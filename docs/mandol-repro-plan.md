---
title: Mandol 论文↔MCP 三层复现方案
status: 待执行（等 wafo 确认）
created: 2026-08-31
决策来源: 2026-08-31 grilling 会话，Q1–Q12 全部收敛
---

# Mandol 论文 ↔ MCP 三层复现方案

> [!abstract] 一句话
> 当前 `servers/mandol` 只接了 `SemanticGraph`/`SemanticMap` 裸 dense kNN，绕过了 Mandol 全部三大机制。本方案按**重灌代价**分三层，用 3-conv 迭代 + 全量定稿，把 mandol arm 从"裸检索面"补到"完整管线"，使其分数可与 mem0/graphiti 同表横比。

## 0. 目标与边界

| 项 | 结论 |
|---|---|
| 目标 | **评测公平性**——让 mandol 的分数代表其论文机制 |
| 验收线 | **完整管线**（不含 router，因其在论文主结果配置下即恒等映射） |
| 明确排除 | 复现 92.21% 这个数字本身 |

> [!warning] 为什么不追 92.21%
> 三重阻断：① 论文构建侧用 `qwen-3.5-plus-thinking` + `deepseek-v3.2-dashscope`，本项目契约 §7 要求统一 `glm-5.3/temp=0/effort=low`；② 论文答题/判分是 GPT 系；③ 论文答题 prompt 注入数据集 gold category（见 §5）。
> 用新模型复现是**正确做法**——控制变量是"全 arm 同一模型"，与 mem0/graphiti 保持可比性，而不是复刻论文的旧模型。

## 1. 已锁定决策

| # | 决策 | 选择 |
|---|---|---|
| Q1 | 目标 | 评测公平性；验收线＝完整管线 |
| Q2 | 三层分界 | **按重灌代价划**（见 §2） |
| Q3 | 对照口径 | 先 3-conv 迭代，最后全量进主表 |
| Q4 | router | **不接**（主结果配置下恒等） |
| Q5 | 复现方式 | **混合**：官方 prompt 常量 + 本项目编排/持久化/LLM client |
| Q6 | P1-step1 God Mode | **保持官方实现，不优化** |
| Q7 | 图架构 | **改 per-conversation 图**（官方原貌） |
| Q8 | 断点续跑 | 补到 **conversation 粒度** |
| Q9 | 分级 | 3-conv 先行，再 resume 全量 |
| Q10 | 考试次数 | **3 次**（基线／Phase 2 后／Phase 3 后），消融在 3-conv 尺度 |
| Q11 | L1 类型 | **`locomo_types() = [STRUCTURED]`** |
| Q12 | 全量考试 | **仅终态 1 次** |

## 2. 三层分界口径（按重灌代价）

```text
Phase 1 存储层 = 改了必须重灌的
                 dense/sparse 向量、unit 结构、metadata、memory space、图架构
Phase 2 构建层 = 要跑 LLM 才能产出的
                 L1 摘要、事件链、实体关系图，及其向量
Phase 3 检索层 = 纯查询期、不用重灌的
                 BM25/SPLADE 倒排、RRF、图扩展、cross-encoder、级联剪枝
```

> [!note] 与论文 §3.2 的一处出入
> 论文把三索引（倒排/dense/sparse）都归在 SemanticMap。代码里**向量**（`MemoryUnit.embedding` / `sparse_embedding`）确实都在 SemanticMap 且由它生成，但**倒排表**在 `retrieval/`。作者的切分线是"向量＝单元属性，倒排表＝语料级派生结构"，理由是可加性、依赖成本（SPLADE 需本地模型）、以及倒排表可从 unit 廉价重建。本方案采用重灌代价口径，此出入在 diff 结论中单独记一条。

## 3. 三层 diff 现状

### Phase 1 存储层

| 维度 | 官方 main | 当前 MCP | 动作 |
|---|---|---|---|
| unit 粒度 / space 隔离 | turn 级 / MemorySpace | 同 | ✅ 无需改 |
| 文本字段 | `message`（走 fallback 链） | `text_content`（直接命中 `DEFAULT_TEXT_EMBEDDING_KEY`） | ✅ 无需改 |
| **图架构** | **每 conv 独立 SemanticGraph** | 单一全局 `_G` | ❌ 改 |
| **sparse 向量** | `generate_sparse_embedding=True` | 显式传 `False` | ❌ 改（需模型 + 重灌） |
| `message_index` | metadata 有 | 无 | ❌ 补 |

### Phase 2 构建层

| 塔 | 官方 pipeline | 当前 MCP |
|---|---|---|
| hierarchical | `step1_generate_l0_graph` → `step2_extract_l1` | ❌ 仅 L0，无 L1 |
| episodic | `step1_extract_facts` → `step2_dedup_enhance` → `step3_load` | ❌ 未建 |
| KG | `step1_entity_extract` → `step2_relation_gen` → `step3_graph_batch` | ❌ 未建 |

当前实测 **5882 nodes / 0 EDGES**——显式边在 KG 塔 step3 建，一条 pipeline 都没跑。

### Phase 3 检索层

| 机制 | 官方 | 当前 MCP |
|---|---|---|
| 三路召回 BM25+SPLADE+dense | `build_all_indexes([BM25, COSINE, SPLADE])` | ❌ 仅 dense |
| RRF 融合 | `score_fusion` | ❌ |
| 图扩展 | `graph_context_expander` | ❌ |
| cross-encoder | `bge-reranker-v2-m3` | ❌ |
| 级联剪枝 Eq.(1)(2)(3) | `cascade_pruner` 三 stage | ❌ |
| router | 恒等映射 | ❌（按 Q4 不接，与官方行为一致） |

## 4. 执行序列

### Phase 1 · 存储层

**动作**

1. `_G` → `dict[scope_id, SemanticGraph]`，每 conv 独立落盘目录
2. `snapshot`/`restore`/`reset` 按 scope 遍历
3. `add_unit(generate_sparse_embedding=True)`，下 `naver/splade-v3`
4. metadata 补 `message_index`

**验收断言**

- [ ] 契约 §10 smoke test 六步全绿
- [ ] `stats().n_memories` ＝ 各 scope 之和
- [ ] 任取一 unit，`sparse_embedding` 非空
- [ ] 3 个 conv 的图目录物理隔离，各自可独立 `load_graph`
- [ ] **不单独考试**——sparse 向量此时无人消费，per-conv 图不改变 dense 结果，无可观测效果

### Phase 2 · 构建层

**动作**

复用官方 prompt 常量，编排用本项目 LLM client（`glm-5.3`/`temp=0`/`effort=low`）：

| prompt 常量 | 出处 |
|---|---|
| `CONTEXTUAL_RETRIEVAL_PROMPT` | `step1_generate_l0_graph.py:29` |
| `L1_STRUCTURED_EXTRACTION_PROMPT` | `hierarchical_prompts.py:152` |
| `EPISODIC_EXTRACTION_PROMPT` | `step1_extract_episodic_facts.py:100` |
| `LLM_DEDUP_PROMPT` | `step2_deduplicate_and_enhance.py:144` |
| `entity_extraction` / `entity_deduplication` | `step1_locomo_entity_extractor.py:145,193` |
| `relation_extraction` / `cross_session_relation_extraction` | `step2_locomo_relation_generator.py:86,141` |

触发点：**ingest 全部完成后、`snapshot` 之前**（`runner.py` Phase A 本就是批量灌完再 snapshot，无在线增量需求）。断点续跑做到 conversation 粒度。

**验收断言**

- [ ] 3 conv × 3 塔 ＝ 9 个图目录，各自非空
- [ ] hierarchical 塔有 L0/L1 两级，L1 的 `source_unit_uids` 指向真实存在的 L0 uid
- [ ] **KG 塔边数 > 0**（对 `0 EDGES` 的直接修复验证）
- [ ] episodic 塔有时序事件链
- [ ] LLM 调用数量级与预估一致（3-conv 约 2,088 次）
- [ ] 考试 1 次（3-conv）

### Phase 3 · 检索层

**动作**

1. 每塔 `MultiRetriever` + `build_all_indexes([BM25, COSINE_SIMILARITY, SPLADE])`
2. RRF 融合 → 选择性图扩展 → `bge-reranker-v2-m3` 重排
3. `CascadeConfidencePruner`：`mad_multiplier=2.5`、`tower_priority` 1.0/0.8/0.6、`lambda_mmr=0.6`，三 stage 默认全开
4. 三塔固定预算 `H=15 / G_sim=30 / E=30 / final_k=20`（`final_k` 与契约 `top_k=20` 一致）
5. 不接 router

**验收断言**

- [ ] BM25／SPLADE／dense 三路各自返回非空候选（可分别断言）
- [ ] `CascadePruner` 三 stage 诊断计数非零（stage1 剔除数、stage2 冲突数、stage3 多样性惩罚数）
- [ ] envelope 字段齐全、`text ≤ 600` 字符（契约 §4/§10）
- [ ] 考试 1 次（3-conv）→ resume 补建 7 conv → 考试 1 次（全量，进主表）

## 5. 必须写进论文的诚实性声明

- **router**：其论文主结果配置（GPT-4.1-mini）的路由表本身即恒等映射（`GPT_41_MINI_ROUTING_AGGRESSIVE` 与 `_CONSERVATIVE` 五类问题全部映射到 `_cfg_full()`），本复现实现了该配置的实际行为，而非省略了某个机制。
- **gold label**：其复现代码在**答题 prompt** 注入数据集 gold category 及针对性提示（`locomo_triple_router.py:2147-2149`），本复现不含此注入——答题 prompt 为本项目全 arm 统一。
- **emotional memory**：论文 §3.1 声称四类记忆源，但其官方 LoCoMo 复现路径（`locomo_types() = [STRUCTURED]`）只构建三塔，emotional 从不构建，无实验支撑。
- **模型口径**：构建侧统一 `glm-5.3`，与论文的 `qwen-3.5-plus-thinking` + `deepseek-v3.2-dashscope` 不同；本复现数字不应与论文 92.21% 并列比较。
- **旧数据**：`locomo-r1` 的 mandol 0.294 为 3-conv / `top_k=5` / `qwen38-27b-nvfp4` 判分，与新口径三维皆不同，不可混表。
- **级联剪枝参数与论文不一致**：论文 Eq.(1) 与代码默认为 κ=2.5 / λ=0.6 / `BUDGET_MAX`，
  但官方主复现脚本 `run_reproduction_suite.sh` 实际传 `mad_multiplier=3.0, lambda_mmr=0.7, STRICT_THRESHOLD, absolute_min_score=-5.0`。
  本复现**采用脚本值**（以可复现的实验配置为准），需在论文中声明该不一致。
- **重排 dtype 偏离**：cross-encoder 从官方硬编码的 `bfloat16` 改为 `float32`。
  原因是 bf16 在 CPU 上无原生指令（125 vs 18 ms/对）；fp32 精度更高，不存在质量损失。属硬件适配而非机制改动。
- **episodic / kg 塔零显式边**：溯源边跨图指向 base 图的 L0 单元，`add_relationship` 静默返回 False。
  已改存 `metadata.source_unit_uids`。因主路径 `topk_graph=0` 不做图遍历，不影响分数，但不应声称「已建完整事件图」。

> [!important] 需修正 WEEKEND-PLAN 的一条记录
> L459 附近"Category Router 按题型选策略 → 别抄，消费数据集 gold label"——方向对但**定位错**。router 在主结果配置下恒等，真正消费 gold label 的是答题 prompt 注入。建议改写该条。

## 6. 时间预算

锚点：`locomo-r2-n3` 实测 14h39m / 约 35,748 次调用 / `concurrency=10` / 智谱端点 → **约 0.68 次调用/秒**。

| 阶段 | 调用数 | 估计墙钟 |
|---|---|---|
| 3-conv 构建 | 2,088 | ~50 min |
| 3-conv 考试 × 3 | 3,348 × 3 | ~4.2 h |
| resume 补建 7 conv | 6,265 | ~2.6 h |
| 全量考试 × 1 | 11,916 | ~4.9 h |
| **合计** | | **~12.6 h** |

## 7. 风险与未验证项

> [!warning] 未验证，需实跑校准
> - 每 session 实体数／事实数（成本估算按 25 假设，代码无法确定）
> - DBSCAN 实际簇结构（参数自动调优，簇数不可预测）
> - 智谱 RPM 限流对**构建侧**吞吐的影响（锚点取自答题侧，端点不同：`/api/anthropic` vs `/api/coding/paas/v4`）
> - `naver/splade-v3`（约 500MB？）与 `bge-reranker-v2-m3`（约 2.3GB？）的**实际下载体积未核实**
> - `step1_generate_l0_graph.py:604` 的 `max_tokens=250` 在非 thinking 模型下是否够用

**已知坑**

- 官方三条 pipeline **零断点续跑**，`locomo_episodic_memory/step2` 与 `step3` 连 `--sample-ids` 都没有，中途失败只能挪文件
- 官方 `locomo_episodic_memory/scripts/step1.sh:37` 传的 `deepseek-reasoner` 不在 `MODEL_CONFIGS` 白名单，直接跑会抛 `ValueError`——不要假设照抄脚本能跑
- 采用 Q5 混合方案后**不碰 Mandol 的 `configs.py` 白名单**，用本项目 LLM client，此坑自动规避
- 本方案破坏当前 mandol server 的"全云端、不拉 HF 模型"设计（SPLADE 与 cross-encoder 都需本地模型），需在 §7 逐系统配置清单中更新该 arm 的偏离声明

**已定实现细节**

- 3-conv 选 **`conv-26/30/49`**（与 `amem-ab-3conv` 同表）。实测规模 63 session / 1,297 turn ＝ 全量的 **22.1%**（全量 272 session / 5,882 turn），构建约 1,870 次调用 ≈ 46 min

## 9. Phase 1 执行记录（2026-08-31）

### 已完成

改动全部收在 `servers/mandol/server.py`（`BaseState.snapshot` 拷贝整个 `state_dir`，子目录自动包含，快照逻辑无需改造）：

- `_G`（单例）→ `_GRAPHS: dict[scope_id, SemanticGraph]`，每 conv 落盘 `state_dir/graphs/<scope_id>/`
- `_get_graph(scope_id)` 惰性加载；`_persist()` 遍历落盘；`restore` 逐 scope 验证可加载
- `generate_sparse_embedding=SPARSE_ON`（环变量 `MEMBENCH_MANDOL_SPARSE` 可回退）
- metadata 补 `message_index`

**验收：contract smoke test 8/8 全绿**（干净状态下）。关键三条：retrieve 3 条、restore 后 id 集合一致、双 scope 零泄漏。

> [!bug] 首次跑 7/8 的真实原因：脏状态，非重构 bug
> `scopes.json` 跨 run 累加，只有 `reset` 才清。旧 run 遗留的 scope_id 排在前面，而 `retrieve` 无 filter 时取 `scope_ids[0]` → 指向不存在的图目录 → 新建空图 → 0 条。
> 旧单图代码同样用 `scope_ids[0]`（只是拿来做 `ms_names` 过滤），在脏状态下同样会返回 0——只是之前没人在脏状态下跑过。清 `.state/mandol` 后 8/8。

### 已解决：SPLADE 模型是 gated repo

`naver/splade-v3` 需 HF 鉴权。已在模型页接受条款 + 生成 Read 类型经典 token 写入 `.env` 的 `HF_TOKEN`（`.env` 已在 `.gitignore:21`）。直连验证 HTTP 200 / `architectures: [BertForMaskedLM]`。

备选（未启用，已验证非 gated）：`naver/splade-cocondenser-ensembledistil`、`prithivida/Splade_PP_en_v1`。

> [!danger] 已修：token 拿到也传不进去的坑
> `smoke_test.py` 与 `runner.py` 的子进程环境白名单只转发 `MEMBENCH_` / `SILICONFLOW_` / `OPENAI_`，**`HF_TOKEN` 不在内**。已补 `HF_` / `HUGGING_FACE_`（`runner.py:87`、`smoke_test.py:93`）。

### 阻塞二：OpenMP 双副本导致 SIGSEGV（启用 SPLADE 后才暴露）

SPLADE 一启用，server 在检索阶段**静默段错误**，MCP 侧只看到 `Connection closed`。macOS crash report 定性：

```text
SIGSEGV / KERN_INVALID_ADDRESS at 0x580
  libomp.dylib  __kmp_suspend_initialize_thread
  libomp.dylib  __kmp_suspend_64 → kmp_flag_64::wait → __kmp_hyper_barrier_release
  libomp.dylib  __kmp_fork_barrier → __kmp_launch_thread → __kmp_launch_worker
```

**根因**：`.venv-mandol` 里共存三份 `libomp.dylib`（torch 720K / sklearn 664K / faiss 740K）。torch 链 `@rpath/libomp.dylib`、faiss 链 `@loader_path/.dylibs/libomp.dylib`，install name 不同故 dyld 当两个库加载；但 OpenMP 运行时是全局单例语义，两份抢同一套线程池元数据 → worker 线程 barrier 处崩溃。

**实测矩阵**（按 server 真实导入序列，含 fastmcp + mandol）：

| 手段 | 结果 |
|---|---|
| 裸跑 | ❌ OMP Error #15（加载期 abort） |
| `OMP_NUM_THREADS=1` 单用 | ❌ 仍 OMP Error #15 |
| `KMP_DUPLICATE_LIB_OK=TRUE` 单用 | ❌ 过加载，检索时段错误 |
| KMP + `faiss.omp_set_num_threads(1)` | ⚠️ 可跑，但 faiss 降为单线程 |
| KMP + `OMP_NUM_THREADS=1` | ⚠️ 可跑，但 torch 也降为单线程（**污染 Search 延迟指标**） |
| **各份 libomp → 符号链接到 torch 那份** | ✅ **torch=12 / faiss=12，无需任何降级** |

**处置**：`scripts/fix_mandol_openmp.sh`（幂等、带备份、自带验证）。`server.py` 启动时 `_assert_single_libomp()` 自检，失效则快速报错并指向修复脚本——把神秘段错误变成可操作提示。

#### 第三份：sklearn（Phase 2 的雷，已提前拆）

用 dyld 接口实数发现，只收 faiss 那份后进程内**仍有 2 份** libomp：

```text
仅修 faiss : 2 份  (torch + sklearn)     ← 当时未崩只因 sklearn 路径未被走到
全量修复 : 1 份  (torch)              ← 真正的根因消除
```

mandol 的 `cluster/dbscan_method.py` 用 `sklearn.cluster.DBSCAN`，**正是 Phase 2 实体/事实去重要走的路径**，不提前收会在 Phase 2 复现同类崩溃。三份均为 LLVM OMP 5.0.20140926 / arm64，ABI 一致。

已验证 Phase 2 真实场景（SPLADE 前向 → DBSCAN 聚类 → 30 次 FAISS 检索 → DBSCAN与SPLADE 交错）全通过。

> [!warning] 重装 torch / faiss-cpu / scikit-learn 会冲掉符号链接
> 需重跑 `bash scripts/fix_mandol_openmp.sh`（退出码非 0 即表示未收拢到 1 份）。
> Phase 3 接 `bge-reranker-v2-m3`（同样走 torch）时此问题仍适用。

> [!danger] 已修：token 拿到也传不进去的坑
> `smoke_test.py` 与 `runner.py` 的子进程环境白名单只转发 `MEMBENCH_` / `SILICONFLOW_` / `OPENAI_` 三个前缀，**`HF_TOKEN` 不在内**。即使写进 `.env`，server 子进程也拿不到 → 依旧 401 静默降级。
> 已补 `HF_` / `HUGGING_FACE_` 到两处白名单（`runner.py:87`、`smoke_test.py:93`）。

### 降级可见性（新增）

SPLADE 失败只在 stderr 刷日志，run 产物里看不出——正是 mem0 dead code / graphiti 渲染 bug 那类静默降级。已对齐 mem0 arm 的 `channels.bm25.enabled` 报告惯例，逐 unit 实测并记入 `stats()`：

```json
"mandol": {
  "n_scopes": 3,
  "sparse": {"requested": true, "attempted": 1297, "generated": 0, "code": "splade_unavailable"}
}
```

`code` 取值：`ok` / `disabled` / `splade_unavailable` / `partial` / `no_data`。

### 附带修复：spaCy 装错环境

BM25 自动下载 `en_core_web_lg` 后报 `E050 Can't find model`，降级为 regex 分词（缺词形还原，直接影响 BM25 召回）。实测两个 venv 都没装上。

**根因**：`.venv-mandol` 是 uv 建的，**没有 pip**（`No module named pip`），而 `python -m spacy download` 内部调 pip → 挂死。官方自动下载走的 uv 又把包装到了别处（报 "Audited 1 package"）。

**正确装法**（spaCy 3.8.14 → 模型 3.8.0）：

```bash
uv pip install --python .venv-mandol/bin/python \
  "https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.8.0/en_core_web_lg-3.8.0-py3-none-any.whl"
```

已验证：`pipes: ['tok2vec','tagger','parser','attribute_ruler','lemmatizer','ner']`，重跑 smoke test 后 regex 降级计数归 0。

### Phase 1 验收状态

| 断言 | 结果 |
|---|---|
| 契约 §10 smoke test 全绿 | ✅ 8/8 |
| 各 conv 图物理隔离、可独立 load | ✅ `n_scopes` 实测 + 步骤 5/8 |
| `stats().n_memories` 跨 scope 求和 | ✅ |
| 任取一 unit，`sparse_embedding` 非空 | ✅ `generated == attempted`，`code: ok` |

实测 `stats().mandol` 输出：

```json
{"n_scopes": 2, "sparse": {"requested": true, "attempted": 2, "generated": 2, "code": "ok"}}
```

日志侧交叉确认：`SPLADE incremental attach: added N documents, vocab=...` 出现 7 次；gated / 跳过 sparse / OMP Error / 段错误 / BM25 regex 降级 均为 **0**。

**Phase 1 完成。** 存储层已对齐官方：per-conv 独立图 + dense/sparse 双向量 + message_index。

## 10. Phase 2 执行记录（2026-09-01）

### 代码资产

```text
scripts/gen_mandol_prompts.py    从官方 dataset_maker AST 提取 prompt（非手抄）
scripts/build_mandol_towers.py   在已 ingest 状态上触发构建，免重灌
servers/mandol/towers/
  prompts.py       10 个官方 prompt，**逐字节回验 10/10 一致**
  llm.py           契约 §7 配置（glm-5.3 / temp=0 / effort=low）+ 429 退避 + JSON 解析
  hierarchical.py  L0 上下文改写 → L1 结构化 → L2 聚合
  episodic.py      事实抽取 → DBSCAN 聚类 → 逐簇 LLM 去重
  kg.py            实体抽取 → 去重 → 会话内/跨会话关系
  load.py          step4 等价：text_content 覆盖 + 建显式边
  orchestrator.py  编排 + conv 粒度断点
```

### prompt 移植：AST 提取而非手抄

10 个 prompt 单个 1.3k–4.3k 字符，手抄错一个字符会静默改变抽取行为且无断言可捕。
其中 4 个是**方法内局部变量或 return 字面量**（graph_maker），grep 直接抄会漏。

> [!note] 两份等价副本
> `src/mandol/auto_builder/hierarchical_prompts.py` 有一份内容等价的 L1 prompt，
> 但那是**运行时 auto_builder 路径**（string.Template 语法）。复现路径用 dataset_maker 版。
> 已做规范化比对：除 `{{` / `{` 转义差异外完全一致。

### 契约冲突：temperature

官方构建侧用 `temperature=0.1`（实体去重 0.05），契约 §7 要求统一 `0`。
**采用契约值 0**，依据是项目已有先例——amem server 同样把官方默认 0.7 强制改为 0 并声明违约。
其余保持官方：`max_tokens` 逐步不同（L0=250 / L1=4000 / L2=8000）、`max_retries=3`、JSON 围栏剥离。
**此项需写入论文声明。**

### 最易踩空的数据流（已处理）

L0 那笔最大的 token 开销产出 `indexing_text`，**在 step1 不进 MemoryUnit**（step1:424 只传 raw_data/metadata），
要到 step4:360 才 `raw_data['text_content'] = indexing_text`。漏掉这次覆盖 → 烧完全部 token 却仍用原文做 embedding，且完全静默。

### 3-conv 构建实测（conv-26/30/49）

| conv | LLM 调用 | in / out | 失败 | 耗时 |
|---|---:|---|---:|---:|
| conv-26 | 588 | 840,480 / 222,672 | 0 | 762s |
| conv-30 | 512 | 652,897 / 199,356 | 1 | 1,060s |
| conv-49 | 721 | 949,692 / 272,814 | 0 | 1,306s |
| **合计** | **1,821** | **2.44M / 0.70M** | **1** | **3,133s** |

估算对照：预估 1,872 次 / 3.75M tok → **调用数准到 97%**，token 偏保守 16%。

产物：

```text
hierarchical  L0 覆盖 1,290 · 时序边 1,227 · 抽象 66 单元 · 溯源边 1,353
episodic      501 事实 · 24,233 溯源边
kg            832 实体 · 28,199 边 · 1,524 关系
```

**从 `0 EDGES` 到五万多条边**——这是对 memory-bench 实测 `5882 nodes / 0 EDGES` 的直接修复。

### 踩过的坑

1. **陈旧 scope 污染**：`ingest_system` 在 pending 非空时也先 `restore(locomo_full)`，
   而 `rm -rf .state/mandol` 不清 `.state/__snapshots__/`，导致旧快照带回 10 个 scope_id（其中 7 个是 28K 空壳）。
   不清理会对空 scope 也建塔，且 `n_units: 7179` 陈旧值会写进 `system_stats.jsonl`。
2. **`--resume` 不建子目录**：`Run.__init__` 只在 `not resume` 分支建 `evidence/`。
   手动预建 run 目录（为了复制 progress 走 restore 分支）时必须一并建 `evidence/`。
3. **避免重灌**：新 run 如果 progress 为空会重新 ingest，**把增强后的 L0 覆盖回原文**，
   白烧 52 分钟。做法：复制上一个 run 的 `ingest_progress/progress.json` → pending 为空 → 走 restore。

## 12. Phase 3 执行记录（2026-09-01）

### 代码资产

| 文件 | 作用 |
|---|---|
| `servers/mandol/towers/retrieve.py` | 三塔并行检索 → RRF → 重排 → `CascadeConfidencePruner` → 去重截断 |
| `servers/mandol/server.py` | `TRITOWER_ON`（env `MEMBENCH_MANDOL_TRITOWER`，默认关），命中返回 `raw_format="mandol_tritower"` |
| `scripts/migrate_tower_spaces.py` | 补挂官方规范 space 名（零 LLM、零重嵌入） |
| `scripts/migrate_l1l2_text.py` | L1/L2 检索文本从 JSON dump 改写为展平语句 |
| `scripts/run_mandol_p3.sh` | 考试启动脚本，含三条前置校验说明 |

### 官方路径考证

`TripleTowerRetriever` 只接单个 graph，不适用；论文复现路径是 `benchmark_locomo/task_eval/locomo_triple_router.py`——自管三图 + 三个 `MultiRetriever`。
hierarchical 走 `HierarchicalRetriever.search(top_k=15)`，kg 与 episodic 走 `MultiRetriever.smart_search(methods=[bm25, cosine_similarity, splade], fusion_method="rrf", rerank_method=baai)`。
`_cfg_full` 中 `use_entity_relation=False`、`topk_graph=0` → **主路径不做图遍历**，三塔全为语义检索。

### 修复一：memory space 名不规范

Phase 2 首版 `load.py` 用了自造名 `"L0"/"L1"/"L2"/"episodic"/"kg"`，而 `HierarchicalRetriever.LAYER_TO_SPACE`
按 `TowerSpace` 规范名分层检索（`hierarchical_memory:L0_Observation` 等），**名字不对就一条都检不到**。
`migrate_tower_spaces.py` 用 `add_unit_to_space_in_map` 补挂 2,689 个单元。

### 修复二：边数汇报错误（自查纠正）

`graph.add_relationship` 目标节点缺失时**返回 False 而非抛异常**（`semantic_graph.py:648` 仅记 ERROR 日志），
而 `_link_sources` 只捕异常 → 把「调用次数」当成了「建边数」。

真实边数：base(hierarchical) **838 边/conv 有效**；episodic、kg **各 0 边**——溯源边跨图指向 base 图的 L0 单元，静默失败。
此前「五万多条边」的说法作废。已修 `load.py`：所有 `add_relationship` 检查返回值，跨图溯源改存 `metadata.source_unit_uids`。
因主路径 `topk_graph=0`，不影响分数。

### 修复三：检索延迟 146s → 11s

首次冒烟 **146 秒/查询**，1500 次要 60 小时。分塔计时定位（不是靠猜）：

```text
hierarchical 93.3s · episodic 21.4s · kg 8.7s
```

试过两条错误假设，都被数据否掉：加检索器缓存（无效，122s→102s）、疑心 space 过滤（无效，直接调 `smart_search` 带 space 过滤只要 0.3s）。
真因是 **cross-encoder 的 dtype**——`rerank_manager.py:462` 无条件 `torch_dtype=torch.bfloat16`，
device 那行也只有 `cuda`／`cpu` 两个分支。这套默认值是为 H800 写的；macOS 上落到 CPU+bf16，
而 **bf16 在 CPU 上没有原生指令，靠软件模拟**：

```text
CPU / bfloat16（原样）  125 ms/对
CPU / float32            18 ms/对   ← 采用
MPS / float32            14 ms/对
MPS / float16             8 ms/对
```

> [!note] 这不是拿精度换速度
> fp32 尾数 23 位、bf16 只有 8 位，改完**又快又更准**。属于硬件适配，不改算法、不改候选集，
> 因此不违反「保持官方实现不优化」（Q6）——该约束针对的是 Mandol 的机制，不是它对 CUDA 的硬编码假设。
> 实现见 `retrieve.py:_patch_reranker_dtype()`，env `MEMBENCH_MANDOL_RERANK_DTYPE` 可调。

第二个乘数：L1 层仅 19 个候选却占 37s，因为 Phase 2 把整个抽取结果 `json.dumps` 当检索文本存了。
键名与转义既稀释语义信号，又把单条文本拉长约 15 倍，而 cross-encoder 按序列长度平方级付费。
`_flatten_extraction()` 展平后平均 **4400 → 1230 字符**。

**顺带发现的静默缺陷**：迁移后 BM25 索引 `docs 419 → 439`、`vocab 969 → 1460`——
那 20 个 L1/L2 单元**此前从未进过 BM25 倒排**（JSON 文本被分词器打碎）。等于修好了一路稀疏召回。

修复后三塔：`hierarchical 7.8s · episodic 2.7s · kg 1.5s`，端到端实测均值 **11.1s/查询**。

### 修复四：级联剪枝 stage 2 结构性失效

考试跑到 31% 时发现 `stage2_conflicts` 与 `stage2_dropped` 恒为 0。不是「没检测到冲突」，是**结构上不可能检测到**：

`_stage2_disambiguate` 判冲突只看两个字段，且要求同一 id 出现在**不同塔**：

| 字段 | 首版实现 | 后果 |
|---|---|---|
| `entity_ids` | 只从 `meta.entity_name` 取，而该字段只有 KG 塔有 | 单塔独有 → 永远不跨塔 |
| `source_chunk_ids` | **完全未设** | 默认空列表 |

另有一层：`load.py` 后来补的 `metadata.source_unit_uids` 是在 Phase 2 建图**之后**才加的，
磁盘上 episodic 154 个、kg 280 个单元的该字段**全为空**（实测），重建它需重跑抽取 LLM。

官方（`locomo_triple_router_quantification.py:552-586`）对**三塔均**提取：

```text
graph(KG)   entity_canonical / entity_text / entity_name + target_entity
episodic    entities / entity_ids / involved_entities
其他(L0)    speaker                      ← 用说话人做实体
全塔兜底    NER 专名抽取 ner:xxx
source_chunk_ids = _extract(...) or [chunk_id]    ← 空时兜底为自身 id
```

> [!note] 一个容易看漏的正则细节
> `_RE_PROPER_NOUN = r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b"` 的 `+` 要求**至少两个连续大写词**，
> 单名字 `Caroline` 不匹配。因此 NER 兜底很少产出人名，
> 跨塔冲突实际主要由「KG 实体 caroline ↔ L0 说话人 caroline」触发。

已照官方逐句移植为 `_fallback_entities()` / `_entity_ids()`，置于 env `MEMBENCH_MANDOL_CASCADE_IDS` 后（**默认关**，
以免影响当时正在进行的 run）。单查询实测：

```text
OFF   stage2 冲突=0 丢弃=0 · stage3 惩罚=669 · tokens 2873
ON    stage2 冲突=2 丢弃=2 · stage3 惩罚=690 · tokens 2861
```

影响不止 stage 2：同一批字段还喂给 stage 3 的多样性惩罚（`entity_penalty=0.15` / `source_penalty=0.2`）。

**实验安排**（用户 09-01 定）：`mandol-p3-retrieval-3conv` 保留为**stage2 消融组**（级联仅 stage1+3），
修复后再跑一次作为**完整管线组**，两个数字均入档。

### 踩过的坑（Phase 3 新增）

1. **陈旧快照会静默抹掉迁移成果**——`BaseState.restore` 是 `rmtree(state_dir)` + `copytree(快照)` **全量替换**。
   `ingest_system` 在 pending 为空时必走 restore；若快照早于迁移，space 迁移与 L1/L2 重建会被无声回滚，
   拿到一份「看起来正常、实际是旧状态」的结果。**启动前必须用当前状态刷新快照**，
   并用 `diff -rq .state/mandol .state/__snapshots__/mandol/locomo_full` 确认一致。
   注意别直接调 `snapshot()` 工具——它在 `TOWERS_ON` 时会先跑 `_build_towers()`。
2. **检索阶段完全串行**：`evidence_for_arm` 是 `for conv / for qi / for rep` 逐个 await，无并发。
   3 个 rep 的检索链路全程确定性（BM25/SPLADE/dense/rerank 均无采样），
   **三次结果逐字节相同**，理论上可省 2/3 时间；但 `runner.py` 为全 arm 共用，
   只给 mandol 加缓存会让 latency 列失去可比性，故不改。
3. **可见终端会折断长命令**：内联长命令被回显折行破坏引号（卡在 `dquote>`），改用 `scripts/run_mandol_p3.sh`。

## 11. 实验结果

### 基线（Phase 1 态，`mandol-p1-baseline-3conv`）

口径：conv-26/30/49 · top_k=20 · glm-5.3 答题与判分 · n=3 · 500 题

```text
总体  632/1493 = 0.4233        平均 F1 0.2469
cat1 multi-hop    0.236
cat2 temporal     0.615
cat3 open-domain  0.359
cat4 single-hop   0.623
cat5 adversarial  0.072      ← 与 WEEKEND-PLAN 记录的“全臂 ~3%，协议层问题”一致
rep 方差  0.4177 / 0.4277 / 0.4245   ← n=3 稳定
```

> [!warning] 不可与旧数字混表
> `locomo-r1` 的 mandol 0.294 是 3-conv（conv-30/41/42）/ top_k=5 / qwen38-27b 判分，三个维度全不同。

### Phase 2（三塔构建后，`mandol-p2-towers-3conv`）

同口径。注意本次只能测出 **hierarchical 塔的贡献**（L0 增强文本 + L1/L2 进基础图）——
episodic 与 kg 在独立图里，当前 `retrieve` 不会触及，要等 Phase 3 接三塔检索才生效。

| 指标 | 基线 (P1) | 三塔 (P2) | Δ |
|---|---:|---:|---:|
| **总体准确率** | **0.4233** | **0.5696** | **+0.1463** |
| 平均 F1 | 0.2469 | 0.2638 | +0.0169 |
| cat1 multi-hop | 0.236 | 0.485 | **+0.249** |
| cat2 temporal | 0.615 | 0.791 | +0.176 |
| cat3 open-domain | 0.359 | 0.442 | +0.083 |
| cat4 single-hop | 0.623 | 0.809 | +0.186 |
| cat5 adversarial | 0.072 | 0.066 | −0.006 |

rep 方差 0.5674 / 0.5795 / 0.5620——**增益远大于噪声**。

解读：

- **多跳题翻倍（0.236 → 0.485）是最强信号**。L0 逐句上下文改写（官方注释自称 "God Mode"、占输入 ~70%）
  把“你那个支持小组怎么样？”这类离开上下文就无法检索的句子，变成自包含的可检索单元。
  这直接支持了 Q6“保持官方实现不优化”的决定——如果当时为省 token 改成批量重写，现在无法区分
  “增益本来就这么大”还是“被我们的优化损伤了”。
- **cat5 对抗题纹丝不动（−0.006）**，与 WEEKEND-PLAN “全臂 ~3%，答题器不拒答 + judge 严格的协议层问题”
  完全吻合。这条对照反向证实了该判断：**它确实不是记忆系统能解决的**。

### Phase 3 stage2 消融组（`mandol-p3-retrieval-3conv`，2026-09-01）

口径同上。级联剪枝仅 stage1+3 生效（stage2 因 id 字段未填而结构性失效，见 §12 修复四）。

```text
                       P1 基线    P2 三塔   P3 检索    Δ(P2→P3)
总体准确率              0.4233    0.5696    0.5901    +0.0205
平均 F1                0.2469    0.2638    0.2851    +0.0213

cat1 multi-hop          0.236     0.485     0.565    +0.079    (n=239)
cat3 open-domain        0.359     0.442     0.506    +0.065    (n=77)
cat5 adversarial        0.072     0.066     0.081    +0.015    (n=332)
cat2 temporal           0.615     0.791     0.796    +0.006    (n=285)
cat4 single-hop         0.623     0.809     0.809    +0.000    (n=560)

逐 rep：P2 0.5674 / 0.5795 / 0.5620（sd 0.0089）
       P3 0.5792 / 0.5944 / 0.5968（sd 0.0096）
```

解读：

- **检索层增益远小于构建层**（+0.02 vs +0.15）。重活是把对话变成三塔内容干的；
  三路召回 + RRF + 重排是锦上添花。
- 增益集中在**多跳 +0.079 与开放域 +0.065**——正是需要跨源拼装证据的两类。
- **single-hop 完全不动（0.809 → 0.809）**：单跳题 dense 本就能命中，
  加再多召回路径也没有额外信息可捞。这条对照很干净。

> [!warning] 不要对 +0.0205 下重话
> P3 最低的 rep（0.5792）与 P2 最高的（0.5795）几乎贴在一起。
> 双样本 t ≈ 2.7，df=4，**p ≈ 0.05 卡在显著性边缘**。n=3 支撑不起「确定有效」；
> 方向一致但幅度存疑，需全量 10-conv（样本量 3 倍）才能定论。

丢失 7 条（evidence 1500 → answers 1493）：Phase B 答题时 **429 限流退避耗尽**（重试 9 次），
与检索无关；P1 同样丢 7 条（仅 1 条重合），随机非系统性。

### Phase 3 完整管线组（`mandol-p3-full-3conv`，2026-09-02）

`MEMBENCH_MANDOL_CASCADE_IDS=1`，级联剪枝三 stage 全部生效。

```text
                       P1 基线    P2 三塔    P3 消融    P3 完整    消融→完整
总体准确率              0.4233    0.5696    0.5901    0.5952    +0.0051
平均 F1                0.2469    0.2638    0.2851    0.2798    -0.0054

cat1 multi-hop          0.236     0.485     0.565     0.561     -0.004
cat2 temporal           0.615     0.791     0.796     0.822     +0.025
cat3 open-domain        0.359     0.442     0.506     0.500     -0.006
cat4 single-hop         0.623     0.809     0.809     0.817     +0.008
cat5 adversarial        0.072     0.066     0.081     0.073     -0.009

逐 rep  P1 0.4177/0.4277/0.4245 (sd 0.0051)   P2 0.5674/0.5795/0.5620 (sd 0.0089)
        P3消融 0.5792/0.5944/0.5968 (sd 0.0096)  P3完整 0.5924/0.5976/0.5956 (sd 0.0026)
```

#### 结论一：stage2 无可测量贡献（可写入论文的定量否证）

`Δ=+0.0051, t=0.89, df≈4 → p≈0.42`。三条独立佐证：

1. 准确率涨、**F1 反而跌**（+0.0051 / −0.0054），方向矛盾；
2. 五个类别**符号混杂**，不是系统性位移；
3. 证据集差异分解（749 条共同 key）：

```text
完全相同（含顺序）      72   9.6%
集合相同、仅顺序不同    503  67.2%   ← 绝大多数
集合有替换             174  23.2%   （其中 153 条只换 1 条）
平均 Jaccard 重合度 0.9746
```

即 stage2 在 LoCoMo 规模上**主要作用是重排序**。另有一个副作用：30 条（4%）因 stage2 丢弃
而拿到**比消融组更少**的证据（如 20→18、18→16）——丢弃不回填预算，故机制收益非单边。

#### 结论二：Phase 3 整体显著，但远小于构建层

比较口径应用**完整管线**而非消融组：

```text
P2 → P3完整   +0.0256   t≈4.8, df≈4 → p≈0.009   显著
P1 → P2       +0.1463                              构建层是主力
```

完整组 rep 方差明显更小（sd 0.0026 vs 消融组 0.0096），把差异衬托出来。
先前用消融组得到的 p≈0.05 边缘结论应以此为准修正。

### 待做

- resume 补建剩余 7 conv → 全量 10-conv 定稿跑一次进主表（配置用 `CASCADE_IDS=1` 完整管线）
- ⚠️ 全量考试的检索耗时需先评估：10 conv 约 5,000 次检索 × 10s 串行 ≈ **14 小时**。
  因检索链路全程确定性（3 个 rep 结果逐字节相同，已实测），若在 harness 层按
  （conv, qa_id）缓存检索结果，可降至 ~4.7 小时且 evidence 位级一致；
  但该改动影响全 arm 的 latency 口径，需先定。

## 8. 相关文档

- `docs/interface-spec.md` —— 六工具契约、§7 公平性配置、§10 smoke test
- `WEEKEND-PLAN.md` —— 移植优先级表（P1 MAD／P3 L0 双视图）、§9 诚实性护栏
- `docs/REPRO-PLAN.md` —— A/B 档模块划分
- OB 笔记 `2-fleeting/papers/Zhang-et-al-2026-Mandol-An-Agglomerative-Agent-Memory-System-for-Long-Term-Conversations.md` —— 2026-08-30/31 两轮论文↔代码核对记录

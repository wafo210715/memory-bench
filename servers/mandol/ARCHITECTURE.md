# Mandol 臂：完整操作流程与设计取舍（P1/P2/P3 三态）

> 写于 2026-09-04，对应 commit `d0a981b`（构建层）→ `104c530`（检索层）→ `d171fe4`（接入）→
> `c29cdb5`/`4bfcdb7`（3-conv 与全量结果）→ `8aad09b`（主表横比）。
> 移植决策、官方路径考证、踩坑与诚实性声明见 `docs/mandol-repro-plan.md`；
> 跑分见 `wafo-base/.context/memory-bench-r2n3/report-2026-09-04.md`。
> 本文档只回答一个问题：**P1、P2、P3 三态下，每条 query 进来到底走了什么路。**

## 先回答三个常见问题

**P1 的答题是不是类似 RAG？** 是。P1 = 对原始对话逐 turn 单元做 dense kNN，
机制上与 rag_baseline 同类（差异只在存储后端与切分粒度：per-turn MemoryUnit vs chunk）。

**P2 构建了三塔，那答题时怎么用？** 没用上塔的检索设计。P2 的 retrieve 仍是
**单路 dense kNN**（`search_similarity_in_graph`），但被检索的**语料变了**：
L0 的 text_content 已被 God Mode 改写覆盖，图里多了 L1/L2 抽象单元。
episodic/kg 两塔建在独立图里，P2 的检索路径**根本不查它们**。
实测补一刀：P2 的 30,000 条证据里 **100.0% 是 L0 单元**——L1/L2 在图里
但 dense kNN 一次也没检回它们，所以 P1→P2 的 +18.9 全部来自 L0 改写本身。

**P3 是不是就走论文设计的召回了？** 是。三塔并行召回 → 融合 → 重排 → 级联剪枝，
见下方读取侧。

```text
状态   检索算法                检索语料                     查询延迟(中位)  3-conv ALL(1–4)
P1     dense kNN（单路）       原始对话文本                    239 ms        52.4
P2     dense kNN（单路）       改写后的 L0（L1/L2 在图但未被检回） 225 ms       71.3
P3     三塔混合召回+重排+剪枝   上者 + episodic/kg 塔内容      10,199 ms      74.4
```

即：**P2→P3 的 +3.1 是检索算法的增益，P1→P2 的 +18.9 是语料变换的增益**——
同一套 dense kNN，搜改写过的文本比搜原文高 19 个点。

## 写入侧（ingest，`add_conversation`，每 turn 一次）

```text
turn 进入（"user: [2023-05-08] Caroline: ..."）
  │
  ├─ 建 MemoryUnit（uid = {conv}_{session}#{i}）
  │    text_content = 原文；metadata: session_id / message_index / speaker / timestamp
  │
  ├─ dense embedding（embedding-3, 2048 维，云端）
  ├─ sparse embedding（SPLADE，env MEMBENCH_MANDOL_SPARSE，默认开）
  │    BM25 倒排与 SPLADE 倒排随写随增量更新
  │
  └─ 落入 per-conversation 独立图 .state/mandol/graphs/{conv_id}/
       （Q7 决策：已验证独立图不改 dense 结果，hash 逐位一致）
```

写入侧**没有任何 LLM 调用**——mandol 的智能全部在构建侧（离线），
这是它与 amem（写入时逐 turn 两次 LLM）的根本区别。

## 构建侧（`snapshot` 钩子触发，TOWERS_ON=1 时，灌完后一次性）

```text
snapshot(tag) 进入
  │
  ├─ 对每个没有 .done.json marker 的 conv：
  │
  ├─ ① L0 God Mode 改写                [LLM，逐 turn 一次]
  │    原文 → 自包含改写句 + indexing_text
  │    例 "Hey Mel! How have you been?"
  │      → "[Date: 2023-05-08] [Caroline] [Conversation Opening]
  │         Caroline greets Melanie and opens a discussion..."
  │    ★ 载入时 text_content 被 indexing_text 覆盖（原文存 original_text 双视图）——
  │      漏掉这步 = 烧完 token 仍用原文 embedding，完全静默（官方 step4:360）
  │
  ├─ ② L1 会话摘要 / L2 全局聚合         [LLM，每 session / 每 conv]
  │    L1 展平成自然语句入库（不存 JSON dump——既伤语义又拖垮重排，实测教训）
  │
  ├─ ③ episodic 事实抽取                [LLM]
  │    事实 → 独立图 {conv}__episodic
  │
  ├─ ④ kg 实体抽取                      [LLM]
  │    实体 → 独立图 {conv}__kg
  │    ⚠️ 关系边 0 条落地（移植错误四层叠加，见"检索路径上没有什么"）
  │
  └─ marker 落盘 + 全部图 save_graph（断点续跑 = conversation 粒度）

成本实测：3-conv 1,821 次调用 / 244 万 in + 70 万 out；
全量 8,071 次 / 1,111 万 in + 301 万 out / 失败 21。
```

## 读取侧（`retrieve`，每次查询）

```text
query 进入（query_mode=fixed, top_k=20, filter.scope_id=conv）
  │
  ├─ TRITOWER_ON=0（P1/P2 态，默认关）
  │    g.search_similarity_in_graph(query, top_k)
  │    → base 图内 dense kNN，语料视构建侧是否跑过而定（P1 原文 / P2 改写+抽象）
  │    → envelope(text ≤ 600, raw_format=mandol_dense)
  │
  └─ TRITOWER_ON=1（P3 态，env MEMBENCH_MANDOL_TRITOWER）
       三塔并行（ThreadPoolExecutor）：
       │
       ├─ hierarchical 15 条：HierarchicalRetriever
       │    按 L0_Observation / L1_Summary / L2_Insight 三个 memory space 分层检索，
       │    每层内部 = bm25 + cosine + splade → RRF → cross-encoder 重排
       │
       ├─ episodic 30 条：MultiRetriever.smart_search
       │    bm25 + cosine + splade → RRF → 重排
       │
       ├─ kg 30 条：同上（实体语义检索面，无边可走）
       │
       └─ 合并 75 条 → CascadeConfidencePruner（三 stage）
            stage1  MAD 离群剔除（mad=3.0，实测几乎不剔）
            stage2  跨塔冲突去重（KG 实体 caroline ↔ L0 说话人 caroline；
                    抽样 65% 查询 2–4 条；丢弃不回填预算 → 9.3% 查询 <20 条）
            stage3  MMR 多样性打包（λ=0.7，token 预算 cap_to_input）
            → 去重截断 20 条 → envelope(raw_format=mandol_tritower)

重排 dtype 已从官方硬编码 bfloat16 改为 float32（CPU 无 bf16 原生指令，
125→18 ms/对；fp32 精度更高，属硬件适配非机制改动）。
```

参数全部取自官方 `run_reproduction_suite.sh`（产生论文数字的实际配置），
与论文 Eq.(1) 的 κ=2.5/λ=0.6 不一致，以脚本为准。

## 跨进程（快照/恢复）

```text
snapshot: _persist() 落盘 → 整目录拷贝到 __snapshots__/mandol/{tag}
restore : rmtree(state_dir) + copytree(快照) —— 全量替换，不是合并
```

三条由此衍生的纪律（都在真实事故里踩过，详见 repro-plan §12）：

1. 改完图必须刷新快照并 `diff -rq` 校验，否则下一次 restore 会**静默回滚**迁移成果
2. `snapshot()` 在 TOWERS_ON 时会先建塔——ingest 路径的 600s 超时撑不住 2h 建塔，
   建塔必须走 `scripts/build_mandol_towers.py`（timeout=36000）
3. 有 `.done.json` marker 的 conv 一律拒绝重灌——`add_conversation` 同 uid 即覆盖，
   重灌会把 God Mode 改写静默冲回原文

## 检索路径上没有什么

- **图遍历**：`_cfg_full()` 设 `topk_graph=0` / `use_entity_relation=False`，
  官方主复现路径从不走边——这是核实过的代码路径，不是推断
- **知识图谱塔**：实体检索面存在，但 5,208 条抽取关系 0 条落地
  （`_entity_candidates_text` 漏 entity_id 等 four-layer 移植错误）。
  分数不受影响（上图），但不得声称复现了 KG 塔
- **router**：论文主结果配置的路由表是恒等映射（五类问题全部 → `_cfg_full()`），
  不接即等价于全开，非省略机制
- **查询期时间推理**：不排序、不衰减；改写注入的 `[Date: ...]` 前缀是唯一时序信号
  （副作用：答题模型照抄 ISO 日期，词重叠 F1 跨臂失效，judge 不受影响）
- **emotional memory**：官方 LoCoMo 路径从不构建（`locomo_types()=[STRUCTURED]`），
  论文声称四类记忆源只有三类有实验支撑
- **答题 prompt 的 gold 注入**：官方复现代码注入 gold category（locomo_triple_router.py:2147），
  本项目全臂不注入，保持统一

## 设计取舍记录（2026-09-01/02 与 wafo 对齐）

### ① 保持官方实现不优化（Q6）

L0 逐句 God Mode 改写占构建 token 的约 70%，是最贵的一步，没有做批量合并。
事后证明这是对的：多跳 23.6→48.5 的翻倍正来自这步，若当时"优化"掉，
将无法区分"增益本来就这么大"与"被自己的优化损伤了"。

### ② 构建侧 temp=0（官方 0.1）

契约 §7 统一 temp=0 覆盖官方默认。偏离已列入诚实性声明，对四臂公平（mem0 等
同口径），但意味着与官方构建产物的差异不可归因。

### ③ 级联 id 的统一兜底（2026-09-02 决策）

`source_chunk_ids` 统一走官方 `or [chunk_id]` 兜底，不读本项目自加的
`metadata.source_unit_uids`（老 conv 空 / 新 conv 有值，读它会让主表内
逐 conv 行为不一致）。实测跨塔冲突本来就全部来自 entity_ids。
stage2 整体在 LoCoMo 规模无可测量贡献（消融 p≈0.42），作用主要是重排序。

### ④ per-conv 独立图（Q7）

不做跨 conv 共享图。已验证：dense 结果逐位一致、BM25 统计量不变；
换来的是可复现性（全量 vs 独立 3-conv 同 conv 对拍差 0.4pp）。

### ⑤ L1/L2 展平而非 JSON dump

首版存 `json.dumps(抽取结果)`：键名稀释语义 + 文本长 15 倍拖垮 cross-encoder
（L1 仅 19 候选占 37s）。展平后平均 4400→1230 字符，且那 20 个单元
**此前从未进过 BM25 倒排**——等于顺带修好一路稀疏召回。

## 相关

- 实现代码：`servers/mandol/server.py`（MCP 层与环境开关）、
  `servers/mandol/towers/`（prompts/llm/hierarchical/episodic/kg/load/orchestrator/retrieve）、
  `scripts/build_mandol_towers.py`、`scripts/ingest_mandol_full.py`、`scripts/run_mandol_full.sh`
- 决策与考证：`docs/mandol-repro-plan.md`（§3 分层依据、§5 诚实性声明、§9–§14 执行记录）
- 实测结果：`runs/mandol-p1-baseline-3conv` → `mandol-p2-towers-3conv` →
  `mandol-p3-retrieval-3conv`（消融）→ `mandol-p3-full-3conv` → `mandol-full-10conv`

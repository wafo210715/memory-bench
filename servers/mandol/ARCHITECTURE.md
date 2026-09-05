# Mandol 臂：完整操作流程与设计取舍（P1/P2/P3 三态）

> 写于 2026-09-04，对应 commit `d0a981b`（构建层）→ `104c530`（检索层）→ `d171fe4`（接入）→
> `c29cdb5`/`4bfcdb7`（3-conv 与全量结果）→ `8aad09b`（主表横比）。
> 移植决策、官方路径考证、踩坑与诚实性声明见 `docs/mandol-repro-plan.md`；
> 跑分见 `wafo-base/.context/memory-bench-r2n3/report-2026-09-04.md`。
> 本文档只回答一个问题：**P1、P2、P3 三态下，每条 query 进来到底走了什么路。**
>
> **2026-09-05 勘误**：本文已按同目录 `verification.md` 的逐条复核结论修正（共 21 处：10 处事实、0 处行号/锚点、11 处表述限定）。原始未修正版本见 git 历史。

## 先回答三个常见问题

**P1 的答题是不是类似 RAG？** 是。P1 = 对原始对话逐 turn 单元做 dense kNN，
机制上与 rag_baseline 同类（差异只在存储后端与索引实现——两者切分粒度其实相同，都是逐 turn 一条记录）。

**P2 构建了三塔，那答题时怎么用？** 没用上塔的检索设计。P2 的 retrieve 仍是
**单路 dense kNN**（`search_similarity_in_graph`），但被检索的**语料变了**：
L0 的 text_content 已被 God Mode 改写覆盖，图里多了 L1/L2 抽象单元。
episodic/kg 两塔建在独立图里，P2 的检索路径**根本不查它们**。
实测补一刀：P2 的 30,000 条证据里 **100.0% 是 L0 单元**——不是「L1/L2 在图里但排名靠后没检回」，
而是 `retrieve()` 传 `ms_names=[conv_id]` 做硬空间过滤：L1/L2 单元只挂在
`hierarchical_memory:L1_Summary`/`:L2_Insight` 空间，从未加入 conv 自己的 space（`conv-26` 实测 419 个
uid 全是 L0），FAISS 检索前候选集就已经不含它们（`semantic_map.py:2186-2192,2539-2557`）。
这是索引可见性问题，不是排序问题，但结论不变：P1→P2 的 +18.9 全部来自 L0 改写本身。

**P3 是不是就走论文设计的召回了？** 是，但顺序有一处偏差：融合/重排发生在**每塔内部**
（各塔各自 bm25+cosine+splade→RRF→重排），三塔结果**直接拼接**（无跨塔二次融合/重排），
再进级联剪枝。见下方读取侧。

```text
状态   检索算法                检索语料                     查询延迟(中位)  3-conv ALL(1–4)
P1     dense kNN（单路）       原始对话文本                    239 ms        52.4
P2     dense kNN（单路）       改写后的 L0（L1/L2 被 space 过滤排除） 225 ms       71.3
P3     三塔混合召回+重排+剪枝   上者 + episodic/kg 塔内容      10,199 ms      74.4
```

即：**P2→P3 的 +3.1 是检索算法的增益，P1→P2 的 +18.9 是语料变换的增益**——
同一套 dense kNN，搜改写过的文本比搜原文高 19 个点。

## 写入侧（ingest，`add_conversation`，每 turn 一次）

```text
turn 进入（"user: [2023-05-08] Caroline: ..."）
  │
  ├─ 建 MemoryUnit（uid = {conv}_{session}#{i}）
  │    text_content = 原文；metadata: session_id / scope / message_index / timestamp
  │    （speaker 要到构建侧改写时才写入，写入侧本身不含该字段）
  │
  ├─ dense embedding（embedding-3, 2048 维，云端）
  ├─ sparse embedding（SPLADE，env MEMBENCH_MANDOL_SPARSE，默认开）
  │    BM25 倒排与 SPLADE 倒排随写随增量更新
  │
  └─ 落入 per-conversation 独立图 .state/mandol/graphs/{conv_id}/
       （Q7 决策：机制上 dense 检索不受独立图影响——同一批归一化向量、同一候选集；
        未见逐位 hash 对拍的归档记录，「不跨 conv 污染」不等于共享图下 BM25 统计量也不变）
```

写入侧**没有任何 LLM 调用**——mandol 的智能全部在构建侧（离线），
这是它与 amem 的根本区别（amem 写入时逐 turn 调 LLM——仅 memory-bench 自建的 fixed 臂是两次，
官方 native 臂只有一次）。

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
  ├─ ③ episodic 事实抽取                [LLM，含抽取+聚类合并两段]
  │    事实 → 独立图 {conv}__episodic
  │
  ├─ ④ kg 实体抽取                      [LLM，含抽取/去重/会话内关系/跨会话关系四段]
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
  │    → base 图内 dense kNN，语料视构建侧是否跑过而定（P1 原文 / P2 改写后的 L0，
  │       抽象层 L1/L2 被 space 过滤排除在候选集外）
  │    → envelope(text ≤ 600, raw_format=mandol_unit)
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
            stage2  跨塔冲突去重（KG 实体 caroline ↔ L0 说话人 caroline，依赖 CASCADE_IDS_ON，
                    默认关，定稿脚本置 1 才生效；全量 78.2%/3-conv 87.6% 查询冲突 2–4 条（非 65%）；
                    丢弃不回填预算 → 9.3% 查询 <20 条）
            stage3  MMR 多样性打包（λ=0.7，token 预算 cap_to_input；但 max_tokens 未传，
                    取类默认 4096，非脚本的 1500，实测 98% 查询超过 1500）
            → 去重截断 20 条 → envelope(raw_format=mandol_tritower)

重排 dtype 已从官方硬编码 bfloat16 改为 float32（CPU 无 bf16 原生指令，
125→18 ms/对（本条未能核实，无归档原始计时，但与端到端 146s→11s 的量级自洽）；
fp32 精度更高，属硬件适配非机制改动）。
```

预算与剪枝参数（topk 15/30/30、final-top-k 20、mad=3.0、λ=0.7）取自官方
`run_reproduction_suite.sh`（产生论文数字的实际配置），但非全部：token 上限
（`--cascade-max-context-tokens`）没取，用了类默认 4096；融合权重
`--weight-hierarchical/graph/episodic 0.34/0.33/0.33` 在封装代码里无任何使用点（三塔直接拼接，无加权）。
κ=2.5 与论文 Eq.(1) 一致（也是代码默认值）；但 λ=0.6 是**代码默认值**，
论文全文未给 λ 数值（且 λ 在 Eq.(3)不在 Eq.(1)），不是论文值。

## 跨进程（快照/恢复）

```text
snapshot: _persist() 落盘 → 整目录拷贝到 __snapshots__/mandol/{tag}
restore : rmtree(state_dir) + copytree(快照) —— 全量替换，不是合并
```

三条由此衍生的纪律（都在真实事故里踩过，详见 repro-plan §12）：

1. 改完图必须刷新快照并 `diff -rq` 校验，否则下一次 restore 会**静默回滚**迁移成果
2. `snapshot()` 在 TOWERS_ON 时会先建塔——ingest 路径的 600s 超时撑不住 2h 建塔，
   建塔必须走 `scripts/build_mandol_towers.py`（timeout=36000）
3. 有 `.done.json` marker 的 conv 应拒绝重灌（人工纪律，代码未强制）——`add_conversation`
   同 uid 即覆盖，重灌会把 God Mode 改写静默冲回原文

## 检索路径上没有什么

- **图遍历**：`_cfg_full()` 设 `topk_graph=0` / `use_entity_relation=False`，
  官方主复现路径从不走边——这是核实过的代码路径，不是推断
- **知识图谱塔**：实体检索面存在，但 5,208 条抽取关系 0 条落地
  （`_entity_candidates_text` 漏 entity_id 等 four-layer 移植错误）。
  分数不受影响（上图），但不得声称复现了 KG 塔
- **router**：论文主结果配置中 GPT-4.1-mini 的路由表是恒等映射（五类问题全部 → `_cfg_full()`），
  不接即等价于全开，非省略机制（另一 backbone GPT-4o-mini 的路由表并非恒等，本臂未涵盖）
- **查询期时间推理**：输出不按时间排序；P1/P2 确实不衰减，改写注入的 `[Date: ...]` 前缀是它们的唯一时序信号；
  **P3 不成立**——级联 stage2 仲裁分含 `exp(−Δh/720h)` 指数时间衰减，参与决定跨塔冲突时谁被丢弃
  （副作用：答题模型照抄 ISO 日期，词重叠 F1 跨臂失效，judge 不受影响）
- **emotional memory**：官方 LoCoMo 路径从不构建（`locomo_types()=[STRUCTURED]`），
  论文声称四类记忆源只有三类有实验支撑
- **答题 prompt 的 gold 注入**：官方复现代码注入 gold category（locomo_triple_router.py:2147），
  本项目全臂不注入，保持统一

## 设计取舍记录（2026-09-01/02 与 wafo 对齐）

### ① 保持官方实现不优化（Q6）

L0 逐句 God Mode 改写占构建 token 的约 70%（无归档分步 token 账，以 L0 调用数占总调用 72.5% 为旁证），是最贵的一步，没有做批量合并。
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

不做跨 conv 共享图。dense 结果机制上一致（同一批向量、同一候选集，未见逐位对拍归档）；
若改共享图，BM25 的 IDF/avgdl 是语料级统计量会受影响，不能简单说“不变”；
换来的是可复现性（全量 vs 独立 3-conv 同 conv 对拍差 0.4pp）。

### ⑤ L1/L2 展平而非 JSON dump

首版存 `json.dumps(抽取结果)`：键名稀释语义 + 文本长 15 倍拖垮 cross-encoder
（L1 仅 19 候选占 37s——本条未能核实，无归档原始计时，但 19 与落盘 conv-26 的 L1 单元数对得上）。
展平后平均 4400→1230 字符（1230 精确，4400 的旧态无归档），且那 20 个单元
**此前从未进过 BM25 倒排**——等于顺带修好一路稀疏召回。

## 相关

- 实现代码：`servers/mandol/server.py`（MCP 层与环境开关）、
  `servers/mandol/towers/`（prompts/llm/hierarchical/episodic/kg/load/orchestrator/retrieve）、
  `scripts/build_mandol_towers.py`、`scripts/ingest_mandol_full.py`、`scripts/run_mandol_full.sh`
- 决策与考证：`docs/mandol-repro-plan.md`（§3 分层依据、§5 诚实性声明、§9–§14 执行记录）
- 实测结果：`runs/mandol-p1-baseline-3conv` → `mandol-p2-towers-3conv` →
  `mandol-p3-retrieval-3conv`（消融）→ `mandol-p3-full-3conv` → `mandol-full-10conv`

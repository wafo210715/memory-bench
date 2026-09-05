# mandol 架构文档复核报告

> 复核日期 2026-09-05
> 论文源：`literature/papers/Zhang-et-al-2026-Mandol-An-Agglomerative-Agent-Memory-System-for-Long-Term-Conversations.txt`（1,512 行，arXiv:2606.29778v1）
> 上游代码源：`repo/Mandol` @ `6d7af4f`（2026-08-02，AgentCombo/Mandol）
> 封装臂代码源：`memory-bench` @ `947c136`，`servers/mandol/{server.py,towers/*.py}`
> 复核对象：`servers/mandol/ARCHITECTURE.md`（189 行，主）；同目录 `methodology-flow.md`（2026-09-05 由 methodology-flow 任务生成，本次仅抽检未计入统计）
> 归档实测源：`runs/mandol-p1-baseline-3conv`、`mandol-p2-towers-3conv`、`mandol-p3-retrieval-3conv`、`mandol-p3-full-3conv`、`mandol-full-10conv`、`.state/mandol/`
>
> **三源结构说明**：本目录的 ARCHITECTURE.md 不是「论文 vs 代码」对照文档，而是 memory-bench
> 自建 **mandol 臂**（上游 prompt/算子 + 本项目编排）的 P1/P2/P3 三态操作流程说明。故本报告核对三条线：
> (a) 论文 → txt 行号；(b) 上游仓库 → `src/mandol/*.py:NNN` / `benchmark_locomo/**:NNN`；
> (c) 封装臂 → `servers/mandol/*.py:NNN` + 归档 run 产物。

---

## 1. 总评

ARCHITECTURE.md 的**数值层可信度极高**：文中每一个可从归档产物复算的数字都逐位对上了——
3-conv ALL(1–4) 52.4 / 71.3 / 74.4、中位延迟 239 / 225 / 10,199 ms、构建总账
3-conv 1,821 次调用 · 244 万 in · 70 万 out 与全量 8,071 次 · 1,111 万 in · 301 万 out · 失败 21、
「5,208 条关系 0 边」、「多跳 23.6→48.5」、「全量 vs 3-conv 对拍差 0.4pp」——全部实测复算一致，
其中「5,208」精确等于 10 个 conv 关系总数 6,732 减去修复前建的 conv-26/30/49 的 1,524。
在我复核过的文档里，这是数字最硬的一份。

**但机制层有一条硬伤**：文档把 P2「证据 100% 是 L0」解释为「L1/L2 在图里但 dense kNN 一次也没检回它们」——
实际是 `retrieve()` 传 `ms_names=[conv_id]` 做**硬空间过滤**，而 L1/L2 单元只挂在
`hierarchical_memory:L1_Summary` / `:L2_Insight` 空间，从未加入 `conv-26` 空间
（落盘实测：`conv-26` 空间 419 个 uid，全部是 L0；`child_space_names` 为空）。
FAISS 检索前就把候选集裁到 419 个 L0（`semantic_map.py:2186-2192,2539-2557`）。
即 L1/L2 是**被结构性排除**，不是「排名靠后没检回」。结论（+18.9 全部来自 L0 改写）不变，
但这是「检索器排序问题」与「索引可见性 bug」的区别，会误导后续改进方向。

另有四条应改：`raw_format` 实际是 `mandol_unit` 而非文档写的 `mandol_dense`（30,000/30,000 条 run 产物为证）；
「论文 Eq.(1) 的 κ=2.5/λ=0.6」把**代码默认值** λ=0.6 记成了论文值（论文全文未给 λ 任何数值，
且 λ 在 Eq.(3) 不在 Eq.(1)）——`towers/retrieve.py:18` 的原始表述是对的，转写时失真；
「查询期不衰减」在 P3 态不成立（级联 stage2 仲裁分含 720h 指数时间衰减）；
「参数全部取自官方脚本」有例外（`--cascade-max-context-tokens` 没取，用了类默认 4096，实测 98% 查询超脚本的 1500）。

跨出文档之外，本次复核在**论文↔上游**方向发现两条更重的问题：论文 §3.2/§4/Table 1 反复声明的
**DuckDB 持久化后端在整个仓库中不存在**（无 import、无依赖、无文档；实际是 rocksdict），
以及 Table 2 列出的三个核心 API（`quantitative_search` / `search_unit` / `build_memory_from_raw`）
**全仓库零出现**。这两条 ARCHITECTURE.md 未涉及（其职责范围是封装臂），但应进入诚实性声明。

---

## 2. 逐条核对表

判定符号：`✓` 属实 / `✗` 不实 / `◐` 部分属实或需加限定 / `?` 无法核实

### 2.1 页首元信息（L1-7）

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| 1 | L3 | commit `d0a981b`（构建层） | ✓ | `git log -1 d0a981b` = "mandol 构建层：三塔离线构建（L0 改写 / 事件链 / 实体图）" | |
| 2 | L3 | `104c530`（检索层） | ✓ | "mandol 检索层：三塔并行召回 + RRF + 重排 + 级联剪枝" | |
| 3 | L3 | `d171fe4`（接入） | ✓ | "mandol 接入：per-conv 独立图 + 稀疏向量 + 三塔检索开关" | |
| 4 | L4 | `c29cdb5`/`4bfcdb7`（3-conv 与全量结果） | ✓ | c29cdb5 "四档 3-conv 对照"；4bfcdb7 "全量 10-conv 定稿：0.6020" | |
| 5 | L4 | `8aad09b`（主表横比） | ✓ | "主表横比：mandol 0.7641 全类别第一" —— 0.7641 与本次复算的全量 ALL(1–4)=76.4 一致 | |
| 6 | L5 | 见 `docs/mandol-repro-plan.md` §12 等 | ✓ | 文件存在，838 行，§5 诚实性声明 / §9–§14 执行记录齐备 | |
| 7 | L6 | 跑分见 `wafo-base/.context/memory-bench-r2n3/report-2026-09-04.md` | ? | 该路径不在本次挂载范围（`$HOME/mnt/` 只有 literature / memory-bench / repo） | 无法核实 |

### 2.2 先回答三个常见问题（L9-32）

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| 8 | L11 | P1 = 对原始对话逐 turn 单元做 **dense kNN** | ✓ | `server.py:281` → `semantic_graph.py:1049-1094` → `semantic_map.py:2748-2761`（`search_similarity_by_text` = 取 embedding 后走 `search_similarity_by_vector`，纯稠密，无 BM25/SPLADE 参与） | |
| 9 | L12 | 与 rag_baseline「差异只在存储后端与**切分粒度**：per-turn MemoryUnit vs chunk」 | ◐ | `servers/rag_baseline/server.py:90`（docstring「turn 级 chunk，逐 turn embed」）、`:98-110` 逐 turn 一条 record | **粒度相同**，两者都是 turn 级。真实差异只有后端与索引实现（mandol：SemanticGraph + FAISS + space 过滤；rag：jsonl + numpy 暴力余弦）。「vs chunk」的对比是虚的 |
| 10 | L14-15 | P2 的 retrieve 仍是单路 dense kNN（`search_similarity_in_graph`） | ✓ | `server.py:259`（`TRITOWER_ON` 为假）→ `server.py:281` | |
| 11 | L16 | L0 的 text_content 已被 God Mode 改写覆盖 | ✓ | `towers/load.py:49`；落盘实测 `conv-26_s01#0` 的 `text_content` 以 `[Date: 2023-05-08] [Caroline] [Conversation Opening]…` 开头 | |
| 12 | L16 | 图里多了 L1/L2 抽象单元 | ✓ | `.state/mandol/graphs/conv-26/semantic_map_data/semantic_map_meta.json`：439 单元 = 419 L0 + 19 L1 + 1 L2 | |
| 13 | L17-18 | episodic/kg 两塔建在独立图里，P2 的检索路径**根本不查它们** | ✓ | `server.py:257` 只取 `_get_graph(gid)`；两塔图目录为 `graphs/conv-26__episodic` / `__kg`（`towers/orchestrator.py:71,80`） | |
| 14 | L19 | P2 的 **30,000 条**证据里 **100.0%** 是 L0 单元 | ✓ | `runs/mandol-p2-towers-3conv/evidence/mandol.jsonl`：1,500 行 × 20 envelope = 30,000，按 memory_id 分类 L0=30,000 / L1=0 / L2=0 | 数字逐位对上 |
| 15 | L19-20 | **L1/L2 在图里但 dense kNN 一次也没检回它们** | **✗** | `server.py:281` 传 `ms_names=[gid]`；`semantic_map.py:2186-2192` 走 `pure_space_filter` 分支，`:2539-2557` `_get_space_filter_int_ids` 把 FAISS 候选裁到该 space 的 uid 集合。落盘实测 `conv-26` space 的 `unit_uids` 恰 419 条（全 L0），`child_space_names=[]`；L1/L2 只在 `L1`/`L2` 与 `hierarchical_memory:L1_Summary`/`:L2_Insight` 四个 space 里 | **机制误述**：不是"检不回"，是候选集里根本没有。现象（100% L0）与推论（+18.9 来自改写）不受影响，但归因方向错了 |
| 16 | L20 | P1→P2 的 +18.9 全部来自 L0 改写本身 | ✓ | 复算 ALL(1–4)：P1 52.4（608/1160）→ P2 71.3（829/1162），Δ=+18.9；且 P2 证据 100% 为 L0 | 结论成立（#15 的证据只让它更强） |
| 17 | L21 | P3 = 三塔并行召回 → **融合 → 重排** → 级联剪枝 | ◐ | `towers/retrieve.py:275-289`：三塔并行 → `triples` 直接拼接 → `_to_chunks` → 剪枝。**合并之后没有任何融合/重排步骤**；重排发生在每塔内部（`retrieve.py:124-126,141-144`） | 顺序应为「每塔内 RRF+重排 → 合并 → 剪枝」。上游反而**有**合并后的统一二段重排（`locomo_triple_router_quantification.py:690`），见 §5.2-B1 |
| 18 | L27-29 | 查询延迟中位 239 / 225 / 10,199 ms | ✓ | 复算 `retrieve_wall_ms` 中位数：239.0 / 225.0 / 10,198.5 | 用 `latency_ms` 则是 233/222/10,196.5；文档取的是 wall |
| 19 | L27-29 | 3-conv ALL(1–4) 52.4 / 71.3 / 74.4 | ✓ | 按 `judge_correct` 复算 cat1-4：608/1160=52.4、829/1162=71.3、864/1161=74.4 | |
| 20 | L31 | P2→P3 +3.1；P1→P2 +18.9 | ✓ | 74.4−71.3=3.1；71.3−52.4=18.9 | |

### 2.3 写入侧（L34-51）

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| 21 | L34 | `add_conversation`，**每 turn 一次**（一个 MemoryUnit） | ✓ | `server.py:221-239` 逐 turn 建 `MemoryUnit` 并 `add_unit` | 工具本身按 session 调用，unit 按 turn 建 |
| 22 | L38 | uid = `{conv}_{session}#{i}` | ✓ | `server.py:224` `uid=f"{session_id}#{i}"`；harness 的 session_id 形如 `conv-26_s01`（落盘 uid `conv-26_s01#0`） | |
| 23 | L39 | metadata: session_id / message_index / **speaker** / timestamp | ◐ | `server.py:227-228` 实际写入 `session_id` / `scope` / `timestamp` / `message_index`——**没有 speaker** | speaker 要到构建侧 `load.py:60` 才写入。写入侧四个字段里有一个不对 |
| 24 | L41 | dense embedding（embedding-3，2048 维，云端） | ✓ | `server.py:108`（`MEMBENCH_EMBED_MODEL` 默认 `embedding-3`）、`:187`（dim 默认 2048）、`:190`（`"type": "cloud"`） | |
| 25 | L42 | sparse embedding（SPLADE，env `MEMBENCH_MANDOL_SPARSE`，默认开） | ✓ | `server.py:111` | |
| 26 | L43 | BM25 倒排与 SPLADE 倒排**随写随增量更新** | ✓ | `semantic_map.py:1217-1246` `_incremental_aux_retriever_add`（对 BM25/SPLADE 调 `add_units`），由 `_apply_index_update_mode` 在默认 `index_update_mode="incremental"` 下触发（`semantic_graph.py:382`） | |
| 27 | L45 | 落入 per-conversation 独立图 `.state/mandol/graphs/{conv_id}/` | ✓ | `server.py:104,173-174,206-210`；落盘目录 `graphs/conv-26 … conv-50`（含 `__episodic`/`__kg` 共 30 个） | |
| 28 | L46 | Q7 决策：已验证独立图不改 dense 结果，**hash 逐位一致** | ◐ | 全仓库检索「逐位/逐字节/位级」：repro-plan 只在**别的**语境出现（prompt 逐字节回验、3 rep 逐字节相同），**无**独立图 hash 对拍记录 | dense 部分机制上成立（同一批归一化向量、同一候选集）；但同句里的「BM25 统计量不变」若指「相对共享图不变」则**不成立**（IDF/avgdl 是语料级）。`server.py:101` 的原话是「不跨 conv 污染 → 分批灌入与一次灌完等价」，转写时语义被拧了 |
| 29 | L50 | 写入侧**没有任何 LLM 调用** | ✓ | `server.py:213-242` 只有 `add_unit`；embedding 走 cloud embedding 端点，非 LLM | |
| 30 | L51 | 与 amem（写入时**逐 turn 两次 LLM**）的根本区别 | ◐ | 上游 `repo/A-mem/agentic_memory/memory_system.py`：`analyze_content` 定义于 `:159` 而**全仓库零调用点**；`add_note`（`:233-241`）只经 `process_memory` 一次 LLM（`:621`） | 「两次」只对 memory-bench 自建的 **fixed 臂**成立（`servers/amem/fixed.py:369-372` 补回 `analyze_content`）；native 臂是 1 次。应加限定 |

### 2.4 构建侧（L53-82）

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| 31 | L53 | `snapshot` 钩子触发，TOWERS_ON=1 时 | ✓ | `server.py:366-368` | |
| 32 | L53 | 灌完后**一次性** | ✓ | `server.py:349-362` 遍历全部 scope；`towers/orchestrator.py:3-5` docstring | |
| 33 | L57 | 对每个没有 `.done.json` marker 的 conv | ✓ | `towers/orchestrator.py:35-40` | |
| 34 | L59 | ① L0 God Mode 改写 **[LLM，逐 turn 一次]** | ✓ | `towers/hierarchical.py:106-133`（每条 message 一次 `llm.complete`，`max_tokens=250`）；上游同构 `step1_generate_l0_graph.py:601-604` | |
| 35 | L60 | 原文 → 自包含改写句 + indexing_text | ✓ | `hierarchical.py:136`（`f"{ctx}\nOriginal: {m.text}"`）＝上游 `step1:608` 逐字同构 | |
| 36 | L61-64 | 例：`"Hey Mel! How have you been?"` → `[Date: 2023-05-08] [Caroline] [Conversation Opening] Caroline greets Melanie…` | ✓ | 落盘 `conv-26_s01#0` 的 text_content 与该串一致 | 原文实为「Hey Mel! Good to see you! How have you been?」，示例做了省略，无实质问题 |
| 37 | L65 | 载入时 text_content 被 indexing_text 覆盖（原文存 `original_text` 双视图） | ✓ | `towers/load.py:49-50` | |
| 38 | L66 | （官方 **step4:360**） | ✓ | `step4_load_to_semantic_graph.py:360` 恰为 `raw_data['text_content'] = indexing_text` | 行号精确命中 |
| 39 | L68 | ② L1 会话摘要 / L2 全局聚合 **[LLM，每 session / 每 conv]** | ✓ | `hierarchical.py:150-184`（逐 session）、`:187-213`（整 conv 一次） | |
| 40 | L69 | L1 展平成自然语句入库（不存 JSON dump） | ✓ | `load.py:124-151` `_flatten_extraction`，`:161,168` 调用点 | |
| 41 | L71-72 | ③ episodic 事实抽取 **[LLM]** → 独立图 | ◐ | 实际是**两段 LLM**：`episodic.py:33-73` 抽取 + `:107-150` 聚类后逐簇合并（中间夹 MiniLM+DBSCAN，`:76-92`） | 流程图把两次 LLM 合并成一格，成本与机制都被压缩 |
| 42 | L74-77 | ④ kg 实体抽取 **[LLM]** → 独立图 | ◐ | 实际是**四段 LLM**：`kg.py:37-68` 抽取、`:114-157` 逐簇去重、`:160-196` 会话内关系、`:199-226` 跨会话关系（`orchestrator.py:76-79`） | 同上 |
| 43 | L77 | ⚠️ 关系边 **0 条落地** | ✓ | `.state/mandol/towers/*.done.json`：conv-41/42/43/44/47/48/50 的 `kg.edges` 全为 0（关系数 743/682/736/739/793/799/716） | conv-26/30/49 的 marker 里 kg.edges 为 10213/6955/11031，是**修复前把调用次数当边数**的旧计法（repro-plan §12 修复二），非反例 |
| 44 | L139 | **5,208 条**抽取关系 0 条落地 | ✓ | 10 conv 关系总数 6,732 − conv-26/30/49 的 507+431+586=1,524 = **5,208** | 精确 |
| 45 | L79 | marker 落盘 + 全部图 `save_graph` | ✓ | `orchestrator.py:94-95` 写 marker；`server.py:369` `_persist()` 遍历 `_GRAPHS` 调 `save_graph` | |
| 46 | L79 | 断点续跑 = conversation 粒度 | ✓ | `orchestrator.py:35-40` | |
| 47 | L81 | 3-conv **1,821** 次调用 / **244 万** in + **70 万** out | ✓ | conv-26/30/49 marker `llm` 求和：calls 1,821 / tokens_in 2,443,069 / tokens_out 694,842 | |
| 48 | L82 | 全量 **8,071** 次 / **1,111 万** in + **301 万** out / 失败 **21** | ✓ | 10 个 marker 求和：8,071 / 11,118,014 / 3,011,202 / 21 | 四个数全部逐位命中 |

### 2.5 读取侧（L84-118）

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| 49 | L86 | query 进入（`query_mode=fixed, top_k=20, filter.scope_id=conv`） | ✓ | `bench/runner.py:244-247`；`runs/mandol-full-10conv/manifest.json` `top_k: 20` | |
| 50 | L88 | TRITOWER_ON=0（P1/P2 态，**默认关**） | ✓ | `server.py:118` | |
| 51 | L90 | base 图内 dense kNN，语料 = P1 原文 / **P2 改写+抽象** | ◐ | 同 #15：抽象层（L1/L2）不在 `conv-26` space，被 `ms_names` 过滤在候选集外 | 应为「P2 改写后的 L0」，「+抽象」不成立 |
| 52 | L91 | envelope(**text ≤ 600**) | ✓ | `servers/common/envelope.py:4` `MAX_CHARS = 600`，`:15-16` 截断 | |
| 53 | L91 | `raw_format=**mandol_dense**` | **✗** | `server.py:301` 写的是 `raw_format="mandol_unit"`；P1/P2 两个 run 共 60,000 条 envelope 的 `raw_format` 全部为 `mandol_unit`，`mandol_dense` 出现 0 次 | 纯事实错误，直接改字符串即可 |
| 54 | L94 | TRITOWER_ON=1（P3 态，env `MEMBENCH_MANDOL_TRITOWER`） | ✓ | `server.py:118,259` | |
| 55 | L95 | 三塔**并行**（ThreadPoolExecutor） | ✓ | `towers/retrieve.py:275-279`；上游同构 `locomo_triple_router.py:1515-1520` | |
| 56 | L97 | hierarchical **15 条**：HierarchicalRetriever | ✓ | `retrieve.py:33,276`；实测 5,958 次查询的 `tower_hits.hierarchical` 恒为 15 | |
| 57 | L98 | 按 `L0_Observation`/`L1_Summary`/`L2_Insight` **三个 memory space 分层检索** | ✓ | `hierarchical_retriever.py:107-111` `LAYER_TO_SPACE`、`:170-182` 逐层 `_smart_search(space_names=[layer_space])`；空间名见 `memory_space_registry.py:13-15` | |
| 58 | L99 | 每层内部 = bm25 + cosine + splade → RRF → cross-encoder 重排 | ✓ | `hierarchical_retriever.py:163`（`effective_methods` 默认三路）、`:74`（`fusion_method="rrf"`）、`:145`（`rerank_method="baai"`） | |
| 59 | L101-102 | episodic **30 条**：`MultiRetriever.smart_search`（bm25+cosine+splade → RRF → 重排） | ✓ | `retrieve.py:119-126,277`；实测 `tower_hits.episodic` 恒为 30 | |
| 60 | L104 | kg **30 条**：同上（实体语义检索面，**无边可走**） | ✓ | `retrieve.py:278` 用 `TOPK_SIMILARITY=30`；实测恒 30；边为 0（#43） | |
| 61 | L106 | 合并 **75 条** | ✓ | 15+30+30；实测 `cascade.stage1_in` 恒为 75 | |
| 62 | L106 | `CascadeConfidencePruner`（三 stage） | ✓ | `cascade_pruner.py:406` `_stage1_hard_filter` / `:464` `_stage2_disambiguate` / `:652` `_stage3_mmr_pack` | |
| 63 | L107 | stage1 MAD 离群剔除（**mad=3.0**） | ✓ | `retrieve.py:40,299`；官方脚本 `run_reproduction_suite.sh:354` `--cascade-mad-multiplier 3.0` | |
| 64 | L107 | 实测**几乎不剔** | ✓ | 全量 5,958 次查询中 `stage1_out==stage1_in` 占 **97.3%**（3-conv 97.4%） | |
| 65 | L108-110 | stage2 跨塔冲突去重（KG 实体 caroline ↔ L0 说话人 caroline） | ◐ | 机制成立：`retrieve.py:190-208` 三塔各自取 entity_ids（L0 用 speaker），`cascade_pruner.py:517-522` 要求同 id **跨塔**才算冲突。但 `retrieve.py:155` `CASCADE_IDS_ON` **默认关**，关时只有 KG 塔有实体（`:247`），stage2 结构性失效 | 定稿脚本 `scripts/run_mandol_full.sh:29` 置 1，故对定稿 run 成立；文档未标注默认态 |
| 66 | L109 | 抽样 **65%** 查询 2–4 条（跨塔冲突） | **✗** | 复算 `cascade.stage2_conflicts` 分布：全量 10-conv **78.2%** 落在 2–4；3-conv 完整组 **87.6%**。两者都不是 65% | 方向对（绝大多数查询有 2–4 条冲突），数字与归档 run 不符 |
| 67 | L110 | 丢弃不回填预算 → **9.3%** 查询 <20 条 | ✓ | 全量 run：5,958 次中 552 次 envelope 数 <20 = **9.3%**（3-conv 完整组为 10.6%） | 精确命中全量口径 |
| 68 | L111 | stage3 MMR 多样性打包（**λ=0.7**） | ✓ | `retrieve.py:41,300`；脚本 `:355` `--cascade-lambda-mmr 0.7` | |
| 69 | L111 | token 预算 `cap_to_input` | ◐ | `cap_to_input_tokens` 默认 True 且未覆盖 ✓（`cascade_pruner.py:198`）；但 `max_tokens` 也没传，取类默认 **4096**，而官方脚本传 1500（4.1-mini）/ 2000（4o-mini） | 实测 cascade `tokens` 中位 2,682，**98.0%** 的查询 > 1500，最大顶到 4096——预算这一维并未对齐脚本 |
| 70 | L112 | 去重截断 **20 条** | ✓ | `retrieve.py:317-326`（按 uid 去重后 `>= top_k` 即停，`FINAL_TOP_K=20`） | |
| 71 | L112 | envelope(`raw_format=mandol_tritower`) | ✓ | `server.py:274`；P3 两个 run 共 145,839 条 envelope 全为 `mandol_tritower` | |
| 72 | L113-114 | 重排 dtype 已从官方**硬编码 bfloat16** 改为 float32 | ✓ | `rerank_manager.py:462` `torch_dtype=torch.bfloat16` 无条件；`:443` device 仅 cuda/cpu 二分支；封装侧 `retrieve.py:59-78` monkeypatch | |
| 73 | L114 | 125→18 ms/对 | ? | 仅见于 repro-plan §12「修复三」，无归档原始计时产物 | 与「端到端 146s→11s」的量级自洽（实测 P3 中位 10.2s） |
| 74 | L117 | **参数全部**取自官方 `run_reproduction_suite.sh` | ◐ | 对得上：topk 15/30/30（脚本 `:340-343`）、final-top-k 20（`:344`）、mad 3.0、λ 0.7、STRICT_THRESHOLD、abs_min −5.0（`:354-357`）。**没取**：`--cascade-max-context-tokens`（见 #69）；`--weight-hierarchical/graph/episodic 0.34/0.33/0.33` 在 `retrieve.py:12` 的 docstring 里列了，但**代码中没有任何使用点**（三塔结果直接拼接，无加权融合） | 「全部」过头了；应写「预算与剪枝参数取自脚本，token 上限与融合权重未取（未使用）」 |
| 75 | L118 | 与**论文 Eq.(1) 的 κ=2.5/λ=0.6** 不一致 | **✗** | 论文 txt:657 Eq.(1) 只含 κ；txt:672「With κ = 2.5」✓。λ 出现在 **Eq.(3)**（txt:680），且**论文全文未给 λ 任何数值**（grep λ/0.6 无果；txt:637 的 0.6 是语义记忆的 source confidence，不是 λ）。λ=0.6 是**代码默认**（`cascade_pruner.py:191,1133`） | `towers/retrieve.py:18`「论文 Eq.(1) 写 κ=2.5，代码默认也是 2.5……λ 代码默认 0.6、脚本 0.7」表述正确；ARCHITECTURE 转写时把代码默认误挂到论文名下 |

### 2.6 跨进程 + 检索路径上没有什么（L120-149）

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| 76 | L123 | snapshot: `_persist()` 落盘 → 整目录拷贝到 `__snapshots__/mandol/{tag}` | ✓ | `server.py:369-370` → `servers/common/base.py:22-26`（`snap_root = root/"__snapshots__"/system`，`copytree`）；落盘 `.state/__snapshots__/mandol/{locomo_full,phase1_baseline,smoke}` | |
| 77 | L124 | restore: `rmtree(state_dir)` + `copytree(快照)` —— **全量替换，不是合并** | ✓ | `base.py:28-36` | |
| 78 | L129 | 纪律1：改完图必须刷快照并 `diff -rq` 校验 | ✓ | repro-plan §12「踩过的坑」1（含具体命令） | 纪律性陈述，机制前提由 #77 支撑 |
| 79 | L130-131 | 纪律2：ingest 路径 **600s 超时**；建塔走 `scripts/build_mandol_towers.py`（**timeout=36000**） | ✓ | `bench/runner.py:195` `timeout=600`；`scripts/build_mandol_towers.py:48` `timeout=36000` | |
| 80 | L132-133 | 纪律3：有 marker 的 conv **一律拒绝重灌**；同 uid 即覆盖，重灌会把改写静默冲回原文 | ◐ | 覆盖机制成立（`load.py:36-37` 注释 + `semantic_map` "added or updated"）；但代码里**没有**任何基于 marker 拒绝 `add_conversation` 的守卫——marker 只被 `orchestrator.py:36` 用来跳过建塔 | 属人工纪律，非代码强制。文档在「纪律」小节下，可接受，但「一律拒绝」的措辞像在描述实现 |
| 81 | L137-138 | 图遍历：`_cfg_full()` 设 `topk_graph=0`/`use_entity_relation=False`，官方主复现路径从不走边 | ✓ | `src/mandol/memory_router/locomo_tower_router.py:66-74`；`locomo_triple_router.py:1997,2018-2023`（`use_entity_relation` 为假走 semantic-only 分支）。更强：`locomo_triple.py:3359` `use_entity_relation = (not no_entity_relation) and (topk_graph > 0)`，而 `--topk-graph` 默认 0——脚本的**四个 section 全部**不走边 | 「核实过的代码路径，不是推断」属实 |
| 82 | L139-141 | KG 塔：`_entity_candidates_text` 漏 entity_id 等 four-layer 移植错误 | ✓ | `towers/kg.py:90-111` 只输出 Name/Type/Session/Confidence；官方 `step2_locomo_relation_generator.py:381` 为 `- ID: {entity_id} \| Name: … \| Type: …`；而 `RELATION_EXTRACTION_PROMPT`（`prompts.py:131`）要求 head/tail 填 "EXACT Entity ID" 并明文禁止用名字。另三层：`load.py:224-226` 读 `source/subject/head` 而 prompt 返回 `head_entity/tail_entity`；`load.py:226` 按名字查 `uid_by_name`；`kg.py:220` 读 `relations` 而跨会话 prompt 返回 `cross_session_relations` | 四层全部复现，文档描述准确 |
| 83 | L141 | 分数不受影响（上图） | ✓ | 由 #81 支撑（`topk_graph=0` → `entity_retriever.search(q, 0)` 不被调用，`graph_results=[]`） | |
| 84 | L142-143 | router：**论文主结果配置**的路由表是恒等映射（五类全部 → `_cfg_full()`） | ◐ | `locomo_tower_router.py:106-119`：GPT-4.1-mini 的 AGGRESSIVE 与 CONSERVATIVE 确为五类全 `_cfg_full()` ✓。但 `:122-138` **GPT-4o-mini** 的 AGGRESSIVE 是 `_cfg_h_e/_cfg_h_g/_cfg_full/_cfg_full/_cfg_g_e`，CONSERVATIVE 的 ADVERSARIAL 也是 `_cfg_g_e`——**都不恒等** | 论文 Table 3 主结果**含两个 backbone**。repro-plan §5 与 `retrieve.py:21` 都写了「（GPT-4.1-mini）」限定，ARCHITECTURE 转写时丢了 |
| 85 | L144 | 查询期时间推理：**不排序、不衰减** | **✗**（对 P3） | `cascade_pruner.py:637-644`：stage2 仲裁分含 `temporal_bonus = exp(−Δh / temporal_decay_hours)`，权重 `w_temporal=0.2`，`temporal_decay_hours` 默认 **720h**（`:194`，封装未覆盖）；封装侧 `retrieve.py:226-232` 确实把 `metadata.timestamp` 解析成 epoch 喂进去（L0 有 session date、EP 有 absolute_start） | 「不排序」✓（输出不按时间排）。「不衰减」对 P1/P2 成立、对 P3 **不成立**——时间衰减参与决定跨塔冲突时谁被丢弃 |
| 86 | L145 | 改写注入的 `[Date: …]` 前缀是**唯一**时序信号 | ◐ | 同 #85：P3 下还有 `metadata.timestamp` 驱动的 Eq.(2) 时间衰减 | |
| 87 | L145-146 | 副作用：答题模型照抄 ISO 日期，词重叠 F1 跨臂失效，judge 不受影响 | ✓ | commit `8aad09b` message「F1 跨臂失效已定位到机制」；样本佐证 `mandol\|conv-26\|q0\|rep2`：gold「7 May 2023」，答案「2023-05-07」，`f1=0.0952` 而 `judge_correct=1` | |
| 88 | L146-147 | emotional memory：官方 LoCoMo 路径从不构建（`locomo_types()=[STRUCTURED]`） | ✓ | `src/mandol/auto_builder/hierarchical_prompts.py:35-38`；`L1SummaryType.EMOTIONAL` 存在（`:23`）且有 `L1_EMOTIONAL_PROMPT`（`:139`），但 LoCoMo 不选它 | |
| 89 | L147 | 论文声称四类记忆源，只有三类有实验支撑 | ✓ | 论文 txt:460「basic, episodic, semantic, and emotional memory」、txt:285-287、txt:755-757。且 `longmemeval_types()` 返回 `[EPISODIC, KNOWLEDGE]`（`hierarchical_prompts.py:40-43`）——**LongMemEval 同样不建 emotional** | 结论比文档写的还强（两个 benchmark 都没有） |
| 90 | L148 | 官方复现代码注入 gold category（`locomo_triple_router.py:2147`） | ✓ | `:2147` `category_guidance = self._get_tri_tower_category_guidance(category)`，`:2148-2149` 把 `QUESTION CATEGORY: {category} - {guidance}` 写进 prompt；`category` 来自数据集（`:1177` `qa_item.get("category", 1)`） | 行号精确 |
| 91 | L149 | 本项目全臂不注入，保持统一 | ✓ | `bench/runner.py:276` `scoring.answer_user(evidence_text, question)`——只有证据与问题，无 category | |

### 2.7 设计取舍记录（L151-181）

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| 92 | L155 | L0 逐句改写占**构建 token 的约 70%**，是最贵的一步 | ◐ | marker 只记 conv 级总账（`llm.tokens_in/out`），**无分步 token 账**，无法直接验。可验的旁证：L0 调用数 5,849 / 总调用 8,071 = **72.5%**，且 L0 每次重发整段 transcript | 方向可信、数量级自洽，但「token 的 70%」这一具体口径无归档证据 |
| 93 | L157 | 多跳 **23.6→48.5** 的翻倍正来自这步 | ✓ | cat1 复算：P1 56/237=23.6，P2 116/239=48.5 | 且 P2 证据 100% 为 L0，归因链完整 |
| 94 | L159-161 | ② 构建侧 temp=0（**官方 0.1**） | ✓ | `towers/llm.py:37` `temperature: float = 0.0`；官方 `step1_generate_l0_graph.py:603`、`step2_extract_l1.py:146`、`step3_aggregate_l2.py:185`、`locomo_episodic_memory/step1:28`、`step2:417`、`locomo_graph_maker/step1:393`、`step2:400,548` 全为 0.1；实体去重 `step1:620` 为 0.05（`towers/llm.py:7` 亦注明） | |
| 95 | L166-167 | ③ `source_chunk_ids` 统一走官方 `or [chunk_id]` 兜底 | ✓ | `towers/retrieve.py:243-245`；官方 `locomo_triple_router_quantification.py:737` `_extract_source_chunk_ids_for_cascade(unit) or [chunk_id]` | |
| 96 | L167-168 | 不读本项目自加的 `metadata.source_unit_uids` | ✓ | `retrieve.py:239-243` 注释与实现一致（只读 `raw_data` 的 `source_chunk_ids`/`source_ids`） | |
| 97 | L169 | 实测跨塔冲突本来就**全部来自 entity_ids** | ✓ | 可推证：三塔 uid 命名空间互不相交（base 图 `conv-26_s01#i` / `conv-26_EP_i` / `conv-26_ENT_i`），而 `source_chunk_ids` 兜底为自身 uid（#95），故 `cascade_pruner.py:526-531` 的 source 跨塔冲突不可能触发 | |
| 98 | L170 | stage2 整体在 LoCoMo 规模无可测量贡献（消融 **p≈0.42**） | ✓ | repro-plan §12「结论一」`Δ=+0.0051, t=0.89, df≈4 → p≈0.42`；两组 ALL(1–4) 复算 73.6（p3-retrieval）vs 74.4（p3-full），overall 0.5901 vs 0.5952，与该 Δ 一致 | |
| 99 | L173 | ④ 已验证：dense 结果**逐位一致**、**BM25 统计量不变** | ◐ | 见 #28。全仓库无该对拍记录；「BM25 统计量不变」在「相对共享图」口径下与 `server.py:101` 的原意矛盾 | |
| 100 | L174 | 换来可复现性（全量 vs 独立 3-conv 同 conv 对拍差 **0.4pp**） | ✓ | 复算 ALL(1–4)：全量限制到 conv-26/30/49 = 74.01，独立 3-conv = 74.42，差 **0.41pp** | 精确（overall 口径则是 0.28pp，repro-plan 用的就是后者） |
| 101 | L177-178 | ⑤ 首版存 `json.dumps`：文本长 15 倍拖垮 cross-encoder（L1 仅 19 候选占 37s） | ? | 仅见 repro-plan §12「修复三」，无归档计时/旧文本产物 | 19 这个候选数与实测吻合（conv-26 恰 19 个 L1） |
| 102 | L179 | 展平后平均 **4400→1230** 字符 | ✓（下界） | 落盘实测 L1+L2 文本均值：全量 282 个单元 **1,228** 字符、3-conv 66 个 **1,236**；`load.py:124,168` 的 limit 为 1200/2000 | 「1230」精确；「4400」的旧态无归档，无法验 |
| 103 | L179-180 | 那 **20 个**单元此前从未进过 BM25 倒排 | ✓ | conv-26 恰 19 L1 + 1 L2 = 20；repro-plan §12 记 BM25 `docs 419 → 439`，与落盘的 419/439 完全对上 | |
| 104 | L183-189 | §相关 列出的实现/脚本/文档路径 | ✓ | `servers/mandol/server.py`、`towers/`（8 个文件齐）、`scripts/build_mandol_towers.py`、`scripts/ingest_mandol_full.py`、`scripts/run_mandol_full.sh`、`docs/mandol-repro-plan.md`、5 个 runs 目录——全部存在 | |

### 2.8 `methodology-flow.md`（附核，抽检 6 项，不计入统计）

该文件于 2026-09-05 06:56 由 methodology-flow 任务生成，只画 Code 视角。抽检行号锚点全部命中：
`server.py:213-229`（逐 turn 建 unit）✓、`server.py:108,185-193`（embedding 配置）✓、
`hierarchical.py:106-147`（build_l0）✓、`episodic.py:25-30,76-92`（DBSCAN 参数）✓、
`towers/retrieve.py:45,55-87`（rerank dtype patch）✓、`scripts/run_mandol_full.sh:27-29`（P3 三开关）✓。
它对 P2 的描述沿用了 ARCHITECTURE 的说法，因此同样受 **#15** 影响（L1/L2 是被 space 过滤排除，不是排名靠后）。

---

## 3. 步骤清单 — 论文侧

来源：Zhang et al. 2026 §3.1–§3.3、§4、Eq.(1)-(3)、Figure 1-2、Table 2。
**系统边界**：论文把 chunk 切分、抽象构建、存储/持久化、路由、混合召回、去噪、冲突消解、
token 约束上下文生成全部划归 Mandol；backbone（GPT-4o-mini / GPT-4.1-mini）的作答在系统之外
（§5.1「answer-generation backbones」，txt:1040-1044）。论文强调**检索全程不调 LLM**
（abstract txt:31-33、§1 txt:110-112、§3.3 txt:459）。

### 写入侧（新对话到达时；§4「Memory construction and storage」）

| # | name（原文叫法） | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| P1 | partition raw dialogue into dialogue chunks（txt:735-737） | 每次新对话到达 | raw dialogue → chunks（每 chunk = session 的局部片段） | no | – | `P-INTAKE` |
| P2 | extract fine-grained memory units（dialogue content / speaker / temporal info，txt:737-740） | 每 chunk | chunk → memory units + metadata | no（未写用 LLM） | SemanticMap | `P-INTAKE` + `P-META` |
| P3 | pretrained model encodes raw info into a unified semantic vector（§3.1.1，txt:250-254） | 每 unit | unit → dense vector（与原文、metadata 同存） | no | SemanticMap | `P-EMBED` |
| P4 | three indexes: inverted index + dense + sparse vector index（§3.2，txt:411-417） | 每 unit（随写） | unit → 倒排/dense/sparse 索引项 | no | SemanticMap 索引 | `P-ANNINDEX` + `~P-SPARSE`（写入期稀疏编码，复用检索侧标签） |
| P5 | memory space assignment（§3.1.1，txt:256-260） | 每 unit | unit → 一个或多个 space（session/task/topic） | no | SemanticMap metadata | `P-META` |
| P6 | explicit structural edges via **rule parsing**（temporal order / entity reference / state update，§3.1.1 txt:262-266；§4 txt:740-743 "contextual edges and reference relations across sessions"） | 每 unit | units → 显式边 | no（明写 rule parsing） | SemanticGraph 邻接表 | `P-LINK` |
| P7 | **session-level context enhancement**（§3.1.2，txt:292-299） | 抽象过程中，每条短片段 | "booked a hutong homestay" → "[Time: … \| Topic: …] Booked a hutong homestay" | 未明写（属 abstraction 过程，隐含 LLM） | 抽象单元文本 | `P-REWRITE` |
| P8 | episodic memory：extract events / user states / temporal relations → **temporal event chains**（§3.1.2 txt:283-289；§4 txt:747-751） | 每 chunk/session | 基础层 → 事件节点 + 时间/因果边 | **是**（"leverages an LLM to agglomerate"） | episodic space | `P-EXTRACT` + `P-AGGREGATE` + `P-LINK` |
| P9 | semantic memory：extract entities and relations → **entity graph**（§4 txt:751-755） | 每 chunk/session | 基础层 → 实体节点 + reference/attribute 边 | **是** | entity-relation space | `P-EXTRACT` + `P-LINK` |
| P10 | emotional memory：extract user preferences / long-term states / preference changes → **preference-evolution chains**（§3.1.2 txt:285-288；§4 txt:755-758） | 每 chunk/session | 基础层 → 偏好节点 + state-update 边 | **是** | emotional space | `P-EXTRACT` + `P-CONFLICT`（state-update 边即状态版本化） |
| P11 | `source_unit_uids` traceable links（§3.1.2 txt:289-292） | 每抽象节点 | 抽象节点 → 指回基础单元 | no | SemanticGraph | `P-LINK` |
| P12 | incremental update（§4 txt:758-762：新对话到达时增量更新受影响的单元/边/链/实体/情感，不重建整个空间） | 每次新对话 | 增量 | no | 全部 | `~P-INTAKE`（增量分支） |
| P13 | memory persistence + **LRU/LFU 驱逐** + `save_graph` 迁移到 DuckDB + page-in callback（§4 txt:790-802） | 内存超阈值 / 手动 checkpoint | 冷单元 → DB，图中保留轻量引用 | no | DuckDB（论文声称） | `P-PERSIST` + `P-EVICT` |

### 检索侧（每 query；§3.3，全程 no-LLM）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| P14 | **Query-Adaptive Routing**：lightweight intent classifier 用 query 特征（时间表达/实体提及）选记忆源并分配 per-source 候选预算（§3.3.1，txt:461-472） | 每 query | query → {激活的源, 各源预算} | **no**（明写 without LLM） | – | `P-QUERYPARSE` |
| P15 | hybrid recall **in parallel**：BM25 + SPLADE + dense（§3.3.1，txt:472-476） | 每 query、每激活源 | query → 三路候选表 | no | 三索引 | `P-SPARSE` + `P-DENSE`（并行） |
| P16 | reciprocal rank fusion（txt:476-477） | 每源 | 三路候选 → 融合表 | no | – | `P-FUSE` |
| P17 | **selective subgraph expansion**：从 top-ranked 单元沿 SemanticGraph 扩展，按 edge type 与预算剪枝（txt:477-480） | 每 query | 融合表 → 扩展候选集 | no | SemanticGraph | `P-GRAPHEXPAND` |
| P18 | lightweight **cross-encoder rerank** → `S_ce(c_i)`（txt:480-483） | 每 query | 扩展候选 → CE 分 | no | – | `P-RERANK` |
| P19 | **Intra-source denoising**：Eq.(1) `τ_mad = median(S_ce) − κ·MAD(S_ce)`，κ=2.5（txt:655-673） | 每 query、每源 | 候选 → 过阈候选 | no | – | `P-SELECT`（阈值截断） |
| P20 | **Cross-source conflict resolution**：Eq.(2) `S_arb = w_rel·S_ce + w_temp·f_time + w_source·f_source`；`f_time` 指数衰减；`f_source` basic 1.0 / episodic 0.8 / semantic 0.6；贪心保留最高分丢弃陈旧冗余（txt:626-648） | 每 query | 多源候选 → 去冲突候选 | no | – | `P-CONFLICT` |
| P21 | **Token-constrained context generation**：Eq.(3) MMR `λ·Rel − (1−λ)·Red`，Red 基于实体与来源重叠，贪心加入直到 token 预算耗尽（txt:674-692） | 每 query | 候选 → 最终选中集 | no | – | `P-SELECT` |
| P22 | 输出 compact LLM context（§4 txt:786-789） | 每 query | 选中集 → prompt 上下文 | no | – | `P-ASSEMBLE` |
| P23 | backbone 作答（§5.1） | 每 query | context + question → answer | 1（backbone） | – | `P-GENERATE`（**边界外**） |

论文未描述任何**去重（P-DEDUP）**步骤、任何**查询期 LLM 改写/扩展**、任何**多跳 agent 工具循环**。

---

## 4. 步骤清单 — 上游代码侧（`AgentCombo/Mandol` @ `6d7af4f`，LoCoMo 复现路径）

**系统边界**：`benchmark_locomo/dataset_maker/**` 三条离线 pipeline（8 个 step）+ `src/mandol/**` 的
存储/检索算子属记忆系统；`benchmark_locomo/task_eval/locomo_triple_router*.py` 既是记忆系统的调用方
又兼评测脚本，其中**答题 prompt 组装与 LLM 作答/判分属评测侧**。
下表以产生论文数字的 `run_reproduction_suite.sh` 路径为准。

### 4.1 离线构建（`dataset_maker`，手动逐 step 执行，无断点续跑）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| C1 | `step1_generate_l0_graph.py` — CONTEXTUAL_RETRIEVAL_PROMPT（自称 "God Mode"） | 离线一次，**每 message 一次** | message + 整段 session transcript → `indexing_text = ctx + "\nOriginal: " + msg`（`:601-608`，`max_tokens=250`，`temperature=0.1`） | **1 次/message** | L0 json | `P-REWRITE` |
| C2 | `step2_extract_l1.py` — L1_EXTRACTION_PROMPT | 离线一次，**每 session** | transcript → 结构化 JSON（events/state_updates/countables/dates/key_facts） | 1 次/session | L1 json | `P-EXTRACT` |
| C3 | `step3_aggregate_l2.py` — L2_AGGREGATION_PROMPT | 离线一次，**每 conversation** | 全部 L1 → 全局统计/时间线/关系图/洞察 | 1 次/conv | L2 json | `P-AGGREGATE` |
| C4 | `step4_load_to_semantic_graph.py` | 离线一次 | L0/L1/L2 → MemoryUnit；`:360` **`raw_data['text_content'] = indexing_text`**（覆盖，检索走增强文本）；`:367` `retrieval_field='indexing_text'` | no | SemanticMap/Graph + FAISS/BM25/SPLADE | `P-EMBED` + `P-ANNINDEX` + `P-PERSIST` |
| C5 | `locomo_episodic_memory/step1_extract_episodic_facts.py` | 离线一次，每 session | dialogue → facts（content/type/participants/time/location/details/source_turns/retrieval_keys） | 1 次/session | 事实 json | `P-EXTRACT` |
| C6 | `step2_deduplicate_and_enhance.py` | 离线一次 | facts → MiniLM 嵌入 + DBSCAN(eps=0.25,min_samples=2) 聚类 → 逐簇 LLM_DEDUP_PROMPT 三模式合并（A 信息合并 / B 频次计数 / C 状态演化） | 1 次/簇 | 合并事实 | `P-DEDUP`（含 `P-CONFLICT` 的 C 模式） |
| C7 | `step3_load_to_retrieval_batch.py` | 离线一次 | 事实 → episodic space 单元 | no | SemanticMap | `P-EMBED` + `P-PERSIST` |
| C8 | `locomo_graph_maker/step1_locomo_entity_extractor.py` | 离线一次，每 session | 会话 → 实体（13 类 schema，含 LOCATION/DATE_TIME/NUMERICAL_VALUE） | 1 次/session | 实体 json | `P-EXTRACT` + `P-META` |
| C9 | `step1` 的聚类去重（`:483-500,618-667`，similarity_threshold=0.85，簇≤12 单次/否则按 12 分批） | 离线一次 | 实体 → mentions-based 归并实体 | 1 次/簇 | 实体 json | `P-DEDUP` |
| C10 | `step2_locomo_relation_generator.py` — 会话内关系（`:381` 候选清单含 **`- ID: {entity_id} \| Name: … \| Type: …`**） | 离线一次，每 session（实体≥2） | 会话 + 实体清单 → `relations[{head_entity,tail_entity,relation_type,…}]` | 1 次/session | 关系 json | `P-LINK` |
| C11 | `step2` 跨会话关系（`:546+`） | 离线一次 | 跨 session 实体组 → `cross_session_relations` | 1 次 | 关系 json | `P-LINK` |
| C12 | `step3_locomo_entity_relation_semantic_graph_batch.py` + `build_unified_graph.py` | 离线一次 | 实体/关系 → entity_relation space + 边 | no | SemanticMap/Graph | `P-EMBED` + `P-LINK` + `P-PERSIST` |

### 4.2 在线写入（`src/mandol` `SemanticGraph.add_unit`，供 Add-latency 实验与 self-host 用）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| C13 | `add_unit`（`semantic_graph.py:376-382`） | 每 unit | unit → SemanticMap（kv + dense + 可选 SPLADE，`generate_sparse_embedding=True`） | no | SemanticMap | `P-INTAKE` + `P-EMBED` + `~P-SPARSE` |
| C14 | `_incremental_aux_retriever_add`（`semantic_map.py:1217-1246`） | 每 unit（`index_update_mode="incremental"`） | unit → BM25/SPLADE 倒排增量 | no | retrieval 索引 | `P-ANNINDEX` |
| C15 | `add_relationship`（`semantic_graph.py:610`） | 显式建边时 | (src,tgt,type) → rustworkx 边；**节点缺失返回 False 不抛异常**（`:646,649`） | no | SemanticGraph | `P-LINK` |
| C16 | `save_graph` / `load_graph`（`:1626,1852`）+ `swap_out_relationship(strategy=LRU/LFU)`（`:1234-1251`）+ rocksdict payload store | 手动 / 超阈值 | 内存图 ↔ 磁盘（json + pkl + safetensors + faiss + rocksdict） | no | 磁盘 | `P-PERSIST` + `P-EVICT` |

### 4.3 在线检索（`locomo_triple_router_quantification.py`，＝论文 §3.3 的实际实现）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| C17 | 路由：`category = qa_item.get("category", 1)` → `GPT_41_MINI_ROUTING_AGGRESSIVE[category]`（`locomo_triple_router.py:1177,1385`；`locomo_tower_router.py:106-119`） | 每 query | **数据集 gold category** → TowerRoutingConfig | no | – | `P-QUERYPARSE`（但输入是 gold 标签，非 query 特征） |
| C18 | 三塔**并行**（`ThreadPoolExecutor`，`:1938-1946`） | 每 query | query → 三塔各自候选 | no | 三张图 | —（调度） |
| C19 | hierarchical 塔：`HierarchicalRetriever.search(top_k=15)` → 逐层 L0/L1/L2 各 `smart_search(bm25+cosine+splade, rrf, rerank=baai)` → `_fuse_layer_results`（`hierarchical_retriever.py:163-184`） | 每 query | query → 15 条 | no | base 图 | `P-SPARSE`+`P-DENSE` → `P-FUSE` → `P-RERANK` → `P-FUSE`(跨层) |
| C20 | graph(KG) 塔：`multi_retriever.smart_search(top_k=topk_similarity=30)`（`locomo_triple_router.py:2018-2023`） | 每 query | query → 30 条 | no | kg 图 | `P-SPARSE`+`P-DENSE` → `P-FUSE` → `P-RERANK` |
| C21 | 实体关系遍历：`entity_retriever.search(question, topk_graph)`（`:1898`） | 每 query | — | no | — | `~P-GRAPHEXPAND`（`use_entity_relation=False`/`topk_graph=0` → **主路径从不执行**） |
| C22 | episodic 塔：`smart_search(top_k=30)`（`:2043-2050`） | 每 query | query → 30 条 | no | episodic 图 | `P-SPARSE`+`P-DENSE` → `P-FUSE` → `P-RERANK` |
| C23 | **二段统一重排**：合并三塔 → `reranker.rerank(query, documents)` 对**全部**候选打分（`locomo_triple_router_quantification.py:690`） | 每 query | 75 条 → 统一 CE 分 | no | – | `P-RERANK` |
| C24 | `tower_separate` 预筛：**保留全部 L0/hierarchical** + graph/episodic 按 CE 取 `final_top_k`（`:698-702`） | 每 query | 75 → 约 35 | no | – | `P-SELECT` |
| C25 | `EnhancedCandidateChunk` 组装：三塔均取 `entity_ids`（KG: entity_canonical/text/name+target；episodic: entities/entity_ids/involved；其他: **speaker**；兜底 NER `ner:xxx`）+ `source_chunk_ids or [chunk_id]`（`:529-586,718-739`） | 每 query | 候选 → 带 id 的 chunk | no | – | `P-META` |
| C26 | Cascade stage1：MAD 硬过滤（`cascade_pruner.py:406-460`，脚本 `mad_multiplier=3.0`） | 每 query | chunk → 过阈 chunk | no | – | `P-SELECT`（＝论文 Eq.1） |
| C27 | Cascade stage2：仲裁分 `0.5·CE + 0.3·tower_trust + 0.2·exp(−Δh/720)`（`:616-650`；tower_trust 1.0/0.8/0.6）→ 同 id 跨塔冲突则丢低分（`:511-560`） | 每 query | → 去冲突 chunk | no | – | `P-CONFLICT`（＝论文 Eq.2） |
| C28 | Cascade stage3：MMR 打包（`:652+,938`），受 `max_tokens`（脚本 1500/2000/1800）与 `cap_to_input_tokens` 约束；DYNAMIC_ADAPTIVE 模式再按 **gold category** 查 `get_adaptive_params`（`adaptive_category.py:86`） | 每 query | → 最终选中集 | no | – | `P-SELECT`（＝论文 Eq.3） |
| C29 | 三塔分区 prompt 组装（TOWER 1/2/3 分节，graph 只放前 10 条，`locomo_triple_router.py:2152-2175`）+ **注入 gold category**（`:2147-2149`） | 每 query | 选中集 → 完整 prompt | no | – | `P-ASSEMBLE`（**评测侧**） |
| C30 | backbone 作答 + LLM 判分 | 每 query | prompt → answer → 判分 | 2（答题+判分） | – | `P-GENERATE`（**边界外**） |

---

## 5. 步骤清单 — memory-bench 适配层（`servers/mandol/`）

**系统边界**：MCP 三个工具 `add_conversation` / `retrieve`（+`snapshot`/`restore`/`reset`/`stats`）之内属记忆系统。
`retrieve` 返回 ≤20 条 envelope 后即出界——答题 prompt 组装、backbone 作答、judge 判分全在
`bench/runner.py:270-305` + `bench/scoring.py`（评测侧，全 arm 统一，**不注入 gold category**）。
查询文本按 `query_mode="fixed"` 原样透传，**无查询改写**。

### 5.1 写入（`add_conversation`，每 session 调用一次，逐 turn 处理；P1/P2/P3 共用）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| A1 | 建 MemoryUnit（`server.py:221-229`） | 每 turn | `{role,content,timestamp}` → uid `{session}#{i}`，`text_content="role: content"`，metadata `{session_id,scope,timestamp,message_index}` | **no** | – | `P-INTAKE` + `P-META` |
| A2 | dense embedding（`server.py:187-193,230-234`） | 每 turn | text → embedding-3 / 2048 维 / 云端 | no | SemanticMap + FAISS | `P-EMBED` |
| A3 | SPLADE 稀疏编码（`server.py:111,233`，默认开；失败上游只 warning，`semantic_map.py:1625-1691`） | 每 turn | text → sparse dict；成功率写入 `stats().mandol.sparse` | no | SemanticMap | `~P-SPARSE`（写入期稀疏编码，复用检索侧标签） |
| A4 | BM25/SPLADE 倒排增量（`semantic_map.py:1217-1246`） | 每 turn | unit → 倒排 | no | retrieval 索引 | `P-ANNINDEX` |
| A5 | space 挂载 `space_names=[scope.id]`（`server.py:232`）+ per-conv 独立图（`:104,177-199`） | 每 turn | unit → `conv-XX` space；图落 `graphs/{conv}/` | no | SemanticGraph | `P-META` |
| A6 | `_persist()` → `save_graph`（`server.py:206-210,369`） | 每次 snapshot | 内存图 → 磁盘 | no | 磁盘 | `P-PERSIST` |

### 5.2 离线构建（`snapshot` 钩子，`TOWERS_ON=1`；＝P1→P2 的全部差异）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| A7 | `collect_l0_messages`（`hierarchical.py:71-103`） | 每 conv 一次 | 图内 unit → L0Message（正则解析 speaker/日期/正文；<15 字符丢弃） | no | 读图 | `P-INTAKE`（二次解析） |
| A8 | `build_l0` God Mode 改写（`hierarchical.py:106-147`，`max_workers=8`） | **每 turn 一次 LLM** | message + 整段 transcript → `indexing_text`；失败退回 `[date] speaker: text` | **1/message**（改写角色） | – | `P-REWRITE` |
| A9 | `build_l1`（`hierarchical.py:150-184`） | 每 session | transcript → 结构化 JSON + `_source_unit_uids` | 1/session（抽取角色） | – | `P-EXTRACT` |
| A10 | `build_l2`（`hierarchical.py:187-213`） | 每 conv | 全部 L1（≤120k 字符）→ 全局聚合 JSON | 1/conv（聚合角色） | – | `P-AGGREGATE` |
| A11 | `apply_l0_indexing`（`load.py:34-69`） | 每 conv | 同 uid 重 `add_unit`：`text_content=indexing_text`（覆盖）+ `original_text` 双视图；挂 `hierarchical_memory:L0_Observation` | no | 重嵌入 + 重稀疏 | `P-EMBED`（承接 A8 的改写） |
| A12 | `link_temporal`（`load.py:72-88`） | 每 conv | 同 session 相邻 message → `temporal_next` 边（**必须检查返回值**） | no | SemanticGraph | `P-LINK` |
| A13 | `_flatten_extraction` + `load_l1_l2`（`load.py:124-178`） | 每 conv | L1/L2 JSON → 展平自然语句（limit 1200/2000）→ 单元 + `derived_from` 溯源边 | no | 图 + 索引 | `P-AGGREGATE` + `P-EMBED` + `P-LINK` |
| A14 | `build_facts`（`episodic.py:33-73`） | 每 session | dialogue → episodic facts | 1/session（抽取角色） | – | `P-EXTRACT` |
| A15 | `_cluster` + `dedup_facts`（`episodic.py:76-150`，MiniLM+DBSCAN eps=0.25/min_samples=2，簇≥2 才调 LLM，≥15 按 12 分批） | 每 conv | facts → 合并 facts（模式 A/B/C） | 1/簇（合并角色） | – | `P-DEDUP`（C 模式含 `P-CONFLICT`） |
| A16 | `load_episodic`（`load.py:181-199`） | 每 conv | facts → **独立图** `{conv}__episodic`，space `episodic_memory`；溯源改存 `metadata.source_unit_uids`（跨图边静默失败） | no | 独立图 | `P-EMBED` + `P-PERSIST` |
| A17 | `build_entities`（`kg.py:37-68`） | 每 session | 会话 → 实体（13 类 schema） | 1/session | – | `P-EXTRACT` + `P-META` |
| A18 | `dedup_entities`（`kg.py:114-157`，MiniLM + AgglomerativeClustering，threshold 0.85） | 每 conv | 实体 → 归并实体 | 1/簇 | – | `P-DEDUP` |
| A19 | `build_relations` + `build_cross_session_relations`（`kg.py:160-226`） | 每 session / 每 conv | 会话 + 实体清单 → 关系（**清单漏 entity_id**） | 1/session + 1 | – | `P-LINK`（**产物 0 条落地**） |
| A20 | `load_kg`（`load.py:202-235`） | 每 conv | 实体 → 独立图 `{conv}__kg`，space `entity_relation:entities`；关系按名字查 uid → 全部 miss | no | 独立图 | `P-EMBED` + `P-LINK`（失效） |
| A21 | marker 落盘（`orchestrator.py:94-95`）+ `_persist()`（`server.py:369`） | 每 conv / 每次 snapshot | 结果 json + 全部图 save_graph | no | 磁盘 | `P-PERSIST` |

### 5.3 检索 —— P1/P2 态（`TRITOWER_ON=0`，默认）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| A22 | scope 定位（`server.py:250-257`） | 每 query | `filter.scope_id` → 该 conv 的独立图 | no | – | `P-SYMFILTER` |
| A23 | `search_similarity_in_graph(query, top_k=20, ms_names=[conv])`（`server.py:281`） | 每 query | query → dense top-20；**空间过滤把候选集裁到 conv space 的 L0 单元**（`semantic_map.py:2186-2192,2539-2557`） | no | FAISS | `P-SYMFILTER` + `P-DENSE` |
| A24 | envelope 渲染（`server.py:294-302`，`raw_format="mandol_unit"`，text ≤600） | 每 query | unit → 统一 envelope | no | – | `P-ASSEMBLE` |

### 5.4 检索 —— P3 态（`TRITOWER_ON=1`）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| A25 | 三塔并行（`retrieve.py:275-279`，`max_workers=3`） | 每 query | query → 三塔 | no | 三图 | —（调度） |
| A26 | hierarchical 塔 15 条（`retrieve.py:129-144`）：逐层 L0/L1/L2 各 bm25+cosine+splade → RRF → bge 重排 | 每 query | query → 15 | no | base 图 | `P-SPARSE`+`P-DENSE` → `P-FUSE` → `P-RERANK` → `P-FUSE` |
| A27 | episodic 塔 30 条（`retrieve.py:119-126,277`） | 每 query | query → 30 | no | episodic 图 | 同上（无跨层） |
| A28 | kg 塔 30 条（`retrieve.py:278`） | 每 query | query → 30 | no | kg 图 | 同上 |
| A29 | 拼接 75 条（`retrieve.py:282-284`）——**无跨塔重排、无加权融合** | 每 query | 3×list → 75 | no | – | —（无操作，见 §6.2-B1） |
| A30 | `_to_chunks`：entity_ids（KG 实体名 / episodic entities / 其他用 **speaker** / NER 兜底）+ `source_chunk_ids or [chunk_id]` + timestamp→epoch（`retrieve.py:160-260`，受 `CASCADE_IDS_ON` 门控，**默认关**） | 每 query | 75 → EnhancedCandidateChunk | no | – | `P-META` |
| A31 | Cascade stage1 MAD（mad=3.0） | 每 query | 75 → 过阈（实测 97.3% 不剔） | no | – | `P-SELECT` |
| A32 | Cascade stage2 跨塔冲突（仲裁分含 720h 指数时间衰减 + tower_trust 1.0/0.8/0.6） | 每 query | → 去冲突（实测中位丢 3 条） | no | – | `P-CONFLICT` |
| A33 | Cascade stage3 MMR（λ=0.7，`max_tokens` 取类默认 **4096**，`cap_to_input`） | 每 query | → 选中集（实测 token 中位 2,682） | no | – | `P-SELECT` |
| A34 | 去重 + 截断到 20（`retrieve.py:317-326`） | 每 query | → ≤20 | no | – | `P-SELECT` |
| A35 | envelope 渲染（`raw_format="mandol_tritower"`） | 每 query | → 统一 envelope | no | – | `P-ASSEMBLE` |

---

## 6. 分歧清单

### 6.1 论文 ↔ 上游代码（paper ↔ `AgentCombo/Mandol` @ `6d7af4f`）

| # | 分类 | 分歧 | 论文证据 | 代码证据 |
|---|---|---|---|---|
| A1 | **[paper-only]** | **DuckDB 持久化后端不存在**。论文 §3.2/§4 与 Table 1 三处声明用 DuckDB 作 in-process 持久化后端 | txt:220（Table 1 "In-process DuckDB"）、txt:437-439、txt:797-801 | 全仓库（含 pyproject / docs / website，排除 uv.lock）**grep "duckdb" 零命中**；实际嵌入式存储是 `rocksdict==0.3.29`（`pyproject.toml:53`，`src/mandol/storage/rocksdb_payload_store.py`） |
| A2 | **[paper-only]** | **Table 2 的三个核心 API 不存在**：`quantitative_search(query,[params])`、`search_unit(query, memory_space, type)`、`build_memory_from_raw(sample_id, extraction_style,[session_date])` | txt:706-716（Table 2） | 全仓库 grep 三个名字**零命中**。存在的只有 `traverse_explicit_nodes`（`semantic_graph.py:1337`）、`traverse_implicit_nodes`（`:1434`）、`add_relationship`（`:610`）、`save_graph`（`:1626`） |
| A3 | **[两边都有但行为不同]** | **路由输入不同**：论文说 lightweight intent classifier 用 query 特征（时间表达、实体提及）在线判断；代码直接读**数据集 gold category** | txt:461-472 | `locomo_triple_router.py:1177` `category = qa_item.get("category", 1)` → `:1385` → `locomo_tower_router.py:106-119` 静态表；`adaptive_category.py:86 get_adaptive_params(query_category=…)` 同样吃 gold |
| A4 | **[两边都有但行为不同]** | 论文的路由是**按 query 动态选源**；GPT-4.1-mini（论文最好成绩 92.21% 的 backbone）的路由表**五类全等于 `_cfg_full()`**，即恒等映射，路由实际不产生任何差异 | txt:465-470 | `locomo_tower_router.py:106-119` |
| A5 | **[paper-only]** | **emotional memory 从不构建**。论文四次声明四类记忆源（含 emotional / user preferences / preference-evolution chains） | txt:89、txt:285-288、txt:460、txt:755-758 | `hierarchical_prompts.py:35-38` `locomo_types()=[STRUCTURED]`；`:40-43` `longmemeval_types()=[EPISODIC, KNOWLEDGE]`——**两个 benchmark 都不建**。`L1_EMOTIONAL_PROMPT`（`:139`）与 `EMOTIONAL` 枚举存在但无实验路径 |
| A6 | **[paper-only]** | **selective subgraph expansion 在主复现路径上是死代码**。论文把图扩展列为多跳证据补全的关键机制 | txt:477-480 | `locomo_tower_router.py:66-74` `_cfg_full()`：`topk_graph=0` + `use_entity_relation=False`；`locomo_triple.py:3359` `use_entity_relation = (not no_entity_relation) and (topk_graph > 0)`，`--topk-graph` 默认 0 → `locomo_triple_router.py:1898` 从不执行 |
| A7 | **[两边都有但参数不同]** | Eq.(1) 的 κ：论文 2.5（代码默认亦 2.5），**产生论文数字的脚本传 3.0** | txt:657,672 | `cascade_pruner.py:186` 默认 2.5；`run_reproduction_suite.sh:354,380,406,431,457,483,508,535,560,585,612,641,670,697` 全部 `--cascade-mad-multiplier 3.0` |
| A8 | **[两边都有但参数不同]** | Eq.(3) 的 λ：**论文未给数值**；代码默认 0.6；脚本传 0.7 | txt:680（Eq.3 只有符号 λ） | `cascade_pruner.py:191,1133` 默认 0.6；脚本 `:355…` `--cascade-lambda-mmr 0.7` |
| A9 | **[code-only]** | 论文 Eq.(2) 只给了 `w_rel/w_temp/w_source` 三个符号，未给权重；代码硬编码 **0.5/0.3/0.2**，且把 `f_source` 实现为 `tower_priority`（1.0/0.8/0.6，与论文文字一致） | txt:626-638（只有 1.0/0.8/0.6 三个 source 权重） | `cascade_pruner.py:628-630,134-138` |
| A10 | **[code-only]** | 论文未提及**剪枝模式**这一维；代码有 5 种 `PruneMode`，脚本对同一 backbone 跑了 STRICT_THRESHOLD / CLIFF_EARLY_STOP / BUDGET_MAX / DYNAMIC_ADAPTIVE 四种，token 上限 1500/1800/2000 各不同 | — | `confidence_pruner.py:21-27`；`run_reproduction_suite.sh:356-357,382-384,408,433-435,459-460,485-486,510-513,537-540` |
| A11 | **[code-only]** | 论文的 f_source 三类是 basic/episodic/semantic；代码的三塔是 hierarchical（**L0 基础 + L1/L2 抽象混在一起**）/episodic/kg，1.0 这一档并非纯 basic | txt:633-638 | `cascade_pruner.py:134-138` `TowerSource.HIERARCHICAL: 1.0`；`hierarchical_retriever.py:107-111` 该塔同时覆盖 L0/L1/L2 |
| A12 | **[code-only]** | 论文的写入侧完全没有 **LLM 去重/合并**步骤；代码在 episodic 与 kg 两条线各有一次「聚类 + 逐簇 LLM 合并」 | — | `locomo_episodic_memory/step2_deduplicate_and_enhance.py`；`locomo_graph_maker/step1_locomo_entity_extractor.py:483-500,618-667` |
| A13 | **[code-only]** | 论文没写 **God Mode 逐句改写**（只写了轻量的 session-level context enhancement 示例：加 `[Time \| Topic]` 前缀）；代码是对**每条 message** 重发整段 transcript 做全局指代消解与绝对时间换算，成本量级完全不同 | txt:292-299 | `step1_generate_l0_graph.py:29`（CONTEXTUAL_RETRIEVAL_PROMPT，含 "God Mode" 字样）、`:568-611` |
| A14 | **[code-only]** | 论文强调「检索全程不调 LLM」；代码检索路径确实零 LLM ✓，但**答题 prompt 注入数据集 gold category 及针对性提示**，这一点论文全文未提 | txt:31-33,110-112,459 | `locomo_triple_router.py:2147-2149` |
| A15 | **[两边都有但行为不同]** | 论文说 implicit semantic edges「computed on demand during queries via semantic indexes」；代码的实现就是 dense/sparse 检索本身，没有任何「隐式边」实体 | txt:266-270 | `semantic_graph.py:1434 traverse_implicit_nodes` 存在但主复现路径不调用（`grep traverse_implicit` 在 `benchmark_locomo/task_eval/` 零命中） |

### 6.2 上游代码 ↔ memory-bench 适配层（`AgentCombo/Mandol` ↔ `servers/mandol/`）

| # | 分类 | 分歧 | 上游证据 | 适配层证据 |
|---|---|---|---|---|
| B1 | **[两边都有但行为不同]** | **缺二段统一重排与预筛**：上游把三塔 75 条合并后用同一个 cross-encoder 重打分，再按 `tower_separate` 保留全部 L0 + graph/episodic 前 20，**约 35 条**进级联；适配层直接把 75 条原样送进级联，用的是各塔内部的重排分 | `locomo_triple_router_quantification.py:690`（`reranker.rerank(query, documents)`）、`:698-710`（`_keep_indices`） | `towers/retrieve.py:282-289`（拼接后直接 `_to_chunks`）；实测 `cascade.stage1_in` 恒为 **75** |
| B2 | **[两边都有但参数不同]** | **token 预算**：脚本传 `--cascade-max-context-tokens 1500/1800/2000`；适配层未传，取 `CascadeConfidencePruner` 类默认 **4096** | `run_reproduction_suite.sh:358,384,409,435,461,486`；`locomo_triple_router_quantification.py:308` `max_tokens=cascade_max_context_tokens` | `towers/retrieve.py:297-302` 只传 mode/mad/λ/abs_min；实测 cascade token 中位 2,682、98.0% >1500、最大 4,096 |
| B3 | **[code-only（上游有适配层没有）]** | **融合权重未实现**：上游把 `weight_hierarchical/graph/episodic` 存进 `fusion_weights`（`:1349-1354`）；适配层只在 docstring 里列了 0.34/0.33/0.33，代码**无任何使用点** | `locomo_triple_router.py:1348-1354,3588` | `towers/retrieve.py:12`（docstring）—— grep `weight` 在实现体中零命中 |
| B4 | **[两边都有但行为不同]** | **KG 关系边**：上游 `step2:381` 的候选清单带 `entity_id`，关系可解析落地；适配层 `_entity_candidates_text` 漏 entity_id，叠加 `load_kg` 键名/映射基准错误、跨会话结果键名错误，共四层 → **5,208 条关系 0 条落地** | `step2_locomo_relation_generator.py:381` | `towers/kg.py:90-111,220`；`towers/load.py:223-234`；marker 实测 |
| B5 | **[两边都有但行为不同]** | **溯源边**：上游 episodic/kg 与 base 同在一张统一图（`build_unified_graph.py`），`source_unit_uids` 可连边；适配层三塔分三张图，跨图 `add_relationship` 静默返回 False → episodic/kg **各 0 条溯源边**，改存 `metadata.source_unit_uids` | `benchmark_locomo/dataset_maker/build_unified_graph.py`；`semantic_graph.py:644-649` | `towers/load.py:106-121,195-198`；marker：conv-41…50 的 `episodic.edges`/`kg.edges` 全为 0 |
| B6 | **[两边都有但参数不同]** | **构建侧 temperature**：上游各 step 0.1（实体去重 0.05）；适配层强制 0（契约 §7） | `step1_generate_l0_graph.py:603`、`step1_locomo_entity_extractor.py:620` 等 | `towers/llm.py:37,52` |
| B7 | **[两边都有但参数不同]** | **重排 dtype/device**：上游无条件 `torch_dtype=torch.bfloat16` + cuda/cpu 二分支；适配层 monkeypatch 成 float32 | `rerank_manager.py:443,462` | `towers/retrieve.py:59-78` |
| B8 | **[code-only（适配层有上游没有）]** | **conversation 粒度断点续跑**：上游 8 个 step 零断点；适配层每 conv 写 `.done.json` | 三条 pipeline 脚本无 resume | `towers/orchestrator.py:35-40,94-95` |
| B9 | **[code-only（适配层有上游没有）]** | **L1/L2 展平**：上游 step4 载入的是 L1/L2 结构化产物的既定文本；适配层加了 `_flatten_extraction`（限长 1200/2000），实测均值 1,228 字符 | — | `towers/load.py:124-151` |
| B10 | **[两边都有但行为不同]** | **路由**：上游按 gold category 查表（GPT-4.1-mini 下恒等）；适配层完全不接 router，固定等价于 `_cfg_full()` | `locomo_tower_router.py:106-119` | `towers/retrieve.py:21-22`（说明）；`server.py:259-263` 无 category 入参 |
| B11 | **[两边都有但行为不同]** | **输出形态**：上游产出三塔分节的完整答题 prompt（graph 只放前 10 条）并注入 gold category；适配层产出扁平去重的 ≤20 条 envelope，答题 prompt 由 harness 统一构造、不注入 category | `locomo_triple_router.py:2152-2175,2147-2149` | `server.py:267-278`；`bench/runner.py:276` |
| B12 | **[两边都有但行为不同]** | **P1/P2 的检索面**：上游没有「只用 dense 单路」的对照态；适配层的 P1/P2 用 `search_similarity_in_graph(ms_names=[conv])`，该 space 只含 L0 单元，**抽象层被结构性排除** | — | `server.py:281`；`semantic_map.py:2186-2192,2539-2557`；落盘 `conv-26` space 419 uid 全为 L0 |
| B13 | **[两边都有但参数不同]** | **embedding 后端**：上游/论文用 Qwen3-Embedding-0.6B（论文 txt:1170）；适配层用智谱 embedding-3 / 2048 维云端 | txt:1170,1277 | `server.py:108,187-192` |
| B14 | **[两边都有但参数不同]** | **构建侧模型**：官方 dataset_maker 用 qwen3.5-plus-thinking / deepseek 系；适配层统一 glm-5.3 | `benchmark_locomo/dataset_maker/**/scripts/*.sh` | `towers/llm.py:42-47`（`MEMBENCH_LLM_*`）；repro-plan §5 已声明 |
| B15 | **[两边都有但参数不同]** | **图架构**：上游按 sample_id 分图但三塔合入统一图；适配层是 base/episodic/kg **三张独立图** × 10 conv = 30 张 | `build_unified_graph.py` | `server.py:104-106`；`towers/orchestrator.py:71,80`；落盘 30 个目录 |

---

## 7. 新造的 primitive 标签

**none。** 本次 mandol 复核未新造任何标签，全部命中种子词表：
`P-INTAKE / P-REWRITE / P-EXTRACT / P-META / P-EMBED / P-DEDUP / P-CONFLICT / P-LINK / P-AGGREGATE /
P-PERSIST / P-EVICT / P-QUERYPARSE / P-DENSE / P-SPARSE / P-SYMFILTER / P-GRAPHEXPAND / P-FUSE /
P-RERANK / P-SELECT / P-ASSEMBLE / P-GENERATE / P-ANNINDEX`。

两处**标签复用说明**（不算新造）：

1. `P-SPARSE` 种子定义是检索侧 BM25，本报告在写入侧用 `~P-SPARSE` 标注 **SPLADE 稀疏编码**
   （A3 / C13）。理由：种子词表写入侧只有 `P-EMBED 稠密编码`，没有稀疏编码槽位；
   SPLADE 产出的是稀疏向量而非稠密向量，硬塞进 `P-EMBED` 会丢掉「三路召回的 sparse 通道依赖它」这一信息。
2. `P-SELECT`（组合优化选择 / 阈值截断）在本系统里承担了**三个不同 stage**：Eq.(1) 的 MAD 阈值截断、
   Eq.(3) 的 MMR 贪心打包、以及最后的去重截断到 top-20。种子定义（"Kruskal森林/贪心/1-swap/阈值截断"）
   四项里占了两项，不必拆分。

---

## 8. 复核统计

| 判定 | 条数 | 占比 |
|---|---|---|
| ✓ 属实 | **80** | 76.9% |
| ✗ 不实 | **5** | 4.8% |
| ◐ 部分属实/需加限定 | **16** | 15.4% |
| ? 无法核实 | **3** | 2.9% |
| **合计** | **104** | |

`✗` 五条：#15（P2 的 L1/L2 是被空间过滤排除，非"检不回"）、#53（`raw_format` 实为 `mandol_unit`）、
#66（跨塔冲突 2–4 条的比例实为 78.2%/87.6%，非 65%）、#75（λ=0.6 是代码默认，非论文 Eq.(1)）、
#85（P3 的级联 stage2 含 720h 指数时间衰减，"不衰减"不成立）。

`?` 三条均为**缺归档产物**而非可疑：#7（跑分报告不在挂载范围）、#73（125→18 ms/对 的原始计时）、
#101（旧 JSON dump 态的 37s 计时）。三条都有 repro-plan §12 的书面记录且与其他实测自洽。

按文档区块看质量分布：**构建侧（2.4）18 条中 16 ✓ / 2 ◐，读取侧数值（2.5 的 #56-#71）全绿**，
是文档最可靠的部分；问题集中在**「先回答三个常见问题」的机制概括**与**「检索路径上没有什么」的否定式断言**——
后者本就是最难写对的一类，本文档 8 条否定式断言中 4 条需要修正或加限定（#84 router、#85/#86 时间衰减、
#15/#51 抽象层可见性），其余 4 条（图遍历、KG 关系边、emotional、gold 注入）经代码链路追证**全部成立**，
其中「图遍历」与「emotional」两条我追到了比文档更强的证据。

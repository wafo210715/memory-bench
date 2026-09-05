# GraphMemix 代码架构

> 调研对象：`/Users/guanhongli/Documents/repo/graphmemix`（官方 `ligeng0197/graphmemix`，克隆时 `HEAD=d0ea01d`）。
> 本文档只读代码得出结论，证据格式为 `文件:行号`。
> **2026-09-05 勘误**：本文已按同目录 `verification.md` 的逐条复核结论修正（共 26 处：2 处事实、11 处行号/锚点、13 处表述限定）。原始未修正版本见 git 历史。

## 1. 一句话机制

GraphMemix 不是"算相似度排 top-k"，而是每道题到来时现算一次组合优化：从多视角检索种子出发，沿"同一轮/连续对话轮次/语义近邻"关系扩出一张几十个节点的候选图，用一个 LLM 给每条候选打"这条本身有没有用"的分（node verifier），再用另一个 LLM 只看"锚点—候选"之间已有 schema 关系的那些边判断"接在锚点后面算不算新信息"（ECV，六选一角色），最后用 Kruskal 算法在打好分的图里选出"总收益最大"的一片森林（先 1-swap 爬山定下 K 个节点，再在这 K 个节点范围内穷举子集精确求解），交给 reader 模型生成答案。

**但要先说清楚一件事**：这套"候选图构建 → 验证 → 森林优化"算法本身（`scripts/build_graphmemix_relation_store.py`、`score_graphmemix_verifier.py`、`score_graphmemix_ecv.py`、`evaluate_graphmemix_ecv.py`、`evaluate_graphmemix_exact_pruning.py`）在这个仓库里自包含、可读、可独立验证；但真正把"写入的多模态记忆编码成向量"和"query 时刻多视角检索出种子/把选中证据拼成最终 prompt"这两头粘起来的胶水类 `ConcreteMemixMethod`（`src/mm_memory_bench/methods/concrete_memix.py`），构造函数里硬性要求一个这个仓库没有、README 也没给下载方式的外部私有仓库 `vendor/memix-core`（concrete_memix.py:48-52,268）。也就是说，只读这个仓库能完整验证"选证据"的算法对不对，但没法在本地从零跑通"写入→检索→生成"整条链路。

## 2. 记忆是怎么存进去的

**触发时机**：`run_graphmemix_release.py` 编排的 9 个 stage（checkpoint→priors→relations→node→ecv→select→prune→reader→judge，run_graphmemix_release.py:23）里，第 1 个 `checkpoint`（run_graphmemix_release.py:111-120）**按 dataset**（不是按 benchmark/backbone 组合）一次性把整个 archive 编码完，不是逐条实时写入——checkpoint 产物路径 `checkpoints/{dataset}`（configs/release/graphmemix.json:53、run_graphmemix_release.py:84）与 backbone 无关，两个 backbone 复用同一份编码结果（只有 `run_root` 才带 backbone，run_graphmemix_release.py:93）；priors 同理（`source_priors/{dataset}.jsonl`，run_graphmemix_release.py:85）。

**存的是原文，不是摘要**。`ConcreteMemixMethod._adapt_memory`（concrete_memix.py:397-499）的具体流程：
- 每条原始记忆（email/图片/视频/文档）把 `metadata.derived` 里数据集**自带**的派生字段（短摘要、caption、OCR、地点、tags 等——这些不是 GraphMemix 自己生成的，是数据集发布方处理好随包分发的，concrete_memix.py:420-441）拼成一段文本，连同 `source_id`/`timestamp`/`session_id` 等头信息存进 `record["text"]`；原始图片/视频路径单独存 `image_path`/`video_path`，`content`（原始 asset 引用）整份保留（record 字典在 concrete_memix.py:456-465，其中 `image_path` 在 :460、`video_path` 在 :461、`"content": [dict(part) for part in memory.get("content", [])]` 在 :463）。
- 每条记忆切出多个"embedding unit"（对应论文说的"view"）：每张图一份、视频每帧一份，可选再切原子文本句子（`media_atomic_limit`，生产配置默认关闭）（concrete_memix.py:466-498：467-471 每图一份、472-487 视频每帧一份）。**注意纯文本 unit 不是无条件产生的**：:488-489 的 `if not units: units.append({...})` 说明它只是"一条媒体 unit 都没有时"的兜底，图像/视频记忆**不会**额外产生一份纯文本 unit，文本被塞进每个媒体 unit 的 `text` 字段（:469/:483）。
- 这些 unit 批量传给多模态编码器（`self.embedder.encode_units`，配置里是 `gme-Qwen2-VL-2B-Instruct`，1536 维），向量存进 FAISS Flat-IP 索引，按 context 分文件落盘为 `state.json` + `index-*.faiss`（`_flush_pending`，concrete_memix.py:365-382，:370 `encode_units`、:373 `index.add`、:382 调 `_save_checkpoint`；`_save_checkpoint` 本体在 concrete_memix.py:875-903，:883 写 `index-{version:08d}.faiss`、:896 写 `state.json`）。

**调不调 LLM**：**本仓库可见的 ingest 代码路径内不调**。整条 ingest 路径（`_ingest`→`_adapt_memory`→`_flush_pending`，concrete_memix.py:337-396）只出现 embedding 调用，没有一次 chat/completion 调用（`build_memix_checkpoints.py:19-21` 的 `UnusedAnswerModel.complete` 一旦被调用直接抛错，checkpoint stage 实跑即可证否）。**但"整条流水线零 LLM"不成立**：h2hmem 的写入侧依赖一份**仓库外用 LLM 生成的冻结 caption sidecar**——`run_graphmemix_release.py:118-119` 在 dataset 为 h2hmem 时追加 `--caption-sidecar`（路径 `captions/{dataset}.jsonl`，configs/release/graphmemix.json:56），`BundleReader` 只**读**它（reader.py:34,44-45），全仓库 `grep -rn caption_sidecar` 的 20 处命中全是消费方，**没有任何生成这份 sidecar 的脚本**；论文 Appendix A.1（txt:1826-1828）说明它是用 `Qwen/Qwen3-VL-8B-Instruct` 离线生成的。

**关系图是另一个独立脚本、也在写入侧构建**：`build_graphmemix_relation_store.py`（"relations" stage）不依赖 memix-core：
- **schema 边**：纯读 metadata。同一个 `metadata.native_round_id` → `same_round`；同一个 `session_id` 内按 `sequence` 相邻 → `consecutive_turn`（`explicit_edges`，build_graphmemix_relation_store.py:70-101）。另有一个可选的 `spatiotemporal_event`（同 context 内时间差、距离都在阈值内的两条媒体相连，`spatiotemporal_edges`，build_graphmemix_relation_store.py:152-186），但两个阈值参数默认是 0（函数直接 `return {}`），且 `run_graphmemix_release.py` 的 relations stage 命令（run_graphmemix_release.py:134-139）没有传这两个参数——生产配置下这个通道是关的。
- **语义边**：取每条记忆的"canonical vector"（`reconstruct_vectors`，build_graphmemix_relation_store.py:209-222）。**这里代码行为和该文件 docstring 的措辞不一致**：docstring（build_graphmemix_relation_store.py:4-8）说"第一个非 atomic 的 embedding unit"才是 canonical graph view，但 `canonical_unit_rows`（:60-67）收集的是每条记忆**全部**非 `representation` 行，:220-221 把这些行**全部**归一化后取均值再归一化——所以不只视频，多图记忆同样是"所有 canonical unit 的归一化均值"，只有单图/纯文本记忆下两种说法才等价。取到 canonical vector 之后，在 FAISS 里做 mutual top-k 近邻（`mutual_neighbors`，build_graphmemix_relation_store.py:225-254；k 由 `--max-semantic-k` 控制，生产配置是 8）。
- 同样不调 LLM，纯向量/metadata 计算。

## 3. 记忆是怎么被用起来的

**触发时机**：每道题触发一次；node→ecv→select→prune→reader 五个子阶段严格按顺序跑，各自把结果落盘成 jsonl 供下一阶段读（run_graphmemix_release.py:141-224）。

**拿什么去找**：
1. **多视角检索定位种子**（"priors" stage，`run_memix_main_track_retrieval.py` 直接调 `ConcreteMemixMethod._source_detail`，concrete_memix.py:558-577）：把 query 的每个视图（每张问题图、视频每帧）分别编码去 FAISS 查 top-k（`_question_units`，concrete_memix.py:544-556，与写入侧的 unit 切分同构：**有媒体时不会另外产生一份独立的纯文本 query 视图**，:556 的 `return units or [{"text": text}]` 只是无媒体时的兜底），同一个 `memory_id` 只留各视图里分数最高的那个（`best[memory_id] = max(best.get(memory_id, -inf), score)`，concrete_memix.py:568-577），凑出 200 条（`source_top_k`）候选——这就是论文 Eq.3 的 max-pooling 在代码里的样子。
2. **候选图扩展**（`candidate_pool`，graphmemix_core.py:83-105）：取前 24 条（`source_top_l`）当种子，顺着 relation store 的边扩 1 跳（**排序键其实只是 `(-similarity, source_rank, neighbor)`，graphmemix_core.py:97-98，没有任何按关系类型的优先规则——关系标签在 :95 就被丢弃成 `_` 了**；explicit 边之所以总排在前面，是因为 `explicit_similarity` 被固定成 0.99（build_graphmemix_relation_store.py:267,336）而 `edge_similarity` 取 explicit/semantic 的 max（graphmemix_core.py:41-52），这是常数取值的副产品，把 `--explicit-similarity` 调低即失效），去重后补到 48 条（`candidate_limit`）。

**不是一步到位，是"两次 LLM 打分 + 两阶段确定性求解"**：
- **Node Verifier**（"node" stage，`score_graphmemix_verifier.py`）：一次 listwise 调用，把全部候选（含 modality/date/location/retrieval_score/snippet）打包成一个 JSON 发给 backbone 模型，模型给每条候选打 0-5 分，不返回即算 0 分（score_graphmemix_verifier.py:255-330；`output_schema`见 313 行）。
- **ECV**（"ecv" stage，`score_graphmemix_ecv.py`）：先从候选里按检索序选 10 个（`anchor_count`）当"锚点"（默认 `anchor_mode=atomic`，不看 verifier 分数）；只对"锚点—候选"之间**relation store 里已有 schema 边**的那些 pair（`eligible_anchor_relations`，语义近邻边不参与）打包发给 LLM。模型对每条候选返回：`direct_support`（生产配置里 `--edge-only` 强制置 0，复用 node 阶段的分，score_graphmemix_ecv.py:35-42,552）、`incremental_support`（0-5，"锚点已知的前提下这条新加了多少信息"）、`role`（六选一：`new_fact`/`clarification`/`corroboration`/`redundant`/`conflict`/`irrelevant`，score_graphmemix_ecv.py:30-31,533）。只有正分 + 前三种角色的边会保留参与后面的图（`positive_edges`/`conditioned_adjacency`，evaluate_graphmemix_exact_pruning.py:32-47，evaluate_graphmemix_ecv.py:31-45）。
- **Select：1-swap 爬山 + Kruskal，定下 K 个节点的提案**："select" stage（evaluate_graphmemix_ecv.py，直接 `from probe_graphmemix_pcsf import solve_forest_greedy`，第 16 行）：节点值 = `sigmoid(a·atomic_score + b·verifier_score + c)`（校准系数来自 `configs/release/calibration/shared_dev.json`）；边的"收益" = `root_cost(0.2) − edge_weight(0.1)·(−log(similarity))`。从 Top-10 节点效用起步（初始化在 probe_graphmemix_pcsf.py:204），每轮**扫遍全部"换一个选中的出去、换一个没选的进来"的组合、再取其中最好的那个**换（best-improvement，不是"首次遇到变好就换"：爬山循环在 probe_graphmemix_pcsf.py:206-220，:208-216 遍历全部 (removed, added) 组合，:215 的 `if proposal_value > value + 1e-12 and (best is None or candidate[:3] > best[:3])` 一路比到最优才收），直到没有能改进的交换；**但"当前这 K 个节点怎么连边"是精确算的**——候选边按收益从高到低排序，用并查集依次加边、成环就跳过，这是标准 Kruskal 求最大权森林（在 `forest()` 内部，probe_graphmemix_pcsf.py:188-200：:188-194 组装正收益边、:196 `sorted(weighted, key=lambda row: (-row[0], row[1], row[2]))` 排序、:197-199 并查集判环、:200 合并累加），diagnostic 明确标 `"exact": False`（probe_graphmemix_pcsf.py:249，指的是"选哪 K 个节点"这件事不是穷举）。
- **Prune：穷举 + Kruskal 做变基数精修**："prune" stage（evaluate_graphmemix_exact_pruning.py）：在 select 阶段选出的 ≤20 个节点范围内，把 2ⁿ−1 个非空子集**全部**枚举，每个子集精确跑一次 Kruskal 求最大权森林，取目标函数值最高的子集+森林（`exact_subset`，evaluate_graphmemix_exact_pruning.py:50-124：枚举循环 :78-108、每子集的 Kruskal :89-97、目标值 :99-102、确定性 tie-break :103-107；超过 20 个节点会直接抛异常，第 62 行）。这一步是真穷举，但只在"1-swap 已经筛过一遍"的小集合里穷举，不是在全部 48 个候选里穷举；而且 **"≤20"只是防御性上界、不是运行规模**——生产下 select 恒返回 K=10（`reader_k=10`，configs/release/graphmemix.json:34、run_graphmemix_release.py:187），实际搜索空间是 2¹⁰−1=1023。

**找到之后怎么交给模型**：证据按"每个连通分量选效用最高的点当根、按根的效用给分量排序、分量内部宽度优先遍历"的顺序排好（`probe_graphmemix_pcsf.py` 里 `solve_forest`/`solve_forest_greedy` 末尾的 BFS 排序逻辑）；"reader" stage 调 `ConcreteMemixMethod._generate_answer`（concrete_memix.py:759 起，被 `run_memix_answers_from_retrieval.py` 复用）把排好序的证据（原文文字 + 原始图片/视频帧）拼成一个多模态 prompt，发给**同一个** backbone 模型（Qwen3-VL-8B-Instruct 或 Gemma-4-12B）生成最终答案。

## 4. 架构图

```mermaid
flowchart TB
    subgraph MEM["记忆系统 GraphMemix（本仓库源码可读）"]
        direction TB
        subgraph WRITE["写入侧：一次性 digest<br/>仓库内 ingest 路径零 LLM 调用<br/>（h2hmem 例外：依赖仓库外 LLM 生成的冻结 caption sidecar）"]
            A1["原始多模态记忆<br/>email / 图片 / 视频 / 文档"]
            A2["多视角切分拼装文本<br/>concrete_memix.py _adapt_memory"]
            A3["多模态编码器 GME-2B<br/>存入 FAISS Flat-IP 索引"]
            A4["Relation Store 构建<br/>build_graphmemix_relation_store.py<br/>schema 边(metadata) + 语义 mutual-kNN"]
            A1 --> A2 --> A3
            A2 --> A4
        end
        subgraph READV["读取侧：每题触发一次"]
            direction TB
            B1["Query 多视角编码检索<br/>_source_detail，max-pool"]
            B2["candidate_pool<br/>Top-24 种子 + 1跳扩展 = 48 候选"]
            B3["Node Verifier LLM 调用一<br/>listwise 打 0-5 分"]
            B4["ECV LLM 调用二<br/>只判锚点-候选的 schema 边<br/>六角色判定"]
            B5["Select：1-swap 爬山 + Kruskal<br/>定 K=10 节点提案"]
            B6["Prune：2^n-1 穷举 + Kruskal<br/>冻结提案内精确变基数求解"]
            B7["按分量根效用排序+分量内BFS<br/>序列化证据"]
            B1 --> B2 --> B3
            B2 --> B4
            B3 --> B5
            B4 --> B5
            B5 --> B6 --> B7
        end
        A3 --> B1
        A4 --> B4
    end

    GLUE["外部依赖 vendor/memix-core<br/>本仓库没有源码也没给下载方式<br/>ConcreteMemixMethod 构造函数硬依赖"]
    A3 --> GLUE
    B1 --> GLUE
    B7 --> GLUE

    subgraph AGENTSIDE["backbone 模型（reader，agent 侧）"]
        C1["Qwen3-VL-8B 或 Gemma-4-12B<br/>接收有序证据 + 原始图片视频帧<br/>生成最终答案"]
    end
    B7 --> C1
    GLUE --> C1

    NOTE["提醒：B3 Node Verifier、B4 ECV<br/>和 C1 reader 在实验里是同一个模型权重<br/>区别只是这次调用的角色是什么"]
    NOTE --- B3
    NOTE --- B4
    NOTE --- C1

    style GLUE fill:#fff3cd,stroke:#d39e00
    style MEM fill:#e7f3ff,stroke:#0d6efd
    style AGENTSIDE fill:#e6ffe6,stroke:#28a745
    style NOTE fill:#f5f5f5,stroke:#999999
```

图中黄色框是关键：区分"记忆系统"和"agent"的边界不是"调没调 LLM"（Node Verifier / ECV 明明也调 LLM），而是"这次调用是在为选证据打分，还是在做最终回答"；同时提醒读者，本仓库能读到源码并验证的只有 relations/node/ecv/select/prune 五步，checkpoint/priors/reader 三步都要绕经黄色框里那个拿不到源码的外部仓库。

## 5. 我没搞清楚的

- **`vendor/memix-core` 到底是什么、从哪下载**：README 的"Data and Artifacts"给了数据集下载方式（HuggingFace `oking0197/graphmemix-benchmarks`），但完全没提这个私有代码仓库怎么获取。`checkpoint`（build_memix_checkpoints.py:41）、`priors`（run_memix_main_track_retrieval.py 内调用 `ConcreteMemixMethod`）、`reader`（run_memix_answers_from_retrieval.py:136,753,773,792）三个 stage 都会在构造 `ConcreteMemixMethod` 时因为缺这个仓库直接抛 `RuntimeError`（concrete_memix.py:48-52）。
- **`cli.py` 里另一条路径 `graphmemix run --method memix`**（cli.py:385-403,546-559）把候选图构建、验证、选择全部甩给 `self.core.retrieve_one(...)`，即完全委托给 `vendor/memix-core`，算法细节在本仓库完全不可见。不确定这是历史遗留/开发期接口，还是也曾被用来产出过论文数字——README 的复现说明只指向 `run_graphmemix_release.py` 这条 9 阶段脚本流水线。
- **校准系数 a/b/c 的拟合脚本没找到**：只看到拟合结果 `configs/release/calibration/shared_dev.json`（"protocol": "graphmemix-shared-logistic-devfold-1.0"，positives=8491，prevalence=0.135），**但缺的只是 logistic 拟合本身**——"按 SHA256 分 5 折"的切分协议其实就在仓库里：`score_graphmemix_verifier.py:28-30` 的 `def fold(question_id, folds=5)`（`int.from_bytes(digest[:8], "big") % folds`），使用点在 :351-354（`"dev" if fold(qid) == args.include_dev_fold else ...`）。真正找不到的是"用 gold 标签在 dev fold 上拟合出 a/b/c"的那段代码（`grep -rn "logistic|devfold|standardization|prevalence"` 全仓库只命中 `shared_dev.json` 自己）。数字对不对得上是靠反推公式验证的（见第 1 节的一句话机制），不是直接读到拟合脚本确认的。
- **`explicit_similarity=0.99` 是否该按 schema 类型区分**——这条放到第 6 节一起说。

## 6. 与论文的冲突点

1. **（本节最大冲突点，静态代码证据链完整，但未实机跑通验证）ATM-Bench 的 schema 关系类型和论文描述对不上，且按生产配置推演应该是空的。** 论文 Appendix A.1 明确说 ATM-Bench 的"query-independent schema graph"有三种关系：`event_bridge`（媒体间 1 分钟–1 小时、5 公里内，每条记忆最多保留 2 个近邻）、`same_record`（邮件间强引用/事件日期类别/主题相近）、`record_grounding`（邮件到媒体的日期+地点/内容匹配）。全仓库搜索这三个字符串：`record_grounding` 只在单元测试里出现一次，且是被当作"不合法的 ECV 角色"测试用例（tests/test_score_graphmemix_ecv.py:63，用来验证 ECV 六角色校验会把它规整成 `irrelevant`）——这恰好说明作者知道这个词，但从没把它实现成一种 schema 关系类型；`event_bridge`/`same_record` 则完全没有出现在任何代码里。真正的通用 schema 边构建函数 `explicit_edges()`（build_graphmemix_relation_store.py:70-101）只认 `metadata.native_round_id`（→`same_round`）和 `session_id`（→`consecutive_turn`）两个字段；而 `converters/atm.py` 里 email 和 media 两类记忆的 `memory_rows.append(...)`（atm.py:400,461）都没有设置这两个字段——对照之下 `memeye.py`、`mem_gallery.py` 显式写了 `session_id`/`native_round_id`；`h2hmem.py` **只写了 `session_id`**（h2hmem.py:260），`native_round_id` 一处都没有——这一条恰好和论文 Appendix A.1（txt:1833-1835）"it does not expose the paired native-round field required by `same_round`"对得上，是代码与论文相符的证据，不是缺陷。两个字段都不写的只有 `atm.py`（`_media_metadata`，atm.py:181-194，把未知字段统统塞进 `metadata["raw_metadata"]`；`sequence` 虽在 :473-474 被赋值，但 `explicit_edges` 必须先有非空 `session_id` 才会用到它，:94-95）。按这条代码路径推演，ATM-Bench 走 `explicit_edges()` 会得到 0 条边；再加上能覆盖"时间+距离"逻辑的 `spatiotemporal_edges()`（但没有"每条记忆最多 2 个近邻"的封顶）两个阈值参数默认是 0、`run_graphmemix_release.py` 的 relations stage 命令（run_graphmemix_release.py:134-139）也没传这两个参数，生产配置下这条通道同样是关的。这样推下来，ATM-Bench 实际跑出来的 relation store 里 schema 边应该是空的——但论文 Table 6 明确写了 ATM-Bench 每题平均有 6.23 条 "Fixed Edges"（schema 边），直接对不上（顺带更正一处数值排序：6.23 在四个数据集里是**第三高**而非第二高，Table 6 的顺序是 Mem-Gallery 7.34 > H2HMem 6.75 > ATM 6.23 > MemEye 6.07）。**没有下载数据实跑一遍 relations stage、看 `*.summary.json` 里的 `native_explicit_edges` 数字，我不能 100% 确认**——一个可能的解释是 HuggingFace 上发布的"unified"数据集快照是用一个比当前仓库 HEAD 更早/不同的转换器版本生成的，跟本地能读到的 `converters/atm.py` 源码对不上；但从纯代码审查角度看，这是我找到的最具体、最可验证、也最值得优先去实机确认的一处不一致。
2. **（复核后改判：这不是"论文↔代码分歧"，而是论文内部记号与取值之间的张力）`w_{ai}^{schema}`（论文 Eq.9 的"schema 关系可靠度上限"）在代码里是单个全局常数，不分 schema 类型。** 不管是 `same_round`、`consecutive_turn` 还是 `spatiotemporal_event`，`build_graphmemix_relation_store.py` 都用同一个 `--explicit-similarity`（默认 0.99）赋值；后续 `evaluate_graphmemix_ecv.py`/`evaluate_graphmemix_exact_pruning.py` 实际算边权重时，也是直接拿常数 `0.99` 乘 ECV 归一化增量分（`similarity = 0.99 * (incremental/5.0)**power`），完全没有读取 relation store 里按边区分的 `explicit_similarity` 字段，也没有区分是哪种 schema 关系。但把它当成"与论文的冲突"站不住：**论文自己就把它钉死成单一全局值**——§4.1（txt:1258）"We set the maximum schema reliability to 0.99"、§4.4.3（txt:1471）"The fixed variant assigns every eligible explicit schema edge the same query-independent reliability of 0.99"。代码的常数 0.99 与论文取值完全一致；真正的张力只存在于**论文内部**：Eq.9 的记号 gloss（txt:641）称它是 "schema-specific reliability ceiling"（暗示 per-type 分辨率），而论文实际给出的值只有一个。
3. **（复核后改判：这确实构成一处实现层分歧，不只是"容易被误读"）** 论文的断言比 Appendix A.2 那句带 "can" 的弱表述（txt:1860）强得多——正文两处是**无条件断言**：§4.1 txt:1314 "The node verifier and ECV each make one listwise call and execute in parallel."、§4.4.4 txt:1647 "The two verifiers have no serial dependency and execute in parallel"。代码这边，ECV 确实不消费 node 阶段打的分数（默认 `anchor_mode=atomic`），但**并不是"只共享同一份冻结候选集"**：`score_graphmemix_ecv.py:260` 的 `--candidate-cache` 是 **required** 参数，:406 的 `candidate_ids` 与 :486/:520 的 `query_captions` 都取自 node 阶段落盘的行（由 `score_graphmemix_verifier.py:355` 与 :360 写出），而 **query-image caption 的那次 LLM 调用只发生在 node 阶段**（`score_graphmemix_verifier.py:83-115`，调用点 :280-282）。也就是说 ecv 对 node 存在真实的**数据依赖**，要真并行必须先把 caption 那一步单独跑一遍。`run_graphmemix_release.py:141-176` 把它们编排成顺序 stage，就不只是产物缓存/一致性校验的工程选择了。
4. **Kruskal 求解器和 ECV 六角色判定本身——核实结论是"真实实现，且和论文高度一致"，不是冲突点，放在这里一并说明**：`probe_graphmemix_pcsf.py:188-200` 的 `forest()` 内部函数、`evaluate_graphmemix_exact_pruning.py:89-97`（`exact_subset()` 内的逐子集求解），两处都是标准 Kruskal（按收益排序 + 并查集判环）的真实实现，不是占位符或名不副实的函数名；`score_graphmemix_ecv.py:30-31` 的 `ALL_ROLES` 六个角色字符串、以及 `score_graphmemix_ecv.py:533` prompt 里原样出现的六个角色名，和论文正文"assigns one of six roles: new_fact, clarification, corroboration, redundant, conflict, or irrelevant"逐字对得上。论文 Eq.11-13 的目标函数、超参命名（`root_cost`↔κ、`edge_weight`↔λ）、Appendix A.5 的证据排序规则（"highest-utility node as root...breadth-first...ties resolved by node utility and then by the original retrieval order"）都能在代码里找到几乎逐一对应的实现，这是本次调研里代码与论文吻合度最高的部分。

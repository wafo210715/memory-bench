---
title: GraphMemix Paper ↔ 上游 Code ↔ memory-bench 臂 对照
date: 2026-09-12
tags:
  - memory-bench
  - paper-vs-code
  - graphmemix
---

# GraphMemix Paper ↔ 上游 Code ↔ memory-bench 臂 对照

> [!note] 口径
> paper = arXiv:2608.26983v1（Li, Wang, Li, Hao, Peng 2026，MemoraX AI Research Technical Report；本地纯文本版全文 2661 行）。
> 上游代码 = `ligeng0197/graphmemix` @ `d0ea01d`（该仓库唯一一次提交，工作区干净）。
> memory-bench 臂 = `servers/graphmemix/server.py`（约 870 行，文件头 12 条编号复现口径 note，2026-09-12 定稿），已在仓库根 `servers.yaml` 注册（`graphmemix:` 条目，`args: ["servers/graphmemix/server.py"]`）。
> 事实依据统一以同目录 `verification.md` 为准（1530 条断言全量基线的一部分，逐条复核结论 + 证据行号）；`paper-architecture.md` / `code-architecture.md` 是被复核的对象，不当事实源。
> 三者时间跨度很短——论文与上游代码同一批次产出，本臂晚约一周定稿——所以本表默认把「论文当下的表述」与「代码当下的行为」之间的矛盾判成文档脱节，只有证据本身指向机制被有意换掉时才判设计演进；不套用"相隔数年默认是演进"的宽松标准。
> 空格 = 该阶段在这一侧不存在。「默认死」= 代码完整、逻辑齐全，但默认配置不可达，不是坏了、也不是缺凭证。
> `verification.md` 的 C52 已经核实过 `w^schema`（Eq.9 记号里"schema 类型各自的可靠度上限"）那条不构成真实分歧——论文自己在 §4.1、§4.4.3 两处都把它写死成单一全局 0.99，与代码的硬编码常数完全一致。这条因此不出现在下面的差异清单里，只在此处交代排除理由。

## A 段 · 形成期（query-independent）

| 阶段 | Paper | 上游 Code | memory-bench 臂 |
|---|---|---|---|
| A1 intake | 用户历史被记为固定集合 V={e_i}（Eq.1，txt:520-533），论文没有描述这个集合怎么产生 | `checkpoint` stage 把统一 archive 转成 record，按 dataset 一次性编码、跨 backbone 复用（`concrete_memix.py:397-499`） | `add_conversation` 工具逐 session 写入，turn 级文本转成 canonical memory 记录，零生成式 LLM 调用 |
| A2 distill | 写入侧唯一的生成式调用是 H2HMem 图片的冻结 caption sidecar（Qwen3-VL-8B-Instruct，A.1 txt:1826-1828），其余三个数据集用发布方自带的派生字段 | 只消费 `caption_sidecar` 字段（`run_graphmemix_release.py:118-119`、`reader.py:34,44-45`），生成该文件的脚本本身不在仓库内 | 空（LoCoMo 纯文本、无图像，caption sidecar 这一整条场景不存在） |
| A3 admit | | | |
| A4 index | 离线一次建 discovery graph `G_disc = E_schema ∪ E_sem`（Eq.4，txt:569）：schema 边按数据集给专属规则（ATM 三种含 event_bridge/same_record/record_grounding；Mem-Gallery/MemEye 用 same_round+consecutive_turn；H2HMem 只用 consecutive_turn，因为它没有配对的原生 round 字段）；语义边用共享编码器算 mutual top-8 近邻 | `explicit_edges()` 只认两个通用字段（`native_round_id`→same_round、`session_id`+`sequence` 相邻→consecutive_turn，`build_graphmemix_relation_store.py:70-104`）；ATM 转换器两个字段都不写（`converters/atm.py:400-411,445-461`），静态推演结果是零 schema 边 | 只产出 consecutive_turn 一种 schema 边（LoCoMo 的 turn 没有配对 round 字段）；语义边在 scope 内做 mutual top-8，用 numpy 暴力扫代替上游的 FAISS（`_mutual_neighbors`），首次 retrieve 前惰性构建 |
| A5 commit | 论文未讨论持久化协议 | FAISS Flat-IP 按 context 分文件落盘（`state.json` + `index-*.faiss`），relation store 落盘为 jsonl + summary | 记忆记录存 jsonl，向量存 `.npy`，relation store 存 jsonl；三者都归 `BaseState` 统一管理快照/恢复 |
| A6 internalize | | | |

## B 段 · 动员期（query-conditioned）

| 阶段 | Paper | 上游 Code | memory-bench 臂 |
|---|---|---|---|
| B1 cue | 每个问题 q 到来后完整触发一次 Π(q,V;K)（Eq.1），q 是显式参数 | `run_graphmemix_release.py` 逐题跑 node→ecv→select→prune→reader 五段，各自落盘供下一段读 | `retrieve` 工具调用触发；命中查询级缓存时直接返回，不重跑内部流程 |
| B2 recall | 多视角检索 s_i(q)=max_{u∈U_i} sim(h(q),h(u))（Eq.3），取 Top-L=24 种子 | 先各视角 FAISS 检索前 200、按 memory_id 取最高分，再截到 L=24（`_source_detail`，论文没有这层中间过滤） | 同上游一样先取 top-200 再截 24（`_source_priors`）；但记忆只有一个文本视角，Eq.3 的 max-pool 退化为恒等 |
| B3 expand | 1 跳可达扩展，按"检索序+关系扩展序"取 Top-M=48 组成候选池 C_q（Eq.5） | `candidate_pool` 的排序键其实是（负相似度、检索序、id），没有按关系类型的显式优先级；explicit 边靠固定 0.99 相似度自然排前面 | 直接调用同一个上游 `candidate_pool` 函数，只额外把候选限定在同一 scope 内防止跨库泄漏 |
| B4 appraise | 两次 listwise 调用：直接节点效用（Eq.6）与锚点条件边验证 ECV（Eq.7-9），论文两处无条件断言二者"execute in parallel" | 顺序编排：ecv 阶段必须读 node 阶段落盘的候选与 query-caption 缓存；`--edge-only` 生产模式下只把有 eligible schema 边的候选送进 ECV 的 prompt；节点效用系数是用 gold 标签在 dev-fold 上拟合出来的 | 两次调用用线程池真并行（LoCoMo 没有图片、没有 caption 依赖）；节点效用系数用论文 Eq.14/15 展开的固定超参，不用上游拟合值；图扩展来但未被检索到的候选沿用上游的合成 floor 分 |
| B5 select | 1-swap 局部搜索 + Kruskal 精确求最大权森林选出 K 节点提案（Eq.11-12），再在提案内穷举全部非空子集精确求变基数解（Eq.13） | `solve_forest_greedy` 是每轮扫完全部候选交换取最优（best-improvement）；`exact_subset` 规定 n>20 直接抛异常；`prune` 之后不重排，只按 mask 过滤；生产实际还会跑 9 个消融变体，只 `original_ecv_edge_p1` 进最终产物；K 固定为 `reader_k=10` | 直接调用上游 `solve_forest_greedy`/`exact_subset` 本体；K 取契约的 `top_k`（跑分时 20），不是论文固定的 10；穷举精修按连通分量分解后逐块调用同一个上游函数，单分量超过 18 个节点时按效用降序截断 |
| B6 deliver | Appendix A.5：每个连通分量取效用最高节点为根，按根效用给分量排序，分量内 BFS——这个排序作用于最终选出的森林 | 这个排序在 K=10 提案阶段就做完一次；`prune` 阶段之后只按 mask 过滤保留原顺序，不对最终 (S*,F*) 重新排序 | 继承上游同一套排序时机（select 阶段排一次，prune 只做过滤），`native_notes` 标注 `ORDER=forest_bfs` |
| B7 generate | 边界外：frozen multimodal generator M(q, O_q) 只读证据序列生成答案 | `reader` stage 把证据文本块与原图/抽帧拼进同一个 backbone 的 prompt | 边界外：只组装 envelope 交给 harness 统一的答题 LLM |
| B8 loop | | | |

> [!tip] A3/A6/B8 三边都空，是共享的缺失，不是分歧
> 论文没有定义任何阈值去重、冲突检测或驱逐机制（写入侧）；代码唯一的写时保护是 memory_id 幂等去重，属工程防重复，不是相似度去重；本臂同样只做幂等保护。B8（多轮迭代）三边都不存在——GraphMemix 是"一次检索、一次生成"的单跳流水线，没有 agent 式的循环判断继续与否。

## 差异清单

| # | 阶段 | 差异 | 类型 | 重要度 |
|---|---|---|---|---|
| 1 | A4 | ATM-Bench 的 schema 边覆盖率。论文按数据集给专属规则，ATM 有三种关系类型；代码只有两种通用规则，且 ATM 转换器不写 `session_id`/`native_round_id`，静态推演结果是零 schema 边，与论文 Table 6 声称的 ATM 均值 6.23 条 Fixed Edges 直接矛盾 | 能力损失 | 高 |
| 2 | A4 | 论文命名的三种数据集专属关系类型（event_bridge、same_record、record_grounding）在代码里完全没有实现；仓库级搜索里 record_grounding 只出现在一处"非法 ECV 角色"的测试用例中 | 能力损失 | 高 |
| 3 | A4 | 代码新增了 spatiotemporal_event 关系类型（同一场景内时间与距离都达标的相邻媒体对相连），论文没有对应的实现形态；关闭它的具体代码是 `build_graphmemix_relation_store.py:159-160` 的 `if max_gap_seconds <= 0 or max_distance_meters <= 0: return {}`，两个阈值的默认值在 `:268-269` 都是 0，等价于生产配置下永久关闭 | 纯加法（默认死） | 低 |
| 4 | B2 | 代码在多视角检索里插了一层论文没有的中间过滤：先各视角检索前 200 再按 memory_id 取最高分，再截到论文的 L=24 种子 | 纯加法 | 低 |
| 5 | B4 | 图扩展进来但从未被任何视角检索到的候选，论文 Eq.6 没定义它的 s_i 该取什么值；代码用"全部检索分的最小值再减 0.01"合成一个人造下限分数补全 | 纯加法 | 中 |
| 6 | B4 | 并行性主张。论文在 §4.1 与 §4.4.4 两处无条件断言 node verifier 与 ECV 没有串行依赖、并行执行；代码里 ecv 阶段必须读 node 阶段落盘的候选与 query-caption 缓存，且问题图片的 caption 调用只在 node 阶段发生，构成真实数据依赖，被迫顺序编排 | 文档脱节 | 高 |
| 7 | B4 | ECV 的候选覆盖率。论文 Appendix A.4 与 Eq.8 都把 G_q^trust 定义在整个候选池 C_q 上，要求"完整且唯一"的覆盖；代码生产用的 `--edge-only` 模式只把与锚点之间已有 eligible schema 边的候选送进 ECV 的 prompt，其余候选连 prompt 都进不去 | 能力损失 | 中 |
| 8 | B4 | 节点效用系数的"等价"断言。论文称 (α,τ,δ)=(0.8,5.2,0.7) 与展开式系数 (4.16,0.208,-3.64) "仅四舍五入之差"；但代码实际装配的是用 gold 标签在 SHA256 dev-fold 上单独拟合出来的系数 (4.054,0.2254,-3.711)，三个数都不等于论文自己导出的展开值 | 文档脱节 | 高 |
| 9 | B4 | 支撑上一条的完整拟合流程——按 SHA256 分 5 折、只在 dev fold 用 gold 标签拟合 logistic 系数——论文全文只有一处"calibrated node utilities"提了一句，没有描述折分或拟合过程 | 纯加法 | 中 |
| 10 | B4 | 校准配置文件里带的 standardization（均值/方差）字段，仓库级搜索显示没有任何代码读取它；节点效用实际用的是未标准化的原始特征 | 文档脱节 | 低 |
| 11 | B6 | 证据排序的作用时机。论文 Appendix A.5 描述"分量根优先+分量内 BFS"作用在最终选中的森林上；代码在 K=10 提案阶段就把这个排序做完一次，之后 prune 阶段只按 mask 过滤、不重新排序 | 设计演进 | 中 |
| 12 | A2 | H2HMem 的图片 caption 生成。论文写明由 Qwen3-VL-8B-Instruct 生成一份冻结 caption sidecar 供全部对比方法共用；代码只消费这份 sidecar 文件，生成它的脚本本身不在仓库里 | 能力损失 | 中 |
| 13 | B5 | select 阶段生产实际会跑 9 个消融变体（3 种 prize 权重 × {fixed 边集, ecv_edge_p1/p2/…}），只有 `original_ecv_edge_p1` 进最终产物；论文只描述单一路径 | 纯加法 | 低 |
| 14 | A1/A5/B7 | `vendor/memix-core` 私有依赖。上游把写入编码、多视角检索、证据序列化都放进 `ConcreteMemixMethod`，构造函数无条件要求一个仓库里没有、README 也没给获取方式的私有包，checkpoint/priors/reader 三个 stage 因此在本地跑不起来；本臂按论文 §3.3 Eq.3 与 Appendix A.5 重新实现这三段胶水层，只复用上游真正开源的核心算法本体 | 能力损失／设计演进 | 高 |
| 15 | A2/B4 | 编码器从论文/上游的 gme-Qwen2-VL-2B-Instruct（1536 维）换成 embedding-3，与本仓库其余四个已复现臂（mem0/graphiti/mandol/rag_baseline/atommem）同口径，为的是排除"嵌入强度"这个跨臂变量 | 设计演进 | 高 |
| 16 | B5 | 证据预算 K 取契约的 `top_k`（跑分时 20），不用论文写死的 `reader_k=10` | 设计演进 | 中 |
| 17 | B5 | 穷举精修按连通分量分解后逐块调用上游 `exact_subset`，是数学等价的加速（正收益边不相连的两组节点之间目标函数可加），单分量超过 18 个节点时按效用降序截断（防御分支，LoCoMo 上未观测到触发） | 纯加法 | 低 |
| 18 | A4 | 本臂的 schema 关系只有 consecutive_turn，没有 same_round，因为 LoCoMo 交给 server 的 turn 没有配对的原生 round 字段；这与论文 Appendix A.1 对 H2HMem 的处理逐字同型，不是实现缺陷 | 能力受限（有论文先例） | 中 |
| 19 | B2/A2 | 多视角检索在纯文本 LoCoMo 上退化为单视角，Eq.3 的 max-pool 恒等于自身；GraphMemix 的多模态融合机制完全没有被本臂的跑分数据练到，被练到的只是与模态无关的候选图发现、两次验证、森林优化这条主干 | 能力损失 | 高 |
| 20 | B4 | 节点效用系数用论文 Eq.14/15 的固定超参 (4.16,0.208,-3.64)，不用上游生产实际装配的拟合值 (4.054,0.2254,-3.711)——理由是嵌入已经换了、又没有对应的 dev fold，那组拟合系数不可移植 | 设计演进 | 高 |
| 21 | B4 | 两次 listwise 调用在本臂确实真并行（线程池），解决了上游被迫顺序编排的问题；但原因是 LoCoMo 没有图片、没有 query-caption 这道数据依赖，不是本臂修复了上游的编排机制 | 设计演进 | 中 |
| 22 | B6/契约 | 加了一层查询级结果缓存（按 query、query_mode、top_k、scope_id、库内容 sha256 做 key）以满足契约要求的 retrieve 幂等性；因为 retrieve 路径要调 LLM，服务端 batching 的浮点非确定性会让节点效用在 prune 临界值附近抖动，2026-09-12 的幂等性 smoke 测试正是因此报过 FAIL。副作用：跑分 harness 同 query 重复 3 次取方差时，缓存会把本臂检索侧的方差直接吸收掉——n=3 测到的实际是答题 LLM 的方差，不是 GraphMemix 检索环节自己的稳定性 | 纯加法 | 高 |
| 23 | B5 | LoCoMo 实测：森林优化的实际退化程度与成因（细节见下） | 设计演进／能力受限（任务错配） | 高 |

## 重点差异详述

### 1／2 · ATM 数据集的 schema 边覆盖率与论文数字不一致

论文 Table 6 声称 ATM-Bench 平均每题有 6.23 条 Fixed Edges，且 §4.1/A.1 给了三种数据集专属的 schema 关系规则（event_bridge、same_record、record_grounding）。上游代码的 `explicit_edges()` 只认两个通用字段（native_round_id、session_id+sequence），而 ATM 的转换器（`converters/atm.py:400-411,445-461`）两个字段都不写。沿这条静态路径推演，ATM-Bench 应该产出零条 schema 边，与论文数字直接矛盾；三种命名关系类型在仓库级搜索里也确实找不到实现，record_grounding 唯一出现的地方是一处"非法 ECV 角色"的单元测试样例（`tests/test_score_graphmemix_ecv.py:63`）。这条差异需要实机跑通 ATM-Bench 的关系构建才能最终判定是发布数据与代码版本不一致，还是代码确有缺失，但目前的静态证据已经足够写进清单。

### 6 · "并行执行"的断言与实际编排矛盾

论文在 §4.1（txt:1314）与 §4.4.4（txt:1647）两处都是无条件语句："The node verifier and ECV each make one listwise call and execute in parallel" 与 "The two verifiers have no serial dependency and execute in parallel"。代码里 `score_graphmemix_ecv.py` 的候选缓存参数是必填项，读的正是 node 阶段落盘的 `candidate_ids` 与 `query_captions`（`:260,406,486,520`），而问题图片的 caption 生成只发生在 node 阶段（`score_graphmemix_verifier.py:83-115,280-282`）。这是一条真实的数据依赖，`run_graphmemix_release.py:141-176` 把两段编排成顺序 stage 并非工程习惯，而是没有选择——这构成论文表述与代码行为当下就矛盾的一处文档脱节，不是三年演进那种可以宽容的落差。

### 8 · 节点效用系数的"等价"说法与实际拟合值不符

论文 Eq.14 给出 (α,τ,δ)=(0.8,5.2,0.7)，展开成 Eq.15 的 σ(4.16s+0.208v−3.64)，并明说"四个数据集、两个 backbone 都不重调"。但代码实际装配读取的是 `configs/release/calibration/shared_dev.json` 里用 gold 标签在 SHA256 dev-fold 上拟合出的系数 (4.054,0.2254,−3.711)（`evaluate_graphmemix_ecv.py:77-78`）。三个数字都跟论文导出的展开值不相等，误差在百分之几到十几个百分点之间。论文正文把这两组数字称为"仅显示舍入之差"（"equivalent, up to the displayed rounding"），但配置文件自己的注释反倒承认二者是两套东西——一套是"人可读的近似值"，一套是"流水线实际用的机器精确系数"。这是一处论文文字与代码配置的自陈之间当下直接冲突的地方。

### 14 · vendor/memix-core 私有依赖使上游三个 stage 跑不起来

`ConcreteMemixMethod.__init__` 第 268 行无条件执行 `self.core = _load_memix_core(self.memix_repo)`，要求 `<memix_repo>/scripts/QA_Agent/MMRAG/memix_memory.py` 存在，否则抛 `RuntimeError`（`concrete_memix.py:48-52`）。默认路径 `vendor/memix-core` 在仓库里不存在，`.gitignore` 显式忽略它，README 和文档只在 artifact 目录树和命令示例里提到这个路径，全仓库没有 URL、没有 submodule、没有 pip 依赖能拿到它。checkpoint、priors、reader 三个 stage 都会在构造这个类时必然抛异常。本臂因此没有选择照抄上游这个类，而是按论文 §3.3 Eq.3（多视角 max-pool）与 Appendix A.5（分量根优先+BFS）重新实现写入编码、多视角检索、证据序列化这三段，只复用上游真正可运行、开源的核心算法本体——`candidate_pool`、`solve_forest_greedy`、`exact_subset`/`positive_edges`。这条差异因此同时具有两个方向：对上游代码而言是它承诺却交付不了的能力（能力损失）；对本臂而言是"换了实现来源、机制目标不变"的设计演进。

### 15 · 编码器换成 embedding-3，偏离论文与上游的 gme-Qwen2-VL-2B-Instruct

这个替换本身是本仓库五个已复现臂的统一决策，目的是让不同记忆系统的比较不被"嵌入模型强弱"这个变量污染。但 server.py 自己的口径 3 明确警告了代价：论文 Eq.14 的 (α,τ,δ) 是在 gme 编码器的余弦相似度尺度上定的（上游 `shared_dev.json` 记录的检索分均值 0.385、标准差 0.114），换成 embedding-3 后 s_i 的分布会整体平移，节点效用 p_i 随之漂移，而 p_i 直接决定 prune 阶段保留多少条证据。这不是一处可以忽略的细节替换，而是会连锁影响 B4/B5 两个阶段判断结果的输入源头，且没有对应的重新校准——本臂选择的是"沿用论文公式，接受尺度漂移"而不是"重新拟合系数"（见差异 20）。

### 19 · 多视角检索在 LoCoMo 上退化为单视角

Eq.3 定义的 s_i(q)=max_{u∈U_i} sim(h(q),h(u)) 需要一条记忆有多个视角（原图、caption、OCR、视频帧）才有意义。LoCoMo 经 `loaders/locomo.py` 交给 server 的每条 turn 只有一段文本，U_i 里只有一个元素，max-pool 数学上退化成恒等函数。这意味着 GraphMemix 论文的两个核心贡献里——查询感知的森林优化，以及多模态多视角融合——本臂只测到了第一个。跑分数据能说明的是"discovery graph 上的两次验证+森林优化在纯文本长对话上表现如何"，不能用来评价论文标题里"multimodal"这部分能力，这是解读跑分结果时必须带着的边界条件。

### 20 · 节点效用系数选了论文公式而不是上游拟合值

上游生产装配的 (4.054,0.2254,−3.711) 是用 gold 标签在四个多模态数据集的 SHA256 dev-fold 上拟合出来的（详见差异 8/9）。本臂没有对应的 dev fold，编码器又已经换成 embedding-3（差异 15），那组系数在新的相似度尺度上没有拟合依据、不可直接移植。因此本臂改用论文 Eq.14/15 展开的固定超参 (4.16,0.208,−3.64)，并在 server.py 的口径 8 里写明理由："与上游拟合值相差 <4%，且论文明说四个数据集、两个 backbone 都不重调——这正是按论文理念复现该取的那一版"。这是一处本臂主动偏离上游生产行为、转而更贴近论文文本的设计选择，后果是 B4/B5 两个阶段的判断依据与上游生产链路事实上不同一套数字。

### 22 · 查询级缓存吸收了 retrieve 侧的方差

interface-spec 要求 retrieve 幂等：同一查询在库内容不变的情况下应该拿到同一结果。但本臂的 retrieve 路径要调两次 LLM，服务端 batching 引入的浮点非确定性会让节点效用 p_i 在 prune 的 κ=0.12 临界值附近来回跨界，2026-09-12 的幂等性 smoke 测试（restore 后同 query 结果应一致）就是因为这个原因报过 FAIL。修复方式是把结果按 (query, query_mode, top_k, scope_id, 库内容 sha256) 缓存在进程内。这解决了幂等性问题，但也带来一个容易被忽略的副作用：runner 的 n=3 重复实验是同一进程内对同一 query 反复调 retrieve（`bench/runner.py:240`），缓存命中后这些重复调用会拿到完全相同的检索结果，本臂检索侧本身的方差在主跑数据里被清零。这意味着如果不知道这条口径，看到本臂 n=3 之间证据完全一致时容易误判为"GraphMemix 检索非常稳定"，而实际测到的只是答题 LLM 的方差。要单独测 GraphMemix 检索侧的真实波动，需要设 `MEMBENCH_GRAPHMEMIX_CACHE=off` 单独跑一轮，不能和主跑数据混着看。

### 23 · LoCoMo 上森林优化的实际退化程度

见下方独立小节，这条结论需要结合论文自己的 Table 6 数字和真实探针数据一起判断，篇幅超出 3-5 行的常规详述格式。

## Benchmark（2026 年多模态基准，与 memory-bench 主跑的 LoCoMo 不同年代不同任务）

GraphMemix 论文的评测体系建立在四个 2026 年发布的个人多模态记忆基准上：ATM-Bench（Bei et al. 2026，一份长期个人多媒体档案，6,742 封邮件+3,759 张图+533 段视频压成 11,034 条记忆，1,044 题）、Mem-Gallery（Guo et al. 2026，20 段人设驱动对话，240 个 session，7,944 条记忆+1,490 张图，1,711 题）、MemEye（Mei et al. 2026，16 个上下文，3,392 条记忆+442 张图，1,855 题，开放问答与四选一位置轮换 MCQ 两种题型）、H2HMem（Zhu et al. 2026，25 段双人/多人对话，7,078 条记忆+1,300 张图，1,982 题）。四者共享"从长期个人多模态历史里检索并组合证据"的任务接口，但各自强调不同侧重：个人多媒体档案、跨 session 交互、细粒度视觉记忆、多方交互历史。

主指标是 LLM-as-Judge 协议（判官模型 GPT-5-mini），每个基准再各报一项代表性原生指标：ATM-Bench/Mem-Gallery 用归一化 Exact Match，MemEye 用四选项轮换平均后的 MCQ Exact Match，H2HMem 用去停用词的词面 Recall。基线方法覆盖文本/结构化记忆系统 A-MEM（NeurIPS'25）、VimRAG（ICML'26）、LightMem（ICLR'26），以及多模态检索方法 UniversalRAG（ACL'26）、MemGuide（AAAI'26）。以 Qwen3-VL-8B-Instruct 为 reader 的 Table 1 里，GraphMemix 四数据集 Judge Accuracy 宏平均 61.55%，比最强基线 UniversalRAG 高 11.75 个百分点；换成 Gemma 4 12B Unified 的 Table 2 里宏平均 67.42%，比 UniversalRAG 高 12.33 个百分点，说明优势能跨 backbone 迁移。效率上，论文用"完整生命周期"（一次性 digest 全部历史+回答全部问题）衡量，GraphMemix 相对 A-MEM/VimRAG/LightMem 分别快约 1.78×、4.27×、4.74×，且是唯一位于时间-精度 Pareto 前沿上的方法。

Table 6（消融实验）单独衡量了 ECV 对森林结构的影响，这组数字与差异 23 讨论的 LoCoMo 实测直接可比：四个数据集下，"Fixed"（不做 ECV 验证，直接用 relation store 的原始边）配置在 K=10 的最终选择里平均分量数是 3.25-3.93（较连通），而"ECV"（生产用的锚点条件验证）配置下分量数升到 8.53-9.75，也就是 K=10 个节点里有 85%-97.5% 变成孤立点；与此同时 ECV 配置的 Hit@10 比 Fixed 配置还要高 1.83-5.60 个百分点。论文自己把这个现象解读为"少量经过验证的可信边胜过大量未经验证的噪声边"，即高碎片化是 ECV 严格筛选设计出的结果，不是缺陷。

memory-bench 主跑用的是 LoCoMo（Maharana et al., ACL 2024）——一套单一模态（纯文本）、单一 schema 关系类型（对话内相邻轮次）的长期对话问答基准，与上述四个 2026 年的多模态个人档案基准既不同年代也不同任务性质，年份相差两年以上。二者的数字不能放进同一张表格比较；下面的实测小节只在"同一套机制在结构差异很大的任务上表现出什么规律"这个意义上引用论文的 Table 6，不做跨基准的分数对比。

### LoCoMo 上森林优化的实际退化程度

真实数据探针（LoCoMo conv0，419 turns，10 题，top_k=20）观测到：候选池恒为 48（`candidate_pool` 的 `candidate_limit` 上限）；节点验证器平均每题只对 48 个候选里的 2.75 个给出非零直接效用分；ECV 一共返回 65 行判定，0 行因解析失败被丢弃，六选一角色分布是 irrelevant 51、clarification 7、redundant 7、new_fact 0、corroboration 0；最终进入森林的可信边平均每题 1.2-1.75 条；K=20 提案里的连通分量数平均 18.9（即 94.5% 的节点是孤立点）；节点效用集中在 0.09-0.30 一个很窄的区间（min/median/max）；变基数精修平均每题只删掉约 0.1 个节点，保留 19.9/20。

这组数字要放进论文自己的 Table 6 里看才有意义。论文四个原生多模态基准在 K=10 时，ECV 配置下的分量碎片率是 85%-97.5%；本臂在 K=20 时观测到的 94.5% 落在这个区间正中间。这说明高碎片化本身不是 LoCoMo 或本臂特有的异常——它是 ECV 这套"宁缺毋滥"的验证机制在论文自己的设计目标基准上就会产生的正常结果，论文也是拿它换来了更高的 Hit@10。

但 LoCoMo 上的碎片化叠加了三个论文原生基准都不具备（或程度更轻）的约束，这才是判断的关键：一是 schema 关系只有 consecutive_turn 一种（差异 18），比论文最贫乏的 H2HMem 也一样只有这一种关系，但论文四个基准里另外三个都至少有 same_round 或更多类型可用；二是多视角检索完全退化为单视角（差异 19），节点直接效用 s_i 这一项的信噪比因此比论文设计时假设的更弱；三是节点验证器本身在 ECV 介入之前就已经把 94.3%（=1-2.75/48）的候选判成零分——这一步的选择性比论文任何一张表里报告的都更极端。三者叠加的后果是 ECV 几乎找不到可以判定为 new_fact 或 corroboration 的边（10 题里两者合计为 0 次），唯一出现过的正向角色只有 clarification（7 次），这与"LoCoMo 里能拿到的唯一关系是同一段对话内的相邻轮次，天然缺少论文最看重的那种跨模态、跨时间、跨记录类型的强关联证据对"这个解释是一致的。

变基数精修那一步的数字给出了更精确的技术解释：`PRUNING_ROOT_COST`（κ）取 0.12，Eq.12 的推导规定一个孤立节点只要 p_i 大于 κ 就值得保留、开辟独立证据链。观测到的中位效用 0.14-0.16 刚好压在这条线之上、最小值 0.09 压在线下，这恰好对应了"平均只删掉约 0.1 个节点"这个几乎不删的结果——不是精修步骤没有运行，而是绝大多数候选的效用分本来就刚好够格。

综合起来，判断是：1-swap+Kruskal 选提案、穷举子集精确求变基数解这套组合优化机器在 LoCoMo 上确实在正确运行——每一步的输入输出都对得上论文公式——但它拿到的问题实例几乎没有边可用（可信边均值 1.2-1.75 条/题，K=20 个候选节点里近 19 个互不相连）。当图上几乎没有边时，"选一批节点、再看哪些边值得连"这套机制在结果上会非常接近于"直接按节点效用排序取前 K 名"，因为 Eq.12 里连接带来的收益项 B_e 在几乎所有节点对之间根本不存在，剩下起作用的只有每个节点自己的 p_i 高低。这是任务/schema 错配导致的行为收敛，不是本臂的实现缺陷：GraphMemix 的核心贡献——用类型化的 schema 关系与多视角语义相似度共同构建可供优化的候选图——需要一个关系类型丰富、模态多样的目标域才能发挥,而 LoCoMo 提供的关系结构过于扁平、模态单一，能让算法据以做出差异化决策的输入信号本身就很稀薄。

## 附：两条推导

1. 论文 Table 6 的碎片率（K=10、四个原生基准）与本臂探针的碎片率（K=20、LoCoMo）之所以可以直接类比，是因为两者衡量的都是"分量数 / K"这个比例而不是绝对分量数——K 不同不影响这个比例的可比性，而两者恰好都落在同一个 85%-97.5% 区间，这不是巧合式的相似，而是 ECV 这套验证机制本身的选择性（宁可留孤立点，不留未经验证的边）决定的行为特征，与具体基准无关。
2. `PRUNING_ROOT_COST=0.12` 与观测到的节点效用分布（min 0.09、median 0.14-0.16）之间的相对位置，直接解释了"变基数精修平均只删掉约 0.1 个节点"这个几乎不生效的结果：按 Eq.12 的推导，孤立节点保留的充要条件是 p_i>κ，本臂 10 题里的效用分绝大多数都压在这条线之上一点，精修步骤因此几乎没有机会真正发挥"剔除低价值孤立证据"的设计意图。

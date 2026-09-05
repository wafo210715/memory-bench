# atommem 架构文档复核报告

> 复核日期 2026-09-05；论文源 `Yao-2026-AtomMem-Building-Simple-and-Effective-Memory-System-for-LLM-Agents-via-Atomic-Facts.txt`（1814 行）；代码源 `AtomMem` @ `776f880`（MINE-USTC/AtomMem，"Update README.md"）
> 复核方式：paper-architecture.md 的每条断言回 txt 用 `grep -n` / `sed -n` 定位并记录亲眼看到的行号；code-architecture.md 的每一个 `file.py:NNN` 都实际 `sed -n` 打开该行核对，控制流断言顺调用链读到底。

## 1. 总评

两份文档的**机制描述**质量非常高：论文侧 58 条断言里 50 条完全属实，代码侧 66 条里 51 条完全属实，且两份文档各自最重要的发现——"event_contexts 被计算出来却在最终 prompt 前两行丢弃"、"事件候选不复用 Cret 而是重新检索"、"Profile 批处理不是 session 末而是攒够 10 条 + conversation 末兜底"、"SFT Fact Executor 在跑分链路里根本不执行"——我逐条追到了双向证据，全部成立，没有一条是编出来的。文档作者显然真的读了代码和论文。

问题集中在**引用锚点的精度**，不在结论上。最严重的一处是 `code-architecture.md` 把 `_llm_generate_event_info` 标成 `src/event_manager.py:242-286`，实际在 **267-327**，242-286 落在另一个函数 `_update_event_info`(229-266) 里——这是唯一一处"照着行号打开会看到错的函数"的引用。其次是 `src/retrieval.py` 的四个函数行号**系统性整体偏移 12~27 行**（`_main_recall_facts` 137 写成 150-173、`_compensation_recall_facts` 164 写成 189-249、`_retrieve_events` 241 写成 252-274），以及 `_extract_query_intent`（实际 `query_response.py:138`，写成 157-179）、`check_and_trigger_batch_extraction`（实际 `profile_manager.py:27`，写成 31-40，引用范围整段落在 docstring 里）。这些函数名和行为都对，只是行号不能直接拿去 `sed`。

另有两条**实质性错误**（判 ✗）：一是 `code-architecture.md` 称"仓库里三份答题 prompt 逐句和论文 Figure 8/9 几乎一致"——实测只有 `answer_generation_prompt.txt` 与 Figure 8 近乎逐字，`_cat2.txt` 是论文里**完全不存在**的时间推理专用模板（5 条时间表达规则 + 4 条输出规则），`_cat3.txt` 与 Figure 9 只是主题相同、措辞另起炉灶；这本身就是一条文档漏掉的 code-only 分歧。二是同一断言里"唯独都没有 event_contexts 这一行"是对的（且 cat3 第 12 行还明令 "Do not use ... event summaries"，比文档说的还强）。

论文侧的错误都是节号/公式号误标：4,352 条样本在 **§A.1.3** 不是 §A.3（§A.3 是 Details of Associative Graph Retrieval）；"Eq.6-9 定义种子分布构造"错——Eq.6 是关键词权重 ω(k)、Eq.7-8 是多通道转移矩阵、只有 Eq.9 是种子分布，且文档自己后面写对了，前后矛盾；"top-k2s"是 PDF 转文本把 `k_s/2` 压平的产物，文档当成参数名照抄，而 §A.6.1（txt 1537-1538）明确写着 "ks = 10, where the main seed and compensation seed are both set to 5"，这个数正好对上代码的 5+5=10，是论文↔代码对齐的关键一环，被这个转写事故掩盖了。此外 §5.1 声称 Figure 1/2 "无法核实（需要看原始 PDF/图片）"——这两张图就躺在它同时在读的那个仓库里（`Figures/intro.png` = Figure 1，`Figures/main-method.png` = Figure 2，caption 与论文逐字一致），PDF 原件也在 txt 旁边。

## 2. 逐条核对表

### 2.1 paper-architecture.md — 抬头与术语

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| P1 | 抬头 | arXiv:2606.19847 | ✓ | txt:41 `arXiv:2606.19847v1 [cs.CL] 18 Jun 2026` | |
| P2 | 抬头 | USTC 认知智能全国重点实验室 + 安徽大学 | ✓ | txt:4-7 `State Key Laboratory of Cognitive Intelligence, University of Science and Technology of China` / `2 Anhui University` | |
| P3 | 术语 | Fact Executor = 专抽原子事实的小模型（SFT 微调 Qwen3-14B） | ✓ | txt:52 `AtomMem introduces a Fact Executor`；txt:662-663 `We fine-tuned a Qwen3-14B model as our fact extractor using SFT LoRA` | 论文正文 §3.1.1 叫 "Atomic Fact Extractor"，摘要/附录叫 "Fact Executor"，同一物 |
| P4 | 术语 | Atomic Fact = 自包含、第三人称、时间锚定的陈述句 | ✓ | txt:1186-1187 `standalone ... Each fact must be complete without additional context`；txt:1197 `3. Rewrite in third person`；txt:1195-1196 相对时间→绝对日期 | |
| P5 | 术语 | PPR = 从种子按边权扩散重要性的图算法 | ✓ | txt:1176 `Personalized PageRank (PPR)`；txt:1411-1416 RWR 迭代式 | 定义性表述 |

### 2.2 paper-architecture.md — §1 一句话机制

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| P6 | §1 | §4.2 原话 "memory storage quality is paramount. Sophisticated system orchestration cannot compensate for flawed memory representations" | ✓ | txt:828-831（§4.2 "Validation of Atomic Fact Extraction" 段末，原文续 `or information loss`） | 引文逐字无误 |
| P7 | §1 | 对比并**点名批评** A-Mem 式不受约束的 LLM 自由重写会 "destruction of original facts"（§1） | ◐ | txt:23-24 §1 提到 `AMem(Xu et al., 2025) enables dynamic memory evolution without pre-defined rules`；批评句在 txt:84-88，主语是 `these methods` / `Recent work has explored dynamic memory evolution`，**没有再点名** | 引文 `destruction of original facts` 逐字对（txt:87-88）；但"点名批评"是过度表述，论文只在同节前文列举时提过 AMem |
| P8 | §1 | 检索时靠实体/事件/时间三类边的关联图做 PPR 扩散 | ✓ | txt:295-298 三类关联为边；txt:314-353 Eq.3/4/5；txt:1174-1182 三通道 Keyword/Event/Dialogue Turn | |

### 2.3 paper-architecture.md — §2 记忆怎么存进去

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| P9 | Atomic Fact Extraction | 触发时机是**每条原始对话消息**进来时 | ✓ | txt:1186 `Extract useful, standalone and high-value facts from the current message, using recent conversation context when necessary` | Figure A.1 prompt 明确是逐条 message |
| P10 | Atomic Fact Extraction | SFT(LoRA) Qwen3-14B / 单 A100 / lr 5e-5 / rank 128 / global batch 8 / 3 epoch（§4.1，txt 行 662-666） | ✓ | txt:662-666 逐项对上，引用范围**精确** | 全文档最干净的一条数值引用 |
| P11 | Atomic Fact Extraction | 训练数据两阶段（§A.1.2），Stage 1 用 GPT-4o 作教师模型 | ✓ | txt:1128-1133 `We utilized GPT-4o as the teacher model` | §A.1.2 = "Extraction Pipeline and Prompt Guidelines" |
| P12 | Atomic Fact Extraction | 系统提示词 Figure A.1（正文 Figure 4 同图，txt 行 1189-1207），编号 **5 条**规则，逐条内容 | ✓ | Figure A.1 头 txt:1185；规则 1-5 精确落在 txt:1189-1207；Figure 4 caption txt:1210-1212。①1190-1193 ②1194-1196 ③1197-1201 ④1202-1204 ⑤1205-1207，四项子内容（`The user believes...` / `Alice expressed frustration regarding...` / `[Image Description]` 当 primary source / 严格 JSON）全部逐字命中 | 引用范围**精确到行** |
| P13 | Atomic Fact Extraction | Stage 2 人工精修（去幻觉、补指代、去噪、长句拆分，§A.1.2） | ✓ | txt:1134-1154 四项职责 Verification/Refinement/Filtering/Decomposition | |
| P14 | Atomic Fact Extraction | 自建 10 组角色、四大类场景、Elena the Chef/Kenji the Novelist vs Caroline/Melanie、零重叠（§A.1.1） | ✓ | txt:1013-1022；四大类 txt:1084-1098（Professional & Academic / Family & Lifestyle / Interests & Culture / Values & Emotional Depth） | |
| P15 | Atomic Fact Extraction | 最终数据集 **4,352 条**样本（**§A.3**） | ◐ | 数字 ✓ txt:1162 `The final constructed dataset D consists of 4,352 high-quality samples`；但该段属 **§A.1.3 "Dataset Statistics and Examples"**（节号 txt:1155，标题 txt:1159）。**§A.3 = "Details of Associative Graph Retrieval"**（节号 txt:1160，标题 txt:1172） | 节号错标；双栏 PDF 转文本把节号和标题拆开了，容易踩 |
| P16 | Atomic Fact Extraction | Figure A.2 训练样本："Emma got an A on her first psychology exam on the Friday before May 17, 2023." | ✓ | txt:1265 Figure A.2 头；txt:1279-1280 output 逐字一致 | Figure 5 caption txt:1282-1283 |
| P17 | Atomic Fact Extraction | Eq.1 = 最大化 Σ log Pθ(F\|I,C) | ✓ | txt:200-207 | |
| P18 | Structured Fact | F={id,c,v,P,K,T,E}，P 用另一次 LLM 调用解析（§3.1.2） | ✓ | txt:250-262；`we leverage the LLM to parse the conversation and extract the following key attributes` txt:252-253；E 初始为空 txt:261-262 | |
| P19 | Fact Verification | §3.1.3, Eq.2；先按 participants+temporal 元数据符号过滤（省向量计算），再 Sh 排 top-k 得 Cret | ✓ | txt:233-235 `symbolic filtering effectively eliminates irrelevant facts before expensive vector computations`；Eq.2 txt:241-242；Cret txt:250-251 | |
| P20 | Fact Verification | **一次 LLM 调用同时产出 (c'_new, U)**；U 只有检测到逻辑冲突才生成；joint mechanism 防冗余 + 维护全局一致性 | ✓ | txt:264-274，`generated only when logical conflicts are detected` txt:271-272；`This joint mechanism effectively prevents memory redundancy and dynamically maintains global consistency` txt:272-274 | |
| P21 | Event Memory | §3.2, Algorithm 1；E={id,S,Fids,Pe,Ke,Te} | ✓ | E 定义 txt:300-303；§3.2 正文 txt:307-308 明说 `The complete event construction and update algorithm is detailed in Appendix A.2`；Algorithm 1 本体在 txt:1285-1329 | 复合锚点；Algorithm 1 实体落在 §A.2 而非 §3.2 内，文档写法可接受 |
| P22 | Event Memory | 候选生成**直接复用 Fact Verification 的 Cret**（不重新检索） | ✓ | Algorithm 1 第 5-11 行 = txt:1290-1301 `for all F ∈ Cret do / if F is linked to existing events then Ecand ← Ecand ∪ GetEvents(F) / else Falone ← Falone ∪ {F}`；§A.2 正文 txt:1105-1107 `AtomMem leverages the retrieved relevant facts Cret` | "不重新检索"是从复用 Cret 推出的，论文没有反向明说，但符号复用足够明确 |
| P23 | Event Memory | 语义路由 = 一次 LLM 调用（LLMverify），可多选、也可都不选 | ✓ | Alg 第 13 行 txt:1303 `Ematch, Fmatch ← LLMverify(Fnew, Ctarget)`；txt:1122-1127 `flexibility to select multiple candidates ... Alternatively, it can choose none` | |
| P24 | Event Memory | 状态执行三分支（并入 Fids + 集合并 + LLMsummarize / 每个匹配独立事实各建一新事件 / 都没命中则 StoreIndependently） | ✓ | Alg 14-21 txt:1304-1317；Alg 22-26 txt:1318-1325 `CreateNewEvent({Fnew, Falone})`；Alg 27-29 txt:1326-1329 `StoreIndependently(Fnew)` | 逐行对上 |
| P25 | Temporal Profile | §3.3；P={id,u,c,vp,Kp,Eevi,t_from,H} | ✓ | txt:343 P 定义；§3.3 标题 txt:324-325 "State Evolution: Temporal Profile Modeling"，节号 txt:309（§3.4 = Memory Graph，经 txt:1174/1233 `Section section 3.4` 两处交叉验证） | 节号映射经交叉验证，文档判对了 |
| P26 | Temporal Profile | 触发机制是 **session 级批处理**（非实时）；抽取阶段 LLM 顺手判断长期特征；"At the end of a dialogue session" | ✓ | txt:354-360 `Unlike the real-time updates for facts and events, profile construction employs a session-based batch mechanism. During atomic fact extraction, the LLM identifies facts implying potential long-term characteristics ... At the end of a dialogue session` | 引文逐字 |
| P27 | Temporal Profile | 检索 top-kp 已有画像，LLM 决策 redundant / update current / modify historical / new | ✓ | txt:361-368 | |
| P28 | Temporal Profile | 当前值变动时旧状态连同有效时间区间拷进 H，"非破坏性更新" | ✓ | txt:368-372 `AtomMem copies the previous state into the history H and records its valid time interval or updates the corresponding historical version` | |
| P29 | Temporal Profile | 与 Mem0g/Zep 的 `t_invalid` 失效标记同族 | ? | 全文 grep `Zep` / `Mem0g` / `t_invalid` / `invalid` **零命中** | 这是文档作者自己的跨系统类比，不是论文内容；写在描述论文的段落里容易被误读为论文原话 |
| P30 | 通篇 | 只有 Fact Executor 明确是独立的 SFT 小模型，其余"the LLM"论文没说是不是同一个 | ✓ | txt:252（metadata）/264-265（verification）/357-358（profile flag）/365（profile updater）/415-416（query parse）/433-434（generation）均只写 "the LLM"/"an LLM"，全文无模型归属说明 | |

### 2.4 paper-architecture.md — §3 记忆怎么被用起来

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| P31 | Query Intent | §3.5.1，每次提问一次 LLM，Qparsed={Iprof,Pq,Kq,Tq}，Iprof∈{0,1} | ✓ | txt:403-418 | |
| P32 | HHR | §3.5.2 三级递进 | ✓ | txt:441-444 `hierarchical retrieval strategy consisting of three stages` | |
| P33 | HHR-1 | Primary Recall 按 Pq/Tq 过滤后 Sh 排序取 **top-k2s** | ◐ | txt:445-448；"k2s" 是 PDF 把 `k_s/2` 压平的转写事故。**txt:1537-1538 明确 `optimizing the configuration at ks = 10, where the main seed and compensation seed are both set to 5`**；Table 5 只有 `Initial Graph Seed Count (ks) = 10`（txt:1633,1637），无 "k2s" 这个量 | 文档把转写产物当参数名照抄，掩盖了"各取 ks/2 = 5"这个与代码 5+5=10 精确对齐的事实 |
| P34 | HHR-2 | Compensatory：Sh(E,Q) 取 top 事件、展开成员、排除 Rpri、Sf=we·Sh(E,Q)+(1-we)·Sh(F,Q)、Rseed=Rpri∪Rcomp | ✓ | txt:449-457（事件层排序、排除 Rpri）；Sf 公式 txt:471-472；Rcomp/Rseed txt:474-477 | 公式逐字 |
| P35 | HHR-3 | Associative：Rseed 为种子、限跳数、仍受 participant/temporal 约束、RWR、取 top-kf 输出 Rfact | ✓ | txt:478-483 + txt:396-402 `applies Random Walk with Restart (RWR) ... selects the top kf facts` | |
| P36 | HHR-3 | "（Eq.3-5 定义三类边权重，**Eq.6-9 定义种子分布构造**）" | ◐ | Eq.3-5 ✓（txt:316-322/336-341/344-353）。但 **Eq.6 = ω(k) 关键词权重**（txt:1240-1242，§A.3.1）、**Eq.7-8 = 多通道转移矩阵**（txt:1227-1229 / 1258-1262，§A.3.2）、**只有 Eq.9 是种子分布**（txt:1338-1345） | 与文档自己后面 P37/P40/P41 的说明直接矛盾，是同文自相冲突 |
| P37 | 边权 | Entity Edge Eq.3 公式；ω(k)=IDF(k)·βq(k)·π(k)（**Eq.6，§A.3.1**）；βq 命中 query 时 boost、π 对高频词非线性衰减 | ✓ | Eq.3 txt:316-322；Eq.6 txt:1240-1242；§A.3.1 "Query-Aware Keyword Weighting" 标题 txt:1232；βq/π 说明 txt:1244-1250 | 公式号和节号**都精确** |
| P38 | 边权 | Event Edge Eq.4 = Σ 1/(\|Fe\|-1)^γe，事件越大衰减越狠 | ✓ | txt:336-341 + 惩罚说明 txt:342-343 | Table 5 里同一系数叫 λ=1.25（txt:1711,1715），论文自身符号不一致，文档未提及但不影响 |
| P39 | 边权 | Temporal Edge Eq.5 = exp(-\|posi-posj\|/τ)，只连同 session 内窗口 W 以内相邻轮 | ✓ | txt:344-353 `AtomMem restricts turn edges to intra-dialogue facts within a maximum window W` | |
| P40 | §A.3.2 | 多通道转移矩阵 Eq.7-8；ρ̄i,c 按节点有效通道集合 Ci 动态重归一化，避免缺边被稀释 | ✓ | Eq.7 txt:1227-1229；Ci 定义 txt:1254 `channels containing at least one outgoing neighbor for node Fi`；Eq.8 txt:1258-1262 | |
| P41 | §A.3.3 | 种子幂变换 Eq.9（γs 越大重启引力越强）；RWR Eq.10；收敛 Eq.11 ‖·‖1<εc；悬挂节点按 p 重分配防泄漏；按 r(∞) 取 top-kf | ✓ | Eq.9 txt:1338-1345 + γs 说明 1347-1351；A.3.3 标题 txt:1353；Eq.10 txt:1416/1436；η 说明 1438-1441；悬挂节点 txt:1441-1444；Eq.11 txt:1447/1452；top-kf txt:1455-1458 | 全部命中 |
| P42 | §3.5.3 | Iprof=1 时按 Pq 过滤全局画像，Sh(Pq,Q) 排序取 top-kp 组成 Rprof | ✓ | txt:419-426 | |
| P43 | §3.5.3 | 查询带时间约束时选取该时间点有效的画像版本 | ✓ | txt:426-429 `the system selects profile versions valid during that specific time` | |
| P44 | §3.5.3 | 把 Rfact 和 Rprof 拼成 C，与原始 q 一起喂 LLM 生成 | ✓ | txt:430-434 | |
| P45 | §3.5.3 | Figure 8/A.3 和 Figure 9/A.4 的 Input **都明确列 `event_contexts`（fact_id→事件摘要，optional）为第四项** | ✓ | Figure A.3 头 txt:1733，Input 四项 txt:1736-1739，`- event_contexts: Dictionary mapping fact_id to event summary (optional)` = **txt:1739**；Figure A.4 头 txt:1756，同一行 = **txt:1762**；Figure 8/9 caption txt:1753-1754 / 1780-1781 | 双向证据最硬的一条 |
| P46 | §3.5.3 | 正文写 "enriched by event-level context" | ✓ | txt:434-436 | |
| P47 | §4 架构图 | mermaid 各节号（§3.1.1/3.1.2/3.1.3/3.2/3.3/3.4/3.5.1/3.5.2/3.5.3、Eq.1/2/3-5） | ✓ | 逐个核对无误；关键的 §3.3=Temporal Profile / §3.4=Memory Graph 经 txt:1174 与 txt:1233 两处 `Section section 3.4` 交叉验证 | 双栏 PDF 把节号和标题拆散（txt:281/293/309/324），文档没被带偏 |

### 2.5 paper-architecture.md — §5 我没搞清楚的 / §6 论文没写清楚的

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| P48 | §5.1 | Figure 1/Figure 2 是唯二整体架构可视化，图片本身**无法核实**（需要看原始 PDF/图片） | ◐ | "唯二"✓（txt:92-93 Figure 1 caption；txt:228-229 Figure 2 caption；全文再无架构图）。但"无法核实"不成立：**这两张图就在同一份 code-architecture 读的那个仓库里**——`AtomMem/Figures/intro.png`（README 引用时 caption 逐字 = Figure 1）与 `AtomMem/Figures/main-method.png`（caption 逐字 = Figure 2）；PDF 原件也在 txt 同目录 | 结论没错（mermaid 是重画不是转录），但"取不到图"这个前提是错的 |
| P49 | §5.2 | Figure 3/6/7 曲线精确读数无法核实，只能反推 ks=10、we=0.7 是甜点 | ✓ | Figure 3 caption txt:849；Figure 6 caption txt:1529-1532 `ks = 10 achieves the optimal trade-off`；Figure 7 caption txt:1590-1593 `we = 0.7 achieves the optimal balance` | 正文文字确实给了最优点，曲线读数确实取不到 |
| P50 | §5.3 | §3.5.3 只说选有效版本，历史版本切分粒度 / t_from 定法没有算法或公式 | ✓ | txt:426-429 与 txt:368-372 均为定性句，全文无相关公式 | |
| P51 | §5.4 | Table 5（§A.7）是**检索侧**完整超参；构建侧四个阈值（Fact 去重门槛 / Profile 批处理触发数 / Profile 最低相似度 / Event 归类 top-k）论文完全没给 | ✓ | Table 5 逐项核对 txt:1625-1729（ks/kf/kp、α/β、we/wf、ρ 三通道、η/max-iter/εc/γs、图构造 5 项、实体边 6 项、事件边 3 项、时间边 3 项），**确无那四项**；§A.7 标题 txt:1603-1605 | 这条推动了后面代码侧的对照，重要且正确 |
| P52 | §5.5 | §A.4 报告 LongMemEval 补充实验（Table 4，**六个类别的 F1/BLEU-1/J**）；只说用 GPT-4o-mini backbone + DeepSeek-v4-Pro judge | ◐ | §A.4 标题 txt:1449-1450；引文 txt:1423-1425 ✓ 逐字；Table 4 txt:1469-1507 六类 ✓。但 **SSP 类只有 J，F1/BLEU-1 是 `—`**（txt:1489,1496），论文在 txt:1428-1434 专门解释了原因 | "六个类别的 F1/BLEU-1/J" 不准确 |
| P53 | §6.1 | Table 2 的三个消融变体"**只给了一句话**定性描述和结果数字" | ◐ | 实际有三处描述：Table 2 caption txt:823-825；§4.2 txt:671-674 `This simplified version lacks hierarchical event structures and relies solely on retrieving atomic facts`；§4.3 txt:838-843 `uses simple flat retrieval without hierarchical structures` | 核心论点（构建期停跑 vs 仅检索期不查，论文没说清）**成立**，且 AtomMem-Flat 的 722.75K vs AtomMem 21357.06K token 差（txt:629-630）恰恰说明这不是纯检索侧改动；但"只给了一句话"是低估 |
| P54 | §6.2 | 除 Fact Extractor 外其余步骤 prompt 均未给出；附录只展示了 Figure A.1/4、Figure 8-9/A.3-A.4、judge Figure 10/A.5 | ✓ | 全文 prompt 图仅 5 张：txt:1185（A.1/4）、1265（A.2/5 是训练样本非 prompt）、1733（A.3/8）、1756（A.4/9）、1785（A.5/10）。metadata 抽取 / 冲突判断 / 事件路由 / 事件摘要 / 画像抽取 / 画像时序决策 / query intent 七类 prompt 全无 | |
| P55 | §6.3 | Fact Verification 输出格式（U 的字段结构 / JSON schema）未给出 | ✓ | txt:264-274 仅函数式公式，无 schema | |
| P56 | §6.4 | "kp" 在 §3.3 和 §3.5.3 两处指代不同，论文没说是否共享同一数值 | ✓ | §3.3 txt:361-362 `retrieves the top-kp most relevant existing profiles for the same user u`；§3.5.3 txt:425 `The top kp items form the profile context set Rprof`；Table 5 只列一个 `Profile Item Retrieval Count (kp) = 5`（txt:1635,1639） | 论文确实没区分；代码侧证实是两个独立参数（`PROFILE_TEMPORAL_TOP_K=8` vs `PROFILE_RECALL_TOP_K=5`），文档这个怀疑是对的 |
| P57 | §6.5 | "追加新历史版本"vs"修改已有历史版本"的判定逻辑没有规则或公式 | ✓ | txt:368-372 只有一句 `... or updates the corresponding historical version`，无判据 | |
| P58 | §6.6 | Fact Executor 离线一次跑完还是每次评测重跑未交代；README/仓库暗示"预抽取一次、复用多次"；论文没说是否计入 Table 1 token | ✓ | 论文只有 txt:642-643 `we track the total API token consumption across the entire pipeline`，无细化；README（`AtomMem/README.md`，"LoCoMo Benchmark Evaluation" 节）确实写 `Reproduce Paper Results: Use the provided pre-extracted facts in data/locomo_preextracted_facts/ ... to directly reproduce our reported metrics` | |

### 2.6 code-architecture.md — §1/§2 写入侧

| # | 文档小节 | 断言摘录 | 判定 | 证据（均为亲自打开该行核对） | 备注 |
|---|---|---|---|---|---|
| C1 | 抬头 | 官方 MINE-USTC/AtomMem | ✓ | 论文 txt:70 `https://github.com/MINE-USTC/AtomMem` | |
| C2 | §1 | LoCoMo 跑分入口从磁盘读现成事实文本，本仓库跑分时不执行"抽原子事实" | ✓ | `scripts/evaluate_locomo.py:744-745`；全文件 grep `FactExtractor`/`extract_facts` **零命中** | |
| C3 | §2 | `process_all_facts`（`preextracted_pipeline.py:197`）逐 session 逐 turn 遍历 turn 自带的 `facts` 数组 | ✓ | def 在 **197**（精确）；session/turn 循环 227-341；`facts = dialogue.get('facts', [])` 在 232；`for fact_text in facts` 在 296 | |
| C4 | §2 | `run_case()` 直接调 `memory_pipeline.load_preextracted_facts(str(case["facts_file"]))` | ✓ | `evaluate_locomo.py:695`（def run_case）、**744**（该调用逐字一致）、745 `process_all_facts` | |
| C5 | §2 | `load_preextracted_facts` 在 `preextracted_pipeline.py:49` | ✓ | def 在 **49**（精确） | |
| C6 | §2 | 预抽取文件只有 `{source_file, total_sessions}` 两个元数据字段（`conv-26.json:1-4`） | ✓ | `data/locomo_preextracted_facts/conv-26.json` 第 1-4 行正是 `{ "metadata": { "source_file": "conv-26.json", "total_sessions": 19 } }` | 引用范围**精确** |
| C7 | §2 | Caroline LGBTQ 例子"见 `conv-26.json` 第 **20 行**附近" | ◐ | 原文 `"I went to a LGBTQ support group yesterday..."` 在 **第 33 行**，改写后的 fact `"Caroline attended a LGBTQ support group on May 7, 2023, and found it to be a powerful experience."` 在 **第 35 行** | 引文逐字正确，行号偏 13 行 |
| C8 | §2 | 结构化字段 `{fact_id, fact, embedding, people, keywords, time:[event_time, interaction_time], dia_id, event_ids, needs_profile_extraction}`（`preextracted_pipeline.py:126-165` `build_fact_tuple`） | ✓ | def 在 **126**（精确）；字段字典在 160-170，九个字段一字不差；`time` 语义见 112-117（`time_info[1] = interaction_time`） | 引用末行 165 略短于实际 172，起点精确 |
| C9 | §2 | "存的过程调不调 LLM（`FactStorageManager.process_new_fact`, `fact_storage.py:35-135`，**五步**）"，随后列①元数据抽取…⑤画像批处理 | ◐ | 函数确在 `fact_storage.py:35-136`。但它自身的五步（docstring 39-44）是 **去重/冲突检测/存储/事件归类/画像检查**——文档列的第①步"元数据抽取"**不在这个函数里**（在 `preextracted_pipeline.build_fact_tuple:147-150` → `extract_fact_metadata:67`，先于 `process_new_fact:312` 调用），且文档漏掉了 Step 3 "Storage"（93-94） | 各子步的独立引用都对，只有这个总锚点套错了容器 |
| C10 | §2① | 元数据抽取调 1 次 LLM（`extract_fact_metadata`, `preextracted_pipeline.py:67-122`，用 `prompts/fact_metadata_extraction_prompt.txt`） | ✓ | def 在 **67**（精确，实际 67-124）；prompt 路径 40；`call_with_retry(..., call_type="metadata_extraction")` 在 99；prompt 文件确实产出 people/keywords/time/needs_profile_extraction | |
| C11 | §2② | 去重**不调 LLM**，纯 cosine > 0.95 直接 `IGNORE`（`_is_duplicate`, 138-165；`DUPLICATE_THRESHOLD=0.95`, `config.py:59`） | ✓ | `_is_duplicate` def **138**，函数体正好到 **165**（范围精确）；`similarity > config.DUPLICATE_THRESHOLD` 在 162；`config.py:59` 精确；IGNORE 早返回在 66-72 | |
| C12 | §2③ | 先按 people 交集筛候选，再 `Sh=α·emb+β·jac`（0.7/0.3）排序取相似度 **>0.6 的 top-5**（`_detect_conflict`, 167-225），喂 1 次 LLM 二元判断（`_llm_detect_conflict`, 228-260） | ◐ | 行为**全对**：`similarity > 0.6` 在 **213**（硬编码）、`[:5]` 在 **222**、α/β 读 `config.py:79-80`；二元输出 `has_conflict`+`conflict_fact_id` 在 246-247。两处 def 行号精确（167 / 228），但函数实际到 **226** 和 **273**。另：people 筛用的是 `people_sets_compatible`（`fact_storage.py:14-16`）"**双方都非空且不相交**才拒"的宽松兼容判断，不是"交集非空才留"——空 people 的 fact 一律放行 | |
| C13 | §2③ | 一旦判定冲突**直接原地覆盖**被冲突那条的 `fact`/`embedding`/`keywords`/`time` 四字段（`fact_storage.py:79-82`），旧文本旧向量不保留、不进任何历史列表 | ✓ | **79-82 四行逐字命中**；83 立刻 `save_facts` 落盘；84-89 早返回，新 fact 从不 append | 引用**精确到行**，本文档最硬的一条 |
| C14 | §2④ | 生产链路实际用 `FactSeededEventLevelEventManager` | ✓ | `incremental_temporal_profile.py:217` `self.event_manager = FactSeededEventLevelEventManager()`；该类由 `IncrementalTemporalProfileFactStorageManager`(206) 装配，经 `IncrementalTemporalProfilePipeline`(273,284) 进入 `AtomMemPipeline`(`run_atommem_pipeline.py:429`)，而 `evaluate_locomo.py:71` 正是 `"pipeline_cls": AtomMemPipeline` | 调用链走通 |
| C15 | §2④ | 它自己单独跑一次 top-k 相似事实检索（`fact_seeded_event_pipeline.py:132-155`，用 `EVENT_ATTRIBUTION_TOP_K=10`/`_EMBEDDING_WEIGHT=0.7`/`_KEYWORD_WEIGHT=0.3`），**不复用**第 3 步冲突检测的候选和分数 | ✓ | `_retrieve_top_similar_facts` def **132**（实际 132-159）；打分 149-152 用 `EVENT_ATTRIBUTION_*`（`config.py:62-64`），与冲突检测的 `EMBEDDING_WEIGHT_ALPHA/KEYWORD_WEIGHT_BETA`（`config.py:79-80`）是两套独立参数；遍历 `all_facts` 全量重算（140-156），无任何缓存复用 | 行为断言**完全成立** |
| C16 | §2④ | 调 1 次 LLM 一次性路由（可多选，`event_level_pipeline.py:166-247`），**用内联 system_prompt，不读取** `prompts/event_attribution_prompt.txt` | ✓ | `_llm_judge_event_level_attribution` def **166**（实际 166-258）；**内联 system_prompt 在 171-192**（`Rules: 1. You may select multiple existing events. 2. ...`）；唯一 LLM 调用在 218-223；全函数无 `self.attribution_prompt` | 引用起点精确，末行 247 略短 |
| C17 | §2④ | 选中已有事件就再调 1 次 LLM 重写事件摘要/关键词（`_llm_generate_event_info`, **`src/event_manager.py:242-286`**，用 `prompts/event_generation_prompt.txt`） | ✗ | **行号错**：`_llm_generate_event_info` 实际在 **`src/event_manager.py:267-327`**；**242-286 落在另一个函数 `_update_event_info`(229-266) 内**。prompt 文件 ✓（`self.generation_prompt` 在 315 被用，加载于 20/27-28）。另：`_update_event_info` 是**每个命中事件各调一次**（`event_level_pipeline.py:47-57` 循环内），新建事件也各调一次（`_create_new_event:185`→198） | 全文档唯一"照行号打开会看到错函数"的引用 |
| C18 | §2⑤ | 不是实时写，是"待处理事实攒够 10 条"才触发（`check_and_trigger_batch_extraction`, `src/profile_manager.py:31-40`；`PROFILE_BATCH_TRIGGER=10`, `config.py:66`） | ◐ | 行为 ✓：`len(pending_facts) >= config.PROFILE_BATCH_TRIGGER` 在 **41**；`config.py:66` 精确。但函数 def 在 **`profile_manager.py:27`**，**引用的 31-40 整段落在 docstring（Args/Returns）里**，恰好没盖住触发行 41 | |
| C19 | §2⑤ | 触发后按人分组，**调 1 次 LLM** 抽取候选画像句（`profile_extraction_prompt.txt`） | ◐ | 分组 ✓（`incremental_temporal_profile.py:145-148`），但 `_llm_extract_profiles` 在 **每人循环内各调一次**（151-153），batch 里有 N 个人就是 N 次调用，不是 1 次 | |
| C20 | §2⑤ | `IncrementalTemporalProfileProcessor.process_candidate`（`incremental_temporal_profile.py:82-107`），内部调父类 `TemporalProfileBuilder`（`temporal_profile_version_chain.py:151`）的方法链 | ✓ | def **82**（实际 82-112）；`TemporalProfileBuilder` class def **151**（精确）；方法链 `_prepare_candidate`(88)→`_retrieve_candidates`(92)→`_direct_decision`(100)→`_llm_decide`(105)→`_apply_decision`(102/106) | |
| C21 | §2⑤ | 检索该用户 top-8（`PROFILE_TEMPORAL_TOP_K=8`），最高相似度 < 0.55（`PROFILE_TEMPORAL_MIN_LLM_SCORE`）→ **不调 LLM**直接建新 | ✓ | `config.py:68-69` 精确；`_retrieve_candidates`（`temporal_profile_version_chain.py:229-250`）用 α/β 打分后 `[: self.top_k]`；`if not candidates or top_score < self.min_llm_score: temporal_profiles.append(prepared)` 在 `incremental_temporal_profile.py:95-98`，**该分支之前无任何 LLM 调用** | |
| C22 | §2⑤ | 文本完全相同（规范化后逐字比对）→ **不调 LLM**，直接 `confirm`/`update_history`（`_direct_decision`, `temporal_profile_version_chain.py:252`） | ✓ | def **252**（精确）；`same_text` 比对 261；`action = "confirm"` 265，更早生效时间则改 `update_history` 268-269；返回决策字典 272-282，**全程无 LLM** | |
| C23 | §2⑤ | 否则调 1 次 LLM 决策 `confirm`/`update_current`/`update_history`/`new`（`profile_temporal_update_prompt.txt`） | ✓ | `_llm_decide`(284-295) 单次 `call_with_retry(..., call_type="profile_temporal_update")`；`TEMPORAL_UPDATE_PROMPT` = `prompts/profile_temporal_update_prompt.txt`（同文件 27）；四分支分派在 `_apply_decision`(350-391) 的 371-388 | |
| C24 | §2⑤ | `update_current` 时把旧 content 连同有效期一起克隆进 `history` 再覆盖（`clone_current_to_history`, :131；`_apply_update_current`, :410）——全系统**唯一**做版本保留的模块 | ✓ | 两个 def 行号 **131 / 410 均精确**；克隆调用在 417-419，覆盖在 421-426；`history` 只在 `clone_current_to_history`(140-148) 和 `_apply_update_history`(446-455) 里被写，Fact/Event 层全仓库无任何 history 字段 | 引用**精确到行** |
| C25 | §2⑤ | 整段对话跑完后 `force_profile_extraction()` 兜底（`preextracted_pipeline.py:362`），随后落盘（`save_memory_snapshot`, `incremental_temporal_profile.py:324`） | ✓ | **362 精确**（在 `process_all_facts` 全部 session 循环结束之后）；子类 override `process_all_facts`(313-317) 在 super() 之后调 `_finalize_temporal_profiles`(315)+`save_memory_snapshot`(316)；`save_memory_snapshot` def **324 精确**，写 `facts_*/events_*/profiles_*.json`(329-332) | 引用**精确到行** |

### 2.7 code-architecture.md — §3 检索侧 / §4 架构图

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| C26 | §3 触发 | `AtomMemGraphQueryResponder.answer_query`（`run_atommem_pipeline.py:296`）每次提问触发一次，内部调 `answer_query_with_query_info`（312-386） | ✓ | def **296 精确**，296-298 转发；`answer_query_with_query_info` def **312 精确**（实际到 396）；`evaluate_locomo.py:772` 每题调一次 | |
| C27 | §3 | 先调 1 次 LLM 解析 query 意图（`_extract_query_intent`, **`src/query_response.py:157-179`**，用 `query_intent_prompt.txt`）得 `need_attribute`/`people`/`keywords`/`time` | ◐ | 行为 ✓（prompt 加载 31/37-38，唯一调用 `call_type="query_intent"` 在 154，返回四字段 166-172）。**行号错**：def 在 **`query_response.py:138`**（实际 138-172）；157-179 横跨 fallback 返回块与真返回块、并溢出到下一函数 | |
| C28 | §3-1 | 主召回：按 people/time 过滤后 `Sh` 排序取 top-5（`_main_recall_facts`, **`src/retrieval.py:150-173`**；`MAIN_RECALL_TOP_K=5`） | ◐ | 行为 ✓（`_filter_facts` 在 145、Sh 打分 154-157、`[:config.MAIN_RECALL_TOP_K]` 在 **162**；`config.py:73`）。**行号偏 13 行**：def 在 **`retrieval.py:137`**（实际 137-162） | |
| C29 | §3-2 | 补偿召回：`Sh` 取 top-5 事件（`_retrieve_events`, **`retrieval.py:252-274`**；`EVENT_RECALL_TOP_K=5`），展开未被主召回覆盖的成员事实，`0.7·事件分+0.3·事实分`（`COMPENSATION_EVENT_WEIGHT=0.7`）取 top-5（`_compensation_recall_facts`, **`retrieval.py:189-249`**） | ◐ | 行为**全对**：`_retrieve_events` 取 `[:config.EVENT_RECALL_TOP_K]` 在 265；跳过 `main_fact_ids` 在 197-198；融合分 230-231 用 `COMPENSATION_EVENT_WEIGHT`/`COMPENSATION_FACT_WEIGHT`（`config.py:81-82`）；`[:config.COMPENSATION_FACT_TOP_K]` 在 239。**两处 def 实际在 `retrieval.py:241` 和 `retrieval.py:164`**，偏 11 / 25 行 | `retrieval.py` 四处引用（C28/C29/C39 相关）整体系统性偏移 |
| C30 | §3-2 | 两路合并、去重后截到 `GRAPH_MAX_SEED_FACTS=10` 作为 seed_facts（`run_atommem_pipeline.py:339`） | ✓ | **339 逐字命中** `seed_facts = base_result.get("facts", [])[: config.GRAPH_MAX_SEED_FACTS]`；`config.py:102` | 去重发生在补偿召回排除 `main_fact_ids` 那一步 |
| C31 | §3-3 | 三通道局部子图，仍受 people/time 过滤，`max_hops=2`、`max_local_nodes=180` | ✓ | `_build_local_node_set`（`multichannel_graph.py:288-326`）按 `cfg.max_hops` 逐跳、`cfg.max_local_nodes` 截断；过滤在 `_top_neighbors_for_expansion:360` → `_fact_matches_query_filters:607-633`（people 617、time 619-632）；`config.py:105-106` | |
| C32 | §3-3 | 种子分先"检索分 + 0.05·排名先验"混合，再做 **5 次幂**锐化并归一化（`SeedOnlyGraphReranker._build_seed_scores`, `graph_rerank.py:83-114`；`GRAPH_SEED_SCORE_POWER=5.0`） | ✓ | def **83**，函数正好结束于 **114**（范围完全精确）；`retrieval_score + 0.05 * rank_prior` 在 99（`rank_prior = 1.0/(rank+1)` 在 98）；`normalized ** seed_score_power` 在 111；归一 113-114；`config.py:103` | 与论文 Eq.9 数学等价（代码先除 max 再幂、论文直接幂后归一，常数抵消） |
| C33 | §3-3 | 关键词边 = IDF 加权重叠 / 几何平均归一化（`multichannel_graph.py:518-530`） | ✓ | def **518**，函数正好到 **530**（范围精确）；分子 526、分母 `sqrt(left_total*right_total + edge_epsilon)` 529 | 与 Eq.3 逐项对应 |
| C34 | §3-3 | 事件边 = `1/(事件大小-1)^1.25`（`:532-544`） | ✓ | def **532**，函数到 **544**（精确）；`1.0 / (max(size-1,1) ** self.config.event_size_alpha)` 在 543；`GRAPH_EVENT_SIZE_ALPHA=1.25`（`config.py:93`）；另有 `max_event_size=60` 跳过（541-542） | 与 Eq.4 对应 |
| C35 | §3-3 | 对话轮边 = `exp(-轮次距离/2.0)`（`:546-556`） | ✓ | def **546**，函数到 **556**（精确）；同 session 判定 549、窗口 552、`math.exp(-distance / self.config.tau_turn)` 556；`GRAPH_TAU_TURN=2.0`/`GRAPH_TURN_WINDOW=2`（`config.py:98-99`） | 与 Eq.5 对应 |
| C36 | §3-3 | 多通道 PPR 按节点级"有效通道"动态归一化通道权重后跑迭代（`_run_ppr`, `:426-462`），收敛或跑满 `GRAPH_MAX_ITER=20` 后取 `GRAPH_FINAL_TOP_K=10` | ✓ | def **426**（实际到 486）；`active_channels` 收集 454-460、`adjusted_rho = rho / active_rho_sum` 467（= Eq.8）；重启项 450、传播项 472-474（= Eq.10）；悬挂节点 `sink_mass` 回灌 476-480；收敛判据 482-485（= Eq.11，`GRAPH_TOL=1e-6`）；top-k 取自全部局部节点 `graph_rerank.py:167-170` | 收敛判据(482-485)略超所引 426-462 |
| C37 | §3-3 | 若种子为空则退化成 seed_facts | ✓ | `run_atommem_pipeline.py:346`（`if self.enable_graph and seed_facts`）、358-359 else 分支；另 356-357 图返回空也退化 | |
| C38 | §3-4 | `need_attribute=True` 时按 person 过滤 + `Sh` 取 top-5（`PROFILE_RECALL_TOP_K=5`），再按 query 时间选当前/历史版本（`_apply_profile_time_filter`, `incremental_temporal_profile.py:229`） | ✓ | `retrieval.py:52-53` 条件、`_retrieve_profiles:57-90`（person 筛 73、Sh 84-86、`[:config.PROFILE_RECALL_TOP_K]` 90，`config.py:77`）；`_apply_profile_time_filter` def **229 精确**，当前版本 249 / 历史版本 252-256 | |
| C39 | §3 | `_generate_answer`（`src/query_response.py:174-230`）格式化 facts/profiles，按 category 选模板（`_load_category_prompt`, **`query_response.py:44-59`**：cat2 时间推理 / cat3 开放域 / 其余默认），最后 1 次 LLM（`response_format="text"`） | ◐ | `_generate_answer` def **174 精确**（实际 174-217）；`response_format="text"` 在 **212**；格式化 `- F5: "..." recorded_date=...` 在 246-249、`- P3: "..."` 在 228（文档漏了前导 `- `）。**`_load_category_prompt` def 在 46**（44 落在 `_load_answer_prompt` 内），cat2/cat3/默认分支 53-58 ✓ | |
| C40 | §3 | `event_contexts` 被显式丢弃：`_ = event_contexts, query_info`（:195）、手传 `event_contexts={}`（:198）、`_format_facts_for_prompt` 内部同样丢弃（:232-234） | ✓ | **195 / 198 / 232-234 三处逐字命中**（`_ = event_contexts` 在 **234**）；产生端 `retrieval.py:117-133` 与 `run_atommem_pipeline.py:399-412` 确实认真算了；传递端 `run_atommem_pipeline.py:365→373` 送到门口 | 全文档最重要的发现，**三个行号全精确** |
| C41 | §4 图 | "① 元数据抽取 LLM `preextracted_pipeline.py:66`" | ◐ | def 在 **67**，66 是空行 | 差一行 |
| C42 | §4 图 | 去重 `fact_storage.py:138`；冲突 `:167,79-82`；事件 `fact_seeded_event_pipeline.py:132` / `event_level_pipeline.py:166` | ✓ | 四处 def/行号全部精确 | |
| C43 | §4 图 | 画像 `temporal_profile_version_chain.py:132,162` | ◐ | 132 在 `clone_current_to_history`(131-148) 首行内，可接受；**162 落在 `TemporalProfileBuilder.__init__` 的 stats 字典（`"llm_calls_attempted": 0`）里**，与节点标注的"LLM抽取+confirm/update/new、旧值克隆进 history"无关 | 正文用的 131/410 才是对的 |
| C44 | §4 图 | 最终答案生成 LLM `query_response.py:174` | ✓ | `_generate_answer` def **174** | |
| C45 | §4 图 | 纯文件存储，无数据库 | ✓ | `src/file_storage.py:24-27` 三个 JSON 路径 + `entity_graph_*.json`；全仓库无 sqlite/DB 依赖（`requirements.txt` 无 DB 包） | |
| C46 | §4 图注 | 8 类 LLM 调用点；全部走同一个 `LLMInterface`，和最终答案生成用**同一个 backbone**（`config.LLM_MODEL` 默认 `gpt-4o-mini`） | ✓ | 全仓库 `call_type=` 精确 8 个取值：`metadata_extraction` / `conflict_detection` / `event_attribution` / `event_generation` / `profile_extraction` / `profile_temporal_update` / `query_intent` / `answer_generation`；5 处 `LLMInterface()` 实例（`preextracted_pipeline.py:33`、`profile_manager.py:17`、`fact_storage.py:33`、`query_response.py:28`、`event_manager.py:17`）均读同一 `config.API_KEY/API_BASE/LLM_MODEL`（`llm_interface.py:27-30`）；`config.py:43` 默认 `gpt-4o-mini` | 计数**完全正确** |
| C47 | §4 图注 | 唯一独立模型接口是 Fact Extractor（`config.FACT_EXTRACTOR_*`），但在 LoCoMo 跑分链路里根本不会被调用 | ✓ | `config.py:49-51`；`evaluate_locomo.py` 无任何 `FactExtractor` 引用 | |

### 2.8 code-architecture.md — §5 我没搞清楚的 / §6 与论文的冲突点

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| C48 | §5.1 | 预抽取文件无模型版本/生成脚本记录；仓库无生成脚本痕迹（evaluate/run 只读不写该目录） | ✓ | `conv-26.json:1-4` 只有两个 metadata 字段；`evaluate_locomo.py:93-94,355` 只读该目录，全仓库无写入该路径的代码 | |
| C49 | §5.2 | `EventManager` 基类两阶段流程在跑分链路完全不触发（`process_event_attribution` 被子类整体覆盖，`event_level_pipeline.py:18`）；`event_attribution_prompt.txt` 加载了却从未被用到 | ✓ | 覆盖 def **18 精确**；`self.attribution_prompt` 唯一使用点是 `event_manager.py:174`（`_llm_judge_clustering`），而 `_llm_judge_clustering` 唯一调用点是基类 `process_event_attribution:54` —— 被覆盖后永不执行；但 `_load_prompts`(23-28) 仍在 `__init__` 无条件加载 | 调用链两端都追过 |
| C50 | §5.3 | "AtomMem-Flat"/"w/o Profile" 无对应命令行开关，只有 `--disable-graph` | ✓ | `run_atommem_pipeline.py:558` `--disable-graph`；全仓库 `grep -i "flat\|ablation\|w/o profile\|disable.profile"` 仅命中 `query_response.py:222` 的 `"(No profiles found)"` 字符串 | |
| C51 | §5.4 | `llm_interface.py:13` docstring 写 "LLM API interface for calling Qwen via DashScope compatible mode"，但 `config.py` 默认 API_BASE 是 OpenAI、LLM_MODEL 默认 gpt-4o-mini，与论文 §4.1 "re-implemented all baselines using GPT-4o-mini" 一致 | ✓ | `llm_interface.py:13` 逐字命中；`config.py:42-43`；论文 txt:638-639 | 引用**精确到行** |
| C52 | §5.5 | 两个 data 目录都只有 10 个 conv 文件；Table 1 AtomMem token = 21357.06K；只有代码实际跑的那几步会被 `get_aggregate_llm_statistics()`（`incremental_temporal_profile.py:334`）计入 | ✓ | 两目录各 10 个 `conv-*.json`；论文 txt:630 = `21357.06`；def **334 精确**，它只聚合 pipeline/fact_storage/event_manager/profile_manager 四个 `LLMInterface`(335-340)，`FactExtractor` 自带独立 `self.stats`（`run_atommem_pipeline.py:123-128`）不在其中 | |
| C53 | §6① | 仓库不含任何模型权重文件 | ✓ | `find . -iname "*.pt" -o "*.ckpt" -o "*.bin" -o "*.safetensors" -o "*.pth"`（排除 .git）**零结果** | |
| C54 | §6① | `requirements.txt` 无 torch/transformers/peft——只有 `openai`（走 API）和 `sentence-transformers`（仅 embedding） | ◐ | 无 torch/transformers/peft ✓。但实际七行：`openai / httpx / fastapi / uvicorn / numpy / sentence-transformers / tqdm`，"只有两个"是简化 | |
| C55 | §6① | 仓库提供 `data/SFT_training_data.json`，**4352 条**，与论文 **§A.3** 数字一致 | ◐ | 实测 `len(json) == 4352` ✓ 与论文 txt:1162 一致；但节号应为 **§A.1.3**（同 P15） | |
| C56 | §6① | Figure A.1（txt:1189-1207）编号的抽取规则是 **5 条大类**（不是 6 条） | ✓ | txt:1189-1207 一级编号 1./2./3./4./5. 共 5 条，行号范围**精确** | 对任务描述的"六条"做了正确更正 |
| C57 | §6① | demo 服务器（`run_demo_server.py:118-140` `DemoFactExtractor`）的 prompt 和 `SFT_training_data.json` 的 `instruction` **逐字几乎完全一致**（都有 "rewrite it as objective third-person facts" 整句），忠实覆盖 ①②③⑤ | ✓ | class def **118**；`user_prompt_template` **131-146**，首句 `Extract high-value factual information from the given dialogue and rewrite it as objective third-person facts.` 与 SFT 样本 `instruction` 首句逐字相同，六条 Requirements 与 `INFORMATION TO EXTRACT FROM Current Dialogue:` / `Please extract all factual information...` 框架全一致 | 引用末行 140 略短于 146 |
| C58 | §6① | 公开批处理脚本（`run_atommem_pipeline.py:105-166` `FactExtractor`）**完全没提"改写第三人称"**（只写 "Keep each fact objective, complete, and standalone"），也没有 "treat as primary source" | ✓ | class def **105**；system_prompt 119-122；user_prompt 166-180，`- Keep each fact objective, complete, and standalone.` 在 **171**，**全 prompt 无 "third"**；图像信息只是 `Image description: ...` / `Image keywords: ...` 拼接（156-164），无 primary-source 指令 | 引用**行为完全成立**，末行 166 略短于 206 |
| C59 | §6① | 跑分入口两条路径都不走，直接读 `data/locomo_preextracted_facts/` | ✓ | 同 C2/C4 | |
| C60 | §6② | 论文侧：Figure 8/A.3 与 Figure 9/A.4 Input 四项含 `event_contexts`；§3.5.3 "enriched by event-level context" | ✓ | txt:1739 / txt:1762 / txt:436（同 P45/P46） | |
| C61 | §6② | 仓库里三份实际使用的答题 prompt 文件（`answer_generation_prompt.txt`、`_cat2.txt`、`_cat3.txt`）**逐句和论文 Figure 8/9 几乎一致**，唯独都没有 "event_contexts" 这一行输入说明 | ✗ | "都没有 event_contexts" ✓（三份 Input 说明各只有 Query / Selected Profiles / Selected Facts 三项；且 `_cat3.txt:12` 还明令 `Do not use unselected retrieved evidence, event summaries, retrieval scores, keywords, or outside conversation details`——比文档说的更强）。但"三份逐句几乎一致"**不成立**：只有 `answer_generation_prompt.txt`(1-20) 与 Figure 8（txt:1740-1751）近乎逐字；`_cat2.txt`(1-25) 是**论文里完全不存在**的时间推理专用模板（5 条时间表达规则 + 4 条输出规则，含 "the Sunday before 22 May 2023" 这类论文没有的规定）；`_cat3.txt`(1-35) 与 Figure 9（txt:1757-1778）只是主题相同，5 条 Reasoning rules + 4 条 Output rules + 2 个 worked example 全是自写 | 而且论文 Figure 8 明确把 **temporal 与 single/multi-hop 归为同一个 prompt**（caption txt:1753-1754），代码却给 cat2 单开一套——这是文档漏掉的一条 code-only 分歧（见 §5 D6） |
| C62 | §6③ | Profile 批处理粒度：论文说每 session 结束（txt 引文），代码是"整个 conversation 结束 + 攒够 10 条"的混合体，计数器跨 session 累积、与 session 边界无关 | ✓ | 论文 txt:356-360 引文逐字；代码 `profile_manager.py:39` 扫的是**全部** `all_facts` 的 `needs_profile_extraction` 标志（无 session 维度），41 行触发；`preextracted_pipeline.py:362` 在全部 session 循环之后；`process_all_facts` 的 session 边界处（235-253）只做 storage_snapshot 统计，**不触发画像** | 结论**完全成立**，是本文档第二硬的发现 |
| C63 | §6③ | LoCoMo 一个 conv 通常有 19-35 个 session | ✓ | `conv-26.json` metadata `total_sessions: 19`；论文 txt:466-467 `average over 600 turns across 35 sessions` | |
| C64 | §6④ | 论文框成"一次 LLM 联合产出残差+冲突更新"，代码拆成"无 LLM 硬阈值去重"+"LLM 二元冲突判断+整条覆盖"两条路；旧文本无保留渠道 | ✓ | 论文 txt:264-274；代码 `fact_storage.py:162`（0.95 无 LLM）与 213/222/246-247/79-82（二元判断+四字段覆盖），两条路径触发条件独立 | |
| C65 | §6⑤ | 论文 Algorithm 1 **第 5-11 行**明确写 "for all F ∈ Cret"；代码 `_retrieve_top_event_candidates`（`fact_seeded_event_pipeline.py:63-101`）调自己的 `_retrieve_top_similar_facts`（同文件 132-155）独立做 top-10 检索，两套权重在 config 里独立可调 | ✓ | Algorithm 行号 5-11 = txt:1290-1301（**算法内行号精确**）；`_retrieve_top_event_candidates` def **63**（实际 63-108）、`_retrieve_top_similar_facts` def **132**（实际 132-159）；`config.py:62-64` vs `79-80` 两套 | 结论成立；两处函数末行号略短 |
| C66 | §6⑥ | Table 2 的 AtomMem-Flat / w/o Profile 无 CLI 参数或代码分支 | ✓ | 同 C50 | |

---

## 3. 步骤清单 — 论文侧

**系统边界（论文）**：`§3.1–§3.5.3` 全部属于 AtomMem 本体，其中 Fact Executor 是本体自带的**独立 SFT 小模型**（离线训练一次，Eq.1），其余所有 LLM 调用论文只写 "the LLM"、未说明模型归属。原始多轮对话的产生、最终 backbone 生成的模型选择（GPT-4o-mini）、以及 judge（Figure 10/A.5）属于**评测脚本 / agent 侧**。上下文组装（C = Rfact ∪ Rprof，Figure 8/9 的 prompt 模板）论文写进了附录，算在系统内；`P-GENERATE` 是边界外的最后一跳。

### 3.1 离线（一次性）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| O1 | Dataset Construction (Stage 1 Teacher / Stage 2 Human) §A.1.2 | 离线一次 | 原始 LoCoMo 式对话 → D = 4,352 条 (I, C, F) | GPT-4o 教师模型逐条抽取（人工精修阶段无 LLM） | — | P-EXTRACT |
| O2 | Fact Executor SFT §3.1.1 / Eq.1 / §4.1 | 离线一次 | D + Qwen3-14B 基座 → LoRA(rank 128) 权重 | no（是训练本身） | — | **P-TRAIN** |

### 3.2 写入侧（每条对话消息）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| W1 | Atomic Fact Extraction §3.1.1 | **每条原始对话消息**（Figure A.1 "from the current message, using recent conversation context"） | 当前 message + 近邻上下文 + 元数据 + `[Image Description]/[Image Keywords]` → JSON 数组的原子事实文本（可为空） | 1× **Fact Executor**（独立 SFT Qwen3-14B），同一次调用内完成"过滤低价值 / 指代+时间消解 / 第三人称改写 / 多模态融合" | — | P-INTAKE > **P-REWRITE + P-EXTRACT**（同一次调用） |
| W2 | Structured Fact Construction §3.1.2 | 每条抽出的 fact | fact 文本 + 对话 → F={id,c,v,P,K,T,E}，E 初始为空 | 1×（解析 P/K/T；§3.3 说同阶段还顺手标记"是否暗示长期特征"） | — | **P-META + P-EMBED** |
| W3 | Fact Verification — 符号过滤 §3.1.3 | 每条新 fact 入库前 | Fnew + 全局记忆 → 候选池（按 participants + temporal 过滤，明说是为了省向量计算） | no | 读 fact 库 | **P-SYMFILTER** |
| W4 | Fact Verification — 混合相似度 top-k §3.1.3 / Eq.2 | 同上 | 候选池 → Cret = top-k，Sh = α·sim_e + β·Jac | no | 读 fact 库 | **P-DENSE + P-FUSE**（加权和） |
| W5 | Fact Verification — 联合残差/冲突 §3.1.3 | 同上 | (cnew ∥ Cret) → (c'_new 残差新信息, U 更新元组集合，U 只在检测到逻辑冲突时生成) | **1×（同一次调用同时产出两样东西）** | 写 fact 库（新增 c'_new + 按 U 更新旧 fact） | **P-DEDUP + P-CONFLICT**（注：非阈值式，是 LLM 残差提炼）> P-PERSIST |
| W6 | Episodic Consolidation §3.2 / Algorithm 1 | 每条已验证 fact | **复用 W4 的 Cret**（Alg 5-11）→ Ecand ∪ Falone → LLMverify 路由 → 并入命中事件（Fids 并、Pe/Te 集合并、LLMsummarize 重生成 S/Ke）/ 为每个命中的独立事实各建一个新事件 / 都没命中则 StoreIndependently | 1× 路由（LLMverify，可多选可全不选）+ **每个命中事件各 1×** LLMsummarize | 写 event 库 + 回写 fact.E | **P-AGGREGATE** > P-PERSIST |
| W7 | Temporal Profile — 入队 §3.3 | 每条 fact（在 W1/W2 的抽取阶段顺手判定） | fact → "可能是长期特征"标志 → 等待队列 | 0（复用 W1/W2 的调用） | 队列 | P-META |
| W8 | Temporal Profile — session 末批处理 §3.3 | **每 session 末**（"At the end of a dialogue session"） | 队列里的候选事实 → 候选画像句 | 1×（论文未说是否按人分批） | 读 fact 库 | **P-AGGREGATE** |
| W9 | Temporal Profile — 相似画像检索 §3.3 | 每条候选画像 | 该用户已有画像 → top-kp（用 Sh，Eq.2） | no | 读 profile 库 | **P-DENSE + P-FUSE** |
| W10 | Temporal Profile — 时序决策 §3.3 | 每条候选画像 | 候选 + top-kp → {redundant / update current / modify historical version / new} | 1× | 写 profile 库；current 变动时旧状态**连同有效时间区间拷进 H** | **P-CONFLICT（版本化，非破坏性）** > P-PERSIST |

> 论文写入侧**没有**：显式的持久化图构建步骤（三类边由 fact 元数据隐式定义，且 Entity 边权 ω(k) 依赖 query keywords（Eq.6），只能在查询时算）、驱逐/剪枝、ANN 索引、KV 窗口。

### 3.3 检索侧（每次提问）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| R1 | Query Intent Analysis §3.5.1 | 每 query | q → Qparsed = {Iprof, Pq, Kq, Tq} | 1× | — | **P-QUERYPARSE** |
| R2 | Query 编码（隐含） | 每 query | q → vQ（Sh(F,Q) 需要） | no | — | P-EMBED |
| R3 | Primary Recall §3.5.2(1) | 每 query | 全局 facts →（Pq/Tq 过滤）→ Sh(F,Q) 排序 → Rpri = top **ks/2**（txt 转写作 "k2s"；A.6.1 明说 main seed = 5） | no | 读 fact 库 | **P-SYMFILTER > P-DENSE + P-FUSE** |
| R4 | Compensatory Recall §3.5.2(2) | 每 query | 事件层（元数据过滤 → Sh(E,Q) 取 top 事件）→ 展开成员事实 → 排除 Rpri → Sf = we·Sh(E,Q) + (1−we)·Sh(F,Q) → Rcomp = top ks/2；Rseed = Rpri ∪ Rcomp | no | 读 event + fact 库 | **P-SYMFILTER > P-DENSE > P-FUSE**（事件分与事实分加权融合） |
| R5 | Associative Recall — 子图构造 §3.5.2(3) / §A.3 | 每 query | Rseed → 限跳扩展 + 保留 top neighbors + 仍受 participant/temporal 约束 → 局部子图 | no | 读 fact/event 库 | **P-LINK**（查询时算 Eq.3-5 边权）**+ P-GRAPHEXPAND** |
| R6 | Associative Recall — 种子重启分布 §A.3.3 / Eq.9 | 每 query | Rseed 检索分 → 幂变换 s̃^γs / Σ s̃^γs → p | no | — | P-DIFFUSE（准备） |
| R7 | Associative Recall — 多通道 PPR/RWR §A.3.2-3 / Eq.7-11 | 每 query | 三通道各自归一化为 Pc → 按节点有效通道集合 Ci 动态重归一化 ρ̄（Eq.8）→ r(t+1)=ηp+(1−η)PᵀR(t)（Eq.10）+ 悬挂节点按 p 回灌 → 收敛(Eq.11) → 按 r(∞) 取 **top kf** = Rfact | no | — | **P-DIFFUSE**（兼作 P-RERANK：最终排序就是激活分排序） |
| R8 | Profile Recall §3.5.3 | 每 query，**~仅当 Iprof=1** | 全局 profiles →（Pq 过滤）→ Sh(Pq,Q) → Rprof = top kp；若 query 带时间约束则选该时间有效的版本（当前或历史） | no | 读 profile 库 | ~**P-SYMFILTER > P-DENSE + P-FUSE** |
| R9 | Context Assembly §3.5.3 / Figure 8,9 | 每 query | Rfact ∪ Rprof（+ **event_contexts**，Figure 8/9 Input 第四项）→ C | no | — | **P-ASSEMBLE** |
| R10 | Response Generation §3.5.3 | 每 query | (C, q) → 最终回答 | 1× backbone | — | **P-GENERATE**（边界外） |

---

## 4. 步骤清单 — 代码侧

**系统边界（代码）**：
- **记忆系统本体** = `atommem_core/` + `src/`：写入五步（元数据/去重/冲突/事件/画像）、三段召回、图重排、画像时间过滤、prompt 组装。
- **不在本体内**：原子事实抽取。`data/locomo_preextracted_facts/*.json` 是**外部产物**（无生成脚本、无模型记录）；`scripts/run_atommem_pipeline.py:FactExtractor` 与 `scripts/run_demo_server.py:DemoFactExtractor` 是脚本侧可选工具，**跑分链路两条都不走**。
- **agent / 评测脚本侧** = `scripts/evaluate_locomo.py`：分 conv 建库、问答循环、F1/BLEU-1/Recall@10/J 打分与 judge LLM。
- **backbone 边界特殊**：最终答案生成的 LLM 调用发生在**记忆系统内部代码**（`src/query_response.py:174`），且与全部 8 类记忆内部调用共用同一个 `LLMInterface` / 同一模型 —— 代码里**不存在真正的 memory ↔ backbone 分界**。

### 4.1 写入侧

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| w0 | `load_preextracted_facts`（`preextracted_pipeline.py:49`，由 `evaluate_locomo.py:744` 调） | 每 conversation 一次 | `conv-NN.json` → dialogue_results（每 turn 自带 `facts` 字符串数组 + 原始 `text`） | **no** | 读磁盘 JSON | **P-INTAKE** |
| — | *（论文的 W1 P-EXTRACT 在跑分链路里**不存在**：无任何代码执行抽取）* | — | — | — | — | — |
| w1 | `extract_fact_metadata`（`preextracted_pipeline.py:67`，prompt `fact_metadata_extraction_prompt.txt`） | **每条 fact 字符串** | fact 文本 + session_time + 前一轮上下文 → `people/keywords/time[event,interaction]/needs_profile_extraction` | **1×** (`metadata_extraction`) | — | **P-META** |
| w2 | `normalize_keyword_list`（`fact_seeded_event_pipeline.py:17`，经 `incremental_temporal_profile.py:307`） | 每条 fact | keywords → 去标点/小写/去重/**截到 5 个** | no | — | P-META（后处理） |
| w3 | `embedding_model.encode`（`preextracted_pipeline.py:153`，all-MiniLM-L6-v2 / 384 维） | 每条 fact | fact 文本 → 稠密向量 | no | — | **P-EMBED** |
| w4 | `_is_duplicate`（`fact_storage.py:138-165`） | 每条 fact | people 兼容筛 → cosine > **0.95** → 命中即 `IGNORE`（整条丢弃，不入库） | **no** | 读 fact 库 | **P-SYMFILTER > P-DEDUP（阈值）** |
| w5 | `_detect_conflict`(`fact_storage.py:167`) + `_llm_detect_conflict`(`:228`) | 每条 fact | people 兼容筛 → Sh(0.7/0.3) > **0.6** → **top-5** → LLM 二元判断 `has_conflict`+`conflict_fact_id` → 命中则把旧 fact 的 `fact/embedding/keywords/time` **四字段整条覆盖**（`:79-82`）并落盘、新 fact 丢弃 | **1×** (`conflict_detection`) | 写 fact 库 | **P-SYMFILTER > P-DENSE+P-FUSE > P-CONFLICT（硬覆盖，无历史）** |
| w6 | `save_facts`（`fact_storage.py:93-94`） | 每条通过的 fact | → `facts_<conv>.json` | no | 写 fact 库 | **P-PERSIST** |
| w7 | `_retrieve_top_similar_facts`（`fact_seeded_event_pipeline.py:132`） | 每条已入库 fact | **独立重跑一次**全量相似检索 → top-**10**（权重 `EVENT_ATTRIBUTION_*` = 0.7/0.3，与 w5 的 α/β 是两套 config） | no | 读 fact 库 | **P-DENSE + P-FUSE** |
| w8 | `_retrieve_top_event_candidates`（`fact_seeded_event_pipeline.py:63`） | 同上 | top-10 facts → 已挂事件候选（分数取触发它的 fact 的最大分）+ singleton fact 候选 | no | 读 event 库 | P-AGGREGATE（候选构造） |
| w9 | `_llm_judge_event_level_attribution`（`event_level_pipeline.py:166`，**内联 prompt**） | 同上 | 候选 → `selected_event_ids` + `selected_singleton_fact_ids`（可多选、可全空） | **1×** (`event_attribution`) | — | **P-AGGREGATE** |
| w10 | `process_event_attribution`（`event_level_pipeline.py:18`）状态执行 | 同上 | 命中事件 → append fact_id + `_update_event_info`(`event_manager.py:229`) 重写 summary/keywords + people 并集 + time 区间扩张；命中 singleton → 每个各建一个新事件（`_create_new_event:185`） | **每个命中事件 1×**、**每个新建事件 1×**（`event_generation`，prompt `event_generation_prompt.txt`） | 写 event 库 + 回写 fact.event_ids | **P-AGGREGATE > P-EMBED（事件摘要编码）> P-PERSIST** |
| w11 | `check_and_trigger_batch_extraction`（`profile_manager.py:27`，触发行 41） | **每条 fact 入库后检查一次**；`needs_profile_extraction` 待处理数 **≥ 10** 才触发（计数跨 session 累积，**与 session 边界无关**） | 待处理 facts → 触发/不触发 | no | 读 fact 库 | （条件门） |
| w12 | `batch_extract_profiles`（`incremental_temporal_profile.py:134`，prompt `profile_extraction_prompt.txt`） | 触发时 | 待处理 facts **按人分组** → 每人各 1× LLM → 候选画像句（content/keywords/evidence/valid_from） | **每个人各 1×** (`profile_extraction`) | 读 profile 库 | **P-AGGREGATE** |
| w13 | `process_candidate`（`incremental_temporal_profile.py:82`）→ `_retrieve_candidates`（`temporal_profile_version_chain.py:229`） | 每条候选画像 | 同人已有画像 → Sh(α/β) top-**8** | no | 读 profile 库 | **P-DENSE + P-FUSE** |
| w14 | 三分支决策 | 每条候选画像 | ① top 分 < **0.55** → 直接新建（**无 LLM**）② 规范化文本全等 → `_direct_decision`(`:252`) 直接 confirm/update_history（**无 LLM**）③ 否则 `_llm_decide`(`:284`) → confirm / update_current / update_history / new_profile | **0 或 1×** (`profile_temporal_update`) | 写 profile 库 | **P-CONFLICT（版本化）** |
| w15 | `_apply_update_current`（`temporal_profile_version_chain.py:410`）→ `clone_current_to_history`(`:131`) | update_current 时 | 旧 content + valid_from/valid_to → 追加进 `history`，再覆盖当前值 | no | 写 profile 库 | **P-CONFLICT（版本保留，全系统唯一）** |
| w16 | `_normalize_timelines`（`temporal_profile_version_chain.py:495`） | 每次批处理末 + conversation 末 | history 排序/重编号/valid_to 补齐 | no | 写 profile 库 | P-CONFLICT（后处理） |
| w17 | `force_profile_extraction`（`preextracted_pipeline.py:362`）→ `_finalize_temporal_profiles`+`save_memory_snapshot`（`incremental_temporal_profile.py:315-316,324`） | **整个 conversation 全部 session 跑完后一次** | 清空不足 10 条的尾巴 → 落盘 `facts_*/events_*/profiles_*.json` | 视残余量而定（同 w12/w14） | 写全部三个库 | **P-AGGREGATE > P-PERSIST** |

### 4.2 检索侧（每次提问）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| r1 | `_extract_query_intent`（`query_response.py:138`，prompt `query_intent_prompt.txt`）+ `_normalize_query_time_field`（`run_atommem_pipeline.py:415`） | 每 query | q → `need_attribute` / `people` / `keywords`（固定 5 个）/ `time`（YYYY-MM-DD 或 YYYY-MM 列表）；`need_specific` 恒 True | **1×** (`query_intent`) | — | **P-QUERYPARSE** |
| r2 | `embedding_model.encode`（`run_atommem_pipeline.py:308`） | 每 query | q → vQ | no | — | **P-EMBED** |
| r3 | `_main_recall_facts`（`retrieval.py:137`） | 每 query | `_filter_facts`(people/time, `:267`) → Sh(0.7/0.3) → **top-5** | no | 读 fact 库 | **P-SYMFILTER > P-DENSE + P-FUSE** |
| r4 | `_compensation_recall_facts`（`retrieval.py:164`）+ `_retrieve_events`（`:241`） | 每 query | `_filter_events`(`:309`) → Sh(E,Q) **top-5 事件** → 展开成员（跳过主召回命中）→ `0.7·max事件分 + 0.3·事实自身分` → **top-5** | no | 读 event + fact 库 | **P-SYMFILTER > P-DENSE > P-FUSE** |
| r5 | 种子截断（`run_atommem_pipeline.py:339`） | 每 query | 主+补偿合并 → `[:GRAPH_MAX_SEED_FACTS=10]` | no | — | **P-SELECT（阈值截断）** |
| r6 | `_build_local_node_set`（`multichannel_graph.py:288`） | 每 query，**~仅当 `--disable-graph` 未开且种子非空** | 种子 → 最多 **2 跳**扩展、≤**180** 节点；每跳邻居仍过 `_fact_matches_query_filters`(`:607`) 的 people/time 过滤 | no | 读 fact/event 库 | ~**P-GRAPHEXPAND** |
| r7 | `_build_channel_adjacency`（`multichannel_graph.py:366`）+ 三个边权函数（`:518/:532/:546`） | 每 query（**边权是查询时才算的**，ω(k) 依赖 query keywords） | 局部节点 → 三通道邻接表；每通道邻居数上限 30/10/6；关键词边和轮次边额外过人物门（`:567`/`:558`） | no | — | ~**P-LINK** |
| r8 | `_build_seed_scores`（`graph_rerank.py:83-114`） | 每 query | 检索分 + 0.05/(rank+1) → 除以 max → **5 次幂** → 归一化 = 重启分布 | no | — | ~P-DIFFUSE（准备） |
| r9 | `_run_ppr`（`multichannel_graph.py:426`） | 每 query | 节点级有效通道 ρ 重归一化 → η=**0.34** 重启 + 边权归一传播 + sink mass 回灌 → ≤**20** 轮 / L1 < **1e-6** → 全部局部节点按分排序取 **top-10** | no | — | ~**P-DIFFUSE > P-RERANK** |
| r10 | `_retrieve_profiles`（`retrieval.py:57`）+ `_apply_profile_time_filter`（`incremental_temporal_profile.py:229`） | 每 query，**~仅当 `need_attribute=True`** | person 精确过滤 → Sh → **top-5** → 按 query 时间选"当前版本"或某个 history 版本 | no | 读 profile 库 | ~**P-SYMFILTER > P-DENSE + P-FUSE** |
| r11 | `_build_event_contexts`（`run_atommem_pipeline.py:399`） | 每 query | final_facts + events → `{fact_id: "摘要1 \| 摘要2"}` | no | 读 event 库 | **P-ASSEMBLE（死代码：结果在 r13 被丢弃）** |
| r12 | `_load_category_prompt`（`query_response.py:46`） | 每 query | LoCoMo category → cat2（时间推理）/ cat3（开放域）/ 默认 三选一模板 | no | 读 prompts/ | **P-ASSEMBLE** |
| r13 | `_format_profiles_for_prompt`(`:219`) + `_format_facts_for_prompt`(`:232`) | 每 query | facts → `- F5: "..." recorded_date=...`；profiles → `- P3: "..."`；**`event_contexts` 在 `:195/:198/:234` 三处被显式丢弃** | no | — | **P-ASSEMBLE** |
| r14 | `_generate_answer`（`query_response.py:174`，`response_format="text"`） | 每 query | (模板, Query + Selected Profiles + Selected Facts) → 答案字符串 | **1×** (`answer_generation`)，与全部记忆内部调用**同一个模型** | — | **P-GENERATE**（代码上仍在记忆系统内部） |

---

## 5. 论文 ↔ 代码分歧

| # | 分类 | 分歧 | 论文侧证据 | 代码侧证据 |
|---|---|---|---|---|
| D1 | **[paper-only]** | **SFT Fact Executor 整条流水线（P-TRAIN + P-EXTRACT）在跑分链路里不存在**。论文的一号卖点（"Fact Executor 抽原子事实"）在这个仓库里既没有权重也没有推理代码 | 训练配置 txt:662-666；Eq.1 txt:200-207；Figure A.1 抽取 prompt txt:1185-1208 | 无权重文件（find 零结果）；`requirements.txt` 无 torch/transformers/peft；`evaluate_locomo.py:744` 直接读 `data/locomo_preextracted_facts/`；`FactExtractor`(`run_atommem_pipeline.py:105`) 只在 `--extract-facts` 下走，评测入口不引用 |
| D2 | **[两边都有但行为不同]** | **Fact Verification**：论文是"**一次** LLM 联合产出残差新信息 c'_new + 冲突更新元组 U"；代码是两条独立路径——纯阈值去重（无 LLM）+ 二元冲突判断后**整条硬覆盖**。论文的"提炼真正新增的那部分"在代码里**完全不存在**：结果只有"整条存 / 整条丢 / 整条覆盖"三种 | `(c'new, U) ← LLM(cnew ∥ Cret)`，`residual novel information not entailed by the existing context` txt:264-274 | `_is_duplicate` cosine>0.95 → `IGNORE`（`fact_storage.py:162`,66-72，无 LLM）；`_llm_detect_conflict` 只输出 `has_conflict`/`conflict_fact_id`（`:246-247`）；命中后四字段替换 `fact_storage.py:79-82` |
| D3 | **[两边都有但行为不同]** | **事件候选生成**：论文 Algorithm 1 第 5-11 行明确"for all F ∈ **Cret**"（复用验证阶段的检索结果）；代码另起一次全量 top-10 检索，且用**另一套 config 权重**，两次检索互不复用、分数不共享 | Alg 1 第 5-11 行 = txt:1290-1301；§A.2 正文 txt:1105-1107 | `_retrieve_top_similar_facts`（`fact_seeded_event_pipeline.py:132-159`）遍历 `all_facts` 重算；权重 `EVENT_ATTRIBUTION_EMBEDDING/KEYWORD_WEIGHT`（`config.py:63-64`）≠ 冲突检测的 `EMBEDDING_WEIGHT_ALPHA/KEYWORD_WEIGHT_BETA`（`config.py:79-80`）；`EVENT_ATTRIBUTION_TOP_K=10`（`:62`） |
| D4 | **[两边都有但行为不同]** | **Profile 批处理触发时机**：论文明写"每个 dialogue session 结束"；代码里**根本没有 session 边界触发**——只有"待处理队列 ≥10 即触发（计数跨 session 累积）"+"整个 conversation 末尾 force 一次" | `session-based batch mechanism ... At the end of a dialogue session` txt:354-360 | `check_and_trigger_batch_extraction` 在每条 fact 入库后被调（`fact_storage.py:123`），扫的是**全局** `all_facts` 的标志、无 session 维度（`profile_manager.py:39-41`）；`force_profile_extraction` 在全部 session 循环之后（`preextracted_pipeline.py:362`）；session 切换处（`preextracted_pipeline.py:235-253`）只记统计快照 |
| D5 | **[paper-only]** | **event_contexts 进入最终生成**：论文两处（两张 prompt 图 + 正文）明确宣称事件摘要参与答案生成；代码算出来后在生成函数门口被两行代码扔掉，且三份 prompt 文件本身就没有这一项输入说明 | Figure 8/A.3 Input 第四项 txt:**1739**；Figure 9/A.4 同 txt:**1762**；§3.5.3 `enriched by event-level context` txt:**436** | `_ = event_contexts, query_info`（`query_response.py:195`）；`_format_facts_for_prompt(..., event_contexts={})`（`:198`）；`_ = event_contexts`（`:234`）；三份 prompt 的 Input 说明只有 Query/Profiles/Facts；`_cat3.txt:12` 更明令 `Do not use ... event summaries` |
| D6 | **[code-only]** | **按 LoCoMo category 分叉答题 prompt**：代码给 cat2（时间推理）单开一套论文里完全不存在的 5 条时间表达规则模板；论文 Figure 8 明确把 temporal 与 single/multi-hop 归为**同一个** prompt | Figure 8 caption txt:1753-1754 `utilized for single-hop, multi-hop, and temporal reasoning tasks` | `_load_category_prompt`（`query_response.py:46-58`）cat2→`answer_generation_prompt_cat2.txt`、cat3→`_cat3.txt`；`_cat2.txt` 全 25 行（含 "the Sunday before 22 May 2023" 这类锚定式相对时间规定）在论文中无任何对应 |
| D7 | **[两边都有但行为不同]** | **符号过滤的 temporal 分量是空的**：论文说按 participants **+ temporal contexts** 过滤以省向量计算；代码的写入侧时间过滤是**显式 no-op**（一段注释后一个 `pass`），只有 people 生效 | txt:233-235 `filtering the global memory based on shared metadata such as participants and temporal contexts` | `_detect_conflict` 的时间分支 `fact_storage.py:189-195`（`pass  # Include all facts with matching people for now`）；`_is_duplicate`（`:149-157`）也只有 people。检索侧的 `_filter_facts`(`retrieval.py:267`) 才真的做时间过滤 |
| D8 | **[code-only]** | **图边上加了人物门控**：关键词边在两侧 people 都非空且不相交时直接归零，轮次边则走"人物不通过就要求共享关键词或共享事件"的软门；论文 Eq.3 / Eq.5 里没有任何人物项 | Eq.3 txt:316-322；Eq.5 txt:344-353 | `_passes_person_gate`（`multichannel_graph.py:567-572`）被 `_keyword_edge_weight:519` 调用；`_turn_soft_person_gate`（`:558-565`）被 `_turn_edge_weight:554` 调用 |
| D9 | **[两边都有但参数不同]** | **每通道邻居上限**：Table 5 只给了统一的 "Maximum Neighbors per Fact = 30"；代码对事件通道和轮次通道另设 10 和 6，在建邻接表时覆盖掉 30 | Table 5 txt:1684,1690 | `config.py:96`（`GRAPH_MAX_EVENT_NEIGHBORS_PER_FACT=10`）、`:100`（`GRAPH_MAX_TURN_NEIGHBORS_PER_FACT=6`）；覆盖逻辑 `multichannel_graph.py:413-417` |
| D10 | **[两边都有但行为不同]** | **"是否长期特征"的判定位置**：论文说在**原子事实抽取**时由 LLM 顺手判定（§3.1.1 阶段）；代码是在**元数据抽取**那次调用里产出（§3.1.2 位置），因为抽取那一步在跑分链路根本不执行 | txt:357-359 `During atomic fact extraction, the LLM identifies facts implying potential long-term characteristics` | `prompts/fact_metadata_extraction_prompt.txt` 第 4 条 `needs_profile_extraction`；`preextracted_pipeline.py:123`、字段落在 `build_fact_tuple:169` |
| D11 | **[两边都有但参数不同]** | **构建侧阈值论文全无、代码全有**：Table 5 只覆盖检索侧 | Table 5 txt:1625-1729（无任何构建侧阈值） | `DUPLICATE_THRESHOLD=0.95`(`config.py:59`)、冲突相似度门槛 **0.6 硬编码**(`fact_storage.py:213`)、冲突 top-5 硬编码(`:222`)、`EVENT_ATTRIBUTION_TOP_K=10`(`config.py:62`)、`PROFILE_BATCH_TRIGGER=10`(`:66`)、`PROFILE_TEMPORAL_TOP_K=8`/`MIN_LLM_SCORE=0.55`(`:68-69`) |
| D12 | **[paper-only]** | **消融变体无可复现路径**：Table 2 的 AtomMem-FLAT / w/o Profile 在仓库里既无 CLI 开关也无代码分支 | Table 2 txt:823-825 + 数值 txt:700-822 | `run_atommem_pipeline.py:547-565` 全部参数里只有 `--disable-graph`(`:558`) 对应 "w/o Graph"；全仓库 grep `flat`/`ablation`/`disable.profile` 零命中 |
| D13 | **[code-only]** | **Figure A.1 的 5 条规则在仓库两条可运行路径上落地程度不一致**：demo 路径与 SFT instruction 逐字对齐（含第三人称改写）；公开批处理脚本缺失③"改写第三人称"和④"视觉信息作主要来源"两条 | Figure A.1 txt:1189-1207（唯一规范）；SFT 样本 instruction txt:1270-1278 | `run_demo_server.py:131-146`（首句逐字同 SFT instruction）vs `run_atommem_pipeline.py:119-122,166-180`（`Keep each fact objective, complete, and standalone.` 在 :171，全 prompt 无 "third"；图像只做字符串拼接 :156-164） |
| D14 | **[code-only]** | **仓库自身 bug**：README 教用户配 `ATOMMEM_FACT_EXECUTOR_*`，`config.py` 实际读的是 `ATOMMEM_FACT_EXTRACTOR_*`（EXECUTOR vs EXTRACTOR），照 README 配的 Fact Executor 端点**永远不生效**，会静默回落到通用 LLM | —（论文无此层面） | `README.md`（"Configuration" 节）`ATOMMEM_FACT_EXECUTOR_API_KEY/BASE/MODEL` vs `config.py:49-51` `ATOMMEM_FACT_EXTRACTOR_API_KEY/BASE/MODEL`（默认回落 `API_KEY`/`API_BASE`/`LLM_MODEL`） |
| D15 | **[两边都有但参数不同]**（取值一致，参数化方式不同） | **ks 的拆分**：论文用一个统一量 ks，主召回与补偿召回各取 ks/2；代码没有 ks 这个量，而是三个独立可调参数，恰好凑出同样的 5+5=10 | txt:447/474（`top k2s` = ks/2 的转写产物）；A.6.1 txt:1537-1538 `ks = 10, where the main seed and compensation seed are both set to 5`；Table 5 txt:1633,1637 | `MAIN_RECALL_TOP_K=5`(`config.py:73`) + `COMPENSATION_FACT_TOP_K=5`(`:75`) + `GRAPH_MAX_SEED_FACTS=10`(`:102`)，三者可各自改到不自洽 |
| D16 | **[两边都有但行为不同]**（次要） | **PPR 迭代的悬挂节点处理**：论文说悬挂节点的概率质量按重启分布 p 重分配；代码把 sink mass 乘上 (1−η) 后再按 p 回灌，与论文"按 p 重分配"在系数上不完全等同（论文没给系数） | txt:1441-1444 | `multichannel_graph.py:476-480` `next_scores[fid] += (1 - cfg.restart_prob) * sink_mass * seed_score` |

---

## 6. 新造的 primitive 标签

**none。** 全部 24 个论文侧步骤和 31 个代码侧步骤都能用种子词表里的既有标签覆盖。

曾考虑但最终判定不需要新造的三处：
1. "查询时才计算边权重"（`ω(k)` 依赖 query keywords，图不是写入侧的持久产物）—— 这是 `P-LINK` 的**触发时机**属性（每 query 而非每 turn），不是新的原语类型，已用 trigger 列表达。
2. "冲突命中即整条硬覆盖、旧值不留痕" —— `P-CONFLICT` 的定义里已含"覆盖"这一档，与"版本化"同属一个原语的不同实现档位，用备注区分即可。
3. "读现成的外部预抽取事实文件" —— 就是 `P-INTAKE`（原始输入摄入），只是这里的"原始输入"已经是别处加工过的产物；这一点用系统边界说明比新造标签更清楚。

另需说明：`P-DEDUP` 在种子表里写作"阈值去重"，论文侧的 W5 其实是 **LLM 残差提炼**而非阈值判断，代码侧的 w4 才是真正的阈值去重。两边共用 `P-DEDUP` 标签但实现档位不同，这正是 D2 那条分歧的原语级表述，故沿用同一标签并在表里注明，不新造。

---

## 7. 复核统计

| 判定 | 数量 | 分布 |
|---|---|---|
| ✓ 属实 | **101** | paper-architecture.md 50 / code-architecture.md 51 |
| ✗ 不实 | **2** | 均在 code-architecture.md：C17（`_llm_generate_event_info` 行号指向错误函数）、C61（"三份答题 prompt 逐句与 Figure 8/9 几乎一致"） |
| ◐ 部分属实 / 需加限定 | **20** | paper 7（P7 P15 P33 P36 P48 P52 P53）/ code 13（C7 C9 C12 C18 C19 C27 C28 C29 C39 C41 C43 C54 C55） |
| ? 无法核实 | **1** | P29（"与 Mem0g/Zep 的 t_invalid 同族"——论文全文无 Zep/Mem0g/t_invalid，属文档作者自己的跨系统类比，不可用论文证伪或证实） |
| **合计** | **124** | paper 58 / code 66 |

**◐ 的性质分类**：20 条里 **10 条是纯行号/锚点漂移**（函数名与行为都对，只是照行号 `sed` 会偏 1~27 行或套错容器：C7 C9 C12 C18 C27 C28 C29 C39 C41 C43），**4 条是节号/公式号/符号误标**（P15 P33 P36 C55），**6 条是表述过强或简化**（P7 P48 P52 P53 C19 C54）。没有一条 ◐ 推翻了文档的机制性结论。

**结论**：两份文档的机制描述与所有关键发现（event_contexts 被丢弃、事件候选重新检索、Profile 触发粒度、SFT 抽取器缺席、Fact 层硬覆盖 vs Profile 层版本化、8 类 LLM 调用共用同一模型、消融变体无开关）**全部经双向证据核实成立**，可直接作为跨系统骨架合成的输入。使用前建议修正：`code-architecture.md` 的 `src/retrieval.py` 四处行号、`event_manager.py:242-286`、`query_response.py:157-179`、`profile_manager.py:31-40`；`paper-architecture.md` 的 §A.3→§A.1.3、"Eq.6-9 定义种子分布"→"Eq.9"、"top-k2s"→"top ks/2（=5）"。

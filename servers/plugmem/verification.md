# plugmem 架构文档复核报告

> 复核日期 2026-09-05；论文源 `Yang-2026-PlugMem-A-Task-Agnostic-Plugin-Memory-Module-for-LLM-Agents.txt`（3953 行）；代码源 `PlugMem` @ `3b2ce75`（TIMAN-group/PlugMem，2026-06-26 merge PR#18）
>
> 复核方法：论文侧每条断言用 `grep -n` 回到 txt 亲眼定位行号；代码侧每个 `file.py:NNN` 都实际 `sed -n` 打开该行确认，控制流断言顺调用链读到调用点。凡未亲眼看到证据的一律不判 ✓。

## 1. 总评

两份文档的**结论质量很高**：`code-architecture.md` 提出的四个头号冲突（多跳只存在于 HotpotQA 脚本、return score 恒为 0、intent 去重是字符串匹配、importance 被架空）逐条复核**全部属实**，而且我找到了比文档更硬的证据（`src/memory_structuring/structuring_inference.py:138` 把 `get_return()` 的调用**直接注释掉**；`plugmem/` 包内 `multi_hop|Tmax|max_hop|enough` 全部零命中）。`paper-architecture.md` 的机制描述、否定式断言（importance 从未定义、C.5 没有独立 delete 实验、θ_equal 无取值）也全部经得起证伪。

最严重的问题集中在 `code-architecture.md` 的**前言**——它对"哪套代码产出论文数字"和"`plugmem/` 是论文之后才有的"两个基础判断都不成立：三个基准脚本里有两个（LongMemEval、WebArena）**无条件**把 `MemoryGraph` 换成了打向 `plugmem/` 服务的 HTTP 客户端，而 `plugmem/` 包的首个提交是 2026-03-19，**早于** 2026-04 的 ICML 接收。文档自己在第 5 节承认"本次调研没有跑 git log"，这个自认的缺口正好埋了这两条错误。

第二类问题是**行号漂移**：论文侧约 45 个抽检锚点里有 8 处偏移，其中 1 处（"分段阈值在 C.2 行 2437-2438"）完全落在错误的段落上；代码侧的 `file.py:NNN` 精度明显更高（`memory_graph.py` 的 13 个函数入口行号**全部逐行命中**），只有 3 处小漂移。

第三类是**描述不完整**（不算错，但会误导下游合成）：episodic 模式实际会白跑一趟语义检索和一趟程序检索再丢弃；程序检索默认 `k=1` 只返回 1 条 prescription；HotpotQA 的多跳也是 `--n_round_retrieval` 默认 1 的 opt-in——也就是说**默认跑法下三个基准全都不走多跳**，这比文档说的还要极端。

---

## 2. 逐条核对表

### 2.1 `paper-architecture.md`

#### 前言 / §1 一句话机制

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| P-1 | 前言 | "arXiv:2603.03296，ICML 2026，UIUC+清华+MSR" | ✓ | txt:11 `arXiv:2603.03296v1 [cs.CL] 6 Feb 2026`；txt:16 `University of Illinois Urbana-Champaign 2 Tsinghua University 3 Microsoft Research` | ICML 2026 由 repo `README.md:41` 佐证 |
| P-2 | 前言 | "正文共 3953 行" | ✓ | `wc -l` = 3953 | |
| P-3 | 前言 | "双栏抽取会把左右两栏交错，行号不代表阅读顺序" | ✓ | §3.1.1 标题在 430 而 "3. Methodology" 在 432；§3.2 标题在 759 而其正文在 735-757 | 该警告本身成立 |
| P-4 | 前言 | "行号…已逐条核对" | ◐ | 抽检约 45 个锚点，8 处偏移（P-2-2/2-5/2-10/2-13/3-6/3-13/3-14/3-23/3-25），1 处完全错位（2-15） | 结论未受影响，但"逐条核对"不成立 |
| 1-1 | §1 | 核心主张是"知识稀疏性"，decision-relevant info 是抽象知识 | ✓ | txt:161 `knowledge sparsity`；txt:36-37 逐字 | |
| 1-2 | §1 | 三模块引用"行 172-177" | ✓ | txt:172 `shown in Figure 2, our approach consists of: i) a structuring`，句子延伸到 180 | |
| 1-3 | §1 | Figure 2 图注原文 | ✓ | txt:126 逐字一致 | |
| 1-4 | §1 | 认知科学三分 (Tulving 1972) | ✓ | txt:435 `(Tulving, 1972)` | |

#### §2 记忆怎么存进去

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| 2-1 | §2.1 | "τ 公式实际在行 454" | ✓ | txt:454 `τ = [(ot , at )]Tt=1` | |
| 2-2 | §2.1 | "五元组定义在行 469" | ◐ | 实际 txt:**470** `et = (ot , st , at , rt , gt )` | 差 1 行 |
| 2-3 | §2.1 | s_t 由 (s_{t-1},a_{t-1},o_t) 经 LLM 抽取，行 482-483 | ✓ | txt:482-483 逐字 | |
| 2-4 | §2.1 | g_t/r_t 由 LLM 在任务指令+局部上下文条件下标注，行 483-484 | ✓ | txt:483-484 逐字 | |
| 2-5 | §2.1 | "§3.1.1 标题在行 430…早于'3. Methodology'行 434" | ◐ | 430 ✓；"3. Methodology" 实际在 txt:**432** | 交错现象的判断成立，被引行号错 |
| 2-6 | §2.1 | "本小节在行 487 指向 Appendix C.1" | ✓ | txt:487 逐字 | |
| 2-7 | §2.1 | Appendix C.1 标题行 2151，含 Get_State/Get_Subgoal/Get_Reward = Listing 1/2/4 | ✓ | txt:2151；Listing 1/2/4 = 2165/2209/2279，prompt 名 2167/2212/2281 | Listing 3 (Get_Return, txt:2236) 物理上夹在其中，文档未误称其属 C.1 |
| 2-8 | §2.1 | "只有 o_t/a_t 是原文，s_t/g_t/r_t 是 LLM 生成" | ✓ | txt:482-484 + C.1 txt:2153-2164 | |
| 2-8b | §2.1 | （文档写 s_t 由三元 (s_{t-1},a_{t-1},o_t) 推导） | ◐ | C.1 txt:2154-2155 明确还包含 **initial goal G** | 主文确实只写三元，附录补了 G，文档未提 |
| 2-9 | §2.2 | Tam Sventon 例子 + 概念集，行 630-634 | ✓ | txt:631-634 逐字 | |
| 2-10 | §2.2 | "三条约束…行 634-637" | ◐ | txt:634 只是句首 `To ensure extraction`；实际内容在 txt:**605-607** | 内容属实，锚点半错 |
| 2-11 | §2.2 | membership 边：命题→概念 | ✓ | txt:2326 `membership edges linking propositions to their concept tags (p → c)`；Table 2 渲染在 txt:569-570 | |
| 2-12 | §2.2 | provenance 边：命题→源 episodic 单元 | ✓ | txt:2327-2328；主文 txt:615-617 | |
| 2-13 | §2.2 | "N_max=10 + sibling 边（行 2340-2344）" | ◐ | N_max=10 在 txt:**2321**；sibling 在 txt:**2328**。2340-2344 是 Get_Semantic prompt 正文（消解指代示例） | 两条内容都属实，行号全错 |
| 2-14 | §2.2 | 相邻子目标相似度低于阈值就切段，行 638 | ✓ | txt:638-640 逐字 | |
| 2-15 | §2.2 | "Appendix C.2 说这个阈值就是相邻子目标 embedding 相似度，行 2437-2438" | ✗ | 内容属实但在 txt:**2420-2422** (`We compute embeddings of each subgoal and start a new segment if the two adjacent subgoals have similarity below a set threshold`)；txt:2437-2438 是 `Listing 6.` 标题行与 `====` 分隔线 | 本次唯一完全错位的论文锚点 |
| 2-16 | §2.2 | prescription 例子（lowest price）行 724 | ✓ | txt:723-727 | |
| 2-17 | §2.2 | return 分数 ρ∈[1,10]，独立 LLM 评委，正文 728 + C.2 2426-2428 | ✓ | txt:728-730；txt:2426-2427 `we assign each prescription a scalar return score ρ(i) ∈ [1, 10] via a separate LLM evaluator` | 逐字命中 |
| 2-18 | §2.2 | "这是明确交代的第三次独立 LLM 调用" | ✓ | Get_Return 独立成 prompt（Listing 3 @2236/2238，C.2 内另一份 @2467），与 Get_Procedural（Listing 6 @2437/2439）分列 | |
| 2-19 | §2.2 | intent 去重：cosine > θ_equal 才 LLM 合并并刷新 embedding，C.2 行 2429-2431 | ✓ | txt:2428-2431 逐字 | |
| 2-20 | §2.2 | G_P 边：hierarchical (intent→prescription，单向) + provenance (prescription→其**所有**源 episodic)，行 743-747 | ✓ | txt:744-748；"unidirectional" 见 txt:2433；`for all et ∈ M(i)epi` 见 txt:2435 | 引用区间 743-747 覆盖了原句 744-748 |
| 2-21 | §2.2 / §4 | 把 Table 2 的边写作 `"Intent —solves→ Prescription"` | ◐ | Table 2 实际渲染为 `Intent ←solves— Prescription`（txt:598-599，Table 13 同 txt:2122-2124）；箭头方向被反转 | 语义方向由 txt:2431-2433 支持，但**引号内的转写与被引表格相反** |
| 2-22 | §2.2 | §3.1.2 标题行 592 | ✓ | txt:592 | |
| 2-23 | §2.2 | C.2 标题行 2319，含四个 prompt，Listing 5-7 | ✓ | txt:2319；Get_Semantic(2331)/Get_Procedural(2439)/Get_Return(2467)/Get_New_Subgoal(2503)；Listing 5/6/7 = 2329/2437/2501 | |
| 2-24 | §2.3 | episodic 是"可验证证据而非可直接使用的知识"，行 477 | ✓ | txt:476-477 逐字 | |
| 2-25 | §2.3 | Table 2 管它叫 "Source Trace (Event Window)" | ✓ | txt:586 | |

#### §3 记忆怎么被用起来

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| 3-1 | §3.1 | "论文没有讨论 agent 在什么时机发起检索"，只有 §3.2 行 781 那句 | ✓ | txt:781 逐字；全文无检索时机的协议描述（Table 13 只给 `memory.retrieve(goal, state)` 签名） | 否定式断言，已证伪失败 = 属实 |
| 3-2 | §3.2 | 三个 prompt 名与分工由 C.3 给出，行 2522-2524 | ✓ | txt:2522-2525 逐字 | |
| 3-3 | §3.2 | GET PLAN 标 "(Table 9/Listing 9)" | ✓ | 论文 txt:2523 确写 `G ET P LAN (Table 9)`，实际 prompt 是 Listing 9 (txt:2577/2579) | 文档并列两者，属实且比论文更准 |
| 3-4 | §3.2 | "§3.2 正文只笼统描述行为，没有点名这三个 prompt" | ✓ | txt:735-757、777-783 无 prompt 名 | |
| 3-5 | §3.2 | "abstraction-specificity interleaving"，行 782 | ✓ | txt:782 逐字 | |
| 3-6 | §3.2 | episodic 优先时"同样流程但返回 provenance-linked 情景节点"，行 782-784 | ◐ | 完整句实际在 txt:**732-734**（双栏交错）；782-783 只有前半句 `When episodic memory is prioritized,` | |
| 3-7 | §3.3 | "Appendix C.3（行 2524-2538）+ Table 14 伪代码给出的算法" | ◐ | C.3 算法正文实为 txt:2520-2542；**第 1 步（初始化 C0）来自主文 §3.2 txt:735-739，不在 C.3 内** | 归因不全 |
| 3-8 | §3.3-1 | 初始化：Q→q，对**全部**低层节点打分取 C0 | ✓ | txt:735-739 `Retrieval begins by encoding Q into an embedding q and scoring it against all low-level nodes` | |
| 3-9 | §3.3-2 | 两通道并集，按预算 K RerankPrune（主要 relevance，可选 importance/recency），行 2530-2531 | ✓ | txt:2526-2531 逐字 | |
| 3-10 | §3.3-2 | 高层节点全程只当路由信号，不进候选集，行 2531-2532 | ✓ | txt:2531-2532；主文 txt:753 同 | |
| 3-11 | §3.3-3 | MULTI HOP CTRL 输出严格 JSON `{"enough","top_node_ids"}`（Listing 10） | ✓ | txt:2533-2535；Listing 10 @2639，prompt body 2645-2652 | |
| 3-12 | §3.3-3 | focus set 受 `n_facts_new_query` 上限约束 | ✓ | txt:2650 `top_node_ids length <= {n_facts_new_query}` | **是论文自己的模板变量，不是代码泄漏**，文档合规 |
| 3-13 | §3.3-4 | "LLM 改写 vs 简单拼接，默认拼接（行 2536-2538）" | ◐ | 实际 txt:**2538-2540** | |
| 3-14 | §3.3-5 | "循环直到足够或 T_max（行 2538-2539）" | ◐ | 实际 txt:**2541**；主文 txt:755-757 已有同义句 | |
| 3-15 | §3.3 | "论文把多跳当作 Retrieval Module 的**默认设计**" | ✓ | 主文 txt:755-757 `This multi-hop retrieval process iterates until sufficient evidence is accumulated or a maximum hop limit is reached` + C.3 txt:2520/2541 | 主文就写死了，不只附录 |
| 3-16 | §3.3 | Table 14 里 `F←TaskAdapter(Q)` 含 {E,S,P}，`ExpandLowLevel` 并列 G_S/G_P | ✓ | txt:2679+2683、2691 | |
| 3-17 | §3.3 | F.2 中 T_max 2→4，EM/F1 66.00/74.73→69.00/78.11，行 3879 | ✓ | txt:3878-3879 逐字 | |
| 3-18 | §3.3 | 受 HippoRAG2 启发（recognition/expansion 分离），行 3867 | ✓ | txt:3867-3868 逐字 | |
| 3-19 | §3.3 | Appendix F.2 标题行 3866 | ✓ | txt:3866 | |
| 3-20 | §3.3 | （文档把多跳算法整体归给附录 C.3 + Table 14） | ◐ | 主文 §3.2 txt:750-757 本身已完整写出两通道 + 只留低层节点 + rerank/prune + 迭代到 T_max | 归因不全，不影响结论 |
| 3-21 | §3.4 | Reasoning 是 "test-time running module"，行 768 | ✓ | txt:768 逐字 | |
| 3-22 | §3.4 | Appendix C.4 行 2660-2766，Listing 11-13 | ✓ | C.4 标题 2660；Listing 11/12/13 = 2706/2719/2742；C.5 起于 2767 | |
| 3-23 | §3.4 | Reason_Episodic 的说明"行 2672-2678" | ◐ | 实际 txt:**2665-2669**；2672-2678 落在 Table 14 伪代码区 | 内容属实 |
| 3-24 | §3.4 | Reason_Semantic "尽量用原话，不要换近义词"（Listing 12） | ✓ | txt:2725-2726 逐字 | |
| 3-25 | §3.4 | Reason_Procedural "整合成功和失败经验""连贯、可执行"（行 2679-2683） | ◐ | 实际 txt:**2704-2705** (`both successful and failed memory` / `coherent and actionable guidance`)；2679-2683 是伪代码 | 内容属实 |
| 3-26 | §3.4 | 去 reasoning"准确率几乎不掉，token 涨 1-2 个数量级"（LME 362.58→9478.59） | ◐ | Table 6 txt:1294-1302：Acc 75.1→**72.4**（-2.7pt），TokAvg 362.58→9478.59（**26×** ≈ 1.4 个数量级） | 数字全对，"几乎不掉"略美化，"1-2 个数量级"上界偏高 |
| 3-27 | §3.5 | 四个通用 API create/retrieve/update/delete | ✓ | txt:801-807；Table 13 txt:2126-2143 | |
| 3-28 | §3.5 | update：语义"检测并缓解矛盾"、程序"优化工作流效率" | ✓ | txt:2138-2139 逐字 | |
| 3-29 | §3.5 | delete："衰减低效用节点，同时压缩旧的情景节点以节省空间" | ✓ | txt:2142-2143 逐字 | |
| 3-30 | §3.5 | "主论文主要评测 create 和 retrieve，update/delete 放 C.5"，行 815-817 | ✓ | txt:815-817 逐字 | |
| 4-1 | §4 | Figure 2 = 黑盒三模块；Figure 4 = 图内四操作 | ✓ | 图注 txt:126、720 | |
| 4-2 | §4 | 三模块+三图全在 PlugMem 侧，base agent 只产交互/消费 token | ✓ | txt:172-180、126、768-773 | |
| 4-3 | §4 | mermaid 里 `Intent —solves→ Prescription` | ◐ | 同 2-21 | |

#### §5 / §6 空白点与表述问题（否定式断言，逐条实际证伪）

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| 5-1 | §5 | RerankPrune 没给闭式公式/权重 | ✓ | txt:2530-2531 只有 `a value function (primarily relevance, optionally combined with metadata such as importance/recency)`，全文无公式 | |
| 5-2 | §5 | "importance 全文只在 §3.2(754-755) 和 C.3(2531) 实质出现，从未被定义" | ✓ | `grep -i importance` 全文 4 命中：**755 / 1798 / 2531 / 3387**；1798 与 3387 是"重要性"的日常用法（"showing the importance of episodic…"），非信号定义 | 断言成立 |
| 5-3 | §5 | θ_equal 无取值；C.5 的 τ∈{0.6,0.7} 是另一个操作的阈值 | ✓ | txt:2430 出现 θequal 但无数字；τ∈{0.6,0.7} 在 txt:2830，属 C.5 的 update/merge | |
| 5-4 | §5 | ToEpisodic 具体规则没写 | ✓ | txt:2696 + 2702 只有 `R ← ToEpisodic(C, GE )` 与注释 `{ map via provenance }`；主文只有 txt:732-734 一句 | |
| 5-5 | §5 | E.1 只笼统说 structuring+retrieval 用 Qwen2.5-32B | ✓ | txt:3310-3311 `we adopt Qwen2.5-32B-Instruct for the inference of structuring and retrieval modules, and Qwen2.5-72B-Instruct for the reasoning module` | |
| 5-6 | §5 / §6a | "C.5 全文（2767-2867）只有 update 消融，**没有任何独立 delete/decay 实验**" | ✓ | 通读 txt:2767-2866：Setup / 阈值 τ∈{0.6,0.7} / compactness / candidate controllability 全部是 update-merge；D 节起于 2868 | 已实际通读全段证伪失败 = 属实 |
| 5-6b | §5 | （细微保留） | ◐ | C.5 的 merge 决策本身包含 deactivate（软删除，txt:2781-2782、2792），可视为 delete 被**间接**评测 | 文档未给这个限定 |
| 5-7 | §5 | Figure 2/3/4 图片没被读到 | ✓ | txt 只含图注 126/544/720 | |
| 5-8 | §5 | "6 行代码接入"是仓库 README 的表述不是论文的 | ✓ | `README.md:45` `Enhance your agent with 6 lines of code`；论文 grep 无 | |
| 5-9 | §5 / §6c | Appendix F 与 abstract "unchanged" 的关系论文没划界 | ✓ | txt:3731 章标题 `F. Task Adaptation via Integrating Task-Specific Heuristics on Top of PlugMem`；abstract txt:48-49 | |
| 6b | §6b | importance 被反复提及但从未定义 | ✓ | 同 5-2 | |
| 6c | §6c | Table 3/4/5 底座不同：LME=Q32+Q72，HotpotQA=Q32，WebArena=Q32+4o | ✓ | Table 3 txt:1057-1058 (`NVE` / `Q32 + Q72` / 75.1)；Table 4 txt:1145+1161 (`NVE` / `Q32` / 61.4 74.1)；Table 5 txt:1107-1109 (`NVE` / `Q32+4o`) | 三处表头逐个核对 |
| 6c-2 | §6c | Appendix F 整章在讲叠加任务特定改动 | ✓ | txt:3736-3746（LME 换抽取 prompt + RMM 反思式更新）；txt:3875-3879（HotpotQA 调 T_max） | |
| 6d | §6d | Episodic 映射细节压缩成伪代码一行 | ✓ | 同 5-4 | |
| 6e | §6e | Return 评委易被误读为顺带产出；Get_Return 与 Get_Procedural 分列 | ✓ | txt:728-730 紧接抽取句；Listing 3 (2236/2238) vs Listing 6 (2437/2439) | |

**文档未指出、但本次发现的论文内部矛盾（供参考，不计入判定）**
- C.3 结尾 txt:2542 写 `The overall control flow is summarized in **Listing 14**`，但 Listing 14（txt:2784）是 C.5 的 `Merge_Semantic` prompt；真正的伪代码是 **Table 14**（txt:2674）。论文自己的交叉引用错了。
- C.2 内三处把 Listing 写成 Table：txt:2424 `the prompt in Table 6`、txt:2426 `(Table 3)`、txt:2430 `(Table 7)`。
- Listing 8 (Get_Mode, txt:2560) 明确要求 `decide which **only one** memory type needed`，与 C.3 的 `memory type(**s**)`（txt:2522）和 Table 14 的 `F ⊆ {E, S, P}`（txt:2683）不自洽——到底能不能同时选多种类型，论文自相矛盾。

### 2.2 `code-architecture.md`

#### 前言（两套实现的定位）

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| C-1 | 前言 | "克隆时 HEAD=`3b2ce75`" | ✓ | `git rev-parse --short HEAD` = `3b2ce75` | |
| C-2 | 前言 | "三个基准（LongMemEval / HotpotQA / WebArena）的官方复现脚本**全部 import 这一套**（`src/memory_retrieving/…`）" | ✗ | `src/eval/longmemeval/eval_longmemeval_all.py:14` 与 `src/eval/webarena/plugmem_agent.py:9` 都是**无条件** `from plugmem_client import PlugMemClient as MemoryGraph`（HTTP 打向 `plugmem/` FastAPI 服务）；只有 `src/eval/hotpotqa/eval_qa_all.py:25-28` 才在 `PLUGMEM_API_URL` 未设时回退到 `from memory_retrieving.memory_graph import MemoryGraph`。git 提交 `95c2a8c`(2026-05-26) 标题即 `feat(integration): switch WebArena and LongMemEval scripts to PlugMemClient` | **本次最严重的事实错误**。仍从 `src/` 来的只有 `memory_structuring.memory`(:13) 和 `memory_retrieving.value_longmemeval`(:15) |
| C-3 | 前言 | "`src/` … 是论文数字的直接来源" | ◐ | 结构化与 value function 确实仍出自 `src/`；但当前 HEAD 上 `MemoryGraph` 已换成服务客户端，无法从静态代码断定"当前脚本状态 = 产出论文数字时的状态" | 该判断需要指定 commit 才成立 |
| C-4 | 前言 | "`plugmem/` … 是论文之外的东西（README 显示这部分 2026-05 才上，晚于 2026-04 ICML 接收）" | ✗ | `git log --reverse -- plugmem/` 首提交 `e064baf` **2026-03-19** `migrate to chromdb for save/load mem graphs`；REST API 层 `c1c19e1` 2026-04-14。README 的 `[2026-05]` 指的是 **plugin 发布**（README:29-31），不是整个包 | 文档 §5 自认"没跑 git log"，这条错误正源于此 |
| C-5 | 前言 | promotion.py 那套编码助手晋升机制是论文之外的 | ✓ | `plugmem/inference/promotion.py` 首提交 `26bca52` 2026-05-03；论文 grep `promotion|promote` **零命中** | |
| C-6 | 前言 | "核心算法…和 `src/` 高度一致" | ✓ | `diff src/memory_retrieving/value_longmemeval.py plugmem/core/value_functions.py` 仅空白/import 差异；分段阈值 0.75 两边一致（`src/memory_structuring/memory.py:48` / `plugmem/core/memory.py:81`） | |

#### §1–§2 写入侧

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| C-7 | §1 | `memory_graph.py:363` = `insert` | ✓ | 逐行确认 `def insert(self, memory: Memory) -> None:` | |
| C-8 | §1 | `memory_graph.py:988` = `retrieve_memory` | ✓ | 逐行确认 | |
| C-9 | §1 | "一轮候选合并排序，取 top-K 拼成 prompt 返回给调用方" | ✓ | 988-1108 全程无循环 | |
| C-10 | §2.1 | append 累积 → `close()` → `MemoryGraph.insert()`，不是逐步写图 | ✓ | `memory.py:59` / `memory.py:104` / `memory_graph.py:363` | |
| C-11 | §2.1 | WebArena `plugmem_agent.py:431` close、`:436` insert | ✓ | 逐行确认（replay 路径另有 550/555） | |
| C-12 | §2.2 | append 每步连调 3 次 LLM：`get_subgoal`(60) / `get_reward`(68) / `get_state`(95) | ✓ | 三处逐行确认 | |
| C-13 | §2.2 | `get_reward` 是自然语言评价"不是打分" | ✓ | `plugmem/prompts/structuring.py:40` `GetRewardPrompt`，输出 `[Natural-language reward statement…]`；论文 Listing 4 txt:2316 同 | |
| C-14 | §2.2 | 分段规则写死 `if similarity_subgoal < 0.75:`（`memory.py:81`） | ✓ | 逐行确认，行号精确；`src/memory_structuring/memory.py:48` 同值 | |
| C-15 | §2.2 | `close()`：每步 `get_semantic()`(115)、每段 `get_procedural()`(123) | ✓ | 逐行确认，`get_semantic` 在 `for i, step` 内循环，`get_procedural` 在 `for j, trajectory` 外层 | |
| C-16 | §2.2 | `Memory.close()` 范围 `memory.py:104-134` | ✓ | 文件共 134 行 | |
| C-17 | §2.2 | `GetSemanticPrompt` 要求消解指代 / 合并去重 / **单条最多 4 句** | ✓ | `structuring.py:124`（Resolving Vague References）、`:122`（Deduplication）、`:136` `AT MOST 4 sentences total`；论文 Listing 5 txt:2361 逐字相同 | |
| C-18 | §2.2 / §6.2 | `get_procedural()` 把 `_return` **硬编码 0.0（第 124 行）** | ✓ | `plugmem/inference/structuring.py:124` `_return = 0.0`，行号逐字命中 | |
| C-19 | §2.2 / §6.2 | `get_return()`(96-109) 存在但 `close()` 全程未调用，是死代码 | ✓ | 全仓 grep `get_return`：仅定义(96/100)、`__init__` 导出、registry 注册；**更硬的证据**：`src/memory_structuring/structuring_inference.py:138` 把 `# _return = get_return(...)` **直接注释掉**，139 行写死 `_return = 0.0` | 文档结论成立且可加强 |
| C-20 | §2.3 | 5 类节点定义在 `graph_node.py:13-226` | ✓ | 13/57/111/142/188 五个 class，文件 226 行 | |
| C-21 | §2.3 | tag 按字符串精确匹配去重（`memory_graph.py:442-450`） | ✓ | `tag_node = self.tag2node.get(tag_str)` @442，新建分支 444-451 | |
| C-22 | §2.3 / §6.3 | **意图去重是精确字符串匹配**：`self.subgoal2node.get(subgoal_str)` @515；合并 LLM `get_new_subgoal` @519 | ✓ | 逐行确认；`insert()` 全段 363-593 无任何 cosine 调用 | 头号结论之一，成立 |
| C-23 | §2.3 | 真正做向量匹配的 `retrieve_subgoal_nodes()`(892) 只在检索时用 | ✓ | 逐行确认，唯一调用点在 `retrieve_procedural_nodes:923` | |
| C-24 | §2.4 | 每个 graph_id 开 5 个 collection（`chroma.py:19,73-83`） | ◐ | 内容 ✓：`NODE_TYPES` 5 项在 `chroma.py:**17**`（19 是空行），`create_graph` 在 **72-81** | 小漂移 |
| C-25 | §2.4 | 检索时全量 load 进内存暴力遍历 cosine，不用 Chroma HNSW（`memory_graph.py:694-701`） | ◐ | 结论 ✓；循环实际在 **688-696**（694 是 embedding 懒加载那一行，不是循环头） | |
| C-26 | §2.4 | `src/` 那套是纯文件 JSON，README 的 `mkdir` 给它用 | ✓ | `README.md:133` `mkdir -p "$DIR_PATH/episodic_memory" \` | |
| C-27 | §2.5 | 默认 NV-Embed-v2 HTTP（`embedding.py:34-61`），cosine `get_similarity()`(`embedding.py:167`) | ✓ | class @34、`model: str = "nvidia/NV-Embed-v2"` @45、`def get_similarity` @**167** 逐字命中 | |

#### §3 检索侧

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| C-28 | §3.2 | `get_mode()` 在 1011-1015、`get_plan()` 在 1019-1022 | ✓ | 逐行确认 | 行号精确 |
| C-29 | §3.2 | 除非调用方强制传 `mode`，否则先调这 2 次 LLM | ✓ | `if mode is None:` @1011；`get_plan` 无条件调用 @1019 | |
| C-30 | §3.3 语义 | Phase 1 硬编码 `sem_node_topk = 5` @686，不受外部 k 影响 | ✓ | 逐行确认 | |
| C-31 | §3.3 语义 | Phase 2 `retrieve_tag_nodes()`@599，1 个标签只取 1 个最相似 TagNode，阈值 0.8 | ✓ | `TagRelevant(k=1, value_threshold=0.8)` @`value_functions.py:29`；默认注入 @`memory_graph.py:132` | |
| C-32 | §3.3 语义 | Phase 3 并集重打分取 top-K，默认 `SemanticRelevant(k=10, value_threshold=0.0)` @`value_functions.py:70-72` | ✓ | 逐字命中 | |
| C-33 | §3.3 语义 | 传了 4 个信号但 `compute_importance/recency/credibility` **全部恒返回 0**，只有 relevance 恒等 | ✓ | `memory_graph.py:767-770` 传参；`value_functions.py:75-88` 四个方法体 | |
| C-34 | §3.3 语义 | "标签投票只影响候选池大小，完全不影响最终排序；最终排序 100% 是 cosine" | ✓ | 并集 @746-749、relevance @762、排序 @786 | 表述精确 |
| C-35 | §3.3 语义 | `ValueBase.evaluate()` 漏加 `v_credibility`（`value_base.py:17-30`，第 30 行只加四项）；`src/memory_retrieving/value_base.py:17-26` 同款 | ✓ | 两处逐行确认（src 版在第 26 行） | 行号精确 |
| C-36 | §3.3 程序 | `retrieve_subgoal_nodes()` 返回 `Optional[SubgoalNode]` 单节点；不够 `SubgoalRelevant.value_threshold=0.1` 直接返回空 | ✓ | 签名 @894、阈值判断 @911、`return []` @935；`value_functions.py:134` | |
| C-37 | §3.3 程序 | 只在这一个 SubgoalNode 挂的 ProceduralNode 里按 cosine 取 top-K | ✓ | `for proc_node in subgoal_node.procedural_nodes:` @939 | |
| C-37b | §3.3 程序 | （文档只说"取 top-K"） | ◐ | 默认 `ProceduralRelevant(k=1)` @`value_functions.py:176` + 注入 @`memory_graph.py:139` → 程序检索**最多只返回 1 条 prescription** | 文档未点破这个量级 |
| C-38 | §3.3 情景 | 调 `retrieve_semantic_nodes_wo_tag()` 跳过标签路由，取前 30（`semantic_nodes[:30]`，`memory_graph.py:855`） | ◐ | 内容 ✓；`semantic_nodes = semantic_nodes[:30]` 实际在 **860**（855 是参数行）。另 `SemanticRelevant4Episodic(k=30)` 已先截过一次，`[:30]` 冗余 | |
| C-39 | §3.3 情景 | 按 session_id 投票，≥3 才搬整段 session；不到 3 就返回该语义节点自己的命题文本 | ✓ | `if value >= 3:` @871；`if sid is None or vote_session.get(sid,0) < 3:` @876-877 | 逐行确认 |
| C-39b | §3.3 情景 | （文档把 episodic 模式描述成只走 `_wo_tag` 一条路） | ◐ | **不完整**：`retrieve_memory` 在 episodic 模式下会先跑 `retrieve_semantic_nodes`(1037-1044) **和** `retrieve_procedural_nodes`(1045-1052)，两者结果只写进 `_audit`(1097-1098) 就被丢弃，然后才第三次调 `retrieve_episodic_nodes`(1058-1063)——三趟检索、两趟白跑。`retrieve_with_trace` 同（1186-1215） | 影响成本估算 |
| C-40 | §3.4 | `MemoryGraph` 全程只跑一轮：没循环、没跳数上限参数 | ✓ | 988-1108 与 1110-1273 均无循环；整个 `plugmem/` 包 grep `multi_hop\|max_hop\|Tmax\|t_max\|max_rounds\|enough` **零命中** | 否定式断言，已实际证伪失败 |
| C-41 | §3.4 | 唯一多跳在 `src/eval/hotpotqa/eval_qa_all.py:122-219`（`multi_hop_retrieval_sem` + `_llm_select_topn`） | ✓ | 函数 122-221 / 63-120 | |
| C-42 | §3.4 | `max_rounds=3`（`eval_qa_all.py:128`） | ✓ | 逐行确认（函数默认值） | |
| C-43 | §3.4 | 把选中候选文本**纯字符串拼接**进新 query，不是 embedding 融合 | ✓ | `query_text = "original question: " + question + "\n" + "\n".join(seed_texts)` @213 | |
| C-44 | §3.4 | 明确只对 `semantic_memory` 生效，procedural/episodic 打日志原样返回（`:155`） | ✓ | 154-166 逐行确认，日志文案逐字一致 | |
| C-45 | §3.4 | LongMemEval(`eval_longmemeval_all.py:100`)、WebArena(`plugmem_agent.py:225`) 只调**一次** `retrieve_memory()` | ✓ | 两处逐行确认 | 行号精确 |
| C-45b | §3.4 | （文档称 HotpotQA 是"唯一真正实现它的"） | ◐ | **更极端**：多跳也是 opt-in——`--n_round_retrieval` 默认 **1**（`eval_qa_all.py:242`），`if n_round_retrieval <= 1:` 走单轮（`:480`）。**默认跑法下三个基准全都不走多跳** | 加强而非推翻 §6.1 |
| C-45c | §3.4 | — | — | 补充：多跳最终返回各轮命中节点的**并集**（216-219），不是论文的每跳 `RerankPrune(C,K)`；且多一个论文没有的 `no_gain` 停止条件（183-185） | 新发现 |
| C-46 | §3.5 | `retrieve_memory()` 只返回渲染好的 `messages`，自己不调 LLM | ✓ | `messages = prompt_template.build_messages(variables)` @1091；`return messages, variables, mode` @1108 | |
| C-47 | §3.5 | 三个基准脚本自己调外部 LLM；`eval_longmemeval_all.py:102` 调 `gpt-4o` | ✓ | `:102` `wrapper_call_model(model_name="gpt-4o", messages=messages)` 逐字；`:116` 第二次 gpt-4o；WebArena `plugmem_agent.py:234` `call_gpt(messages=messages, model_id="gpt-4o")` | |
| C-48 | §3.5 | `retrieve_and_reason()`(1274-1297)，`src/eval/` 下**没有任何** `.retrieve_and_reason(` 调用 | ✓ | 全仓 grep：`src/eval/{hotpotqa,webarena,longmemeval}/plugmem_client.py:386/366/366` 只是**定义**同名 HTTP 方法，无调用点；`README.md:56` 有示例但不是 eval 脚本 | 否定式断言成立 |
| C-49 | §3.6 | `update_semantic_subgraph()`(1348-)、默认 `merge_threshold=0.5`、`merge_semantic()`(1298) 用 LLM 合并并软删（`is_active=False`） | ✓ | 1348 / `merge_threshold: float = 0.5` @1351 / 1298 / 合并决策 1301-1308 | |
| C-50 | §3.6 | 不在 `insert()` 里自动触发；`eval_longmemeval_all.py:91` 由 `--update_merge_first` 控制，默认不开 | ✓ | `insert()` 363-593 无调用；`:91-92` + argparse `action="store_true"` @:20 | |
| C-50b | §3.6 | （文档只举 LongMemEval 一例） | ◐ | HotpotQA 也调：`eval_qa_all.py:381` `mg.update_semantic_subgraph(merge_threshold=sem_merge_threshold, write_to_disk=True)` | |
| C-51 | §4 | "中间所有 LLM 调用（结构化 5 类、检索 2 类）都在记忆系统这一侧" | ◐ | 5 类（subgoal/reward/state/semantic/procedural）+ 2 类（mode/plan）✓；但**写入侧还有第 6 类** `get_new_subgoal`(`memory_graph.py:519`)，更新侧还有 `get_new_semantic`(`:1301`) | "5 类"不完整 |
| C-52 | §4 | HotpotQA 多跳是 eval 脚本外挂的编排逻辑，不属上图任何一侧 | ✓ | `eval_qa_all.py:138-213` for 循环包在 `retrieve_memory` 外 | |

#### §5 我没搞清楚的（本次能结案的都结案）

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| C-53 | §5 | `src/memory_retrieving/memory_graph.py:1444` 的 `max_w` 只在 semantic 分支赋值，却在 procedural 分支(1457) 被引用 → 纯 procedural 模式应抛 `NameError` | ✓ | `elif mode == "semantic_memory":`@1429 内 `max_w = len(str(max(ids)))`@1444；`elif mode == "procedural_memory":`@1451 内引用 `{max_w}`@1457；两者同属 `retrieve_memory`(1364-1486)，同名变量在 1056/1195 属别的函数 | 分析成立 |
| C-54 | §5 | `subgoal2node` 命中率未做统计 | ✓ | 诚实声明，本次也未跑 | |
| C-55 | §5 / §6.7 | gpt-4o 硬编码与论文矛盾"未完全验证，不确定是否有环境变量或 `eval_longmemeval_sota.py` 覆盖" | ◐（可结案） | 硬编码 ✓。`wrapper_call_model`(`src/utils.py:142`) 是 `model_name or os.environ.get("LLM_NAME") or DEFAULT_LLM_NAME` → **显式实参优先，环境变量无法覆盖**。`eval_longmemeval_sota.py` 确实存在，但硬编码 **`gpt-5.4`**(:92,:106)，对应 README `[2026-05]` SOTA，不可能是 Table 3 的脚本 | 该冲突可从"疑似"升为**确定**（限 `eval_longmemeval_all.py`） |
| C-56 | §5 | "`plugmem/` 是否论文接收后新增…README 时间线支持'后加'，但没跑 git log" | ✗ | 见 C-4：首提交 2026-03-19，早于 2026-04 接收；且两个基准脚本现在正是通过 `PlugMemClient` 打向它 | 推断方向错误 |
| C-57 | §5 | promotion 的触发条件未深入验证 | ✓（可结案） | `promotion.py:24` `CandidateKind = Literal["failure_delta","correction"]`；`:31` failure_delta = 工具调用失败后跟进成功；`:32` correction = 用户显式纠正（"don't/stop/actually"）。入口是 API `/extract`(`routes/extract.py:26-32`)，**绕开 `Memory`/5 次结构化 LLM**，产物经 `_insert_structured`(`routes/memories.py:63-145`) 直接入图 | |
| C-58 | §5 | Chroma 是否在别处做 ANN 检索未排查 | ✓（可结案） | `chroma.py` 确有 4 个 ANN 方法 `query_semantic`(411)/`query_tag`(521)/`query_subgoal`(623)/`query_procedural`(750)，全仓 grep **零调用**，是死代码。文档"完全没用 Chroma 自带 HNSW 近邻检索"成立 | |

#### §6 与论文的冲突点

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| C-59 | §6.1 | 多跳落地范围远小于论文描述 | ✓ | 见 C-40~C-45；且默认还是关的（C-45b） | 头号结论成立 |
| C-60 | §6.2 | return score 从未被真正计算 | ✓ | 见 C-18/C-19 | |
| C-61 | §6.3 | intent 去重不是 cosine 是精确字符串 | ✓ | 见 C-22 | |
| C-62 | §6.4 | importance 被算出来又扔掉；三基准用的正是默认 value function | ✓ | 见 C-33/C-34；`value_longmemeval.py` ≡ `value_functions.py`（diff 仅空白） | |
| C-63 | §6.5 | credibility 在论文里零命中；confidence/source/promotion 也是论文外 | ✓ | 论文 `grep -i credib` **0 命中**；`confidence` 4 处全在信息论分析语境(2992/3093/3155/3301)；`promot` 0 命中。代码 `credibility: int = 10` @`graph_node.py:70` | |
| C-63b | §6.5 | （文档提到 `credibility_decay` 参数） | ◐ | 该参数默认 **0**（`memory_graph.py:1356`，`if credibility_decay != 0:` @1374），衰减默认是 no-op | |
| C-64 | §6.6 | `plugmem/` 规避了 `max_w` 的 NameError（"约 1080 行附近"） | ✓ | `plugmem/core/memory_graph.py:1070-1075` 的 `procedural_memory_str` 拼接不依赖任何跨分支变量 | "约…附近"的表述容得下 1070-1075 |
| C-65 | §6.7 | 产出主结果的脚本模型配置疑似与论文表头不一致 | ✓（可加强） | 见 C-55。**补充限定**：论文 §4.2 txt:823-824 本身就写 `Qwen2.5-32B/72B-Instruct … and GPT-4o`，所以冲突只落在 **LongMemEval 这一行**（E.1 txt:3311-3312 明确 reasoning=Q72、base agent=Q72）；WebArena 那行（Table 5 = Q32+4o）与代码的 gpt-4o **一致，无冲突** | 文档未做这个区分 |

**文档未提到、本次新发现的代码问题（不计入判定）**
- `memory_graph.py:519-524`：intent 合并分支调 `get_new_subgoal()` 拿到 `merged_str` 后，**只刷新了 `embedding` 和 `time`，没有把 `merged_str` 写回 `subgoal_node.subgoal`**；565/576/583 持久化的仍是旧字符串 → 节点文本与向量脱节。
- `plugmem/api/routes/memories.py:136-143` 暴露 `tag/semantic/subgoal/procedural_equal_threshold` 四个"插入去重阈值"，但 `insert()` 从不读这些 value function（全文件只有 `semantic_equal` 在 `update_semantic_subgraph:1432/1435` 用过）→ 死旋钮，**反过来加强了 §6.3**。
- 论文 C.2 的 sibling 边在代码里**确有实现**（`graph_node.py:81` `bro_semantic_nodes`，持久化 `memory_graph.py:496` `bro_semantic_ids`），文档全篇未提。
- `retrieve_subgoal_nodes:913` `best_node.importance += 1` —— 检索会写图状态（副作用）。
- `retrieve_semantic_nodes_wo_tag`（episodic 模式用的那条路）**不检查 `is_active`**（对比 `retrieve_semantic_nodes:689-690`），软删除的节点仍会在 episodic 模式下被检索出来。
- `src/memory_structuring/memory.py:100-148` 的 `Memory_LongMemEval` 完全跳过 subgoal/reward/state 标准化（写死空串）、**不产生任何程序记忆**，仅供 `eval_longmemeval_sota.py` 使用。
- Table 13 承诺的 delete（"衰减低效用节点 + **压缩旧的情景节点**"）在代码里只有半个：`credibility_decay`（默认 0）+ 软删；grep `compress|prune|evict` 全仓**没有任何 episodic 压缩实现**，唯一的 delete API 是整图删除 `routes/graphs.py:53 delete_graph`。

---

## 3. 步骤清单 — 论文侧

> 全部步骤都在 PlugMem 边界**内**，除非注明。`llm` 一栏是每次触发的调用次数。

### 写入侧（Structuring Module = `create`）

| # | name（论文自己的叫法） | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| W1 | Episodic Formalization（§3.1.1 Standardize） | 每 turn（一次 `memory.create(trajectory)` 内对每个 (o_t,a_t)） | `(o_t,a_t)` + 任务指令/初始目标 G → 五元组 `e_t=(o_t,s_t,a_t,r_t,g_t)` | **3**：Get_State（滚动状态摘要）/ Get_Subgoal（子目标）/ Get_Reward（动作有效性标注） | G_E | `P-INTAKE`（o/a 原样）+ `P-META`（s/g/r 三个 LLM 标注字段） |
| W2 | Aggregating into M_epi（§3.1.1） | 每轨迹一次 | `[e_t]` → `M_epi` | no | G_E | `P-PERSIST` |
| W3 | Extract Knowledge — Semantic（§3.1.2 / C.2） | 每个 episodic 单元 e_t | `e_t` → ≤ N_max=10 组 `(proposition p, concepts T)` | **1** Get_Semantic（prompt 内含指代消解、命题去重、≤4 句长度控制） | — | `P-EXTRACT`（内嵌 `P-REWRITE` 指代消解 + `P-DEDUP` + `P-META` 概念标签） |
| W4 | Cache dense embeddings（§3.1.2 / C.2） | 每个新节点 | 命题/概念文本 → 向量 | no | G_S | `P-EMBED` |
| W5 | Materialize semantic edges（C.2） | 每条命题 | → membership `p→c`、provenance `p→e_t`、同源命题间 sibling | no | G_S ↔ G_E | `P-LINK` |
| W6 | Trajectory segmentation（§3.1.2 / C.2） | 每条完整 `M_epi` 一次 | 相邻 `g_t` embedding 余弦 < 阈值处切段 → 子轨迹 `M_epi^(i)` | no（复用 W1 已产出的 subgoal） | — | `P-EMBED` > `P-AGGREGATE`（以边界切分把连续步聚成 sub-trajectory 单元） |
| W7 | Extract Knowledge — Procedural（§3.1.2 / C.2） | 每个轨迹段 | 线性化的 state–action–reward 过程描述 → `(intent u, prescription π)` | **1** Get_Procedural | — | `P-EXTRACT` |
| W8 | Return scoring / quality-aware reuse（§3.1.2 / C.2） | 每条 prescription | `(intent, segment trace)` → `ρ ∈ [1,10]` | **1** Get_Return（独立评委，txt:2426-2427） | G_P 节点元数据 | `P-META` |
| W9 | Intent deduplication（C.2） | 每个新 intent | `φ(u)` vs 已有 intent 节点 cosine → 超 `θ_equal` 则合并改写并刷新 embedding，否则新建 | **0 或 1** Get_New_Subgoal（仅超阈值时） | G_P | `P-EMBED` > `P-DEDUP`（+ `~P-REWRITE` 合并改写） |
| W10 | Materialize procedural edges（C.2） | 每条 prescription | → hierarchical `u→π`（单向 child list）、provenance `π→e_t` for all `e_t ∈ M_epi^(i)` | no | G_P ↔ G_E | `P-LINK` |
| W11 | `update`（§3.4 / Table 13 / C.5） | 手动 `memory.update(feedback)`（主论文主结果未评测，见 txt:815-817） | 语义节点 + 共享 tag 的邻居 → 合并节点 + deactivate 决策 | **1** Merge_Semantic | G_S | `~P-DEDUP` + `~P-CONFLICT`（"检测并缓解矛盾" + 软删版本化）+ `~P-AGGREGATE` |
| W12 | `delete`（§3.4 / Table 13） | 手动 `memory.delete(criteria)`（**只有描述，无实验，无算法**） | → 衰减低效用节点 + 压缩旧 episodic | 未交代 | G_S/G_P/G_E | `~P-EVICT` |

### 检索侧（Retrieval Module + Reasoning Module = `retrieve`）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| R1 | GET MODE（§3.2 / C.3 Listing 8） | 每 query 1 次 | `Q` + task description → episodic / semantic / procedural（Listing 8 txt:2560 要求"only one"） | **1** | — | `P-QUERYPARSE` |
| R2 | Init candidates（主文 txt:735-739 / Table 14 `InitLowLevel`+`TopK`） | 每 query 1 次 | `Q` → `q`，对**全部**低层节点（命题/处方）打分 → `C_0` | no | G_S / G_P（读） | `P-EMBED` + `P-DENSE` |
| R3 | Stop / MULTI HOP CTRL（C.3 Listing 10） | 每跳 1 次 | `(Q, 可用节点 ID, 已检索事实文本)` → 严格 JSON `{"enough", "top_node_ids"}`（长度 ≤ `n_facts_new_query`） | **1/跳** | — | `P-TOOLLOOP`（多跳控制） |
| R4 | GET PLAN / Abstract（C.3 Listing 9） | 每跳 1 次 | `(Q, C_t)` → 抽象查询 `q_t^a`（G_S 为概念集，G_P 为意图集） | **1/跳** | — | `P-QUERYPARSE` |
| R5 | Embedding channel（C.3 txt:2527-2528） | 每跳 | `Q_t` → 高分低层节点 | no | G_S / G_P | `P-DENSE` |
| R6 | Linking channel（C.3 txt:2528-2530） | 每跳 | `q_t^a` → 匹配高层节点 → 沿 membership/hierarchical 边激活相邻低层节点 | no | G_S / G_P | `P-GRAPHEXPAND` |
| R7 | Merge（union）（C.3 txt:2530） | 每跳 | 两路候选 → 并集 | no | — | `P-FUSE` |
| R8 | RerankPrune(C,K)（§3.2 txt:754-755 / C.3 txt:2530-2531） | 每跳，`|C_t|` 超预算时 | 候选 → value function（relevance 为主，可选 importance/recency）打分剪到 top-K；高层节点从不进 `C_t` | no | — | `P-RERANK` |
| R9 | Next-hop query 构造（C.3 txt:2538-2540） | 每跳（未停止时） | `Q_t` + focus set → `Q_{t+1}`；**默认简单拼接**，可选 LLM 改写 | **0**（默认）/ 1（可选改写） | — | `P-TOOLLOOP` 循环体（`~P-REWRITE` 为可选变体） |
| R10 | ToEpisodic（Table 14 txt:2696+2702 / §3.2 txt:732-734） | 当 `E ∈ F` | 命中的命题/处方 → 沿 provenance 边映射回情景节点 | no | G_E | `P-GRAPHEXPAND`（provenance 反向跳） |
| R11 | Reasoning Module（§3.3 / C.4 Listing 11-13） | 每 query 1 次 | 检索到的多条知识 → 一段紧凑、任务对齐的可执行指导（"refined memory tokens"）；按类型走 Reason_Episodic / Reason_Semantic / Reason_Procedural | **1** | — | `P-AGGREGATE` + `P-ASSEMBLE` |
| R12 | base agent 决策 | 每 query | refined memory tokens → 答案 / 下一步动作 | 1 | — | `P-GENERATE`（**边界外**） |

### 论文侧系统边界

Structuring / Retrieval / **Reasoning** 三模块 + G_E/G_S/G_P 三张图**全部在 PlugMem 内**（§3.3 明确把 Reasoning 列为第三个核心组件，txt:444-451、768-773）。base agent 只负责产生原始交互 τ 和消费 refined memory tokens（R12）。评测脚本侧论文未讨论。

---

## 4. 步骤清单 — 代码侧

> 主线以 `plugmem/`（当前 HEAD 上两个基准脚本实际打向的服务包）为准；与 `src/` 有差异处标注。

### 写入侧

| # | name（代码里的叫法） | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| c-W1 | `Memory.append(action_t0, observation_t1)`（`core/memory.py:59`） | 每 turn，由调用方主动调 | `(action, observation)` → `trajectory` 里一条 `{subgoal,state,observation,action,reward,time}` | **3**：`get_subgoal`(:60) / `get_reward`(:68，自然语言评价而非分数) / `get_state`(:95) | 进程内 list（尚未落盘） | `P-INTAKE` + `P-META` |
| c-W2 | 轨迹分段（内联在 `append`，`memory.py:76-83`） | 每 turn 判一次 | 相邻 subgoal 向量 cosine **< 0.75**（硬编码 `:81`）就切段 | no（embedder 调 2 次） | 进程内 | `P-EMBED` + `P-AGGREGATE` |
| c-W3 | `Memory.close()` → `get_semantic()`（`memory.py:115`） | `close()` 时对**每一步**跑一次 | step → `[{semantic_memory, tags}]`（prompt 要求指代消解、去重、≤4 句、≤10 条） | **1/步** | 进程内 | `P-EXTRACT`（内嵌 `P-REWRITE`/`P-DEDUP`/`P-META`） |
| c-W4 | 命题与 tag 编码（`memory.py:118-121`） | 每条命题 | 文本 → 向量 | no | 进程内 | `P-EMBED` |
| c-W5 | `Memory.close()` → `get_procedural()`（`memory.py:123`） | `close()` 时对**每一段**跑一次 | 段的 `trajectory_str` → `(procedural_memory, goal, _return)` | **1/段** | 进程内 | `P-EXTRACT` |
| c-W5x | ~~Return scoring~~ | **从不触发** | — | `get_return()`(`inference/structuring.py:96`) 存在但零调用；`_return` 写死 `0.0`(`:124`)；`src` 版 `:138` 直接注释掉 | — | 论文的 `P-META`（质量分）**在代码里缺失** |
| c-W6 | `MemoryGraph.insert(memory)`（`core/memory_graph.py:363`） | 每条轨迹一次（`close()` 之后） | `Memory` → 5 类节点：Episodic / Semantic / Tag / Procedural / Subgoal | **0 或 N**：仅当 subgoal 字符串精确重复时调 `get_new_subgoal`(:519) | ChromaDB 5 个 collection | `P-DEDUP`（**字符串级**，`tag2node.get`:442、`subgoal2node.get`:515）+ `P-LINK`（sem↔tag 双向、sem→epis、proc→subgoal child list、proc→epis、sibling `bro_semantic`）+ `P-PERSIST` |
| c-W7 | `update_semantic_subgraph()`（`memory_graph.py:1348`） | **手动/CLI 开关**：LongMemEval `--update_merge_first` 默认关(`eval_longmemeval_all.py:91`)；HotpotQA `eval_qa_all.py:381` | 按 tag 找候选 → cosine → 超 `merge_threshold=0.5` → `merge_semantic()` 建合并节点 + 软删原节点(`is_active=False`) | **1/对** `get_new_semantic`(:1301) | ChromaDB | `~P-DEDUP` + `~P-CONFLICT` + `~P-EVICT`（`credibility_decay` 默认 **0**，衰减实为 no-op） |
| c-W8 | （论文外）`extract_coding_memories()`（`inference/promotion.py:63`，API `/extract`） | 编码 agent hook 检出 `failure_delta` / `correction` 候选时 | 候选片段 → 0~N 条带 `source`/`confidence` 的语义/程序节点，经 `_insert_structured`(`routes/memories.py:63`) **绕开 c-W1~c-W5 直接入图** | **1** | ChromaDB | `P-EXTRACT` + `P-META` + `P-PERSIST` |

### 检索侧

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| c-R1 | `MemoryGraph.retrieve_memory(...)`（`memory_graph.py:988`） | 调用方每次决策/提问主动调（LME 每题 1 次 `:100`；WebArena 每步 1 次 `plugmem_agent.py:225`） | 入口 | — | — | — |
| c-R2 | `get_mode()`（`:1011-1015`） | 每次，除非调用方传 `mode` | → `episodic_memory` / `semantic_memory` / `procedural_memory` **三选一**（`_normalize_mode`:56 兜底 semantic） | **1** | — | `P-QUERYPARSE` |
| c-R3 | `get_plan()`（`:1019-1022`） | 每次，**无条件** | → `next_subgoal` + `query_tags` | **1** | — | `P-QUERYPARSE` |
| c-R4 | `retrieve_semantic_nodes()` Phase 1（`:663`, `:686-699`） | semantic 或 episodic 模式 | query 向量 vs **全部 active 语义节点**暴力 cosine → top-**5**（硬编码 `sem_node_topk=5`） | no | 内存列表（Chroma 只做持久化，4 个 ANN 方法零调用） | `P-EMBED` + `P-DENSE` |
| c-R5 | Phase 2 标签路由（`:714-740`，`retrieve_tag_nodes`:599） | 同上 | 每个 `query_tag` 取 **1** 个最相似 TagNode（阈值 0.8）→ 其下全部语义节点进候选 + 记 `tag_vote` | no | — | `P-GRAPHEXPAND` |
| c-R6 | Phase 3 并集重排（`:745-797`） | 同上 | 两路取并集 → `value_func.evaluate(Relevance,Recency,Importance,Credibility)` → 排序取 top-**10** | no | — | `P-FUSE` + `P-RERANK`（**退化为纯 cosine**：importance/recency/credibility 恒 0，`value_base.py:30` 连 credibility 都漏加） |
| c-R7 | `retrieve_procedural_nodes()`（`:916`） | procedural 或 episodic 模式 | `retrieve_subgoal_nodes()`(`:892`) 与**全部** SubgoalNode 算 cosine 取**唯一 1 个**（阈值 0.1，不够返回 `[]`） | no | — | `P-DENSE`（在高层节点上） |
| c-R8 | 子树内排序（`:939-972`） | 同上 | 只在该 SubgoalNode 的 child prescription 列表里按 cosine 取 top-k（**默认 k=1**） | no | — | `P-GRAPHEXPAND` + `P-RERANK` |
| c-R9 | `retrieve_episodic_nodes()`（`:847`） | episodic 模式（此前 c-R4~c-R8 已白跑并丢弃，见 `:1037-1052`） | `retrieve_semantic_nodes_wo_tag()`(`:809`) 跳过标签路由纯全局 cosine 取前 30(`:860`) | no | — | `P-DENSE` |
| c-R10 | session 投票（`:862-878`） | 同上 | 按 `session_id` 计票：**≥3** → `get_session_memory()` 搬出整段原始情景；**<3** → 直接返回该语义节点的**命题文本**（不溯源） | no | G_E | `P-GRAPHEXPAND`（session/provenance）+ `P-AGGREGATE` |
| c-R11 | 套 reasoning prompt 模板（`:1079-1092`，`prompts/reasoning.py`） | 每次 | 记忆文本 → 渲染好的 `messages` 并 **return**（`:1108`），自己**不调 LLM** | no | — | `P-ASSEMBLE` ← **记忆系统在此终止** |
| c-R12 | 调用方做 reasoning 压缩 | 每次 | `messages` → 压缩后的信息 | **1**（LME `eval_longmemeval_all.py:102` `gpt-4o`；WebArena `plugmem_agent.py:234` `gpt-4o`） | — | `P-AGGREGATE`（**边界外**；`retrieve_and_reason()`:1274 提供了收回来的选项，但 eval 脚本零调用） |
| c-R13 | 调用方出最终答案/动作 | 每次 | 信息 + 问题 → answer / action | **1**（LME `:116` `gpt-4o`） | — | `P-GENERATE`（**边界外**） |
| c-R14 | `multi_hop_retrieval_sem()`（`src/eval/hotpotqa/eval_qa_all.py:122`） | **仅 HotpotQA 且 `--n_round_retrieval ≥ 2`；默认值 1(`:242`)，默认不触发** | for r in 1..≤3(`:138`)：重调 `retrieve_memory` → `_llm_select_topn`(`:63`) 判 `{enough, top_node_ids}` → 新 query = 纯字符串拼接(`:213`)；停止条件 enough / `no_gain`(`:183`) / 无候选 / 轮数上限；最终返回各轮命中的**并集**(`:216-219`) | **1/轮**（判定器） | — | `P-TOOLLOOP`（**在评测脚本侧，不是记忆系统能力**）；procedural/episodic 模式直接跳过(`:154-166`) |

### 代码侧系统边界

- **记忆系统本体** = `plugmem/core` + `plugmem/inference` + `plugmem/storage`（对应 `src/memory_structuring` + `src/memory_retrieving`）：从 c-W1 到 c-R11，即"吃原始 (observation, action) 步骤，吐渲染好的 `messages`"。写入侧 5 类 + 插入侧 1 类 + 检索侧 2 类 + 更新侧 1 类 LLM 调用都在这一侧。
- **调用方 / agent 一侧**：c-R12（reasoning 压缩——**论文把它算作 PlugMem 的第三个模块，代码里却落在这一侧**）、c-R13（最终生成）。
- **评测脚本一侧（既不属记忆系统也不属 agent）**：c-R14 的多跳编排、`--update_merge_first` 这类维护开关的调度。
- **论文之外的第四条通路**：c-W8 的编码助手记忆晋升（`/extract` + `_insert_structured`），完全绕开结构化链路。

---

## 5. 论文 ↔ 代码分歧

| # | 分歧 | 类型 | 论文证据 | 代码证据 |
|---|---|---|---|---|
| D1 | **多跳检索控制器**：论文把"迭代到 `T_max` 或证据够了"写成 Retrieval Module 的默认能力、G_S/G_P 通用；代码里 `MemoryGraph` 完全没有，只有 HotpotQA 一个脚本外挂，且只支持 semantic、默认还关着 | 两边都有但行为不同 | txt:755-757（主文）、2520-2542（C.3）、2674-2702（Table 14 伪代码） | `plugmem/` 包 grep `multi_hop\|Tmax\|max_hop\|enough` **零命中**；`src/eval/hotpotqa/eval_qa_all.py:122-221`，semantic-only 守卫 `:154-166`，opt-in `:242`+`:480` |
| D2 | **Return score ρ∈[1,10]**：论文有独立 LLM 评委与 prompt；代码恒为 0，评委是死代码 | paper-only | txt:728-730、2426-2427、Listing 3(2236/2238) | `plugmem/inference/structuring.py:124` `_return = 0.0`；`get_return` 零调用；`src/memory_structuring/structuring_inference.py:138` 调用被**注释掉**，139 写死 0.0 |
| D3 | **Intent 去重**：论文是 embedding cosine > `θ_equal`；代码是 Python dict 精确字符串匹配 | 两边都有但行为不同 | txt:2428-2431 | `plugmem/core/memory_graph.py:515` `self.subgoal2node.get(subgoal_str)`；`insert()` 363-593 内无任何 cosine |
| D4 | **重排信号 importance**：论文说 relevance **和** importance 一起重排剪枝；代码算了 `importance_score` 却被恒 0 的 `compute_importance` 吃掉，排序退化成纯 cosine | 两边都有但行为不同 | txt:754-755、2531 | `memory_graph.py:764`(算) → `:767-770`(传) → `value_functions.py:75-76`(恒 0)；`value_base.py:30` 连 `v_credibility` 都漏加（`src/memory_retrieving/value_base.py:26` 同款） |
| D5 | **语义检索第一路的 k**：论文只说"对全部低层节点打分"初始化 C0，未给数；代码硬编码 top-5，与外部 k 无关 | 两边都有但参数不同 | txt:735-739；E.1 txt:3313 `we set k=10` 对应的是最终 top-10 | `memory_graph.py:686` `sem_node_topk = 5`（不受参数影响）；最终 k=10 见 `value_functions.py:71` |
| D6 | **Episodic 检索的映射规则**：论文只有 `ToEpisodic(C, G_E)` 一行；代码用 session 投票 ≥3 才搬整段，否则返回语义命题文本（**根本没回到情景原文**） | code-only | txt:2696+2702、732-734 | `memory_graph.py:871`（`>= 3`）、`:876-877`（否则返回 `sn.get_semantic_memory()`） |
| D7 | **`credibility` / `confidence` / `source` / 记忆晋升**：论文完全没有这些概念 | code-only | 论文 `grep -i credib` **0 命中**；`promot` 0 命中；`confidence` 4 处全在信息论分析语境 | `graph_node.py:70` `credibility: int = 10`、`:72` `confidence: float = 0.5`；`inference/promotion.py:24/31-32`；API `/extract` |
| D8 | **Reasoning Module 的归属**：论文把它列为 PlugMem 三大组件之一；代码里 `retrieve_memory` 只返回 `messages`，压缩那次 LLM 由调用方自己调，`retrieve_and_reason()` 在 eval 脚本里零调用 | 两边都有但行为不同 | txt:444-451、761-775、C.4 2660-2766 | `memory_graph.py:1091-1092,1108`；`eval_longmemeval_all.py:102`、`plugmem_agent.py:234`；`retrieve_and_reason` 定义在 `:1274` 但 `src/eval/` 无调用点 |
| D9 | **LongMemEval 的模型配置**：论文 reasoning=Qwen2.5-72B、base agent=Qwen2.5-72B；复现脚本硬编码 gpt-4o，且显式实参优先于环境变量 | 两边都有但参数不同 | Table 3 txt:1057-1058（`Q32 + Q72`）；E.1 txt:3310-3313 | `eval_longmemeval_all.py:102,116` `model_name="gpt-4o"`；`src/utils.py:142` `model_name or env or DEFAULT` → 无法被环境变量覆盖。**注**：WebArena 无此冲突（Table 5 txt:1107-1109 = `Q32+4o`，与代码一致） |
| D10 | **分段阈值取值**：论文只说 "a predefined threshold"；代码写死 0.75 | 两边都有但参数不同 | txt:640、2420-2422 | `plugmem/core/memory.py:81`、`src/memory_structuring/memory.py:48`：`< 0.75` |
| D11 | **memory type 能否多选**：论文自相矛盾（Table 14 `F ⊆ {E,S,P}` 允许子集，Listing 8 要求 "only one"）；代码严格三选一，站 Listing 8 那边 | 两边都有但行为不同 | txt:2683 vs txt:2560 | `memory_graph.py:56-70` `_normalize_mode` + `:1011` `get_mode` 单值返回；`_VALID_MODES` 三元互斥 |
| D12 | **任务适配变体**：`Memory_LongMemEval` 完全跳过 subgoal/reward/state 标准化、不产程序记忆，论文 Appendix F 只说"换抽取 prompt + 反思式更新"，没写还关掉了标准化 | code-only | txt:3736-3746 | `src/memory_structuring/memory.py:100-148`（`subgoal=""`, `reward=""`, `state=""`，`close()` 只跑 semantic）；`eval_longmemeval_sota.py:12-13` 使用它，模型 `gpt-5.4`(:92,:106) |
| D13 | **delete / decay**：论文 Table 13 承诺"衰减低效用节点 + 压缩旧的情景节点"；代码只有半个衰减（`credibility_decay` 默认 0）+ 软删，**完全没有 episodic 压缩** | paper-only | txt:2140-2143 | grep `compress\|prune\|evict` 全仓仅命中 `credibility_decay`(`memory_graph.py:1356/1374`)；唯一 delete API 是整图删除 `routes/graphs.py:53` |
| D14 | **存储与近邻检索**：`plugmem/` 用 ChromaDB 却只做持久化，4 个 ANN 查询方法零调用，检索全靠 Python 暴力 for 循环 | code-only | 论文不涉及存储实现 | `chroma.py:411/521/623/750` 四个 `query_*` 全仓零调用；`memory_graph.py:688-696` 手写 cosine 循环 |
| D15 | **`plugmem/` 是不是"论文之外"**（`code-architecture.md` 前言的判断） | — | — | `git log --reverse -- plugmem/`：首提交 `e064baf` **2026-03-19** 早于 2026-04 ICML 接收；REST 层 `c1c19e1` 2026-04-14；仅 plugin/promotion 部分（`26bca52` 2026-05-03）才是接收后新增 |

---

## 6. 新造的 primitive 标签

**无（none）。** 全部步骤都用种子词表现有标签覆盖。两处值得说明的复用判断：

- **轨迹分段**（W6 / c-W2）——种子词表没有"按边界切分序列"的条目。判定为 `P-AGGREGATE`，理由：其产物 sub-trajectory 是"比单步更高层的单元（事件段）"，与 `P-AGGREGATE` 定义中的"聚合成更高层单元（事件/…）"同构，只是实现手段是切分而非合并。为避免为一个系统单造标签，优先复用。
- **多跳循环**（R3/R9 / c-R14）——判定为 `P-TOOLLOOP`（词表原文即"agent工具循环/**多跳控制**"），无需新造。注意代码侧这枚标签落在**评测脚本**而非记忆系统。

---

## 7. 复核统计

| 判定 | 论文文档 | 代码文档 | 合计 |
|---|---|---|---|
| ✓ 属实 | 65 | 57 | **122** |
| ✗ 不实 | 1 | 3 | **4** |
| ◐ 部分属实 / 需加限定 | 17 | 11 | **28** |
| ? 无法核实 | 0 | 0 | **0** |
| **总计** | 83 | 71 | **154** |

**✗ 的 4 条**
1. `paper-architecture.md` §2.2：分段阈值"在 C.2 行 2437-2438" —— 实际 txt:2420-2422，2437-2438 是 Listing 6 的标题行。
2. `code-architecture.md` 前言："三个基准的官方复现脚本全部 import `src/` 这一套" —— LongMemEval 与 WebArena 无条件用 `PlugMemClient`（HTTP → `plugmem/` 服务）。
3. `code-architecture.md` 前言："`plugmem/` … README 显示这部分 2026-05 才上，晚于 2026-04 ICML 接收" —— 首提交 2026-03-19。
4. `code-architecture.md` §5：由第 3 条派生的"plugmem/ 是否论文之后新增"的推断方向错误。

**另有 6 条本次新发现、两份文档都没写的代码缺陷**（intent 合并后字符串未回写、API 的插入去重阈值是死旋钮、检索有 `importance += 1` 副作用、episodic 路不过滤 `is_active`、episodic 模式三趟检索两趟白跑、sibling 边已实现却未记录），详见 §2.2 末尾。

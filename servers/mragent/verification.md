# mragent 架构文档复核报告

> 复核日期 2026-09-05；论文源 `Ji-2026-Memory-is-Reconstructed-Not-Retrieved-Graph-Memory-for-LLM-Agents.txt`（1984 行）；代码源 `MRAgent` @ `7441506`（单提交，`Mon Jun 8 20:58:34 2026 +0800`）。
> 本次复核所有论文证据均写为该 .txt 的实际行号（`txt:N`），所有代码证据均逐条打开 `file:line` 现场确认。
> `servers/mragent/` 下只有两份 .md，没有 memory-bench 自己的 .py 适配层，故本报告只覆盖论文侧与上游仓库侧。

## 1. 总评

两份文档的**事实密度和可核查性都很高**：112 条可判定断言里 85 条完全属实，绝大多数 `file.py:NNN` 是逐行精确的（`agent.py:796-803/811/847-848`、`llm/controller.py:140-143/178-181/187-189`、`memory/controller.py:29-47/54-96/214/263`、`memory/system.py:16-36/38-43/45-76/78-96/372-376` 全部命中），论文侧的 §/Eq/Table/Algorithm 编号也基本对得上原文。文档作者对"最大冲突"（图里存的是原始对话原文而非改写句）的判断经三处交叉验证成立，是这两份文档最有价值的发现。

最严重的问题有三类。**第一类是一条运行时不成立的机制断言**：`code-architecture.md` 反复强调的"两路 LLM 精排取并集"在主问答路径上根本跑不到第二路——`select_finegrained_sentence_sort` 的入口条件 `len(coarse_ids) > K2`（`agent.py:315`）在它被调用时恒为假，`top_ids2` 恒为空，"并集"是 no-op；实际只有一路 LLM 精排生效。这条错误还向下污染了 `code-architecture.md` §6.2 对"论文 ActiveSetInit 一步 vs 代码 5-6 种机制"的计数。**第二类是两条被 Appendix E 证伪的"论文没写"式否定断言**：`paper-architecture.md` 说 Appendix E 的 prompt"原文自己标注这是简化摘要"（原文没有任何此类标注），`code-architecture.md` §6.5 说 5 个抽取函数合并成 2 次调用这件事"论文完全没写、得看代码才知道"——但论文 Appendix E 的 Dialogue Processing Prompt（txt:1946-1990）已经把"改写句+tag+topics+personal_sentences 一个 schema 一次产出"完整摆出来了，Keyword Extraction Prompt（txt:1919-1943）另算一次，论文附录事实上已经给出了 2-prompt 结构。**第三类是若干需要加限定的概括**：把 7 个工具都说成"对应 §3.1 定义的映射算子"（§3.1 Eq.5 只定义了 2 个，5 个算子全文只在 Table 4 出现过）；把 `event_by_tag` 的 embedding 重排也算进"2 个工具会临时插一次 LLM"；以及 3 处 prompt 常量的行号区间多吞了 12 行左右的后续代码。

除此之外还发现两处**文档没提、但两边都值得记一笔的代码事实**：`agent.py:698` 调用 `check_key_json(keys_out, text, replace=True)`，而 `prompts/schema.py:144` 的签名是 `check_key_json(text, ref_obj=None)`——关键词抽取第 3 次重试失败时会抛 TypeError；以及 `answer_question_with_time_lm`（LM 时间分支）在 `agent.py:192-193` 花 LLM 调用算出 `key_candidates`/`key_tag_sentences` 后，`agent.py:195-199` 的 `ans_input` 根本没装进去，属纯浪费。

整体结论：两份文档可以放心用作骨架抽取的输入，但"两路 LLM 精排取并集"这一条必须改成"一路"，`§6.5`/`§5` 里两条关于"论文没写"的判断需要撤回。

## 2. 逐条核对表

### 2.1 paper-architecture.md — 文档头 / §1 一句话机制

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| P1 | 头 | "arXiv:2606.06036" | ✓ | txt:5 `arXiv:2606.06036v1 [cs.AI] 4 Jun 2026` | |
| P2 | 头 | "ICML 2026 / PMLR 306" | ✓ | txt:60-61 `Proceedings of the 43rd International Conference on Machine Learning, Seoul, South Korea. PMLR 306, 2026` | |
| P3 | 头 | "NUS Shuo Ji / Yibo Li / Bryan Hooi" | ✓ | txt:3；txt:57 `National University of Singapore, Singapore` | |
| P4 | 头 | "正文+全部附录 A-E，共1984行" | ✓ | `wc -l`=1984；A@txt:1172, B@1275, C@1373, D@1609, E@1897 | 五个附录齐全 |
| P5 | §1 | "Cue–Tag–Content 三元关联图" | ✓ | txt:193 §3.1 标题；txt:226-228 `M = (C, V, R)`；txt:244-246 `R ⊆ C×G×V` | |
| P6 | §1 | "每一步根据已积累证据决定下一步…要不要收尾" | ✓ | txt:404-413（§4.2 开篇迭代循环）；txt:448-455（`H(t)` 条件化）；txt:510-513（C_LLM 判停） | |
| P7 | §1 | 锚点"§2.1 Eq.1-2" | ✓ | txt:81-107：Eq.(1) 被动 `πp(x)`，Eq.(2) 主动 `πa(t)(x,S(t-1))` | 编号与内容一致 |
| P8 | §1 | "§4.3，Theorem 4.1，证明见 Appendix C" | ✓ | §4.3@txt:531；Theorem 4.1@txt:468-482；Appendix C@txt:1373 | |
| P9 | §1 | "允许 T 步自适应检索下主动严格强于被动" | ✓ | txt:481-482 `H_passive^LM(T) ⊊ H_active^LM(T)` | 原文限定 `T ≥ 2`（txt:469），文档未复述该限定 |

### 2.2 paper-architecture.md — §2 记忆写入

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| P10 | §2 | "论文没有明确写实时逐轮还是整段离线批量" | ✓ | 全文 grep 未见任何 online/per-turn/batch 的构建时机表述 | 否定式断言，实际证伪通过 |
| P11 | §2 | §3.3 引文 "populated through an automated distillation pipeline applied to the input stream T" | ✓ | txt:309-310 逐字一致 | |
| P12 | §2 | "Figure 4(a) 把 construction 画成…一次性阶段" | ? | txt:237-241 只有 Figure 4 图注（`constructs an associative memory system from dialogues`），.txt 无图内容 | 图形内容无法从纯文本核实；图注本身不足以支撑"一次性" |
| P13 | §2 | "三层结构，均由 LLM 抽取（§3.2/§3.3/B.1）" | ✓ | txt:286-307（§3.2 三层）；txt:308-330（§3.3）；txt:1277-1315（B.1 Eq.18-21） | |
| P14 | §2 | Eq.18 `{e_i} ← R_LLM(T)`，含"代词消解/时间归一化/episode 切分" | ✓ | txt:1283 `{ei} ← RLLM(T)`；txt:1285 `pronoun resolution, temporal normalization, and episodic segmentation` | |
| P15 | §2 | "对每个 `e_i` 分别跑 `T_LLM`/`K_LLM`（Eq.19）" | ◐ | txt:1288 prose 写 `For each episodic segment ei`，但 txt:1289-1291 的 Eq.19 实际写作 `gi ← TLLM(xi)`, `Ci ← KLLM(xi)`；txt:1294 `We then add nodes for xi` | 论文自身 `e_i`/`x_i` 记号不一致，文档静默归一成 `e_i`，未标注 |
| P16 | §2 | "`K_LLM` 抽 cue（实体、动作、上下文关键词等）（Eq.19）" | ◐ | Eq.19 语境（txt:1293-1294）用词是 `entities, attributes, and other salient descriptors`；"实体/动作/上下文关键词"是 §3.2 txt:292-294 的措辞 | 内容不错，但引用锚点挂错小节 |
| P17 | §2 | "每个 cue 通过 tag `g_i` 连到 `e_i`，构成 Cue–Tag–Episode" | ✓ | txt:1294-1295；§3.3 txt:343-345 | |
| P18 | §2 | "Episodic 层沿统一时间线组织支撑时间推理（§3.2）" | ✓ | txt:296-299 `organized along a unified timeline` | |
| P19 | §2 | Semantic 层"个人属性、偏好、一般性事实（§3.2）" | ✓ | txt:300-302 `personal attributes, preferences, and general facts` | |
| P20 | §2 | "`S_LLM` 直接作用于原始输入流 `T`（Eq.20），不是已切好的 episode" | ✓ | txt:1300-1301 `from the input text T via an LLM-based semantic extraction function`；Eq.20@txt:1302 | |
| P21 | §2 | "`c^s` 实体级 cue / `g^s` aspect-level tag / `s` 语义内容" | ✓ | txt:1298-1299；txt:1304-1307；§3.2 txt:303-305 | |
| P22 | §2 | "论文原文把这一步写成…**一次独立 LLM 调用**" | ◐ | 论文只写成独立的 *函数*（Eq.20），从未提"调用次数"；且 Appendix E 的 Dialogue Processing Prompt（txt:1975-1989 的 `personal_sentences` 字段）把语义抽取与改写放在同一个 prompt/schema 里 | 与文档自己 §5/§6.3 的"论文没说几次调用"自相矛盾 |
| P23 | §2 | "`A_LLM` 对已抽出的 episode 集合 `{e_i}` 做摘要（Eq.21）" | ✓ | txt:1311-1312 `applying an LLM-based abstraction function to the set of episodic segments`；Eq.21@txt:1313 | |
| P24 | §2 | "论文明确写输入是 `{e_i}` 不是 `T`" | ✓ | txt:1313 `{τj} ← ALLM({ei})` | |
| P25 | §2 | "三层抽取呈现为三个概念上独立的 LLM 函数族" | ✓ | Eq.18-21 分别为 R/T/K、S、A 三组独立函数（txt:1283/1289/1302/1313） | 形式化层面成立；执行层面见 P22/P51 |
| P26 | §2 | "把记忆系统建模成异构图 `M=(C,V,R)`（§3.1）" | ✓ | txt:226-228 逐字一致 | |
| P27 | §2 | "`R⊆C×G×V` 是带 tag 属性的三元关系" | ✓ | txt:244-246 | |
| P28 | §2 | "论文完全没有提…是否持久化、内存占用等" | ◐ | §7 txt:950-953 明写 `the memory graph grows monotonically as interactions accumulate, raising storage overhead in long-lived deployments` | 数据结构/持久化格式确实没写，但"内存/存储占用"论文在局限性里点过 |

### 2.3 paper-architecture.md — §3 记忆检索

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| P29 | §3 | "每个查询 `x` 一次（§4.2 开篇）" | ✓ | txt:405-413 `Given a query, MRAgent first extracts a set of fine-grained cues…` | |
| P30 | §3 | "抽 cue 匹配图 cue 集合 → `Z(0)`，`S(0)=(Z(0),∅)`（Alg.1 line 1-4）" | ✓ | txt:408-413；Algorithm 1 line1-4 @ txt:1329-1333 | |
| P31 | §3 | "Algorithm 1 在 Appendix B.2" | ✓ | B.2@txt:1318；Algorithm 1@txt:1326-1350 | |
| P32 | §3 | "论文没有展开'匹配'具体怎么做" | ✓ | 全文与之相关只有 txt:408-409 一句 `matches them against the stored cue set`；`ACTIVESETINIT` 仅出现于 txt:1331 | 否定断言经 grep 全文证伪通过 |
| P33 | §3 | "多步迭代，循环体三个角色（§4.1-4.2，Eq.7/10-12，Alg.1 line 5-19）" | ✓ | Eq.7@txt:430；Eq.10@txt:444；Eq.11@txt:466；Eq.12@txt:496；for 循环@txt:1334-1348 | 行号区间与伪代码完全对应 |
| P34 | §3 | `f_select` 引文"减少噪声…发现新 cue、动态调整推理轨迹" | ✓ | txt:426-427（小标题）；txt:448-455 | |
| P35 | §3 | "Forward（Cue→Tag / (Cue,Tag)→Content）+ Reverse（Content→(Cue,Tag)），Eq.8-9/11" | ✓ | txt:335（Forward）；txt:355-380（Eq.8）；txt:385-395（Eq.9 Reverse）；txt:461-466（Eq.11） | |
| P36 | §3 | Reverse 引文"发现新检索线索、重定向重构轨迹" | ✓ | txt:386-388 `refine or redirect its reconstruction trajectory` | |
| P37 | §3 | `f_route` 公式 `Z(t+1)=f_route(x,H(t),Z̃(t+1))`，`H(t+1)=H(t)∪Z(t+1)` | ✓ | txt:489（小标题）；txt:496-498（Eq.12） | |
| P38 | §3 | 引文"不是表层匹配或预定义遍历…纳入图暴露的语义关联和结构关系" | ✓ | txt:508-510 | |
| P39 | §3 | "`H(t+1)` 交给 `C_LLM` 判停，最多 `T` 步（Alg.1 line 16-18）" | ✓ | txt:510-513（`evaluated by CLLM to determine if the evidence is sufficient`）；txt:1344-1348（`if STOP(x,H(t+1)) then break`） | |
| P40 | §3 | "`Ψ∈{Navigate, Answer}`（§B.2）" | ✓ | txt:1361-1363 | |
| P41 | §3 | "工具箱固定 7 个工具（Table 4，Appendix B.2）" | ✓ | Table 4@txt:1243-1265（7 行）；B.2 正文引用@txt:1365 | |
| P42 | §3 | 7 个工具名与 `ϕ` 映射逐条列出 | ✓ | txt:1248-1265，7 组工具名/映射/描述与文档完全一致 | |
| P43 | §3 | "每个都对应 **§3.1 定义**的一个映射算子 `ϕ`" | ◐ | §3.1 Eq.5（txt:263-264）只定义 `ϕc→g`、`ϕ(c,g)→v`；`ϕτ→e` 在 §3.2（txt:283）；`ϕe→t`/`ϕe→(c,g)`/`ϕe→ctx`/`ϕcs→gs`/`ϕ(cs,gs)→vs` 全文只在 Table 4（txt:1260-1264）出现，正文从未定义 | 7 个里只有 2 个真正出自 §3.1；B.2 原文措辞是 `a typed mapping between memory components`（txt:1366），并未说都在 §3.1 定义过 |
| P44 | §3 | "最终答案 `ŷ = AnswerLLM(x, H^(T))`（Alg.1 line 20）" | ◐ | txt:1349 伪代码实为 `ŷ ← ANSWERLLM(x, H(t+1))` | 上标写错（`H^(T)` vs `H^(t+1)`）；机制描述本身正确 |
| P45 | §3 | "Appendix E 给了精简版 QA and Tool-Use Prompt（答题规则 + 两种模式 JSON）" | ✓ | txt:1898-1917：Yes/No/Likely yes/Likely no、place name、number、minimal concrete entity、`answer`/`navigate` 两模式 JSON，与文档逐条对应 | |
| P46 | §3 | 边界说明：图+`ϕ` 归记忆系统，`f_select`/`f_route`/`C_LLM`/`AnswerLLM` 归 LLM 侧 | ✓ | txt:461-462 `the memory system executes the corresponding traversal operator`；txt:1368-1372（LLM 选工具/评估返回结果/决定扩展或终止） | |

### 2.4 paper-architecture.md — §5 我没搞清楚的 / §6 论文没写清楚的

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| P47 | §5 | "Table 6 只列 5 个工具，缺 `query event keywords`/`query personal information`" | ✓ | txt:1848-1857：只有 query tag events / query conversation time / query event context / query personal aspect / query topic events | 完全属实，且论文 D.7 正文（txt:1830-1841）也未解释 |
| P48 | §5 | "`f_select` 与 `f_route` 是两次独立调用还是同一次，论文只给了数学记号" | ◐ | Appendix E 只给了**一个** QA and Tool-Use Prompt（txt:1898-1917），内含 `answer`/`navigate` 二选一；B.2 txt:1368-1370 描述为同一步内"选工具→调用→评估返回结果" | 论文确实没有一句显式说明，但附录 prompt 结构已强烈指向"每轮一次调用"，文档未把这条证据纳入 |
| P49 | §5 | "`C_LLM`（§4.2）与 `STOP`（Alg.1）是否同一个东西无法百分百确认" | ✓ | txt:511 `CLLM` vs txt:1344 `STOP(x, H(t+1))`，全文无桥接说明 | |
| P50 | §5 | "`A_LLM({e_i})` 的输入范围（单 session 还是跨 session）论文没写" | ✓ | txt:1309-1315 通读，只说 `a coherent set of episodes`，无粒度说明 | |
| P51 | §5 | "五个抽取函数对应几次实际 API 调用，论文的数学记号完全没有对应到具体调用次数" | ◐ | Appendix E 的 Dialogue Processing Prompt（txt:1946-1990）在同一 schema 里同时输出 `sentence[].text/.tag`、`topics{}`、`personal_sentences[]`，Keyword Extraction Prompt（txt:1919-1943）单独一份 | 正文数学记号确实没写，但附录 prompt 事实上已把"5 函数→2 prompt"摆出来了 |
| P52 | §5 | "Appendix E 只给了 3 段 prompt（QA与工具使用、关键词抽取、对话处理）" | ✓ | txt:1898 / txt:1919 / txt:1946 三段，无第四段 | |
| P53 | §5 | "**且原文自己标注这是简化摘要**" | ✗ | 全文 grep `simplif\|abridg\|condensed\|shortened\|for brevity` 无任何命中；Appendix E（txt:1897-1990）没有任何"这是精简版"的标注 | 该断言无据；括号里给出的理由（只有规则列表和 JSON schema）是文档作者自己的推断，不是原文标注 |
| P54 | §5 | "对话处理 prompt 里同时出现 topic 和 personal_sentences 输出字段" | ✓ | txt:1975-1989 `"topics": {...}` 与 `"personal_sentences": [...]` 同在一个 Output Schema | |
| P55 | §5 | "Table 3 的统计口径论文没有逐项拆解，只给汇总数字" | ◐ | Table 3 caption txt:789-790 明写 `Results include both memory construction and retrieval`；数值 txt:797-806（MRAgent 118k / 586.11s） | 口径**范围**论文写了，只是没有分项拆解；文档措辞把"没拆解"扩大成了"口径不明" |
| P56 | §6.1 | "`ActiveSetInit(C,G)` 论文完全没有算法层面说明，唯一相关一句是 'matches them against the stored cue set'" | ✓ | txt:1331（唯一伪代码出现）；txt:408-409（唯一正文描述） | 强否定断言，全文 grep 证伪通过 |
| P57 | §6.2 | "§4.2 正文两个独立小标题；Alg.1 line 7 与 line 14 是两条分开的赋值语句" | ✓ | 小标题 txt:426 / txt:489；line7@txt:1335、line14@txt:1342 | 行号与伪代码编号完全对应 |
| P58 | §6.2 | "论文从未说明是两次独立 API 调用还是同一次调用" | ◐ | 同 P48：Appendix E 的单一 prompt + B.2 txt:1368-1370 已是间接证据 | |
| P59 | §6.3 | "论文没有说明原始对话文本是否会被完整喂给模型两次" | ◐ | Appendix E Dialogue Processing Prompt（txt:1946-1990）一次同时产出改写句与 personal_sentences，实际已回答"不是两次" | 文档 §5 提到了这个 prompt，§6.3 却仍按"论文完全没写"论述，前后不一致 |
| P60 | §6.3 | "§5.3/§7 反复强调 construction 阶段 lightweight" | ✓ | txt:845-847 `maintains a lightweight construction phase and defers complex relation-building to the retrieval stage`；txt:940-944 | |

### 2.5 code-architecture.md — 文档头 / §1 / §2 记忆写入

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| C1 | 头 | "commit `7441506`，单提交仓库，无 tag/无 CHANGELOG" | ✓ | `git rev-parse --short HEAD`=7441506；`git log` 仅 1 条；仓库无 CHANGELOG 文件 | |
| C2 | 头 | "只读了…没有实际跑起来（无 API key，只静态读代码）" | ? | 作者自述行为，无法从产物核实 | 不影响结论 |
| C3 | §1 | "纯 Python 内存对象图…进程内、单次 run 只服务一个对话样本、不持久化" | ✓ | `memory/system.py:107-128`（全是 dict/list，无任何写盘）；`run.py:165` 每 sample `MemorySystem()` | |
| C4 | §1 | "最多 8 轮的 LLM 工具调用循环" | ✓ | `common/config.py:66` `MAX_ROUNDS=8`；`llm/controller.py:104,137` | |
| C5 | §2 | "`run.py:184-205`（`main()`）依次跑完 rewrite→keyword→embedding→store 四步" | ✓ | `run.py:184` rewrite_sample、`:190` extract_keyword_sample、`:196` embed_sample、`:203` store_raw_text、`:205` store_keyword | 四步顺序与文档一致 |
| C6 | §2 | "`MemorySystem()` 对每个 sample 重新 new 一次，不从上一个 sample 累积" | ✓ | `run.py:163-167`（在 for 循环体内 new） | |
| C7 | §2 | "不跨进程持久化；重启从磁盘缓存 JSON/pkl 重新组图" | ✓ | `common/config.py:89-92`（三个缓存模板）；`run.py:183/189/195` 存在即跳过 | |
| C8 | §2.1 | rewrite：`agent.py:592`/`623`/`657`，prompt=`prompts/prompts.py:18-67` | ◐ | `agent.py:592` `def rewrite`、`:623` `def rewrite_sample`、`:657` `def rewrite_sentence` 三处**精确命中**；但 `REWRITE_SYSTEM_PROMPT` 实为 `prompts.py:18-55`，56-67 是 `REWRITE_PROMPT` 与 `extract_rewrite_prompt` | 行号区间多吞 12 行 |
| C9 | §2.1 | "一次 LLM 调用同一个 JSON schema 同时产出改写句 + 每句 tag + ≥10 topics + personal_sentences" | ✓ | `prompts.py:21-22`（代词消解）、`:23`（tag）、`:27`（≥10 topics）、`:28`（personal_sentences）、`:31-54`（单一 schema）；`agent.py:594-597` 单次 `chat_text` | 核心机制断言，完全属实 |
| C10 | §2.1 | "落盘 `data/<ds>/rewrite_<model>/<sample_id>_rewrite.json`，已存在则跳过（`run.py:182-185`）" | ✓ | `config.py:89` 模板逐字一致；`run.py:182-186` | |
| C11 | §2.2 | keyword：`agent.py:669`/`712`/`665`，prompt=`prompts.py:69-99` | ◐ | `agent.py:669` `def extract_keys`、`:712` `def extract_keyword`、`:665` `def extract_keyword_sample` **精确命中**；但 `KEYWORD_SYSTEM_PROMPT` 实为 `prompts.py:69-87`，89-99 是 `KEYWORD_PROMPT`/`extract_keyword_prompt` | 行号区间多吞 12 行 |
| C12 | §2.2 | "输入是第1步改写句；`agent.py:737-743` 显式丢弃 tag/origin/topic/time 只留 `{id,text}`" | ✓ | `agent.py:734-735` 注释 + `:737-743` 构造 `filtered_sentences` | 精确命中；另注 `extract_keyword_prompt` 的 `tag_list` 参数根本没被用（`prompts.py:96-99`），更强化了这条 |
| C13 | §2.3 | embedding：`embed_rewrite.py:20`、`llm/embeddings.py:34-36`、`rag_utils.py:10-26`；3072 维、L2 归一化、OpenRouter | ✓ | `embed_rewrite.py:20` `def embed_sample`；`embeddings.py:34-36` `get_openai_embedding(..., model="text-embedding-3-large")`；`embeddings.py:13,53` 3072-d；`rag_utils.py:10-26` `get_embeddings` 含 `F.normalize`；`embeddings.py:17` OpenRouter base_url | 四个锚点全部精确 |
| C14 | §2.3 | "问题 embedding 也在这一步一次性算完（`embed_rewrite.py:12`），不是问答时现算" | ✓ | `embed_rewrite.py:12` `def embed_question`，`:64` 在 `embed_sample` 内调用并写进 pkl；`run.py:202,208` 问答时直接读 | |
| C15 | §2.4 | 组图：`agent.py:864` store_raw_text、`:748` store_keyword、`:772` store_event_new | ✓ | 三处 `def` 精确命中 | |
| C16 | §2.4 | `system.py:78-96` EpisodeEvent / `45-76` PersonalEvent+Persona / `38-43` Topic / `16-36`+`99-105` KeyNode+Link | ✓ | 逐个打开：EpisodeEvent@78-96、PersonalEvent@45-51、Persona@54-75、Topic@38-42、KeyNode@16-35、Link@99-104 | 全部精确（误差 ≤1 行空行） |
| C17 | §2.4 | "说话人会被强制补进 cue 列表（`agent.py:847-848`：`if speaker not in ks: ks.append(speaker)`）" | ✓ | `agent.py:847-848` 逐字一致 | |
| C18 | §2 关键细节 / §6.1 | 【最大冲突】"`EpisodeEvent.text` 是按 origin 查回的**原始对话行**，不是改写句" | ✓ | `agent.py:796` `embedding = self.memory.embeddings[id]`（改写句向量）；`:798-803` `text = self.memory.raw_text[prefix].get(origin)`；`:811` `EpisodeEvent(id, text, ...)`；`store_event_new` 全函数（772-862）从未读取 `ee.get("text")`；`embed_rewrite.py:46` 读的确实是改写句 `s.get("text")`；`get_data.py:64-70` raw_text 未经任何 LLM | 三处交叉验证全部成立。唯一措辞瑕疵："`text` 被覆盖成原文"——代码里 `text` 从来没被赋过改写句，是直接从 raw_text 构造的 |
| C19 | §2 关键细节 | "Topic 和 PersonalEvent 文本就是 LLM 直接生成的内容（`agent.py:778, 821, 779-829`）" | ✓ | `:778` `topic_sentences = events.get("topics")`；`:821` `add_topics`；`:779` `personal_sentences=...`；`:823-829` 逐条 `add_personal_information` | |

### 2.6 code-architecture.md — §3 记忆检索

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| C20 | §3 触发 | "每问题一次，同 sample 下 10 线程并发（`run.py:31`），各自 new LLM/MemoryController/Agent，共享只读 `memory_system`" | ✓ | `run.py:31` `def get_question`；`:89` `MAX_WORKERS = 10`；`:92` ThreadPoolExecutor；`:57-59` 每线程 new 三件套；`:36` 注释 `shared read-only` | |
| C21 | §3.1 | "先用 LLM 抽问题 cue + 时间范围（`agent.py:566`，`prompts.py:206-218`）" | ◐ | `agent.py:566` `def extract_question_keys` **精确**；`QUESTION_KEY_SYSTEM_PROMPT` 实为 `prompts.py:206-219`（含 `keywords[].alternatives` 与 `question_time`） | 1 行偏差，内容属实 |
| C22 | §3.2 | "图匹配**不用向量**，纯文本归一化+子集/Jaccard 匹配 KeyNode（`controller.py:214`），拿 `evaluate_relations_over_graph`（`:263`）的 full/partial 候选池" | ✓ | `memory/controller.py:213` 段注释 `text-only, no vectors`；`:214` def；`:243-257` 精确相等/子集包含/Jaccard≥0.6；`:263` def，`:370` 返回 `{"full_matches","partial_matches"}` | 两个行号精确命中 |
| C23 | §3.3 | 时间快通道：`system.py:137-146`；locomo `TIME_EVENT_LIMIT=50` 判定在 `agent.py:69`（属 `:64`）；LM 用 `K2=20` 判定在 `agent.py:117`（属 `:111`） | ✓ | `system.py:137-147` `get_time_event`（`timeline: Dict[datetime, List[str]]`@`:118`）；`agent.py:64` def / `:69` `if len(events_time) < config.TIME_EVENT_LIMIT`；`agent.py:111` def / `:117` `if len(events_time) < config.K2` | 四个行号全部精确 |
| C24 | §3.3 | "候选够少直接给，太多则**退回第4步的图匹配结果**按时间过滤" | ◐ | `agent.py:85-104`：else 分支是重跑 `evaluate_relations_over_graph`（第2步）+ 按 `events_time_originlist` 过滤，**不含**第4步的 K1 粗排与 K2 LLM 精排 | "第4步"指错；locomo 时间分支根本不做 K1/K2/topic/key_tag |
| C25 | §3.4 | "候选数 > `K1=80` 用 embedding 点积粗排（`utils.py::topk_answers_by_similarity`，`agent.py:497`）" | ✓ | `agent.py:495` 阈值判断、`:497` 调用；`common/utils.py:47` def，`:72` `np.dot`（默认 `similarity="dot"`） | |
| C26 | §3.4 / 架构图 | "dedup 后 >`K2=20` 触发**两路不同的 LLM 精排**…**两次结果取并集去重**（`agent.py:524-534`）" | ✗ | 函数/prompt/行号本身都对（`agent.py:244`+`prompts.py:112-116`；`agent.py:309`+`prompts.py:104-110`；并集在 `:525-533`）。但**第二路不可达**：`select_finegrained_sentence` 的所有返回分支都保证 `len(selected_list) ≤ K2`（`agent.py:291-304` 一律 `topk(k=config.K2)`），而 `select_finegrained_sentence_sort` 的入口条件是 `agent.py:315` `if len(coarse_ids) > config.K2`，`20 > 20` 恒假 → 直接返回 `([],[],[])`，`top_ids2` 恒为空，`:525-533` 的并集是 no-op | **主问答路径上只有一路 LLM 精排（`ANSWER_SORT_PROMPT2`）真正生效**。反例：`ANSWER_SORT_PROMPT`（0-1 打分）只在 LM 时间分支 `agent.py:178` 被首先调用，那里顺序相反、且第二路同样死掉并额外被 `config.MODEL_NAME=="gemini"`（`:180`）再加一道门 |
| C27 | §3.5 | "另开一路独立向量检索 `select_topic`（`agent.py:236`）取 top `TOPIC_K=8`，与第4步完全不合并、并列塞进上下文" | ◐ | `agent.py:236-242`（`config.TOPIC_K`）、`:520` 调用、`:544` `"similar_topic": top_topic_texts` —— 机制全对；但**执行顺序**是 `:520`（topic）先于 `:522-524`（LLM 精排），文档把它编号为"第5步"排在精排之后 | 仅顺序描述不准，机制无误 |
| C28 | §3.6 | "覆盖标签数 > `TAG_MAX=15` 的 cue，`select_key_tag`（`agent.py:392`）**再触发一次** LLM 打分（`prompts.py:6-16`），≥0.7 的标签预取原文" | ◐ | `agent.py:392` def、`:402` `> config.TAG_MAX`、`:409-414` LLM 调用、`:428` `[:config.TAG_LIMIT]`、`:433` `if v >= 0.7`、`:434` `event_by_tag` 预取 —— 全部精确；`EVENT_KEYWORDS_SYSTEM_PROMPT` 实为 `prompts.py:6-13`（14-17 为空行） | "一次"不准：`:396` 是逐 cue 循环，**每个**高扇出 cue 各一次 LLM 调用，可能多次 |
| C29 | §3.6 | "这一步在工具循环开始前就已经替模型执行了一次等价于 `edges_by_tag` 的操作" | ✓ | `agent.py:434` `self.memory_controller.event_by_tag(key, k, "")`，与 `tools.py:170` 的 `edges_by_tag` 分发目标是同一函数 | |
| C30 | §3 | "拼出的初始证据包 `ans_input = {question, key_sentences, keys_candidates, key_tag_sentences, similar_topic}`（`agent.py:539-548`）" | ◐ | `agent.py:539-545` 五个字段逐字一致，`:547-548` 条件加 `current_date` —— 主路径完全属实 | 但另有两种形状文档未区分：locomo 时间分支 `agent.py:79-83/105-109` 只有 `{question, similar_sentence}`；LM 时间分支 `:126-130/195-199` 只有 `{question, key_sentences, current_date}`（且 `:192-193` 算出来的 `key_candidates`/`key_tag_sentences` 被直接丢弃） |
| C31 | §3 | "`_chat_with_tools`（`agent.py:30`）调 `LLM.chat_with_tools_once`（`llm/controller.py:92`）" | ✓ | `agent.py:30` def、`:31` 调用；`llm/controller.py:92` def | |
| C32 | §3 | "最多 8 轮（`config.py:66`）；第 8 轮强制换成 `ANSWER_SYSTEM_PROMPT_FINAL`（`llm/controller.py:140-143`）" | ✓ | `config.py:66`；`controller.py:137` for 循环、`:140-143` `if round_id == max_rounds: messages[0]["content"]=ANSWER_SYSTEM_PROMPT_FINAL` + 追加 final-round user 消息 | 精确命中 |
| C33 | §3 | "总共最多 50 次工具调用（`config.py:67`），跨全部轮次的全局预算，无单轮硬上限，`controller.py:187-189` 只在总数超预算时整体截断" | ✓ | `config.py:67`；`controller.py:105,134,187-190`（`tool_calls_used + len(tool_calls) > max_tool_calls` 才截断）；`:155` `parallel_tool_calls=True` 无数量限制；全仓库无单轮上限常量 | 强否定断言，实际证伪通过 |
| C34 | §3 | "模型每轮从两种模式二选一：`mode=answer` break（`:178-181`）或发起 `tool_calls` 进入 navigate" | ◐ | `:178-181` 精确；`:184-227` tool_calls 分支精确 | 遗漏第三条路径：既无 answer 也无 tool_calls 时走 `:229-232` 的 `continue`，空烧一轮 |
| C35 | §3 | "7 个工具（`tools.py:4-155`），另有被注释掉的第 8 个 `score_event_relevance` 未启用" | ✓ | `tools.py:4` `TOOLS= [` … `:155` `]`；7 个 function；`:135-153` 注释块 `score_event_relevance` | 区间起止精确 |
| C36 | §3 | "全部纯 Python 图查询、不调 LLM，由 `ToolBridge.call()` 分发（`tools.py:158-193`）" | ✓ | `tools.py:158` class、`:162-192` `call()` 七分支全部转发 `memory_controller`，无 LLM | |
| C37 | §3 | "其中 2 个工具内部候选过多时会**临时插一次 LLM**：`event_by_tag` >`RERANK_LIMIT=20` 用 embedding 重排（`controller.py:29-47`）；`query_event_keywords_single` …用 LLM 打分" | ◐ | `memory/controller.py:29-48` def + `:33` `> config.RERANK_LIMIT` + `:39-40` `topk_answers_by_similarity`（**embedding，不是 LLM**）；`:54-95` 才是真的 LLM | 概括句把 embedding 重排也算成"插一次 LLM"，与紧随其后的括号自相矛盾；实际只有 1 个工具会插 LLM |
| C38 | §3 | "`query_event_keywords_single` 遇到某 cue 标签数 > `TAG_MAX` 且未被问过时用 LLM 打分选 `TAG_LIMIT=10` 个（`controller.py:54-96`）" | ✓ | `:54` def、`:60-64` 已问过则剔除、`:67` `len(tag) > config.TAG_MAX and (key not in key_list)`、`:73-78` LLM、`:88` `[:config.TAG_LIMIT]` | |
| C39 | §3 | "所有工具返回结果**原样**拼回 `messages`（`_append_if_list` 定义 `:114`，调用 `:223`）" | ✓ | `controller.py:114` def、`:223` 调用；`:206-220` 逐个包装为 `role:"tool"` 后全部追加 | 两个行号精确 |
| C40 | §3 | "代码里没有一个独立的路由/剪枝函数去过滤已经拿到的证据" | ✓ | 通读 `controller.py:92-234`：`messages` 只增不删，无任何过滤/淘汰逻辑 | 强否定断言，逐行证伪通过 |
| C41 | §3 | "收尾要么模型自己吐 `mode=answer`（`:178-181`），要么被第 8 轮强制 prompt 逼着回答" | ✓ | 同 C32/C34 | |
| C42 | §3 | "`memory.get_support_origin()`（`system.py:372-376`）把证据 id 映射回 `dia_id` 用于评测" | ✓ | `system.py:372-376` def 全体；`agent.py:563` 调用 | 精确命中 |
| C43 | §4 | 边界说明（`memory/system.py`+`memory/controller.py`+`ToolBridge` 为记忆系统；`agent/agent.py`+`llm/controller.py`+`prompts/` 为 agent/backbone） | ✓ | `system.py` 恰有 7 个查询方法（`:289/303/309/312/315/319/355`）；`tools.py:162-192` 只做分发；`agent.py`/`llm/controller.py` 承载全部 LLM 调用 | 与代码结构一致 |

### 2.7 code-architecture.md — §5 我没搞清楚的 / §6 与论文的冲突点

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| C44 | §5 | "prompt 要求 ≥10 topics，但 `SCHEMA["properties"]["topics"]` 只写 `"type":"object"`，无数量下限；重试（`agent.py:602-618`）只在 schema 校验失败时触发" | ✓ | `prompts.py:27` `derive at least ten concrete topics overall`；`schema.py:47-49` `"topics": {"type": "object"}`；`agent.py:601-619` 重试仅由 `check_rewrite_json` 的 flag 驱动 | |
| C45 | §5 | "locomo 用 `TIME_EVENT_LIMIT=50` 而 LM 用 `K2=20`，代码注释没解释" | ✓ | `config.py:63` 注释只写 `(locomo)`；`agent.py:117` 用 `config.K2` 无注释 | |
| C46 | §6.1 | 最大冲突（图里存原文而非改写句） | ✓ | 同 C18 | |
| C47 | §6.2 | "论文 `ActiveSetInit` 像一步，代码进入工具循环前实际做了 **5-6 种机制**…包括'两路 LLM 精排取并集'" | ◐ | 图匹配（`controller.py:263`）→ K1 向量粗排（`agent.py:495-498`）→ 前缀去重（`:505-518`）→ topic 向量 top-8（`:520`）→ 一路 LLM 精排（`:523`）→ 条件触发的 LLM 标签打分+预取（`:536`）| 机制清单本身成立，但"两路 LLM 精排取并集"这一项不成立（见 C26），实际是 5 种；论文侧的对比（Alg.1 line2 一行 vs 代码一大段）依然有效 |
| C48 | §6.3 | "论文 `f_route` 的剪枝在代码里没有对应的独立函数，工具返回全部原样追加" | ✓ | 同 C39/C40；`llm/controller.py` 无任何删除/过滤 messages 的代码 | |
| C49 | §6.4 | "论文 §D.4 写 'allow up to 10 tool invocations per turn'，代码里没有这个单轮上限，只有全局 `MAX_TOOL_CALLS=50`；平均 50/8≈6.25" | ✓ | txt:1696-1697 逐字一致（并同时给出 `at most 8 turns per query`，与 `MAX_ROUNDS=8` 吻合）；`config.py:67` + `controller.py:187-189` | 算术无误；论文与代码在"8 轮"上其实是一致的，只在"单轮 10 次"上分歧 |
| C50 | §6.5 | "论文 5 个函数在代码里实际收敛成 **2 次 LLM 调用**" | ◐ | `agent.py:646-652`（rewrite_sample 逐 session 循环）、`:722-744`（extract_keyword 逐 session 循环） | 应为"**每 session** 2 次"；整段对话的构建成本是 2 × session 数（LoCoMo 单样本约 20-30 session） |
| C51 | §6.5 | "topic 是直接从原始 session 对话文本生成的，不是先切 episode 再对 episode 集合摘要" | ✓ | `prompts.py:27` 的 topics 要求与 `:21-26` 的逐句改写同在一个 prompt；`agent.py:593-597` 的输入是 `rewrite_sample` 传进来的 session 原文 | 与论文 Eq.21 `A_LLM({e_i})` 确实不同 |
| C52 | §6.5 | "只是'怎么省'**论文完全没写**，得看代码才知道" | ✗ | 论文 Appendix E 的 Dialogue Processing Prompt（txt:1946-1990）在一个 Output Schema 里同时给出 `sentence[].text/.tag`、`topics{}`、`personal_sentences[]`；Keyword Extraction Prompt（txt:1919-1943）单独一份 —— 正是代码里的 2-prompt 结构 | 论文附录已经写了；文档这条否定断言不成立（`paper-architecture.md` §5 其实注意到了这个 prompt，两份文档之间也不自洽） |

## 3. 步骤清单 — 论文侧

### 3.1 写入侧（Memory Construction，§3.3 + Appendix B.1，Figure 4(a)）

| # | name（论文自己的叫法） | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| W1 | input stream `T` | 每个输入流一次（论文未明确 online / batch） | 原始对话 → `T` | no | - | `P-INTAKE` |
| W2 | `R_LLM`: raw text processing（pronoun resolution + temporal normalization + episodic segmentation，Eq.18） | 对整段 `T` 一次 | `T` → `{e_i}` | 1×（论文只给函数记号，未给调用次数） | - | `P-REWRITE` > `P-EXTRACT`（切分出 episodic unit） |
| W3 | `T_LLM`: associative tag generation（Eq.19） | 每个 episode | `e_i` → `g_i` | 1×/episode | - | `P-META` |
| W4 | `K_LLM`: cue extraction（Eq.19） | 每个 episode | `e_i` → `C_i` | 1×/episode | - | `P-META` |
| W5 | Cue–Tag–Episode relations | 每个 episode | `(C_i,g_i,e_i)` → `R` 中三元关系 | no | 异构图 `M` | `P-LINK` |
| W6 | unified timeline organization（§3.2） | 每个 episode | `e_i`+时间 → 时间线 | no | 异构图 `M` | `P-LINK`（时间邻接） |
| W7 | `S_LLM`: semantic unit extraction（Eq.20） | 对整段 `T` 一次，与 W2 并列 | `T` → `{(c^s,g^s,s)}` | 1× | - | `P-EXTRACT` + `P-META`（aspect-level tag） |
| W8 | Cue–Tag–Semantic associations | 每个 semantic unit | 三元组 → 同一张图 | no | 异构图 `M` | `P-LINK` |
| W9 | `A_LLM`: topic abstraction（Eq.21） | 对 `{e_i}` 全集一次 | `{e_i}` → `{τ_j}` | 1× | - | `P-AGGREGATE` |
| W10 | topic–episode links | 每个 topic | `τ_j` ↔ 其 episodes | no | 异构图 `M` | `P-LINK` |

**论文写入侧明确没有的**：`P-EMBED`（全文 embedding 只出现在 baseline 描述里，txt:36/134/1626-1641）、`P-DEDUP`、`P-CONFLICT`、`P-EVICT`、`P-PERSIST`（§7 txt:948-951 明说 `our static construction does not update or consolidate memory over time`）。

### 3.2 检索侧（Active Memory Reconstruction，§4.1-4.2 + Algorithm 1）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| R1 | `ExtractCues(x)`（Alg.1 line1） | 每 query | `x` → `C` | 1×（论文未明说；写成函数） | - | `P-QUERYPARSE` |
| R2 | `ActiveSetInit(C, G)`（Alg.1 line2；§4.2 `matches them against the stored cue set`） | 每 query | `C` + 图 cue 集合 → `Z^(0)`, `S^(0)=(Z^(0),∅)` | 论文未说明 | 图 | `P-SYMFILTER`（论文未说明匹配方式，见 §6.1） |
| R3 | LLM Reasoning and Action Selection `f_select`（Eq.10） | 每步 `t`（≤T 步） | `x,H^(t),Z^(t)` → `A^(t)⊆A` | 1×/步 | - | `P-TOOLLOOP` |
| R4 | Controlled Memory Traversal `Π_a`（Eq.8/9/11） | 每步 | `Z^(t)` → `Z̃^(t+1)` | no（`the memory system executes the operator`，txt:461） | 图 | `P-GRAPHEXPAND`（Forward `Cue→Tag`/`(Cue,Tag)→Content` + Reverse `Content→(Cue,Tag)`） |
| R5 | LLM Routing and State Update `f_route`（Eq.12） | 每步 | `x,H^(t),Z̃^(t+1)` → `Z^(t+1)`, `H^(t+1)` | 1×/步 | - | `P-RERANK`（LLM 选相关 + 剪枝） |
| R6 | `STOP(x,H^(t+1))` / `C_LLM`（Alg.1 line16；§4.2 txt:511） | 每步 | `x,H^(t+1)` → 停/继续 | 1×/步 | - | `P-TOOLLOOP` |
| R7 | `AnswerLLM(x, H)`（Alg.1 line20） | 每 query 一次 | `H` → `ŷ` | 1× | - | `P-ASSEMBLE` > `P-GENERATE` |

**论文侧系统边界**：`M=(C,V,R)` 这张图 + Table 4 的 7 个 `ϕ` 算子属于**记忆系统本体**（只按结构化条件存取，txt:461-462 明说算子由 memory system 执行）；`f_select` / `f_route` / `C_LLM` / `AnswerLLM` 全部属于 **LLM/agent 侧**；`ExtractCues` / `ActiveSetInit` 归属论文没说清（Alg.1 里在循环外，既没说是 LLM 也没说是图操作）。

## 4. 步骤清单 — 代码侧

### 4.1 写入侧（离线构建，`run.py:163-205` 每 sample 一次）

| # | name（代码里的叫法） | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| w1 | `get_data`（`data/get_data.py:9`） | 每次 run 一次 | dataset JSON → `raw_text[D<i>][D<i>:<j>] = "speaker:text"` | no | 进程内 dict | `P-INTAKE`（LM 分支 `:62-63` 只保留 user 轮次，属输入过滤） |
| w2 | `rewrite_sample`→`rewrite_sentence`→`rewrite`（`agent.py:623/657/592`，`REWRITE_SYSTEM_PROMPT` `prompts.py:18-55`） | **每 session 一次** | session 原文 → `{conversation_time, sentence[{id,text,tag,origin,topic,time}], topics{}, personal_sentences[]}` | **1×/session**（一次调用同时完成 4 件事） | 落盘 `rewrite_<model>/*.json` | `P-REWRITE`（代词消解+时间归一化）+ `P-META`（每句 tag）+ `P-AGGREGATE`（topics）+ `P-EXTRACT`（personal_sentences） |
| w3 | `_normalize_sentence_ids` + `check_rewrite_json` 重试（`agent.py:575/601-619`，`schema.py:95`） | 每 session，仅 schema 失败时 | 同上 → 修正后的 JSON | 0-3× 重试 | - | 工程校验（非记忆原语） |
| w4 | `extract_keyword`→`extract_keys`（`agent.py:712/669`，`KEYWORD_SYSTEM_PROMPT` `prompts.py:69-87`） | **每 session 一次** | w2 的 `{id,text}`（`:737-743` 丢弃 tag/origin/topic/time）→ 每句 2-30 个 keyword | **1×/session** | 落盘 `keyword_<model>/*.json` | `P-META`（关键词标注） |
| w5 | `embed_sample`（`data/embed_rewrite.py:20`；`rag_utils.py:10-26`；`embeddings.py:34-36`） | 每 sample 一次 | w2 的改写句文本 + topic 文本 + **全部问题文本** → 3072 维 L2 归一化向量 | no（embedding API） | 落盘 `embedding/gpt_<model>/*.pkl` | `P-EMBED` |
| w6 | `store_raw_text`（`agent.py:864`→`system.py:240`） | 每 sample 一次 | raw_text + 句向量 + topic 向量 → `MemorySystem` 字段 | no | 进程内对象图 | `P-INTAKE`（装载） |
| w7 | `store_keyword`→`store_event_new`（`agent.py:748/772`） | 每 sample 一次（内部逐 session） | rewrite JSON + keyword JSON + raw_text + 向量 → `EpisodeEvent`（**text=原始对话行**，`:798-811`）/`Topic`（`:821`）/`PersonalEvent`（`:823-829`）/`KeyNode`+`Link`（`:849-860`）/`timeline`（`:815`） | no | 进程内对象图，**不落盘** | `P-LINK`（cue–tag–episode 边 + topic–episode 边 + 时间索引）+ `P-META`（`:847-848` 强制补 speaker 进 cue） |
| w8 | 缓存跳过（`run.py:183/189/195`） | 每 sample | 存在即复用 | - | 磁盘中间产物 | `P-PERSIST`（只持久化中间产物，不持久化图本体） |

**代码写入侧明确没有的**：`P-DEDUP`（写入侧无阈值去重）、`P-CONFLICT`（无冲突检测/覆盖/失效标记）、`P-EVICT`（无遗忘/压缩/剪枝）、`P-ANNINDEX`（无 Faiss/HNSW，检索是 numpy 全量点积）。

### 4.2 检索侧（`agent.py:450 answer_question`，每问题一次，10 线程并发）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| r1 | `extract_question_keys`（`agent.py:566`，`prompts.py:206-219`） | 每 question | `x` → `{keywords[{id,alternatives}], question_time}` | **1×** | - | `P-QUERYPARSE` |
| r2 | `evaluate_relations_over_graph` + `match_query_key_to_graph_keys`（`controller.py:263/214`） | 每 question | cue → 归一化/子集/Jaccard≥0.6 匹配 KeyNode → `key_to_values` → `full_matches`/`partial_matches` | no | 图 | `P-SYMFILTER` > `P-GRAPHEXPAND`（key→event 一跳） |
| r3 | ~`answer_question_with_time` / `_lm`（`agent.py:64/111`；`system.py:137-147`；`controller.py:191-197`） | 条件：`question_time` 非空 | 日期区间 → timeline 命中事件 | no | 图 timeline | `P-SYMFILTER`（时间过滤）；命中够少（<50 / <20）则**直接短路成最终证据包**，跳过 r4-r9 |
| r4 | 主路径候选收集 + `matched_keys>=2` 过滤（`agent.py:482-491`） | 每 question（非时间短路时） | full/partial → 候选池 | no | 图 | `P-SYMFILTER` |
| r5 | ~`topk_answers_by_similarity` K1=80（`agent.py:495-498`，`utils.py:47/72`） | 条件：候选 > 80 | 问题向量 · 句向量（dot）→ ≤80 | no | 向量（内存） | `P-DENSE` |
| r6 | 前缀去重（`agent.py:505-518`） | 每 question | 同 origin 前缀只留第一条 | no | - | `P-DEDUP` |
| r7 | `select_topic`（`agent.py:236/520`，`TOPIC_K=8`） | 每 question（非时间短路时） | 问题向量 × topic 向量 → top-8 topic 文本 | no | 向量 | `P-DENSE`（独立一路，不与 r5/r8 合并） |
| r8 | ~`select_finegrained_sentence`（`agent.py:244/523`，`ANSWER_SORT_PROMPT2` `prompts.py:112-116`） | 条件：去重后 > 20 | 候选 → LLM listwise 选 ≤20 个 id | **1×** | - | `P-RERANK` |
| r8' | ~~`select_finegrained_sentence_sort`（`agent.py:309/524`）~~ | **主路径不可达**（`:315` 条件恒假，见 C26） | — | 0 | - | — （仅在 LM 时间分支 `agent.py:178` 作为首选精排生效） |
| r9 | ~`select_key_tag`（`agent.py:392/536`，`prompts.py:6-13`） | 条件：某 cue 的 tag 数 > 15 | 每个高扇出 cue → LLM 给 tag 打分，取前 10；≥0.7 的 tag 直接 `event_by_tag` 预取原文 | **0..N×**（每高扇出 cue 一次） | 图 | `P-RERANK` + `P-GRAPHEXPAND`（预取） |
| r10 | `ans_input` 组装（`agent.py:539-548`） | 每 question | 五段证据 → 一条 user message | no | - | `P-ASSEMBLE` |
| r11 | `chat_with_tools_once` 工具循环（`llm/controller.py:92-234`） | 每 question，≤8 轮 / ≤50 次工具调用 | messages → `mode:answer` 或 `tool_calls` | **1×/轮**（同一次调用里同时给出 mode 与 tool_calls） | - | `P-TOOLLOOP` |
| r12 | `ToolBridge.call` → 7 个图查询（`tools.py:162-192`） | 每次 tool_call | JSON 参数 → 结果字符串 | no | 图 | `P-GRAPHEXPAND`（`edges_by_tag`/`query_topic_events`/`query_event_keywords`）+ `P-SYMFILTER`（`query_conversation_time`/`query_personal_information`/`query_personal_aspect`）+ `P-ASSEMBLE`（`query_event_context` 取前后轮） |
| r13 | ~`event_by_tag` 内部重排（`controller.py:29-48`，`RERANK_LIMIT=20`） | 条件：某 cue-tag 下事件 > 20 | 向量点积取前 20 | no（**embedding，不是 LLM**） | 向量 | `P-DENSE` |
| r14 | ~`query_event_keywords_single` 内部 tag 打分（`controller.py:54-95`） | 条件：某 cue 的 tag 数 > 15 且本轮未问过 | LLM 打分取前 10 | **1×** | - | `P-RERANK` |
| r15 | 工具结果原样回灌 messages（`controller.py:206-223`） | 每轮 | tool 结果 → `role:"tool"` 消息，**只增不删** | no | - | `P-ASSEMBLE`（无剪枝） |
| r16 | 第 8 轮强制收尾（`controller.py:140-143`） | 条件：`round_id == MAX_ROUNDS` | 换 `ANSWER_SYSTEM_PROMPT_FINAL` + 追加 final-round user 消息 | - | - | `P-TOOLLOOP` |
| r17 | 最终 answer JSON（`controller.py:178-181/234`） | 每 question | messages → `{answer, supports, confidence}` | （即 r11 的那一次调用） | - | `P-GENERATE` |
| r18 | `get_support_origin`（`system.py:372-376`） | 每 question | evidence id → `dia_id` | no | 图 | 评测侧，边界外 |

**代码侧系统边界**：`memory/system.py`（对象图 + 7 个查询方法）+ `memory/controller.py`（图匹配、时间展开、工具内重排）+ `agent/tools.py::ToolBridge`（分发）= 记忆系统本体；`agent/agent.py`（问题理解 r1、初始证据包 r2-r10）+ `llm/controller.py`（工具循环 r11-r17）+ `prompts/` = agent/backbone 侧；`eval/` = 评测侧。注意 **r2-r10 这一整段"初始证据包"住在 agent 侧，却承担了论文 `ActiveSetInit` 的职责**，所以代码的实际边界比论文更靠 agent 一侧。

## 5. 论文↔代码分歧

| # | 分歧 | 分类 | 论文证据 | 代码证据 |
|---|---|---|---|---|
| D1 | episode 节点存的文本：论文是 `R_LLM` 改写后的文本，代码是未消解代词的原始对话行（改写句只用于算向量与抽标签，建图时即被丢弃） | 两边都有但行为不同 | txt:1281-1285（Eq.18 先 rewrite 再 segment，episodic unit = 处理后文本） | `agent.py:796`（向量取改写句）/`:798-803`（text 取 raw_text）/`:811`；`store_event_new` 全程未读 `ee.get("text")` |
| D2 | 五个抽取函数 vs 2 个 prompt：论文形式化为 `R/T/K/S/A` 五个独立函数；代码合并为 rewrite（覆盖 R+T+A+S）+ keyword（K）两次调用/每 session | 两边都有但行为不同 | Eq.18-21 @ txt:1283/1289/1302/1313 | `prompts.py:18-55`（一个 schema 四样输出）+ `prompts.py:69-87`；`agent.py:646-652`/`:722-744` 逐 session |
| D3 | topic 的输入：论文 `A_LLM({e_i})` 对已切好的 episode 集合摘要；代码 topics 直接由 session 原文一次生成，且是 session 级而非全样本级 | 两边都有但行为不同 | txt:1311-1313 | `prompts.py:27`；`agent.py:593-597`；`agent.py:821`/`system.py:263-279`（tid 加 `D{session_id}:` 前缀） |
| D4 | 单轮工具调用上限：论文 D.4 写 `up to 10 tool invocations per turn`；代码只有跨全轮的 `MAX_TOOL_CALLS=50`，无单轮上限 | 两边都有但参数不同 | txt:1696-1697 | `config.py:67`；`controller.py:187-190`；`prompts.py:157`（prompt 只说"尽可能多调"，无数量） |
| D5 | 轮数上限：论文 `at most 8 turns per query` 与代码 `MAX_ROUNDS=8` **一致**（文档双方都没点明这条是对上的） | 两边都有且一致 | txt:1696 | `config.py:66`；`controller.py:104,137` |
| D6 | `f_route` 剪枝：论文是显式的候选筛选步骤，代码无任何剪枝函数，工具输出全部原样累积 | paper-only（论文写了代码没实现） | Eq.12 @ txt:494-498；txt:489-493 | `controller.py:206-223`（只增不删）；全文件无过滤逻辑 |
| D7 | `ActiveSetInit`：论文一行伪代码；代码是"图文本匹配 → K1=80 向量粗排 → 前缀去重 → 一路 LLM listwise 精排到 20 → 独立 topic 向量 top-8 → 条件触发的 LLM tag 打分与证据预取" | code-only（代码有论文没写） | txt:1331；txt:408-409 | `agent.py:454/495-498/505-518/520/523/536` |
| D8 | 向量检索：论文对 MRAgent **完全没有** embedding/向量成分（embedding 只出现在 baseline 描述里）；代码有三处向量检索（K1 粗排、topic top-8、`event_by_tag` 内部重排）+ 一个 3072 维 embedding 模型 | code-only | txt:36/134/152/1626-1641 全是 baseline | `embeddings.py:36`；`agent.py:497/520`；`controller.py:39-40` |
| D9 | 工具命名与签名：论文 Table 4 叫 `query tag events`（`ϕ(c,g)→e`）；代码叫 `edges_by_tag`，且**必填**一个 `note`（8-80 字符的"决策备注"）参数——论文的算子签名里没有这个东西 | 两边都有但行为不同 | txt:1248/1259 | `tools.py:8`（名）/`:21-28`（`note` required） |
| D10 | timeline：论文说 episodic 沿统一时间线组织以便"在重构过程中施加时间约束"；代码的 timeline **没有作为工具暴露给 LLM**，只在工具循环开始前的初始检索快通道里用一次 | 两边都有但行为不同 | txt:296-299；txt:1360-1372（7 个工具里没有时间检索工具） | `system.py:118/132-147`；`agent.py:65/113`（唯二调用点）；`tools.py:4-155` 无对应工具 |
| D11 | LM 数据集只存 user 侧发言，assistant 轮次在数据加载和建图两处被丢弃 | code-only | 论文 D.1（txt:1610-1623）无此说明 | `get_data.py:62-63`；`agent.py:806-810` |
| D12 | 按题型改写问题 / 换答题 prompt（locomo category 2/3、LM 专用 prompt、category-3 强制换 prompt） | code-only | 论文只给一份 QA prompt（txt:1898-1917） | `agent.py:550-558`；`prompts.py:167-182`；`controller.py:125-126` |
| D13 | 说话人被强制补进每句的 cue 集合 | code-only | 论文 `K_LLM` 只说抽 entities/attributes/salient descriptors（txt:1293-1294） | `agent.py:847-848` |
| D14 | LM 温度分支：`select_finegrained_sentence` 的第二路精排额外被 `config.MODEL_NAME == "gemini"` 门控 | code-only | 论文无对应 | `agent.py:180` |
| D15 | 论文 Table 6 只报告 5 个工具的证据覆盖率，`query event keywords` / `query personal information` 缺席；代码这两个工具是启用的（且 `query_event_keywords` 内部还会额外调 LLM） | 两边都有但行为不同 | txt:1848-1857 | `tools.py:51/83`；`controller.py:54-95` |

## 6. 新造的 primitive 标签

**none。** 全部步骤都能落进种子词表：论文侧的 `STOP`/`C_LLM` 判停与代码侧的 8 轮循环控制统一归 `P-TOOLLOOP`（其定义"agent工具循环/多跳控制"已覆盖终止判断）；代码里 `select_topic` 那条独立向量通道归 `P-DENSE`，它与主证据在 `ans_input` 里只是并列字段、没有做任何加权或 RRF，所以**不**记 `P-FUSE`；`agent.py:525-533` 那个形式上像 `P-FUSE` 的并集因为第二路不可达而是 no-op，同样不计。

## 7. 复核统计

| 判定 | 条数 |
|---|---|
| ✓ 属实 | 85 |
| ✗ 不实 | 3 |
| ◐ 部分属实/需加限定 | 22 |
| ? 无法核实 | 2 |
| **合计** | **112** |

分文档：`paper-architecture.md` 60 条（✓47 / ✗1 / ◐11 / ?1）；`code-architecture.md` 52 条（✓38 / ✗2 / ◐11 / ?1）。

三条 ✗：C26（"两路 LLM 精排取并集"运行时不成立）、C52（"怎么省论文完全没写"被 Appendix E 证伪）、P53（"原文自己标注这是简化摘要"无据）。

### 附：本次复核顺带发现的、两份文档都没记的代码问题

1. **`check_key_json` 参数不匹配**：`agent.py:698` 调用 `json_scheme.check_key_json(keys_out, text, replace=True)`，而 `prompts/schema.py:144` 的签名是 `def check_key_json(text, ref_obj=None)` —— 关键词抽取第 3 次重试仍失败时会抛 `TypeError`。
2. **LM 时间分支的无效计算**：`agent.py:192-193` 调用 `select_key_tag`（可能触发多次 LLM 调用）算出 `key_candidates` / `key_tag_sentences`，但 `:195-199` 构造的 `ans_input` 只有 `{question, key_sentences, current_date}`，两者被直接丢弃。
3. **工具循环的空转轮**：`llm/controller.py:229-232`，模型既没给 `mode:answer` 也没发 `tool_calls` 时走 `continue`，会白白消耗一轮 `MAX_ROUNDS` 预算。

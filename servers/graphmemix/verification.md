# graphmemix 架构文档复核报告

> 复核日期 2026-09-05；论文源 `Li-2026-GraphMemix-Query-Aware-Evidence-Forests-for-Long-Term-Multimodal-Agent-Memory.txt`（2661 行）；代码源 `graphmemix` @ `d0ea01d`（唯一一次提交，工作区干净）。
> 复核对象：`servers/graphmemix/paper-architecture.md`（100 行）、`servers/graphmemix/code-architecture.md`（113 行）。该目录下没有 .py 适配层，只有这两份 .md。
> 证据格式：论文写 `txt:NNN`（我亲眼 `grep -n`/`sed -n` 看到的行号）；代码写 `file.py:NNN`（我亲眼 `sed -n` 打开过那一行）。

## 1. 总评

两份文档的整体质量很高，属于我复核过的少数"绝大多数行号能对上、否定式断言基本站得住"的档次；代码侧对 Kruskal 求解器、ECV 六角色、超参数值、`--edge-only` 契约等关键点的引用几乎逐条精确（`score_graphmemix_ecv.py:30-31`、`:35-42`、`:533`、`:552`，`probe_graphmemix_pcsf.py:249`，`evaluate_graphmemix_exact_pruning.py:62`，`build_memix_checkpoints.py:41`，`run_memix_answers_from_retrieval.py:136,753,773,792`，`tests/test_score_graphmemix_ecv.py:63` 全部一字不差）。

最严重的问题有三类。**第一类是事实错误**：(a) 论文文档反复把 §1 Introduction 里那句 "For any fixed node set, its optimal maximum-weight forest is obtained exactly by Kruskal's algorithm"（txt:60-61）称作"摘要原话"，但摘要（txt:12-20）通篇没有 Kruskal 二字，据此展开的"摘要表述强度 vs 正文细节落差"整段论证的锚点是错的；(b) 论文文档把"锚点数 |A_q|=10"当成论文给出的超参写进"我没搞清楚"一节，但全文 `grep -ci anchor` 42 处没有任何一处给出锚点集合的规模，这个 10 是从代码 `configs/release/graphmemix.json:33` 倒灌回论文侧的；(c) 代码文档说 ATM-Bench 的 6.23 条 Fixed Edges 是"四个数据集里第二高的"，Table 6 实为 Mem-Gallery 7.34 > H2HMem 6.75 > ATM 6.23 > MemEye 6.07，ATM 是第三高；(d) 代码文档把 Kruskal 实现定位到 `probe_graphmemix_pcsf.py:203-215`，那一段是 1-swap 的初始化和爬山循环，真正的 Kruskal 在 `forest()` 内部的 188-200 行——两个行号区间事实上被写反了。

**第二类是被证伪的否定式断言**：论文文档从多处证据"合理推断写入阶段没有生成式 LLM 调用"，但 Appendix A.1（txt:1826-1828）与 Table 8（txt:1820）白纸黑字写着 H2HMem 的 1,300 张图没有原生 caption、作者用 Qwen/Qwen3-VL-8B-Instruct 离线生成了一份冻结 caption sidecar——这就是写入侧的生成式 LLM 调用；代码侧 `run_graphmemix_release.py:118-119` 正是消费这份 sidecar，而生成它的脚本全仓库不存在。代码文档架构图上"写入侧：一次性 digest，全程零 LLM 调用"这句话对仓库内 ingest 代码成立，对整条流水线不成立。

**第三类是行号漂移**：`run_graphmemix_release.py` 的两处 stage 引用整体偏移 4~10 行（文档写 107-116/124-129，实为 111-120/134-139），`concrete_memix.py` 的多个函数区间尾部被截短（`_adapt_memory` 写 397-472、实为 397-499），`_save_checkpoint` 被错标在 365-396（实为 875-903）。这些不影响结论，但按判定规则都记 ◐。

关于本次任务特别点名的问题：**`vendor/memix-core` 的硬依赖属实，源码确实不在仓库里，README 和 docs 也确实没有给任何获取方式**（详见 §5-A）。

## 2. 逐条核对表

### 2.1 paper-architecture.md

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| P1 | 抬头 | "arXiv:2608.26983v1（MemoraX AI Research 技术报告）"；"本地纯文本版全文（2661 行）"；作者 Li/Wang/Li/Hao/Peng | ✓ | txt:4 `arXiv:2608.26983v1 [cs.AI] 27 Aug 2026`；txt:6-8 作者与单位；`wc -l` = 2661 | — |
| P2 | §1 | 目标 = 节点值总和 − 边不确定性成本 − 开辟独立证据链成本（Eq.2、Eq.11） | ✓ | Eq.2 @txt:545（上文 txt:541-544）；Eq.11 @txt:998（txt:983-997） | — |
| P3 | §1 / §6 | "对固定的节点集合，这个最大权森林可以用 Kruskal 算法精确求出（**摘要原话**）"；§6 又写"**摘要**这句话单独读容易被误解" | ✗ | 该句在 txt:60-61，属 **§1 Introduction**；Abstract 为 txt:12-20，全段无 "Kruskal"（`grep -n Kruskal` 全文命中 61/365/1048/1074/1083/1113/1465/1655，无一在 12-20 区间） | 引用锚点错误。摘要真正的对应表述只有 txt:18 的 "forest optimization, which jointly selects a forest-format memory context"，并未宣称精确性；§6 第一条"摘要表述强度与正文落差"的论证前提因此不成立（落差存在于 §1 与 §3.5 之间） |
| P4 | §1 | 选点是确定性 1-swap 局部搜索；再在锚定候选范围内穷举子集精确求解变基数版本（§3.5, Eq.13） | ✓ | txt:1080-1090（"deterministic two-stage solver…initializes from the top-K node utilities, evaluates one selected–unselected swap at a time"）；Eq.13 @txt:1111 | — |
| P5 | §2 | §3.1 把用户历史记为固定集合 V={e_i}（Eq.1），没有描述 e_i 怎么产生/写入 | ✓ | txt:520-533，Eq.1 @txt:534；全节只定义 V、q、Π、M，无写入过程 | — |
| P6 | §2 | "§4.3 和 Appendix A.3 说 'construct the memory representation for every canonical memory once'" | ◐ | 该引文只在 A.3：txt:1888-1889；§4.3（txt:1328-1332）的对应说法是 "digesting the entire history once and answering every question once" | 双重出处的归属不准，引文本身准确 |
| P7 | §2 | Figure 3(a) 把 digest 和 answer 分开单独计时 | ✓ | txt:1076-1077 图注 "(a) Estimated time to digest all 11,034 memories once and answer all 1,044 questions once"；Figure 5 同构（txt:2161-2164） | — |
| P8 | §2 | §4.1 "We use the frozen gme-Qwen2-VL-2B-Instruct encoder to produce 1,536-dimensional multimodal embeddings" | ✓ | txt:1255-1256 逐字 | — |
| P9 | §2 | "可以合理推断**写入阶段没有生成式 LLM 调用**——但论文没有哪一句话直接明确写'写入时零 LLM 调用'" | ✗ | A.1 txt:1826-1828："The release provides no image captions. We therefore generate a frozen caption sidecar for all 1,300 assets with Qwen/Qwen3-VL-8B-Instruct, temperature 0, a 32,768-token context limit…"；Table 8 的 Caption source 列 txt:1820 = "Qwen3-VL-8B generated" | **推断被论文正文证伪**。H2HMem 的写入侧存在一次覆盖全部 1,300 个资产的生成式 LLM captioning。四个数据集里 ATM 用 release 自带派生字段（txt:1752-1753，标注由 Qwen3-VL-2B 生成，属数据集发布方）、Mem-Gallery/MemEye 用 native captions（txt:1800/1810），只有 H2HMem 是 GraphMemix 自己生成的 |
| P10 | §2 | 摘要有 "avoids substantial lifecycle cost" 措辞 | ✓ | txt:18 | — |
| P11 | §2 | 论文在 §1、§2.1 反复批评 MIRIX/SGM/A-MEM/AUGUSTUS/M2A 的 question-agnostic 路线 | ✓ | §1 txt:40-46；§2.1 txt:70-76、txt:490-492 | — |
| P12 | §2 | discovery graph G_disc=(V, E_schema ∪ E_sem) 本身不含 q；只有取 Top-L 种子 + H 跳扩展才是 query 相关（§3.3） | ✓ | Eq.4 @txt:569（E_schema/E_sem 定义无 q）；txt:580-592 + Eq.5 @txt:590 | — |
| P13 | §2 | A.1 列出 ATM 三种 schema 关系：event_bridge（1 分钟–1 小时、5 公里内、每条最多 2 个近邻）、same_record（强引用/事件日期类别/归一化主题临近）、record_grounding（邮件↔其提到日期的媒体，地点或内容也吻合） | ✓ | txt:1754（"three relation types. event_bridge links complementary media captured 1 minute–1 hour apart and within 5 km, retaining at most two local neighbors per"）、txt:1755（same_record）、txt:1756-1757（record_grounding） | 逐条对得上，包括"最多 2 个近邻" |
| P14 | §2 | Mem-Gallery/MemEye 用 same_round + consecutive_turn；H2HMem 只用 consecutive_turn | ✓ | Mem-Gallery txt:1764-1765；MemEye txt:1823-1824；H2HMem txt:1833-1835（"it does not expose the paired native-round field required by same_round"） | 文档只在正文里提了 Mem-Gallery/MemEye/H2HMem，与论文一致 |
| P15 | §2 | "语义边只在 Eq.4 给了数学定义（互为 top-k 近邻），没有说明用什么编码器算相似度" | ◐ | Eq.4 @txt:569 ✓；但 Eq.3 上文 txt:559 已定义 "where h is a shared multimodal encoder"，§4.1 txt:1257 又给了 k=8 与同一个 frozen gme 编码器 | "shared encoder h" 已经把语义边与检索绑定在同一个编码器上，只是没有在 §3.3 重新点名 gme；断言需加限定 |
| P16 | §2 | "论文正文没有一句明确写'每条记忆的原始像素/文字被无损保留、可以在回答阶段原样发给 reader'" | ◐ | A.4 "Reader serialization"（txt:2203-2207）："For each selected memory, the reader receives a labeled text block containing evidence rank, memory ID, source ID, modality, and cleaned canonical text, followed by the selected image or uniformly sampled video frames when the selected action is visual" | 这已经很接近明确陈述（原图/抽帧直接进 reader），只是用了 "cleaned canonical text" 而非"无损" |
| P17 | §3 | 触发时机：每个问题 q 到来后完整走一遍 §3.3–3.5；Π(q,V;K) 以 q 为显式参数 | ✓ | Eq.1 @txt:534；txt:527-533 | 文档自称"论文没有讨论跨问题缓存"——全文无相关表述，属实 |
| P18 | §3.1 | Multi-view 检索 s_i(q)=max_u sim(h(q),h(u))（Eq.3），Top-L（L=24）为种子 R_q^(L) | ✓ | Eq.3 @txt:558（txt:552-559）；L=24 @txt:1256 | — |
| P19 | §3.2 | H=1 跳可达扩展，"检索序 + 关系扩展序"取前 M=48 组成 C_q（Eq.4-5） | ✓ | txt:588-593（"collect nodes reachable within H hops and retain at most M candidates"、"The ranking combines retrieval order and relation-expansion order"）；H=1/M=48 @txt:1256-1257 | — |
| P20 | §3.3 | listwise node verifier 一次读入 q 与全部 C_q，输出 v_i∈[0,5]；p_i=σ(τ[αs_i+(1−α)ṽ_i−δ])，ṽ=v/5；(α,τ,δ)=(0.8,5.2,0.7)（Eq.14）；等价形式 σ(4.2s+0.2v−3.6)（Eq.15） | ✓ | txt:594-599 + Eq.6 @txt:609；Eq.14 @txt:1871（txt:1864-1870）；ṽ=v/5 @txt:1873；Eq.15 @txt:1879 | 数值全部逐字对上 |
| P21 | §3.3 | "四个数据集、两个 backbone 都不重新调" | ✓ | txt:1880 "We do not retune these values by benchmark or reader backbone." | — |
| P22 | §3.4 | 先确定性选高置信锚点 A_q（不用 verifier 分数/ECV 结果/gold，只按冻结检索序，A.2 "Anchor-set construction"）；只看锚点↔候选的 schema 边 E_q^elig；一次 listwise 调用给 best anchor + s^inc∈[0,5] + 六选一角色；只留正分且属前三角色的边构成 G_q^trust；w_ai=w^schema·s^inc/s_max，c_ai=−log w_ai（Eq.9） | ✓ | A.2 txt:1881-1885；Eq.7 @txt:625（txt:617-624）；txt:626-632（一次 listwise、六角色逐字、"Only the best anchor edge with a positive score and one of the first three roles is retained"）；Eq.8 @txt:639；Eq.9 @txt:650（txt:634-649） | 本条是全文档信息密度最高也最准确的一条 |
| P23 | §3.4 | "语义边不参与 ECV" | ✓ | Eq.7 @txt:625 把 E_q^elig 限定为 `(a,i) ∈ E_schema`；A.4 txt:2175-2176 的 eligible_anchor_relations 也只带 "schema-relation type" | 否定式断言成立 |
| P24 | §3.5 | 两阶段确定性求解：1-swap 从 Top-K 起步、每步用 Kruskal 精确重算最大权森林；第二阶段在冻结提案 S̄_q 内穷举全部非空子集精确求解（Eq.13）；"globally optimal over all nonempty subsets of S̄_q" 而非在 C_q(48) 内全局最优 | ✓ | txt:1080-1090；Eq.13 @txt:1111；txt:1113-1115（"For each subset, Kruskal applied to positive-gain edges gives F_S* exactly"、"globally optimal over all nonempty subsets of S̄_q"） | K=10 @txt:1257；m(S,F)=|S|−|F| 与 B_e=κ−λc_e 见 txt:1000-1008（Eq.12 @txt:1008） |
| P25 | §3.5 / §6 | "这个限定词在**摘要**里被省略了，但在 §3.5 正文写得很清楚" | ◐ | 摘要（txt:12-20）根本没有提最优性，因此谈不上"省略限定词"；被省略限定词的是 §1 txt:58-61 | 与 P3 同源的锚点错误，结论方向对、出处错 |
| P26 | §3 | A.5 Evidence Serialization：分量取效用最高节点为根、按根效用给分量排序、分量内 BFS、打平先按节点效用再按原始检索序；最多 K 条 | ✓ | txt:2214-2218 逐字（"Ties are resolved by node utility and then by the original retrieval order"、"supplies the reader with at most K canonical multimodal memories"） | — |
| P27 | §3 | reader M 与 node verifier/ECV 是同一模型（A.2 Model assignment：Qwen3-VL 设置三者都用 Qwen/Qwen3-VL-8B-Instruct，Gemma 4 设置都用 google/gemma-4-12B-it） | ✓ | txt:1846-1848 逐字 | — |
| P28 | §3 | Table 7：随机 100 题子集上 Two-Call 宏平均 61.25 > Joint 59.25 | ✓ | txt:1443 `59.25 52.94 61.25 55.94`；表头 Joint/Two-Call @txt:1408/1410；表注 txt:1445-1446 "random 100-question held-out subset of each benchmark" | §4.4.4 txt:1646 亦称提升 2.00 / 3.00 点，与 61.25−59.25=2.00 一致 |
| P29 | §3 | 佐证 README 的 "Separated evidence verification" | ✓ | `README.md:30-32` | — |
| P30 | §3 / §4 图 | 每题两次 LLM 调用（node verifier + ECV），reader 一次 | ◐ | 主线成立（§4.1 txt:1314 "The node verifier and ECV each make one listwise call"）；但 A.4 txt:1906-1908 规定：问题图若没有 dataset caption，"the verifier backbone generates one with the following prompt"——这是同一 backbone 的**第三次**（按图数可能多次）query-caption 调用 | 计数类断言需加"条件触发的 query-caption 调用未计入" |
| P31 | §5 | "候选图规模 M=48、**锚点数 \|A_q\|=10** 这些超参是怎么调出来的" | ✗ | `grep -ci anchor` 全文 42 处（含 §3.4 txt:615-632、A.2 txt:1860/1881-1885、A.4 prompt txt:2173-2177/2593-2616 等），**没有任何一处给出锚点集合规模**；A.2 "Anchor-set construction"（txt:1881-1885）只说构造方式（去重、保序、不用 verifier/ECV/gold）不说数量。唯一同时出现 anchor 与 10 的是 txt:1452，但那是 Table 4 用 "source top-10" 划分 gold 证据可达性，与 A_q 无关 | \|A_q\|=10 只在代码里（`configs/release/graphmemix.json:33` `"anchor_count": 10`、`scripts/score_graphmemix_ecv.py:272` 默认 10）。把它写成论文超参属于把代码数值倒灌进论文侧 |
| P32 | §5 | "'execute in parallel'：Appendix A.2 说 node verifier 和 ECV 'can therefore execute in parallel'，但没说是不是真并发" | ◐ | A.2 txt:1860 确实是带 "can" 的弱表述 ✓；但主文两处是**无条件断言**：§4.1 txt:1314 "The node verifier and ECV each make one listwise call and execute in parallel."；§4.4.4 txt:1647 "The two verifiers have no serial dependency and execute in parallel" | 只引 A.2 的弱表述会低估论文与代码的分歧强度（见 §5-D6） |
| P33 | §5 | "关系图是否支持增量更新：论文没有讨论新记忆持续到来时怎么维护" | ✓ | `grep -i "incremental update|incrementally|online update|streaming|new memories arrive|maintain the graph|rebuild"` 全文 0 命中；§4.3 txt:1328-1332 与 A.3 txt:1887-1893 都是"一次性 digest + 依次答题"的批处理定义 | 否定式断言，已实际证伪未果 |
| P34 | §6 | "w^schema 的上标是'专属 schema 类边'还是'不同 schema 类型各有上限'，论文没有明确区分；**正文和附录都没有专门讨论**" | ✗ | Eq.9 下文 txt:641 明写 "where w_ai^schema is a schema-specific reliability ceiling"；§4.1 txt:1258 "We set the maximum schema reliability to **0.99**"（单值）；§4.4.3 txt:1470-1472 "The fixed variant assigns every eligible explicit schema edge the **same** query-independent reliability of 0.99" | 论文其实在实现层把它钉死成单一全局 0.99，"正文和附录都没有专门讨论"不成立；这三处证据也直接削弱了代码文档 §6 第 2 条把它当作"分歧"的定性（见 C52） |

### 2.2 code-architecture.md

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| C1 | 抬头 | 官方 `ligeng0197/graphmemix`，克隆时 `HEAD=d0ea01d` | ✓ | `git rev-parse --short HEAD` → `d0ea01d`（仓库只有这一次提交）；`pyproject.toml` Source = https://github.com/ligeng0197/graphmemix | — |
| C2 | §1 | `ConcreteMemixMethod` 构造函数硬性要求外部私有仓库 `vendor/memix-core`（concrete_memix.py:48-52,268） | ✓ | `concrete_memix.py:48-52`（`_load_memix_core`；50 行拼 `<repo>/scripts/QA_Agent/MMRAG/memix_memory.py`；51-52 缺失即 `raise RuntimeError`）；`:219` 默认 `memix_repo="vendor/memix-core"`；`:268` `self.core = _load_memix_core(self.memix_repo)` 位于 `__init__` 内 | 行号全部精确。详见 §5-A 的专项确认 |
| C3 | §2 | 9 个 stage：checkpoint→priors→relations→node→ecv→select→prune→reader→judge（run_graphmemix_release.py:23） | ✓ | `run_graphmemix_release.py:23` `STAGES = ("checkpoint", "priors", "relations", "node", "ecv", "select", "prune", "reader", "judge")` | 精确 |
| C4 | §2 | checkpoint stage 在 run_graphmemix_release.py:107-116 | ◐ | 实际 `run_graphmemix_release.py:111-120`（111 `if enabled("checkpoint"):` … 120 `runner.run(command)`）；107 是空行、108-109 是 `def enabled` | 行号漂移 4 行 |
| C5 | §2 | "对每个 benchmark/**backbone** 组合一次性把整个 archive 编码完" | ◐ | checkpoint 产物路径与 backbone 无关：`configs/release/graphmemix.json:53` `"checkpoint": "checkpoints/{dataset}"`，`run_graphmemix_release.py:84` `artifact_path(layout,"checkpoint",args.artifact_root,args.dataset)`；只有 `run_root`（:93）才带 backbone | 编码是 **per-dataset** 且跨 backbone 复用；priors 同理（`source_priors/{dataset}.jsonl`，:85）。"每个 backbone 组合都编码一次"不成立 |
| C6 | §2 | `_adapt_memory`（concrete_memix.py:397-472） | ◐ | 函数实为 `concrete_memix.py:397-499`（499 行 `return record, units`） | 区间尾部截短 27 行 |
| C7 | §2 | 把 `metadata.derived` 里数据集**自带**的派生字段（短摘要/caption/OCR/地点/tags）拼成文本，不是 GraphMemix 自己生成（concrete_memix.py:420-441） | ✓ | `concrete_memix.py:416-424` 的 `labels` 元组（Short Summary/Summary/Caption/Short Caption/OCR/Location/City）、425-428 取值、429-435 `image_captions`、436-438 `tags`；`_visible_derived` 只读 `metadata["derived"]`（:75-79） | 论文 A.1 txt:1752-1753 亦证实 ATM 的派生字段来自 release（由 Qwen3-VL-2B 生成、随包分发） |
| C8 | §2 | 原始图片/视频路径单独存 `image_path`/`video_path`，`content` 整份保留（concrete_memix.py:441-462） | ◐ | record 字典在 `concrete_memix.py:456-465`：`image_path` @460、`video_path` @461、`"content": [dict(part) for part in memory.get("content", [])]` @463 | 引用区间没盖住 `content`（463），结论本身正确 |
| C9 | §2 | "每条记忆切出多个 embedding unit：**文本一份**、每张图一份、视频每帧一份，可选再切原子文本句子（concrete_memix.py:453-472）" | ◐ | units 构造在 `concrete_memix.py:466-498`：467-471 每图一份、472-487 视频每帧一份、**488-489 `if not units: units.append({...})`** —— 纯文本 unit 只是"没有任何媒体 unit 时"的兜底，图像/视频记忆**不会**额外产生一份纯文本 unit（文本被塞进每个媒体 unit 的 `text` 字段，:469/:483） | 机制描述不准；区间 453-472 也起点偏早（453-455 是 metadata 字段） |
| C10 | §2 | `media_atomic_limit` 生产配置默认关闭 | ✓ | 构造函数默认 `media_atomic_limit: int = 0`（`concrete_memix.py:228`）；`build_memix_checkpoints.py:41-52` 构造 `ConcreteMemixMethod` 时不传该参数；`configs/release/graphmemix.json` 无该键 | 关闭时 `_atomic_text_chunks` 直接返回 `[]`（`concrete_memix.py:89-91`） |
| C11 | §2 | 向量存 FAISS Flat-IP，按 context 分文件落盘为 `state.json` + `index-*.faiss`（`_flush_pending`/`_save_checkpoint`，concrete_memix.py:365-396） | ◐ | `_flush_pending` = `concrete_memix.py:365-382` ✓（370 `encode_units`、373 `index.add`、382 `_save_checkpoint()`）；但 **`_save_checkpoint` 在 875-903**（883 `index-{version:08d}.faiss`、896 `state.json`），不在 365-396；365-396 的后半是 `_canonical_modality`(384-395) | 落盘结论正确，`_save_checkpoint` 行号错 |
| C12 | §2 | "整条 ingest 路径（`_ingest`→`_adapt_memory`→`_flush_pending`）只出现 embedding 调用，没有一次 chat/completion 调用" | ✓ | `concrete_memix.py:337-363` / `397-499` / `365-382` 内无任何 `.complete(`；唯一的 caption 生成（`CAPTION_PROMPT`，:618）位于 `_query_image_caption`(590-630)，只在 query 侧；`build_memix_checkpoints.py:19-21` 的 `UnusedAnswerModel.complete` 一旦被调用直接抛错，checkpoint stage 实跑即可证否 | 否定式断言，对**仓库内 ingest 代码**成立 |
| C13 | §2/§4 图 | 架构图子图标题 "写入侧：一次性 digest，**全程零 LLM 调用**" | ◐ | 仓库内 ingest 成立（见 C12）；但整条流水线对 h2hmem 依赖一份 LLM 生成的 caption sidecar：`run_graphmemix_release.py:118-119` `if args.dataset == "h2hmem": command.extend(["--caption-sidecar", str(caption_sidecar)])`，路径 `configs/release/graphmemix.json:56` `"caption_sidecar": "captions/{dataset}.jsonl"`；`BundleReader` 只**读**它（`reader.py:34,44-45`），**全仓库没有生成该 sidecar 的脚本**（`grep -rn caption_sidecar` 20 处全是消费方）；论文 txt:1826-1828 说明它由 Qwen/Qwen3-VL-8B-Instruct 生成 | "零 LLM"要加限定："在本仓库可见的 ingest 代码路径内零 LLM；h2hmem 的写入侧依赖一份仓库外用 LLM 生成的冻结 caption" |
| C14 | §2 | 关系图脚本 `build_graphmemix_relation_store.py` 不依赖 memix-core | ✓ | 该文件 import 只有 argparse/datetime/json/math/time/collections/pathlib/typing/numpy（:11-22），以及函数内惰性 `import faiss`（:210,:227）；无任何 `mm_memory_bench` 或 `self.core` | — |
| C15 | §2 | schema 边纯读 metadata：同 `metadata.native_round_id` → `same_round`；同 `session_id` 内按 `sequence` 相邻 → `consecutive_turn`（`explicit_edges`，build_graphmemix_relation_store.py:70-101） | ✓ | `build_graphmemix_relation_store.py:70-104`：:91 读 `metadata.native_round_id`、:99 `add(left,right,"same_round")`、:90 读 `session_id`、:101 `sorted(..., key=lambda row:(int(row.get("sequence",0)), ...))`、:103 `"consecutive_turn"` | 函数结束于 104（文档写 101），实质无误 |
| C16 | §2 | 可选 `spatiotemporal_event`（同 context 内时间差、距离都在阈值内的两条媒体相连），但两个阈值默认 0（函数直接 `return {}`）（`spatiotemporal_edges`，:152-186） | ✓ | 函数 `:152-189`；:159-160 `if max_gap_seconds <= 0 or max_distance_meters <= 0: return {}`；默认值 :268-269 均为 0；:163 `kind != "media"` 跳过；:174-180 只连时间排序后的相邻对 | — |
| C17 | §2/§6 | "`run_graphmemix_release.py` 的 relations stage 命令（run_graphmemix_release.py:124-129）没有传这两个参数" | ◐ | 实际 `run_graphmemix_release.py:134-139`，只传 `--bundle --checkpoint-root --output --max-semantic-k`——**内容断言成立** | 行号漂移 10 行 |
| C18 | §2 | 语义边取"canonical vector（**非 atomic 的第一个** embedding unit**；视频取所有帧向量归一化后的均值**）"（`reconstruct_vectors`，:209-223） | ◐ | `canonical_unit_rows`(:60-67) 收集每条记忆**全部**非 `representation` 行；`reconstruct_vectors`(:209-222) 第 220-221 行对这些行**全部**归一化后取均值再归一化——不只视频，多图记忆同样是"所有 canonical unit 的归一化均值" | 文档复述的是该文件 docstring 的措辞（:4-8 "The first (non-atomic) embedding unit … is its canonical graph view"），不是代码行为；单图/纯文本记忆下两者等价，多图记忆下不等价 |
| C19 | §2 | FAISS 里做 mutual top-k 近邻（`mutual_neighbors`，:225-254；k 由 `--max-semantic-k` 控制，生产配置 8） | ✓ | `build_graphmemix_relation_store.py:225-254` 精确；:250 `if right <= left or left not in ranked[right]: continue` 即互为近邻；生产 k=8 见 `configs/release/graphmemix.json:32` + `run_graphmemix_release.py:138` | 该脚本自身默认是 16（:266），生产覆盖为 8 |
| C20 | §2 | relation store 同样不调 LLM，纯向量/metadata 计算 | ✓ | 同 C14，全文件无 chat/completion | — |
| C21 | §3 | 每道题触发一次；node→ecv→select→prune→reader 五个子阶段严格按顺序跑，各自落盘 jsonl 供下一阶段读（run_graphmemix_release.py:141-224） | ✓ | `run_graphmemix_release.py:141-220`（node 141-157 / ecv 159-176 / select 178-190 / prune 192-203 / reader 205-220），每段后接 `validate_jsonl`；ecv 读 `--candidate-cache node`(:162)、select 读 `--ecv-scores ecv`(:181)、prune 读 `--retrieval fixed`(:196)、reader 读 `--retrieval pruned`(:208) | 区间尾 224 已落进 judge stage（222-234），无碍 |
| C22 | §3.1 | priors stage 由 `run_memix_main_track_retrieval.py` 直接调 `ConcreteMemixMethod._source_detail`（concrete_memix.py:558-577）；每视图查 FAISS top-k，同 memory_id 只留最高分（`best[memory_id]=max(...)`，:568-577），凑出 200 条（`source_top_k`） | ✓ | `run_memix_main_track_retrieval.py:177` 构造、:196 `detail = method._source_detail(resolved)`；`concrete_memix.py:558-579` 为该函数，max-pool 在 :574，截断 `[: self.source_top_k]` 在 :575；`source_top_k=200` 见 `configs/release/graphmemix.json:29` 与 `build_memix_checkpoints.py:50` | 函数实际到 579；引用可接受 |
| C23 | §3.1 | "把 query 的每个视图（**文字**、每张问题图、视频每帧）分别编码去 FAISS 查 top-k" | ◐ | `_question_units`（`concrete_memix.py:544-556`）与 C9 同构：有媒体时**不**产生独立的纯文本 query 视图，:556 `return units or [{"text": text}]` 只是兜底 | 与 C9 同一处机制误读 |
| C24 | §3.2 | `candidate_pool`（graphmemix_core.py:83-108）：取前 24 条当种子，扩 1 跳，去重后补到 48 条 | ✓ | `graphmemix_core.py:83-105`：:89 `seeds = ...[:source_top_l]`、:94-97 只从 seeds 出发一跳、:103-104 `if len(selected) >= candidate_limit: break`；24/48 见 `configs/release/graphmemix.json:30-31` | 函数止于 105 |
| C25 | §3.2 | 顺着 relation store 的边"**explicit 优先于 semantic**，按相似度排序"扩 1 跳 | ◐ | `candidate_pool` 的排序键是 `(-similarity, source_rank, neighbor)`（`graphmemix_core.py:97-98`），**没有任何按关系类型的优先规则**（关系标签在 :95 被丢弃为 `_`）。explicit 之所以总排前面，是因为 `explicit_similarity` 被固定成 0.99（`build_graphmemix_relation_store.py:267,336`），而 `edge_similarity` 取 explicit/semantic 的 max（`graphmemix_core.py:41-52`） | 是常数取值的副产品，不是显式优先级；若 `--explicit-similarity` 调低即失效 |
| C26 | §3 | Node Verifier 一次 listwise 调用，把全部候选（含 modality/date/location/retrieval_score/snippet）打包成 JSON，0-5 分，不返回即算 0（score_graphmemix_verifier.py:255-330；`output_schema` 见 313 行） | ✓ | `score_graphmemix_verifier.py:255` `def score(qid)`；payload :285-314，候选字段 :292-302 逐项对应；**:313 正是 `"output_schema": {"selected":[{"id":..., "score":"0-5 evidence usefulness"}]}`**；:307 指令 "Omit candidates with score 0."；:344-348 只收 `value > 0`，其余不入 `scores` 即等价 0 | 行号 313 精确 |
| C27 | §3 | ECV 先从候选里按检索序选 10 个（`anchor_count`）当锚点（默认 `anchor_mode=atomic`，不看 verifier 分数） | ✓ | `score_graphmemix_ecv.py:263` `--anchor-mode … default="atomic"`；:272 `--anchor-count … default=10`；:424-425 `elif args.anchor_mode == "atomic": anchor_order = candidate_ids`；:452 切片；`run_graphmemix_release.py:159-174` 只传 `--anchor-count`，不传 `--anchor-mode`；`configs/release/graphmemix.json:33` `anchor_count=10` | verifier 分数在 :408-411 被读入，但只有 `verifier`/`reward` 两个非默认模式才用（:426-451） |
| C28 | §3 | 只对"锚点—候选"之间 relation store 里**已有 schema 边**的 pair 打包发给 LLM（语义近邻边不参与） | ✓ | `explicit_relations_from_store`（:203-216）只收 `row["explicit_relations"]` 非空的行（:210-212），语义字段被忽略；:459-466 逐锚点检查 `anchor in relations.get(mid,{})`；:479 `edge_candidates = [row for row in candidates if row["eligible_anchor_relations"]]`；:499 `rows_to_score = edge_candidates if args.edge_only else candidates` | 否定式断言成立 |
| C29 | §3 | `direct_support` 生产配置里 `--edge-only` 强制置 0，复用 node 阶段的分（score_graphmemix_ecv.py:35-42,552） | ✓ | :35-42 `direct_support_value(..., edge_only)` → `if edge_only: return 0.0`（docstring :36 "Enforce the edge-only contract in code, not merely in the prompt"）；:552 prompt 指令 "Set direct_support to 0; this edge-only experiment reuses the locked original node verifier."；`run_graphmemix_release.py:173` 传 `--edge-only` | 两个行号都精确；论文 A.4 txt:2197 有对应表述 |
| C30 | §3 | 六选一角色 `new_fact`/`clarification`/`corroboration`/`redundant`/`conflict`/`irrelevant`（score_graphmemix_ecv.py:30-31,533） | ✓ | :30 `POSITIVE_ROLES = {"new_fact","clarification","corroboration"}`、:31 `ALL_ROLES = POSITIVE_ROLES \| {"redundant","conflict","irrelevant"}`；**:533 prompt 内 `"role": "new_fact, clarification, corroboration, redundant, conflict, or irrelevant."`** | 与论文 txt:628-631 逐字一致 |
| C31 | §3 | 只有正分 + 前三种角色的边保留（`positive_edges`/`conditioned_adjacency`，evaluate_graphmemix_exact_pruning.py:32-46，evaluate_graphmemix_ecv.py:32-44） | ✓ | `evaluate_graphmemix_exact_pruning.py:32-47`（:39-40 角色过滤、:43 `incremental <= 0` 过滤）；`evaluate_graphmemix_ecv.py:31-45`（:36 角色、:39-40 分数） | 两处区间各差 1 行，实质精确 |
| C32 | §3 | 节点值 = `sigmoid(a·atomic_score + b·verifier_score + c)`，系数来自 `configs/release/calibration/shared_dev.json` | ✓ | `evaluate_graphmemix_ecv.py:48-55`（:53 `expit(a*atomic + b*verifier + c)`）、系数读入 :77-78；`evaluate_graphmemix_exact_pruning.py:127-154`（:148-152）、:173-174 | 补充发现：`shared_dev.json:12-21` 的 `standardization`(mean/scale) **全仓库无任何读取者**（`grep -rn standardization` 仅命中该 JSON），即节点效用用的是未标准化原始特征 |
| C33 | §3 | 边的"收益" = `root_cost(0.2) − edge_weight(0.1)·(−log(similarity))` | ✓ | `probe_graphmemix_pcsf.py:192` `benefit = root_cost - edge_weight * -math.log(max(similarity, 1e-6))`；`configs/release/graphmemix.json:35-36` `edge_weight=0.1`、`proposal_root_cost=0.2`；`run_graphmemix_release.py:185-186` 传入 | 与论文 λ=0.1（txt:1258）、κ_prop=0.2（txt:1313）一致 |
| C34 | §3 | "从 Top-10 节点效用起步，每次尝试换一个进出，**只要严格变好就换**，直到没有更好的交换（probe_graphmemix_pcsf.py:196-231）" | ◐ | 初始化在 :204（`sorted(ids, key=(-prize, position, mid))[:k]`）、爬山循环 :206-220；但 :208-216 **遍历全部 (removed, added) 组合并取最优**（:215 `if proposal_value > value + 1e-12 and (best is None or candidate[:3] > best[:3])`），是 best-improvement 而非 first-improvement | "只要严格变好就换"读起来像首次改进即接受；实际每轮扫完全部候选交换。区间 196-231 也跨越了 `forest()` 尾部与分量分组开头 |
| C35 | §3 | "候选边按收益从高到低排序，用并查集依次加边、成环就跳过，这是标准 Kruskal 求最大权森林（**probe_graphmemix_pcsf.py:203-215**）" | ✗ | Kruskal 在 `forest()` 内部：`probe_graphmemix_pcsf.py:188-200`（:188-194 组装正收益边、**:196 `for benefit,left,right,relation in sorted(weighted, key=lambda row:(-row[0],row[1],row[2]))`**、:197-199 并查集判环、:200 合并累加）。而 **:203-215 是 1-swap 的初始化与爬山循环**（见 C34） | 行号错，且与 C34 的区间事实上被写反；机制描述本身正确 |
| C36 | §3 | diagnostic 明确标 `"exact": False`（probe_graphmemix_pcsf.py:249） | ✓ | `probe_graphmemix_pcsf.py:249` `"local_search_iterations": iterations, "exact": False,` | 精确 |
| C37 | §3 | Prune：在 select 选出的 ≤20 个节点范围内穷举 2ⁿ−1 个非空子集，每子集精确 Kruskal（evaluate_graphmemix_exact_pruning.py:50-100；超过 20 个节点抛异常，第 62 行） | ◐ | `exact_subset` 实为 :50-124（枚举循环 :78-108，Kruskal 在 :89-97，目标值 :99-102，确定性 tie-break :103-107）；**:62-63 的 `if n > 20: raise ValueError` 行号精确** ✓；但生产下 select 恒返回 K=10（`configs/release/graphmemix.json:34` `reader_k=10`，`run_graphmemix_release.py:187`），实际搜索空间是 2¹⁰−1=1023，"≤20"是防御性上界不是运行规模 | 另：诊断字段 `"exact": True` + `"globally_exact_over_candidate_pool": False`（:120-122）正好印证文档"不是在全部 48 个候选里穷举"的说法 |
| C38 | §3 | Prune 是"穷举 + Kruskal 做变基数精修"，且只在 1-swap 筛过的小集合内穷举 | ✓ | 见 C37 | **但文档漏了**：prune 的 `root_cost` 从 0.2 变成 0.12（`run_graphmemix_release.py:199` 传 `pruning_root_cost`，`configs/release/graphmemix.json:37` = 0.12），恰好对应论文 txt:1313 的 κ=0.12；`--node-cost` 未传，默认 [0.0]（:182）。这是遗漏不是错误 |
| C39 | §3 | 证据按"分量取效用最高点为根、按根效用排序分量、分量内 BFS"排序（`solve_forest`/`solve_forest_greedy` 末尾） | ✓ | `probe_graphmemix_pcsf.py:225` `key = lambda mid: (-prizes[mid], position[mid], mid)`；:236-242 分量排序 + BFS（邻居按同一 key 排序）；`solve_forest` 同构逻辑在 :140-153 | 与论文 A.5 txt:2215-2216 的 tie-break（先节点效用、再原始检索序）逐条对应 |
| C40 | §3 | reader stage 调 `ConcreteMemixMethod._generate_answer`（concrete_memix.py:759 起，被 `run_memix_answers_from_retrieval.py` 复用），把有序证据（原文文字 + 原始图片/视频帧）拼成多模态 prompt | ✓ | `concrete_memix.py:759` `def _generate_answer(...)`；证据块 :786-798（`Evidence {rank}; memory_id=…; source_id=…; modality=…`）、媒体 :799 起；调用点 `run_memix_answers_from_retrieval.py:753,773,792`，构造点 :136 | 四个行号全部精确；与论文 A.4 txt:2203-2207 一致 |
| C41 | §3 | 发给**同一个** backbone（Qwen3-VL-8B-Instruct 或 Gemma-4-12B） | ✓ | `run_graphmemix_release.py:98` `model = args.model or backbone_cfg["model"]`，同一个 `model` 变量分别传给 node(:149)、ecv(:165)、reader(:210)；`configs/release/graphmemix.json:11-20` | — |
| C42 | §5 | README 给了数据集下载方式，但完全没提 `vendor/memix-core` 怎么获取 | ✓ | `README.md:99-108` 只给 HF `oking0197/graphmemix-benchmarks` → `data/`；`README.md:110-119` 的 artifact layout 里出现 `vendor/memix-core/` 但无出处；`docs/graphmemix_release.md:29-39` 同；`.gitignore` 含 `/vendor` 与 `Memix-core-share-*.tar.gz`；`pyproject.toml` `dependencies = []` | 详见 §5-A |
| C43 | §5 | checkpoint（build_memix_checkpoints.py:41）、priors、reader（run_memix_answers_from_retrieval.py:136,753,773,792）三个 stage 都会在构造 `ConcreteMemixMethod` 时因缺该仓库抛 `RuntimeError`（concrete_memix.py:48-52） | ✓ | `build_memix_checkpoints.py:41` `method = ConcreteMemixMethod(`（:31 `--memix-repo` required）；`run_memix_main_track_retrieval.py:177`；`run_memix_answers_from_retrieval.py:136`；三者都必然走到 `concrete_memix.py:268` → `:51-52` | 行号精确 |
| C44 | §5 | `cli.py` 另一条路径 `graphmemix run --method memix`（cli.py:385-403,546-559）把候选图构建、验证、选择全部甩给 `self.core.retrieve_one(...)` | ✓ | `cli.py:385-404` 与 `:546-560` 构造 `ConcreteMemixMethod`；`concrete_memix.py:649-701` 的 `_select_evidence` 第 **675** 行 `result = self.core.retrieve_one(...)`，返回 `result["ordered"]` 截断到 top_k（:692-695） | 两处 cli 区间各差 1 行；委托结论精确 |
| C45 | §5 | "校准系数 a/b/c 的拟合脚本没找到……'按 SHA256 分 5 折、只在 dev fold 用 gold 标签防泄漏'这套流程**具体怎么实现的代码没有找到**" | ◐ | 拟合脚本确实不存在（`grep -rn "logistic|devfold|standardization|prevalence"` 全仓库仅命中 `shared_dev.json` 本身）✓；但 **5 折 SHA256 切分就在仓库里**：`score_graphmemix_verifier.py:28-30` `def fold(question_id, folds=5): … int.from_bytes(digest[:8],"big") % folds`，使用点 :351-354（`"dev" if fold(qid)==args.include_dev_fold else …`） | 只有 logistic 拟合缺失，切分协议可读。另：文档内部交叉引用"（见第 4 节的一句话机制）"有误——第 4 节是"架构图"，"一句话机制"是第 1 节 |
| C46 | §5 | `shared_dev.json`："protocol": "graphmemix-shared-logistic-devfold-1.0"，positives=8491，prevalence=0.135 | ✓ | `configs/release/calibration/shared_dev.json:2`、`:24` `"positives": 8491`、`:25` `"prevalence": 0.13480345462627802` | — |
| C47 | §6.1 | 全仓库搜 `record_grounding` 只在 `tests/test_score_graphmemix_ecv.py:63` 出现一次，且是"不合法 ECV 角色"测试用例；`event_bridge`/`same_record` 完全没有出现在任何代码里 | ✓ | 仓库级 `grep -rn "record_grounding|event_bridge|same_record"`（含 .py/.json/.md，排除 .git）**唯一命中** `tests/test_score_graphmemix_ecv.py:63` `[{**valid, "role": "record_grounding"}]`，:67-71 断言被规整成 `irrelevant` + `_normalizations` 含 `invalid_role_replaced_with_irrelevant` | 否定式断言，逐字证实 |
| C48 | §6.1 | 通用 schema 边构建 `explicit_edges()` 只认 `metadata.native_round_id` 与 `session_id` | ✓ | 见 C15（`build_graphmemix_relation_store.py:90-91`）；ECV 侧的同构实现 `explicit_relations_from_memories`（`score_graphmemix_ecv.py:236-237`）也只认这两个字段 | — |
| C49 | §6.1 | `converters/atm.py` 的 email 与 media 两处 `memory_rows.append(...)`（atm.py:400,461）都没设这两个字段；"对照 memeye.py、mem_gallery.py、h2hmem.py **三个转换器都显式写了 `session_id`/`native_round_id`**" | ◐ | ATM 部分**完全属实**：`atm.py:400-411`（email）与 `:445-461`（media）均无 `session_id`/`native_round_id`；`_media_metadata`(:181-194) 把未知字段统统塞进 `metadata["raw_metadata"]`（:192-193），不会产生 `native_round_id`；`sequence` 虽在 :473-474 被赋值，但 `explicit_edges` 必须先有非空 `session_id` 才会用它（:94-95）。**但 h2hmem 只写了 `session_id`**（`h2hmem.py:260`），没有 `native_round_id`——`grep -n native_round_id h2hmem.py` 0 命中 | "三个转换器都写了两个字段"过度概括；h2hmem 缺 `native_round_id` 恰与论文 A.1 txt:1833-1835 "does not expose the paired native-round field required by same_round" 一致，反而是代码与论文相符的证据 |
| C50 | §6.1 | 按代码路径推演，ATM-Bench 走 `explicit_edges()` 会得到 0 条 schema 边；spatiotemporal 通道生产下也是关的；而论文 Table 6 写 ATM 每题平均 6.23 条 Fixed Edges，直接对不上 | ✓ | 静态推演成立（见 C48/C49/C16）；Table 6 的 ATM Fixed Edges = **6.23** 在 txt:1359（表注 txt:1405） | 这是本次复核确认的、最值得实机验证的一处不一致；文档自己也标注了"未实机跑通" |
| C51 | §6.1 | ATM 的 6.23 "是四个数据集里**第二高**的" | ✗ | Table 6：Mem-Gallery **7.34**（txt:1371）> H2HMem **6.75**（txt:1395）> ATM **6.23**（txt:1359）> MemEye **6.07**（txt:1383） | ATM 是**第三高**。不影响该条冲突的成立，但数值排序断言错误 |
| C52 | §6.2 | "`w^schema`（论文 Eq.9）在代码里是单个全局常数 0.99，不分 schema 类型；后续算边权重时直接拿常数 0.99 乘 ECV 归一化增量分，完全没有读取 relation store 里的 `explicit_similarity` 字段" | ◐ | **代码部分完全属实**：`build_graphmemix_relation_store.py:267`（`--explicit-similarity` default 0.99）、:336（不分类型统一赋值）；`evaluate_graphmemix_ecv.py:41` 与 `evaluate_graphmemix_exact_pruning.py:45` 都是硬编码 `similarity = 0.99 * (incremental/5.0) ** power`，确实不读 store 里的字段 ✓。**但把它列为"与论文的冲突点"站不住**：论文 §4.1 txt:1258 "We set the maximum schema reliability to 0.99"、§4.4.3 txt:1471 "assigns every eligible explicit schema edge the same query-independent reliability of 0.99" —— 论文自己就钉死了单一全局 0.99 | 应改判为"记号（Eq.9 的 schema-specific 上标，txt:641）与论文自身实现描述之间的张力"，而非论文↔代码分歧 |
| C53 | §6.3 | "论文说 can execute in parallel；代码里 ECV 确实不消费 node 阶段打的分数，只共享同一份冻结候选集……编排成顺序 stage 只是产物缓存/一致性校验的工程选择，**不构成对论文说法的否定**" | ◐ | "不消费 verifier 分数"属实（C27）✓；但"只共享同一份冻结候选集"低估了依赖：`score_graphmemix_ecv.py:260` `--candidate-cache` 是 **required**，:406 `candidate_ids` 与 :486/:520 `query_captions` 都取自 node 阶段落盘的行（由 `score_graphmemix_verifier.py:355` 与 :360 写出），而 **query caption 的那次 LLM 调用只发生在 node 阶段**（`score_graphmemix_verifier.py:83-115`，调用点 :280-282）。要真并行必须先单独跑一遍 caption | 论文的断言比文档引用的更强（§4.1 txt:1314、§4.4.4 txt:1647 都是无条件"execute in parallel / no serial dependency"），因此这确实构成一处实现层分歧 |
| C54 | §6.4 | Kruskal 求解器与 ECV 六角色是"真实实现、与论文高度一致"，不是占位符；κ↔`root_cost`、λ↔`edge_weight`、A.5 排序规则都能对应 | ✓ | Kruskal 见 C35 更正后的 `probe_graphmemix_pcsf.py:188-200` 与 `evaluate_graphmemix_exact_pruning.py:89-97`；六角色见 C30；κ/λ 见 C33+C38；A.5 见 C39 | 结论成立，仅其中一个行号需按 C35 更正 |
| C55 | §6.1 | "一个可能的解释是 HF 上发布的 unified 快照由更早/不同的转换器版本生成" | ? | 无法核实：本机 `repo/graphmemix` 下没有 `data/` 也没有 `artifacts/`（`ls -d data artifacts` 均不存在），`release/benchmark_results.json` 不含任何 edge 计数（`grep -o "edges"` 0 命中），也没有任何 `*.summary.json` 可看 `native_explicit_edges` | 需要下载 HF 数据并实跑 relations stage 才能判定 |

## 3. 步骤清单 — 论文侧

系统边界：论文 Eq.1（txt:534）自己划线——`Π`（evidence selector）= GraphMemix 本体；`M`（frozen multimodal generator）= agent/backbone 侧；LLM-as-judge（A.4 txt:2208-2213）= 评测侧。

**写入侧（离线，query 无关）**

| # | name（原文叫法） | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| W1 | "user multimodal memory archive V = {e_i}"（§3.1, txt:520-522） | 离线一次 | 用户历史多模态记录 → 固定集合 V | no | —（论文未命名后端） | P-INTAKE |
| W2 | "frozen caption sidecar"（A.1, txt:1826-1828） | 离线一次 / 每个媒体资产；**仅 H2HMem** | 1,300 张无 caption 的图 → 冻结 caption 文件 | **1 次/资产**，Qwen3-VL-8B-Instruct 作 captioner（与 reader 同权重但产物冻结、跨方法共享） | caption sidecar | **[NEW] P-CAPTION** |
| W3 | "construct the memory representation for every canonical memory once"（A.3 txt:1888-1889）+ multi-view U_i（§3.3 txt:552-557） | 离线一次 / 每条记忆 | e_i 的各视角（原图 / caption / OCR / 视频帧） → 1,536-d 向量 | no（frozen gme-Qwen2-VL-2B-Instruct，txt:1255-1256） | 向量索引（论文未命名） | P-EMBED |
| W4 | "Schema relations E_schema"（Eq.4 @txt:569；规则见 A.1 txt:1754-1757/1764-1765/1823-1824/1833-1835） | 离线一次 | 记忆 metadata（round id / session 位置 / 时间 / 地点 / 邮件引用） → 类型化边 | no | 关系图 | P-LINK |
| W5 | "Semantic relations E_sem"（Eq.4 @txt:569，mutual-kNN，k=8 @txt:1257） | 离线一次 | 记忆向量 → 互为 top-k 近邻边 | no | 关系图 | P-LINK |
| W6 | "discovery graph G_disc = (V, E_schema ∪ E_sem)"（txt:580-581） | 离线一次 | W4 ∪ W5 | no | 关系图 | P-LINK（同一步） |

论文写入侧**不存在**的步骤（否定式，已逐条查证）：无 LLM 摘要/笔记抽取（P-EXTRACT）、无指代消解/改写（P-REWRITE）、无阈值去重（P-DEDUP）、无冲突检测消解（P-CONFLICT，冲突只在 query 时由 ECV 的 `conflict` 角色处理）、无高层聚合（P-AGGREGATE）、无驱逐/压缩（P-EVICT）、无落盘协议描述（P-PERSIST）。这正是论文与 MIRIX/SGM/A-MEM/AUGUSTUS/M2A 路线对立的核心（txt:40-46）。

**检索侧（每 query）**

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| R0 | query-image caption（A.4 txt:1906-1908） | 每 query，**条件触发**（问题图无 dataset caption 时） | 问题图 → noisy caption | 1 次/缺 caption 的图，verifier backbone | 缓存 | **~[NEW] P-CAPTION** |
| R1 | "Multi-view retrieval"（§3.3, Eq.3 @txt:558） | 每 query | q → s_i(q)=max_u sim(h(q),h(u))，Top-L=24 种子 R_q^(L) | no | 向量索引 | P-DENSE |
| R2 | "Query-relevant subgraph discovery"（Eq.5 @txt:590） | 每 query | 种子 + G_disc → H=1 跳可达，按"检索序+关系扩展序"取 Top-M=48 → C_q | no | 关系图 | P-GRAPHEXPAND |
| R3 | "Direct node utility / listwise node verifier"（§3.4, Eq.6 @txt:609） | 每 query | q + 全部 C_q → v_i∈[0,5]，融合成 p_i=σ(τ[αs+(1−α)ṽ−δ]) | **1 次 listwise**（与 reader 同一模型，txt:1846-1848） | — | P-RERANK |
| R4 | "Anchor-set construction"（A.2 txt:1881-1885） | 每 query | 冻结多视图检索序（去重、保序） → A_q | no | — | P-SELECT（确定性截断） |
| R5 | "Anchor-conditioned relation verification (ECV)"（§3.4, Eq.7-9 @txt:625/639/650） | 每 query（与 R3 **声称**并行，txt:1314/1647/1860） | E_q^elig（仅 schema 边） → best anchor + s^inc∈[0,5] + 六选一角色；正分且属前三角色的边 → G_q^trust，w_ai / c_ai | **1 次 listwise**（同一模型） | — | **[NEW] P-EDGEVERIFY** |
| R6 | "fixed-cardinality forest solver / 1-swap"（§3.5 txt:1081-1086） | 每 query | p_i、B_e=κ−λc_e、C_q → K=10 节点提案 S̄_q（每步 Kruskal 精确重算森林），κ_prop=0.2 | no | — | P-SELECT |
| R7 | "Bounded exact cardinality refinement"（Eq.13 @txt:1111，κ=0.12 @txt:1313） | 每 query | S̄_q → 穷举全部非空子集，逐子集 Kruskal 精确求 F_S*，取最优 (S*_q, F*_q) | no | — | P-SELECT |
| R8 | "Evidence Serialization"（A.5 txt:2214-2218） | 每 query | (S*_q, F*_q) → 有序序列 O_q（≤K 条） | no | — | P-ASSEMBLE |
| R9 | "ŷ = M(q, O_q)"（Eq.1 @txt:534） | 每 query | O_q + q → 答案 | **1 次**（frozen multimodal generator） | — | P-GENERATE ← **边界外（backbone 侧）** |
| R10 | LLM-as-judge（A.4 txt:2208-2213，gpt-5-mini） | 每 query | 答案 + 参考答案 → correct 布尔 | 1 次 | — | ← **边界外（评测侧）** |

检索侧**不存在**的步骤：无查询意图/时间范围解析（P-QUERYPARSE）、无 BM25（P-SPARSE）、无符号过滤（P-SYMFILTER，论文层面 E_q^elig 的 schema 限定接近但被并入 Eq.7）、无 PPR/RWR 扩散（P-DIFFUSE）、无 RRF/MMR 融合（P-FUSE，MMR 只作为 A.6 的对照 baseline，txt:2223）、无 agent 工具循环（P-TOOLLOOP）；参数侧整组（P-DATASTORE/P-ANNINDEX/P-KNNDIST/P-TRAIN/P-FROZENFWD/P-SIDEPATH/P-INJECT/P-INTERP/P-KVWINDOW）全部不适用——GraphMemix 不训练任何参数，编码器与生成器都冻结。

## 4. 步骤清单 — 代码侧

系统边界：`run_graphmemix_release.py:23` 的 9 个 stage 中，**checkpoint / priors / relations / node / ecv / select / prune 七个属记忆系统本体**；**reader 属 backbone 侧**；**judge 属评测侧**。此外 `evaluate_graphmemix_ecv.py:86-89` 每次还会跑 8 个对照变体（`*_fixed`、`ecv_*`、`atomic_only_*`），只有 `original_ecv_edge_p1` 进入生产链路（`run_graphmemix_release.py:92`）——其余属评测/消融侧。仓库外还有两块：`vendor/memix-core`（构造 `ConcreteMemixMethod` 必需）与 h2hmem caption sidecar 的生成。

**写入侧**

| # | name（stage / 函数） | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| W0 | h2hmem caption sidecar（`run_graphmemix_release.py:118-119` 消费，`reader.py:44-45` 读取） | 离线一次（**生成脚本不在本仓库**） | 1,300 张图 → `captions/h2hmem.jsonl` | 仓库外，论文说是 Qwen3-VL-8B（txt:1827） | jsonl | **~[NEW] P-CAPTION** |
| W1 | `checkpoint` stage → `build_memix_checkpoints.py:41-67` → `ConcreteMemixMethod.ingest`→`_adapt_memory`(`concrete_memix.py:397-499`) | 离线一次 / **每 dataset**（跨 backbone 复用，见 C5） | unified `memories.jsonl` + 原始资产 → `record{item_id,modality,text,image_path,video_path,content,metadata}` | **no**（`build_memix_checkpoints.py:19-21` 的 `UnusedAnswerModel` 会在任何 chat 调用上抛错） | 内存 | P-INTAKE |
| W2 | embedding unit 切分（`concrete_memix.py:466-498`） | 每条记忆 | 文本 + 媒体 → 每图一份 / 每视频帧一份 / 无媒体才一份纯文本 / 可选 atomic 句子（默认关） | no | — | P-EMBED（视图准备） |
| W3 | `self.embedder.encode_units` → FAISS Flat-IP（`concrete_memix.py:370-373`） | 每 batch（`ingest_batch_size=16`） | units → 1,536-d 向量 | no（`GMEQwen2VLEmbedder`，`configs/release/graphmemix.json:28`） | FAISS | P-EMBED |
| W4 | `_save_checkpoint`（`concrete_memix.py:875-903`） | 每 100 条 / context 结束 | 索引 + records + units → `contexts/<ctx>/state.json` + `index-{n:08d}.faiss` | no | 磁盘 | P-PERSIST |
| W5 | `relations` stage → `explicit_edges()`（`build_graphmemix_relation_store.py:70-104`） | 离线一次 / 每 dataset | memories metadata → `same_round`（native_round_id）/ `consecutive_turn`（session_id + sequence） | no | relation store | P-LINK |
| W6 | `spatiotemporal_edges()`（同文件 :152-189） | **生产下不触发**（阈值默认 0，release 不传参） | 同 context 媒体的时间+距离相邻对 → `spatiotemporal_event` | no | relation store | ~P-LINK |
| W7 | `reconstruct_vectors`(:209-222) + `mutual_neighbors`(:225-254) | 离线一次 / 每 context | canonical unit 向量归一化均值 → 互为 top-8 近邻边（含双向 rank 与 cosine） | no | FAISS（临时 IndexFlatIP） | P-LINK |
| W8 | 写 `relation_store/{dataset}.jsonl` + `.summary.json`（:333-365） | 离线一次 | 边表（`explicit_similarity` 统一 0.99、`explicit_cost`、`semantic_cost`） | no | 磁盘 | P-PERSIST |

**检索侧（每题）**

| # | name（stage / 函数） | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| R1 | `priors` stage → `run_memix_main_track_retrieval.py:196` → `_source_detail`（`concrete_memix.py:558-579`） | 每 query | query 各视图编码 → FAISS 检索 → 按 memory_id max-pool（:574）→ top-200 | no | FAISS | P-DENSE |
| R1b | 落盘 `source_priors/{dataset}.jsonl`（含 run contract sha256，`run_memix_main_track_retrieval.py:98-105`） | 每 dataset | — | no | 磁盘 | P-PERSIST |
| R2 | `node` stage → `candidate_pool`（`graphmemix_core.py:83-105`，`--graph-mode full`） | 每 query | top-24 种子 + 1 跳邻居（按边相似度排序）→ 48 候选 | no | relation store | P-GRAPHEXPAND |
| R3 | `caption_question_images`（`score_graphmemix_verifier.py:83-115`，调用点 :280-282） | 每 query，**条件触发** | 无 dataset caption 的问题图 → caption | **0~N 次**，同 backbone | — | **~[NEW] P-CAPTION** |
| R4 | listwise node verifier（`score_graphmemix_verifier.py:255-343`） | 每 query | q + 48 候选（id/modalities/date/location/retrieval_score/snippet≤420 字，OCR≤120 字）→ 每条 0-5 分，缺省 0；最多重试 3 次 | **1 次** | — | P-RERANK |
| R4b | 落盘 `node_scores.jsonl`（candidate_ids / atomic_scores / verifier_scores / query_captions，:349-376） | 每 query | — | no | 磁盘 | P-PERSIST |
| R5 | `ecv` stage 锚点选取（`score_graphmemix_ecv.py:424-425,452`，`anchor_mode=atomic`） | 每 query | 候选序（=检索序）前 10 → A_q | no | — | P-SELECT（确定性截断） |
| R6 | eligible 边过滤（`score_graphmemix_ecv.py:203-216,459-466,479,499`） | 每 query | 只保留"锚点↔候选"且 relation store 里有 explicit 边的 pair；`--edge-only` 下只把有边的候选发给模型 | no | relation store | P-SYMFILTER |
| R7 | ECV listwise 调用（`score_graphmemix_ecv.py:500-600`，prompt :525-567） | 每 query | pairs → `direct_support`(强制 0, :35-42/:552) / `best_anchor_id` / `incremental_support` 0-5 / `role` 六选一(:533)；`validate_candidate_rows`(:45-…) 对非法锚点、非正角色带正分等做保守清零，最多重试 3 次 | **1 次** | — | **[NEW] P-EDGEVERIFY** |
| R7b | 落盘 `ecv_scores.jsonl` | 每 query | — | no | 磁盘 | P-PERSIST |
| R8 | `select` stage 节点效用（`evaluate_graphmemix_ecv.py:48-55,77-78`） | 每 query | atomic + verifier → `sigmoid(a·s + b·v + c)`，a/b/c 来自 `shared_dev.json`；缺检索分的图邻居用 `missing_atomic_floor`=min−0.01（`graphmemix_core.py:114-119`） | no | 磁盘（calibration） | P-SELECT（输入准备） |
| R9 | `select` stage 边权（`evaluate_graphmemix_ecv.py:31-45`） | 每 query | 正分 + 前三角色的 ECV 边 → `similarity = 0.99·(inc/5)^1` | no | — | P-EDGEVERIFY（输出使用） |
| R10 | `solve_forest_greedy`（`probe_graphmemix_pcsf.py:163-250`） | 每 query | 从 Top-10 效用起步，best-improvement 1-swap（:206-220），每步用 Kruskal 精确求最大权森林（:188-200），`root_cost=0.2`/`edge_weight=0.1`；诊断 `"exact": False`(:249) | no | — | P-SELECT |
| R11 | 分量根 + BFS 排序（`probe_graphmemix_pcsf.py:225-242`） | 每 query | 森林 → 有序 10 条 | no | — | P-ASSEMBLE |
| R11b | 落盘 `selection/original_ecv_edge_p1.jsonl`（+ 8 个对照变体，`evaluate_graphmemix_ecv.py:86-89,143-146`） | 每 query | — | no | 磁盘 | P-PERSIST |
| R12 | `prune` stage `exact_subset`（`evaluate_graphmemix_exact_pruning.py:50-124`） | 每 query | 对 select 的 10 个节点穷举 2¹⁰−1 子集，逐子集 Kruskal；`root_cost=0.12`、`node_cost=0`；tie-break 先少节点后早序（:103-107）；n>20 抛错(:62) | no | — | P-SELECT |
| R12b | 落盘 `pruning/root0.12_node0.jsonl`（:215-218） | 每 query | 保留 select 的顺序按 mask 过滤（:110），**不重跑 BFS** | no | 磁盘 | P-PERSIST |
| R13 | `reader` stage 组装（`concrete_memix.py:759-800+`） | 每 query | 选中证据 → `Evidence {rank}; memory_id=…; source_id=…; modality=…` 文本块 + 原图 / 抽帧 | no | — | P-ASSEMBLE |
| R14 | `reader` 生成（`run_memix_answers_from_retrieval.py:753/773/792`） | 每 query | prompt → 答案 | **1 次**，同 backbone | — | P-GENERATE ← **边界外** |
| R15 | `judge` stage（`run_graphmemix_release.py:222-234`，gpt-5-mini，protocol `mmmb-llm-judge-1.2`） | 每 query | — | 1 次 | 磁盘 | ← **边界外（评测侧）** |

代码侧**不存在**的步骤：同论文侧的否定清单，另加——没有 P-DEDUP（`_ingest:339` 的 memory_id 去重是幂等保护，不是相似度去重）、没有 P-EVICT、没有任何梯度训练。注意 stage 顺序上 `priors`（检索侧）排在 `relations`（写入侧）之前（`run_graphmemix_release.py:122-139`），这是编排产物依赖导致的，不代表逻辑顺序。

## 5. 论文 ↔ 代码分歧

### A. 专项确认：`vendor/memix-core` 硬依赖（本次任务点名核实）

**结论：代码文档的说法成立，且比它写的更硬。**

1. `ConcreteMemixMethod.__init__` 第 **268** 行无条件执行 `self.core = _load_memix_core(self.memix_repo)`，没有任何 try/except、没有 lazy 化、没有开关。
2. `_load_memix_core`（`concrete_memix.py:48-52`）要求 `<memix_repo>/scripts/QA_Agent/MMRAG/memix_memory.py` 存在，否则 `raise RuntimeError(f"Memix core is missing: {core_path}")`。
3. 默认路径 `memix_repo="vendor/memix-core"`（`:219`），配置里也写死（`configs/release/graphmemix.json:57`）、cli 两处默认值同（`cli.py:88,156`）。
4. **仓库里没有 `vendor/`**：`ls vendor` → No such file or directory；`.gitignore` 显式忽略 `/vendor`，并额外忽略 `Memix-core-share-*.tar.gz`（暗示它以私有 tarball 形态分发）。
5. **没有任何获取方式**：`README.md:99-119` 的 "Data and Artifacts" 只给 HF 数据集 `oking0197/graphmemix-benchmarks`（下载到 `data/`），而 `vendor/memix-core/` 只出现在 artifact layout 树里（`README.md:118`、`docs/graphmemix_release.md:38`）与命令示例的 `--memix-repo` 参数里（`README.md:211`、`docs/graphmemix_release.md:106,120`），全仓库无 URL、无 git submodule、无 pip 依赖（`pyproject.toml` `dependencies = []`）。
6. **影响面**：9 个 stage 里 3 个必然构造 `ConcreteMemixMethod`——`checkpoint`(`build_memix_checkpoints.py:41`，`--memix-repo` required)、`priors`(`run_memix_main_track_retrieval.py:177`)、`reader`(`run_memix_answers_from_retrieval.py:136`)。三者都会在构造期抛 `RuntimeError`。此外 `run_memix_main_track_retrieval.py:80-85` 还会把 core 三个文件的 sha256（`run_memix_retrieval_only.py:26-30` 定义 `CORE_FILES`）与 checkpoint 里记录的 `core_sha256`（`concrete_memix.py:865`）比对，不匹配直接 `RuntimeError`。
7. `release/repository_audit.json` 显示白名单共 93 个文件、`"missing": []`、`"status": "valid"`——即"仓库自认为完整"的定义本身就把 memix-core 排除在外。
8. 唯一的补充限定：**reader stage 的实际工作不需要 core**（`_generate_answer` 全程不碰 `self.core`；`self.core` 只在 :271/:299/:515/:540/:675 使用），它是被构造函数连坐的；`checkpoint` 也只在构造与 `core_sha256` 记录时用到。真正把算法委托给 core 的是 `_select_evidence`→`self.core.retrieve_one`（:675），也就是 `cli.py` 那条非发布路径。

因此代码文档"只读这个仓库能完整验证'选证据'的算法对不对，但没法在本地从零跑通'写入→检索→生成'整条链路"这一判断，我确认属实。

### B. 逐条分歧清单

| # | 分类 | 内容 | 论文证据 | 代码证据 |
|---|---|---|---|---|
| D1 | **两边都有但行为不同** | ATM-Bench 的 schema 关系。论文给三种数据集专属规则；代码只有 `same_round`/`consecutive_turn` 两种通用规则，而 ATM 转换器两个字段都不写 → 静态推演 0 条 schema 边，与 Table 6 的 6.23 矛盾 | txt:1754-1757（三种规则）；txt:1359（Fixed Edges 6.23） | `build_graphmemix_relation_store.py:70-104`；`converters/atm.py:400-411,445-461,181-194`；`run_graphmemix_release.py:134-139`（不传时空阈值） |
| D2 | **paper-only** | `event_bridge` / `same_record` / `record_grounding` 三个关系名在代码中不存在；`record_grounding` 仅作为"非法 ECV 角色"测试样例出现 | txt:1754-1757 | 仓库级 grep 唯一命中 `tests/test_score_graphmemix_ecv.py:63` |
| D3 | **code-only** | `spatiotemporal_event` 关系类型（同 context 内按时间排序、只连时间+距离双达标的**相邻对**）论文完全没提这个名字与实现形态；且没有论文 `event_bridge` 所要求的"每条记忆最多 2 个近邻"的显式封顶（相邻链结构使其巧合满足）。生产默认关闭 | txt:1754（只有 event_bridge 的自然语言描述） | `build_graphmemix_relation_store.py:152-189,268-269` |
| D4 | **code-only** | `missing_atomic_floor` = min(retrieval_scores) − 0.01：落在 top-200 之外、靠图扩展进来的候选用一个人造 floor 分参与 p_i 计算 | Eq.6 @txt:609 只说 s_i(q) 是检索分（A.2 txt:1873 称 "frozen Atomic retrieval score"），未定义未被检索到的候选取值 | `graphmemix_core.py:114-119`；使用点 `evaluate_graphmemix_ecv.py:110`、`evaluate_graphmemix_exact_pruning.py:137,149`、`score_graphmemix_verifier.py:297` |
| D5 | **code-only** | 检索先取 `source_top_k=200` 再取前 24 当种子的中间层，论文没写（论文直接从 Top-L=24 起步） | txt:1256 只给 L=24 | `configs/release/graphmemix.json:29`；`concrete_memix.py:575`；`graphmemix_core.py:89` |
| D6 | **两边都有但行为不同** | 并行性。论文两处无条件断言两个 verifier "no serial dependency and execute in parallel"；代码里 ecv stage **必须**读 node stage 落盘的候选缓存，且 query-image caption 的 LLM 调用只在 node stage 发生 | txt:1314、txt:1647（另 txt:1860 是带 "can" 的弱表述） | `score_graphmemix_ecv.py:260`（`--candidate-cache` required）、:406、:486/:520；`score_graphmemix_verifier.py:280-282,355,360`；`run_graphmemix_release.py:141-176` 顺序编排 |
| D7 | **两边都有但参数不同** | 节点效用系数。论文把 (α,τ,δ)=(0.8,5.2,0.7) 呈现为"one fixed parameter setting"，等价形式 σ(4.2s+0.2v−3.6) 并称二者仅差"displayed rounding"；代码实际用的是从 gold 标签拟合出来的 logistic 系数 a=4.0541 / b=0.2254 / c=−3.7113，与 τα=4.16、τ(1−α)/5=0.208、−τδ=−3.64 都不相等 | Eq.14 @txt:1871、Eq.15 @txt:1879、txt:1871-1872（"equivalent, up to the displayed rounding"） | `configs/release/calibration/shared_dev.json:7-11`；`configs/release/graphmemix.json:22-27` 自己标注 (0.8,5.2,0.7) 是 "Human-readable approximation"，"calibration_file contains the machine-exact frozen coefficients used by the pipeline"；读取点 `evaluate_graphmemix_ecv.py:77-78`、`evaluate_graphmemix_exact_pruning.py:173-174` |
| D8 | **code-only（校准协议）** | 用 gold 标签在 SHA256 fold-0 dev 问题上拟合节点效用的整套协议，论文未描述（论文只在 A.6 txt:2221 出现过 "calibrated node utilities" 一词，`grep -i "calibrat\|fold\|dev set"` 全文再无相关说明） | txt:2221 | `configs/release/calibration/shared_dev.json:2,23-25,49`；`score_graphmemix_verifier.py:28-30,351-354` |
| D9 | **code-only** | `shared_dev.json` 的 `standardization`（mean/scale）字段全仓库无读取者，节点效用用的是未标准化原始特征 | —（论文 Eq.14/15 也是未标准化形式，行为上一致） | `configs/release/calibration/shared_dev.json:12-21`；`grep -rn standardization` 仅命中该 JSON |
| D10 | **两边都有但行为不同** | 最终证据顺序。论文 A.5 的"分量根 + BFS"作用在最终森林上；代码在 `select` 阶段对 K=10 提案做 BFS，`prune` 阶段只按 mask 过滤保序，不对最终 (S*_q, F*_q) 重排 | txt:2214-2218（"We choose the highest-utility node in each component as its root…"） | `probe_graphmemix_pcsf.py:236-242`（select）；`evaluate_graphmemix_exact_pruning.py:110` `kept = [ids[i] for i in range(n) if best_mask >> i & 1]` |
| D11 | **两边都有但行为不同** | ECV 的候选覆盖。论文 A.4 要求 "complete and unique candidate coverage"，Eq.8 也把 G_q^trust 定义在整个 C_q 上；代码在 `--edge-only`（生产配置）下只把**有 eligible schema 边**的候选发给模型，其余候选根本不进 prompt | txt:2179-2181；Eq.8 @txt:639 | `score_graphmemix_ecv.py:479,499`（`rows_to_score = edge_candidates if args.edge_only else candidates`）；:481-498 无 edge 候选时直接返回空 ECV 行 |
| D12 | **两边都有但行为不同** | `w^schema` 的类型化。Eq.9 的记号 gloss 说是 "schema-specific reliability ceiling"，但论文自己两处把它固定成单一 0.99；代码硬编码常数 0.99 且不读 relation store 的 `explicit_similarity` 字段 | txt:641（记号）；txt:1258、txt:1471（单一 0.99） | `build_graphmemix_relation_store.py:267,336`；`evaluate_graphmemix_ecv.py:41`；`evaluate_graphmemix_exact_pruning.py:45` |
| D13 | **两边都有但行为不同（写入侧 LLM）** | 论文明说 H2HMem 的 caption sidecar 由 Qwen3-VL-8B 生成（写入侧的生成式 LLM pass）；代码只消费该 sidecar，生成脚本不在仓库 | txt:1826-1828；Table 8 txt:1820 | `run_graphmemix_release.py:118-119`；`configs/release/graphmemix.json:56`；`reader.py:34,44-45`；`grep -rn caption_sidecar` 20 处全是消费方 |
| D14 | **code-only** | select stage 实际会跑 9 个变体（3 种 prize × {fixed, ecv_edge_p*}），生产只取 `original_ecv_edge_p1`；论文只描述单一路径 | — | `evaluate_graphmemix_ecv.py:86-89,114-124`；`run_graphmemix_release.py:92` |

## 6. 新造的 primitive 标签

两个。均因种子词表在"多模态"和"边级验证"两个维度上没有可复用项。

**`P-CAPTION` — 跨模态描述生成（图像/视频 → 文本 caption/OCR 描述）**
理由：种子词表的写入侧只有 `P-EXTRACT`（LLM 抽取事实/实体/三元组/笔记/命题）和 `P-META`（LLM 标注关键词/标签/参与者/时间），两者都假设输入已是文本、输出是结构化片段。GraphMemix 里这一步是"把像素翻译成一段自然语言描述，作为该记忆的一个**检索视图**"（论文 §3.3 的 U_i 明确把 caption/OCR 与原图并列为 view），既不抽事实也不打标签，输出是自由文本。它同时出现在写入侧（H2HMem sidecar，txt:1826-1828 / `run_graphmemix_release.py:118-119`）和检索侧（query-image caption，txt:1906-1908 / `score_graphmemix_verifier.py:83-115`），且是这类多模态记忆系统区分"是否付出生成式写入成本"的关键计费点——用 `P-EXTRACT` 会把它和 A-MEM 式的笔记抽取混为一谈，正是本论文极力区分的两件事。

**`P-EDGEVERIFY` — 锚点条件下的边级增量价值验证**
理由：`P-RERANK` 的本质是"用更强的模型对**候选**重新打分/排序"，`P-LINK` 是"query 无关地建边"，`P-SELECT` 是组合优化。ECV 三者都不是：它的决策单元是 **(anchor, candidate) 这条边**，输出是"这条候选在锚点已知的前提下新增了多少信息"的连续分 + 六选一的语义角色门控，产物是**带权可信边集** G_q^trust 而非候选排序（Eq.7-9 @txt:625/639/650；`score_graphmemix_ecv.py:459-479,525-567`）。把它压成 `P-RERANK` 会丢掉"冗余/冲突识别"和"边权→森林结构"这两个决定该方法身份的性质。这个原语在跨系统骨架里应该是可复用的——任何"判断新证据相对已有证据是补充还是重复"的机制都落在这里。

其余步骤全部复用了种子词表标签，未新造。

## 7. 复核统计

| 文档 | ✓ | ✗ | ◐ | ? | 小计 |
|---|---:|---:|---:|---:|---:|
| paper-architecture.md | 24 | 3 | 7 | 0 | 34 |
| code-architecture.md | 35 | 2 | 17 | 1 | 55 |
| **合计** | **59** | **5** | **24** | **1** | **89** |

✗ 明细：P3/P25（Kruskal 名句被误标为"摘要原话"，同源两处）、P9（写入侧零 LLM 的推断被 A.1 证伪）、P31（|A_q|=10 论文没写）、P34（w^schema 论文"没讨论"不成立）、C35（Kruskal 行号写到 1-swap 循环上）、C51（ATM Fixed Edges 排第二 → 实为第三）。
注：P3 与 P25 为同一处错误在两节的两次出现，按两条计；若合并计则 ✗ 为 4 条。

◐ 中"纯行号漂移、结论无误"的有 9 条（C4/C6/C8/C11/C17/C24/C31/C37 及 P6），"机制描述需加限定"的有 8 条（C5/C9/C13/C18/C23/C25/C34/C45），"定性需修正"的有 4 条（C49/C52/C53/P32），其余为引文归属与措辞限定（P15/P16/P30）。

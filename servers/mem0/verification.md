# mem0 架构文档复核报告

> 复核日期 2026-09-05；论文源 `Chhikara-2025-Mem0-Production-Ready-Agents-Scalable-Long-Term-Memory.txt`（1168 行 / 23 页，含 23 个换页符，页码映射已逐页核实）；代码源 `repo/mem0` @ `dae67f74`（2026-09-04，`pyproject.toml:7` version = `2.0.20`）。
> 核对方式：论文侧全部证据写成**亲眼所见的 txt 行号**并附换算后的页码；代码侧每一个 `file.py:NNN` 都实际打开该行读过上下文，控制流断言顺调用链读到底。
> **本报告核的是 `repo/mem0`（上游 OSS 包）** —— 这正是 `code-architecture.md` 第 1–6 节自己声明的对象；该文档"附"一节另行描述 `servers/mem0/server.py`（memory-bench 自己的 MCP 封装层），这部分也一并核了，行号见 C57–C61。

---

## 1. 总评

两份文档整体可信度**高**：论文侧 46 条断言里 32 条完全属实，逐字引文（四操作定义、conflict resolver、A-Mem\* 脚注、Algorithm 1 判断顺序、7k/14k/26k/600k token 数）**无一处引错**；代码侧 61 条里 45 条属实，`main.py` 的关键行号（760/879/920/940/991/1070/1086/1152/1196/1379-1389/1628/1641/1733/1815/1869/2610-2615）几乎全部精确命中，`a488e190` 这个"v3 换架构"的考古结论完全站得住（已用 `git show a488e190^:mem0/memory/main.py` 反证改动前确实调用 `get_update_memory_messages` 并有 UPDATE/DELETE/NONE 分支）。

**最严重的问题有三类**。第一类是**否定式断言被证伪**：`code-architecture.md` §6① 说"代码里找不到任何地方会写入 `UPDATE`/`DELETE`/`NOOP`"，实际 `main.py:2084`/`3781` 写 `"UPDATE"`、`main.py:2116`/`3815` 写 `"DELETE"` 进 history 表（走手动 CRUD 路径，位置传参所以逃过了 grep）；§6② 说 `mem0/` 包里搜 graph/Neo4j/Memgraph/Kuzu "没有任何一个匹配"，实际 `mem0/AGENTS.md:54,103` 仍整段描述图记忆、`mem0/exceptions.py:396` 有 kuzu/graph_store、`mem0/vector_stores/neptune_analytics.py` 通篇 graph。两条的**实质结论仍成立**（自动路径确无 LLM 判定的 UPDATE/DELETE；确无图记忆实现），但作为"已用 grep 双重确认"的证据链是破的。

第二类是**写入流程漏了一整个 Phase**：代码是 Phase 0–8 共 9 段，文档的表只列到 Phase 7，漏掉的 `Phase 8: Save messages + return`（`main.py:1192-1193`）恰恰是把**原始对话逐条落进 SQLite `messages` 表**（`storage.py:134-141`）的那一步，而 Phase 0 又会把它读回来喂给抽取 prompt。这直接推翻了文档"存的是什么：**不是原始对话**"这句话，也是代码里唯一与论文"最近 m 条消息"对得上的机制。同一节里"每条事实外加一份 `linked_memory_ids`"也不成立——记忆记录 payload 只有 data/text_lemmatized/hash/created_at/updated_at/attributed_to（`main.py:1029-1037`），LLM 吐出来的 `linked_memory_ids` 在同步和异步两条路径上**都被直接丢弃**（`main.py:1015-1039` / `2673-2697` 只读 `text` 和 `attributed_to`）；真正落盘的 `linked_memory_ids` 是 entity_store 行上由 spaCy 实体共现自动生成的，跟 LLM 的输出无关。

第三类是**页码锚点系统性偏移**：`paper-architecture.md` 有 2 条页码明确错（§2.2 的 Neo4j/GPT-4o-mini 实现细节标 p.7，实为 p.6；"10 independent runs" 标 p.8，实为 p.7），另有 6 条页码越界或跨页标错（p.3↔p.4、p.6-7、p.19-20）。§ 号全对，引文全对，只是页码不可直接引用。

---

## 2. 逐条核对表

判定：`✓` 属实 / `✗` 不实 / `◐` 部分属实或需加限定 / `?` 无法核实

### 2.1 `paper-architecture.md`

页码换算依据（换页符实测）：p.3=txt 102–156，p.4=157–195，p.5=196–239，p.6=240–297，p.7=298–351，p.8=352–410，p.9=411–473，p.13=623–680，p.14=681–739，p.19=925–982，p.20=983–1040，p.21=1041–1093。

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| P1 | 头注 | arXiv:2504.19413v1，2025-04-28，23 页 | ✓ | txt:10；末页脚注 txt:1168 = "23"；文件 23 个换页符 | |
| P2 | 头注 | "后发表于 ECAI 2025" | ? | 全文 grep `ecai` 无命中 | 外部事实，无法从 txt 核实 |
| P3 | §1 | 引文 "Mem0 attains a 91% lower p95 latency and saves more than 90% token cost"（摘要, p.1） | ✓ | txt:26-27，p.1 | 逐字一致 |
| P4 | §1 | Mem0g = 在 Mem0 之上加图记忆（实体节点/关系边/Neo4j） | ✓ | txt:137-138, 217-221, 274 | |
| P5 | §2.1 | 每来一对新消息 (m_{t-1},m_t) 触发一次抽取；"incremental processing paradigm"（§2.1, p.3） | ✓ | txt:147 "incremental processing paradigm"；txt:150-151 "initiates upon ingestion of a new message pair" | p.3 正确 |
| P6 | §2.1 | "逐 turn-pair 触发，不是攒一大段对话再批量处理" | ✓ | txt:151-152 "This pair typically consists of a user message and an assistant response, capturing a complete interaction unit" | 推论正确 |
| P7 | §2.1 | prompt P = (S, {m_{t-m}..m_{t-2}}, m_{t-1}, m_t)（§2.1，**p.3**） | ◐ | 公式在 txt:176 = **p.4** | 内容 ✓，页码应为 p.4 |
| P8 | §2.1 | 会话摘要 S 由"独立的异步摘要生成模块周期性刷新"+引文（§2.1，**p.3**） | ◐ | txt:170-173 逐字命中，位于 **p.4**（句子起点 txt:153 在 p.3） | 内容 ✓，页码跨页应写 p.3-4 或 p.4 |
| P9 | §2.1 | 最近 m 条消息提供"细粒度时序上下文"，m 是超参数 | ✓ | txt:168-169；txt:173-175 "granular temporal context that may contain relevant details not consolidated in the summary" | |
| P10 | §2.1 | φ 由 LLM 实现，φ(P) 产出 Ω={ω1..ωn}（p.3-4） | ✓ | txt:176-179，p.4 | |
| P11 | §2.1 | "调不调 LLM：调，φ 本身就是一次 LLM 调用" | ✓ | txt:176-177 "an extraction function ϕ implemented via an LLM" | |
| P12 | §2.1 | m=10，LLM 统一 GPT-4o-mini（§2.1 末段，p.5） | ✓ | txt:207-209，p.5 | 页码正确 |
| P13 | §2.1 | 更新阶段先检索 top-s 语义最相似记忆（向量 embedding），s=10（§2.1，p.5） | ◐ | s=10 在 txt:208（p.5）✓；"retrieves the top s ... using vector embeddings" 在 txt:183-184 = **p.4** | 两个事实分居两页，单标 p.5 不完整 |
| P14 | §2.1 | tool call 四操作（ADD/UPDATE/DELETE/NOOP）整段引文（§2.1，p.4） | ✓ | txt:184-189，p.4 | **逐字一致，无一字出入** |
| P15 | §2.1 | "论文特别强调不用单独**训练**一个分类器" | ◐ | txt:189 原文 "Rather than using a separate classifier" | 原文只说 "using"，"训练"是译入的 |
| P16 | §2.1 | Algorithm 1 ClassifyOperation 顺序：①不相似→ADD ②矛盾→DELETE ③补充→UPDATE ④否则→NOOP（Appendix B，p.21） | ✓ | txt:1072-1082，p.21 | 顺序完全一致 |
| P17 | §2.1 | SemanticallySimilar/Contradicts/Augments 只有函数名，没展开实现 | ✓ | txt:1073-1078 | |
| P18 | §2.1 | 存自然语言事实；引文 "The vector database employs dense embeddings to facilitate efficient similarity search during the update phase."（§2.1 末段，p.5） | ✓ | txt:209-210，p.5 | 逐字一致 |
| P19 | §2.1 | Mem0 ≈7k tokens/对话；原文直塞 ≈26k（"amounts to roughly 26k tokens on average"）（§4.5，p.14） | ✓ | txt:695-696；txt:701-702，均 p.14 | |
| P20 | §2.2 | G=(V,E,L)：节点=实体、边=关系、标签=语义类型（§2.2，p.5） | ✓ | txt:217-221，p.5 | |
| P21 | §2.2 | 实体节点三部分（类型/embedding/含创建时间戳的元数据）；三元组 (v_s,r,v_d) | ✓ | txt:223-227，p.5 | |
| P22 | §2.2 | 两阶段抽取：实体抽取器(LLM) + 关系生成器(LLM)（§2.2，p.5-6） | ✓ | txt:228-236（p.5）；txt:243-251（p.6） | 跨页标注正确 |
| P23 | §2.2 | 新三元组：源/目标各算 embedding，找相似度超阈值 t 的已有节点，可新建两个/新建一个/都复用（p.6） | ✓ | txt:253-257，p.6 | |
| P24 | §2.2 | LLM update resolver 把过时关系"标 invalid 而非物理删除"+引文（p.6） | ✓ | txt:257-260，p.6 | 逐字一致 |
| P25 | §2.2 | "图数据库用 Neo4j；实体抽取器和更新模块都用 GPT-4o-mini（带 function calling）"（§2.2，**p.7**） | ✗ | txt:274-275 位于 **p.6**（Neo4j 脚注 txt:293-294 也在 p.6 底部）；p.7 = txt 298-351，全是 §3.1 尾 + §3.2 + §3.3，无 §2.2 内容 | 内容 ✓，页码错 |
| P26 | §2.2 | Mem0g ≈14k tokens/对话，约 Mem0 两倍（§4.5，p.14） | ✓ | txt:696-698，p.14 | |
| P27 | §2.2 | Zep >600k tokens/对话（Mem0g 的 40+ 倍），因每节点缓存完整摘要+边上存事实 | ✓ | txt:698-701；600/14 ≈ 42.9 | |
| P28 | §3.1 | "论文对查询时怎么检索没有单独给一个像 Mem0g 那样详细的小节…能确认的信息分散在两处" | ◐ | §2.1（txt:145-210）确无检索小节 ✓；但正文还有第三处提及：txt:671-672（§4.4, p.13）"our selective memory retrieval mechanism … dynamically identifies and retrieves only the most salient information rather than fixed-size chunks" | "两处"应为三处 |
| P29 | §3.1 | 更新阶段的检索是写入流程内部的检索，不是回答问题时的检索 | ✓ | txt:180-184 明确处于 "the update phase" 语境 | |
| P30 | §3.1 | "论文没有单独给出回答问题时的 top-k 数值或算法细节" | ✓ | 全文 `top k` 仅 txt:383（RAG baseline），`top s` 仅 txt:183（update phase） | 否定式断言，已实际证伪失败＝成立 |
| P31 | §3.1 | Appendix A 模板含 "Memories for user {speaker_1_user_id}: {speaker_1_memories}"（p.19） | ✓ | txt:969-970，p.19 | |
| P32 | §3.1 | "论文全文没有描述任何检索→反思→再检索的循环" | ✓ | 全文 grep `iterativ|reflect|multi-step|agentic|feedback loop`：命中处均为形容词或他人系统描述（txt:82,469,483,498,573,669,854,1154），无 Mem0 自身的迭代检索机制 | 否定式断言成立 |
| P33 | §3.1 | "摘要和引言部分反复用 'dynamically extracting, consolidating, and retrieving salient information' 这类措辞" | ◐ | 摘要 txt:14 逐字命中；**引言 txt:117 是 "dynamically captures, organizes, and retrieves salient information"**（措辞不同）；原句变体另见结论 txt:720 | "引言"处措辞对不上 |
| P34 | §3.1 | 模板要求 Think step by step / 先看时间戳找证据 / 答案 <5-6 词 | ✓ | txt:957；txt:959-967；txt:955 | |
| P35 | §3.1 | "（<5-6 词）这是 LOCOMO 评测协议本身的要求，不是 Mem0 系统的通用行为" | ◐ | 该行写在 Mem0 自己的 Results Generation 模板里（txt:955）；论文未说这是 LOCOMO 的要求，§3.1（txt:286-303）也没有答案长度约定 | 属推断，论文无据 |
| P36 | §3.2 | Mem0g 双路检索：entity-centric + semantic triplet（§2.2，**p.6-7**） | ◐ | txt:262-272 **全部在 p.6** | 内容 ✓，p.7 部分不存在 |
| P37 | §3.2 | "论文明确指出这两条路都依赖语义相似度"，引 "This dual retrieval mechanism enables Mem0g to handle both…"（§2.2，p.7） | ◐ | 引文逐字命中 txt:271-272，但**该句并未陈述"两路都依赖语义相似度"**；该结论要由 txt:263（"leverages semantic similarity to locate corresponding nodes"）+ txt:266-268（"encoding the entire query as a dense embedding vector"）推出。页码亦应为 p.6 | 引文与被支撑的断言不对位 |
| P38 | §3.2 | Mem0g 模板多 "Relations for user … {speaker_1_graph_memories}" 与 "Analyze the knowledge graph relations…"（p.19-20） | ◐ | txt:1009-1010、txt:1001 逐字命中，但整个 Mem0g 模板框（txt:989-1020）**全在 p.20** | 内容 ✓，不跨 p.19 |
| P39 | §4 边界说明 | 论文没有明确画记忆系统/Agent 边界，也没说对外暴露类似 add/search 的 API | ✓ | 全文核对：仅 Appendix A 模板隐含"检索"与"生成"两步分离；无接口/API 描述 | 否定式断言成立 |
| P40 | §5 | RAG baseline 明确给出 k∈{1,2}（§3.3，p.8） | ✓ | txt:385，p.8 | 页码正确 |
| P41 | §5 | "Appendix A 只给了'结果生成''LLM 裁判''OpenAI 基线'**三个**提示词模板" | ◐ | 实为 **4 个**模板框：txt:890 (Judge)、txt:930 (Results Generation Mem0)、txt:989 (Results Generation Mem0g)、txt:1025 (OpenAI ChatGPT) | 文档 §3.2 自己单独引过 Mem0g 那一框，此处口径不一致 |
| P42 | §5 | 没有印出抽取 prompt 和更新判断 prompt 的实际文本 | ✓ | Appendix A 四框内容已逐框读完，确无 | |
| P43 | §5 | Mem0g "可配置相关性阈值"与节点阈值 t 均无具体数值 | ✓ | txt:255 "above a defined threshold 't'"；txt:269 "a configurable relevance threshold" | |
| P44 | §6 | A-Mem\* 脚注引文（Table 1 脚注，p.9） | ✓ | txt:417-418，p.9 | 逐字一致 |
| P45 | §6 | 引文 "conducted 10 independent runs for each method on the entire dataset"（§3.2，**p.8**） | ✗ | txt:324-325 位于 **p.7**（p.7 = txt 298-351） | 引文 ✓，页码错 |
| P46 | §6 | Algorithm 1 第 11-12 行：`InformationContent(f) > InformationContent(mi)` 则替换 | ✓ | txt:1060-1061 | 行号（伪代码内编号）也对 |

**小计**：✓ 32 / ✗ 2 / ◐ 11 / ? 1 = 46

### 2.2 `code-architecture.md`

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| C1 | 头注 | HEAD `dae67f74`；`pyproject.toml` 声明 `mem0ai==2.0.20` | ✓ | `git rev-parse --short HEAD` = `dae67f74`；`pyproject.toml:6-7` name=mem0ai / version=2.0.20 | |
| C2 | 头注 | "核心逻辑集中在 `mem0/memory/main.py`（`Memory` 类，约 3700+ 行）" | ◐ | 文件共 **3868** 行；`class Memory(MemoryBase)` 在 `main.py:487`，`class AsyncMemory(MemoryBase)` 在 `main.py:2172` → `Memory` 类本身约 **1685** 行 | 把文件行数当成类行数 |
| C3 | §1 | 写入"每次调用只用 1 次 LLM" | ◐ | 默认 `infer=True`（`main.py:770`）路径下确为 1 次（`main.py:940-962`）✓；但 `infer=False` 分支（`main.py:880-914`）**0 次 LLM**，逐条消息原样入库 | 缺 infer=False 这个分支 |
| C4 | §1 | "只增不改、不删" | ✓ | 自动抽取路径无任何 UPDATE/DELETE 决策（`main.py:1013-1075` 只有 insert）；`_add_to_vector_store` 不调用 `_update_memory`/`_delete_memory` | 指自动路径，成立 |
| C5 | §1 | 检索 = 语义 + BM25 + 实体加分三通道加权合并 top-k | ✓ | `main.py:1640-1687`；`utils/scoring.py:94-119` | |
| C6 | §1 / §6① | 四操作机制是"定义了但**零调用点**的死代码" | ◐ | `mem0/` 包内确实零调用点（仅 `prompts.py:176` 定义、`prompts.py:406` 定义、`prompts.py:409` 自引用）✓；但仓库内 `tests/configs/test_prompts.py:11,18,24,32,43` 仍在调用并断言它 | 文档已把范围限定在 `mem0/` 包，故结论成立；"零调用点"宜写成"生产代码零调用点" |
| C7 | §1 / §6② | 图记忆 Mem0g "整个模块都不存在" | ✓ | `find mem0 -iname "*graph*"` 无结果；无 `graph_memory.py`；`MemoryConfig`（`configs/base.py:29-57`）无 graph/graph_store 字段 | 实质结论成立（证据链问题见 C51） |
| C8 | §2 | 触发时机：`Memory.add(messages, user_id=..., ...)`（`main.py:760`） | ✓ | `main.py:760-773` | 行号精确 |
| C9 | §2 | `servers/mem0/server.py:509` 的 `add_conversation` 把一整个 session 的 turns 拼成 list 一次性传给 `add()` | ✓ | `server.py:509` def；`server.py:513` 拼 messages；`server.py:521` `_mem().add(messages, user_id=..., metadata=...)` 单次调用 | 行号精确 |
| C10 | §2 存的是什么 | "**不是原始对话**、不是摘要、也不是向量本身" | ✗ | **原始对话被逐条持久化**：`main.py:1193`（同步）/ `main.py:2851`（异步）`self.db.save_messages(messages, session_scope)`；表结构 `mem0/memory/storage.py:134-141` `CREATE TABLE IF NOT EXISTS messages (id, session_scope, role, content, name, created_at)`；下一次 `add()` 的 Phase 0 再读回（`main.py:920`） | 这是代码里唯一与论文"最近 m 条消息"对应的机制，被整段漏掉 |
| C11 | §2 存的是什么 | 每条事实"外加…一份 `linked_memory_ids`（软链接到相关老记忆的 ID 列表）" | ✗ | 记忆 payload 只写 data / text_lemmatized / hash / created_at / updated_at / attributed_to（`main.py:1029-1037`）；同步 `main.py:1015-1039` 与异步 `main.py:2673-2697` **都只读 `mem.get("text")` 和 `mem.get("attributed_to")`**，LLM 按 `prompts.py:936` 吐出的 `linked_memory_ids` 被直接丢弃。真正落盘的 `linked_memory_ids` 在 **entity_store 的实体行**上（`main.py:1157-1159, 1175`），由 spaCy 实体共现自动生成 | 归属对象错（memory→entity），且 LLM 那份是死输出 |
| C12 | §2 | "完整写入流程分 **8 个阶段（Phase 0-7）**" | ✗ | 代码是 **Phase 0–8 共 9 段**：`main.py:918/923/940/991/1005/1045/1086/1192`（异步同构 `2579/2584/2602/2651/2664/2703/2746/2850`）。文档表格漏掉 `# Phase 8: Save messages + return` | 漏掉的正是 C10 那一步 |
| C13 | §2 Phase 0 | 取该 scope 最近 10 条历史消息（`db.get_last_messages(session_scope, limit=10)`），只用来消解代词/指代，**不是**论文的会话摘要 S（`main.py:918-920`） | ✓ | `main.py:920` 逐字命中；用途见 `prompts.py:521` "Recent messages (up to 20) preceding New Messages. Use to resolve references and pronouns in New Messages." | 行号精确 |
| C14 | §2 Phase 1 | 新消息整体 embedding → 向量库捞 `top_k=10` 已有记忆作去重/关联参考（`main.py:923-929`） | ✓ | `main.py:925` embed；`main.py:926-931` search(top_k=10)；`main.py:936-938` 映射成 `existing_memories` 喂 prompt | 实际块为 923-931 |
| C15 | §2 Phase 2 | system prompt **固定**用 `ADDITIVE_EXTRACTION_PROMPT`（`main.py:940-953`；`prompts.py:468`） | ◐ | `main.py:942` 赋值 ✓，但 `main.py:941-944`：`is_agent_scoped` 为真时 `system_prompt += AGENT_CONTEXT_SUFFIX`（`prompts.py:947`） | "固定"需加限定 |
| C16 | §2 Phase 2 | "开头第一句就是 'Your sole operation is ADD'"（`prompts.py:472`） | ◐ | 短语确在 `prompts.py:472` ✓，但它是该段**第二句**；第一句是 "You are a Memory Extractor — a precise, evidence-bound processor…" | |
| C17 | §2 Phase 3 | 抽取结果一次性批量 embedding（`main.py:991`） | ✓ | `main.py:991` 注释 + `main.py:994` `embed_batch` | 行号精确 |
| C18 | §2 Phase 4-5 | `hashlib.md5(text)` 与已有/本批哈希比对，重复直接跳过、不触发任何更新（`main.py:1005-1043`） | ✓ | `main.py:1020` md5；`main.py:1021-1023` `continue`；`main.py:1007-1011` 建 existing_hashes | 行号区间精确 |
| C19 | §2 Phase 6 | 写向量库 + SQLite `history` 表（只记审计、**不参与检索**）；`event` 硬编码 `"ADD"`（`main.py:1045-1075`，`event="ADD"` 在 `main.py:1070`） | ✓ | `main.py:1051-1055` insert；`main.py:1065-1077` history；`main.py:1070` `"event": "ADD"`；检索路径 `_search_vector_store`（1628-1731）全程不碰 `self.db` | 行号精确；"不参与检索"经调用链核实成立 |
| C20 | §2 Phase 7 | spaCy 抠实体 → 与已有实体库语义匹配（**阈值 0.95**）决定合并/新建 → 写独立 entity collection；`entity_store` 懒加载（`main.py:559-580`） | ✓ | `main.py:1089` `extract_entities_batch`；`main.py:1152` `matches[0].score >= 0.95`；`main.py:1154-1177` 合并/新建；`main.py:558-580` `@property entity_store` + `VectorStoreFactory.create` | 全部命中 |
| C21 | §2 | 模板留了 "## Summary" 段（`prompts.py:496`）、函数支持 `summary=`（`prompts.py:1016-1024`） | ✓ | `prompts.py:496`；`prompts.py:1016-1018` 签名首两参即 `summary=None, recently_extracted_memories=None` | |
| C22 | §2 / §6④ | 两个真实调用点（`main.py:948-953` 同步 / `main.py:2610-2615` 异步）**都没传** `summary=` 与 `recently_extracted_memories=`；全仓无第三处 | ✓ | 逐字读过两处；`grep -rn generate_additive_extraction_prompt` 全仓仅 `main.py:23`(import)、`948`、`2610`、`prompts.py:1016`(定义) | 行号精确，否定式断言成立 |
| C23 | §2 | "## Recently Extracted Memories" 本该是"session 内近 20 条已抽取记忆的去重参考"（`prompts.py:501`） | ✓ | `prompts.py:501-503` "Memories already captured from recent messages in this session (up to 20). This is your primary deduplication reference" | |
| C24 | §2 | `update()`（`main.py:1815`）/`delete()`（`main.py:1869`）是纯 CRUD，`add()` 自动流程从不调用 | ✓ | `main.py:1815`/`1869` def 精确命中；`1845-1867` / `1876-1888` 为纯 CRUD；`_add_to_vector_store` 全段无调用 | |
| C25 | §3 | `search()` 默认值 `top_k=20, threshold=0.1, rerank=False, explain=False`（`main.py:1379-1389`） | ✓ | `main.py:1379` def，`1383/1385/1386/1387` | 实际全部为 keyword-only 参数（`main.py:1382` 的 `*`） |
| C26 | §3 | `_search_vector_store` 在 `main.py:1628` | ✓ | `main.py:1628` | |
| C27 | §3 | 三样输入：query embedding / lemmatized query / spaCy 实体 | ✓ | `main.py:1634` lemmatize、`1635` extract_entities、`1638` embed | |
| C28 | §3 | "三条通道**设计上并行跑**" | ◐ | 代码是顺序 Step3→4→5→6（`main.py:1640-1664`），无跨通道并发；唯一并发是实体通道**内部**的 `ThreadPoolExecutor(max_workers=4)`（`main.py:1778`） | 作"三路并列"读可接受，作"并发"读不成立 |
| C29 | §3 | 语义通道 over-fetch `max(top_k*4, 60)`（`main.py:1641`） | ✓ | `main.py:1641` `internal_limit = max(limit * 4, 60)` | 行号精确 |
| C30 | §3 | BM25 调 `vector_store.keyword_search(...)`（`main.py:1646`） | ✓ | `main.py:1646` 为该 Step 注释，调用在 `main.py:1647` | 块级锚点，偏 1 行 |
| C31 | §3 | 基类默认 `return None`（`vector_stores/base.py:68-80`） | ◐ | 方法定义 `base.py:68`，但 `return None` 在 **`base.py:83`**，落在所引区间之外 | 应写 68-83 |
| C32 | §3 | 只有部分后端（Qdrant/Pinecone/pgvector/ES/MongoDB/Weaviate/Milvus/OpenSearch 等十几种）覆写 | ✓ | 实测 15 个文件含 `def keyword_search`：azure_ai_search / azure_mysql / baidu / databricks / elasticsearch / milvus / mongodb / opensearch / pgvector / pinecone / qdrant / redis / upstash_vector / vertex_ai_vector_search / weaviate | 点名的 8 个全部在列 |
| C33 | §3 | **chroma 没有覆写**，用 chroma 这条通道恒为空 | ✓ | `vector_stores/chroma.py` 无 `def keyword_search`（全部 def 已列出核对）；基类返回 None → `main.py:1653` `if keyword_results is not None` 恒假 → `bm25_scores` 恒空 | 否定式断言成立 |
| C34 | §3 | 实体加成阈值 ≥0.5（`main.py:1661-1663`）；`_compute_entity_boosts` 定义在 `main.py:1733` | ✓ | `main.py:1661-1664` 调用；`main.py:1733` def；阈值实际在 `main.py:1793` `if similarity < 0.5: continue`（docstring `main.py:1738` 亦述） | |
| C35 | §3 | `extract_entities()` 在 spaCy 不可用时直接返回空列表（`entity_extraction.py` 顶部 docstring） | ✓ | `utils/entity_extraction.py:15` "Returns `[]` if spaCy is unavailable"；实现 `751-758` `if nlp is None: return []`；`spacy_models.py:44-66` 加载失败返回 None | |
| C36 | §3 | `score_and_rank()` 做**加法**融合（非 max 非 RRF），分母自适应 1.0/2.0/2.5/1.5 | ✓ | `utils/scoring.py:97-101`（`max_possible` 累加 1.0 + 1.0 + `ENTITY_BOOST_WEIGHT=0.5`）；`scoring.py:118-119` `raw_combined = semantic + bm25 + entity_boost; combined = min(raw/max_possible, 1.0)` | 四种分母组合与文档完全一致 |
| C37 | §3 | `threshold` 只卡语义分，BM25/实体分再高也捞不回来 | ✓ | `scoring.py:110-112` `semantic_score = result.get("score") or 0.0; if semantic_score < threshold: continue` | |
| C38 | §3 | 一步到位，没有 agentic 检索循环 | ✓ | `main.py:1494-1496` 单次 `_search_vector_store`，无循环/回灌 | |
| C39 | §3 | mem0 自己不生成答案，`search()` 只返回 `{id, memory, score, metadata...}` 结构化列表 | ✓ | `main.py:1708-1727` 构造 MemoryItem dict；`main.py:1522` `return {"results": original_memories}`；全类无 answer 生成 | |
| C40 | §3 | "retrieve 阶段本身不调 LLM（**只调一次 embedding** 把 query 向量化）" | ◐ | 不调 LLM ✓（1628-1731 无 `self.llm`）；但 embedding 最多 **2 次**：query 一次（`main.py:1638`）+ 实体文本 `embed_batch` 一次（`main.py:1761`）。本次评测环境无 spaCy，`query_entities` 恒空（`main.py:1663`）才使其恒为 1 次 | 结构上不是"只一次" |
| C41 | §3 | rerank 需 `rerank=True` 且配了 reranker（`main.py:1500`）；`MemoryConfig.reranker` 默认 `None`（`configs/base.py`） | ✓ | `main.py:1500` `if rerank and self.reranker and original_memories:`；`configs/base.py:46-49` `reranker: Optional[RerankerConfig] = Field(..., default=None)` | |
| C42 | §3 | 本次实测环境 `import spacy` 失败、未装 `mem0ai[nlp]` | ✓ | `memory-bench/.venv/lib/python3.12/site-packages/` 下无任何 `spacy*` 目录 | venv 的 python 解释器在本 sandbox 不可执行，改以 site-packages 目录清单核实，结论一致 |
| C43 | §3 | `DEPLOY.md` 的部署矩阵没提这件事 | ✓ | `grep -niE "spacy|\[nlp\]|en_core_web" DEPLOY.md` 无命中；`DEPLOY.md:92` 只写 "mem0 \| 6/6 \| ~4s \| 主 venv + chroma" | |
| C44 | §5 | `_create_procedural_memory` 在 `main.py` 约 2000 行附近，未验证是否 ADD-only / 是否另调 LLM | ✓ | 位置属实：`main.py:1993`（异步 `main.py:3671`）。**本次代为核实**：额外调 1 次 LLM（`main.py:2014`），单条落库，`event` 为 `"ADD"`（`main.py:2034`），确为 ADD-only；且只有 `agent_id` 非空且 `memory_type="procedural_memory"` 时才走这一支（`main.py:853`） | 文档诚实标注"未验证"，此处补齐 |
| C45 | §5 | `get_bm25_params()` sigmoid 分段（3/6/9/15 词） | ✓ | `utils/scoring.py:31-40`：≤3→(5.0,0.7)、≤6→(7.0,0.6)、≤9→(9.0,0.5)、≤15→(10.0,0.5)、else→(12.0,0.5)；无注释无 issue 链接 | 实为 5 段；steepness 在后三段同为 0.5 |
| C46 | §5 | 评测 venv 装的是 `mem0ai==2.0.18`，与 HEAD 同属 "V3 PHASED BATCH PIPELINE"，两版本 `chroma.py` 都无 `keyword_search` | ✓ | `.venv/.../mem0ai-2.0.18.dist-info` 存在；`grep -c "V3 PHASED BATCH PIPELINE"` 装机版 `main.py` = 2；`grep -c "def keyword_search"` 装机版 `chroma.py` = 0 | |
| C47 | §6① | `DEFAULT_UPDATE_MEMORY_PROMPT`（`prompts.py:176`）、`get_update_memory_messages()`（`prompts.py:406`） | ✓ | 两处行号精确命中 | |
| C48 | §6① | "在全部 **9 处**赋值点（`main.py:909, 1070, 1196, 2034, 2570, 2728, 2854, 3729`）无一例外硬编码为 `\"ADD\"`" | ◐ | 所列 **8** 个行号全部命中且确为 `"event": "ADD"`；文档自称 9 处但只列了 8 个。另有 4 处以**位置参数**把 `"ADD"` 传给 `add_history`（`main.py:1082, 1985, 2740, 3662`），合计 12 处 | 计数与清单不自洽 |
| C49 | §6① | "代码里找不到任何地方会写入 `\"UPDATE\"`、`\"DELETE\"` 或 `\"NOOP\"`" | ✗ | **`main.py:2084`** `self.db.add_history(memory_id, prev_value, data, "UPDATE", ...)`（`_update_memory`）；**`main.py:2116`** `... None, "DELETE", ..., is_deleted=1`（`_delete_memory`）；异步同构 **`main.py:3781`** / **`main.py:3815`**。这四处走的是手动 CRUD `update()`/`delete()` 路径（`main.py:1865` / `1882` 调入） | 因是位置传参躲过了 `event="UPDATE"` 式 grep。只有 `"NOOP"` 确实全仓无写入。文档的实质结论（自动路径无 LLM 判定的 UPDATE/DELETE）仍成立 |
| C50 | §6① | commit `a488e190`（2026-04-14，"feat(oss): port v3 pipeline with hybrid search, entity extraction, and additive scoring #4805"）一次性把整个 update 阶段连根拔掉 | ✓ | `git log -1 a488e190` 元数据逐字命中；`git show a488e190^:mem0/memory/main.py` 显示改动前 `main.py:20` import、`601`/`1717` 调用 `get_update_memory_messages`，`651/672/684` 与 `1770/1788/1794` 有 UPDATE/DELETE/NONE 分支 | 考古结论扎实（旧版用 `"NONE"` 不是 `"NOOP"`） |
| C51 | §6② | "在 `mem0/` 整个包里搜 `graph`/`Neo4j`/`Memgraph`/`Kuzu`/`Mem0g`——**没有任何一个匹配**（已用文件名 glob `*graph*` 和内容 grep 双重确认）" | ✗ | 字面不成立：`mem0/AGENTS.md:54` "\| Graph stores \| 4 \| Neo4j, Memgraph, Kuzu, Apache AGE \|"；`mem0/AGENTS.md:103-105` 仍整段描述 "Graph memory … configured through the `graph` section of `MemoryConfig`"（陈旧文档）；`mem0/exceptions.py:396` `details={"package": "kuzu", "feature": "graph_store"}`；`mem0/vector_stores/neptune_analytics.py` 通篇 graph；`mem0/configs/prompts.py:858` "build a graph of related memories" | 文件名 glob `*graph*` 确实无结果 ✓，`MemoryConfig` 确无 graph 字段 ✓，**实质结论成立**，但"没有任何一个匹配"这句被证伪 |
| C52 | §6② | 同一 commit 里 TS SDK 的 `graph_memory.ts`(675) / `graphs/tools.ts`(267) / `graphs/utils.ts`(116) / `graphs/configs.ts`(30) 被整体删除 | ◐ | 四个行数逐一命中 ✓；但同一 commit **同时删掉了体量大得多的 Python 图记忆**：`mem0/memory/graph_memory.py`(744)、`memgraph_memory.py`(708)、`kuzu_memory.py`(732)、`apache_age_memory.py`(595)、`mem0/graphs/tools.py`(371)、`configs.py`(136)、`utils.py`(97)、`graphs/neptune/*`(~1500) | 只举 TS 会让人误以为 Python 侧本来就没有图记忆 |
| C53 | §6② | `docs/platform/platform-vs-oss.mdx:70` 引文 | ✓ | 该行逐字含 "Removed. OSS previously connected external graph stores (Neo4j, Memgraph, Kuzu, Apache AGE); that integration was dropped when the v3 pipeline landed." | 原文加粗的是 "Graph Memory" 而非 "Removed"，无实质影响 |
| C54 | §6② | `docs/open-source/configuration.mdx:97` 引文 | ✓ | 该行逐字含 "Graph memory is not part of OSS in either language: it is a built-in Mem0 Platform feature." | |
| C55 | §6③ | "论文怎么写：base Mem0 **只说**'按语义相似度检索'" | ◐ | 与本仓 `paper-architecture.md` §3.1（"论文没有单独给出这一步的 top-k 数值或算法细节"）自相矛盾；论文对 base Mem0 **查询时**检索根本没有描述（见 P30） | 两份文档口径不一致 |
| C56 | §6④ | 模板留 "## Summary" 段（`prompts.py:496`）、签名支持 `summary=`（`prompts.py:1016`）、两调用点都没传、grep 确认无第三处 | ✓ | 全部命中，见 C21/C22 | |
| C57 | 附 | 封装层 `_probe_channels()` 用三个信号钉死通道可用性并写进 trace | ✓ | `servers/mem0/server.py:279-334`；BM25 探针用 `type(memory.vector_store).keyword_search is not VectorStoreBase.keyword_search`（`server.py:290`）；`server.py:262` `_probe_spacy()` | |
| C58 | 附 | `_search_params()` 把 top_k/threshold/rerank/explain 全部显式传给 `search()`，不吃包默认值 | ✓ | `server.py:242-253`，`server.py:600,605` | 备注：`explain` 默认 **True**（与库默认 False 相反）；`top_k` 由评测循环传 5（不是库默认 20）——"库默认值当锚点"只对 threshold/rerank 成立 |
| C59 | 附 | 因 `mem0/llms/openai.py:83` 只返回 content 丢弃 usage，封装层 monkeypatch `chat.completions.create` 拦 `response.usage` | ✓ | `mem0/llms/openai.py:83` `return response.choices[0].message.content`；`server.py:174` 取原函数、`server.py:187` `_collect_usage(getattr(resp,"usage",None))`、`server.py:190` 覆写 | 行号精确 |
| C60 | 附 | `reset()` 必须以 `_drop_memory()` 收尾（"P1 修复（2026-08-19 核查）"），否则悬挂句柄致 `add()` 静默失败 | ✓ | `server.py:676-695`（注释 678-679 逐字命中；`_drop_memory()` 在 682/688/691）；`_drop_memory` 定义 `server.py:447`；`DEPLOY.md:134` 亦记录同一 P1 | |
| C61 | 附 | 封装层没有任何 graph 相关调用，评测里的 mem0 只能是纯 Mem0 | ✓ | `server.py` 全文无 graph/Neo4j 调用；上游亦无该能力（C7） | |

**小计**：✓ 45 / ✗ 5 / ◐ 11 / ? 0 = 61

---

## 3. 步骤清单 — 论文侧

> 按论文描述的实际执行顺序。Mem0g（§2.2）在论文里是**与 base Mem0 并列的第二套架构**（不是可选插件），但两者共享 §2.1 的写入触发粒度，故分列。

### 3.1 写入侧 — base Mem0（§2.1）

| # | name（论文原称） | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| W1 | ingestion of a new message pair | 每 turn-pair（(m_{t-1}, m_t)，通常一问一答） | 新消息对 → 进入抽取流水线 | no | - | `P-INTAKE` |
| W2 | asynchronous summary generation module | 离线/异步周期性（独立于主流程，周期未给） | 整段对话历史 → 会话摘要 S | 1 次（摘要器；论文未给 prompt/模型/次数） | database（读历史、写 S） | `P-AGGREGATE` |
| W3 | 拼 prompt P = (S, {m_{t-m}..m_{t-2}}, m_{t-1}, m_t) | 每 turn-pair | S + 最近 m=10 条 + 新消息对 → prompt P | no | database（读 S、读最近消息） | `P-ASSEMBLE` |
| W4 | extraction phase（函数 φ） | 每 turn-pair | P → 候选事实集合 Ω={ω1..ωn} | 1 次（GPT-4o-mini，抽取器） | - | `P-EXTRACT` |
| W5 | retrieve the top s semantically similar memories | 每个候选事实 ω_i | ω_i → top-s=10 条老记忆 | no | vector DB（dense embedding） | `P-EMBED` > `P-DENSE` |
| W6 | tool call → ClassifyOperation（ADD/UPDATE/DELETE/NOOP） | 每个候选事实 ω_i | ω_i + s 条老记忆 → 四选一操作 | 1 次（GPT-4o-mini function calling，判定器；与 W4 同模型不同调用） | - | `P-CONFLICT`（含 `P-DEDUP` 语义：NOOP 即去重） |
| W7 | execute the provided operations | 每个候选事实 ω_i | 操作 → 更新后的记忆库 | no | vector DB | `P-PERSIST`（DELETE 分支＝`P-EVICT`） |

### 3.2 写入侧 — Mem0g 图记忆（§2.2）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| G1 | entity extractor module | 每 turn-pair（输入文本） | 对话文本 → 实体集合 + 类型 | 1 次（GPT-4o-mini，function calling） | - | `P-EXTRACT` |
| G2 | relationship generator | 每 turn-pair | 实体 + 上下文 → 关系三元组 (v_s, r, v_d) | 1 次 | - | `P-EXTRACT` |
| G3 | node embedding + threshold-`t` 节点匹配 | 每条新三元组 | 源/目标实体 → 复用已有节点或新建 | no | Neo4j + embedding | `P-EMBED` > `P-DEDUP`（阈值 t，数值未给） |
| G4 | establish the relationship with appropriate metadata | 每条新三元组 | 节点对 + 关系标签 → 图边（含创建时间戳） | no | Neo4j | `P-LINK` |
| G5 | conflict detection + LLM-based update resolver | 每次新信息到来 | 新关系 + 已有关系 → 过时关系标 `invalid`（不物理删除） | 1 次（GPT-4o-mini，update resolver） | Neo4j | `P-CONFLICT`（失效标记/版本化，非驱逐） |
| G6 | 落图 | 同上 | → G=(V,E,L) | no | Neo4j | `P-PERSIST` |

### 3.3 检索侧 — base Mem0（§2.1/Appendix A）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| R1 | （论文未命名）memory retrieval | 每 query | query → `{speaker_N_memories}` 文本块 | no（论文未说） | vector DB | `P-DENSE`（**论文未给 top-k / 阈值 / 算法，此为可确认索引机制下的推断**） |
| R2 | Results Generation prompt（Appendix A） | 每 query | 记忆文本块 → 问答 prompt | no | - | `P-ASSEMBLE` |
| R3 | 生成答案 | 每 query | prompt → <5-6 词答案 | 1 次（答题模型；与抽取用的 GPT-4o-mini 是否同一个论文未明说） | - | `P-GENERATE`（**记忆系统边界之外**） |

### 3.4 检索侧 — Mem0g 双路（§2.2）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| R4 | entity-centric method | 每 query（与 R5 并行） | query → 关键实体 → 锚点节点 → 出入边子图 | no | Neo4j + embedding | `P-QUERYPARSE` > `P-DENSE`（锚点定位） > `P-GRAPHEXPAND`（出入边子图） |
| R5 | semantic triplet approach | 每 query（与 R4 并行） | query 整体 dense 向量 → 与每条三元组文本编码匹配 → 超阈值者按相似度降序 | no | Neo4j | `P-EMBED` > `P-DENSE`（含阈值截断，阈值可配、数值未给） |
| R6 | 拼进 Mem0g Results Generation 模板 | 每 query | 记忆 + `{speaker_N_graph_memories}` → prompt | no | - | `P-ASSEMBLE` |
| R7 | 生成答案 | 每 query | prompt → 答案 | 1 次 | - | `P-GENERATE`（边界之外） |

> **论文侧缺口**：R4/R5 两路的**融合方式论文完全没写**（没有 RRF、没有加权、没说各取多少条），因此**不能**标 `P-FUSE`。

### 3.5 系统边界（论文侧）

- **记忆系统本体**：W1–W7、G1–G6、R1、R4–R5。
- **边界之外**：R3/R7（答案生成，由宿主 LLM 做）；R2/R6（prompt 组装）在论文里只体现为 Appendix A 的评测模板，归属未明说，实际上是**评测脚本**一侧。
- 论文**没有**为记忆系统定义任何对外 API（无 add/search 之类），也没讨论生产部署时边界怎么切（见 P39）。

---

## 4. 步骤清单 — 代码侧

> 上游 `repo/mem0` @ `dae67f74`（v3 pipeline），默认 `infer=True` 路径。异步 `AsyncMemory` 与同步同构，行号见括号第二个。

### 4.1 写入侧 — `Memory.add()` → `_add_to_vector_store()`（`main.py:760` → `879` / `2533`）

| # | name（代码原称） | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| A0 | Phase 0: Context gathering（`main.py:918` / `2579`） | 每次 `add()` 调用（粒度由调用方定；本项目＝每 session 一次） | messages → `parse_messages()` 串 + 该 scope 最近 10 条历史消息 | no | **SQLite `messages` 表**（`get_last_messages(..., limit=10)`） | `P-INTAKE` |
| A1 | Phase 1: Existing memory retrieval（`main.py:923` / `2584`） | 每次 `add()` | 新消息整体 → embedding → 向量库 `top_k=10` 老记忆（映射成整数 id 防幻觉） | no | vector store | `P-EMBED` > `P-DENSE`（**内部去重/关联参考，不是给用户的检索**） |
| A2 | Phase 2: LLM extraction (single call)（`main.py:940` / `2602`） | 每次 `add()` | prompt（`## Summary` 空 + `## Last k Messages` + `## Recently Extracted Memories` 空 + `## Existing Memories` + `## New Messages`）→ JSON 事实列表 | **1 次**（`ADDITIVE_EXTRACTION_PROMPT`，"Your sole operation is ADD"；agent-scoped 时追加 `AGENT_CONTEXT_SUFFIX`） | - | `P-EXTRACT` |
| A3 | Phase 3: Batch embed（`main.py:991` / `2651`） | 每次 `add()` | 事实文本列表 → 向量（失败回退逐条） | no | - | `P-EMBED` |
| A4 | Phase 4+5: CPU processing + Hash dedup（`main.py:1005` / `2664`） | 每条抽出的事实 | 文本 → md5 哈希，与已有哈希/本批哈希比对，命中即跳过；同时算 `text_lemmatized`（供 BM25 用） | no | - | `P-DEDUP`（**精确哈希，非阈值**） |
| A5 | Phase 6: Batch persist（`main.py:1045` / `2703`） | 每次 `add()` | records → 向量库 insert + `history` 表 `event="ADD"` | no | vector store + SQLite `history`（审计，不参与检索） | `P-PERSIST` |
| A6 | Phase 7: Batch entity linking（`main.py:1086` / `2746`） | 每次 `add()` | 事实文本 → spaCy 实体（专有名词/引号/名词短语/NER）→ 批量 embed → entity_store `top_k=1` 匹配 → 精确命中或 score≥0.95 则并进已有实体的 `linked_memory_ids`，否则新建实体行 | no（spaCy，不是 LLM） | 独立 entity collection | `P-NLPEXTRACT`\[NEW] > `P-EMBED` > `P-DEDUP`（0.95） > `P-LINK`（entity→memory 软链） |
| A7 | Phase 8: Save messages + return（`main.py:1192` / `2850`） | 每次 `add()` | messages → **原始对话逐条落 SQLite `messages` 表** | no | SQLite `messages` | `P-PERSIST` |

> 旁支（非默认）：`infer=False`（`main.py:880-914`）→ 0 次 LLM，逐条消息原样 embed 入库；`memory_type="procedural_memory"` 且 `agent_id` 非空（`main.py:853` → `1993`）→ 另 1 次 LLM 生成一条 procedural 摘要，仍是 ADD-only。
> **代码里没有**：`P-REWRITE`、`P-META`、`P-CONFLICT`、`P-EVICT`、`P-AGGREGATE`（论文的异步摘要模块在代码里只剩 prompt 坑位，从未被填）。

### 4.2 检索侧 — `Memory.search()` → `_search_vector_store()`（`main.py:1379` → `1628` / `3293`）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| S1 | Step 1: Preprocess query（`main.py:1633-1635`） | 每 query | query → lemmatized query + spaCy 实体列表 | no | - | `P-QUERYPARSE` |
| S2 | Step 2: Embed query（`main.py:1637-1638`） | 每 query | query → 向量 | no | - | `P-EMBED` |
| S3 | Step 3: Semantic search（over-fetch）（`main.py:1640-1644`） | 每 query | 向量 → `max(top_k*4, 60)` 条候选 | no | vector store | `P-DENSE` |
| S4 | Step 4+5: Keyword search + BM25 sigmoid 归一（`main.py:1646-1659`） | 每 query（**需后端覆写 `keyword_search`；chroma 未覆写 → 恒空**） | lemmatized query → 原始 BM25 分 → sigmoid 归一到 [0,1]（分段参数按词数 3/6/9/15） | no | vector store | `~P-SPARSE` |
| S5 | Step 6: Compute entity boosts（`main.py:1661-1664` → `1733`） | 每 query 且抽到实体（**需 spaCy**） | query 实体（去重取前 8）→ 批量 embed → entity_store 各查 `top_k=500`（4 线程并发）→ 相似度 ≥0.5 的实体，其 `linked_memory_ids` 指向的记忆得加分（按被链记忆数衰减） | no | entity collection | `~P-DENSE`（实体库） + 反查实体链（只加分，不引入新候选） |
| S6 | Step 7+8: 候选集 + `score_and_rank()`（`main.py:1666-1687`；`utils/scoring.py:60-139`） | 每 query | 候选 → `combined = min((semantic + bm25 + entity)/max_possible, 1.0)`，`max_possible ∈ {1.0, 1.5, 2.0, 2.5}` 自适应；语义分 < threshold 直接淘汰；排序取 top_k | no | - | `P-FUSE`（加权和，非 RRF 非 max） > `P-SELECT`（阈值截断 + top-k） |
| S7 | 可选 rerank（`main.py:1500`） | 每 query，且 `rerank=True` **且** `self.reranker` 非空（`MemoryConfig.reranker` 默认 `None`） | 候选 → 重排 | 视 reranker 而定 | - | `~P-RERANK`（默认路径空操作） |
| S8 | Step 9: Format results（`main.py:1689-1731`，`1522`） | 每 query | → `{"results": [{id, memory, score, metadata, ...}]}` | no | - | —（**不是 `P-ASSEMBLE`：mem0 不拼 prompt、不生成答案**） |

### 4.3 封装层与 Agent 侧（`servers/mem0/server.py` / 评测循环）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| B1 | `add_conversation`（`server.py:509`） | **每 session 一次** | 整个 session 的全部 turns → 一次 `_mem().add(messages, user_id=scope_id, metadata=...)` | 触发上游那唯一 1 次抽取 | - | `P-INTAKE`（粒度收窄；比论文"每对消息一次"粗得多） |
| B2 | `_probe_channels()`（`server.py:279`） | 启动期一次 | → BM25/实体通道可用性钉进 trace | no | - | —（工程可观测性，非记忆原语） |
| B3 | `retrieve`（`server.py:584`） | 每 query | query → `memory.search(query, filters={"user_id": uid}, top_k/threshold/rerank/explain 显式传)` → envelope 列表 | no | - | 透传 S1–S8 |
| B4 | 拼 prompt + 生成答案 | 每 query | envelope → 问答 prompt → 答案 | 1 次（答题模型） | - | `P-ASSEMBLE` > `P-GENERATE`（**记忆系统边界之外**） |

### 4.4 系统边界（代码侧）

- **记忆系统本体**＝`mem0` OSS 包的 `Memory` 类，边界就是 `add()` / `search()`（另有 `get_all()` / `update()` / `delete()` / `reset()` 等纯 CRUD）。A0–A7、S1–S8 全在本体内。
- **外部服务**（mem0 借用、既不属 Agent 也不属 mem0 存储）：LLM API（仅写入阶段 1 次）、Embedding API（写入 2–3 次批量、检索 1–2 次）。
- **Agent / 评测脚本一侧**：什么时候调 `add()`、一次灌多少（B1）、检索结果怎么拼 prompt、调哪个模型答题（B4）。
- **本次实测环境的退化**：chroma 后端（BM25 通道恒空）+ 未装 spaCy（实体通道恒空）→ S4、S5、A6 三步全部失效，写入侧退化为 A0→A1→A2→A3→A4→A5→A7，检索侧退化为 S1(仅 lemmatize，无实体)→S2→S3→S6，**等价于裸向量 RAG**。

---

## 5. 论文↔代码分歧

| # | 分歧 | 分类 | 论文侧证据 | 代码侧证据 |
|---|---|---|---|---|
| D1 | 四操作（ADD/UPDATE/DELETE/NOOP）由 LLM tool call 现场判定 | **[paper-only 论文写了代码没实现]** | txt:184-192（tool call + 四操作 + "executes the provided operations, thereby maintaining knowledge base coherence and temporal consistency"）；Algorithm 1 txt:1046-1082 | `prompts.py:176` / `406` 定义仍在，但 `mem0/` 生产代码零调用点；实跑路径 `main.py:940-962` 用 `ADDITIVE_EXTRACTION_PROMPT`（`prompts.py:472` "Your sole operation is ADD"）。自动路径不会写出 UPDATE/DELETE/NOOP（手动 CRUD 路径才写，`main.py:2084/2116/3781/3815`）。旧实现于 `a488e190`(2026-04-14) 被整体替换（`git show a488e190^:mem0/memory/main.py:601,651,672,684`） |
| D2 | Mem0g 图记忆（G=(V,E,L)、Neo4j、双路检索、update resolver 标 invalid） | **[paper-only]** | txt:213-279（§2.2 全节）；Figure 3 caption txt:202-204 | `find mem0 -iname "*graph*"` 无结果；`MemoryConfig`（`configs/base.py:29-57`）无 graph 字段；`a488e190` 删除 `mem0/memory/graph_memory.py`(744) / `memgraph_memory.py`(708) / `kuzu_memory.py`(732) / `apache_age_memory.py`(595) / `mem0/graphs/*`；`docs/platform/platform-vs-oss.mdx:70` 明说 "Removed … dropped when the v3 pipeline landed" |
| D3 | 异步会话摘要模块 S（提供全局主题理解） | **[paper-only]** | txt:170-173 | `prompts.py:496` 有 `## Summary` 段、`prompts.py:1017` 有 `summary=` 形参，但全仓仅两个调用点 `main.py:948-953` / `2610-2615`，**均未传**；无任何摘要生成代码 |
| D4 | 抽取触发粒度：每对新消息 vs 调用方任意分批（本项目每 session 一次） | **[两边都有但行为不同]** | txt:150-152 "initiates upon ingestion of a new message pair (m_{t-1}, m_t)" | `main.py:760` `add(messages, ...)` 接受任意长度列表；`server.py:513,521` 把整段 session 一次性灌入 → 一个 session 一次 LLM 抽取 |
| D5 | 抽取的上下文来源：摘要 S + 最近 m=10 条 vs 只有最近 10 条 | **[两边都有但参数/成分不同]** | txt:176 `P = (S, {m_{t-m}..m_{t-2}}, m_{t-1}, m_t)`；m=10（txt:207） | `main.py:920` `get_last_messages(session_scope, limit=10)`（条数同为 10 ✓），但 S 恒为空（D3），且多了论文没有的"Existing Memories top-10"通道（`main.py:926-931`） |
| D6 | 写入时的相似记忆检索用途：喂 LLM 做四操作判定 vs 喂 LLM 做去重/链接参考 | **[两边都有但行为不同]** | txt:183-189（top-s=10 → tool call 判操作） | `main.py:926-931` top_k=10（**数值巧合一致**）→ `main.py:936-938` 只作为 `## Existing Memories` 去重/链接参考（`prompts.py:511-513`），不参与任何写操作决策 |
| D7 | 去重手段：LLM 语义判定 NOOP vs md5 精确哈希 | **[两边都有但行为不同]** | txt:188-189 "NOOP when the candidate fact requires no modification" | `main.py:1020-1023` `hashlib.md5(text)` 精确匹配才跳过；语义近似但字面不同的事实会重复入库 |
| D8 | 检索通道：纯语义（论文唯一提到的索引机制）vs 语义+BM25+实体三通道加权 | **[code-only 代码有论文没写]** | txt:209-210 只提 dense embeddings；base Mem0 查询时检索论文根本没描述（P30） | `main.py:1640-1687` + `utils/scoring.py:60-139` 三通道加法融合、自适应分母、语义阈值门 |
| D9 | 实体处理：LLM 实体抽取器 + 关系生成器建图 vs spaCy 规则/NER 抽实体只做检索加分 | **[两边都有但行为不同]** | txt:228-251（两个 LLM 模块，产出带类型的实体与关系三元组） | `utils/entity_extraction.py`（spaCy，非 LLM，产出 PROPER/QUOTED/TOPIC/IDENTIFIER 四类）；实体只挂 `linked_memory_ids` 做检索加分（`main.py:1786-1808`），**无关系边、无三元组、无图查询** |
| D10 | 冲突/时序：LLM update resolver 标 invalid 支持时序推理 | **[paper-only]** | txt:257-260 | 代码无冲突检测；`expiration_date` 是纯手动字段（`main.py:769`、`_payload_is_expired` `main.py:442`），Temporal Reasoning 明确是 Platform 专属（`docs/platform/platform-vs-oss.mdx:72`） |
| D11 | 原始对话是否保留 | **[code-only]** | 论文只说存"自然语言事实"（txt:209-210），未提保留原始对话 | `main.py:1193`/`2851` `save_messages` → SQLite `messages` 表（`storage.py:134-141`），并在下次 `add()` 读回 |
| D12 | 记忆之间的关联 | **[code-only]** | 论文里 base Mem0 的记忆是彼此独立的自然语言事实，无链接概念 | `prompts.py:513,936` 要求 LLM 输出 `linked_memory_ids`；**但代码从不读取该字段**（`main.py:1015-1039` / `2673-2697`），实际生效的链接是 entity 行上由 spaCy 共现自动生成的 `linked_memory_ids`（`main.py:1157-1159, 1175`） |
| D13 | 检索 top-k / 阈值 | **[两边都有但参数不同]** | 论文对 base Mem0 查询时未给 top-k（P30）；Mem0g 给"可配置阈值"但无数值（txt:269） | `main.py:1383-1385` `top_k=20, threshold=0.1`；内部 over-fetch `max(top_k*4, 60)`（`main.py:1641`）；实体阈值 0.5（`main.py:1793`）、实体合并阈值 0.95（`main.py:1152`）；本项目实跑 `top_k=5`（`server.py:247`） |
| D14 | 答案生成 | **[两边都有但边界不同]** | Appendix A 给出完整问答模板（txt:930-1020），暗示记忆系统交付的是"拼好的 prompt 输入" | mem0 库完全不管，只返回结构化列表（`main.py:1522`）；prompt 与答题在评测循环侧 |
| D15 | 模型 | **[两边都有但参数不同]** | 全部 LLM 操作用 GPT-4o-mini（txt:208-209） | 模型由配置注入，本项目为 `MEMBENCH_LLM_MODEL`（glm-5.3 系），`temperature=0`、`max_tokens=128000`（`server.py:385-393`） |

---

## 6. 新造的 primitive 标签

| 标签 | 含义 | 造它的理由 |
|---|---|---|
| `P-NLPEXTRACT` \[NEW] | **确定性 NLP 抽取**：用规则/统计 NLP（spaCy NER、专有名词序列、引号内容、名词短语）从文本中抽出实体或短语单元，**全程不调 LLM** | 种子词表里 `P-EXTRACT` 的定义把"抽取"绑死在 LLM 上（"LLM抽取(事实/实体/三元组/笔记/命题)"）。mem0 v3 的写入侧 Phase 7（`main.py:1089` → `utils/entity_extraction.py`）做的正是实体抽取，但零 LLM、纯 spaCy。若复用 `P-EXTRACT`，会把"这一步要不要花 LLM 调用"这个跨系统对比中最关键的成本/延迟维度抹平——而这恰恰是 mem0 论文（G1/G2 两次 LLM）与 mem0 代码（0 次 LLM）之间最大的机制差异之一（见 D9）。检索侧的 `extract_entities(query)` 已由 `P-QUERYPARSE` 覆盖，不需要新标签；写入侧没有对应项，故只新造这一个。 |

其余步骤全部复用了种子词表中的既有标签。

---

## 7. 复核统计

| 判定 | paper-architecture.md | code-architecture.md | 合计 |
|---|---|---|---|
| ✓ 属实 | 32 | 45 | **77** |
| ✗ 不实 | 2 | 5 | **7** |
| ◐ 部分属实 / 需加限定 | 11 | 11 | **22** |
| ? 无法核实 | 1 | 0 | **1** |
| **小计** | **46** | **61** | **107** |

**✗ 的 7 条**：P25（Neo4j/GPT-4o-mini 实现细节页码 p.7→p.6）、P45（"10 independent runs" 页码 p.8→p.7）、C10（"不是原始对话"）、C11（记忆记录带 `linked_memory_ids`）、C12（Phase 0-7 共 8 阶段）、C49（"找不到任何地方写入 UPDATE/DELETE/NOOP"）、C51（"mem0/ 包里搜 graph/Neo4j 没有任何一个匹配"）。

**建议优先修的 5 处**：C49 与 C51 两条否定式断言（证据链已破，需改写限定范围）；C10+C12 两条一起补上 Phase 8 与 SQLite `messages` 表；C11 把 `linked_memory_ids` 的归属从 memory 改到 entity 并注明 LLM 那份是死输出；C52 补上被删的 Python 图记忆文件；P25/P45 两处页码。

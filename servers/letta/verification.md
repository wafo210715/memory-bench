# Letta / MemGPT 架构文档复核报告（A+B 合并版）

> 复核日期 2026-09-05。本文件是**两次独立复核的合并结果**：版本 A（PDF 全文 + 页↔行映射，论文侧证据强）与版本 B（`git show origin/archive` 逐行核对，代码侧覆盖面宽）。两份原件均已归档，未删除。合并时同一断言只保留一行并取更强证据；两侧判定冲突的行**同时保留两个判定**并标 `[A]` / `[B]`，且由本次合并**重新打开代码/论文自行裁决**（裁决证据写在「仲裁」列）。
>
> **论文源**：arXiv:2310.08560v2（2024-02-12），Packer/Wooders/Lin/Fang/Patil/Stoica/Gonzalez，*MemGPT: Towards LLMs as Operating Systems*，13 页。存在**两套行号系统**，引用时必须区分：
> - `txt:NNN` = 版本 A 的 `pdftotext -layout` 提取（1000 行 / 13 个换页符）。页↔行映射：p.1=1–71、p.2=72–192、p.3=193–264、p.4=265–347、p.5=348–415、p.6=416–501、p.7=502–593、p.8=594–679、p.9=680–746、p.10=747–803、p.11=804–877、p.12=878–948、p.13=949–1000。换页符位于 txt:72/193/265/348/416/502/594/680/747/804/878/949/1001。
> - `libtxt:NNN` = 本机论文库副本 `$HOME/mnt/literature/papers/Packer-2023-MemGPT-Letta-Towards-LLMs-as-Operating-Systems.txt`（**无 `-layout`**，1473 行，换页符 76/289/379/535/668/811/946/1024/1122/1180/1304/1425/1474）。**这是与 A 不同的一次提取，行号不可互换。** 本次合并所有新增/仲裁性论文证据均用 `libtxt:` 前缀，可在本机直接复现。
> - 版本 B 的论文侧证据原为 WebFetch 逐字引文（无行号，弱否定标 `[弱否定]`）。合并后凡能在 `libtxt` 落到行的，一律替换为行号证据；B 的三条 `?`（穷尽性缺席断言）因此全部可以自行证伪并升级，见 §2.1 P48/P49。
>
> **代码源**：`$HOME/mnt/repo/letta` 的 `origin/archive` @ `56ba9c25552605eec89de8ed3dc6394b625c1993`（2026-08-13，`pyproject.toml:3` version `0.16.8`）。`main` 已由 `87fd37aab`（2026-08-15）清空为落地页。全程 `git show origin/archive:<path>` 只读，**未 checkout、未切分支、未改动仓库任何文件**。
>
> **复核范围**：`paper-architecture.md`（222 行）、`code-architecture.md`（281 行）全文逐句；`methodology-flow.md`（236 行）抽查全部代码引用锚点与退化条件断言（派生文档，仅 B 覆盖，合并后原样保留）。
>
> **范围声明**：本文只描述历史 Letta V1 archive，不代表 2026 年当前 Letta 产品；archive `AGENTS.md` 自称 deprecated / maintenance mode，当前 `main/AGENTS.md` 明确禁止用它推断当前 Letta。

---

## 1. 总评

两份架构文档的主干判断**整体可信度较高**：论文侧的两级上下文、Queue Manager 自动双写 recall、70%/100%/50% 三个 `e.g.` 阈值、recursive summary 滚动生成并占 FIFO 首位、`request_heartbeat=true` 串链与 yield、pgvector+HNSW+cosine、分页防溢出，逐条都能落到原文行号；代码侧对 Block / Passage / Message 三层状态、默认归档工具被移除、默认 `letta_v1_agent` 以「是否调用工具」替代 heartbeat、Native 与 Turbopuffer 两条检索分叉的判断也都属实，`file.py:NNN` 命中率高。

需要修正的承重点，按严重度：

1. **`core_memory_replace` 不要求唯一匹配**（code §2.1）。`core_tool_executor.py:328-345` 只判 `old_content not in current_value`（:339-340），随后 `str.replace` **全量替换所有出现**（:341）。唯一性校验属于新式 `memory_replace`（:346-401）。直接影响「记忆改写是否安全」的结论。
2. **默认路径的上下文压缩写错了对象**（code §3.4）。`SummarizationMode.PARTIAL_EVICT_MESSAGE_BUFFER` + `simple_summary()` 属于 `Summarizer` 类，**只被 `LettaAgentV2:124` 与 legacy `letta_agent.py:141` 构造**；默认 `letta_v1_agent` 走的 `LettaAgentV3` **全文无 `Summarizer(`**，它 import 并使用 `compact_messages`（`letta_agent_v3.py:72` import → `:2109` 调用）与 `get_compaction_trigger_threshold`（`:75` import → `:938` 调用），阈值为 100% 上下文窗口（GPT-5 系列 90%），且摘要模型可被 `compact.py:42-131` 换成更便宜的模型。文档当成「向论文致敬且保持一致」的那条路径，在默认建号下走不到。
3. **「默认建号一定没有归档工具 / 一定 discard send_message」有一个成立的反例**。`agent_manager.py:404-405` 的 `elif agent_create.enable_sleeptime:` 分支**排在** `letta_v1_agent` 分支（:410-413）**之前**，命中时挂 `BASE_SLEEPTIME_CHAT_TOOLS = [send_message, conversation_search, archival_memory_search]`（`constants.py:133`），既不减 `archival_memory_search`，也不 `discard("send_message")`。
4. **Message 并非「从不物理删除」**。上下文驱逐确实只移出窗口不删 DB，但有三个硬删除入口：`message_manager.py:822`（单条）、`:1045-1067`（整 agent，`delete(MessageModel)` 在 :1060）、`:1094-1121`（按 id 批量，`delete(...)` 在 :1119）。
5. **sleeptime 与 legacy Agent 的路由陈述过时**。默认 `letta_v1_agent` 由 `agent_loop.py:20-43` 路由到 `LettaAgentV3` / `SleeptimeMultiAgentV4`，不是文档重点引用的 `groups/sleeptime_multi_agent.py`——后者唯一入口 `groups/helpers.py:15 load_multi_agent()` **全仓零调用者**。legacy `letta/agent.py:Agent` 更是**根本无法被实例化**：生产代码唯一 import 在 `chat_completions.py:8`，其 `:51` 调 `server.load_agent(...)`，而全仓 `git grep "def load_agent"` **零命中**，该路由本身是坏的。
6. **三处「我没搞清楚」其实可以关闭**：memory_repo **已接进主编辑路径**（`server.py:155-167` 配置 memfs 即把 `block_manager` 换成 `GitEnabledBlockManager`；`block_manager_git.py:188-238` 先 commit 再同步 Postgres；门槛是 agent 带 `git-memory-enabled` tag）；`archival_memory_insert` 后强制重建系统提示词的原因可坐实（`prompts/prompt_generator.py:26-58 compile_memory_metadata_block` 参数含 `archival_memory_size`「Number of items in archival memory」与 `archive_tags`）；legacy Agent 不可达（见上）。
7. **`Memory.compile()` 的「Block 100% 在场」需加 git 模式限定**。`schemas/memory.py:122-130 _get_renderable_blocks` 在 `git_enabled` 时**只渲染 `system/` 前缀的块**，其余块仅以 `<external>` 文件树出现在 `_render_memory_blocks_git`（:205-236）里，正文不进 context。且 `compile` 在 **:688**，不是文档引的 :143（那是 `_render_memory_blocks_standard`）。

论文架构图另有两处语义需收紧：函数返回值应写「追加到 main context / FIFO」，不能画进只读 `System Instructions`；LLM 必须从 prompt / schema 获知 heartbeat 参数（心跳恰恰是 **LLM 自己在输出里生成**的），只能说底层无状态模型 API 不实现该调度语义。另有一类系统性小问题：**行号偏一 / 指向注释行**（`agent_manager.py:412`→413、`core_tool_executor.py:38`→41、`message_manager.py:1175`→1176、`memory.py:143`→688、`constants.py:132`→133），不影响结论但锚点不可直接复用。

---

## 2. 逐条核对表

判定：`✓` 属实 / `✗` 不实 / `◐` 部分属实或需加限定 / `?` 无法核实
来源标记：无标记 = 两份报告都覆盖（已取更强证据）；`[A only]` / `[B only]` = 仅一侧覆盖；`[A]` / `[B]` = 两侧判定冲突，已重新裁决。

### 2.1 `paper-architecture.md`

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 来源 / 仲裁 |
|---|---|---|---|---|---|
| P1 | 头注 | arXiv v2、2024-02-12、13 页、Packer 等 UC Berkeley | ✓ | `txt:16` / `libtxt:1-6`；13 个换页符（两套映射见页首） | 两侧 |
| P2 | 头注 | 论文标题为 MemGPT，全文不出现 "Letta" | ✓ | `libtxt` 全文 `grep -i letta` **零命中**（本机可复现，强于 B 原来的 `[弱否定]`） | 两侧，B 的中介否定已升级 |
| P3 | §1 | 固定 context 类比主存、外部 context 类比磁盘 | ✓ | `txt:21-30,33-53,151-178,180-190`（p.1-2）；§2 首段 "main context (analogous to main memory/physical memory/RAM) and external context (analogous to disk...)" | 两侧 |
| P4 | §2 | main context 分 system instructions / working context / FIFO queue | ✓ | `txt:157-177`（p.2）；Fig.3 `txt:200-217`（p.3）；§2.1 "split into three contiguous sections" | 两侧 |
| P5 | §2 | external context 分 archival / recall 两库 | ✓ | `txt:189-190`；Fig.3 `txt:207-216`（p.2-3） | 两侧 |
| P6 | §2.1 | system instructions 只读 static，含控制流与函数说明 | ✓ | §2.1 "read-only (static) and contain information on the MemGPT control flow, the intended usage of the different memory levels, and instructions on how to use the MemGPT functions"；`txt:161-165` | **[B only]**，与 P54/P55 直接相关 |
| P7 | §2.1 | working context 是定长、可读写、非结构化文本，只能由函数写 | ✓ | `txt:165-170`（p.2）；逐字 "a fixed-size read/write block of unstructured text, writeable only via MemGPT function calls" | 两侧 |
| P8 | §2.1 | 函数名只在图注伪代码出现，「见 Figure 1/2/4」 | ◐ | `libtxt` 中 `working_context.*` 仅出现在 :182,185,187,190（Fig.1）与 :273,415（Fig.4）；**Fig.2 里是 `recall_storage.search`（:134,136,409），不含 `working_context.*`** | **[B only]**，本次以 `libtxt` grep 坐实。应写「Figure 1/4」 |
| P9 | §2.1 | memory edit / retrieval 由 LLM 自主决定 | ✓ | `txt:255-261`（p.3）；§2.3 "Memory edits and retrieval are entirely self-directed" | 两侧 |
| P10 | §2.1 | `Birthday is February 7` / `Boyfriend named James` 作为 working-context 写入例 | ✓ | Fig.1 `txt:74-147`（p.2）/ `libtxt:182-190`；图注 "MemGPT (left) writes data to persistent memory after it receives a system alert about limited context space." | 两侧 |
| P11 | §2.1 | 信息变化时用 replace 改成 `Ex-boyfriend named James` | ✓ | Fig.4 `txt:267-301`（p.4）/ `libtxt:415`；图注 "An example conversation snippet where MemGPT (left) updates stored information." | 两侧 |
| P12 | §2.1 | 写入不需要第二次独立 LLM 请求 | ✓ | `txt:243-259`（p.3）；函数调用即当前 completion，论文未描述第二个抽取器 | 两侧 |
| P13 | §2.2 | Queue Manager 自动追加新消息到 FIFO 并触发推理 | ✓ | `txt:181-186`（p.2）；"the queue manager appends the incoming messages to the FIFO queue, concatenates the prompt tokens and triggers the LLM inference" | 两侧 |
| P14 | §2.2 | incoming message 和生成的 LLM output 都写 recall storage | ✓ | `txt:186-190`（p.2）；"writes both the incoming message and the generated LLM output to recall storage (the MemGPT message database)" | 两侧 |
| P15 | §2.2 | FIFO 存原始滚动消息、函数调用输入输出和系统警告 | ✓ | `txt:172-177`（p.2）；§2.1 "system messages and function call inputs and outputs" | **[A only]** |
| P16 | §2.2 | 新摘要 = 旧 recursive summary + 本次 evicted messages（滚动式） | ✓ | `txt:242-248`（p.3）；"generates a new recursive summary using the existing recursive summary and evicted messages" | 两侧 |
| P17 | §2.1 | recursive summary 位于 FIFO 第一个位置 | ✓ | `txt:175-177`（p.2）；"The first index in the FIFO queue stores a system message containing a recursive summary..." | 两侧 |
| P18 | §2.2 | 「论文没写清 recursive summary 是否独立再调一次 LLM」 | ✓ [B] / ? [A] | `txt:246-248` 只写 `generates`，无调用者、模型、prompt | **仲裁取 ✓**：核对表校验的是**文档断言**，而「论文未写清」这一断言本身可证实；A 的 `?` 指的是底层机制本身在论文里仍是空白，两者不矛盾，已在此并记 |
| P19 | §2.3 / §3.2.1 | 文档实验先预计算 embedding 再批量载入 archival | ✓ | `txt:465-490`（尤其 472-480，p.6）；"We precompute embeddings and load them into the database, which uses an HNSW index..." | 两侧 |
| P20 | §3.2.1 | PostgreSQL + pgvector + HNSW，cosine similarity | ✓ | `txt:465-490`（p.6）；原文拼写 `extention` 为论文自身错误 | 两侧 |
| P21 | §2.2 | memory pressure 时 LLM 可把 FIFO 重要信息写 working **或** archival | ✓ | `txt:226-241`（p.3）；"...to working context or archival storage" | 两侧 |
| P22 | §2.3 | 论文没有展示运行时 FIFO→archival 的具体实验或示例 | ✓ | `libtxt` 中 `archival_storage.*` **只有 `.search`**（:708,722,828,830,840,846,871），无一处 insert；Fig.1 驱逐案例走 working_context 分支 | 两侧；本次以 grep 把 B 的 `[弱否定]` 升级为正面证据 |
| P23 | §2.2 | archival 可存任意长度文本对象 | ✓ | `txt:238-241`（p.3）；"archival storage (a read/write database storing arbitrary length text objects)" | 两侧 |
| P24 | §2.3 | archival 写入「本身不调对话 LLM」 | ◐ | 预处理导入路径成立；运行时写入仍由主 LLM 先生成函数调用，论文未展开 embedding 写入实现 | **[A only]**。应区分「无额外 LLM」与「完全不经 LLM」 |
| P25 | §3.1 | 用户消息 / 系统消息 / 交互提醒 / 定时事件都可触发推理 | ✓ | `txt:309-320`（p.4）；§2.4 events 定义逐字 | 两侧 |
| P26 | §3.1 | 定时事件允许 "run 'unprompted' without user intervention" | ✓ | `txt:316-318`（p.4） | 两侧 |
| P27 | §3.1 | warning token count 示例为 70% | ✓ | `txt:224-234`（p.3）；原文是 `e.g.`，不是硬编码理论值 | 两侧 |
| P28 | §3.1 | 警告由系统插入，是否搬运由 LLM 决定 | ✓ | `txt:230-240`（p.3）；"the queue manager inserts a system message into the queue warning the LLM..." | 两侧 |
| P29 | §3.2 | archival 检索为 embedding cosine similarity | ✓ | `txt:465-490`（p.6）；"performs vector search based on cosine similarity" | 两侧 |
| P30 | §3.2 | recall 检索算法正文完全未说明 | ✓ | `txt:181-190` 只写 readable/retrieved；已通读 §2 与 Appendix 无算法描述。文档拒绝采纳 vault 笔记的「混合检索」提法，判断正确 | 两侧 |
| P31 | §3.2 | Fig.2 示例 `recall_storage.search("six flags")` | ✓ | `txt:101-130,146-148`（p.2）/ `libtxt:134,136,409` | 两侧 |
| P32 | §3.3 | `request_heartbeat=true` 请求立即再推理 | ✓ | Fig.3 caption `txt:212-217`（p.3）；§2.4 `txt:323-337`（p.4） | 两侧 |
| P33 | §3.3 | 无 flag 是 "a yield"，等下一外部事件 | ✓ | `txt:329-337`（p.4）逐字 | 两侧 |
| P34 | §3.3 | archival 检索可分页、多次调用（`page=2`，Figure 6） | ✓ | Fig.6 `txt:421-450`（p.6）/ `libtxt:722`；`txt:570-575`（p.7） | 两侧 |
| P35 | §3.3 | Nested KV 示例被称作「**三层**嵌套 key-value」 | ◐ [B] / ✓ [A] | `libtxt:889` 逐字："In this particular example, the key-value pair has **two** nesting levels: 831..ea5 → 5b8..4c3 → f37...617"；§3.2.2 的 nesting levels 从 0 变到 4（`libtxt:966`） | **仲裁取 ◐ [B]**：A 只核了 UUID 链（属实），但漏了层数口径——原文说 **two**，文档写「三层」。应改「两层嵌套（三个 UUID）」 |
| P36 | §3.3 | 该示例标注为「（Figure 7/8）」 | ◐ | `libtxt:873-877` Figure 7 = "Nested KV retrieval task performance"（**性能曲线**）；示例轨迹只在 Figure 8（`libtxt:888-889`） | **[B only]**，本次以 `libtxt` 坐实。引用锚点应收敛到 Fig.8 |
| P37 | §3.3 | GPT-4 + MemGPT "is unaffected with the number of nesting levels" | ✓ | `txt:622-629`（p.8）/ `libtxt:976-977`；归因句 "accessing the key-value pairs stored in main context repeatedly via function queries" | 两侧。论文实验表述，不外推到其他模型 |
| P38 | §3.4 | 函数输出加入 main context | ✓ | `txt:329-335`（p.4）；`txt:248-251`（p.3）；§2.4 "MemGPT will add the function output to main context" | 两侧 |
| P39 | §3.4 | runtime errors 也反馈给 processor（feedback loop） | ✓ | `txt:243-252`（p.3）；§2.3 两句连续逐字命中 | 两侧，章节归属正确 |
| P40 | §3.4 | pagination 防止检索结果撑爆 context | ✓ | `txt:253-259`（p.3）；§2.3 "implement pagination to prevent retrieval calls from overflowing the context window" | 两侧 |
| P41 | §3.5 | flush token count 示例 100% | ✓ | `txt:242-245`（p.3） | 两侧 |
| P42 | §3.5 | 一次示例驱逐 50% context | ✓ | `txt:245-248`（p.3）；同样是 `e.g.` | 两侧 |
| P43 | §3.5 | 驱逐后消息 "stored indefinitely in recall storage"，可由函数读回 | ✓ | `txt:248-251`（p.3）逐字 | 两侧 |
| P44 | §5 | 论文只给伪代码式函数名，没有完整 schema | ✓ | Fig.1/2/4/6；Appendix `txt:810-812`（p.11） | **[A only]** |
| P45 | §4/§5 | 出现函数名 `archival_storage.insert` | ◐ | `libtxt` 全文 `archival_storage.*` **只有 `.search`**（见 P22）；写入 archival 的**能力**有 §2.2 散文支持，但这个函数名是文档自己补的 | **[B only]**，本次以 grep 坐实 |
| P46 | §5 | Appendix 明说 prompt 为简化版，精确实现另见网站 | ✓ | `txt:806-812`（p.11）；附录为 Section 6，6.1 下分 6.1.1–6.1.6；"The MemGPT prompts have been edited for brevity. For full implementation details (including exact prompts) visit https://research.memgpt.ai" | 两侧 |
| P47 | §6 | 论文没有真正删除 / 遗忘机制，recall 写为 indefinitely | ✓ | `libtxt` 全文 `grep -ni "forget\|delete\|deletion"` 只命中 :344 的 queue eviction policy 一句；无任何遗忘机制 | 两侧，本次以本机 grep 升级为强证据 |
| P48 | §6 | 论文未讨论 heartbeat 死循环的安全阀或步数上限 | ✓ [A] / ? [B] | `libtxt` 全文 `grep -ni "infinite loop\|safeguard\|safety\|max step\|step limit\|cap on\|runaway\|termination"` **零命中** | **仲裁取 ✓ [A]**：B 判 `?` 是因为它当时只有 WebFetch 中介否定；本机 txt 到位后该穷尽性缺席可自行证伪 |
| P49 | §6 | 检索结果的再筛选 / 去重 / 时效评估论文没讨论 | ✓ | `libtxt` 全文 `grep -ni "duplicat\|dedup\|stale\|rerank\|re-rank\|filter"` **零命中** | **[B only]**，B 原判 `?`；本次以本机 grep **升级为 ✓** |
| P50 | §6 | MSC 每段五个 session、每 session 约十几条消息 | ✓ | `txt:391-400`（p.5）；§3.1 "Each multi-session chat in MSC has five total sessions, and each session consists of a roughly a dozen messages."；目标叙述 `txt:331-338`（p.4） | 两侧。与 weeks/months/years 目标的尺度差批评有原文支撑 |
| P51 | §6 | 论文未讨论多 agent 共享记忆或多用户隔离；§5 未来方向只列三项空泛方向 | ✓ | 全文 multi-agent 仅 Related Work 的 Park 模拟社会，未进入方法/局限；§5 逐字 "applying MemGPT to other domains with massive or unbounded contexts, integrating different memory tier technologies like databases or caches, and further improving control flow and memory management policies" | 两侧 |
| P52 | §5 | DMR 段只提 recall memory，未提 archival | ✓ | §3.1 "MemGPT instead has access to the full conversation history but must access it via paginated search queries to recall memory (in order to bring them into main context)." | **[B only]** |
| P53 | §5 | warning / flush 阈值是否可配置论文没说，只用 `e.g.` 口吻 | ✓ | 见 P27/P41/P42 三处 "e.g."；正文无敏感性分析 | **[B only]** |
| P54 | §4 Mermaid | Function Executor 的结果 / 错误直接箭头写入 `SysInstr` | ✗ [B] / ◐ [A] | §2.1 system instructions "read-only (static)"（`txt:161-165`）；§2.4 "add the function output to **main context**"（`txt:333-335`）；§2.1 FIFO queue 才存 "function call inputs and outputs" | **仲裁取 ✗ [B]**：这条边指向论文明确声明只读的段落，是**错边**而非「需加限定」；A 自己也把它列进「优先修正」。应改画到 FIFO / main-context 回灌接口 |
| P55 | §4 边界 | LLM Processor「不知道心跳这件事存在」 | ✗ | Fig.3 图注 `txt:215-217`：LLM "**generating** a special keyword argument (request_heartbeat=true) **in its output**"；`txt:227-241` 说明 system instructions 含 memory hierarchy 与 function schema | 两侧一致 ✗。底层 API 不实现调度，但被提示后的 LLM 必须知道该参数 |
| P56 | §5 | working context 的评测初始化流程未交代清楚 | ◐ [B] / ✓ [A] | 正文确未说明 human/persona block 是预置还是运行时积累；但附录 §6.1.1（MemGPT instructions, DMR）给出了 "The following is information about myself. My task is to completely immerse myself in this role" 这类 persona 注入文本 | **仲裁取 ◐ [B]**：结论方向对，但附录存在部分初始化线索，「完全没交代」需加限定 |

**小计**：✓ 48 / ✗ 2 / ◐ 6 / ? 0 = **56**

### 2.2 `code-architecture.md`

全部证据均为 `git show origin/archive:<path>` 的实际行内容（行号 = 该文件在 `origin/archive` 上的行号）。

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 来源 / 仲裁 |
|---|---|---|---|---|---|
| C1 | 头注 | `main` 于 2026-08-15 被 `87fd37aab`「chore: archive the legacy server repository」清空 | ✓ | `git log origin/main`：`87fd37aab Sat Aug 15 20:56:10 2026 -0700 (#3430)`；`git show --stat` 删除约 1152 文件 / 367k 行 | 两侧 |
| C2 | 头注 | README 原文 "The retired Letta V1 server source is preserved on the `archive` branch for historical reference" | ✓ | `origin/main:README.md` NOTE 块逐字命中 | 两侧 |
| C3 | 头注 | 引用路径写作 "`letta/AGENTS.md`@archive" | ◐ | 文本逐字命中，但 `git ls-tree -r origin/archive \| grep AGENTS.md` **只有仓库根 `AGENTS.md`**，`letta/AGENTS.md` 不存在 | **[B only]**，本次复核确认。路径写错 |
| C4 | 头注 | 分析对象是退役 `origin/archive`，非当前产品 | ✓ | archive `AGENTS.md:1-15`（deprecated / maintenance mode）；main `AGENTS.md:1-38` 禁止据此推断当前 Letta | 两侧。必须保留此范围警告 |
| C5 | 头注 | archive 当前源码版本 | ✓ | `origin/archive:pyproject.toml:1-4` = letta 0.16.8；commit `56ba9c25` | **[A only]**（原文未写版本号，报告补齐） |
| C6 | §1 | Letta 是完整有状态 Agent runtime，不只是可插拔 memory 库 | ✓ | `agents/agent_loop.py:15-63`；`server/server.py:148-193` | **[A only]** |
| C7 | §1 | Block / Passage / Message 三层持久状态 | ✓ | `schemas/memory.py:68-80`；`orm/archive.py:24-59`；`orm/message.py:23-47` | **[A only]** |
| C8 | §1 | 默认 agent 类型是 `letta_v1_agent` | ✓ | `schemas/agent.py:226 agent_type: AgentType = Field(default_factory=lambda: AgentType.letta_v1_agent, ...)` | **[B only]**，行号精确 |
| C9 | §2.1 | 每块字符上限 `CORE_MEMORY_BLOCK_CHAR_LIMIT`（`schemas/block.py:20`） | ✓ [B] / ◐ [A] | **本次打开 `block.py:14-30` 确认**：第 20 行正是 `limit: int = Field(CORE_MEMORY_BLOCK_CHAR_LIMIT, description="Character limit of the block.")` | **仲裁取 ✓ [B]**：A 称 `:20` 「只是常量导入」是错的，该行就是字段定义本身，锚点精确 |
| C10 | §2.1 | core memory 由 agent 工具调用触发 | ✓ | `core_tool_executor.py:39-56,319-399,683-773` | **[A only]** |
| C11 | §2.1 | Block 存按 label 组织的自由文本 | ✓ | `schemas/memory.py:68-80,143-173` | **[A only]** |
| C12 | §2.1 | `core_memory_append` = 原值后拼接换行 + 新内容 | ✓ | `core_tool_executor.py:319-326`：`new_value = current_value + "\n" + str(content)`（:323） | **[B only]** |
| C13 | §2.1 | 旧 `core_memory_replace` 要求 `old_content` 唯一匹配 | ✗ | `core_tool_executor.py:328-345`（整函数）：只有 `if old_content not in current_value: raise`（:339-340），随后 `current_value.replace(old, new)` **全量替换**（:341） | 两侧一致 ✗，取 B 的整函数区间（A 的 `:336-343` 只覆盖检查体）。唯一性属于 C14 |
| C14 | §2.1 | 新 `memory_replace` / `memory_insert` 要求唯一匹配并拒绝行号前缀 | ✓ | `core_tool_executor.py:346-401`：`occurences = current_value.count(old_string)`，`==0` 与 `>1` 都 raise；`MEMORY_TOOLS_LINE_NUMBER_PREFIX_REGEX` / `CORE_MEMORY_LINE_NUMBER_WARNING` 三处校验；`memory_insert` 在 :683-742；函数 schema `function_sets/base.py:310-388` | 两侧 |
| C15 | §2.1 | 代码注释直接引用 anthropic-quickstarts 的 `edit.py` | ✓ | `functions/function_sets/base.py:310`：`# Based off of: https://github.com/anthropics/anthropic-quickstarts/blob/main/computer-use-demo/computer_use_demo/tools/edit.py...` | **[B only]** |
| C16 | §2.1 | 统一 `memory(command="create\|str_replace\|insert\|delete\|rename", path=...)` 工具，位于 `base.py` 顶部 | ✓ | `base.py:10 def memory(`（文件第一个定义）；executor dispatch `core_tool_executor.py:41-56`，五个 command 分支实现在 `:1014-1068` | 两侧 |
| C17 | §2.1 | `memory_rethink` / `rethink_memory` 用于整块重写 | ✓ | `base.py:488 def memory_rethink`、`base.py:283 def rethink_memory(agent_state, new_memory, target_block_label)`；executor `core_tool_executor.py:743-773` | 两侧。两个名字都真实存在 |
| C18 | §2.1 | core edit 不额外调 LLM，变更后同步 DB 并重编 system prompt | ✓ | `agent_manager.py:1747 update_memory_if_changed_async`；:1760-1766 `new_memory.compile(...)` 后字符串比较；:1777 `block_manager.update_block_async`；:1795 `rebuild_system_prompt_async`。全函数无 LLM 调用 | 两侧 |
| C19 | §2.1 | read-only Block 写前报错 `READ_ONLY_BLOCK_EDIT_ERROR` | ✓ | `schemas/block.py:36`；`core_tool_executor.py:320/329/347/684/744` 每个编辑方法首行 | 两侧 |
| C20 | §2.1 | `Memory.git_enabled` 字段 | ✓ | `schemas/memory.py:76 git_enabled: bool = Field(False, description="Whether this agent uses git-backed memory with structured labels.")` | **[B only]** |
| C21 | §2.1 | memory_repo 让 Block 镜像为 git 文件并保留版本史 | ✓ | `block_manager_git.py:1-40,188-285`；`memory_repo/memfs_client_base.py:36-56` | 两侧 |
| C22 | §2.1 | Block 序列化成 `{label}.md`，YAML frontmatter 存 description / **limit** / read_only 等元数据 | ◐ | `services/memory_repo/block_markdown.py:1-11` 确为「Markdown with YAML frontmatter」、blocks 存于 repo 根的 `{label}.md`（`memfs_client_base.py:31` 注释），但第 10 行明写 "``limit`` is intentionally **excluded** from frontmatter (deprecated for git-base memory)" | **[B only]**。limit 不在 frontmatter |
| C23 | §2.1 | 本地默认 `~/.letta/memfs/`，云端连 memfs HTTP 服务 | ✓ | `memfs_client_base.py:1-8` docstring + `:34 DEFAULT_LOCAL_PATH = os.path.expanduser("~/.letta/memfs")` | **[B only]** |
| C24 | §2.2 | `archival_memory_insert(content, tags)` 由 agent 主动调用 | ✓ | `function_sets/base.py:164 async def archival_memory_insert(...)`；executor `core_tool_executor.py:307-317` | 两侧。仅在工具已挂载时 |
| C25 | §2.2 | 工具描述建议存 "self-contained facts or summaries"、会议纪要 / 项目更新 / 对话摘要 | ✓ | `base.py:164+` docstring 逐字："Store self-contained facts or summaries, not conversational fragments"；"Use for: meeting notes, project updates, conversation summaries, events, reports" | **[B only]** |
| C26 | §2.2 | 写入 Passage 不做摘要，原文本身送 embedding / DB | ✓ | `passage_manager.py:543-604`：`text_chunks=[text]`，没有 LLM 摘要器 | **[A only]** |
| C27 | §2.2 | `insert_passage` 内把 embedding pad 到 `MAX_EMBEDDING_DIM=4096` | ◐ | `constants.py:93 MAX_EMBEDDING_DIM = 4096`；`passage_manager.py:543 insert_passage`，:574-580 调 `request_embeddings`；**但 pad 不在 `insert_passage` 里**，在下游 `create_agent_passage_async:148-159` / `create_agent_passages_async:234-239`，且只在 PostgreSQL / pgvector 相关路径 pad，不是所有后端一律 | 两侧均 ◐，此处合并两侧的限定（A：后端条件；B：函数归属需下移一层） |
| C28 | §2.2 | tags 同时写 JSON 列和 `PassageTag` 关联表 | ✓ [B] / ◐ [A] | **本次打开确认**：`passage_manager.py:55-79` 建 `PassageTag` 对象并 `batch_create_async`，docstring 逐字 "Create tag entries in junction table (complements tags stored in JSON column)"；JSON 列写入在 `:590-597` 的 `passage_data = {... "tags": tags}`；ORM 关系 `orm/passage.py:82-83` | **仲裁取 ✓ [B]**：双写机制已直接见到两端。A 的 ◐ 只是因为文档原引的 `:543-604` 仅覆盖 JSON 那一半 |
| C29 | §2.2 | archival insert 后强制 `rebuild_system_prompt_async(force=True)` | ✓ | `core_tool_executor.py:307-317`（:316） | 两侧 |
| C30 | §2.2 | rebuild 是为了让 external memory summary 显示归档条目计数（文档自标「猜测、未验证」） | ✓ [B ◐] / ? [A] | **本次打开确认**：`prompts/prompt_generator.py:26-58 compile_memory_metadata_block(...)` 参数含 `previous_message_count`、`archival_memory_size`（docstring "Number of items in archival memory (long-term storage)"）、`archive_tags`，输出 `<memory_metadata>` 块 | **仲裁：猜测可坐实，升级为 ✓**。唯一保留的限定是 executor 调用点本身没有因果注释 |
| C31 | §2.2 | `Archive` 可挂多个 agent、共享 passage 集合 | ✓ | `orm/archive.py:24-25` docstring "An archive represents a collection of archival passages that can be shared between agents"；`:55-59` `ArchivesAgents` 关联表 | 两侧（B 的 §6.5 条目并入此行） |
| C32 | §2.2 / §6 | archival 两工具不在默认 base tool 集 | ✓ | `constants.py:115-116`；`agent_manager_helper.py:1298-1302` | 两侧。实现仍在，默认接线被移除（另见 C72 的反例） |
| C33 | §2.3 | 进出消息自动持久化到 `messages` 表 | ✓ | `message_manager.py:477 create_many_messages_async`；v3 组装点 `letta_agent_v3.py:1935 messages_to_persist = (initial_messages or []) + parallel_messages`；`orm/message.py:23-47` | 两侧 |
| C34 | §2.3 | Message 保存 role / content / tool_calls 等原始结构 | ✓ | `orm/message.py:40-82` | **[A only]** |
| C35 | §2.3 | Message「从不物理删除」 | ✗ | 三个硬删除入口：`message_manager.py:822 delete_message_by_id_async`；`:1045-1067 delete_all_messages_for_agent_async`（`delete(MessageModel)` 在 :1060）；`:1094-1121 delete_messages_by_ids_async`（`delete(...)` 在 :1119） | 两侧一致 ✗，本行取两侧入口的**并集**（B 多出 :822）。应改为「自动 context eviction 不删除 DB 行」，见 C63 |
| C36 | §2.3 | 正常消息落库不调用 LLM | ✓ | `message_manager.py:477-573` 为 ORM 批量写入 | **[A only]** |
| C37 | §2.4 | sleeptime 每 N 轮异步启动独立 agent 整理共享 Block | ✓ | 活跃路径 `sleeptime_multi_agent_v4.py:132-168,140-157,171-267`；建组 `server.py:756-789`；共享 block_ids `server.py:762` | 两侧。主机制正确 |
| C38 | §2.4 | server 创建 sleeptime 组时默认频率 5 | ✓ | `server/server.py:780-785`（`:784 sleeptime_agent_frequency=5`）；前置条件 `:756-758`：`main_agent.embedding_config is None` 则跳过创建 | 两侧 |
| C39 | §2.4 | 触发实现引 `groups/sleeptime_multi_agent.py:192-238`（`bump_turns_counter` → `_issue_background_task`） | ◐ [B] / ✗ [A] | **本次打开确认**：该文件有 `:192 def step`、`:236 bump_turns_counter`，但 `_issue_background_task` 的**调用**在 `:248`（定义在 :64），超出所引区间；且 `git grep load_multi_agent` 显示唯一入口 `groups/helpers.py:15 def load_multi_agent` **零调用者** | **仲裁取 ◐ [B]**：文档这句描述的**机制**（计数到点起后台任务）真实存在于该文件，只是文件不可达且区间少 10 行——属「引对了机制、引错了实现」。A 的 ✗ 对应的是更强的表述，见 C40 |
| C40 | §5 | 旧 `sleeptime_multi_agent.py` 可代表**当前默认** sleeptime 路径 | ✗ | `agent_loop.py:20-43` 对默认 agent 明确选择 `SleeptimeMultiAgentV4`；旧类只经不可达的 `load_multi_agent` 构造 | **[A only]**（B 把同一事实并进 C39 的备注）。文档应换引用 |
| C41 | §2.4 | sleeptime 是独立、用户不可见的 LLM run | ✓ | `sleeptime_multi_agent_v4.py:171-199,201-280`；后台起的是 `LettaAgentV3`（`:257`），有独立 run_id | 两侧 |
| C42 | §3.1 | `Memory.compile()` 把 Block 渲染进 system prompt，「只要没超字符上限就 100% 在场」 | ◐ [B] / ✓ [A] | **本次打开确认**：`compile` 在 `schemas/memory.py:688`（不是文档引的 :143，那是 `_render_memory_blocks_standard`）；`:122-130 _get_renderable_blocks` 逐字 "For git-memory-enabled agents, only system/ blocks are rendered."，git 模式下其余块只以 `<memory><external>` 文件树出现（`:205-236`） | **仲裁取 ◐ [B]**：标准/行号模式下「常驻」成立，git 模式必须加限定；A 的锚点 `:143-173,675-719` 也未指到 `compile` |
| C43 | §3.1 | standard / line-numbered / git 三种渲染模式 | ✓ | `schemas/memory.py:143 / :175 / :205` 三个渲染器；`compile` 分支 `:688,700-712`；`is_line_numbered = is_line_numbered_agent_type and is_anthropic`，类型限于 `("sleeptime_agent","memgpt_v2_agent","letta_v1_agent")` | 两侧（B 补齐了行号模式的门槛条件） |
| C44 | §3.2 | `archival_memory_search(query, tags, top_k, start_datetime, end_datetime)` 签名 | ◐ | `core_tool_executor.py:278-288` 签名还含 `tag_match_mode: Literal["any","all"] = "any"` | **[B only]**。少列一个参数 |
| C45 | §3.2 | archival tool 走 `search_agent_archival_memory_async` → `query_agent_passages_async` | ✓ | `core_tool_executor.py:278-302`；`agent_manager.py:2534 search_agent_archival_memory_async` → `:2416 query_agent_passages_async`（TPUF 分支与 SQL fallback 都在 2416-2480 内） | 两侧 |
| C46 | §3.2 | Turbopuffer 分支请求 hybrid search | ✓ | `agent_manager.py:2452-2476`：`archive.vector_db_provider == VectorDBProvider.TPUF` → `tpuf_client.query_passages(..., search_mode="hybrid")`；RRF `helpers/tpuf_client.py:1023-1024,1204-1205 _reciprocal_rank_fusion` | 两侧（B 补了 RRF 实现位置，外部融合细节仍不在本仓可见） |
| C47 | §3.2 | Native Postgres/SQLite 有 embedding 时按 cosine distance | ✓ | `agent_manager_helper.py:1180 build_agent_passage_query`；`:1245` pgvector `.cosine_distance(...)`，`:1252` SQLite `func.cosine_distance` | 两侧 |
| C48 | §3.2 | 无 embedding config 时退化为大小写无关子串 | ✓ | `agent_manager_helper.py:1259-1260`：`query.where(func.lower(ArchivalPassage.text).contains(func.lower(query_text)))` | 两侧。严格说是 `lower(text) LIKE lower('%q%')` 而非 `ILIKE` 关键字，行为等价 |
| C49 | §3.2 | 单次工具调用本身不做 agentic 多轮检索 | ✓ | `query_agent_passages_async` 一次 SQL / 一次 TPUF 请求返回，函数内无循环；多步只能由 Agent 再调工具 | 两侧 |
| C50 | §3.2 | 结果作为工具返回进入后续 context | ✓ | `core_tool_executor.py:278-302`；`letta_agent_v3.py:1915-1933` | **[A only]** |
| C51 | §3.3 | `conversation_search` docstring 自称 hybrid | ✓ | `functions/function_sets/base.py:87+` 首行逐字："Search prior conversation history using hybrid search (text + semantic similarity)." | 两侧。文档承诺强于默认 SQL 实现 |
| C52 | §3.3 | dispatch → `core_tool_executor.conversation_search` → `message_manager.search_messages_async`（默认 `search_mode="hybrid"`） | ✓ | `core_tool_executor.py:81`；`message_manager.py:1142-1147` | **[B only]** |
| C53 | §3.3 | 启用 Turbopuffer 时消息检索走 vector / FTS / hybrid + RRF | ✓ | `message_manager.py:1176 if should_use_tpuf_for_messages():` → `tpuf_client.query_messages_by_agent_id(..., search_mode=search_mode)`；RRF `tpuf_client.py:1371` | 两侧（文档锚点 `:1175` 是注释行，判断在 :1176） |
| C54 | §3.3 | 默认自托管 SQL 路径只是 ILIKE / JSON LIKE | ✓ | `message_manager.py:895 list_messages`；`:977-993` Postgres `content_element->>'text' ILIKE :query_text`、SQLite `JSON_EXTRACT(content,'$') LIKE :query_text`；`:1242-1250` else 分支回落 `list_messages`。无 embedding | 两侧（SQLite 分支在 :993，略超文档所引 :980） |
| C55 | §3.3 | 排除 tool 消息和调用过 `conversation_search` 的 assistant 消息 | ✓ | `core_tool_executor.py:151-166`：`if message.role == MessageRole.tool: continue`；`if CONVERSATION_SEARCH_TOOL_NAME in [...]: continue` | 两侧 |
| C56 | §3.4 | **默认** summarization mode 为 `PARTIAL_EVICT_MESSAGE_BUFFER`，驱逐比例 0.30 | ◐ [B] / ✓ [A] | 全局默认值属实：`settings.py:78 mode: SummarizationMode = ...PARTIAL_EVICT_MESSAGE_BUFFER`、`:86 partial_evict_summarizer_percentage: float = 0.30`。**但这条路径属于 `Summarizer` 类**，本次 grep 确认只被 `letta_agent_v2.py:124` 与 legacy `letta_agent.py:141` 构造；`letta_agent_v3.py` **全文无 `Summarizer(`** | **仲裁取 ◐ [B]**：设置项默认值 ≠ 默认建号实际走的路径 |
| C57 | §3.4 | partial evict **同步**调独立 summarizer LLM 生成摘要 | ◐ [B] / ✓ [A] | 机制属实：`summarizer/summarizer.py:136-203`（:145-151 docstring、:188 `await simple_summary(...)`、:148-150 明说不能异步）。**但默认 `letta_v1_agent`/`LettaAgentV3` 走的是** `compact_messages`：`letta_agent_v3.py:72` import → `:2109` 调用；阈值 `:75` import `get_compaction_trigger_threshold` → `:938` 调用（`thresholds.py:27-41`，GPT-5 系列 90%、其余 100% 上下文窗口）；摘要模型可被 `compact.py:42-131 build_summarizer_llm_config` 换成更便宜的模型 | **仲裁取 ◐ [B]**，理由同 C56。这是本次合并中最重要的一处更正 |
| C58 | §3.4 | 引 "as implemented in the original MemGPT loop, but using message count instead of token count"，出处标 `settings.py:78` | ◐ | 引文真实，但原句在 `services/summarizer/summarizer.py:145`（`_partial_evict_buffer_summarization` docstring 首行）；`settings.py:84-85` 是另两句注释 | **[B only]**。出处标错文件 |
| C59 | §3.4 | 另一模式 `STATIC_MESSAGE_BUFFER`（当前非默认）由后台 `EphemeralSummaryAgent` 异步生成 | ✓ | `settings.py:77` 被注释掉的 `# mode: ... STATIC_MESSAGE_BUFFER`；`summarizer.py:104-110` 分支、`:244 _static_buffer_summarization`、`:339 fire_and_forget(...)`；`letta_agent.py:132 EphemeralSummaryAgent(...)` | **[B only]** |
| C60 | §3.4 | 旧版 `letta/agent.py` 先按 `memory_warning_threshold * context_window` 发文字警告，硬触发是捕获 `ContextWindowExceededError` 后 `summarize_messages_inplace()`，最多重试 `max_summarizer_retries` | ✓ | `agent.py:957` 阈值判断，`:962-971` 插 `memory_pressure_warning`；`:1037` 重试判断，`:1042 self.summarize_messages_inplace()`；`settings.py:96 max_summarizer_retries: int = 3`（最终 raise 在 :1060） | **[B only]** |
| C61 | §3.4 | 默认 V3 同时保留旧 warning-threshold 行为 | ◐ | `letta_agent_v3.py:365-408` 的 proactive summarization 代码**整段被注释**（`:376/:400/:634` 的 `summarize_conversation_history` 调用均在注释里）；实际主触发在 context-exceeded / compaction 路径 | **[A only]**（B 在 C57 备注里提到同一事实）。旧 `agent.py:948-1055` 不能代表默认 V3 |
| C62 | §3.4 | 「新版 `letta_agent.py`/v2/v3 用 `_rebuild_context_window`」 | ✗ | **本次 grep 确认**：`_rebuild_context_window` 只存在于 `agents/letta_agent.py:1576`（调用点 547/881/1354/1562）与 `agents/voice_agent.py:293`（调用点 :197）；`letta_agent_v2.py` 用 `summarize_conversation_history()`（:277/:412/:1352），`letta_agent_v3.py` 用 `compact_messages()`（:2109） | **[B only]**。v2/v3 没有这个方法 |
| C63 | §3.4 | context eviction 不删 Message DB 行，可由 search 找回 | ✓ | `summarizer.py:136-203` 全程只重排 `in_context_messages`，无 delete；`compact.py` 同样只产出 summary message。DB 删除是显式 API（见 C35），不是 eviction | 两侧 |
| C64 | §3.5 | 默认 `letta_v1_agent` 有工具调用就继续，无工具就停 | ✓ | `agent_loop.py:20-43`；`letta_agent_v3.py:1967 _decide_continuation`，docstring「1. Did not call a tool? Loop ends 2. Called a tool? Loop continues」，函数体至 :2036 无 `request_heartbeat` 读取；`:2071` 显式 `request_heartbeat=False,  # NOTE: difference for v3` | 两侧。terminal rule / max step 可强制停止；补充：v3 继续时仍会注入一条 heartbeat **系统消息**（`:1628-1641 create_heartbeat_system_message`），只是不再读 flag |
| C65 | §3.5 | 默认系统 prompt 明说工具调用继续、纯文本 yield | ✓ | `prompts/system_prompts/letta_v1.py:22` 逐字："Continue executing and calling tools until the current task is complete or you need user input. To continue: call another tool. To yield control: end your response without calling a tool." | 两侧 |
| C66 | §3.5 | heartbeat 仍存在于旧循环 | ✓ | `agent.py:563 heartbeat_request = function_args.pop("request_heartbeat", None)`，:564-576 兜底，`:834 elif heartbeat_request:` → `:842 continue  # always chain`；`letta_agent.py:1769 _pop_heartbeat`、`:1875 _decide_continuation`、`:1884 continue_stepping = request_heartbeat`、`:1919 return`；`letta_agent_v2.py:1126,1241-1250,1285` | 两侧，取 B 的四处精确行号并集 |
| C67 | §5 | 「`memgpt_v2_agent` 类型走的是 `letta_agent.py`」 | ◐ | `agent_loop.py` 的 else 分支返回 **`LettaAgentV2`**（`letta_agent_v2.py`），不是 `letta_agent.py`；结论方向对（v2 同样读心跳，见 C66） | **[B only]**。文件张冠李戴 |
| C68 | §5 | legacy `letta/agent.py:Agent` 是否仍由当前 factory 实例化 | ◐ [B] / ? [A] | **本次 grep 确认可定论为不可达**：`agent_loop.py:15-63` 只返回 V2/V3/SleeptimeV3/V4；生产代码唯一 import 是 `server/rest_api/routers/openai/chat_completions/chat_completions.py:8`，其 `:51 letta_agent = server.load_agent(agent_id=agent_id, actor=actor)`，而 `git grep "def load_agent" origin/archive` **零命中**（另一处 import 在 `tests/data/functions/dump_json.py:3`） | **仲裁取 ◐ [B]**：文档的「不确定」可以关闭——不仅默认路径不可达，该 REST 路由在 archive 上本身就是坏的 |
| C69 | §5 | 「Turbopuffer 在自托管默认配置里是否启用没细读」 | ◐ | 可确认：`helpers/tpuf_client.py:208-210 should_use_tpuf() = bool(settings.use_tpuf) and bool(settings.tpuf_api_key) and bool(model_settings.openai_api_key)`；`:213-215 should_use_tpuf_for_messages() = should_use_tpuf() and bool(settings.embed_all_messages)` | **[B only]**。默认关闭，文档的 fallback 判断因此成立 |
| C70 | §6 | `DEPRECATED_LETTA_TOOLS` 含 archival insert/search | ✓ | `constants.py:115 BASE_TOOLS = [...]`、`:116 DEPRECATED_LETTA_TOOLS = ["archival_memory_insert", "archival_memory_search"]` | 两侧，行号逐字精确 |
| C71 | §6 | `calculate_base_tools()` 无论 `is_v2` 真假都减掉这两个工具 | ✓ | `agent_manager_helper.py:1298 def calculate_base_tools(is_v2: bool)`；`:1300` 与 `:1302` 两个 return 都是 `(set(BASE_TOOLS) - set(DEPRECATED_LETTA_TOOLS)) \| ...` | 两侧 |
| C72 | §6 | **所有**普通自动建号分支最终都经过 `calculate_base_tools` 去掉 archival | ◐ [B] / ✓ [A] | **本次打开 `agent_manager.py:388-430` 确认**：`else: tool_names \|= calculate_base_tools(is_v2=False)`（:424-425）确实覆盖 `memgpt_agent` ✓；但 `react_agent`(:408-409) / `workflow_agent`(:422-423) 是 `pass  # no default tools`；**关键反例：`elif agent_create.enable_sleeptime:`(:404-405) 排在 `letta_v1_agent`(:410) 之前**，命中时挂 `BASE_SLEEPTIME_CHAT_TOOLS = [send_message, conversation_search, archival_memory_search]`（`constants.py:133`），既不减 archival，也不 discard send_message | **仲裁取 ◐ [B]**：反例成立且可复现，A 的全称判断过强 |
| C73 | §6 | 调用方仍可显式挂载 archival 工具 | ✓ | `agent_manager.py:390 tool_names = set(agent_create.tools or [])` 先并入调用方指定工具，移除只作用于默认 `BASE_TOOLS` 计算结果 | **[A only]**。实现未物理删除 |
| C74 | §6 | 默认 `letta_v1_agent` 丢弃 `send_message`（文档标 `:412`） | ◐ [B] / ✓ [A] | 行为属实但锚点偏一：`:412` 是注释 `# Remove \`send_message\` if it exists`，`discard("send_message")` 在 **:413**；且该分支会被 C72 的 `enable_sleeptime` 分支抢先短路（该分支不 discard） | **仲裁取 ◐ [B]**：行为不是无条件成立 |
| C75 | §6 | 默认 `letta_v1_agent` 纯文本映射为 assistant message | ✓ | `server/server.py:968 text_is_assistant_message = agent_state.agent_type == AgentType.letta_v1_agent`（区间 :965-978） | 两侧 |
| C76 | §5 | memory_repo 的主编辑提交时机「没跟到底」 | ◐ | 已可跟到底：`server.py:155-161` 配置 memfs 即 `self.block_manager = GitEnabledBlockManager(memory_repo_manager=...)` 并注入 `AgentManager(block_manager=...)`（:167）；`block_manager_git.py:188-238 update_block_async`「Update a block. If git-enabled, **commits to git first**」→ 返回 commit 后同步 Postgres；门槛 `:52-70 _is_git_enabled_for_agent`（agent 需带 `GIT_MEMORY_ENABLED_TAG`）；主编辑路径 `update_memory_if_changed_async:1777` 正是调 `block_manager.update_block_async` | 两侧一致。**该不确定项应关闭：已接入，逐次 commit** |
| C77 | §5 | archival insert 后 rebuild 的具体展示原因未知 | ◐ | 见 C30：`prompt_generator.py:26-58` 已坐实 `archival_memory_size` / `archive_tags` 渲染进 `<memory_metadata>`；仅 executor 调用点无因果注释 | **[A only]**（A 原判「仍不能写成定论」）。**该不确定项应关闭** |
| C78 | §6.4 | 默认部署下 `conversation_search` 是纯子串匹配，与 docstring 的 hybrid 承诺不符 | ✓ | 同 C51 / C54 | **[B only]**（文档 §6.4 的独立表述） |
| C79 | §6.6 | 新增了论文没有的两个子系统：git 版本化 memory_repo、sleeptime 后台整理 agent | ✓ | 同 C20-C23、C37-C41、C76 | **[B only]** |
| C80 | §4 架构图 | `core_tool_executor.py:38` = 函数名到方法的 dispatch 表 | ◐ | `:38` 是 `execute()` 签名的 `) -> ToolExecutionResult:` 收尾行；`function_map = {` 在 **:41**，表体 41-55 | **[B only]**。行号偏 3 |
| C81 | §4 架构图 | `sleeptime_multi_agent.py:230` 标注 sleeptime 触发点 | ◐ | `:230` 在 `step()` 内但不是触发点（`bump_turns_counter` 在 :236、`_issue_background_task(` 调用在 :248）；且该文件不可达（见 C39/C40） | **[B only]** |
| C82 | §4 架构图 | 其余锚点 `message_manager.py:895`、`constants.py:116`、`letta_agent_v3.py:1967`、`orm/block.py`、`schemas/memory.py` | ✓ | 逐个打开命中：`message_manager.py:895 async def list_messages`；`constants.py:116` 同 C70；`letta_agent_v3.py:1967` 同 C64；`orm/block.py`（115 行）与 `schemas/memory.py`（884 行）均存在 | **[B only]** |
| C83 | 全文 | archive 代码可代表当前 Letta 产品 | ✓ | 文档明确否认；`origin/archive:AGENTS.md` 与 `origin/main:README.md` 也明确禁止这种推断 | 两侧。范围声明严谨 |

**小计**：✓ 60 / ✗ 4 / ◐ 19 / ? 0 = **83**

### 2.3 `methodology-flow.md`（派生文档，仅抽查引用锚点与退化条件）

> 本节完全来自版本 B（版本 A 未复核该文件），原样保留。

| # | 位置 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| M1 | Code 图 | `letta_agent_v3.py:1935` = agent step / auto persist | ✓ | `:1935 messages_to_persist: list[Message] = (initial_messages or []) + parallel_messages` | — |
| M2 | Code 图 | `message_manager.py:477` = Message rows | ✓ | `:477 async def create_many_messages_async` | — |
| M3 | Code 图 | `core_tool_executor.py:319` = memory tools | ✓ | `:319 async def core_memory_append` | — |
| M4 | Code 图 | `memory.py:68` = Block core memory | ✓ | `:68 class Memory(BaseModel, validate_assignment=True)` | — |
| M5 | Code 图 | `memory.py:143` = `Memory.compile` | ◐ | `:143 def _render_memory_blocks_standard`；`compile` 在 `:688` | 锚点指向渲染器而非 compile（同 C42） |
| M6 | Code 图 | `settings.py:78-86` = partial evict 30% | ✓ | `:78` mode、`:86 partial_evict_summarizer_percentage: float = 0.30` | 但默认 v3 不走这条路（见 C56/C57） |
| M7 | Code 图 | `message_manager.py:977` = substring conversation_search | ✓ | `:977` 注释 + `:978 if query_text:` → ILIKE / JSON LIKE | — |
| M8 | Code 图 | `letta_agent_v3.py:1915` = tool result Message | ✓ | `:1915 # 5f. Create messages using parallel message creation` | — |
| M9 | Code 图 | `letta_v1.py:22` = plain text yields | ✓ | 同 C65，行号精确 | — |
| M10 | dead 图 | `core_tool_executor.py:307` = archival insert | ✓ | `:307 async def archival_memory_insert` | — |
| M11 | dead 图 | `passage_manager.py:543` = Archive Passage | ✓ | `:543 async def insert_passage` | — |
| M12 | dead 图 | `helper.py:1241` = Native cosine | ◐ | 文件实为 `services/helpers/agent_manager_helper.py`；cosine 排序在 `:1245`（pgvector）/`:1252`（SQLite），1241 是其上文分支 | 文件名简写 + 行号偏 4 |
| M13 | optional 图 | `block_manager_git.py:188` = git-enabled Block history | ✓ | `:188 async def update_block_async`（"If git-enabled, commits to git first"） | — |
| M14 | optional 图 | `server.py:784` = 每 5 轮 | ✓ | 同 C38 | — |
| M15 | optional 图 | `sleeptime_multi_agent_v4.py:257` = 后台 V3 agent | ✓ | `:257 sleeptime_agent = LettaAgentV3(` | 比 `code-architecture.md` 引的 v1 文件更准确 |
| M16 | optional 图 | `message_manager.py:1175` = Turbopuffer hybrid | ◐ | `:1175` 是注释 `# check if we should use turbopuffer`，判断在 `:1176` | 偏一 |
| M17 | dead 表 | `constants.py:115-116`、`agent_manager_helper.py:1298-1302` | ✓ | `:115 BASE_TOOLS = [...]`、`:116 DEPRECATED_LETTA_TOOLS`；同 C71 | — |
| M18 | dead 表 | `agent_loop.py:20-43` 路由 | ✓ | `:20 if agent_state.agent_type in [AgentType.letta_v1_agent, AgentType.sleeptime_agent]:` … `:43 elif agent_state.enable_sleeptime and ...` | 行号区间精确 |
| M19 | dead 表 | `letta_agent_v2.py:1241-1285` 保留心跳 | ✓ | `:1241 def _decide_continuation`、`:1250 continue_stepping = request_heartbeat`、`:1285 return` | — |
| M20 | dead 表 | `agent_manager.py:410-418`、`server.py:965-978` | ✓ | `:410-413` letta_v1 分支 + discard；`:967-968` text_is_assistant_message | 比 `code-architecture.md` 的 `:412` 更准确（见 C74） |
| M21 | 退化条件 | 「`Store:Git` 只在 memfs 已配置且 agent 带 `git-memory-enabled` tag 时生效」 | ✓ | `server.py:155-161`；`block_manager_git.py:52-70`（查 `AgentsTags.tag == GIT_MEMORY_ENABLED_TAG`） | — |
| M22 | 退化条件 | 「Sleeptime 默认每 5 轮，但只有 `enable_sleeptime=True` 且创建时有 embedding config 才建后台 agent」 | ✓ | `server.py:756-758` 无 embedding config 即 `return None`；`agent_loop.py:20-31` 无 group 时回落普通 V3 | — |
| M23 | 边界声明 | 「Code 图不代表当前 Letta 产品」「retired archive 历史快照」 | ✓ | `origin/archive:AGENTS.md` 与 `origin/main:README.md` 均如此声明（同 C1/C2/C4） | 免责声明到位 |

**小计**：✓ 20 / ✗ 0 / ◐ 3 / ? 0 = **23**

---

## 3. 步骤清单 — 论文侧（arXiv:2310.08560v2）

> 两份报告的步骤表已合并：A 的 `canonical module` 词表与 B 的 `prim` 词表**并列保留**（同一步骤两套标签互为交叉检验）。`~` = 可选 / 条件触发。

### 3.0 离线一次（仅文档分析实验）

| # | name（论文原称） | trigger | in → out | llm | store | canonical module [A] | prim [B] |
|---|---|---|---|---|---|---|---|
| W0 | "We precompute embeddings and load them into the database"（§3.2.1） | 离线一次（实验准备） | Wikipedia 文档 → 向量 + 文本行 | no（embedding 模型，非对话 LLM） | archival storage（PostgreSQL + pgvector，HNSW） | `Retrieval:Emb` > `Store:Vector` | `P-EMBED > P-ANNINDEX > P-PERSIST` |

### 3.1 写入侧（每 event / 每 turn）

| # | name | trigger | in → out | llm | store | canonical module [A] | prim [B] |
|---|---|---|---|---|---|---|---|
| W1 | events trigger LLM inference（§2.4） | 每 event（用户消息 / 系统消息 / 用户交互 / 定时事件） | 外部事件 → 待处理输入 | no | — | `Sched:QueueManager` | `P-INTAKE` |
| W2 | Queue Manager append（§2.2） | 每 turn | 新消息 → FIFO 尾部 | no | main context / FIFO queue | `Sched:QueueManager` > `Store:Plaintext` | `P-INTAKE` |
| W3 | 双写 recall storage（§2.2） | 每 turn | incoming message + LLM output → 消息库 | no | recall storage | `Store:Database` | `P-PERSIST` |
| W4 | "concatenates the prompt tokens and triggers the LLM inference"（§2.2） | 每 turn | 三段 main context → prompt 字符串 | 1 次主推理（边界外） | main context | `Sched:QueueManager` | `P-ASSEMBLE` |
| W5 | memory pressure warning（§2.2，e.g. 70%） | prompt 超 warning count | token 计数 → 系统警告消息，LLM 决定是否搬运 | 主推理 | FIFO queue | `Sched:QueueManager` > `LLM:SelfEdit` | `P-EVICT`（阈值监控段） |
| W6 | `working_context.append/replace`（§2.1、Fig.1/4） | LLM 自主函数调用（常由 W5 触发） | 当前上下文事实 → append / replace 后的定长文本块 | 0 次额外（就是这一步的函数调用输出） | working context | `LLM:SelfEdit` > `Store:Plaintext` | `P-EXTRACT + P-CONFLICT` |
| W7 | ~archival insert（§2.2 概念路径；实验里为 W0 预加载） | ~memory pressure 时 LLM 自选目的地。**论文无任何实验 / 示例走过这条分支**（见 P22、P45） | 任意长度文本 → embedding + external DB | 无额外对话 LLM | archival vector DB | `Retrieval:Emb` > `Store:Vector` | `~P-EMBED > ~P-PERSIST` |
| W8 | queue flush（§2.2，e.g. 100% → 驱逐 e.g. 50%） | prompt 超 flush count | FIFO 前段 → 移出 main context（recall 仍在） | no | main context | `Sched:QueueManager` | `P-EVICT` |
| W9 | recursive summary（§2.2 + §2.1 index 0） | 每次 flush | 旧摘要 + 被驱逐消息 → 新摘要，置于 FIFO 首位 | **论文未写清**是否独立调用 | main context / FIFO[0] + recall DB | `LLM:Summarize` > `Store:Plaintext` | `P-AGGREGATE` |

### 3.2 检索侧（每 event，agent 自主）

| # | name | trigger | in → out | llm | store | canonical module [A] | prim [B] |
|---|---|---|---|---|---|---|---|
| R1 | event-driven inference | 用户 / 系统 / 定时事件 | event → main-context prompt | 1 次 | — | `IO:Query` > `LLM:SelfEdit` | `P-INTAKE` |
| R2 | "Memory edits and retrieval are entirely self-directed"（§2.3） | 每 event | 上下文 → 函数调用 + query 串 | 0 次额外（同一步推理） | — | `LLM:SelfEdit` | `P-QUERYPARSE` |
| R3 | `recall_storage.search(...)`（Fig.2） | LLM 自主调用 | 自然语言 query → 历史消息页 | 无额外 LLM | recall DB | `Retrieval:Unspecified` > `Store:Database` | **算法未披露**：可能落 `P-DENSE` 或 `P-SPARSE`，论文不足以判定 |
| R4 | `archival_storage.search(...)`（Fig.6/8） | LLM 自主调用 | query embedding → cosine top-K / 分页 | 无额外 LLM | PostgreSQL + pgvector + HNSW | `Retrieval:Emb` > `Store:Vector` | `P-DENSE` |
| R5 | function-result feedback（§2.4 + §2.3 分页） | 每次函数结束（含 runtime error） | results / 报错 → main context | no | FIFO / main context | `Store:Plaintext` | `P-ASSEMBLE` |
| R6 | function chaining（`request_heartbeat=true`；无 flag = "a yield"） | 每次函数调用后 | 结果 → 立即下一次推理 / 等外部事件 | 每跳 1 次主 LLM | — | `Sched:Heartbeat` | `P-TOOLLOOP` |
| R7 | answer / yield | 找到答案或不再请求 heartbeat | main context → 用户回答 | 1 次主 LLM | — | `LLM:Answer` | `P-GENERATE`（记忆系统边界之外） |

### 3.3 系统边界（论文侧）

- **MemGPT runtime（记忆系统本体）**：W1–W9、R1–R6 全部——Queue Manager（append / 双写 recall / 阈值监控 / 生成摘要 / 执行 eviction）、Function Executor（解析、校验、执行、把结果写回 main context、读 heartbeat flag）、main context 三段组装、archival + recall 两个外存、heartbeat 调度。
- **外部无状态计算（边界外）**：LLM Processor 本身，只做「吃 prompt tokens、吐 completion tokens」（W4 的推理动作与 R7）。
- **共享接口区**：main context 与 completion / function-call envelope。LLM 从 system instructions / schema 获知可用 memory tools 与 heartbeat 参数——**心跳 flag 由 backbone 生成，调度语义由 MemGPT 侧实现**，这是一条双向接口而非单向黑箱（这正是 P55 判 ✗ 的依据）。
- **评测脚本侧**：W0 的 Wikipedia 语料预 embedding、MSC/DMR 数据构造、LLM judge（§6.1.2 / 6.1.5）——属实验装置，不是运行时机制。

---

## 4. 步骤清单 — 代码侧（`origin/archive@56ba9c25`，默认 `letta_v1_agent` → `LettaAgentV3`）

> `~` = 可选 / 条件触发；**`[dead]`** = 实现仍在但默认建号不可达。归档工具、git memory、sleeptime 都是条件路径。

### 4.1 写入侧

| # | name（代码原称） | trigger | in → out | llm | store | canonical module [A] | prim [B] |
|---|---|---|---|---|---|---|---|
| A1 | message persistence（`message_manager.py:477`；v3 组装点 `letta_agent_v3.py:1935`） | 每 step（进出消息全量） | user / assistant / tool message → ORM rows | no | Message / PostgreSQL 或 SQLite | `Store:Database` | `P-INTAKE > P-PERSIST` |
| A2 | core memory 自编辑（默认集 `memory_replace`/`memory_insert`；另有 `memory(command=...)`、`memory_apply_patch`、`memory_rethink`：`core_tool_executor.py:346/683/1014/403/743`） | agent 自主，主循环内 | 对话事实 → Block 文本 → DB 更新 | 0 次额外（当前这步的工具调用） | `blocks` 表 | `LLM:SelfEdit` > `Store:Plaintext` | `P-EXTRACT + P-CONFLICT + P-PERSIST` |
| A3 | `update_memory_if_changed_async` → `rebuild_system_prompt_async`（`agent_manager.py:1747-1795`） | 每次成功编辑，**同步** | 新 Block 值 → 重渲染的 system prompt | no | — | `Store:Plaintext` | `P-ASSEMBLE` |
| A4 | ~git-backed Block commit（`block_manager_git.py:188-238`；`memfs_client_base.py`） | ~memfs 已配置 **且** agent 带 `git-memory-enabled` tag | Block edit → `{label}.md` commit（先 git 后 Postgres） | no | 本地 `~/.letta/memfs/` 或云端 memfs 服务 | `Store:Git` | `~P-PERSIST`（版本化变体） |
| A5 | ~sleeptime 后台整理（`agent_loop.py:20-43` → `sleeptime_multi_agent_v4.py:140-157,257`；频率 `server.py:784` 默认 5） | ~`enable_sleeptime=True` 且有 embedding config；每 5 轮 | 最近 transcript → 后台 agent 改写共享 Blocks | **1 次独立 LLM run**（另起 `LettaAgentV3`，用户不可见） | shared Blocks（`server.py:762` 共享 block_ids） | `Sched:Sleeptime` > `LLM:SelfEdit` | `~P-AGGREGATE + ~P-CONFLICT` |
| A6 | **默认压缩路径**：`compact_messages()`（`letta_agent_v3.py:72,938,2109` → `summarizer/compact.py:135`），阈值 `get_compaction_trigger_threshold`（非 GPT-5=100%、GPT-5 系列=90% 上下文窗口） | token 超阈值 / context exceeded | in-context 消息序列 → 摘要 + 保留尾部 | **1 次**（可被 `compact.py:42-131 build_summarizer_llm_config` 换成更便宜的模型） | 只改 in-context 序列，**Message DB 行保留** | `LLM:Summarize` > `Store:Plaintext` | `P-EVICT > P-AGGREGATE` |
| A6' | **（非默认）** `Summarizer` + `PARTIAL_EVICT_MESSAGE_BUFFER`：按**消息条数** 驱逐 30%、`simple_summary()` 同步生成、插到 index 1（`summarizer.py:136-203`；`settings.py:78,86`） | 仅 `LettaAgentV2` / legacy `letta_agent.py` | 同上 | 1 次同步 summarizer LLM | 同上 | `LLM:Summarize` > `Store:Plaintext` | `P-EVICT > P-AGGREGATE` |
| A7 | **[dead]** `archival_memory_insert` → `insert_passage`（`core_tool_executor.py:307`；`passage_manager.py:543`）→ embedding → pad 至 4096 → `ArchivalPassage` + `PassageTag` 双写 | 默认工具集已移除（`constants.py:116`），需显式挂载；`enable_sleeptime` 分支也只给 search 不给 insert | content → 向量行 + tag 行 | 无额外对话 LLM（embedding 模型） | Archive / vector DB 或 Turbopuffer | `Retrieval:Emb` > `Store:Vector` | `~P-EMBED > ~P-PERSIST` |

### 4.2 检索侧

| # | name | trigger | in → out | llm | store | canonical module [A] | prim [B] |
|---|---|---|---|---|---|---|---|
| S1 | 核心记忆**不检索**：`Memory.compile()` 渲染进 system prompt（`memory.py:688`；渲染器 `:143/:175/:205`） | 每轮 LLM 调用 | 全部 Block（**git 模式下仅 `system/*`**，`:122-130`）→ `<memory_blocks>` XML / git tree | no | Block / SQL | `Store:Plaintext` | `P-ASSEMBLE` |
| S2 | LLM 决定调 `conversation_search` 并写 query（`base.py:87`） | 每 query | 上下文 → 工具调用参数 | 0 次额外 | — | `LLM:SelfEdit` | `P-QUERYPARSE` |
| S3 | `conversation_search` 默认 SQL 路径：`list_messages` 的 `ILIKE '%q%'`（Postgres）/ `JSON_EXTRACT ... LIKE`（SQLite）（`message_manager.py:895,977-993`），叠加 roles / start_date / end_date 过滤 | agent 工具调用 | query 串 → 命中消息（按 `created_at` 排序） | 无额外 LLM | Message / SQL | `Retrieval:Substring` > `Store:Database` | **[NEW] `P-SUBSTR`** + `P-SYMFILTER` |
| S4 | ~Turbopuffer message search：`search_mode="hybrid"` 向量 + 全文，`_reciprocal_rank_fusion` 融合（`message_manager.py:1176`；`tpuf_client.py:1371`） | ~`use_tpuf` + `tpuf_api_key` + `openai_api_key`（+ `embed_all_messages`） | query → RRF 排序结果 | embedding，非对话 LLM | Turbopuffer | `Retrieval:Emb` + `Retrieval:FTS` | `~P-DENSE + ~P-SPARSE > ~P-FUSE` |
| S5 | 结果过滤：跳过 `role=tool`、跳过调用过 `conversation_search` 的 assistant 消息（`core_tool_executor.py:151-166`） | 每次调用 | 命中集 → 去递归集 | no | — | — | `P-SYMFILTER` |
| S6 | **[dead]** `archival_memory_search` → `query_agent_passages_async`（`agent_manager.py:2416-2480`）：TPUF=hybrid；Native=pgvector/SQLite cosine top-k；无 embedding config 时退化 `lower(text) LIKE '%q%'`（`agent_manager_helper.py:1180-1260`） | 默认工具集已移除（但 `enable_sleeptime` 分支仍挂 search，见 C72） | query → top_k 段落 | embedding，非对话 LLM | Archive / vector DB | `Retrieval:Emb` / `Retrieval:Substring` | `~P-DENSE`（退化时 `~P-SUBSTR`） |
| S7 | 工具返回值作为 Message 落库并进入下一轮 prompt（`letta_agent_v3.py:1915,1935`） | 每次工具执行 | 结构化结果 → Message → 下一轮 prompt | no | Message / SQL | `Store:Database` | `P-ASSEMBLE` |
| S8 | `_decide_continuation`（`letta_agent_v3.py:1967-2036`）：调了工具就继续，没调就结束；tool rules / max step 可覆盖 | 每 step 末 | 本步是否有 tool_call → 继续 / 停 | 每步 1 次主 LLM | — | `Sched:ToolLoop` | `P-TOOLLOOP` |
| S9 | 纯文字输出即视为回复用户（`server.py:968 text_is_assistant_message`） | 无工具调用时 | completion → assistant message | 1 次主 LLM | Message / SQL | `LLM:Answer` | `P-GENERATE` |

### 4.3 环境与配置退化

- **默认 agent 工具退化**：`archival_memory_insert/search` 被 `DEPRECATED_LETTA_TOOLS` 从 base tools 移除，默认路径只剩 Block 常驻记忆 + Message 历史检索；需显式挂载才能恢复 Passage 路径。**唯一反例**：`agent_create.enable_sleeptime` 命中时挂 `BASE_SLEEPTIME_CHAT_TOOLS`，仍带 `archival_memory_search`（`agent_manager.py:404-405`；`constants.py:133`）。
- **Native archive**：有 embedding config 时纯 cosine；无 embedding config 时退化为大小写无关 substring。
- **Message search**：无 Turbopuffer 时，docstring 所称 hybrid 退化为 SQL substring；`should_use_tpuf()` 需要 `use_tpuf` + `tpuf_api_key` + `openai_api_key` 三者齐备（消息侧再加 `embed_all_messages`），**自托管默认全关**。
- **Git memory**：memfs 未配置或 agent 无 `git-memory-enabled` tag 时，`Store:Git` 整段旁路为空，只写普通 SQL Block；且 git 模式会改变 `Memory.compile` 的渲染范围（仅 `system/*` 进正文）。
- **Sleeptime**：`enable_sleeptime=False` 时不存在后台整理；创建 sleeptime agent 还要求 embedding config（`server.py:756-759`）。
- **压缩路径分叉**：默认 `LettaAgentV3` 走 `compact_messages`（token 阈值 100%/90%），非默认 V2 与 legacy 走 `Summarizer` 的按条数 30% partial evict——**两条路的阈值口径与摘要模型都不同**。
- **适配层**：`memory-bench/servers/letta/` 下**没有任何 `.py`**（只有三份 md 与 assets），本仓未为 letta 写 MCP 适配层，因此不存在「适配层 vs 上游」的差异需要核对。
- **产品范围**：整个 code 视角都是 retired Letta V1 server 的历史机制，不能用于宣称当前 Letta 行为或性能。

---

## 5. 论文 ↔ 代码分歧

> A 的 D1-D10 与 B 的 X1-X14 已按同一断言合并；仅一侧提出的保留并标 `[A only]` / `[B only]`。

| # | 分歧 | 分类 | 论文侧证据 | 代码侧证据 |
|---|---|---|---|---|
| D1 | 多步执行的驱动信号：显式 heartbeat flag → 「这步有没有调工具」 | **两边都有但控制条件不同** | `txt:212-217,323-337`；§2.4 "functions can be called with a special flag..."；"If this flag is not present (a yield)..." | `letta_agent_v3.py:1967-2036`（不读 flag，`:2071 request_heartbeat=False`）；规则写进 `letta_v1.py:22`；旧信号仍活在 `agent.py:563,834-842`、`letta_agent.py:1769,1875-1919`、`letta_agent_v2.py:1126,1241-1250` |
| D2 | archival 是核心默认层 vs 默认工具集断开 | **paper-active / code-default-dead** | `txt:207-217,465-490`；§3.2.1 全部文档实验依赖它 | `constants.py:115-116`；`agent_manager_helper.py:1298-1302`（is_v2 真假都减）；**例外**：`agent_manager.py:404-405` 的 `enable_sleeptime` 分支仍挂 `archival_memory_search`（`constants.py:133`） |
| D3 | `send_message` 也是函数 vs 默认纯文本即用户回复 | **行为替换** | Fig.3 与 §2.4 的函数控制流；论文把 `send_message` 与记忆函数并列 | `agent_manager.py:413 tool_names.discard("send_message")`；`server.py:968 text_is_assistant_message`；同样受 `enable_sleeptime` 分支影响 |
| D4 | recall 检索算法未说明 vs 默认 SQL substring，且 docstring 过度承诺 | **code-only specificity** | `txt:181-190`；Fig.2 只给自然语言 query | `message_manager.py:895,977-993,1220-1260` 子串匹配；docstring 却自称 "hybrid search (text + semantic similarity)"（`base.py:87`） |
| D5 | working context 单块概念 vs label 化 Block + 多种编辑工具 | **code extension** | `txt:165-170` | `schemas/memory.py:68-80`；`core_tool_executor.py:319-773,1014-1068` |
| D6 | 单 agent 自整理 vs 可选 sleeptime 后台角色 | **code-only** | 论文方法只有单 Agent loop | `agent_loop.py:20-43` → `sleeptime_multi_agent_v4.py:132-280`；频率 `server.py:784`；专用 persona `sleeptime_memory_persona` |
| D7 | recall / archival 为单 agent 叙事 vs Archive 可跨 agent 共享 | **code-only** | §2 无共享语义 | `orm/archive.py:24-25,55-59`；`ArchivesAgents` 关联表 |
| D8 | recursive summary 的调用者、位置与模型 | **code resolves paper gap + 行为不同** | 摘要放 FIFO **index 0**（`txt:175-177`）；生成者 / prompt / 模型未披露（`txt:246-248`） | `Summarizer` 放 **index 1**（index 0 是 system message，`summarizer.py:151,166-168`）；默认 v3 的 `compact.py:42-131` 还可把摘要调用路由到**另一个更便宜的模型** |
| D9 | 驱逐阈值与驱逐量 | **参数与口径都不同** | warning e.g. 70%、flush e.g. 100%、evict e.g. 50%，均按 **token**（`txt:224-248`） | 默认 v3：`get_compaction_trigger_threshold` = 100% 上下文窗口（GPT-5 系列 90%）触发 `compact_messages`；非默认 `Summarizer` 路径按**消息条数** 30%（`settings.py:86`），并自陈 "using message count instead of token count"（`summarizer.py:145`） |
| D10 | 无版本化 memory 概念 vs 可选 per-agent git history | **code-only** | 全文无 git / version history | `server.py:155-161`；`block_manager_git.py:1-40,188-285`；`memfs_client_base.py`；`block_markdown.py` |
| D11 | 分页多跳检索 | **paper-only** | §2.3 pagination 防溢出；Fig.6 `page=2`；§3.2.2 多跳 KV | `core_tool_executor.py:278-288 archival_memory_search` **无 page 参数**，单次返回 top_k；多步只能靠 agent 反复发起调用（`query_agent_passages_async` 内无迭代） |
| D12 | 记忆改写的唯一性语义 | **两边都有但行为不同** | Fig.4 只示范语义替换（James → Ex-boyfriend），未定义匹配语义 | `core_memory_replace` 全量替换、不校验唯一（`core_tool_executor.py:328-345`）；`memory_replace` 强制唯一并报出重复行号（`:346-401`） |
| D13 | 消息的物理删除 | **code-only** | 论文只说 "stored indefinitely"（`txt:248-251`），无删除机制 | `message_manager.py:822 / 1045-1067（CORE DELETE）/ 1094-1121` |
| D14 | 核心记忆是否恒在 context | **两边都有但行为不同** | working context 定长、始终在 main context 内（`txt:165-170`） | 标准 / 行号模式恒在；**git 模式下 `_get_renderable_blocks` 只渲染 `system/*`**，其余块只以 `<external>` 文件树出现（`memory.py:122-130,205-236`） |
| D15 | 「一个 agent 一个循环」 | **code-only（组件分化）** | §2 只有一个 LLM processor | 至少四条循环并存：`LettaAgentV3`（默认）、`LettaAgentV2`、legacy `letta/agent.py`（**已不可达**：`chat_completions.py:51` 调用的 `server.load_agent` 全仓无定义）、Sleeptime V3/V4 |

---

## 6. 新登记的 canonical module / primitive

### 6.1 canonical module（来自版本 A）

| module | 含义 | 登记理由 |
|---|---|---|
| `Sched:QueueManager` | 自动追加消息、监控 warning/flush、执行 context eviction | 论文的调度核心，不能等同于只负责继续推理的 `Sched:Heartbeat` |
| `Sched:ToolLoop` | 「调用工具就继续、纯文本就 yield」的默认 V3 调度 | 与显式 heartbeat 的可比较差异必须单列 |
| `Sched:Sleeptime` | 每 N 轮触发后台记忆整理 agent | 现有词表无后台协整理调度标签 |
| `Retrieval:Unspecified` | 文档确认存在检索接口，但算法未披露 | 防止把论文 recall search 错标成 embedding / BM25 |
| `Retrieval:Substring` | SQL `ILIKE '%query%'` / JSON LIKE 子串匹配 | 不是 BM25，也不是 full scan 的同义词 |
| `Retrieval:FTS` | 后端全文检索通道 | Turbopuffer hybrid 明确区分 vector 与 full-text，但仓内看不到其具体打分算法 |
| `Store:Git` | per-agent git-backed Block 历史 | `Store:Plaintext` 描述内容形态，不能表达版本化持久载体 |
| `Store:Database` | 未锁定具体引擎的结构化持久存储 | 论文只称 message database；archive 可用 PostgreSQL 或 SQLite，强标 `Store:SQLite` 会失真 |

### 6.2 新造 primitive（来自版本 B，按合并规则保留）

| 标签 | 定义 | 为什么必须新造 |
|---|---|---|
| **[NEW] `P-SUBSTR`** | 子串 / `LIKE` 模式匹配检索：对存储文本做 `ILIKE '%q%'` / `lower(text) LIKE` 之类的包含判断并按时间序返回，**无词项权重、无 IDF、无排序打分** | 种子词表里最接近的两个都不成立：`P-SPARSE` 特指 BM25（有词项权重与相关性排序），而 Letta 默认路径的 `conversation_search` 只是 SQL 包含匹配、结果按 `created_at` 排序（`message_manager.py:977-993`，metadata 里 `combined_score: None`）；`P-SYMFILTER` 指按 participant / 时间 / 标签的**符号过滤**，而这里子串匹配是**主召回通道**本身，不是叠加在召回之上的过滤。并进任一标签都会让跨系统骨架高估或低估这条通路。同一标签也适用于 `archival_memory_search` 在无 embedding config 时的退化分支（`agent_manager_helper.py:1259-1260`） |

其余步骤全部复用种子词表；`recall_storage.search`（论文侧）刻意不贴检索标签，因为原文不足以判定它是 dense 还是 sparse（对应 `Retrieval:Unspecified`）。

---

## 7. 复核统计（合并后重算）

| 判定 | paper-architecture.md | code-architecture.md | methodology-flow.md | 合计 |
|---|---:|---:|---:|---:|
| ✓ 属实 | 48 | 60 | 20 | **128** |
| ✗ 不实 | 2 | 4 | 0 | **6** |
| ◐ 部分属实 / 需加限定 | 6 | 19 | 3 | **28** |
| ? 无法核实 | 0 | 0 | 0 | **0** |
| **小计** | **56** | **83** | **23** | **162** |

**行来源分布**：两侧共同覆盖 **95** 行（paper 46 / code 49）；仅版本 A 覆盖 **16** 行（paper 3 / code 13）；仅版本 B 覆盖 **51** 行（paper 7 / code 21 / methodology 23）。

**判定冲突与仲裁**：两侧对同一断言给出不同判定的共 **15** 行，全部由本次合并重新打开代码 / 论文原文裁决——
- 采纳 B：P35（原文说 two nesting levels）、P54（函数返回值边指向只读段，是错边）、P56（附录有 persona 初始化线索）、C9（`block.py:20` 就是字段定义行）、C28（junction 表与 JSON 列双写均已见到）、C39（机制真实但实现不可达）、C42（`compile` 在 :688，git 模式只渲染 `system/*`）、C56 与 C57（`LettaAgentV3` 全文无 `Summarizer(`，走 `compact_messages`）、C68（`def load_agent` 零命中）、C72（`enable_sleeptime` 分支在 :404-405 抢先）、C74（discard 在 :413 且可被短路）。
- 采纳 A：P48（本机 `libtxt` 全文 grep 安全阀相关词零命中，可自行证伪，不必判 `?`）。
- 并记 / 折中：P18（A 的 `?` 指底层机制空白，B 的 ✓ 指文档断言属实，两义并存，计为 ✓）、C30（A 判 `?`、B 判 ◐，本次以 `prompt_generator.py:26-58` 坐实，升级为 ✓）。
- A 的强表述另立一行保留：C40（旧 sleeptime 文件不能代表当前默认路径，✗）与 C39（引用本身，◐）并存，两个判定都不丢。

**`?` 归零说明**：A 的 3 条与 B 的 2 条 `?` 全部被消除——论文侧因本机 `libtxt` 到位可直接 grep 证伪穷尽性缺席断言（P48/P49），代码侧因重新打开 `prompt_generator.py`、`agent_loop.py` 与 `git grep def load_agent` 而定论（C30/C68）。

**证据强度**：代码侧 100% 为 `git show origin/archive:<file>` 亲自打开对应行核对；论文侧以 A 的 `txt:` 行号为主干（`pdftotext -layout` 提取），本次新增与仲裁性证据用本机论文库副本的 `libtxt:` 行号（两套行号系统不可互换，见页首）。B 原报告中标 `[弱否定]` 的中介式否定证据，凡能落到 `libtxt` 行的均已替换为可复现的本地 grep 结果。

**引用锚点可靠性**：`code-architecture.md` 引用的 24 个 `file.py:NNN`(区间) 中，18 个精确命中定义行 / 目标行；4 个偏 1–3 行或指向紧邻注释（C74/C80、M12/M16）；1 个文件路径写错（C3 `letta/AGENTS.md` → 根 `AGENTS.md`）；1 个指向不可达实现（C39 `sleeptime_multi_agent.py`）。没有任何被引文件不存在。

**优先修正**（按影响面排序）：
1. C56/C57 —— 默认 `letta_v1_agent` 的压缩路径写错对象（`Summarizer`/partial-evict → 应为 `compact_messages`，阈值 100%/90%、摘要模型可替换）。
2. C13 —— 旧 `core_memory_replace` 不校验唯一性，是全量 `str.replace`。
3. C72/C74 —— 「默认建号一定去掉 archival / 一定 discard send_message」有 `enable_sleeptime` 反例。
4. C35 —— Message 存在三个硬删除入口，「从不物理删除」不成立。
5. C39/C40 —— legacy `sleeptime_multi_agent.py` 与 legacy `letta/agent.py:Agent` 均不可达，不能当活跃路径引用。
6. P54/P55 —— 架构图的函数返回边指向只读 `System Instructions`；「LLM 不知道心跳存在」与 Fig.3 图注直接矛盾。
7. C42/P35 —— `Memory.compile` 的「100% 在场」需加 git 模式限定；Nested KV 应写「两层嵌套（三个 UUID）」。
8. C76/C77/C30/C68 —— 四处「没跟到底」的不确定项已可关闭，应改写为定论。

方法流程图（`methodology-flow.md`）应按上述勘误重绘，不复刻原架构图中的错误边。

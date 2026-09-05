# memos 架构文档复核报告

> 复核日期 2026-09-05；论文源 `Li-2025-MemOS-A-Memory-OS-for-AI-System.txt`（3094 行，arXiv:2507.03724v4，txt:1）；
> 代码源 `MemOS` @ `8553242`（2026-08-18, "docs: announce DeepSeek Harness support (#2263)"）。
> 复核对象：`servers/memos/paper-architecture.md`（160 行）、`servers/memos/code-architecture.md`（256 行）。
> 附带核对了 `servers/memos/server.py`（memory-bench 的 MCP 适配层）与实机部署配置 `MemOS/.env`（21 行，实际生效的环境变量）。
> **本报告区分两个层：**（a）**上游 MemOS REST 服务**（`MemOS/src/memos/**`）；（b）**memory-bench 适配层**（`servers/memos/server.py`）。
> `code-architecture.md` 第 1–6 节讲的是 (a)，第 7 节讲的是 (b)；本报告逐条注明核对的是哪一层。

---

## 1. 总评

`paper-architecture.md` 质量高：论文侧 40 条断言中 31 条完全属实、9 条部分属实，**零条不实**；且它自己抓出的两个论文内部矛盾（§5.2 五态 vs §5.4.3 四态；`task–concept–fact` vs `topic–concept–fact`）经逐字核对**完全成立**（txt:1309-1310 / 1466-1467；txt:792 / 1421）。它的问题集中在**章节锚点串位**——多处把 §5.2 的内容记成 §5.4.1 或 §5.3.1，内容对、出处错。

`code-architecture.md` 的 `file.py:NNN` 命中率相当高（108 条中 73 条完全属实，多数行号一字不差，包括 `manager.py:239-240` 的 TODO 注释、`simple_struct.py:295-302` 的 bug #1355 注释、`config.py:1242-1243` 的两个环境变量），但有 **10 条不实**，其中三条是**结构性错误**，会让读者对"我们到底测了什么"产生系统性误解：

1. **存储后端写反了**：文档说"向量作为节点属性存进 Neo4j，检索走 Neo4j 原生向量索引"。实机 `.env:14` 是 `NEO4J_BACKEND=neo4j-community`，走 `Neo4jCommunityGraphDB`，它在写入时把 `embedding` 从 metadata 里 **pop 出来送进 Qdrant**（`neo4j_community.py:151-165,194`），检索时走 `self.vec_db.search(...)`（`neo4j_community.py:360`）。文档第 5 节把"Qdrant 服务于谁"列为未验证，实际答案就在这条主链路上（`api/config.py:781-795`）。
2. **写入侧的 mem_reader 认错了类**：文档整个第 2 节按 `SimpleStructMemReader` 写。实机 `.env` **没有设 `MEM_READER_BACKEND`**，代码默认是 `"multimodal_struct"`（`api/config.py:657`）→ `MultiModalStructMemReader`（`mem_reader/factory.py:22`）。该子类覆写了 `get_scene_data_info`（直通，不切 10 条窗口）、`_read_memory`、`_get_llm_response`，并在 fine 模式下跑 **4 路并行 LLM 抽取**（string / tool-trajectory / skill / preference，`multi_modal_struct.py:1020-1049`）。
3. **"写入路径上唯一一次必经的 LLM 调用"不成立**：即使按 `simple_struct` 算也是"每个窗口一次"（`simple_struct.py:407-408`）；按实际的 `multimodal_struct` 算是 4 路 × 每路每窗口一次。这也顺带解释了检索侧为什么默认要查 Tool/Skill/Preference 三种记忆——它们是写入时真的被造出来的。

另有两条影响可复现性的错误：reranker 生效路径认错（不是 `tree.py:66` 的兜底，`SimpleTreeTextMemory.__init__` 根本不执行那段），以及 `metadata.chat_time` 实际**不存在**（只存在于 `metadata.sources[].chat_time`），意味着 `server.py:143` 的时间戳修复恒回落到 `created_at`。

---

## 2. 逐条核对表

判定符号：`✓` 属实 / `✗` 不实 / `◐` 部分属实或需加限定 / `?` 无法核实。
论文证据格式 `txt:NNN`；代码证据均相对 `MemOS/` 仓库根。

### 2A. `paper-architecture.md`

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| P1 | 抬头 | arXiv:2507.03724v4 | ✓ | txt:1 `arXiv:2507.03724v4 [cs.CL] 3 Dec 2025` | |
| P2 | §1 | "把 LLM 记忆资源类比成 OS 要管理的硬件资源（§3.2）" | ✓ | txt:669-679（§3.2 起于 txt:667） | |
| P3 | §1 | "统一封装单元 MemCube（§4.2）…元数据+载荷" | ✓ | txt:878-891 | |
| P4 | §1 | 三类记忆 Plaintext/Activation/Parameter | ✓ | txt:772-774（§4.1 起于 txt:756） | |
| P5 | §1 | 三层架构 接口/操作/基础设施（§5.1） | ✓ | txt:1144-1147 | |
| P6 | §1 | "中枢调度器 MemScheduler（§5.4.2）" | ✓ | txt:1425-1431 `MemScheduler is the central memory dispatcher` | |
| P7 | §2 | 否定式："论文没有给出类似 REST 端点这样具体的触发方式" | ✓ | 全文无 API 端点/接口签名级定义；§5.3.2 只列 Provenance/Update/LogQuery 三类 API 语义（txt:1354-1364） | 已实际证伪尝试 |
| P8 | §2 | "§5.2 开篇：系统执行由用户交互或自动触发的任务启动" | ✓ | txt:1199-1200 | |
| P9 | §2 | Figure 8：`My dog needs help!` / `Semantic Parse: The user has a dog.` / `MemoryCube (extracted)` 与 `(retrieved)` 同图 | ✓ | txt:1227 / 1239-1240 / 1242-1243 / 1269-1270；检索例文 txt:1252-1254 | |
| P10 | §2 | Figure 6 三种 payload JSON 逐字引用 | ✓ | txt:916-919（explicit/text）、921-924（activation/tensor/injection_layer 12）、926-929（parametric/lora_patch/mlp.6.down_proj） | 逐字一致 |
| P11 | §2 | §5.4.2 Type-Aware Transformation 三条分派规则 | ✓ | txt:1435-1441 | |
| P12 | §2 | 否定式："论文没写存的过程调不调 LLM；没有伪代码" | ✓ | 全文 grep 无 `pseudocode` / `Algorithm N` 块 | 已实际证伪尝试 |
| P13 | §2 | "§5.3.1：MemReader 将自然语言输入转成结构化 MemoryCall" | ✓ | txt:1343（§5.3.1 起于 txt:1335）；MemoryCall 字段定义在 §5.2 txt:1203-1205 | |
| P14 | §2 | "例如给定 'Summarize my meeting notes from last month'…（§5.3.1）" | ◐ | 该例出自 **§5.1** txt:1156-1159；§5.3.1 的例子是 `Remind me what the doctor said about my medication during last year's hospitalization`（txt:1341-1344） | 锚点串位 |
| P15 | §2 | "§4.1 提到 Plaintext Memory 支持冲突检测、去重、版本管理" | ✓ | txt:792-793（原文还有 forgetting policies） | |
| P16 | §2/§5 | 漏述：§5.3.1 明写 MemReader 支持 prompt rewriting / coreference resolution / dialogue memory slot filling | ◐ | txt:1344-1345 | 文档把 MemReader 说成"论文全文没写实现"，但论文确实声明了这三项能力（仍未说是否用 LLM） |
| P17 | §3 | "论文把执行路径分成四段：Retrieval→Scheduling→Lifecycle→Archiving" | ◐ | §5.2 实际有**五个** run-in 小标题：txt:1212 / 1218 / 1306 / 1308 / 1319；而 §5.2 正文 txt:1200 又自述为另一组四段（input parsing, memory scheduling, state management, storage archiving） | 计数与出处都需限定 |
| P18 | §3 | "MemOperator…构建 task-specific 索引和记忆图来筛候选（§5.4.1 'Memory Retrieval and Organization' 段）" | ◐ | 被引文字在 **§5.2** txt:1214-1217；`Memory Retrieval and Organization` 是 §5.2 的段标题（txt:1218），不是 §5.4.1 的子标题（§5.4.1 子标题为 Multi-perspective Memory Structuring / Hybrid Retrieval and Dynamic Dispatch / Pipeline Coupling and Caching Strategy / Task-Aligned Memory Routing） | 内容对、出处错 |
| P19 | §3 | Hybrid Retrieval：结构化（tags/时间跨度/布尔/ACL）+ 语义（embedding） | ✓ | txt:1408-1413 | |
| P20 | §3 | "可组合成复合查询（标签过滤+语义排序）" | ✓ | txt:1412-1413 | |
| P21 | §3 | Task-Aligned Memory Routing：topic–concept–fact 三层 + MemoryPathResolver 回答三问 | ✓ | txt:1418-1424 | |
| P22 | §3 | 否定式："论文没有明确说明单步还是多轮迭代；没有失败重试/反馈式扩展检索" | ✓ | 全文无 iterative retrieval / retry / re-retrieval 描述（`multi-hop` 仅出现在 §6 的 benchmark 任务类别里，txt:1611,1620,1821,2062） | 已实际证伪尝试 |
| P23 | §3 | MemScheduler 四指标 + 复诊场景三类记忆混合注入 | ✓ | txt:1301-1307 | |
| P24 | §4 图 | Memory API = Provenance / Update / LogQuery | ✓ | txt:1354-1364（§5.3.2） | |
| P25 | §4 图/边界 | Table 2 把三类记忆归 Core Operation Layer，类比 寄存器·微码 / Cache / I/O Buffer | ✓ | txt:697-712 | |
| P26 | §4 图 | MemGovernance 三元权限模型 / TTL / 审计 | ✓ | txt:1506（ternary permission model）、1512-1515 | |
| P27 | §4 图 | MemVault 多命名空间存储 | ✓ | txt:1524-1527 | |
| P28 | §4 图 | MemStore 跨 Agent 发布订阅 | ✓ | txt:1192-1193、1558-1566 | |
| P29 | §4 边界 | "论文的 OS 隐喻把 LLM Core 本身也当成 MemOS 要调度的资源之一" | ◐ | txt:685-686 原文是 `MemOS coordinates inference and memory block scheduling **via** the LLM Core and MemScheduler`——LLM Core 是调度**手段**而非被调度对象；不过 Figure 7 确实把 `Large Language Models` 画在 `MemOS` 框内（txt:1078,1088），结论方向可支持 | 需加限定 |
| P30 | §5 | "MemReader 到 MemoryCall 具体怎么实现，论文全文没写" | ◐ | 机制（LLM/规则/NER）确实没写；但能力清单写了（txt:1344-1345，见 P16） | |
| P31 | §5 | "写入这个动作从未脱离一次问答闭环被单独描述过" | ✓ | §5.2 是唯一的执行路径描述；§5.3.3 的 Memory Pipeline 是 retrieve→augment→update→archive，仍以已有记忆为输入（txt:1375-1381） | |
| P32 | §5 | "Activation Memory 跨 session 持久化/复用的具体格式或机制论文没给" | ◐ | §4.1 txt:808-810 给了定性说法（`Frequent KV patterns are cached to form low-latency "instant memory paths"`、`steering vectors or semantic templates`）；格式与触发机制确实没给 | 需加限定 |
| P33 | §5 | Parameter Memory 蒸馏的触发时机/数据量/开销论文没写 | ✓ | txt:819-822、1437-1439 均为定性 | |
| P34 | §5 | "MemGovernance 三元权限模型只描述效果（§5.5.1）" | ✓ | txt:1506-1510（`only physicians may access a patient's diagnostic records`） | |
| P35 | §5 | 生命周期阈值未量化，引 `if frequently accessed`→Activated 与 `no longer accessed for a prolonged period`→Archived（均标 §5.4.3） | ◐ | 第一句出自 **§5.2** txt:1311；第二句确在 §5.4.3 txt:1474 | 锚点串位；"未量化"结论成立 |
| P36 | §6.1 | §5.2 说五态（含 Expired），§5.4.3 说四态（缺 Expired）——论文自相矛盾 | ✓ | txt:1309-1310 vs txt:1466-1467 | 逐字成立；另注 §5.4.3 txt:1481-1484 还引入第三个状态 `Frozen` |
| P37 | §6.2 | `task–concept–fact`（§4.1）vs `topic–concept–fact`（§5.4.1）措辞不一致 | ✓ | txt:792 vs txt:1421 | 逐字成立 |
| P38 | §6.3 | "Figure 7 列出 Memory Pipeline、LogQuery API 等，Figure 8 没有明确画出这些子模块" | ◐ | Figure 7 确有 `Memory API/Pipeline`（txt:1036）与 `Memory Log Query（API）`（txt:1049）；但 **Figure 8 里画了 `Memory Pipeline`（txt:1237）和 `Memory API`（txt:1247）**，只有 LogQuery API 没画 | 需加限定 |
| P39 | §6.4 | "§6 是端到端 benchmark 分数，没有针对跨类型迁移做消融" | ✓ | §6.1 End-to-End（txt:1581）、§6.2 token/content（1713）、§6.3 chunk size & Top-K（1814）、§6.4 Memory Retrieval Robustness（2042）、§6.5 KV-Based Memory Acceleration（2067）——无跨类型迁移消融 | 已逐节核对 |
| P40 | §6.5 | "§6.5/§7 的延迟实验（Table 8、Figure 10）测的是 KV 注入 vs 全量 prefill 的 TTFT 加速" | ✓ | txt:2087-2090（Build / KV TTFT / Dir TTFT / Speedup 定义）、2368-2372、Table 8 题注 2406-2409、Figure 10 题注 2659 | 表/图排版落在 §7 页面内，文档已注明"§6.5/§7" |

### 2B. `code-architecture.md`

**核对的层**：C1–C98 针对 **上游 MemOS REST 服务**（`MemOS/src/memos/**`）；C99–C108 针对 **memory-bench 适配层**（`servers/memos/server.py`）。
关键前提：实机生效配置是 `MemOS/.env`（21 行）——`NEO4J_BACKEND=neo4j-community`(:14)、`MOS_RERANKER_BACKEND=cosine_local`(:13)、`EMBEDDING_DIMENSION=2048`(:12)、`ENABLE_CHAT_API=false`(:21)；**未设** `MEM_READER_BACKEND` / `MOS_ENABLE_REORGANIZE` / `FAST_GRAPH` / `BM25_CALL` / `FULLTEXT_CALL` / `SIMPLE_STRUCT_ADD_FILTER`。

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| C1 | §0 | 调研范围：`/product/add`(async_mode=sync) + `/product/search`(mode 未传→FAST) | ✓ | `servers/memos/server.py:73-79,118-119`；`api/product_models.py:386-389`；router prefix `/product`（`api/routers/server_router.py:68`） | |
| C2 | §1 | "写入时用**一次** LLM 调用把整段对话窗口翻译成几条事实陈述" | ✗ | 按 simple_struct 也是每窗口一次（`mem_reader/simple_struct.py:407-408`）；实机 reader 是 `MultiModalStructMemReader`，fine 模式 4 路并行 LLM（`mem_reader/multi_modal_struct.py:1020-1049`） | 见 C15/C20 |
| C3 | §1 | "连同其向量一起存成 Neo4j 图节点" | ◐ | 节点属性进 Neo4j，**向量被 pop 出来进 Qdrant**（`graph_dbs/neo4j_community.py:151-165,194`） | 见 C47 |
| C4 | §1 | "检索时默认不调 LLM，向量近邻+余弦重排+阈值过滤，原样返回" | ✓ | `task_goal_parser.py:46-47,55,73-81`；`reranker/cosine_local.py:63-100`；`api/handlers/search_handler.py:254` | |
| C5 | §1 | "论文的三种记忆统一调度、五态生命周期在这条路径上都没有对应实现" | ✓ | `api/handlers/component_init.py:245-249`（`act_mem=None, para_mem=None`）；`memories/textual/item.py:109`（status 只有 activated/resolving/archived/deleted） | |
| C6 | §2 | `server.py add_conversation` 每 session 一次 `POST /product/add`，显式 `async_mode="sync"` | ✓ | `servers/memos/server.py:69-79` | 适配层 |
| C7 | §2 | `server_router.py:127-130 add_memories` → `AddHandler.handle_add_memories` | ◐ | :127 是装饰器、:128 是 `def add_memories`，**真正的转发在 :134** | 行号漂移 |
| C8 | §2 | add_handler 构造 `SingleCubeView`（单 cube 时） | ✓ | `api/handlers/add_handler.py:130-142`（`len(cube_ids)==1` → SingleCubeView） | |
| C9 | §2 | `single_cube.py:56-84 add_memories` | ✓ | `def` 在 `multi_mem_cube/single_cube.py:59`，`return` 在 :86；引用区间覆盖函数体 | |
| C10 | §2 | "`single_cube.py:596` 附近 `_process_text_mem`" | ◐ | `_process_text_mem` 实际在 **:662**；:596 是 `add_before_search` 的异常分支 | 66 行漂移 |
| C11 | §2 | `single_cube.py:64` `sync_mode = add_req.async_mode or self._get_sync_mode()` | ✓ | `single_cube.py:64` 一字不差 | |
| C12 | §2 | `single_cube.py:687-689` sync 下 `extract_mode = "fast" if mode=="fast" else "fine"` | ✓ | `single_cube.py:686-689` 一字不差 | |
| C13 | §2 | `APIADDRequest.mode` 默认 `None` | ✓ | `api/product_models.py:652-653` | |
| C14 | §2 | "所以实际走 fine 分支" | ✓ | `single_cube.py:689`；`get_memory(..., mode=extract_mode)` 在 :712 | |
| C15 | §2 | "（`mem_reader/simple_struct.py`，被 `SimpleStructMemReader` 实现）" | ✗ | `MEM_READER_BACKEND` 代码默认 `"multimodal_struct"`（`api/config.py:657`）→ `MultiModalStructMemReader`（`mem_reader/factory.py:22`）；实机 `.env` 未设该变量（只有 `docker/.env.example-full:104` 设 simple_struct，实机用的不是它） | **结构性错误** |
| C16 | §2 | `_iter_chat_windows`(:315)、`chat_window_max_tokens=1024`(:207)、`overlap=200`(:315) | ✓ | `simple_struct.py:207,315` 一字不差 | 但该函数在实机 reader 下不被调用（C15） |
| C17 | §2 | "每条消息带 `role:` 和 `[chat_time]` 前缀拼成纯文本" | ✓ | `simple_struct.py:327-332` | |
| C18 | §2 | "把整段 `messages` 按 token 数切窗口" | ◐ | simple_struct 是**两层**窗口：先 `get_scene_data_info` 按 ≤10 条消息 / 2 条重叠切（`simple_struct.py:857-866`），再按 token 切；而 multimodal 版 `get_scene_data_info` 是直通（`multi_modal_struct.py:1257-1270`，注释 `TODO: split messages`） | |
| C19 | §2 | `_get_llm_response`(:274) 用 `SIMPLE_STRUCT_MEM_READER_PROMPT` 中英自动切换，调 `self.llm.generate` | ✓ | `simple_struct.py:274-277`（`PROMPT_DICT["chat"][lang]`）、:89-95、:260 | |
| C20 | §2 | "**这是写入路径上唯一一次必经的 LLM 调用**" | ✗ | fine 分支对**每个窗口**各调一次（`simple_struct.py:407-408`）；实机 reader 更是 4 路并行（string/tool-trajectory/skill/preference，`multi_modal_struct.py:1021-1049`），且 `_process_string_fine` 内部按 item 逐个调（:615,629） | **结构性错误** |
| C21 | §2 | 要求返回 `{"memory list":[{key,memory_type,value,tags}],"summary"}` | ✓ | `simple_struct.py:301-311`（兜底对象逐字给出这些键） | |
| C22 | §2 | `simple_struct.py:295-302` 的 "memory list" 必须带空格 + bug #1355 注释 | ✓ | `simple_struct.py:295-300` 一字不差 | |
| C23 | §2 | `_make_memory_item`(`simple_struct.py:220`) | ✓ | `simple_struct.py:220` 一字不差 | |
| C24 | §2 | "`memory` 字段存的是 LLM 输出的 `value`，不是原文" | ✓ | `simple_struct.py:239`（`memory=value`）+ :417（`value=m.get("value","")`） | |
| C25 | §2 | "`metadata.embedding = self.embedder.embed([value])[0]`（`simple_struct.py:220` 附近）" | ◐ | 实际在 **:247**（函数确于 :220 起） | 行号漂移 |
| C26 | §2 | `metadata.sources` 存该窗口原始消息（role/content/chat_time），不参与检索向量 | ✓ | `simple_struct.py:249,344-352,422`；向量算在 `value` 上（:247） | |
| C27 | §2 | `metadata.background` = 窗口 LLM 输出的 `summary` | ✓ | `simple_struct.py:250,423` | |
| C28 | §2 | 中文兜底替换 `长期记忆`→LongTermMemory / `用户记忆`→UserMemory（`simple_struct.py:405-408`） | ◐ | 实际在 **:411-415** | 行号漂移 |
| C29 | §2 | `confidence=0.99`、`type_="fact"` 是签名默认值，fine 分支未覆盖 | ✓ | `simple_struct.py:229-230`（签名）+ :416-425（fine 分支不传这两个参数） | |
| C30 | §2 | `SIMPLE_STRUCT_ADD_FILTER` 默认 `false`，默认不跑幻觉过滤 | ✓ | `simple_struct.py:709` `os.getenv("SIMPLE_STRUCT_ADD_FILTER","false")=="true"`；实机 `.env` 未设 | 一字不差 |
| C31 | §2 | "逐条问 LLM 要不要保留" | ◐ | `filter_hallucination_in_memories` 是**按 group 一次 listwise 调用**（`simple_struct.py:603-658`，:721-724 传整个 `memory_list`），不是逐条 | |
| C32 | §2 | `single_cube.py:734` `naive_mem_cube.text_mem.add(mem_group, ...)` | ✓ | `single_cube.py:734` 一字不差 | |
| C33 | §2 | `tree.py:103-114` `TreeTextMemory.add` 转发 `memory_manager.add(..., mode=self.mode)` | ✓ | `memories/textual/tree.py:103-114` 一字不差 | |
| C34 | §2 | `manager.py:138 _add_memories_batch`（默认批量路径） | ✓ | `.../tree_text_memory/organize/manager.py:138`；`use_batch: bool = True` 在 :94 | |
| C35 | §2 | `manager.py:169` 算出 `memory_type` 改写为 `WorkingMemory` 的 `working_metadata` | ✓ | `manager.py:169-171` 一字不差 | |
| C36 | §2 | `manager.py:239-240` TODO 注释，WorkingMemory 从未提交写库 | ✓ | `manager.py:239-241` 一字不差（`_submit_batches(graph_nodes, ...)` 只提交 graph 节点） | 高价值发现，属实 |
| C37 | §2 | `tree.py:83` `"WorkingMemory": 20` 配额 | ✓ | `tree.py:83` 一字不差 | |
| C38 | §2 | `manager.py:243-244` 只有 `is_reorganize` 为真才入 `GraphStructureReorganizer` 队列 | ✓ | `manager.py:243-246` 一字不差 | |
| C39 | §2 | `configs/memory.py:175,270` `reorganize` 默认 `False` | ✓ | 两处一字不差 | |
| C40 | §2 | `component_init.py:223` 从 config 读 `reorganize`，默认 False | ✓ | `api/handlers/component_init.py:223` 一字不差 | |
| C41 | §2 | `api/config.py:1234,1314` `MOS_ENABLE_REORGANIZE` 默认字符串 `"false"` | ✓ | 两处一字不差 | |
| C42 | §2 | "docker 部署的 `.env.example` 没有设置这个变量" | ✓ | `docker/.env.example`（49 行）无该变量；实机 `MemOS/.env` 亦无；`docker/.env.example-full:9` 显式写 `false` | |
| C43 | §2 | 否定式："写入之后不会有任何 LLM 驱动的图重组织/合并/去重" | ✓ | C38–C42 链条成立 | 已实际证伪尝试 |
| C44 | §2 | `docker/docker-compose.yml:28-53` 起 Neo4j 5.26.6 + Qdrant v1.15.3 | ✓ | `docker/docker-compose.yml:29`（`neo4j:5.26.6`）、:47（`qdrant/qdrant:v1.15.3`）；:19-20 注入 `QDRANT_HOST/PORT` | |
| C45 | §2 | "产品部署实际构造的是 `SimpleTreeTextMemory`（`component_init.py:229`）" | ✓ | `component_init.py:229-240` 一字不差 | |
| C46 | §2 | "其 `graph_db` 用的是 `Neo4jGraphDB`" | ◐ | 实际是子类 `Neo4jCommunityGraphDB`（`graph_dbs/factory.py:16`；`api/handlers/config_builders.py:47-49` 默认 `neo4j-community`；实机 `.env:14`） | 行为差异极大，见 C47 |
| C47 | §2 | "向量直接作为节点属性存进 Neo4j，检索走 `graph_dbs/neo4j.py:952` 的原生向量索引" | ✗ | 写：`graph_dbs/neo4j_community.py:151`（`embedding = metadata.pop("embedding", None)`）→ :155-165 组 `VecDBItem` → :194 `self.vec_db.add(vec_items)`。读：`neo4j_community.py:293` `search_by_embedding` → :360 `self.vec_db.search(...)`。`neo4j.py:952` 那行确实存在但属基类 `Neo4jGraphDB`（`NEO4J_BACKEND=neo4j` 才走），且**即使走基类，带 filter 时也不用 ANN 索引而是全表 `vector.similarity.cosine`（`neo4j.py:940-947`）** | **结构性错误** |
| C48 | §2/§5 | "Qdrant client 只在 `general.py`/`preference.py` 等另一套实现里出现…服务于哪个子系统未验证" | ✗ | `graph_dbs/neo4j_community.py:15,37` 用 `VecDBFactory`；`api/config.py:769-796 get_neo4j_community_config` 明写 `vec_config.backend="qdrant"`、`collection_name="neo4j_vec_db"`、`distance_metric="cosine"`、host/port 取 `QDRANT_HOST/QDRANT_PORT` | 未验证项已可结案 |
| C49 | §3 | `server.py retrieve` 不传 `mode`，`APISearchRequest.mode` 默认 `SearchMode.FAST` | ✓ | `servers/memos/server.py:118-119`；`product_models.py:386-387`；`SearchMode(str,Enum) FAST="fast"`（`types/general_types.py:90-93`） | |
| C50 | §3 | `_search_text`→`_fast_search`→`search_text_memories`→`tree.py:157`→`Searcher`(别名，实为 `AdvancedSearcher`)→`searcher.py:191` | ✓ | `single_cube.py:190,208-209,385,400`；`search/search_service.py:68,79`；`tree.py:24-26`（`AdvancedSearcher as Searcher`）、:157、:202-214；`advanced_searcher.py:25`（`class AdvancedSearcher(Searcher)`，未覆写 `search`） | 链条逐环打开确认 |
| C51 | §3 | `searcher.py:338` 把 `mode` 原样传给 `TaskGoalParser.parse` | ✓ | `.../retrieve/searcher.py:338-345`（同时传 `use_fast_graph=self.use_fast_graph`） | |
| C52 | §3 | `task_goal_parser.py:30-51` 的 mode 分派 | ✓ | `task_goal_parser.py:30-53` | |
| C53 | §3 | "`_parse_fast`（`task_goal_parser.py:53` 起）" | ◐ | 实际 `def _parse_fast` 在 **:55** | 行号漂移 |
| C54 | §3 | `use_fast_graph=True` 才用 jieba；否则 `ParsedTaskGoal(memories=[task_description], rephrased_query=task_description, ...)` 原样透传（:73-83） | ✓ | `task_goal_parser.py:61-71`（jieba 分支）/ :73-81（透传分支） | |
| C55 | §3 | "`use_fast_graph` 来自 `search_strategy.get("fast_graph", False)`（`searcher.py:78`）" | ◐ | 实际在 **:74**（:78 是 `_usage_executor`） | 行号漂移 |
| C56 | §3 | `api/config.py:1242` `"fast_graph": bool(os.getenv("FAST_GRAPH","false")=="true")` | ✓ | 一字不差（另一副本在 :1323） | |
| C57 | §3 | 否定式："FAST 模式下查询理解不调 LLM，只是原样透传 query 文本" | ✓ | `task_goal_parser.py:46-47` → `_parse_fast` 不触碰 `self.llm` | 已实际证伪尝试 |
| C58 | §3 | `api/config.py:1243` `"bm25": bool(os.getenv("BM25_CALL","false")=="true")` | ✓ | 一字不差 | |
| C59 | §3 | "即关键词检索（BM25）路径默认不启用" | ◐ | `_retrieve_paths` 里的**关键字全文路径**由 `self.use_fulltext` 控制（`searcher.py:429`），来源是 `"fulltext": FULLTEXT_CALL`（`api/config.py:1245`），不是 `bm25`；`bm25` 控制的是 `EnhancedBM25` 检索器是否注入 `GraphMemoryRetriever`（`tree.py:59-61` / `simple_tree.py:52-56`）。两者都默认 false，结论不变 | 机制归因不准 |
| C60 | §3 | "真正调 LLM 的是写入侧，不是检索侧" | ✓ | 见 C57 与 C20 | |
| C61 | §3 | "`searcher.py:357` 起的 `_retrieve_paths` 用线程池同时发起最多 7 条独立检索路径" | ◐ | `def _retrieve_paths` 在 **:355**；7 条路径确认（:384/399/415 无条件三条 + :429/445/462/479 四条条件路径）；线程池是 `max_workers=5`（:383） | 行号漂移；"最多 7 条"属实 |
| C62 | §3 | 路径清单：Working / LongTerm+User / Internet / 关键字 / Tool / Skill / Preference | ✓ | `searcher.py:505,733,856,635,894,989,1043` | |
| C63 | §3 | "`GraphMemoryRetriever` 做图检索+向量检索混合召回，`recall.py:85` 起的 docstring 自述" | ◐ | 引文一字不差但在 `recall.py:94-98`（`def retrieve` 在 :81）；:85 是形参行 | 行号漂移 |
| C64 | §3 | `search_tool_memory`/`include_skill_memory`/`include_preference` 都是 `APISearchRequest` 自己的默认 True | ✓ | `product_models.py:448-449,463-464,439-440` | |
| C65 | §3 | "Internet（wrapper 传 `internet_search=False` 时会跳过）" | ◐ | wrapper **根本没传**该字段；`APISearchRequest.internet_search` 默认 False（`product_models.py:492-493`），经 `search_service.py:84` 转成 `manual_close_internet=True`。效果一致，描述不准 | |
| C66 | §3 | "各路径结果**合并** → `_maybe_rerank`" | ◐ | 顺序相反：rerank 在**每条路径内部**先做（如 `searcher.py:817` 是 Path B 的收尾），随后才在 `_retrieve_paths:496-498` 合并 | 控制流描述错 |
| C67 | §3 | "`_maybe_rerank`（`searcher.py:87-97`）用 `reranker.rerank(...)`" | ◐ | `def` 在 :80，`self.reranker.rerank(...)` 在 :91 | 行号漂移 |
| C68 | §3 | "`TreeTextMemory` 没显式配置 reranker 时的默认值是 `backend:"cosine_local"`（`tree.py:66`）" | ✗ | 产品路径构造的是 `SimpleTreeTextMemory`，其 `__init__` **不调用** `TreeTextMemory.__init__`，直接 `self.reranker = reranker`（`memories/textual/simple_tree.py:28-58`）；reranker 由 `component_init.py:207` 从 `APIConfig.get_reranker_config()` 造，**代码默认是 `http_bge`**（`api/config.py:562-575`），只有当 `MOS_RERANKER_BACKEND` 非 http_bge* 时才落到 cosine_local（`api/config.py:576-583`）。实机 `.env:13` 设了 `cosine_local`，**结论碰巧成立、机制完全不对**；`tree.py:63-73` 在产品路径上是死代码 | **结构性错误**（可复现性影响：换 `.env` 就变 HTTP cross-encoder） |
| C69 | §3/§5 | `level_weights: {"topic":1.0,"concept":1.0,"fact":1.0}`（`tree.py:68`） | ◐ | 生效值来自 `api/config.py:580`；`tree.py:68` 是死代码分支 | |
| C70 | §3 | `_deduplicate_results`（`searcher.py:1149`）按 `item.memory` 文本去重、同文本取高分 | ✓ | `searcher.py:1149-1155` 一字不差 | |
| C71 | §3 | `_sort_and_trim`（`searcher.py:1158`）排序截断 top_k，把最终分数写回 `metadata.relativity` | ✓ | `searcher.py:1158`、:1185 `meta_data["relativity"] = score` | |
| C72 | §3 | 回到 `search_handler.py:254 _apply_relativity_threshold`，丢弃 `relativity < 0.45` | ✓ | `api/handlers/search_handler.py:254-278`；阈值默认 `product_models.py:406-407` | |
| C73 | §3 | `dedup="mmr"` 是 `APISearchRequest.dedup` 默认值，阈值之后再做一次 MMR | ✓ | `product_models.py:416-417`；`search_handler.py:108`（阈值）→ :113-115（MMR） | 顺序属实 |
| C74 | §3 | `formatters_handler.py:44 format_memory_item` 序列化响应 | ✓ | `api/handlers/formatters_handler.py:44` 一字不差 | |
| C75 | §3 | 漏述：`search_handler.py:90-92` 在 dedup 时把 `top_k` 放大 3 倍（注释写 5x）；:119-125 之后还有一次 `rerank_knowledge_mem` | ◐ | `search_handler.py:90-92`（`top_k * 3`，注释 `Expand top_k for deduplication (5x ...)`）；:119-125 → `formatters_handler.py:169-209`（该函数注释 `# rerank set unuse`，实际只按 relativity 排序，本 arm 无 RawFileMemory 故近似空转） | 文档未提；注释与代码自相矛盾（5x vs ×3） |
| C76 | §3/§4 | "MemOS 自己另有 `/product/chat` 端点，检索后再调一次 LLM" | ◐ | 实际路由是 `/product/chat/complete`(`server_router.py:270`) 与 `/product/chat/stream`(:284)，没有裸 `/product/chat`；`ChatRequest` 在 `product_models.py:136`；且实机 `.env:21` `ENABLE_CHAT_API=false`（`component_init.py:178` 因此不构造 chat_llms） | |
| C77 | §3 | "`tree.py:157-179` 与 `searcher.py:191` 的 docstring 都写着 `User query -> TaskGoalParser -> GraphMemoryRetriever -> MemoryReranker -> MemoryReasoner -> Final output`" | ◐ | `searcher.py:212-213` 正是这一串；但 `tree.py:179-180` 的版本**多一段 `MemoryPathResolver`**（`TaskGoalParser -> MemoryPathResolver -> GraphMemoryRetriever -> ...`），文档引用的字符串与 `tree.py` 不符 | |
| C78 | §3 | 否定式："`MemoryReasoner` 只在 `searcher.py:69` 实例化一次，全仓库搜不到第二处 `self.reasoner.` 调用" | ✓ | 全仓库 grep `reasoner`：`tree.py:180`(docstring)、`reasoner.py:11,13`(类定义)、`searcher.py:32`(import)、`:69`(实例化)、`:213`(docstring)——无任何调用点 | 已实际证伪尝试，成立 |
| C79 | §4 | 边界：`server.py` 是 memory-bench 自己的适配层，与 MemOS 只经 HTTP JSON 交换 | ✓ | `servers/memos/server.py:60-65,118-146` | |
| C80 | §5 | "Qdrant 在这套部署里服务于哪个子系统，未验证" | ✗ | 见 C47/C48：它就是这条主链路的向量索引 | |
| C81 | §5 | sync 模式写完仍调 `_schedule_memory_tasks` 提交 `ADD_TASK_LABEL`（`mem_scheduler/schemas/task_schemas.py:33`） | ✓ | `single_cube.py:760-767` → :549-561（else 分支即 sync）；`mem_scheduler/schemas/task_schemas.py:33` `ADD_TASK_LABEL = "add"` | |
| C82 | §5 | `task_schedule_modules/registry.py:52` 路由到 `self.add` | ✓ | `mem_scheduler/task_schedule_modules/registry.py:52` 一字不差 | |
| C83 | §5 | `type_` 硬编码 `"fact"`，从未见写 `topic`/`concept` 类型节点 | ✓ | `simple_struct.py:229`；全仓库无写 topic/concept `type` 的路径 | |
| C84 | §5 | "`manager.py:459 _ensure_structure_path` 全仓库搜索不到任何调用它的地方" | ◐ | 生产代码确无调用，但 `tests/memories/textual/test_tree_manager.py:124,132` 有调用 | 否定式过强 |
| C85 | §5 | 漏述：`CosineLocalReranker` 的 `level_field` 是 `"background"`，而 `background` 存的是 LLM summary 文本 → `level_weights` 实际恒取默认 1.0 | ◐ | `reranker/cosine_local.py:56,88-90`；`background` 写入见 `simple_struct.py:250,423` | 文档第 5 节的疑问（三层结构是否被构建）由此可直接结案：不但没建，权重也形同虚设 |
| C86 | §5 | `single_cube.py:686-687` async 模式强制 `extract_mode="fast"` | ✓ | 一字不差 | |
| C87 | §6.1 | 论文模块名（MemOperator/MemLifecycle/MemGovernance/MemVault/MemStore/MemLoader/MemDumper/MemDecoder/MemBlock）在 `src/memos/**` 无同名**类定义** | ✓ | 全仓库 grep `class (Mem…)`：零命中 | 成立 |
| C88 | §6.1 | "唯一在代码 docstring 里出现过一次的相关名字是 `MemoryPathResolver`（`tree.py:179`）" | ✗ | `src/memos/templates/mos_prompts.py:112`（英）与 `:222`（中）在产品系统提示词里明写 `**MemCube, MemScheduler, MemLifecycle, and MemGovernance**` 及五态 `Generated → Activated → Merged → Archived → Frozen`（:110/:217） | 否定式被证伪 |
| C89 | §6.2 | MemScheduler 语义漂移；任务标签清单（ADD/MEM_READ/MEM_ORGANIZE/MEM_DREAM/MEM_UPDATE/MEM_ARCHIVE/MEM_FEEDBACK） | ◐ | 标签清单一字不差且行号 :31-41 正确，但**路径写错**：文档写 `task_schedule_modules/schemas/task_schemas.py`，真实路径是 `mem_scheduler/schemas/task_schemas.py`（全仓库只有这一个 `task_schemas.py`）。附注：`MEM_ARCHIVE_TASK_LABEL` 定义了但不在 `registry.py:48-58` 的 dispatch map 里 | |
| C90 | §6.3 | `component_init.py:246-248` 写死 `act_mem=None, para_mem=None` | ✓ | `component_init.py:245-249` 一字不差 | |
| C91 | §6.3 | `memories/activation/`、`memories/parametric/` 类存在但未实例化 | ✓ | `memories/activation/{kv.py,vllmkv.py}`、`memories/parametric/lora.py` 存在；产品路径不构造 | |
| C92 | §6.4 | `memories/textual/item.py:178` `memory_type` 的十个取值 | ✓ | `item.py:178-189` 一字不差，恰好十个 | |
| C93 | §6.5 | `item.py:109` `status` 取值 `activated/resolving/archived/deleted` | ✓ | `item.py:109-112` 一字不差 | |
| C94 | §6.5 | "`Generated`/`Merged`/`Expired` 这些状态名在代码里都不存在" | ◐ | `Expired` 作为生命周期状态确实不存在（全仓库仅 `TimeoutExpired` / `Expired API key`）；但 `Generated`/`Merged` 以字符串出现在 `templates/mos_prompts.py:110,112`（且那份五态的第五个是 `Frozen` 而非 `Expired`——这是**第三个**版本的状态机） | 否定式过强 |
| C95 | §6.6 | Figure 6 元数据字段 vs 代码 `TextualMemoryMetadata`/`TreeNodeTextualMemoryMetadata` 字段清单 | ✓ | 论文 txt:904-915；代码 `item.py:101-156`（16 个）+ :178-214（memory_type/sources/embedding/created_at/usage/background/file_ids）——文档列举与代码逐字吻合 | 文档漏列 `internal_info`(:157)、`covered_history`(:164)，不影响结论 |
| C96 | §6.6 | "只有 `source`、`tags`、`usage`、`created_at` 四个字段名对得上" | ◐ | 论文写的是 `created`（txt:906）而非 `created_at`，严格说不同名；`source`/`tags`/`usage` 三项确实同名；`priority`/`expires`/`access`/`embedding_fp`/`storage_mode` 确实无对应实现 | |
| C97 | §6.7 | 检索并行最多 7 路；无 topic-concept-fact 三层查询分解；`MemoryPathResolver` 只在过时 docstring 出现 | ✓ | 见 C62；`ParsedTaskGoal` 字段只有 memories/keys/tags/rephrased_query/internet_search/goal_type/context（`retrieval_mid_structs.py:4-16`），无三层结构 | 结论成立（"只出现过一次"须按 C88 修正为"只在 `tree.py:179`，另有 `mos_prompts.py` 提到其他模块名"） |
| C98 | §6.8 | 论文的单轮闭环 vs 代码拆成 `/product/add` 与 `/product/search` 两个互不感知的端点 | ✓ | `server_router.py:111-118`（search）、:127-134（add）；两端点无共享状态 | |
| C99 | §7 | `server.py` 强制 `async_mode="sync"`，而 `APIADDRequest.async_mode` 默认是 `"async"` | ✓ | `servers/memos/server.py:78`；`product_models.py:642-643` | 适配层 |
| C100 | §7 | "MemOS 开箱默认跑异步 + fast（不调 LLM，直接存窗口原文）" | ✓ | `single_cube.py:686-687`；fast 分支 `simple_struct.py:374-403` 只做 `_make_memory_item`，不调 LLM | |
| C101 | §7 | 服务端默认阈值 0.45；`search_handler.py:105-108` 的截断逻辑 | ✓ | `search_handler.py:105-108` 一字不差；默认值 `product_models.py:406-407` | 附注：`server.py:91` 的行号注释 `product_models.py:166-173` 指向的是 **`ChatRequest.relativity`**，`APISearchRequest.relativity` 在 :406-414 |
| C102 | §7 | "实测（`runs/locomo-r1`）有 78 题因为全部候选低于阈值而返回 0 条证据" | ✓ | 本次直接复算 `runs/locomo-r1/evidence/memos.jsonl`：**1986 题总数，78 题 `envelopes` 为空，621 题不足 top_k=5**——与 `server.py:94` 注释数字完全一致 | 数值独立复现 |
| C103 | §7 | `server.py` 在 `native_notes` 报告 `RETURNED`/`TRUNCATED_BELOW_TOP_K` | ✓ | `servers/memos/server.py:147-153` | 附注：`locomo-r1` 那批 evidence 的 `native_notes` 为空串，说明该报告是那次跑批**之后**加的 |
| C104 | §7 | score 修复：`meta.get("relativity")` 优先、`mem.get("score")` 兜底 | ✓ | `servers/memos/server.py:133-135`；字段定义 `item.py:279-281` | |
| C105 | §7 | "`search_handler.py` 里 `_sort_and_trim` 写回该字段的逻辑" | ✗ | `_sort_and_trim` 在 `.../retrieve/searcher.py:1158`（写回在 :1185），`search_handler.py` 里没有这个函数 | 文件归属错 |
| C106 | §7 | "`server.py` 优先取 `metadata.chat_time`（对话发生时间）…是否每条记忆都有该字段未验证" | ✗ | `chat_time` **不是记忆 metadata 的字段**——它只存在于 `metadata.sources[].chat_time`（`item.py:40`）。写入链路（`simple_struct.py:344-352` / `_make_memory_item` :238-256）从不把它提升到 metadata 顶层，`formatters_handler.py:44-73` 也不加。故 `server.py:143` 的 `meta.get("chat_time")` **恒为 None**，永远回落到 `created_at`（入库墙钟）。另：`server.py:77` 也没往 turns 里塞 `chat_time`，`get_scene_data_info` 会填 `""`（`simple_struct.py:852`） | **该"修复"实际未生效** |
| C107 | §7 | `snapshot`/`restore` 返回 `SNAPSHOT_UNSUPPORTED` | ✓ | `servers/memos/server.py:180-188` | |
| C108 | §7 | `server.py` 把 relativity 当显式参数传下去 | ✓ | `servers/memos/server.py:97-98,119` | |

---

## 3. 步骤清单 — 论文侧

**重要前提**：论文（§5.2 / Figure 8）把"写入新记忆"和"检索旧记忆"画在**同一次交互的同一个闭环**里（txt:1199-1201, 1227-1291），并没有"先灌库后提问"的两阶段。下面为了与代码侧对齐才拆成写/读两栏，`||` 两侧在论文里是**同一个 turn 内并行发生**的。

**系统边界**：论文没有 API 边界。Table 2（txt:697-712）把 Parameter/Activation/Plaintext 三类记忆全部归入 `Core Operation Layer`，Figure 7（txt:1078-1090）把 `Large Language Models` 画在 `MemOS` 框**内**——所以 **`P-GENERATE` 在论文里属于记忆系统本体**，这与 memory-bench 的"记忆系统是外置 REST 服务、答题 LLM 在外面"完全相反。

### 写入侧

| # | name（原文叫法） | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| W1 | Prompt Input and Memory API Packaging（§5.2, txt:1212） | 每 turn（用户交互或自动触发任务） | 自然语言 prompt → 结构化 `MemoryCall`（caller ID / context scope / memory type / access intent / time window） | **论文没写**（§5.3.1 声明 MemReader 做 intent 识别 + prompt rewriting + coreference resolution + slot filling，txt:1344-1345，但没说用不用 LLM） | - | `P-QUERYPARSE` + `P-REWRITE` |
| W2 | Semantic Parse → `MemoryCube (extracted)`（Figure 8, txt:1239-1243） | 每 turn，与检索同一闭环 | prompt → 新记忆内容（例：`The user has a dog.`） | 论文没写 | - | `P-EXTRACT` |
| W3 | MemCube 封装：Memory Payload + 三组 Metadata（§4.2, txt:889-902） | 每条新记忆 | 语义内容 → payload + descriptive identifiers（Timestamp / Origin Signature / Semantic Type）+ governance attributes（ACL / TTL / Priority / 合规标签）+ behavioral usage indicators | no | - | `P-INTAKE` + `P-META` |
| W4 | Contextual Fingerprint（§4.2, txt:1028-1029） | 每条新记忆 | 内容 → "lightweight semantic signature for fast retrieval" | no | - | `~P-EMBED`（论文只说"轻量语义签名"，没说是稠密向量，故标可选） |
| W5 | conflict detection, deduplication, versioning, forgetting policies（§4.1, txt:792-793）+ Version Chain（§4.2, txt:1029-1031） | **论文没写触发时机** | plaintext 记忆集 → 去重/消解冲突/版本链 | 论文没写 | Plaintext Memory | `~P-DEDUP` + `~P-CONFLICT` |
| W6 | hierarchical graph structure organized by task–concept–fact paths（§4.1, txt:789-792）+ knowledge-graph structure / semantic layering（§5.4.1, txt:1404-1407） | 论文没写 | 记忆项 → 图节点+语义边 + private/shared/global 分层 | 论文没写 | 记忆图 | `~P-LINK` + `~P-AGGREGATE` |
| W7 | Lifecycle Modeling and State Transitions（§5.2 txt:1308-1312 / §5.4.3 txt:1465-1479） | 调度之后 + 系统启发式（access patterns / time decay / task labels） | 记忆单元 → 状态迁移 Generated→Activated→Merged→Archived（→Expired 或 Frozen） | no（策略/启发式，阈值论文没给） | MemCube metadata | `P-CONFLICT`（Merged 语义重叠合并）+ `P-EVICT`（Archived→冷存） |
| W8 | Storage Archiving and Access Governance（§5.2 txt:1315-1322 / §5.5.1-§5.5.2） | 策略 / 用户命令 / 调度触发 | 演化后的记忆 → 落 MemVault 命名空间 + ACL/TTL/脱敏/水印/审计日志 | no | MemVault（vector store / relational DB / blob，经 `MemoryAdapter`，txt:1529-1531） | `P-PERSIST` + `P-META` |
| W9 | Cross-Type Conversion and Migration（§5.4.2, txt:1447-1453）/ Cross-Modality Memory Transformation（§4.2, txt:1016-1024） | 跨 session 高频调用 / 模板稳定 / KV 长期低利用（**阈值论文全部没给**） | Plaintext ⇄ Activation(KV) ⇄ Parameter(LoRA/adapter) | Parameter 方向需蒸馏；论文没给流程 | Activation Memory / Parameter Memory | **`P-TRANSMUTE`** `[NEW]`（+ Parameter 方向含 `~P-TRAIN`） |

### 检索侧

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| R1 | 同 W1（同一次 MemReader 解析既产生新记忆也产生检索意图） | 每 turn | prompt → MemoryCall | 论文没写 | - | `P-QUERYPARSE` + `P-REWRITE` |
| R2 | Memory Retrieval and Organization（§5.2, txt:1214-1217） | 每 query | intent/context → 候选记忆集；靠 task-specific 索引（用户偏好/锚点/关键词向量）+ 记忆图（时序链/实体关系/依赖）筛 | 论文没写 | 索引 + 记忆图 | `P-SYMFILTER` + `P-DENSE` + `~P-GRAPHEXPAND` |
| R3 | Hybrid Retrieval and Dynamic Dispatch（§5.4.1, txt:1408-1413） | 每 query | 结构化过滤（tags/时间跨度/布尔/ACL）与语义向量检索可组合成复合查询（"tag filters combined with semantic ranking"） | no | 同上 | `P-FUSE`（符号+语义复合） |
| R4 | Task-Aligned Memory Routing / MemoryPathResolver（§5.4.1, txt:1418-1424） | 每 query | 用户输入 → topic–concept–fact 三层任务模式 → "查什么 / 去哪查 / 按什么顺序查" | 论文没写 | - | `P-QUERYPARSE`（任务分解）+ `P-SELECT`（范围与顺序规划） |
| R5 | Memory Scheduling and Activation（§5.2 txt:1300-1305 / §5.4.2 txt:1433-1445） | 候选集确定后 | 候选集 → 每条记忆的最优注入策略；打分指标 = contextual similarity / access frequency / temporal decay / priority tags | no | - | `P-RERANK` + `P-SELECT` |
| R6 | 按类型分通道注入（§5.4.2, txt:1436-1441；例见 txt:1302-1305） | 每 query | Activation→KV-cache 注入；Parameter→adapter/权重生效；Plaintext→原文插进 prompt | no | - | `P-ASSEMBLE`（Plaintext 通道）+ `~P-KVWINDOW`（Activation 通道）+ **`P-TRANSMUTE`**`[NEW]` 的落地面（Parameter 通道无种子标签可用） |
| R7 | Memory-equipped conversation / Output with memory（Figure 8, txt:1256-1257, 1275） | 每 turn | 注入后的上下文 → 带记忆的回复 | 1 次（backbone） | - | `P-GENERATE` — **注意：论文把它划在系统内部**（Table 2 / Figure 7） |
| R8 | Access Patterns / behavioral usage indicators 回写（§4.2, txt:1011-1014） | 每次访问 | 命中记忆 → frequency/recency 更新，驱动 caching priority | no | MemCube metadata | `P-META` |

**PAPER-SEQ**
`P-QUERYPARSE + P-REWRITE > P-EXTRACT > P-INTAKE + P-META > ~P-EMBED > ~P-DEDUP + ~P-CONFLICT > ~P-LINK + ~P-AGGREGATE > P-CONFLICT + P-EVICT > P-PERSIST > ~P-TRANSMUTE[NEW] || P-QUERYPARSE + P-REWRITE > P-SYMFILTER + P-DENSE + ~P-GRAPHEXPAND > P-FUSE > P-SELECT > P-RERANK > P-ASSEMBLE + ~P-KVWINDOW + ~P-TRANSMUTE[NEW] > P-GENERATE > P-META`

**论文侧明确"没有"的步骤**：没有 BM25/稀疏检索（`P-SPARSE` 仅在 §2 相关工作里作为他人方法提到，txt:480）；没有图扩散打分（`P-DIFFUSE`）；没有多跳/迭代检索或 agent 工具循环（`P-TOOLLOOP`）；没有 datastore/ANN 索引构建（`P-DATASTORE`/`P-ANNINDEX`）；没有 kNN-LM 式输出分布插值（`P-INTERP`）；没有梯度训练主线（`P-TRAIN` 只在"可以蒸馏成 LoRA"这一句里作为可能性出现）。

---

## 4. 步骤清单 — 代码侧

**核对的层**：下表描述的是 **上游 MemOS REST 服务在 memory-bench 实机配置下真正执行的路径**（`MemOS/.env` 生效），W0/R0/R14 两端标注为 memory-bench 适配层（`servers/memos/server.py`）。
与 `code-architecture.md` 的关键差异已在第 2B 节 C15/C47/C68 说明：**reader 是 `MultiModalStructMemReader` 不是 `SimpleStructMemReader`；向量索引在 Qdrant 不在 Neo4j；reranker 由 `MOS_RERANKER_BACKEND` 决定而非 `tree.py` 兜底。**

**系统边界**：`servers/memos/server.py`（W0/R0/R14）与答题 LLM（R15）在 **MemOS 进程之外**，属评测框架；`W1–W8 / R1–R13` 在 MemOS 容器内。MemOS 另有 `/product/chat/*` 会把生成也包进系统内（更接近论文），但实机 `.env:21 ENABLE_CHAT_API=false`，本 arm 未走。

### 写入侧（`POST /product/add`，`async_mode="sync"`，`mode` 未传 → `extract_mode="fine"`）

| # | name（代码里的叫法） | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| W0 | `add_conversation`（`servers/memos/server.py:69-87`） | **每 session 一次**（整段 turns 一次性提交） | `turns[]` → HTTP body（role/content，**不带 chat_time**） | no | - | `P-INTAKE` ← 边界外 |
| W1 | `add_memories`(`server_router.py:128`) → `AddHandler.handle_add_memories`(:134) → `_build_cube_view` → `SingleCubeView.add_memories`(`single_cube.py:59`) → `_process_text_mem`(:662) | 每请求 | request → `UserContext` + `extract_mode`（:686-689） | no | - | `P-INTAKE` |
| W2 | `mem_reader.get_memory(mode="fine")`(`single_cube.py:703-717`) → `simple_struct.py:479` → 多态到 `MultiModalStructMemReader._read_memory`(`multi_modal_struct.py:1272`) → `get_scene_data_info`(**直通**, :1257-1270) | 每请求 | messages → scene 列表（multimodal 版**不切**；simple 版才按 ≤10 条/2 条重叠切，`simple_struct.py:857-866`） | no | - | `P-INTAKE` |
| W3 | `multi_modal_parser.parse(mode="fast", need_emb=False)`（`multi_modal_struct.py:981-992`，30 线程并行） | 每条消息 | 单条消息 → 规范化 raw 记忆项（多模态路由：文本/图片/文档） | 文本分支 no（图片/文档分支会用 `image_parser_llm`/`document_parser_llm`；本 arm 纯文本） | - | `P-INTAKE` |
| W4 | `_concat_multi_modal_memories`（`multi_modal_struct.py:194-196`） | 每 scene | raw 项 → 按 token 滑窗聚合；`max_tokens=chat_window_max_tokens`(1024, `simple_struct.py:207`)、`overlap=200`；超长项先 `_split_large_memory_item`(:115) | no | - | `P-AGGREGATE` |
| W5 | fine 模式 **4 路并行 LLM 抽取**（`multi_modal_struct.py:1020-1049`） | 每 scene（4 路并发） | 窗口文本 → ①`_process_string_fine`(:615) 逐窗口一次 LLM，出 `{"memory list":[{key,memory_type,value,tags}],"summary"}`；②`_process_tool_trajectory_fine`(:900) 出 ToolTrajectoryMemory；③`process_skill_memory_fine` 出 SkillMemory；④`process_preference_fine` 出 PreferenceMemory | **≥4 路 × 每路 ≥1 次**（角色：事实抽取 / 工具轨迹抽取 / 技能抽取 / 偏好抽取） | - | `P-EXTRACT` + `P-META`（tags/key/memory_type 由 LLM 给） |
| W6 | `_make_memory_item`（`simple_struct.py:220-256`） | 每条抽出的记忆 | LLM 的 `value` → `TextualMemoryItem`；`embedding=embedder.embed([value])[0]`(:247)、`sources`=原始消息、`background`=summary、`status="activated"`、`confidence=0.99`、`type="fact"` | no | - | `P-EMBED` + `P-META` |
| W6b | `filter_hallucination_in_memories`（`simple_struct.py:709-734`） | `SIMPLE_STRUCT_ADD_FILTER=true` 时；实机**未开** | 记忆组 → listwise 保留判定 | 1 次/组（不跑） | - | `~P-RERANK` / `~P-DEDUP`（本部署不存在） |
| W7 | `text_mem.add`(`single_cube.py:734`) → `tree.py:114` → `MemoryManager.add`(`manager.py:89`) → `_add_memories_batch`(:138) | 每请求 | 记忆项 → 图节点批（batch_size=5，最多 8 线程）；**WorkingMemory 镜像节点算出来但被注释掉不写**（:239-240） | no | Neo4j（节点属性）+ **Qdrant**（向量，`neo4j_community.py:151→155-165→194`，collection `neo4j_vec_db`，cosine，dim=2048） | `P-PERSIST` + `P-ANNINDEX` |
| W8 | `_cleanup_working_memory`(`manager.py:115-116,250`)（`mode=="sync"` 时） | 每请求 | WorkingMemory 层配额裁剪（`tree.py:83` 20 条） | no | Neo4j | `P-EVICT`（因 W7 从不写 WorkingMemory，实际空转） |
| W9 | `_schedule_memory_tasks`(`single_cube.py:762` → :549-561) | 每请求（sync 分支） | mem_ids → `ADD_TASK_LABEL` 消息入 `mem_scheduler` 队列（`registry.py:52` → `self.add`） | 未追踪 | 队列 | `-`（记账；未继续追副作用） |
| — | `GraphStructureReorganizer`（合并/去重/冲突检测/建边） | **默认关闭**：`is_reorganize=False`（`component_init.py:223` + `api/config.py:1234` + 实机 `.env` 未设 `MOS_ENABLE_REORGANIZE`） | — | — | — | `~P-DEDUP` / `~P-CONFLICT` / `~P-LINK` / `~P-AGGREGATE` **本部署不发生** |

### 检索侧（`POST /product/search`，`mode` 未传 → `SearchMode.FAST`）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| R0 | `retrieve`（`servers/memos/server.py:101-160`） | 每 query | query → body（显式传 `top_k`、`relativity=0.45`） | no | - | `P-INTAKE` ← 边界外 |
| R1 | `search_memories`(`server_router.py:112,118`) → `SearchHandler.handle_search_memories`(`search_handler.py:69`) | 每 query | dedup="mmr" → **`top_k ← top_k×3`**（:90-92，注释却写 5x） | no | - | `-`（候选放大） |
| R2 | `SingleCubeView._search_text`(:190) → `_fast_search`(:385) → `search_text_memories`(`search_service.py:68`) → `TreeTextMemory.search`(`tree.py:157`) → `AdvancedSearcher.search`(`searcher.py:191`) | 每 query | 请求 → Searcher 调用 | no | - | `-` |
| R3 | `_parse_task`(`searcher.py:284`) → `TaskGoalParser.parse(mode="fast")`(:338) → `_parse_fast`(`task_goal_parser.py:55`) | 每 query | query → `ParsedTaskGoal(memories=[query], rephrased_query=query, keys=[], tags=[])` **原样透传**（`use_fast_graph=False`） | **no** | - | `P-QUERYPARSE`（退化为恒等映射） |
| R4 | `self.embedder.embed([query])`（`searcher.py:349-351`） | 每 query | query 文本 → 查询向量 | no | - | `P-EMBED` |
| R5 | `_retrieve_paths`（`searcher.py:355`，`ContextThreadPoolExecutor(max_workers=5)`） | 每 query | 本配置实际提交 **6 条路径**：Working(:505) / LongTerm+User(:733) / Internet(:856，因 `manual_close_internet=True` 空转) / Tool(:894) / Skill(:989) / Preference(:1043)；关键字全文(:635) 因 `use_fulltext=False`(`api/config.py:1245`) **不提交** | no | Neo4j + Qdrant | `P-DENSE` + `P-GRAPHEXPAND` + `P-SYMFILTER`（user_name/status/session_id/id_filter） |
| R5b | `GraphMemoryRetriever.retrieve`（`recall.py:81`，Path B 内部再开 3 线程分别查 LongTerm/User/RawFile） | 每路径 | "graph-based lookup + vector similarity search + merge"（docstring :94-98）；向量实际落 `Neo4jCommunityGraphDB.search_by_embedding`(`neo4j_community.py:293`) → `self.vec_db.search`(:360) = **Qdrant** | no | Qdrant → Neo4j 取字段 | `P-DENSE` + `P-GRAPHEXPAND` |
| R6 | `_maybe_rerank`（`searcher.py:80-96`；**每条路径内部各调一次**，如 Path B 在 :817） | 每路径 | 候选 → `CosineLocalReranker.rerank`（`cosine_local.py:63-100`）：query 向量与候选 `metadata.embedding` 余弦，乘 `level_weights[metadata.background]`（`level_field="background"`，实际恒取默认 1.0） | **no** | - | `P-RERANK` |
| R7 | `_retrieve_paths` 收集各路径结果（`searcher.py:496-498`） | 每 query | 6 路结果 → 简单 concat（**无 RRF / 无加权**） | no | - | `P-FUSE`（退化为拼接） |
| R8 | `post_retrieve`(`searcher.py:157`) → `_deduplicate_results`(:1149) | 每 query | 按 `item.memory` 文本去重，同文本取高分 | no | - | `P-DEDUP` |
| R9 | `_sort_and_trim`（`searcher.py:1158`） | 每 query | 按分数降序、按 memory_type 分桶各自截断（fact/tool/skill/pref 各自 top_k），把分数写回 `metadata.relativity`(:1185) | no | - | `P-SELECT` |
| R10 | `_update_usage_history`（`searcher.py:187,1343`，4 线程后台） | 每 query | 命中记忆 → `usage` 回写图库 | no | Neo4j | `P-META` / `P-PERSIST`（读路径的写副作用） |
| R11 | `_apply_relativity_threshold`（`search_handler.py:254`） | 每 query | 丢弃 `relativity < 0.45` 的结果（**空桶时直接返回 0 条**） | no | - | `P-SELECT`（阈值截断） |
| R12 | `_mmr_dedup_text_memories`（`search_handler.py:113-115,331`） | 每 query（dedup 默认 "mmr"） | 从 ×3 候选里做 MMR 选回 top_k | no | - | `P-FUSE`（MMR）+ `P-DEDUP` |
| R13 | `rerank_knowledge_mem`(`search_handler.py:119-125` → `formatters_handler.py:169-209`) → `format_memory_item`(:44) | 每 query | 本 arm 无 RawFileMemory，函数体注释 `# rerank set unuse`，实际只按 relativity 排序 → 序列化成响应 JSON | no | - | `P-SELECT`（近似空转）+ `P-ASSEMBLE` |
| R14 | `servers/memos/server.py:122-153` | 每 query | 响应 → memory-bench envelope（`memory_id`/`text`/`score=metadata.relativity`/`timestamp`/`raw_format="memos_text"`）+ `RETURNED`/`TRUNCATED_BELOW_TOP_K` 报告 | no | - | `P-ASSEMBLE` ← 边界外 |
| R15 | 答题 LLM（memory-bench backbone） | 每 query | envelope → 答案 | 1 次 | - | `P-GENERATE` ← **MemOS 进程之外** |

**CODE-SEQ**
`P-INTAKE > P-AGGREGATE > P-EXTRACT + P-META > P-EMBED > P-PERSIST + P-ANNINDEX > ~P-EVICT > ~P-DEDUP + ~P-CONFLICT + ~P-LINK(默认关) || P-QUERYPARSE > P-EMBED > P-DENSE + P-GRAPHEXPAND + P-SYMFILTER > P-RERANK > P-FUSE > P-DEDUP > P-SELECT > P-META > P-FUSE(MMR) > P-SELECT > P-ASSEMBLE > P-GENERATE`

**代码侧明确"没有"的步骤**：没有 `P-REWRITE`（FAST 模式查询理解是恒等透传；写入侧的 `rewrite_memories` 存在但只在 memory-version 管线里、`memory_version_switch` 默认 `"off"`）；没有 `P-SPARSE`（BM25/fulltext 双开关默认 false）；没有 `P-DIFFUSE`（无 PPR/RWR/标签传播）；没有 `P-TOOLLOOP`；参数侧一个都没有——`P-DATASTORE`/`P-KNNDIST`/`P-TRAIN`/`P-FROZENFWD`/`P-SIDEPATH`/`P-INJECT`/`P-INTERP`/`P-KVWINDOW` 全部不存在（`act_mem=None, para_mem=None`，`component_init.py:246-248`）；也**没有** `P-TRANSMUTE`（论文的核心主张在代码里无实现）。

---

## 5. 论文↔代码分歧

对照层：论文 = `Li-2025-MemOS…txt`；代码 = 上游 MemOS 服务在 memory-bench 实机配置下的行为（`servers/memos/server.py` 打到的那条链路）。

| # | 分歧点 | 分类 | 论文证据 | 代码证据 |
|---|---|---|---|---|
| D1 | **三态记忆统一调度**：论文的核心主张是 MemCube 统一封装并调度 Plaintext/Activation/Parameter，且支持跨类型迁移与提升 | `[paper-only]` | txt:772-774、916-929、1016-1024、1435-1453 | `component_init.py:245-249` 写死 `act_mem=None, para_mem=None`；`memories/activation/`、`memories/parametric/` 的类存在但产品路径从不实例化 → `P-TRANSMUTE` 在代码中零实现 |
| D2 | **OS 模块命名体系**：MemOperator / MemLifecycle / MemGovernance / MemVault / MemStore / MemLoader / MemDumper / MemDecoder / MemBlock / MemoryPathResolver | `[paper-only]` | txt:697-735、1035-1141、1388-1571 | 全仓库 `class Mem…` 零命中；仅两处**字符串**残留：`memories/textual/tree.py:179`（过时 docstring 的 `MemoryPathResolver`）与 `templates/mos_prompts.py:112,222`（产品系统提示词里的 `MemCube, MemScheduler, MemLifecycle, MemGovernance`）。代码的真实模块划分是 `mem_reader/` `mem_scheduler/` `mem_cube/` `multi_mem_cube/` `graph_dbs/` `search/` `tree_text_memory/{organize,retrieve}/` |
| D3 | **MemScheduler 的职责**：论文说它按任务语义决定用哪种记忆类型并做跨类型迁移 | `[两边都有但行为不同]` | txt:1425-1453 | `mem_scheduler/` 是纯任务队列/异步 worker：标签 `query/answer/add/mem_read/mem_organize/mem_dream/mem_update/mem_archive/api_mix_search/pref_add/mem_feedback`（`mem_scheduler/schemas/task_schemas.py:31-41`），dispatch map 在 `task_schedule_modules/registry.py:47-58`，不涉及任何"记忆类型选择" |
| D4 | **生命周期状态机**：论文 §5.2 五态（…Expired）、§5.4.3 四态、§5.4.3 另提 Frozen | `[两边都有但行为不同]` | txt:1309-1310 / 1466-1467 / 1481-1484 | `item.py:109` 只有 `activated / resolving / archived / deleted`；`Generated`/`Merged` 仅作为**提示词文案**存在于 `templates/mos_prompts.py:110,112`（那份还是第三个版本：…→Archived→**Frozen**）；`Expired` 全仓库无生命周期含义的出现 |
| D5 | **记忆类型分类层级**：论文三分类是系统级 Plaintext/Activation/Parameter | `[code-only]` | txt:772-774 | `item.py:178-189` 的 `memory_type` 十值（Working/LongTerm/User/Outer/ToolSchema/ToolTrajectory/RawFile/Skill/Preference/Context）全部是"Plaintext 内部的子分类"，论文完全没写到这一层 |
| D6 | **MemCube 元数据字段** | `[两边都有但参数不同]` | txt:904-915：`created/last_used/source/model/usage/priority/expires/access/tags/embedding_fp/storage_mode` | `item.py:101-156,178-214`：只有 `source`/`tags`/`usage` 同名（`created` vs `created_at` 近似）；`priority`/`expires`/`access`/`embedding_fp`/`storage_mode`/`model`/`last_used` 无对应实现；代码独有 `is_fast`/`evolve_to`/`working_binding`/`version`/`history`/`background`/`file_ids` |
| D7 | **检索的任务分解**：论文 topic–concept–fact 三层 + MemoryPathResolver 三问 | `[paper-only]` | txt:1418-1424 | `ParsedTaskGoal` 只有 `memories/keys/tags/rephrased_query/internet_search/goal_type/context`（`retrieval_mid_structs.py:4-16`）；FAST 模式下连这些都不填，直接透传（`task_goal_parser.py:73-81`）。写入侧 `type` 硬编码 `"fact"`（`simple_struct.py:229`），从无 topic/concept 节点 |
| D8 | **检索的并行结构**：论文只画"一次检索→一次调度"的线性流程 | `[code-only]` | txt:1214-1217、1300-1307 | `searcher.py:355-501` 最多 7 条并行路径（实机 6 条），每路内部还各自 rerank（:817），之后才合并（:496-498）；`recall.py` Path B 内部再开 3 线程 |
| D9 | **读写是否同一次交互**：论文 Figure 8 是"一句话同时抽新记忆+检索旧记忆+生成回复"的单闭环 | `[两边都有但行为不同]` | txt:1227-1291 | 代码拆成互不感知的 `/product/add`(`server_router.py:127-134`) 与 `/product/search`(:111-118)；memory-bench 按"先灌库后提问"两阶段调用（`server.py:69,101`）。`/product/chat/*`(:270,284) 更接近论文闭环，但实机 `.env:21 ENABLE_CHAT_API=false` |
| D10 | **写入触发粒度**：论文是每 turn | `[两边都有但参数不同]` | txt:1199-1201 | `server.py:69-79` 每 **session** 一次，整段 turns 一起提交；MemOS 内部再按 token 窗口切（1024/overlap 200，`simple_struct.py:207` + `multi_modal_struct.py:194-196`） |
| D11 | **抽取是否调 LLM**：论文全文未定义 | `[code-only]` | 全文无伪代码/算法（grep 确认） | 代码是**多路 LLM 抽取**：fine 模式 4 路并行（事实/工具轨迹/技能/偏好，`multi_modal_struct.py:1020-1049`），每路按窗口/条目再多次调用 |
| D12 | **冲突检测/去重/版本化**：论文列为 Plaintext Memory 的固有能力 | `[paper-only（在本部署里）]` | txt:792-793、1029-1031 | 实现存在（`GraphStructureReorganizer`、`add_before_search`、`merged_from→status=archived`），但：reorganize 默认关（`api/config.py:1234`+实机 `.env` 未设）；`add_before_search`(`single_cube.py:563`) **全仓库无调用点**；`merged_from` 依赖 `add_req.info`，wrapper 不传 → 本 arm 三条全部不发生 |
| D13 | **权限/治理/审计/水印/TTL**（MemGovernance） | `[paper-only]` | txt:1500-1520 | 这条链路上只有 `user_id`+`cube_id` 的命名空间隔离（`server.py:56-57,76`），无 ACL/TTL/水印/审计接口 |
| D14 | **存储后端**：论文 Figure 7 画了 Vector DB + Graph DB 两种，并说 MemVault 经 `MemoryAdapter` 统一 | `[两边都有但行为不同]` | txt:1119,1123；txt:1529-1531 | 代码确实是"图库 + 向量库"双栈，但不是 MemVault 抽象，而是 `Neo4jCommunityGraphDB` 内部硬编码组合：节点进 Neo4j、向量进 Qdrant（`neo4j_community.py:37,151-165,194,360`；`api/config.py:781-795`） |
| D15 | **答题生成的归属**：论文把 LLM Core 画在 MemOS 内（Table 2 / Figure 7），生成属于系统本体 | `[两边都有但行为不同]` | txt:697-712、1078-1090 | 代码里 `/product/search` 只返回记忆文本+分数，生成在 MemOS 进程外（memory-bench backbone）。MemOS 自带的 `/product/chat/*` 才符合论文，但本 arm 关闭 |
| D16 | **重排机制**：论文说按 contextual similarity / access frequency / temporal decay / priority tags 四个指标算注入策略 | `[两边都有但参数不同]` | txt:1301-1307 | 代码只有**单指标**：查询向量与记忆向量的余弦（`cosine_local.py:86`），乘一个恒为 1.0 的 level 权重（:88-90）；访问频率、时间衰减、优先级标签都不参与打分（`usage` 只被回写不被使用，`searcher.py:1343`） |

---

## 6. 新造的 primitive 标签

### `P-TRANSMUTE` — 跨表示形态迁移 `[NEW]`

**定义**：把**同一份记忆内容**在不同**载体形态**之间双向转换，而不改变其语义内容——典型即 MemOS 论文的 Plaintext ⇄ Activation(KV) ⇄ Parameter(LoRA/adapter)，由使用热度/稳定性/资源约束驱动。

**为什么种子词表不够用**：
- `P-TRAIN`（梯度训练）只覆盖 Plaintext→Parameter 这**一个方向**，且把它降格成"训练"，丢掉了"这是同一条记忆换了个存放位置"的语义；反向的 Parameter→Plaintext（论文 txt:1022-1024 的 offload/backpatch）无标签可用。
- `P-KVWINDOW`（KV 窗口/驱逐）描述的是推理时 KV 的窗口管理，不是"把一段外部文本预先烘成可复用 KV 并当作持久记忆单元"。
- `P-INJECT`（隐状态注入）、`P-SIDEPATH` 都是推理期的状态操作，不含"存储形态的持久转换"。
- `P-AGGREGATE`/`P-EVICT` 是同一形态内的层级升降，不跨表示。

**为什么值得单列**：这是 MemOS 论文区别于所有纯文本记忆系统的**唯一核心主张**（摘要、§4.1、§4.2、§5.4.2 反复出现），也正是代码里完全缺失的那一块——把它标出来，跨系统骨架里"论文承诺 vs 代码兑现"的缺口才不会被 `P-TRAIN` 之类的近似标签掩盖掉。

**用法**：论文侧 W9/R6 标 `~P-TRANSMUTE`（可选/条件触发，阈值论文未给）；代码侧无。

---

## 7. 复核统计

| 文档 | ✓ | ✗ | ◐ | ? | 小计 |
|---|---|---|---|---|---|
| `paper-architecture.md` | 31 | 0 | 9 | 0 | 40 |
| `code-architecture.md`（C1–C98，上游 MemOS 层） | 65 | 8 | 25 | 0 | 98 |
| `code-architecture.md` §7（C99–C108，memory-bench 适配层） | 8 | 2 | 0 | 0 | 10 |
| **合计** | **104** | **10** | **34** | **0** | **148** |

**✗ 条目索引**：C2（写入只调一次 LLM）、C15（reader 认成 SimpleStruct）、C20（"唯一一次必经 LLM 调用"）、C47（向量存 Neo4j / 走原生向量索引）、C48（Qdrant 未验证）、C68（reranker 默认来自 `tree.py:66`）、C80（Qdrant 服务于谁未验证）、C88（"唯一出现过一次的模块名"）、C105（`_sort_and_trim` 在 `search_handler.py`）、C106（`metadata.chat_time` 生效）。

**◐ 中值得单独修的**：C7/C10/C25/C28/C53/C55/C61/C63/C67（行号漂移，其中 C10 漂 66 行、C55 指向了另一条语句）；C89（`task_schemas.py` 路径写成不存在的 `task_schedule_modules/schemas/`）；C66（rerank 与合并的先后顺序写反）；P14/P18/P35（论文章节锚点串位）；P17（§5.2 段数）。

**建议补进文档的三处遗漏**（都不是错误，是缺口）：
1. `search_handler.py:90-92` 的 `top_k × 3` 候选放大（注释还写着 5x），以及 :119-125 的第二次 `rerank_knowledge_mem`。
2. `CosineLocalReranker` 的 `level_field="background"` 导致 `level_weights` 恒取 1.0（`cosine_local.py:56,88-90`）——这直接回答了文档第 5 节"topic/concept/fact 三层是否被构建"的疑问：不但没建，配置本身也是死的。
3. 论文 §5.3.1 明写 MemReader 支持 prompt rewriting / coreference resolution / dialogue memory slot filling（txt:1344-1345），`paper-architecture.md` 未提；这三项恰好是代码 FAST 检索路径里**完全没有**的东西，属于可直接进分歧表的素材。

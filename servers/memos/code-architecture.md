# MemOS 代码架构

> 调研范围：`memory-bench` 通过 `servers/memos/server.py` 实际调用的路径——`/product/add`（`async_mode="sync"`）与
> `/product/search`（`mode` 未传，走默认 `FAST`）。MemOS 是一个体量很大的仓库（`product` API 下还有 chat、feedback、
> suggestion、多 cube 组合等大量本次评测没碰到的功能），本文档**只保证覆盖 memory-bench 实际打到的这条链路**，不是整个
> MemOS 代码库的地图。
>
> 下文文件路径均相对于 MemOS 仓库根目录 `/Users/guanhongli/Documents/repo/MemOS/`。
> 术语第一次出现时给一句话解释；不确定的地方标「未验证」，不用推测填。

## 1. 一句话机制

写入时用一次 LLM 调用把整段对话窗口"翻译"成几条独立的事实陈述，连同其向量一起存成 Neo4j（一种图数据库，把数据存成
"节点+关系"而不是表）里的图节点；检索时默认不调 LLM，而是对图里的向量做近邻检索、再用余弦相似度重排、按阈值过滤，
把命中的事实原文连同分数一起原样返回给调用方——论文强调的"三种记忆统一调度、五态生命周期"在这条路径上都没有对应实现
（细节见第 6 节）。

## 2. 记忆是怎么存进去的

**触发**：`server.py` 的 `add_conversation` 每个 session 调一次 `POST /product/add`，显式传 `async_mode="sync"`（即等
MemOS 处理完再返回，不走后台队列）。

**入口链路**（证据）：
- `src/memos/api/routers/server_router.py:127-130` `add_memories` → `add_handler.py` `AddHandler.handle_add_memories`
- → `add_handler.py` 构造 `SingleCubeView`（因为 memory-bench 每次只传一个 `writable_cube_ids`）→
  `src/memos/multi_mem_cube/single_cube.py:56-84` `add_memories` → `src/memos/multi_mem_cube/single_cube.py:596` 附近 `_process_text_mem`
- 抽取模式判定：`src/memos/multi_mem_cube/single_cube.py:64` `sync_mode = add_req.async_mode or self._get_sync_mode()`（wrapper 传的是
  `"sync"`）；`src/memos/multi_mem_cube/single_cube.py:687-689`：sync 模式下 `extract_mode = "fast" if add_req.mode == "fast" else "fine"`——
  wrapper **没有**传 `mode` 字段（`APIADDRequest.mode` 默认 `None`），所以实际走的是 `"fine"`（细粒度抽取）分支，
  不是名字听起来更快的 `"fast"`。

**存的是什么、调不调 LLM**（`src/memos/mem_reader/simple_struct.py`，被 `SimpleStructMemReader` 实现）：
1. `_iter_chat_windows`（`src/memos/mem_reader/simple_struct.py:315`）：把整段 `messages` 按 token 数切窗口——默认
   `chat_window_max_tokens=1024`（`src/memos/mem_reader/simple_struct.py:207`），窗口间重叠 `overlap=200` token（`src/memos/mem_reader/simple_struct.py:315`
   签名默认值），每条消息带 `role:` 和 `[chat_time]` 前缀拼成一段纯文本。
2. 每个窗口 → `_get_llm_response`（`src/memos/mem_reader/simple_struct.py:274`）：用 `SIMPLE_STRUCT_MEM_READER_PROMPT`（中/英按语言自动
   切换）拼 prompt，调 `self.llm.generate(messages)`——**这是写入路径上唯一一次必经的 LLM 调用**。要求模型返回 JSON：
   `{"memory list": [{"key":..., "memory_type":..., "value":..., "tags":[...]}, ...], "summary": "..."}`。
   `src/memos/mem_reader/simple_struct.py:295-302` 有一条明确注释：这个 JSON 的 key 必须是带空格的字符串 `"memory list"`，写错会导致
   `/product/add` 返回 200 但图里一条记忆都没存（历史 bug #1355 的教训）。
3. 每条 `memory list` 项 → `_make_memory_item`（`src/memos/mem_reader/simple_struct.py:220`）：
   - `memory` 字段存的是 **LLM 输出的 `value`**，不是原始对话原文；
   - `metadata.embedding = self.embedder.embed([value])[0]`（`src/memos/mem_reader/simple_struct.py:220` 附近）——**向量化的对象是 LLM
     改写后的事实句，不是原文**；
   - `metadata.sources` 存该窗口的原始消息列表（role/content/chat_time），供溯源用——原文没丢，但不参与检索用的向量；
   - `metadata.background` = 该窗口 LLM 输出的 `"summary"`；
   - `metadata.memory_type` 取 `LongTermMemory` 或 `UserMemory`（LLM 自己判断，代码里做了"长期记忆"→`LongTermMemory`、
     "用户记忆"→`UserMemory` 的中文兜底替换，`src/memos/mem_reader/simple_struct.py:405-408`）；
   - `confidence=0.99`、`type_="fact"` 都是硬编码默认值（`src/memos/mem_reader/simple_struct.py:230` 附近的函数签名默认参数，
     `_process_chat_data` 的 fine 分支没有覆盖它们）。
4. 可选的第二次 LLM 调用：环境变量 `SIMPLE_STRUCT_ADD_FILTER=true` 时才会跑 `filter_hallucination_in_memories`
   （逐条问 LLM 要不要保留），**默认是 `false`**，memory-bench 的 docker 部署没有设置这个变量，即默认不跑。

**写库**（`src/memos/memories/textual/tree_text_memory/organize/manager.py`）：
- `src/memos/multi_mem_cube/single_cube.py:734` `naive_mem_cube.text_mem.add(mem_group, ...)` → `tree.py:103-114` `TreeTextMemory.add` 直接
  转发给 `self.memory_manager.add(memories, mode=self.mode)`（`tree.py:114`）
- `src/memos/memories/textual/tree_text_memory/organize/manager.py:138` `_add_memories_batch`（默认走这条批量路径）：每条记忆变成一个 Neo4j 图节点，
  `graph_store.add_nodes_batch(...)` 批量写入，`metadata` 里带着上一步算好的向量。
- **WorkingMemory 镜像节点是死代码**：`src/memos/memories/textual/tree_text_memory/organize/manager.py:169` 确实算出了一份 `memory_type` 强制改写成 `WorkingMemory` 的
  `working_metadata`，但 `src/memos/memories/textual/tree_text_memory/organize/manager.py:239-240` 明确写着注释「`TODO: working id is same with item.id, need to fix,
  currently stop adding WorkingMemories here.`」——这份数据算出来之后**从未被提交写库**。也就是说代码里定义的
  `WorkingMemory`（短期记忆层，配额 20 条，`tree.py:83` `"WorkingMemory": 20`）这一档，在当前批量写入路径下形同虚设。
- **图结构自动整理默认关闭**：`src/memos/memories/textual/tree_text_memory/organize/manager.py:243-244` 只有 `self.is_reorganize == True` 时才会把新节点 ID 塞进队列交给
  `GraphStructureReorganizer` 做异步的合并/去重/冲突检测（这部分对应论文说的记忆"演化"）。而
  `configs/memory.py:175,270` 两处 `reorganize` 字段的默认值都是 `False`；`component_init.py:223`
  从环境变量 `MOS_ENABLE_REORGANIZE` 读取（`src/memos/api/config.py:1234,1314` 里默认字符串是 `"false"`），docker 部署的
  `.env.example` 没有设置这个变量——即 **memory-bench 实际跑的这套部署，写入之后不会有任何 LLM 驱动的图重组织/合并/
  去重**，每条记忆写进去之后就是独立的一个图节点，不会再被"演化"。

**存储后端**：`docker-compose.yml` 起了 Neo4j 5.26.6 和 Qdrant v1.15.3 两个容器（`docker/docker-compose.yml:28-53`），
但产品部署实际构造的是 `SimpleTreeTextMemory`（`component_init.py:229`），其 `graph_db` 用的是 `Neo4jGraphDB`；
向量直接作为节点属性存进 Neo4j，检索走 Neo4j 5.x 自带的原生向量索引（`graph_dbs/neo4j.py:952`
`CALL db.index.vector.queryNodes('memory_vector_index', $top_k, $embedding)`）。Qdrant 客户端
（`vec_dbs/qdrant.py`）只在 `memories/textual/general.py`、`preference.py` 等**另一套**记忆实现里出现——这套部署里
Qdrant 具体服务于哪个子系统，未验证。

## 3. 记忆是怎么被用起来的

**触发**：`server.py` 的 `retrieve` 调 `POST /product/search`，没有传 `mode`，`APISearchRequest.mode` 默认
`SearchMode.FAST`（`product_models.py` 中 `mode: SearchMode = Field(SearchMode.FAST, ...)`）。

**拿什么去找**：`single_cube.py` `_search_text` 按 `search_mode == FAST` 分支进 `_fast_search` →
`search/search_service.py` `search_text_memories` → `text_mem.search(mode="fast", ...)` → `tree.py:157`
`TreeTextMemory.search` 创建 `Searcher`（实际类是 `AdvancedSearcher`，`tree.py` 顶部把它 `import ... as Searcher`
起了别名）并调用其 `search()`（`searcher.py:191`）。

- **查询理解这一步默认不调 LLM**：`searcher.py:338` `self.task_goal_parser.parse(..., mode=mode, ...)` 把
  `mode="fast"` 原样传给 `TaskGoalParser.parse`（`task_goal_parser.py:30-51`）。`mode="fast"` 分支走 `_parse_fast`
  （`task_goal_parser.py:53`起）：只有当 `use_fast_graph=True` 时才会用 jieba 分词；否则（默认）直接
  `return ParsedTaskGoal(memories=[task_description], rephrased_query=task_description, ...)`——原样透传，
  `task_goal_parser.py:73-83`。而 `use_fast_graph` 来自 `search_strategy.get("fast_graph", False)`
  （`searcher.py:78`），部署配置里 `"fast_graph": bool(os.getenv("FAST_GRAPH", "false") == "true")`
  （`src/memos/api/config.py:1242`），docker 部署未设置该变量 → 默认 `False`。**结论：FAST 模式下查询理解不调 LLM，只是原样透传
  query 文本**；同理 `"bm25": bool(os.getenv("BM25_CALL","false")=="true")`（`src/memos/api/config.py:1243`）默认也是
  `False`，即关键词检索（BM25）路径默认不启用。真正调 LLM 的是**写入**侧（第 2 节），不是检索侧——这一点容易和直觉
  反过来。
- **一步到位还是多步迭代**：单步查询，但内部"广度并行"——`searcher.py:357` 起的 `_retrieve_paths` 用线程池同时发起
  最多 7 条独立检索路径：WorkingMemory（Path A）、LongTermMemory+UserMemory（Path B，`GraphMemoryRetriever` 做
  "图检索+向量检索"的混合召回，`src/memos/memories/textual/tree_text_memory/retrieve/recall.py:85` 起的 docstring 自述）、Internet（wrapper 传
  `internet_search=False` 时会跳过）、关键字全文（默认关，见上）、ToolSchemaMemory/ToolTrajectoryMemory
  （`APISearchRequest.search_tool_memory` 默认 `True`）、SkillMemory（`include_skill_memory` 默认 `True`）、
  PreferenceMemory（`include_preference` 默认 `True`）。也就是说 memory-bench 每次调 `retrieve`，哪怕语义上只是想
  查"用户提到过的某件事"，MemOS 默认也会顺带把工具记忆、技能记忆、偏好记忆各查一遍——这些默认值不是 wrapper 设的，
  是 `APISearchRequest` 自己的默认值（`product_models.py`）。
- **找到之后怎么处理**（不经过任何 LLM）：各路径结果合并 → `_maybe_rerank`（`searcher.py:87-97`）用
  `reranker.rerank(...)`——`TreeTextMemory` 没显式配置 reranker 时的默认值是 `backend: "cosine_local"`
  （`tree.py:66`，按 embedding 余弦相似度打分，`level_weights: {"topic":1.0,"concept":1.0,"fact":1.0}`，
  `tree.py:68`）→ `_deduplicate_results`（`searcher.py:1149`，按 `item.memory` 文本去重，同文本取分数更高的）→
  `_sort_and_trim`（`searcher.py:1158`，按分数排序截断 `top_k`，把最终分数写回
  `metadata.relativity`）→ 回到 `search_handler.py:254` `_apply_relativity_threshold`（丢弃
  `relativity < 0.45` 的结果——`0.45` 是 `APISearchRequest.relativity` 的默认值，wrapper 显式把它当参数传了一遍，见
  第 7 节）→ `dedup="mmr"`（`APISearchRequest.dedup` 默认值）再做一次 MMR（最大边际相关性，一种"既要相关又要不重复"
  的去重排序）→ `formatters_handler.py:44` `format_memory_item` 把 `TextualMemoryItem` 序列化成响应 JSON。
- **交给谁**：`/product/search` 直接把命中记忆（`memory` 文本原样 + `metadata`，含 `relativity` 分数、
  `chat_time`）返回给调用方——这里调用方就是 `server.py`，由它自己包成 memory-bench 的 envelope 格式
  （`memory_id`/`text`/`score`/`timestamp`/`raw_format="memos_text"`），塞进 benchmark 的答题上下文。MemOS
  自己另有 `/product/chat` 端点（`product_models.py` `ChatRequest`），会在检索后**再调一次 LLM** 生成最终回答——但
  memory-bench 的 wrapper 完全没有用它，答题的 LLM 是评测框架自己的，在 MemOS 进程之外。

**一个文档字符串与实际代码不一致的地方**：`tree.py:157-179`（`TreeTextMemory.search` 的 docstring）和
`searcher.py:191` 附近的 docstring 都写着检索流水线是
`"User query -> TaskGoalParser -> GraphMemoryRetriever -> MemoryReranker -> MemoryReasoner -> Final output"`，
但 `MemoryReasoner` 只在 `searcher.py:69` `self.reasoner = MemoryReasoner(dispatcher_llm)` 被实例化一次，
全仓库搜索不到第二处 `self.reasoner.` 的调用——这一步在当前代码里是从未被执行的死代码，文档字符串没跟上代码演进。

## 4. 架构图

```mermaid
flowchart TB
    subgraph HARNESS["评测侧 / Agent（MemOS 进程之外）"]
        LLM["答题用的 LLM<br/>memory-bench 的 backbone"]
        WRAP["servers/memos/server.py<br/>MCP 工具封装"]
    end

    WRAP -- "POST /product/add<br/>async_mode=sync" --> ADDH
    WRAP -- "POST /product/search<br/>mode未传=FAST" --> SEARCHH

    subgraph MEMOS["MemOS REST 服务（docker compose 容器内）"]
        ADDH["add_handler<br/>SingleCubeView._process_text_mem"]
        READER["SimpleStructMemReader.get_memory mode=fine<br/>LLM调用①: 对话窗口→memory list JSON"]
        WRITEDB["MemoryManager._add_memories_batch<br/>is_reorganize=False 默认关"]
        ADDH --> READER --> WRITEDB

        SEARCHH["search_handler<br/>SingleCubeView._fast_search"]
        GOALPARSE["TaskGoalParser mode=fast<br/>fast_graph关闭时=原样透传query,不调LLM"]
        PARALLEL["_retrieve_paths 并行最多7路:<br/>WorkingMemory / LongTerm+User(图+向量混合)<br/>/ Tool / Skill / Preference /（Internet关）"]
        RERANK["cosine_local重排 → 去重 →<br/>relativity阈值过滤(0.45) → MMR去重"]
        SEARCHH --> GOALPARSE --> PARALLEL --> RERANK

        GRAPH[("Neo4jGraphDB<br/>图节点 + 原生向量索引<br/>db.index.vector.queryNodes")]
        WRITEDB --> GRAPH
        PARALLEL --> GRAPH
    end

    RERANK -- "memory文本 + relativity分数 + chat_time" --> WRAP
    WRAP -- "envelope" --> LLM

    NOTE["MemOS另有/product/chat端点：<br/>检索后自己再调一次LLM生成答案，<br/>把'检索+生成'包在系统内部。<br/>memory-bench没有用这条路径，<br/>答题LLM始终在MemOS进程之外。"]
    MEMOS -.- NOTE
```

**边界说明**：图中 `HARNESS` 框内是 memory-bench 自己的代码（`server.py` 是本次评测专门写的适配层，不是 MemOS
自带的东西）；`MEMOS` 框内是 MemOS 仓库里的代码，两者只通过 HTTP JSON 交换信息（写：turns 文本；读：query 文本
→ memory 文本+分数）。MemOS 的 `Activation Memory`、`Parameter Memory` 两个类在这套部署里根本没被实例化（见第 6
节第 3 条），所以图里没有画——产品 REST API 实际上只是一套"文本记忆"服务，不是论文描述的三态统一系统。

## 5. 我没搞清楚的

- **Qdrant 在这套 docker-compose 部署里到底服务于哪个子系统**：`graph_dbs/neo4j.py` 的检索路径明确走 Neo4j 原生
  向量索引，没见调用 Qdrant client；Qdrant client 代码只出现在 `memories/textual/general.py`（`GeneralTextMemory`）
  和 `preference.py` 等看起来是另一套未被产品部署实例化的记忆实现里。未验证。
- **`mem_scheduler` 收到 `ADD_TASK_LABEL` 后台任务后具体做什么**：`single_cube.py` 里 sync 模式写完之后仍会调
  `_schedule_memory_tasks` 提交一条 `ADD_TASK_LABEL` 消息（`mem_scheduler/schemas/task_schemas.py:33`），
  `task_schedule_modules/registry.py:52` 把它路由到 `self.add` 处理器，但没有继续往下读该处理器的具体实现，不确定
  这一步除了记账/统计之外是否还有别的副作用。
- **"topic/concept/fact" 三层结构在当前写入路径下是否真的被构建**：reranker 默认权重配置了
  `{"topic":1.0,"concept":1.0,"fact":1.0}`（`tree.py:68`），但 `mem_reader` 写入时 `type_` 硬编码成 `"fact"`
  （见第 2 节），从未见到写 `"topic"`/`"concept"` 类型节点的代码路径。`src/memos/memories/textual/tree_text_memory/organize/manager.py:459`
  `_ensure_structure_path` 这个方法看起来是建"结构路径"节点用的，但全仓库搜索不到任何调用它的地方——不确定这是死
  代码，还是在本文没有追踪到的其他路径（比如某个异步任务）里被调用。
- **`GraphMemoryRetriever.retrieve()`（`recall.py`）内部"图检索"和"向量检索"具体怎么融合/加权**：只读了函数签名和
  docstring（"Run graph-based lookup from dispatch plan... Run vector similarity search... Merge and return
  combined result set"），没有把 500+ 行实现读完，两路结果的合并/加权逻辑未验证。
- **`async_mode="async"`（生产默认值，memory-bench 没用）下的完整链路**：`src/memos/multi_mem_cube/single_cube.py:686-687` 显示 async 模式
  会强制 `extract_mode="fast"`（跳过 LLM 抽取，直接把窗口原文当记忆存），后续处理转给 `mem_scheduler` 异步跑——这条
  路径本文没有继续往下追。

## 6. 与论文的冲突点

1. **最大冲突——论文的"操作系统模块"命名体系在代码里基本不存在**：论文 §5.1–§5.5、Table 2、Figure 7/8 反复出现的
   `MemOperator`、`MemLifecycle`、`MemGovernance`、`MemVault`、`MemStore`、`MemLoader`、`MemDumper`、`MemDecoder`、
   `MemBlock` 这些模块名，在当前代码库（`src/memos/**/*.py`）里**全文搜索不到任何一个同名的类定义**。唯一在代码
   docstring 里出现过一次的相关名字是 `MemoryPathResolver`（`tree.py:179`），但也只是文档字符串里的一句话，代码里
   从未实现、从未调用（见第 3 节）。代码实际用的是完全不同的一套模块划分：`mem_reader/`、`mem_scheduler/`、
   `mem_cube/`、`graph_dbs/`、`tree_text_memory/{organize,retrieve}/`。
2. **`MemScheduler` 语义漂移**：论文 §5.4.2 说 MemScheduler 是"根据任务语义动态决定用 Plaintext/Activation/
   Parameter 哪种记忆类型、并做跨类型迁移"的中枢调度器。代码里 `mem_scheduler/` 实际是一个任务队列/异步 worker
   系统——`task_schedule_modules/schemas/task_schemas.py:31-41` 定义的任务标签是 `ADD_TASK_LABEL`、
   `MEM_READ_TASK_LABEL`、`MEM_ORGANIZE_TASK_LABEL`、`MEM_DREAM_TASK_LABEL`、`MEM_UPDATE_TASK_LABEL`、
   `MEM_ARCHIVE_TASK_LABEL`、`MEM_FEEDBACK_TASK_LABEL` 等，职责是把 add/search 之后的收尾工作丢进后台队列异步处理，
   不涉及论文说的"三种记忆类型间调度"逻辑。
3. **三种记忆并没有真的"统一"——本次评测打到的 MemOS 100% 只是文本记忆子系统**：论文反复强调 MemCube 统一调度
   Plaintext/Activation/Parameter 三类记忆（摘要、§4.1、Figure 6、§5.4.2）。但产品 REST API 构造 `NaiveMemCube`
   时明确写死 `act_mem=None, para_mem=None`（`api/handlers/component_init.py:246-248`）——`Activation Memory` 和
   `Parameter Memory` 对应的类在代码里存在（`memories/activation/`、`memories/parametric/`），但在这条部署路径上
   从未被实例化。论文说的"高频 plaintext 提炼成 activation/parameter""跨类型迁移"，在这套产品部署里没有发生的
   可能性（因为另外两种记忆压根不存在）。
4. **`memory_type` 分类体系和论文的三分类不在一个层级**：论文的三类是系统级的 Plaintext/Activation/Parameter；
   代码里 `TreeNodeTextualMemoryMetadata.memory_type`（`memories/textual/item.py:178`）的取值是
   `WorkingMemory`/`LongTermMemory`/`UserMemory`/`OuterMemory`/`ToolSchemaMemory`/`ToolTrajectoryMemory`/
   `RawFileMemory`/`SkillMemory`/`PreferenceMemory`/`Context`——这十个值全部只是论文所谓"Plaintext Memory"内部的
   子分类，论文完全没写到这一层细分。
5. **生命周期状态对不上**：论文自己前后就不一致（§5.2 说 5 态 Generated/Activated/Merged/Archived/Expired，§5.4.3
   说 4 态、少了 Expired，详见 `paper-architecture.md` 第 6 节）。代码里 `TextualMemoryMetadata.status`
   （`memories/textual/item.py:109`）的取值是 `activated`/`resolving`/`archived`/`deleted`——和论文两个版本的状态
   命名都不一致，`Generated`/`Merged`/`Expired` 这些状态名在代码里都不存在。
6. **`MemCube` 元数据字段对不上**：论文 Figure 6 给的示例 JSON 字段是
   `created`/`last_used`/`source`/`model`/`usage`/`priority`/`expires`/`access`/`tags`/`embedding_fp`/
   `storage_mode`。代码实际的 `TreeNodeTextualMemoryMetadata`/`TextualMemoryMetadata`
   （`memories/textual/item.py:94,175`）字段是
   `user_id`/`session_id`/`status`/`is_fast`/`evolve_to`/`version`/`history`/`working_binding`/`type`/`key`/
   `confidence`/`source`/`tags`/`visibility`/`updated_at`/`info` +（tree 子类）`memory_type`/`sources`/
   `embedding`/`created_at`/`usage`/`background`/`file_ids`——只有 `source`、`tags`、`usage`、`created_at` 四个
   字段名对得上，`priority`/`expires`/`access`/`embedding_fp`/`storage_mode` 在代码里都找不到对应实现。
7. **检索路径论文没写到的复杂度**：论文说检索是"topic-concept-fact 三层任务分解 + `MemoryPathResolver`"
   （§5.4.1）。代码里检索时其实是并行发起最多 7 条独立路径（WorkingMemory/LongTerm+User/Internet/关键字/
   Tool/Skill/Preference，见第 3 节），根本没有"topic-concept-fact 三层查询分解"的实现，`MemoryPathResolver`
   这个名字也只在一句过时的 docstring 里出现过。
8. **单轮闭环 vs 拆分成两个独立接口**：论文 Figure 8 画的是"用户一句话进来 → 同时完成抽取新记忆＋检索旧记忆＋
   生成回复"的单一闭环（例子里 "My dog needs help!" 一句话同时触发语义解析出新记忆、也触发检索出旧记忆）。代码把
   这拆成两个独立、互不感知的 REST 端点（`/product/add` 写、`/product/search` 读），memory-bench 的 wrapper 正是
   按"先写后读两阶段"分别调用的——论文图里那种"读写同时发生在一次交互里"的画法，和这条实际路径不符（MemOS 另有
   `/product/chat` 端点更接近论文画的闭环，但评测没有走它，见第 4 节）。

## 7.（附）server.py 封装对照

`server.py` 本身是 memory-bench 为这次评测写的适配层，不是 MemOS 自带代码，但它对 MemOS 原始行为做了几处不能忽略
的改写/兜底，直接影响"我们测到的到底是不是 MemOS 的默认行为"：

- **强制同步 + 细粒度抽取**：`server.py` 显式传 `async_mode: "sync"`，而 `APIADDRequest.async_mode` 的默认值其实是
  `"async"`（`product_models.py`）。这意味着 memory-bench 测的是"fine"抽取路径（每个窗口一次 LLM 调用），而 MemOS
  开箱默认（不传这个字段）跑的是异步 + fast（不调 LLM，直接存窗口原文）——两者的记忆质量和延迟特征都不同。
- **`relativity` 从"隐式生效"改成"显式传参+可观测"**：`server.py` 注释里写明，MemOS 服务端默认阈值 0.45
  （对应 `product_models.py` 里 `APISearchRequest.relativity` 的默认值，`search_handler.py:105-108` 的截断逻辑），
  实测中（`runs/locomo-r1`）有 78 题因为全部候选都低于阈值而返回 0 条证据。`server.py` 的做法是把这个阈值当作
  显式参数传下去（而不是依赖服务端隐式默认），并在 `native_notes` 里报告 `RETURNED`/`TRUNCATED_BELOW_TOP_K` 等
  截断信息，让"检索到 0 条"这件事在评测结果里可见，而不是静默发生。
- **`score` 字段读取修复**：`server.py` 注释指出 MemOS 把相关性分数写在 `metadata.relativity`
  （对应 `memories/textual/item.py` 的 `SearchedTreeNodeTextualMemoryMetadata.relativity` 字段，及
  `search_handler.py` 里 `_sort_and_trim` 写回该字段的逻辑），顶层没有 `score` 字段；旧版 wrapper 代码读
  `mem["score"]` 会恒为 `None`。现在的实现是 `meta.get("relativity")` 优先、`mem.get("score")` 兜底。
- **时间戳字段选择**：`server.py` 优先取 `metadata.chat_time`（对话发生时间）而不是 `created_at`（入库墙钟时间），
  注释里提到旧代码恒传 `None` 会让时序类题目拿不到时间锚点。`chat_time` 对应 `mem_reader` 写入时保存在
  `sources` 里的原始消息时间戳（第 2 节），是否每条记忆都一定有这个字段未在本次调研中逐条验证。
- **快照/恢复不支持**：`server.py` 的 `snapshot`/`restore` 直接返回 `SNAPSHOT_UNSUPPORTED`，原因是 Neo4j+Qdrant
  双存储卷没有做卷级快照，重灌数据库是当前的兜底方案。

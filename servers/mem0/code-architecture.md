# Mem0 代码架构

> 读的是 `/Users/guanhongli/Documents/repo/mem0`（官方仓库，Git HEAD `dae67f74`，2026-09-04；`pyproject.toml` 声明版本
> `mem0ai==2.0.20`）。核心逻辑集中在 `mem0/memory/main.py`（整个文件 3868 行；`Memory` 类从
> `mem0/memory/main.py:487` 起、本身约 1685 行，`AsyncMemory` 从 `mem0/memory/main.py:2172` 起）、
> `mem0/configs/prompts.py`（提示词模板）、`mem0/utils/scoring.py`（检索打分）。
> 术语先解释一遍：**embedding（向量化）**＝把一段文字变成一串数字（向量），语义相近的文字向量也相近；
> **BM25**＝一种经典的关键词匹配算法（不看语义，看字面词重叠）；**spaCy**＝一个开源 NLP（自然语言处理）库，
> 这里用来从文本里挑"实体"（人名、地名等专有名词）。
> **2026-09-05 勘误**：本文已按同目录 `verification.md` 的逐条复核结论修正（共 20 处：10 处事实、3 处行号/锚点、7 处表述限定）。原始未修正版本见 git 历史。

## 1. 一句话机制

mem0 现在（2026-04 起的 "v3 pipeline"）的写入逻辑是"每次调用只用 1 次 LLM，把新消息批量抽成一条条独立的
事实性短句，只增不改、不删"（这说的是默认的 `infer=True` 路径，`mem0/memory/main.py:770`；另有一条
`infer=False` 旁支，`mem0/memory/main.py:880-914`，**0 次 LLM**、逐条消息原样入库）；检索逻辑是"语义向量
相似度 + 关键词匹配（BM25）+ 实体关联加分三条通道并列打分，加权合并出 top-k"（"并列"是指三路各自出分再
融合，代码里其实是顺序执行的，不是并发，详见第 3 节）。论文里那套"LLM 自己判断 ADD/UPDATE/DELETE/NOOP
四种操作"的更新机制，在当前代码里是**定义了但在 `mem0/` 生产代码里零调用点的死代码**（仓库里还在调用
它的只剩单元测试 `tests/configs/test_prompts.py:11,18,24,32,43`）；论文里的图记忆 Mem0g，在当前代码里
是**整个模块都不存在**（不是弱化，是连 Neo4j/图存储的代码文件都被删掉了）。这两点是本篇最大的发现，
详见第 6 节。

## 2. 记忆是怎么存进去的

**触发时机**：调用方调 `Memory.add(messages, user_id=..., ...)`（`mem0/memory/main.py:760`）。这里的
`messages` 可以是任意长度的消息列表——不是论文说的"每来一对新消息就触发一次"，触发粒度完全由调用方决定。
本项目的封装层 `servers/mem0/server.py:509` 的 `add_conversation` 工具把一整个 session 的所有 turns
拼成一个 list，**一次性**传给 `add()`——也就是每个 session 只触发一次写入调用，一次写入只对应一次 LLM 抽取。

**存的是什么**：记忆库里存的不是摘要、也不是"向量"本身，而是 LLM 从这批新消息里"抽取"出来的一条条
自包含事实短句（例如"User 养了一只叫 Max 的狗"），外加这条短句的 embedding（用于以后检索）。记忆记录的
payload 只有 `data` / `text_lemmatized` / `hash` / `created_at` / `updated_at` / `attributed_to`
这六个字段（`mem0/memory/main.py:1029-1037`）——**里面没有 `linked_memory_ids`**：提示词确实要求 LLM
吐出 `linked_memory_ids`（`mem0/configs/prompts.py:936`），但同步（`mem0/memory/main.py:1015-1039`）和
异步（`mem0/memory/main.py:2673-2697`）两条路径都只读 `text` 和 `attributed_to` 两个键，LLM 吐的那份
**被直接丢弃**。真正落盘的 `linked_memory_ids` 挂在 **entity_store 的实体行**上
（`mem0/memory/main.py:1157-1159, 1175`），由 spaCy 的实体共现自动生成，跟 LLM 的输出无关（见下表 Phase 7）。

**原始对话是留着的**：`add()` 的最后一步（Phase 8）把这批 messages 逐条写进 SQLite 的 `messages` 表
（`mem0/memory/main.py:1193` 同步 / `mem0/memory/main.py:2851` 异步，都是 `self.db.save_messages(...)`；
表结构见 `mem0/memory/storage.py:134-141`：`id / session_scope / role / content / name / created_at`），
下一次 `add()` 的 Phase 0 再把最近 10 条读回来喂给抽取 prompt（`mem0/memory/main.py:920`）。这是代码里
唯一和论文"最近 m 条消息"对得上的机制。

**调不调 LLM**：调，且整批 messages 只调 **1 次**（`mem0/memory/main.py:940` 那行注释直接写
`# Phase 2: LLM extraction (single call)`）。完整写入流程分 9 个阶段（Phase 0-8，均在
`_add_to_vector_store`，`mem0/memory/main.py:879`；异步同构版在 `mem0/memory/main.py:2533` 起）：

| Phase | 做什么 | 证据 |
|---|---|---|
| 0 上下文收集 | 取该 scope 最近 10 条历史消息（`db.get_last_messages(session_scope, limit=10)`），只用来帮 LLM 消解代词/指代，**不是**论文的"会话摘要 S" | `mem0/memory/main.py:918-920` |
| 1 现有记忆检索 | 把新消息整体做一次 embedding，去向量库里捞 `top_k=10` 条已有记忆，作为"去重/关联参考"喂给 LLM（这不是给用户看的检索结果，是内部去重用的） | `mem0/memory/main.py:923-931` |
| 2 LLM 抽取（唯一一次 LLM 调用） | system prompt 默认用 `ADDITIVE_EXTRACTION_PROMPT`（`is_agent_scoped` 为真时还会再追加 `AGENT_CONTEXT_SUFFIX`，所以不是无条件"固定"）；它的**第二句**就是 "Your sole operation is ADD"（你唯一的操作是新增；第一句是 "You are a Memory Extractor — a precise, evidence-bound processor…"）；LLM 返回 JSON 事实列表，每条可带 `linked_memory_ids`，但这个字段在下游被丢弃、从不落盘 | `mem0/memory/main.py:940-953`（追加 suffix 在 `mem0/memory/main.py:941-944`，定义在 `mem0/configs/prompts.py:947`）；`mem0/configs/prompts.py:468,472` |
| 3 批量向量化 | 把抽取出来的事实文本一次性批量 embedding | `mem0/memory/main.py:991` |
| 4-5 CPU 处理 + 去重 | 用 `hashlib.md5(text)` 算哈希，跟已有记忆哈希、本批内哈希比对，重复的直接跳过——跳过就是"什么都不做"，不会触发任何"更新"动作 | `mem0/memory/main.py:1005-1043` |
| 6 批量落盘 | 写入向量库 + SQLite 的 `history` 表（这张表只记审计日志，**不参与检索**）；history 记录的 `event` 字段被硬编码为字符串 `"ADD"` | `mem0/memory/main.py:1045-1075`（`event="ADD"` 在 `mem0/memory/main.py:1070`） |
| 7 实体链接 | 用 spaCy 从每条新事实里抠"实体"（专有名词/引号内容/名词短语），跟已有实体库做语义匹配（阈值 0.95）决定合并还是新建，写进一个独立的 entity 向量库 collection（`entity_store` 是懒加载属性，`mem0/memory/main.py:559-580`）；**真正落盘的 `linked_memory_ids` 就写在这些实体行上**（`mem0/memory/main.py:1157-1159, 1175`），由实体共现自动生成 | `mem0/memory/main.py:1086` 起；`mem0/utils/entity_extraction.py` |
| 8 存原始对话 + 返回 | 把这批 messages 逐条写进 SQLite 的 `messages` 表（下一次 `add()` 的 Phase 0 会读回来），然后返回结果——**原始对话在这里被完整持久化** | `mem0/memory/main.py:1192-1193`（异步 `mem0/memory/main.py:2850-2851`）；表结构 `mem0/memory/storage.py:134-141` |

**一个容易漏看的细节**：论文 §2.1 描述的"异步会话摘要刷新模块"（给抽取阶段提供 conversation summary S）
在当前代码里连"接口占位但空转"都算不上——`generate_additive_extraction_prompt()` 函数确实支持
`summary=` 参数，提示词模板里也确实有 "## Summary" 这一段（`mem0/configs/prompts.py:496`，函数默认值定义在
`mem0/configs/prompts.py:1016-1024`）；但两个真实调用点（`mem0/memory/main.py:948-953` 同步 / `mem0/memory/main.py:2610-2615` 异步）
**都没有传这个参数**，也没传 `recently_extracted_memories=`（对应 "## Recently Extracted Memories" 段，
`mem0/configs/prompts.py:501`，本该是"session 内近 20 条已抽取记忆的去重参考"）。这两个字段在每一次真实调用里都是默认值
`None`——是提示词模板留了坑位，调用方从来没填过。

**两条旁支（都不是默认路径）**：其一是 `infer=False`（`mem0/memory/main.py:880-914`）——0 次 LLM，
逐条消息原样 embed 入库；其二是 `memory_type="procedural_memory"` 且 `agent_id` 非空时
（`mem0/memory/main.py:853`）走的 `_create_procedural_memory`（`mem0/memory/main.py:1993`，异步
`mem0/memory/main.py:3671`）：它额外调 1 次 LLM（`mem0/memory/main.py:2014`）把整段对话压成一条
procedural 摘要，单条落库，`event` 同样硬编码 `"ADD"`（`mem0/memory/main.py:2034`）——也是 ADD-only，
不改不删。

**public 的 `.update()` / `.delete()` API**：`Memory` 类上确实有 `update(memory_id, text, ...)`
（`mem0/memory/main.py:1815`）和 `delete(memory_id)`（`mem0/memory/main.py:1869`）方法，但这两个是纯 CRUD（调用方直接给 ID
和新内容，代码直接改/删），**不是论文说的"LLM 判断该不该更新/删除"**，而且 `add()` 的自动抽取流程从不
调用它们——这两个方法只有调用方手动显式调用才会触发。

## 3. 记忆是怎么被用起来的

**触发时机**：调用方调 `Memory.search(query, filters, top_k=20, threshold=0.1, rerank=False, explain=False)`
——这几个数字都是函数签名的默认值（`mem0/memory/main.py:1379-1389`）。

**拿什么去找**（`_search_vector_store`，`mem0/memory/main.py:1628`）：
1. query 原文做一次 embedding（语义检索用）
2. query 经词形还原（lemmatize）后的版本（BM25 关键词检索用）
3. 用 spaCy 从 query 里抽出的实体（实体加成用）

**三条通道并列打分**（"并列"不等于"并发"：代码里是顺序跑 Step3→4→5→6，`mem0/memory/main.py:1640-1664`；
全流程唯一的并发发生在实体通道**内部**的 `ThreadPoolExecutor(max_workers=4)`，`mem0/memory/main.py:1778`）：
- **语义**：`vector_store.search(...)`，为了给后面的分数融合留余地，一次多捞
  `max(top_k*4, 60)` 条候选（`mem0/memory/main.py:1641`）
- **BM25 关键词**：调 `vector_store.keyword_search(...)`（Step 注释在 `mem0/memory/main.py:1646`，调用在
  `mem0/memory/main.py:1647`）。这是个"选配"接口——基类里方法定义在 `mem0/vector_stores/base.py:68`、
  函数体直接 `return None` 在 `mem0/vector_stores/base.py:83`，只有部分后端（Qdrant/Pinecone/pgvector/
  Elasticsearch/MongoDB/Weaviate/Milvus/OpenSearch 等十几种，已用 grep 核实）覆写了这个方法。
  **chroma 没有覆写**（`vector_stores/chroma.py` 只定义了 `search`，没有 `keyword_search`）——只要用
  chroma 当后端，这条通道恒为空
- **实体加成**：从 query 抽到的实体去 entity 向量库里找匹配（阈值 ≥0.5），命中的实体所关联的记忆会加分
  （`mem0/memory/main.py:1661-1663`；`_compute_entity_boosts` 定义在 `mem0/memory/main.py:1733`）。这一步依赖 spaCy——
  `extract_entities()` 在 spaCy 不可用时直接返回空列表（`entity_extraction.py` 顶部 docstring）

**融合方式**：`score_and_rank()`（`mem0/utils/scoring.py`）做**加法**融合，不是取最大值也不是 RRF
（倒数排名融合）——`combined = (语义分 + BM25分 + 实体加成) / 分母`，分母根据"这次查询里哪些通道真的产出了值"
自适应：只有语义 → 1.0；语义+BM25 → 2.0；语义+BM25+实体 → 2.5；语义+实体（无BM25）→ 1.5。
`threshold` 只卡语义分这一关（`score_and_rank` 里 `if semantic_score < threshold: continue`）——语义分
没过线的候选直接被淘汰，BM25/实体分再高也捞不回来。

**一步到位，不是多步迭代**：一次 `search()` 调用直接返回最终 top-k，中间没有"检索→反思→再检索"的
agentic 循环。

**找到之后怎么交给模型**：mem0 自己**不生成答案**——`search()` 只返回结构化列表
（`{id, memory, score, metadata...}`），"怎么拼进 prompt、喂给哪个模型回答问题"完全是调用方的事，
mem0 库本身不管这一步。retrieve 阶段本身不调 LLM，除非 `rerank=True` 且配置了 reranker
（`mem0/memory/main.py:1500`，`if rerank and self.reranker`）；`MemoryConfig.reranker` 默认是 `None`
（`mem0/configs/base.py`），所以默认路径下 `rerank=True` 也是空操作。**embedding 不是"只调一次"**：
结构上最多 **2 次**——query 一次（`mem0/memory/main.py:1638`）、实体文本批量一次
（`mem0/memory/main.py:1761`）；只是本次评测环境没装 spaCy、`query_entities` 恒空
（`mem0/memory/main.py:1663`），才使它退化成恒为 1 次。

**本次实测环境的通道状态**（这是环境事实，不是代码结构本身）：memory-bench 的 mem0 主 venv 里
`import spacy` 报 `ModuleNotFoundError`（已用 `.venv/bin/python -c "import spacy"` 实测验证），且没有
安装 `mem0ai[nlp]` 这个可选依赖组（`DEPLOY.md` 的部署矩阵没提这件事）——所以这次评测里实体通道也是关的。
语义+BM25+实体三通道设计，在"chroma 后端 + 未装 spaCy"这个实际组合下，**结构性退化成只剩语义单通道**，
检索侧等价于裸向量 RAG。

## 4. 架构图

```mermaid
flowchart LR
    subgraph AGENT["调用方 / Agent（论文里叫『系统』，这里是评测循环或任何用 mem0 的应用）"]
        A1["产生对话消息 messages"]
        A2["调用 Memory.add() 触发写入"]
        A3["调用 Memory.search() 触发检索"]
        A4["自己拼 prompt，调 answer LLM 生成最终回答"]
    end

    subgraph MEM0["mem0 OSS 包（Memory 类 = 记忆系统本体，边界就是 add()/search() 这两个方法）"]
        direction TB
        ADD["add()\nPhase0-8：取近10条消息做上下文→\n检索top10老记忆做去重参考→\nLLM单次抽取(ADD-only)→\n批量embed→md5去重→\n写向量库+history审计表→\nspaCy实体链接→\n原始对话逐条落messages表"]
        SEARCH["search()\n语义(over-fetch)+BM25(需后端支持)+实体加成(需spaCy)→\nscore_and_rank加权融合→\n返回结构化top-k列表"]
        VS[("VectorStore\nchroma/qdrant/...\n存事实文本+向量")]
        ES[("EntityStore\n独立collection\n存实体+linked_memory_ids")]
        DB[("SQLite\nhistory表=只记审计日志(不参与检索)\nmessages表=逐条存原始对话\n(下次add()的Phase0读回)")]
    end

    subgraph EXT["外部服务（mem0 自己调用，不属于mem0，也不属于Agent）"]
        LLM_EXT["LLM API\n仅写入阶段调1次\n(抽取)；检索阶段默认不调"]
        EMB["Embedding API\n写入/检索都要调"]
    end

    A1 --> A2 --> ADD
    ADD -.抽取事实.-> LLM_EXT
    ADD -.向量化.-> EMB
    ADD --> VS
    ADD --> DB
    ADD --> ES
    A3 --> SEARCH
    SEARCH -.query向量化.-> EMB
    SEARCH --> VS
    SEARCH --> ES
    SEARCH -->|"{id,memory,score,metadata}结构化列表\n(不是prompt文本，mem0不负责生成答案)"| A4
```

**边界说明**：mem0 系统的边界就是 `Memory` 类暴露的 `add()` / `search()`（以及 `update()`/`delete()`/
`get_all()`）几个方法。Agent 侧负责"什么时候存、存什么内容、检索结果怎么拼进最终回答的 prompt"；
mem0 侧只负责"存进去之后怎么组织、查的时候怎么找、怎么打分排序"。mem0 内部还要反过来调外部的 LLM API
（写入阶段抽取用）和 Embedding API（写入、检索都要用）——这两个是 mem0 借用的外部服务，既不算 Agent
的一部分，也不算 mem0 自己的存储/计算，图里单独画了一层。

## 5. 我没搞清楚的

- entity collection 的具体隔离粒度：`entity_store` 是按 `VectorStoreFactory.create` 出来的独立
  collection（`mem0/memory/main.py:559-580`），但没有逐行确认它在多 `user_id`/`agent_id`/`run_id` 混用场景下是否
  严格隔离，还是可能跨 scope 互相污染实体匹配——**未验证**
- README 里说的 "Mem0's managed platform, which includes proprietary optimizations not available
  in the open-source SDK"——OSS 和付费 SaaS 平台具体差多少、差在哪几个模块，代码里看不出来，只能确认
  "现在这份 OSS 代码里没有"，不能推断"SaaS 平台里有什么"
- `get_bm25_params()`（`utils/scoring.py`）里 sigmoid 参数分段（3/6/9/15 词对应不同 midpoint/steepness）
  为什么这么取值，代码没有注释说明依据，没找到对应的实验记录或 issue 链接——**未验证是否有 A/B 测试支撑**
- 本文档读的是仓库当前 HEAD（`mem0ai==2.0.20`，2026-09-04），而 memory-bench 实际跑分用的 venv 里装的
  是 PyPI 发布的 `mem0ai==2.0.18`——已用运行时检查确认两者都在同一套 "V3 PHASED BATCH PIPELINE"
  架构上（`grep "V3 PHASED BATCH PIPELINE"` 两个版本都命中，`chroma.py` 两个版本都没有 `keyword_search`），
  核心结论一致，但没有逐行 diff 两个版本，不排除个别参数/措辞有小改动

## 6. 与论文的冲突点

### ① 四操作（ADD/UPDATE/DELETE/NOOP）机制：论文的核心卖点，在 `mem0/` 生产代码里是纯死代码

**论文怎么写**（§2.1，p.4，Algorithm 1 / Appendix B，p.21）：抽取出候选事实后，系统检索 top-s
相似记忆，通过 LLM 的 "tool call"（函数调用接口）判定四个操作之一——ADD（新建）/UPDATE（用更丰富信息
替换旧记忆）/DELETE（删除被矛盾的旧记忆）/NOOP（不操作）。这是论文反复强调的设计核心，也是它宣称能维护
"知识库一致性和时序一致性"的机制来源。

**代码怎么实现**：
- `DEFAULT_UPDATE_MEMORY_PROMPT`（`mem0/configs/prompts.py:176`）和 `get_update_memory_messages()`
  （`mem0/configs/prompts.py:406`）确实还定义在文件里，但用 `grep` 搜整个 `mem0/` 包（`*.py`），
  **除了定义处和 `mem0/configs/prompts.py:409` 的自引用，找不到第二个调用点**——也就是说 `mem0/` 生产
  代码里没有任何路径会真正拼出这个"四操作判断"的 prompt 并发给 LLM。（范围限定在 `mem0/` 包：仓库里仍
  在调用并断言它的是单元测试 `tests/configs/test_prompts.py:11,18,24,32,43`。）
- 真正跑的 `add()` → `_add_to_vector_store()`（`mem0/memory/main.py:879`）走的是 `ADDITIVE_EXTRACTION_PROMPT`
  （`mem0/configs/prompts.py:468`），其**第二句**就是 **"Your sole operation is ADD"**
  （`prompts.py:472`；第一句是 "You are a Memory Extractor — a precise, evidence-bound processor…"）
- 自动抽取路径上所有写入历史记录（`history` 表）的 `event` 字段，在 8 处 `event="ADD"` 关键字赋值点
  （`mem0/memory/main.py:909, 1070, 1196, 2034, 2570, 2728, 2854, 3729`，含同步/异步/procedural 各分支）
  再加 4 处以**位置参数**把 `"ADD"` 传给 `add_history` 的（`mem0/memory/main.py:1082, 1985, 2740,
  3662`），合计 12 处，**无一例外硬编码为字符串 `"ADD"`**
- 但**不能说"代码里找不到任何地方会写入 UPDATE/DELETE"**——手动 CRUD 路径就在写：`_update_memory` 在
  `mem0/memory/main.py:2084` 以位置参数把 `"UPDATE"` 传给 `add_history`，`_delete_memory` 在
  `mem0/memory/main.py:2116` 传 `"DELETE"`（并置 `is_deleted=1`），异步同构版在
  `mem0/memory/main.py:3781` / `3815`；入口就是下面说的那两个纯 CRUD 方法（`mem0/memory/main.py:1865`
  / `1882` 调进去）。因为是位置传参，才躲过了 `event="UPDATE"` 这种写法的 grep。全仓真正零写入的只有
  `"NOOP"`。**精确的说法是**：自动抽取路径不会产生任何由 LLM 判定的 UPDATE/DELETE/NOOP，UPDATE/DELETE
  只可能由调用方手动调 `.update()`/`.delete()` 时写出，与论文的"LLM 现场判断"无关

**这不是"退化"，是整条流水线换了架构**：git log 显示 commit `a488e190`（2026-04-14，
"feat(oss): port v3 pipeline with hybrid search, entity extraction, and additive scoring #4805"）
一次性把整个"update 阶段"连根拔掉，改成单次 ADD-only 抽取 + `linked_memory_ids` 软关联（关联不是覆写，
老记忆内容永远不变）。要注意这份软关联是**由 spaCy 实体共现在 entity_store 的实体行上生成的**，不是
提示词里让 LLM 吐的那份——LLM 吐的 `linked_memory_ids` 从不落盘（第 2 节已述）。**以代码为准**：当前
OSS 版本没有任何自动的 UPDATE/DELETE 决策；旧记忆永远不会被自动覆盖或删除，只能靠调用方手动调那两个
纯 CRUD 的 `.update()`/`.delete()` API（第 2 节已述，那条路径确实会往 `history` 写 UPDATE/DELETE），
跟论文的"LLM 现场判断"毫无关系。

### ② Mem0g 图记忆：论文的第二套架构，在代码里整体不存在

**论文怎么写**（§2.2，p.5-7，Figure 3）：记忆存成有向标注图 G=(V,E,L)（节点=实体，边=关系），落地在
Neo4j 上；检索走"双路策略"——entity-centric（先定位 query 里的实体锚点，探索出入边构建子图）+
semantic triplet（把整个 query 编码成向量，跟每条关系三元组的文本编码做匹配）；写入时有 LLM 冲突检测器，
把过时的关系标记 invalid 而不是物理删除，用来支持时序推理。

**代码怎么实现**：
- 在 `mem0/` 整个包里用文件名 glob `*graph*` 搜——**一个文件都没有**；`MemoryConfig`
  （`mem0/configs/base.py:29-57`）里也没有 `graph`/`graph_store` 字段，即**没有任何可运行的图记忆实现**。
  但要更正一句：内容 grep **并不是"没有任何一个匹配"**——陈旧文档 `mem0/AGENTS.md:54` 还留着
  "\| Graph stores \| 4 \| Neo4j, Memgraph, Kuzu, Apache AGE \|"，`mem0/AGENTS.md:103-105` 还整段描述
  "Graph memory … configured through the `graph` section of `MemoryConfig`"；`mem0/exceptions.py:396`
  仍有 `details={"package": "kuzu", "feature": "graph_store"}`；`mem0/vector_stores/neptune_analytics.py`
  通篇是 graph；`mem0/configs/prompts.py:858` 也有 "build a graph of related memories" 的措辞。这些都是
  残留的文档/字符串/别的产品的向量后端，不构成图记忆能力，实质结论不变
- `git log` 显示同一批 commit `a488e190` 里，**Python 侧的图记忆实现被整体删除**，而且体量比 TS 侧大
  得多：`mem0/memory/graph_memory.py`（744 行）、`memgraph_memory.py`（708 行）、`kuzu_memory.py`
  （732 行）、`apache_age_memory.py`（595 行），以及 `mem0/graphs/tools.py`（371 行）、
  `mem0/graphs/configs.py`（136 行）、`mem0/graphs/utils.py`（97 行）、`mem0/graphs/neptune/*`
  （约 1500 行）；同一 commit 里 TypeScript SDK 的
  `mem0-ts/src/oss/src/memory/graph_memory.ts`（675 行）、`graphs/tools.ts`（267 行）、
  `graphs/utils.ts`（116 行）、`graphs/configs.ts`（30 行）也**被整体删除**——也就是说 Python 侧本来是
  有完整图记忆的，不是"从来就没有过"
- 仓库自带文档明确写着这是故意为之：`docs/platform/platform-vs-oss.mdx:70`——
  "**Removed**. OSS previously connected external graph stores (Neo4j, Memgraph, Kuzu, Apache AGE);
  that integration was dropped when the v3 pipeline landed."；
  `docs/open-source/configuration.mdx:97`——"Graph memory is not part of OSS in either language:
  it is a built-in Mem0 Platform feature."

**结论**：Mem0g 不是"能力弱化"，是整个模块被从开源仓库里移出，现在是纯付费 Platform 功能。当前 OSS 代码
里唯一残留的"实体"痕迹，是第 3 节说的 spaCy 实体抽取打分加成（`utils/entity_extraction.py`）——这跟
图数据库、关系边、Neo4j 完全是两件事，不能混为一谈。用这份仓库做"Mem0 vs Mem0g"对比是做不到的，因为
Mem0g 在这份代码里根本不存在。

### ③ 检索机制：代码比论文描述得更复杂，但在本项目实际用的组合下又退化回更简单

**论文怎么写**：严格说，论文对 base Mem0 **查询时**怎么检索根本没有描述（见 `paper-architecture.md`
§3.1——既没给 top-k，也没给算法）；只能从"记忆库用 dense embedding 索引、更新阶段按语义相似度取 top-s"
推断查询时也是语义向量检索。可以确定的是论文里没有 BM25/实体加成的任何描述（Mem0g 那套"双路检索"也是
"语义向量匹配"的两种用法，不是关键词匹配）。

**代码怎么实现**：v3 的检索是显式的三通道加权（语义 + BM25 + 实体，`utils/scoring.py`），比论文描述的
纯语义检索**更复杂**——这个方向是代码比论文"多做了"，不是退化。但对本项目用 chroma 做后端、且评测环境
没装 spaCy 的实际组合（第 3 节已述），三通道结构性退化成只剩语义单通道，效果上跟论文描述的"纯语义
相似度检索"又趋同了——只是趋同的原因是环境限制，不是代码本身只有语义检索。

### ④ 论文的"异步摘要模块"在代码里只剩提示词模板的坑位，从未被填过

**论文怎么写**（§2.1，p.3）：抽取阶段的 prompt 由会话摘要 S（一个独立的异步模块周期性刷新）+ 最近 m 条
消息 + 新消息对拼成，S 提供"全局主题理解"。

**代码怎么实现**：`ADDITIVE_EXTRACTION_PROMPT` 的模板里确实还留着 "## Summary" 段
（`mem0/configs/prompts.py:496`），`generate_additive_extraction_prompt()` 函数签名也确实支持
`summary=` 参数（`mem0/configs/prompts.py:1016`）；但两个真实调用点（`mem0/memory/main.py:948-953` / `mem0/memory/main.py:2610-2615`）
都没有传这个参数——已用 grep 确认整个 `main.py` 里没有第三处会传 `summary=` 给这个函数。这个字段在每一次
真实调用里都是默认值 `None`。异步摘要刷新模块在代码里连"接口占位但空转"都算不上，是提示词模板留了坑位，
调用方从来没填过。

---

## 附：我们封装层的降级面（对照 `servers/mem0/server.py`）

以上 1-6 节说的都是上游 `repo/mem0` 本身的架构。本项目 `servers/mem0/server.py` 这层封装在此基础上
又做了几处**明确的降级/取舍**，和上面的机制对照如下：

- **写入粒度进一步收窄**：`add_conversation`（`servers/mem0/server.py:509`）把一个 session 的**全部** turns 一次性
  拼进 `messages` 列表传给 `_mem().add()`——不管这个 session 有多少轮对话，只触发**一次** `add()` 调用，
  也就是只触发第 2 节说的那"唯一一次 LLM 抽取"一次。这比论文的"每对新消息触发一次"粒度更粗，也比 mem0
  库本身"调用方可以任意分批调 add()"这个灵活度更收窄——是封装层自己选的评测协议（整段 session 灌完再
  评测检索），不是 mem0 库的限制
- **图记忆能力边界**：因为上游 OSS 包里完全没有图记忆代码（第 6 节 ②），封装层没有做任何 graph 相关
  调用——评测里的"mem0"只能是纯 Mem0（无图），跟 Mem0g 完全无关。这是能力边界，不是封装层的选择
- **三通道状态显式探测**：封装层在启动期做 `_probe_channels()`（`server.py` 内），用"是否覆写
  `keyword_search`"+"spaCy 与 `en_core_web_sm` 是否可用"+"entity collection 是否已建库"三个信号，
  把 BM25/实体两条通道的可用性钉死并写进 trace，而不是任其默默退化——这是对第 3 节"三通道结构性退化"
  这件事做了显式暴露
- **检索参数全部显式传参**：`_search_params()`（`server.py:242-253`，调用点 `server.py:600,605`）把
  `top_k`/`threshold`/`rerank`/`explain` 全部显式传给 `search()`，不吃包默认值，并把"这次实际生效的
  参数"写进 `native_notes`/trace，便于事后审查。要注意"拿库默认值当锚点"只对 `threshold=0.1` 和
  `rerank=False` 成立：`explain` 封装层传的是 **True**（库默认 `False`），`top_k` 由评测循环传 **5**
  （库默认 20）
- **手动打点 token 用量**：因为 `mem0/llms/openai.py:83`（`return response.choices[0].message.content`）
  只返回内容、丢弃 `usage` 字段，封装层在 OpenAI client 的 `chat.completions.create` 上打了个
  monkeypatch 来拦截 `response.usage`，绕开 mem0 库本身"不暴露内部 LLM 用量"的限制
- **`reset()` 有一处已知修复**：封装层注释标注"P1 修复（2026-08-19 核查）"——`reset()` 必须以
  `_drop_memory()`（弃实例 + 清 chroma 进程级缓存）收尾，否则残留的 `Memory` 实例会持有指向已删除目录的
  悬挂句柄，后续 `add()` 会静默失败（数据库只读错误，但对外表现为"成功"）——这是封装层自己踩坑后加的
  防御，不是上游 mem0 库文档里提到的已知问题

以上均为封装层针对上游能力边界/默认行为做的**工程封装决策**，不改变上游 `repo/mem0` 本身第 1-6 节
描述的机制。

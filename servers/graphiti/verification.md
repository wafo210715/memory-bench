# graphiti 架构文档复核报告

> 复核日期 2026-09-05；论文源 `Rasmussen-2025-Zep-Temporal-Knowledge-Graph-Architecture-for-Agent-Memory.txt`（661 行，已通读全文）；代码源 `getzep/graphiti` @ `a6e026f`（`git describe` = `mcp-v1.1.0-2-ga6e026f`，`pyproject.toml` version = `0.30.1`）+ 本仓库封装层 `servers/graphiti/server.py`（638 行）/ `trace.py`（249 行）。
> 复核方法：论文侧每条断言回 txt 用 `grep -n` 定位并给出亲眼所见的行号；代码侧每个 `file.py:NNN` 都用 `sed -n` 打开该行前后核对，控制流断言顺调用链读到底。

---

## 1. 总评

两份文档的**证据密度和行号准确率都很高**：抽查的 60 余个 `file.py:NNN` 锚点里，只有 3 处需要修正（且都是"文件对、指向的字段在基类/邻近行"这类轻微偏移），没有一个是文件不存在。论文侧 52 条断言全部能在 txt 里找到出处，4 条需要加限定，**零条不实**——`paper-architecture.md` 可以直接信用。三处实测数据（`.state/.../graphiti-20260829.jsonl` 的 `llm_calls=3`/`embed_calls=8~12`/`body_chars 30-80`、`graphiti-align-shakeout` 的 105 次 retrieve 全 RRF 且 `communities` 全 0、首条 `edge.bfs` `hits_per_call=[0,40]`）我重跑统计后**逐个数字对上**，这部分是本次复核里最扎实的一段。

最严重的问题集中在 `code-architecture.md` 的**"这一步调几次 LLM"和"引擎有没有内置某能力"这两类断言**上，共 4 条不实：

1. **§3.4 断言"论文 §3 定义的 χ 在代码里没有一个统一函数与之对应""不是 Graphiti 引擎内置能力"——不实。** `graphiti_core/search/search_helpers.py:28` 的 `search_results_to_context_string()` 就是完整的 χ，且它渲染出的模板比论文示例还多 `<EPISODES>`/`<COMMUNITIES>` 两个区块。属实的只有更弱的一句"`search_()` 不会自动调它"。讽刺的是本仓库 `server.py:348` 的注释自己就引用了同一文件里的 `format_edge_date_range`。
2. **§2.3 第③步标注"[LLM 调用，按候选实体数量]"、第⑤步标注"[LLM 调用，按新增/更新实体数量]"——两条都不实。** 实体消解是**对全部未解析节点一次批量调用**（`node_operations.py:681-689` → `:552`），且零候选/相似度可判的节点根本不进 LLM；摘要生成是**按 30 个一批**（`MAX_NODES=30`），短摘要节点直接拼 edge fact 不调 LLM。两步都不随实体数线性增长。文档自己引的实测 `llm_calls=3` 恰恰印证了这一点，但结论没被回改。
3. **§2.3 第⑤步列出的三个 prompt 里有两个在这条路径上根本不会被调用。** `extract_summary`（`prompts/extract_nodes.py:467`）全仓库**零调用点**（含 tests）；`extract_entity_summaries_from_episodes`（`:613`）只在 `skip_fact_appending=True` 时用，而该参数全仓库无人传 True。默认路径真正用的是文档从未提及的 `extract_summaries_batch`（`:509`）。

其余 15 条 ◐ 多为"结论对但需要加限定"，最值得改的三条：`search()` 不是"固定用 `EDGE_HYBRID_SEARCH_RRF`"（传了 `center_node_uuid` 就换 node-distance 配方）；§3.3"没有循环"与本文档 §3.2 自述的"自动播种 BFS 会跑第二次"自相矛盾；§6.1 的 `reflect` 命中计数是 3 处不是 2 处（结论不受影响）。另有 2 条 `?`：`.context/memory-bench-r2n3/` 与 `research-vault/` 两个证据目录在本机挂载内不存在，§7.4 的 McNemar 结果与 §7.7 的 LoCoMo 分数表无法核实（文档已自述"引自既有报告、未重新跑分"，属诚实标注）。

---

## 2. 逐条核对表

判定：`✓` 属实 / `✗` 不实 / `◐` 部分属实或需加限定 / `?` 无法核实

### 2.1 `paper-architecture.md`（论文侧，证据 = txt 行号）

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| P1 | 头注 | arXiv:2501.13956v1，2025-01-20 | ✓ | txt:11 | |
| P2 | 头注 | Zep = memory layer service，Graphiti = temporally-aware KG engine（§1） | ✓ | txt:62-64 | |
| P3 | §1 | `G = (N, E, φ)`，φ 为 incidence function，§2 开篇 | ✓ | txt:74-76 | |
| P4 | §2.1 | Episode 三类型 message/text/json；实验只聚焦 message | ✓ | txt:102-104 | |
| P5 | §2.1 | `t_ref` = 消息发送时间；锚定 "next Thursday"/"in two weeks"/"last summer" | ✓ | txt:107-109 | 三个例子逐字对上 |
| P6 | §2.2 表 | `Ge` = "non-lossy data store"；episodic edges 连 episode → 语义实体 | ✓ | txt:78-80 | |
| P7 | §2.2 表 | `Gs` = 实体节点 + 语义边（实体间抽出的关系） | ✓ | txt:81-84 | |
| P8 | §2.2 表 | `Gc` = 强连通实体簇高层摘要；community edges 连社区 → 成员实体 | ✓ | txt:85-88 | |
| P9 | §2.2 | 心理学 [8] / AriGraph [9] / GraphRAG [4] 三处出处，"§2 倒数第二段" | ◐ | txt:90-98 | 内容全对，但该段是 §2 前言的**最后**一段（§2.1 起于 txt:100），不是倒数第二段；另原文 "draws from similar approaches in AriGraph" 说成"直接借鉴"略强 |
| P10 | §2.2 | 双向索引；"these connections are not directly examined in this paper's experiments...future work" | ✓ | txt:120-125 | 引文逐字命中，确在 §2.1 内 |
| P11 | §2.3 | 当前消息 + 最近 n 条消息，n=4，两个完整对话轮次；speaker 自动抽成实体 | ✓ | txt:130-133 | |
| P12 | §2.3 | 采用受 reflexion [12] 启发的自我反思技术减少幻觉、提升覆盖率 | ✓ | txt:133-134 | |
| P13 | §2.3 | 从 episode 抽实体摘要，供后续实体消解与检索 | ✓ | txt:135-136 | |
| P14 | §2.3 | 实体名嵌入 1024 维；cosine 找相似 + **单独**对已有实体名和摘要做全文检索；两路候选 + episode 上下文 → LLM 消解 prompt；判重则生成更新后的 name 和 summary | ✓ | txt:137-141 | 四个子断言逐句对上 |
| P15 | §2.3 | 写库用预先定义好的 Cypher，不用 LLM 生成查询，理由是 schema 一致 + 减少幻觉 | ✓ | txt:142-144 | |
| P16 | §2.3 | "为每个事实抽取其关键谓词" | ◐ | txt:148 | 该句在 txt 里首字母丢失、是残句（`or each fact containing its key predicate.`，同 §2.2.1 的 `ntity extraction`）。文档把残句当完整机制陈述转述，且**没有像对待附录 6.1.1 截断那样标注 PDF 丢字**——同一份文档对两处同类损伤处理不一致 |
| P17 | §2.3 | 同一事实可在不同实体对间被抽取多次，用普通边模拟超边 | ✓ | txt:148-149 | |
| P18 | §2.3 | 边去重的混合检索被**限定在与新边相同实体对之间**的已有边；理由是防误合并 + 降复杂度 | ✓ | txt:150-155 | |
| P19 | §2.3 | §2.2.3 自称"与其他知识图谱引擎相比的关键差异化特征" | ✓ | txt:158-159 | |
| P20 | §2.3 | 4 个时间戳 `t'created`/`t'expired` ∈ T′，`tvalid`/`tinvalid` ∈ T；存在边上 | ✓ | txt:162-165 | |
| P21 | §2.3 | LLM 把新边与语义相关旧边比对找矛盾；时序重叠 → 旧边 `tinvalid` = 新边 `tvalid`；按 T′ 优先采信新信息 | ✓ | txt:166-170 | |
| P22 | §2.3 | 用 label propagation [13] 而非 Leiden [14]，理由是动态扩展更直接、推迟完整刷新 | ✓ | txt:180-183 | |
| P23 | §2.3 | 动态扩展 = label propagation 单次递归步；新节点归入邻居**多数派**社区并更新摘要 | ✓ | txt:184-187 | |
| P24 | §2.3 | 承认动态更新会漂移，"periodic community refreshes remain necessary"；定性为"实用启发式"、降低延迟与 LLM 推理成本 | ✓ | txt:187-190 | |
| P25 | §2.3 | 社区摘要用迭代 map-reduce（沿用 [4]）；但检索与 GraphRAG map-reduce 本质不同；生成含关键术语的社区名，嵌入后供 cosine 检索 | ✓ | txt:191-194 | |
| P26 | §2.3 尾 | 论文没有给出"平均每个 episode 触发几次 LLM 调用"这类量化数字 | ✓ | 全文 grep `llm call\|cost\|inference cost` 仅命中 txt:190/264/372/426/431/444，均为定性 | 否定式断言，已实际证伪 |
| P27 | §3.1 | `f: S → S`，α 进 β 出，β 供下游 LLM agent 生成回答 | ✓ | txt:197-200 | |
| P28 | §3.1 | `f(α) = χ(ρ(φ(α))) = β`（§3 末尾） | ✓ | txt:212-213 | 位于 §3 前言末、示例模板之前 |
| P29 | §3.2 | `φ: S → Esn × Nsn × Ncn`，三元组 = 语义边 / 实体节点 / 社区节点 | ✓ | txt:202-205 | |
| P30 | §3.2 | cosine + BM25 基于 Neo4j 的 Lucene 实现；BFS 在图 RAG 领域少被研究，例外 AriGraph [9]、Distill-SynthKG [19] | ✓ | txt:229-230, 242-244 | |
| P31 | §3.2 | BFS 纳入 n 跳内额外节点/边；`φbfs` 可接受节点作参数；典型用法拿最近 episode 当种子 | ✓ | txt:244-248 | |
| P32 | §3.2 | 搜索字段：`Es`→fact，`Ns`→实体名，`Nc`→社区名；与 LightRAG [17] 独立发展、结合是未来方向 | ✓ | txt:237-241 | |
| P33 | §3.2 | 三方法各管词面 / 语义 / 上下文（图上距离）相似 | ✓ | txt:249-252 | |
| P34 | §3.3 | 单轮复合，不是迭代检索循环；全篇无"根据结果决定要不要再查一轮"的机制 | ✓ | txt:196-264 通读无此描述 | 否定式断言，已通读全节证伪 |
| P35 | §3.4 | 5 种重排：RRF [20] / MMR [21] / episode-mentions（graph-based，Zep 自有）/ node distance / cross-encoder | ✓ | txt:256-264 | RRF/MMR 有引用、后三者无引用，"Zep 自有"的读法成立 |
| P36 | §3.4 | cross-encoder 论文称之为"最精细"、成本最高 | ✓ | txt:262-264 | 原文 "most sophisticated"…"highest computational cost" |
| P37 | §3.4 | χ：每条 `ei∈Es` 返回 fact + `tvalid`/`tinvalid`；每个 `ni∈Ns` 返回 name + summary；每个 `ni∈Nc` 返回 summary | ✓ | txt:208-210 | |
| P38 | §3.4 | 示例 context 模板原文照录，只有 `<FACTS>`/`<ENTITIES>`，**没有 `<COMMUNITIES>`** | ✓ | txt:214-226 | 逐行比对，模板文本一字不差 |
| P39 | §4 图/边界 | 构建 LLM = gpt-4o-mini；Chat Agent LLM = gpt-4o-mini / gpt-4o | ◐ | txt:285-286 | 前两项对；但 txt:287-288 明确 DMR 还用 **gpt-4-turbo-2024-04-09** 作答题模型（Table 1 txt:304 有 Zep+gpt-4-turbo 94.8%），mermaid 与边界说明两处都漏了这个模型 |
| P40 | §4 边界 | cross-encoder 重排用 BAAI 的 BGE-m3（§4.1） | ✓ | txt:284 | 原文 "BGE-m3 models from BAAI for both reranking and embedding" |
| P41 | §5 | 附录 6.1.1 第 6 条 guideline 被截断 | ✓ | txt:469 | `6. DO NOT extract entities mentioned only` 后戛然而止 |
| P42 | §5 | 论文没说 DMR/LME 各用哪种重排、BFS 几跳、是否含 community | ✓ | txt:274-277 只写 "using the techniques described in Section 3" | |
| P43 | §5 | reflexion 具体形式论文没给 prompt/伪代码 | ✓ | txt:133-134 仅一句；附录 6.1.1-6.1.5（txt:453-586）无 reflection prompt | |
| P44 | §5 | 社区"定期完整刷新"的周期/触发条件论文没给 | ✓ | txt:189 仅 "periodic community refreshes remain necessary" | |
| P45 | §6 | §4 实验部分完全没提 community 是否参与 | ✓ | `grep -n -i communit` 在 txt:266-420（§4 全段）**零命中** | 否定式断言，已实际证伪 |
| P46 | §6 | top-k 论文内部矛盾：§4 开头 20 vs §4.2 DMR 段 10 | ✓ | txt:275 "the 20 most relevant edges (facts) and entity nodes" vs txt:323-324 "retrieve the top 10 most relevant nodes and edges" | |
| P47 | §6 | 检索该不该排除已失效事实，论文完全没讨论 | ✓ | §2.2.3（txt:157-172）+ §3（txt:196-264）通读无此讨论 | |
| P48 | §6 | BFS 默认跳数 n 论文没给数字 | ✓ | txt:245 仅符号 n | |
| P49 | §6 | 5 种重排"什么场景用哪种"没给准则、彼此无对比数据 | ✓ | txt:254-264 | |
| P50 | §6 | φ 一符两义（incidence vs Search），论文未做符号区分 | ✓ | txt:75 vs txt:204 | |
| P51 | §6 | 论文完全没有报告"图构建"阶段的成本/延迟 | ✓ | 全文无 ingest 侧数字 | |
| P52 | §6 | "Table 2 只报告了检索阶段的 latency（3.20s/2.58s vs 31.3s/28.9s）" | ◐ | txt:378-382 数字全对 | 但"检索阶段"这个定性需限定：txt:35 叫 "response latency"、txt:409 叫 "response times"，full-context 的 31.3s 显然含 115k token 上的生成；只有 txt:444 才把它称作 "latency benchmarks for our retrieval mechanisms"。**论文自身表述不一**，文档单取一种读法且未说明这处歧义 |

### 2.2 `code-architecture.md` §1-§6（上游 `getzep/graphiti` @ `a6e026f`）

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| C1 | 头注 | HEAD `a6e026f`；`git describe` = `mcp-v1.1.0-2-ga6e026f`；version `0.30.1` | ✓ | `git rev-parse --short HEAD`=a6e026f；`git describe`=mcp-v1.1.0-2-ga6e026f；`pyproject.toml:4` | 三项全对 |
| C2 | 头注 | `prompts/extract_nodes.py:540` 注释承认与 Zep 闭源 Go worker `src/lib/graphsummary/processor.go` 语义镜像 | ✓ | `graphiti_core/prompts/extract_nodes.py:540-541` | 逐字命中 |
| C3 | 头注 | 论文 2025-01-20 → HEAD 2026-09-03，约 19.5 个月 | ✓ | `git log -1` = 2026-09-03 10:34 | |
| C4 | §1 | 后端可选 Neo4j / FalkorDB / Kuzu / Neptune | ✓ | `graphiti_core/driver/{neo4j,falkordb,kuzu,neptune}/` 四个驱动目录 | |
| C5 | §2.1 | `Graphiti.add_episode()`，`graphiti_core/graphiti.py:980` | ✓ | `graphiti.py:980` `async def add_episode(` | |
| C6 | §2.2 表 | `EpisodicNode` 原文一字不丢（`content: str`）+ `source`/`source_description`；`valid_at` 就是调用方传的 `reference_time`，`nodes.py:318-332` | ✓ | `nodes.py:318-332`（`content` 在 :321，`valid_at` 在 :322）；`graphiti.py:1110` `valid_at=reference_time` | |
| C7 | §2.2 表 | `EntityNode`：`name` + `name_embedding` + `summary`，`nodes.py:499-504` | ◐ | `nodes.py:499-504` 只含 `name_embedding`/`summary`/`attributes` | `name` 在基类 `Node`（`nodes.py:95`），不在给出的行区间内 |
| C8 | §2.2 表 | `EntityEdge`：`fact` + `fact_embedding` + 4 时间戳；`edges.py:49-54`（基类 created_at）、`:264-280` | ✓ | `edges.py:54` `created_at`；`:264` name `:265` fact `:266` fact_embedding `:267` episodes `:271` expired_at `:274` valid_at `:277` invalid_at `:280` reference_time | **八个字段行号逐个命中，零偏移** |
| C9 | §2.2 表 | `CommunityNode` = map-reduce 摘要 + 关键词名，**无时间戳字段**，`nodes.py:687-690` | ◐ | `nodes.py:687-690` 确实只有 `name_embedding`/`summary` | 但基类 `Node` 有 `created_at`（`nodes.py:98`），`CommunityNode` 继承它。准确说法应是"无双时间轴（valid/invalid/expired）字段" |
| C10 | §2.2 | 第五个字段 `reference_time`（`edges.py:280`）论文四时间戳模型里没有、代码里确实持久化 | ✓ | `edges.py:280` 定义；`edges.py:355` `save()` 的 `edge_data` 含 `reference_time` | 持久化这一点已顺调用链确认到 Cypher |
| C11 | §2.2 | "检索管线本身默认并不会把 episode 内容返回给调用方" | ◐ | 对本仓库封装成立（`server.py:114` `episode_config=None`） | 但对 `graphiti_core` **不成立**：`search_()` 的默认配方 `COMBINED_HYBRID_SEARCH_CROSS_ENCODER` 含 `episode_config`（`search_config_recipes.py:98-103`），`SearchResults.episodes` 会有内容。这句缺主语限定 |
| C12 | §2.3 ① | 查最近 10 条历史 episode（`RELEVANT_SCHEMA_LIMIT=10`，`search_utils.py:64`），`graphiti.py:1087-1090` | ✓ | `search_utils.py:64` `RELEVANT_SCHEMA_LIMIT = 10`；`graphiti.py:1087-1090` `last_n=RELEVANT_SCHEMA_LIMIT` | 逐行命中 |
| C13 | §2.3 ② | `extract_nodes` 按 source 三选一 prompt（`prompts/extract_nodes.py:83`/`:213`/`:278`），调用点 `graphiti.py:1122`，**固定 1 次 LLM** | ✓ | 三个 prompt 行号全中；`graphiti.py:1122`；`node_operations.py:132` → `_extract_nodes_single`（`:244`，docstring 原文 "Extract entities using a single LLM call"）→ `_call_extraction_llm`（`:255-280`）单次 `generate_response` | |
| C14 | §2.3 ③ | `resolve_extracted_nodes` 调用点 `graphiti.py:1131` | ✓ | `graphiti.py:1131` | |
| C15 | §2.3 ③ | **"[LLM 调用，按候选实体数量]"** / 尾段"③④⑤的调用次数随抽出的实体数/边数**线性增长**" | **✗** | `node_operations.py:627-689`：`:652-653` `if not candidates: continue`（零候选直接跳过）；`:659` `_resolve_with_similarity` 先做**无 LLM** 的确定性消解；`:672-689` 只对剩余 `unresolved_indices` 调**一次** `_resolve_with_llm`，其内部 `:552` 是单次 `generate_response`（batch prompt `dedupe_nodes.nodes`，返回 `NodeResolutions` 列表） | 该步是 **0 或 1 次** LLM 调用，与实体数无关。文档自己引的实测 `llm_calls=3`（抽出多个实体的 episode）正好印证，但结论未回改 |
| C16 | §2.3 ③ | "判重复则合并/改写 name+summary" | ◐ | `prompts/dedupe_nodes.py:25-34` `NodeDuplicate` 只有 `id`/`name`/`duplicate_candidate_id` | **没有 summary 字段**；summary 由后面第⑤步 `_extract_entity_summaries_batch` 单独重生成。论文（txt:141）确实写了 name+summary，代码只做了 name——这是一处未被文档 §6 收录的论文↔代码分歧 |
| C17 | §2.3 ④ | 边去重 + 矛盾检测**合并成一次 LLM 调用**，`duplicate_facts`/`contradicted_facts` 一起返回（`prompts/dedupe_edges.py:27-29`，语义边界 `:57`） | ✓ | `dedupe_edges.py:27`（duplicate_facts 描述）/`:29`（contradicted_facts 描述）/`:57`（"contradicted_facts: idx values from EITHER list"）；`edge_operations.py:726-732` 单次 `generate_response` 返回 `EdgeDuplicate` 双字段 | 三个行号逐字命中 |
| C18 | §2.3 ④ | `resolve_edge_contradictions()`（`edge_operations.py:538`）：旧边 `invalid_at` = 新边 `valid_at`；旧边 `expired_at` = now（`:569-570`） | ✓ | `edge_operations.py:538` 函数定义；`:569` `edge.invalid_at = resolved_edge.valid_at`；`:570` `edge.expired_at = ... utc_now()` | 逐行命中；`:553-562` 的 `continue` 分支也证实了"时序重叠"这个前提条件 |
| C19 | §2.3 ④ | 新边自己也可能一出生就被判无效（`:837-838`，出自 `resolve_extracted_edge`，`:623`） | ✓ | `edge_operations.py:623` 函数定义；`:826-839` `if resolved_edge.expired_at is None:` → `:837` `resolved_edge.invalid_at = candidate.valid_at` `:838` `resolved_edge.expired_at = now` | 逐行命中 |
| C20 | §2.3 ④ | 零候选快速路径：两个候选列表都空时仍抽时间戳、跳过去重/矛盾（`:653` 附近） | ✓ | `edge_operations.py:653-682`，注释原文 "Still extract custom attributes and timestamps even when no dedup needed"，`:680` `_extract_edge_timestamps` 后 `:682` return | 逐行命中。**补充**：`:684-695` 还有一条文档未提的"fact 文本逐字相同即复用旧边"快速路径 |
| C21 | §2.3 ④ | 调用点 `graphiti.py:1138-1145` | ✓ | 实际赋值语句 `:1140-1154`，`await self._extract_and_resolve_edges(` 在 `:1144` | 落在给出区间内 |
| C22 | §2.3 ⑤ | "为节点生成/更新摘要与自定义属性：`extract_attributes`(`:383`)、`extract_summary`(`:467`)、`extract_entity_summaries_from_episodes`(`:613`)" | **✗** | 三个行号本身都对，但**其中两个 prompt 在 `add_episode` 路径上根本不会被调用**：`grep -rn extract_summary` 全仓库（含 tests）在 `prompts/extract_nodes.py` 之外**零命中**，`extract_summary`(`:467`) 是死代码；`extract_entity_summaries_from_episodes`(`:613`) 只在 `use_episode_prompt=True`（即 `skip_fact_appending=True`）时用（`node_operations.py:972-974`），而 `grep -rn skip_fact_appending` 全仓库**无人传 True**。默认路径实际使用的是文档从未提及的 `extract_summaries_batch`（`prompts/extract_nodes.py:509`，`node_operations.py:976-977`）。`extract_attributes`(`:383`) 也只在 entity_type 有字段时才调（`node_operations.py:790-794`，无自定义类型时直接 return，零 LLM） | 读者按此文档去看 prompt，会读到两份系统实际不用的文本 |
| C23 | §2.3 ⑤ | **"[LLM 调用，按新增/更新实体数量]"** | **✗** | `_extract_entity_summaries_batch`（`node_operations.py:836`）：`:879-882` 摘要+edge fact 长度 ≤ `MAX_SUMMARY_CHARS*2`（=2000）时**直接拼接、不调 LLM**；需要 LLM 的节点按 `MAX_NODES=30`（`node_operations.py:63`）切 flight，`:896-913` 每个 flight **1 次**调用（`_process_summary_flight` `:979` 单次 `generate_response`） | 实际次数 = ⌈需摘要节点数/30⌉，常为 0 或 1，不是"按实体数" |
| C24 | §2.3 ⑤ | 调用点 `graphiti.py:1160` | ✓ | `graphiti.py:1160` `hydrated_nodes = await extract_attributes_from_nodes(` | |
| C25 | §2.3 ⑥ | 写库用预写 Cypher，`graphiti.py:1170` `_process_episode_data`；关系类型 `RELATES_TO`/`MENTIONS`/`HAS_MEMBER` | ✓ | `graphiti.py:1170`；`edges.py:335` `EntityEdge.save()` → `get_entity_edge_save_query` → `edge_db_queries.py:69/78` `MERGE (source)-[e:RELATES_TO ...`；`edges.py:202`/`:238` `MATCH (n:Episodic)-[e:MENTIONS]->(m:Entity)`；`community_operations.py:288` `MATCH (c:Community)-[:HAS_MEMBER]->(n:Entity {uuid: $entity_uuid})` | 三条 Cypher 字面量逐字命中 |
| C26 | §2.3 ⑦ | `update_communities` 默认 `False`（签名 `graphiti.py:989`），判断分支 `graphiti.py:1184` | ✓ | `graphiti.py:989` `update_communities: bool = False`；`:1184` `if update_communities:` | 逐行命中 |
| C27 | §2.3 尾 | "②④⑤三步都各自触发（②固定 1 次，③④⑤的调用次数…）" | ◐ | — | 同一句内列举自相矛盾：前半"②④⑤"、后半"③④⑤"。实际调 LLM 的是 ②③④⑤ 四步 |
| C28 | §2.3 尾 | 实测 `llm_calls=3`、`embed_calls=8~12`、`body_chars` 30-80（`.state/graphiti/mcp_trace/graphiti-20260829.jsonl`） | ✓ | 本次重跑统计该文件：6 条 `add_conversation`，`llm_calls` **全部 = 3**，`embed_calls` ∈ {8×4, 12×2}，`body_chars` ∈ [30, 80] | 三个数字全对 |
| C29 | §2.3 尾 | `WEEKEND-PLAN.md:357` 给出经验估算 "2 + (1~2)×边数" | ✓ | `WEEKEND-PLAN.md:357` 逐字命中 | |
| C30 | §2.3 社区 | `build_communities()`（`graphiti.py:1490`）需显式调用；内部先 `remove_communities()` 再 label propagation（`community_operations.py:93`）；Neo4j 走重复实现 `driver/operations/graph_utils.py`；二者均同步双缓冲、`while True` 无迭代上限 | ✓ | `graphiti.py:1490` 定义、`:1504` `await remove_communities(...)`；`community_operations.py:93` 定义、`:102` `while True`、`:104+:131` 双缓冲；`driver/operations/graph_utils.py:27-65`，difflib 逐行比对两份实现**仅注释/类型注解/返回写法不同，控制流完全一致**；`driver/neo4j/operations/graph_ops.py:22,128` 确认 Neo4j 走后者 | 本条含 5 个子断言，全部核实 |
| C31 | §3.1 | `search_()`（`graphiti.py:1603`）默认 `COMBINED_HYBRID_SEARCH_CROSS_ENCODER`（`recipes:81-108`，边 bm25+cosine+bfs 全开、cross-encoder 重排）；`search_filter` 默认空（`graphiti.py:1625`） | ✓ | `graphiti.py:1603/1606/1625`；`search_config_recipes.py:81-108`（edge `:83-88` 三方法 + `:88` cross_encoder） | 逐行命中 |
| C32 | §3.1 | `search()`：**固定用** `EDGE_HYBRID_SEARCH_RRF` 配方 | ◐ | `graphiti.py:1569-1571`：`EDGE_HYBRID_SEARCH_RRF if center_node_uuid is None else EDGE_HYBRID_SEARCH_NODE_DISTANCE` | 不是"固定"，是二选一——传了 `center_node_uuid` 就换成 node-distance 配方。文档结论（只查边、只两路、无 BFS）在两个配方下都成立，但"固定"这个词不实 |
| C33 | §3.1 | docstring 自称 "our basic out-of-the-box search"（`graphiti.py:1542`）；不传 filter 落到空 `SearchFilters()`（`graphiti.py:1580`） | ✓ | `graphiti.py:1542` 逐字命中；`:1580` `search_filter if search_filter is not None else SearchFilters()` | |
| C34 | §3.2 | `search()`（`search/search.py:98`）用 `semaphore_gather` 并行跑四类：`edge_search:253`/`node_search:464`/`episode_search:664`/`community_search:764`；论文 φ 只有 3 分量 | ✓ | `search.py:98` 定义、`:173` `await semaphore_gather(`；四个函数定义行号 253/464/664/764 **全部逐个命中** | |
| C35 | §3.2 | 每路取 2×limit 候选；`sim_min_score` 默认 0.6（`search_utils.py:65`）；BFS 默认 3 跳（`MAX_SEARCH_DEPTH=3`，`search_utils.py:67`） | ✓ | `search.py:286/297/309` 三处 `2 * limit`；`search_utils.py:65` `DEFAULT_MIN_SCORE = 0.6`、`:67` `MAX_SEARCH_DEPTH = 3`；`search_config.py:83/85` 取作默认值 | 常量名是 `DEFAULT_MIN_SCORE`，字段名才是 `sim_min_score`，文档表述可接受 |
| C36 | §3.2 | 无种子时 BFS 先冷跑一次（大概率 0 命中）再用本轮 bm25/cosine 命中的 `source_node_uuid` 二次播种（`search.py:338` "expand_bfs"） | ✓ | `search.py:332` `if EdgeSearchMethod.bfs in ... and bfs_origin_node_uuids is None:`；`:333-335` 种子取 `edge.source_node_uuid`；`:338` span 名 `'search.edge_search.expand_bfs'`；`:344-353` 第二次 `edge_bfs_search` | 行号与语义逐条命中 |
| C37 | §3.2 | 5 种重排各自行为（rrf 纯融合 / mmr 重拉 embedding / episode_mentions 先 RRF 再按 `edge.episodes` 长度 / node_distance 先 RRF 且需中心节点 / cross_encoder 先 RRF 取 2×limit 再打分） | ✓ | `search.py:368-374`（rrf）、`:375-394`（mmr，`:381` `get_embeddings_for_edges`）、`:450-451`（`sort(key=lambda edge: len(edge.episodes))`）、`:412-446`（`:414` 无中心节点抛 `SearchRerankerError`）、`:395-411`（`:398` `[: 2 * limit]`） | 五条子断言全部逐行核实 |
| C38 | §3.2 | "只有 cross_encoder 这一种重排会在检索阶段触发 **LLM** 调用；其余 4 种都是纯算法/图计算" | ◐ | 前半"只有它会外调模型"成立（`search.py:405` 唯一的 `await cross_encoder.rank`） | 但 cross-encoder **未必是 LLM**：`graphiti_core/cross_encoder/bge_reranker_client.py` 是本地 BGE 模型实现，论文 §4.1 用的正是 BGE-m3。"用 LLM 打分"只对 `openai_reranker_client.py`/`gemini_reranker_client.py` 成立 |
| C39 | §3.2/§6.7 | community 无 BFS、只 bm25+cosine（`search_config.py:48`），重排只 rrf/mmr/cross_encoder（`:74`）；episode 只 bm25、只 rrf/cross_encoder（`:69`） | ✓ | `search_config.py:44-46`（EpisodeSearchMethod 只 bm25）、`:48-50`（CommunitySearchMethod 只两个）、`:69-71`（EpisodeReranker 两值）、`:74-77`（CommunityReranker 三值）；`search.py:793-802` community 只起 fulltext+similarity、`:694-700` episode 只起 fulltext | 四个行号全中 |
| C40 | §3.3 | "单轮，不迭代…**没有循环**、没有基于结果内容判断'要不要再搜一轮'的分支重试逻辑" | ◐ | `search.py:332-353` | **与本文档 §3.2 自述矛盾**：自动播种 BFS 就是"依据第一轮命中结果发起的第二次检索"。准确表述应为"没有 LLM 驱动的多跳循环，但有一次固定的、结果依赖的二次 BFS" |
| C41 | §3.4 | **"graphiti_core 本身不做渲染成文本这一步"、"论文 §3 定义的 χ 在代码里没有一个统一函数与之对应"、"不是 Graphiti 引擎内置能力"** | **✗** | `graphiti_core/search/search_helpers.py:28` `def search_results_to_context_string(search_results: SearchResults) -> str`，docstring 原文 "Reformats a set of SearchResults into a single string to pass directly to an LLM as context"；`:29-37` 渲染 fact+valid_at+invalid_at，`:38-40` entity_name+summary，`:47-50` community_name+summary，`:52-71` 拼进 `<FACTS>/<ENTITIES>/<EPISODES>/<COMMUNITIES>` 模板；同文件 `:22` 还有 `format_edge_date_range()` | 这**就是** χ，且是引擎内置。属实的只有更弱的一句"`search_()` 不自动调用它"（全仓库调用点仅 `tests/test_graphiti_int.py:77`）。附带一提：本仓库 `server.py:348` 的注释自己就引用了同文件的 `format_edge_date_range` |
| C42 | §5 | "不确定 `resolve_extracted_nodes` 有没有类似边侧的零候选快速路径" | ◐ | `node_operations.py:652-653` `if not candidates: continue` 即零候选快速路径；`:659` `_resolve_with_similarity` 还多一层无 LLM 的确定性消解 | 这条自述的"不确定"其实可以确定，且答案是**节点侧的省 LLM 优化比边侧更强** |
| C43 | §5 | pip 包 0.29.3 实测死循环、4 分钟约 1200 万轮；当前克隆逻辑一致 | ✓ | `patches/graphiti/community_operations.py:102-104` 逐字命中（"4 分钟烧掉约 1200 万轮"）；当前克隆 `while True` 无上限已由 C30 证实 | |
| C44 | §5/§6.8 | `saga`/`SagaNode`/`HAS_EPISODE`/`NEXT_EPISODE` 存在，论文没提，本仓库封装未用 | ✓ | `graphiti.py:996-997` 两个参数；`nodes.py:867` `class SagaNode(Node)`；`driver/neo4j/operations/has_episode_edge_ops.py:81` `MATCH (n:Saga)-[e:HAS_EPISODE]->(m:Episodic)`；论文 txt 全文无 saga；`server.py` 无 saga | |
| C45 | §6.1 | reflexion 步骤代码里找不到；搜 `reflexion`/`reflect` **"只命中两处"**（`graphiti.py:361`、`edge_db_queries.py:197`） | ◐ | 主结论 ✓：`grep -rn -i reflexion` 全仓库**零命中**；`extract_nodes` 单次调用即 return，无二次复检环节 | **计数错**：`grep -rn -i reflect graphiti_core` 是**三**处——`graphiti.py:361`、`graphiti.py:1415`、`edge_db_queries.py:197`，漏了 `:1415`（同样是 "reflects" 动词的无关用法，不影响结论） |
| C46 | §6.2 | 当前 `extract_message`（`prompts/extract_nodes.py:83`）近 10 类禁抽名单、6 组带正反例示例、去掉 "implicitly" 只留 "explicitly" | ✓ | `:90-112` 共 **11** 条 `NEVER extract` 项；`:169/175/181/187/193/199` 恰好 **6** 个 `<EXAMPLE>` 块，每块都有 Good/Do NOT 两侧；`:114`+`:134` 两处加粗 `**explicitly**`，全文无 implicitly；对照论文附录 txt:461 "explicitly or implicitly" | 三个计数类断言全部实数核对 |
| C47 | §6.3 | 社区子图默认不参与写入循环，建整棵树还需单独调 `build_communities()`（`graphiti.py:1490`） | ✓ | 同 C26 + C30；`build_communities` 在 `graphiti_core` 内无任何自动调用点 | |
| C48 | §6.4 | `SearchFilters` 支持 `expired_at` 过滤（`search_filters.py:65` 字段、`:242-271` Cypher 构造），但 `search()`/`search_()` 默认落空 filter | ✓ | `search_filters.py:65` `expired_at: list[list[DateFilter]] | None`；`:242-271` `if filters.expired_at is not None:` 到 `filter_queries.append(expired_at_filter)`；`graphiti.py:1580`/`:1625` | 行号区间起止都对 |
| C49 | §6.5 | 代码 `DEFAULT_SEARCH_LIMIT = 10`（`search_config.py:29`） | ✓ | `search_config.py:29` | |
| C50 | §6.6 | `EDGE_HYBRID_SEARCH_RRF`（`recipes:111-116`）只配 bm25+cosine、无 BFS、只查边 | ✓ | `search_config_recipes.py:111-116`，只有 `edge_config`，`search_methods=[bm25, cosine_similarity]` | 逐行命中 |

### 2.3 `code-architecture.md` §7（本仓库封装层 `servers/graphiti/server.py`）

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| W1 | §7.1 | 现状已修：改用 `search_()` + 显式 `SearchConfig`（`_build_search_config()`）；`_edge_envelope()` 显式取 `e.valid_at`；缺失时 `timestamp=None` 不回退 `created_at`；缺失率写进 `native_notes`（`VALID_AT_MISSING`） | ✓ | `server.py:471` `cfg = _build_search_config(knobs)`、`:477` `g.search_(...)`；`:73` `_build_search_config`；`:346` `_edge_envelope`、`:356-357` 取 `valid_at`、`:365` `timestamp=valid.isoformat() if valid else None`；`:502` `VALID_AT_MISSING` | 四个子断言逐行命中 |
| W2 | §7.1 | 历史 bug：9930 条 envelope 时间戳年份 100% 落在 2026（`WEEKEND-PLAN.md:386-389`） | ✓ | `WEEKEND-PLAN.md:386-387` 逐字命中（"9930 条 envelope 时间戳年份分布 = {'2026': 9930}，100% 错"） | |
| W3 | §7.2 | 从未构造或传入 `search_filter` | ✓ | `server.py:477` `await g.search_(query, config=cfg, group_ids=group_ids)` 无 `search_filter`；全文件无 `SearchFilters` 字样 | 否定式断言，已实际证伪 |
| W4 | §7.2 | envelope 的 `display_time: "{lo} → {hi}"` | ✓ | `server.py:368` `display_time=f"{lo} → {hi}"`；`:358-359` lo/hi 缺失时为 "date unknown"/"present" | |
| W5 | §7.3 | `MEMBENCH_GRAPHITI_RERANKER` 默认 `"rrf"`（`server.py:65`）；全仓库脚本/配置无覆盖 | ✓ | `server.py:65`；`grep -rl MEMBENCH_GRAPHITI`（排除 .git/runs/.state）只命中 `server.py`、`trace.py`、二者 `__pycache__`、以及 `code-architecture.md` 自身 | |
| W6 | §7.3 | 实测 trace 的 `init` 与逐条 `retrieve` 里 reranker 确凿是 `"reciprocal_rank_fusion"` | ✓ | 本次重跑 `runs/graphiti-align-shakeout/mcp_trace/graphiti.jsonl`：`init.knobs.reranker="rrf"`；**105 条 retrieve 的 `config.edge.reranker` 100% = `reciprocal_rank_fusion`** | |
| W7 | §7.3 | 上游 `OpenAIRerankerClient` 靠 `logit_bias`+`top_logprobs` 取连续分数；封装降级为 True/False→1.0/0.0 + 稳定排序 | ✓ | `cross_encoder/openai_reranker_client.py:91` `logit_bias={'6432': 1, '7983': 1}`、`:92-93` `logprobs=True, top_logprobs=2`、`:116` `zip(passages, scores, strict=True)`；`server.py:146` `_make_reranker`、`:157` `TextClassifierReranker`、`:176` `1.0 if txt.startswith("true") else 0.0`、`:207` 稳定排序 | 两侧行号全中 |
| W8 | §7.4 | `_search_knobs()` 默认 `triple=True`；`add_conversation()` 只调 `add_episode(...)`、从不传 `update_communities=True` | ✓ | `server.py:68` `"triple": os.environ.get("MEMBENCH_GRAPHITI_TRIPLE", "1") == "1"`；`:421-427` `add_episode()` 五个参数里无 `update_communities` | |
| W9 | §7.4 | "**也从不额外调用** `build_communities()`" | ◐ | `add_conversation` 路径确实不调 | 但同一份 `server.py:539-549` 就暴露了一个 `build_communities` MCP 工具（`:549` `nodes, edges = await g.build_communities(group_ids=group_ids)`）。应限定为"ingest 路径不触发，需人工调该工具"——文档后文承认手动跑过消融，与这句字面表述打架 |
| W10 | §7.4 | 105 次 `retrieve` 的 `raw_counts.communities` 无一例外全部为 0 | ✓ | 本次重跑统计：`{0: 105}`，105/105 | 数字精确命中 |
| W11 | §7.4 | community 开/关消融：38 题错转对 / 36 题对转错 / 净 +0.10pp / McNemar p=0.908（源 `research-vault/1-project/...`） | ? | `$HOME/mnt` 下只挂了 `literature`/`memory-bench`/`repo` 三个目录，无 `research-vault` | 证据路径不在本机可见范围，无法核实 |
| W12 | §7.5 | `retrieve()` 调 `search_()` 时不传 `bfs_origin_node_uuids`；实测首条 `retrieve` 的 `edge.bfs` `calls=2`、`hits_per_call=[0, 40]` | ✓ | `server.py:477` 调用无该参数；本次重跑首条 retrieve：`"edge.bfs": {"calls": 2, "hits_total": 40, "hits_per_call": [0, 40]}` | **数字逐个命中**；补充：`node.bfs` 同为 `[0, 40]` |
| W13 | §7.6 | `add_conversation()` 把整个 session 的 turns 拼成一个字符串（`"\n".join(f"{role}: {content}")`）当作**一个** episode | ✓ | `server.py:414` docstring "一个 session 一个 episode"；`:417` `body = "\n".join(f"{t.get('role','user')}: {t.get('content','')}" for t in turns)` | |
| W14 | §7.6 | 于是"最近 10 条历史 episode"实际取到的是最近 10 个历史 session | ✓ | 逻辑推论：`RELEVANT_SCHEMA_LIMIT` 计的单位是 episode（`graphiti.py:1088-1090` `retrieve_episodes(..., last_n=...)`），episode = session | |
| W15 | §7.7 | LoCoMo 四臂分数表（graphiti 44.7±0.3 等）、弃答率 34.6% vs mem0 12.7%、5958 次检索中 3465 次 `VALID_AT_MISSING` | ? | 唯一出处 `.context/memory-bench-r2n3/report-2026-09-04.md` 在本机不存在（memory-bench 根下无 `.context/` 目录） | 无法核实；文档已自述"均引自既有 benchmark 报告，本次调研未重新跑分"，属诚实标注而非编造 |

---

## 3. 步骤清单 — 论文侧

> 按论文描述的**实际执行顺序**。`trigger` 一栏严格照论文原文；论文没写触发时机的标 "论文未定"。

### 3.1 写入侧（§2）

| # | name（论文自己的叫法） | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| 1 | Episode ingestion（"ingestion of raw data units called Episodes"） | 每条 message（论文的 episode = 一条消息，txt:104-106） | message 文本 + speaker + `t_ref` → `EpisodicNode` 进 `Ge` | no | 图（episode 子图，non-lossy） | **P-INTAKE** |
| 2 | Entity extraction（§2.2.1） | 每 episode | 当前消息 + 最近 n=4 条消息 → 实体列表（speaker 必抽） | 1 次（抽取） | - | **P-EXTRACT** |
| 3 | Reflection（"a reflection technique inspired by reflexion[12]"） | 每 episode，紧随抽取 | 初抽实体 → 去幻觉、补覆盖后的实体 | ≥1 次（论文未给次数） | - | **P-SELFCHECK** `[NEW]` |
| 4 | Entity summary extraction（"extracts an entity summary from the episode"） | 每 episode | episode + 实体 → 实体摘要 | 1 次 | - | **P-AGGREGATE** |
| 5 | Entity name embedding | 每实体 | 实体名 → 1024-d 向量 | no（embedding） | - | **P-EMBED** |
| 6 | 候选检索（消解用）：cosine over existing entities + 单独 full-text over names & summaries | 每实体 | 向量/文本 → 候选已有节点 | no | 图（读） | **P-DENSE** + **P-SPARSE**（写入侧内嵌的检索） |
| 7 | Entity resolution（"our entity resolution prompt"） | 每实体（论文行文如此） | 候选 + episode 上下文 → is_duplicate + 更新后的 name & summary | 1 次/实体 | - | **P-DEDUP**（LLM 裁决式，非阈值式） |
| 8 | Fact / edge extraction（§2.2.2，含 key predicate；同一事实可跨实体对重复抽取模拟 hyper-edge） | 每 episode | 消息 + 实体 → 事实边 | 1 次 | - | **P-EXTRACT** |
| 9 | Fact embedding | 每边 | fact → 向量 | no | - | **P-EMBED** |
| 10 | Edge deduplication（混合检索**限定在同实体对**的已有边） | 每新边 | 新边 + 同实体对旧边 → is_duplicate | 1 次/边 | 图（读） | **P-DEDUP** |
| 11 | Temporal extraction（§2.2.3，用 `t_ref` 解绝对/相对时间） | 每边 | fact + `t_ref` → `tvalid`/`tinvalid` | 1 次/边 | - | **P-META**（LLM 时间标注） |
| 12 | Edge invalidation（"employs an LLM to compare new edges against semantically related existing edges"） | 每新边 | 新边 + 语义相关旧边 → 矛盾集；旧边 `tinvalid` ← 新边 `tvalid` | 1 次/边 | 图（写） | **P-CONFLICT** |
| 13 | Graph integration（"predefined Cypher queries"，明确不是 LLM 生成查询） | 每 episode 末 | 实体/边 → Neo4j | no | 图（写） | **P-PERSIST** |
| 14 | Community dynamic extension（"a single recursive step in label propagation"） | 每新实体节点加入图时（论文描述为随数据流入自然发生） | 新节点 + 邻居社区 → 归入多数派社区 + 更新社区摘要 | 摘要更新（次数未给） | 图（写） | **P-AGGREGATE** |
| 15 | Complete community refresh（"periodic community refreshes remain necessary"）+ 社区名生成与嵌入 | 定期（**周期论文未给**） | 全图 → 社区划分 + map-reduce 摘要 + 关键词社区名 + 名字嵌入 | map-reduce 两两合并（按簇大小） | 图（写） | **P-AGGREGATE** + **P-EMBED** |

**论文写入侧明确没有的步骤**：无 `P-REWRITE`（不做指代消解/改写，只做抽取）；无 `P-EVICT`（失效事实"打标签留在图里"，从不删除，txt:166-172）；无 `P-LINK` 的语义 mutual-kNN 式建边（边全部来自 LLM 抽取，不是相似度建边）。

### 3.2 检索侧（§3）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| R1 | ϕcos（cosine semantic similarity search） | 每 query | α → 语义相近的边/实体/社区 | no（需 query embedding） | 图（读，Neo4j 向量） | **P-DENSE** |
| R2 | ϕbm25（Okapi BM25 full-text，Neo4j Lucene） | 每 query | α → 词面相近候选 | no | 图（读，Lucene） | **P-SPARSE** |
| R3 | ϕbfs（breadth-first search，n 跳；可拿最近 episode 当种子） | 每 query | α（+种子节点）→ 图上邻域候选 | no | 图（读） | **P-GRAPHEXPAND** |
| R4 | ρ Reranker（RRF / MMR / episode-mentions / node-distance / cross-encoder，五选一） | 每 query | 三元组候选 → 重排后三元组 | 仅 cross-encoder 分支（论文用 BGE-m3） | - | **P-FUSE**（RRF/MMR）｜ **P-RERANK**（其余三种） |
| R5 | χ Constructor | 每 query | 边→fact+`tvalid`+`tinvalid`；实体→name+summary；社区→summary → context 字符串 β | no | - | **P-ASSEMBLE** |
| R6 | *（边界外）* Chat agent 生成回答 | 每 query | β + 问题 → 答案 | 1 次（gpt-4o-mini / gpt-4o / gpt-4-turbo） | - | **P-GENERATE** |

**论文检索侧明确没有的步骤**：无 `P-QUERYPARSE`（论文从未描述查询理解/意图识别/时间范围解析，α 原样进三路检索）；无 `P-SYMFILTER`（不讨论按 participant/时间/标签过滤，也不讨论排除失效事实）；无 `P-TOOLLOOP`（txt:212-213 是一次函数复合，全篇无多轮）；无 `P-SELECT`（论文没有名额分配/组合优化，只有 top-k 截断）。

### 3.3 系统边界（论文侧）

- **属于记忆系统本体**：三层图 `Ge`/`Gs`/`Gc` + 构建用 LLM（实验用 `gpt-4o-mini-2024-07-18`）+ 嵌入模型（BGE-m3）+ φ/ρ/χ 三段流水线（含 cross-encoder 重排，BGE-m3）。边界由 §3 的 `f: S → S` 定义：**α 字符串进，β 字符串出**。
- **属于 agent 侧（边界外）**：Chat agent LLM（`gpt-4o-mini` / `gpt-4o` / `gpt-4-turbo-2024-04-09`），只消费 β。
- **属于评测脚本侧（边界外）**：DMR 的 LLM judge（txt:324）、LongMemEval 的 GPT-4o judge + question-specific prompts（txt:358-359）。
- 论文自己也承认边界内还有一层没展开：Zep 是生产服务、Graphiti 是引擎，"Zep 服务层由什么组成"论文没写（这一点 `paper-architecture.md` 头注已正确指出）。

---

## 4. 步骤清单 — 代码侧

> 两层分开列：**L1 = 上游 `graphiti_core` @ a6e026f**，**L2 = 本仓库封装 `servers/graphiti/server.py`**。触发时机以实际调用链为准。

### 4.1 写入侧 —— L2 `add_conversation()` → L1 `Graphiti.add_episode()`

| # | name | 层 | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|---|
| 1 | `add_conversation` 拼 body | L2 | 每 session（`server.py:417`） | 整段 turns → 单个字符串 body | no | - | **P-INTAKE** |
| 2 | `EpisodicNode` 构造 + `retrieve_episodes(last_n=10)` | L1 | 每 `add_episode`（`graphiti.py:1087-1112`） | body + `reference_time` → EpisodicNode + 最近 10 条历史 episode | no | Neo4j（读） | **P-INTAKE** |
| 3 | `extract_nodes` | L1 | 每 episode（`graphiti.py:1122`） | body + previous_episodes → 实体列表 | **恰好 1 次**（`node_operations.py:250`） | - | **P-EXTRACT** |
| 4 | `_collect_candidate_nodes` / `_semantic_candidate_search` | L1 | 每 episode（`node_operations.py:637`） | 实体名 embedding → 候选已有节点 | no（embedding） | Neo4j（读） | **P-EMBED** + **P-DENSE** |
| 5 | `_resolve_with_similarity`（确定性消解） | L1 | 每实体（`node_operations.py:659`） | 实体 + 候选 → 命中则直接合并 | **no** | - | **P-DEDUP** |
| 6 | `_resolve_with_llm`（**批量**，仅剩余未解析节点） | L1 | 每 episode 至多一次（`node_operations.py:681`→`:552`） | 全部未解析实体 + 候选 → `NodeResolutions`（只回 name，无 summary） | **0 或 1 次**（非按实体数） | - | **P-DEDUP** |
| 7 | `extract_edges` | L1 | 每 episode（`edge_operations.py:656`） | body + 实体 → 事实边 | 1 次 | - | **P-EXTRACT** |
| 8 | `resolve_extracted_edge` 的 dedupe+contradiction 合并调用 | L1 | 每新边（`edge_operations.py:726`） | 新边 + 同实体对旧边 + 失效候选 → `duplicate_facts` + `contradicted_facts` | 1 次/边（零候选时 **0 次**，`:653`） | Neo4j（读） | **P-DEDUP** + **P-CONFLICT** |
| 9 | `_extract_edge_timestamps` | L1 | 每**新**边（`edge_operations.py:680` / `:812-813`，重复边跳过） | fact + episode `valid_at` → `valid_at`/`invalid_at` | 1 次/新边 | - | **P-META** |
| 10 | `resolve_edge_contradictions` + 新边自失效 | L1 | 每新边（`edge_operations.py:842` / `:826-839`） | 新边 + 矛盾候选 → 旧边 `invalid_at`/`expired_at`；或新边自身被判无效 | **no**（纯时序比较） | - | **P-CONFLICT** |
| 11 | `_extract_entity_attributes` | L1 | 每节点（`node_operations.py:744`） | 节点 + 自定义 entity_type → 结构化属性 | **仅当 entity_type 有字段**；本仓库不传 entity_types → **0 次** | - | ~**P-META** |
| 12 | `_extract_entity_summaries_batch` | L1 | 每 episode（`node_operations.py:767`） | 节点 + edge facts → summary | 短摘要直接拼接**不调 LLM**（`:879-882`）；需 LLM 的按 `MAX_NODES=30` 分批，**每批 1 次**（`:896-913`，prompt = `extract_summaries_batch`） | - | **P-AGGREGATE** |
| 13 | `create_entity_node_embeddings` | L1 | 每 episode（`node_operations.py:778`） | 实体名 → 向量 | no | - | **P-EMBED** |
| 14 | `_process_episode_data` → 预写 Cypher save | L1 | 每 episode（`graphiti.py:1170`） | 节点/边 → Neo4j（`MENTIONS`/`RELATES_TO`） | no | Neo4j（写） | **P-PERSIST** |
| 15 | `update_community`（单步动态扩展） | L1 | **默认关闭**（`graphiti.py:989` `update_communities=False`，分支 `:1184`） | 新实体 → 多数派社区 + `summarize_pair` + `generate_summary_description` | 2 次/节点（`community_operations.py:351-352`） | Neo4j（写） | ~**P-AGGREGATE** + ~**P-EMBED** + ~**P-PERSIST** |
| 16 | `build_communities()` 全量重建 | L1（L2 暴露为独立 MCP 工具 `server.py:539`） | **手动调用**，ingest 路径永不触发 | 全图 → 清空旧社区 → label propagation → map-reduce 摘要 → 社区名嵌入 → save | 每簇 map-reduce 若干次 | Neo4j（删+写） | **P-EVICT**（`remove_communities`，`graphiti.py:1504`）> **P-AGGREGATE** > **P-EMBED** > **P-PERSIST** |

**代码写入侧明确没有的步骤**：无 reflexion 自检（对应论文步骤 3，全仓库 `reflexion` 零命中）；无 `P-REWRITE`；实体/边层无任何 `P-EVICT`（只有社区层重建时会 `remove_communities`）。

### 4.2 检索侧 —— L2 `retrieve()` → L1 `Graphiti.search_()`

| # | name | 层 | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|---|
| R1 | `_search_knobs` / `_build_search_config` | L2 | 每 query（`server.py:470-471`） | top_k → `SearchConfig`（edge/node/community 三路，`episode_config=None`，limit=max(top_k,20)） | no | - | *（配置装配，无对应 primitive）* |
| R2 | query embedding | L1 | 每 query（`search.py:145-149`） | α → 向量 | no（embedding） | - | **P-EMBED** |
| R3 | `edge_fulltext_search` / `node_fulltext_search` / `community_fulltext_search` | L1 | 每 query，并行（`search.py:173`） | α → 2×limit 词面候选 | no | Neo4j Lucene | **P-SPARSE** |
| R4 | `*_similarity_search`（`sim_min_score=0.6` 阈值截断） | L1 | 每 query，并行 | 向量 → 2×limit 语义候选 | no | Neo4j 向量 | **P-DENSE** |
| R5 | `edge_bfs_search` / `node_bfs_search`（`bfs_max_depth=3`） | L1 | 每 query，并行（community **无此路**） | 种子（本仓库恒为 None）→ 邻域候选 | no | Neo4j | **P-GRAPHEXPAND** |
| R6 | `expand_bfs` 自动播种二次 BFS | L1 | 每 query，**条件触发**：配了 bfs 且无显式种子（`search.py:332-353`） | 第一轮 bm25/cosine 命中的 `source_node_uuid` → 二次邻域候选 | no | Neo4j | ~**P-GRAPHEXPAND**（第二次） |
| R7 | 重排（本仓库默认 `rrf`；上游 `search_()` 默认 `cross_encoder`） | L1 | 每 query，每对象类型各一次 | 多路候选 → 排序 + 分数 | rrf/mmr/episode_mentions/node_distance **0 次**；cross_encoder 每条候选 1 次外部模型调用 | - | **P-FUSE**（rrf/mmr）｜ **P-RERANK**（其余） |
| R8 | `_allocate`（最大余额法按 `mix=3:1:1` 分 top_k 名额 + 缺额回填） | L2 | 每 query（`server.py:387-409`） | 三类候选数 + top_k → 各类名额 | no | - | **P-SELECT** |
| R9 | `_edge_envelope` / `_node_envelope` / `_community_envelope` | L2 | 每 query（`server.py:346/372/380`） | 对象 → envelope（fact + `"lo → hi"` 日期区间 / name+summary / name+summary） | no | - | **P-ASSEMBLE** |
| R10 | *（引擎自带但未被使用）* `search_results_to_context_string` | L1 | — | `SearchResults` → `<FACTS>/<ENTITIES>/<EPISODES>/<COMMUNITIES>` 文本 | no | - | **P-ASSEMBLE**（`search_helpers.py:28`；唯一调用点 `tests/test_graphiti_int.py:77`） |
| R11 | *（边界外）* 答题 LLM | harness | 每题 | envelope 文本 + 问题 → 答案 | 1 次（glm-5.3，anthropic 协议） | - | **P-GENERATE** |

**代码检索侧明确没有的步骤**：无 `P-QUERYPARSE`（`search.py:117` 只判空串，随后直接 embed + 三路检索）；`P-SYMFILTER` **有实现但默认不启用**（`SearchFilters` 支持 `node_labels`/`edge_types`/四个时间字段/`property_filters`，但 `graphiti.py:1580`/`:1625` 和 `server.py:477` 都落到空 filter）；无 `P-TOOLLOOP`。

### 4.3 系统边界（代码侧）

- **属于记忆系统本体**：MCP 工具边界内的一切 —— `server.py` 封装层 + `graphiti_core` + Neo4j + 内部 LLM（glm-5.3，走 OpenAI 协议端点）+ 内部 embedding（embedding-3）。对外只有三个口子：`add_conversation` / `retrieve` / `build_communities`。
- **属于 agent / 评测 harness 侧（边界外）**：memory-bench runner、答题 LLM（同为 glm-5.3 但走 anthropic 协议、不同 prompt、不同职责）、判分脚本。
- **一处边界归属值得单独点出**：论文的 χ 在本接入里由 **L2 封装实现**（`_edge_envelope` 等），而不是用引擎自带的 `search_results_to_context_string`。也就是说 χ 这一步在"引擎本体"和"接入方"之间是**可移动的**——引擎两边都能做，本仓库选了接入方这一侧。
- **另一处**：`build_communities` 被 L2 提升成了一个显式 MCP 工具，等于把论文里"随数据流入自动发生"的社区维护，改造成了**边界上的手动运维操作**。

---

## 5. 论文↔代码分歧

> 每条给两侧证据。txt 行号 = 论文；`file.py:NNN` = `getzep/graphiti` @ a6e026f 或本仓库 `servers/graphiti/`。

| # | 分类 | 分歧 | 论文侧证据 | 代码侧证据 |
|---|---|---|---|---|
| D1 | **[paper-only]** | reflexion 式自我反思步骤 | txt:133-134 "we employ a reflection technique inspired by reflexion[12] to minimize hallucinations and enhance extraction coverage" | `grep -rn -i reflexion` 全仓库**零命中**；`node_operations.py:132`→`:244-252`（docstring 明写 "using a single LLM call"）→`:255-280` 单次调用后直接 return，无二次复检 |
| D2 | **[两边都有但行为不同]** | 实体消解的调用粒度 | txt:139-141 逐实体口吻："These candidate nodes, together with the episode context, are then processed through an LLM using our entity resolution prompt" | `node_operations.py:652-653` 零候选跳过 → `:659` 无 LLM 的相似度消解 → `:672-689` 只对**剩余**节点发**一次批量**调用（`:552`，`NodeResolutions` 返回列表） |
| D3 | **[两边都有但行为不同]** | 消解产物 | txt:141 "it generates an updated name **and summary**" | `prompts/dedupe_nodes.py:25-34` `NodeDuplicate` 只有 `id`/`name`/`duplicate_candidate_id`，**无 summary**；summary 在后续独立批量步骤重生成（`node_operations.py:836-913`） |
| D4 | **[两边都有但行为不同]** | 社区动态扩展的触发时机 | txt:184-187 "When the system adds a new entity node…it surveys the communities of neighboring nodes"，读起来是随 ingest 自动发生 | `graphiti.py:989` `update_communities: bool = False`（默认关），`:1184` 才是分支；整棵树还需单独 `build_communities()`（`:1490`），ingest 路径永不自动调用 |
| D5 | **[两边都有但行为不同]** | label propagation 的收敛保障 | txt:181-183 引 [13] Zhu & Ghahramani，"迭代至收敛"是 LP 的定义性质 | `community_operations.py:102` 与 `driver/operations/graph_utils.py:30` 两份实现均为**同步双缓冲 + `while True` 无迭代上限**；memory-bench 在 LoCoMo 图上实测不收敛（`patches/graphiti/community_operations.py:102-104`："4 分钟烧掉约 1200 万轮"） |
| D6 | **[code-only]** | "新边一出生就被判无效"的反向失效 | txt:166-170 只写单向："The introduction of new edges can invalidate existing edges" | `edge_operations.py:826-839`：若矛盾候选比新边更"新"，则 `resolved_edge.invalid_at = candidate.valid_at`、`resolved_edge.expired_at = now` |
| D7 | **[code-only]** | 第四路检索 `episode_search`（纯 BM25） | txt:202-205 φ 只有 3 分量 | `search.py:664` `episode_search` + `search_config.py:44-46` `EpisodeSearchMethod`；`search_config_recipes.py:98-103` 默认配方里就带 `episode_config`。（本仓库显式关掉：`server.py:114` `episode_config=None`） |
| D8 | **[code-only]** | context 模板多出 `<EPISODES>` 与 `<COMMUNITIES>` 两个区块 | txt:214-226 示例模板只有 `<FACTS>`/`<ENTITIES>` | `search_helpers.py:52-71` 的模板四个区块齐全，且 `:41-46` 明确把 `episode.content`（原文）也渲进去 —— 正好补上了论文 §3 定义（含 `Nc`）与示例模板（无 COMMUNITIES）之间的那处落差 |
| D9 | **[两边都有但参数不同]** | top-k | txt:275 "the **20** most relevant edges…and entity nodes" vs txt:323-324 "the top **10** most relevant nodes and edges"（论文自相矛盾） | `search_config.py:29` `DEFAULT_SEARCH_LIMIT = 10`；本仓库 `server.py:64` 默认 `search_limit=max(top_k, 20)`，再由 `_allocate` 裁到 top_k |
| D10 | **[两边都有但参数不同]** | BFS 跳数 | txt:245 只给符号 n，无数值 | `search_utils.py:67` `MAX_SEARCH_DEPTH = 3`；`search_config.py:85` 作默认值；`server.py:66` 默认 3 |
| D11 | **[两边都有但行为不同]** | BFS 种子来源 | txt:246-248 举例最佳用法是"using recent episodes as seeds" | `search.py:332-335`：无显式种子时用**本轮 bm25/cosine 命中的 `source_node_uuid`** 自动播种；本仓库从不传种子（`server.py:477`），实测首条 retrieve `edge.bfs hits_per_call=[0, 40]` |
| D12 | **[两边都有但行为不同]** | 重排方法的适用范围 | txt:256-264 笼统"Zep supports"五种，不分对象类型 | `search_config.py:53/61` edge/node 各 5 种；`:74` community 只 3 种（无 episode_mentions、无 node_distance）；`:69` episode 只 2 种 |
| D13 | **[两边都有但行为不同]** | 失效事实是否参与检索 | txt:157-172 + txt:196-264 完全未规定 | `search_filters.py:65` + `:242-271` 有 `expired_at` 过滤能力，但 `graphiti.py:1580`/`:1625` 默认落空 `SearchFilters()`，`server.py:477` 也不传 → 失效边照常返回 |
| D14 | **[两边都有但行为不同]** | 实体抽取 prompt 的严格度 | 附录 txt:461 "explicitly **or implicitly** mentioned"，6 条简短 guideline（第 6 条截断） | `prompts/extract_nodes.py:90-112` 11 条 `NEVER extract` 名单、`:169-203` 6 组带正反例示例、`:114`/`:134` 只保留 `**explicitly**` |
| D15 | **[code-only]** | `saga` 组织维度 | 论文全文无 saga | `graphiti.py:996-997` 两个参数；`nodes.py:867` `class SagaNode(Node)`；`has_episode_edge_ops.py:81` `HAS_EPISODE` / `next_episode_edge_ops.py` `NEXT_EPISODE` |
| D16 | **[code-only]** | 第五个时间戳 | txt:162-165 明确"tracks **four** timestamps" | `edges.py:280` `reference_time`，且 `edges.py:355` 确实写进 Cypher 持久化 |
| D17 | **[两边都有但行为不同]** | episode 粒度与抽取上下文窗口（**接入侧引入**） | txt:104-106 episode = 一条消息；txt:131-132 抽取上下文 = 最近 n=4 条消息 | `server.py:414-417` 把整个 session 拼成**一个** episode → 上游 `RELEVANT_SCHEMA_LIMIT=10`（`search_utils.py:64`）取到的变成"最近 10 个 **session**"，论文的 4-消息窗口假设失效 |
| D18 | **[两边都有但参数不同]** | 重排模型 | txt:284 BGE-m3（连续分数 cross-encoder） | 本仓库 cross-encoder 分支降级为 glm-5.3 输出 True/False → 1.0/0.0 二值（`server.py:157-208`），且默认根本不启用（`server.py:65` `rrf`，实测 105/105 全 RRF） |
| D19 | **[两边都有但行为不同]** | χ 的归属 | txt:208-213 把 χ 定义为 `f` 的第三个组成部分，即引擎能力 | 引擎**有** `search_helpers.py:28 search_results_to_context_string`（正是 χ），但 `search_()` 不自动调用它（全仓库唯一调用点 `tests/test_graphiti_int.py:77`），本仓库封装也没用，自己重写了一份（`server.py:346/372/380`） |
| D20 | **[一致，作为对照记录]** | 嵌入维度 | txt:137 "1024-dimensional vector space" | `embedder/client.py:23` `EMBEDDING_DIM = int(os.getenv('EMBEDDING_DIM', 1024))` —— 默认值与论文一致，但可被环境变量改写 |

---

## 6. 新造的 primitive 标签

| 标签 | 含义 | 造它的理由 |
|---|---|---|
| **P-SELFCHECK** `[NEW]` | LLM 对自己刚产出的结果做一次自我复检/批判并据此修补（reflexion/self-refine 式），**不引入新输入、不改变输出类型** | 种子词表里最接近的是 `P-EXTRACT`，但那是"从输入里抽东西"；这一步的输入是**上一步 LLM 自己的输出**，本质是 verify-and-repair，不是 extract。也不是 `P-REWRITE`（不做指代消解/时间归一化）。把它单列有两个分析价值：(1) 它是本次最大的一条 paper-only 分歧（论文有、代码零命中），塞进 `P-EXTRACT` 会让这条分歧在骨架里消失；(2) 自我复检在多个记忆系统（A-mem 的 note evolution、各类 self-refine ingest）里反复出现，跨系统骨架大概率还要用到它。**保守回退方案**：若统一骨架不想新增标签，可标为 `P-EXTRACT(第二轮·自检)`。 |

其余 24 个步骤全部复用了种子词表已有标签，未新造。

---

## 7. 复核统计

| 判定 | 条数 | 分布 |
|---|---|---|
| ✓ 属实 | **98** | paper-architecture 48 / code-architecture §1-§6 38 / code-architecture §7 12 |
| ✗ 不实 | **4** | 全部在 code-architecture：C15、C22、C23、C41 |
| ◐ 部分属实 / 需加限定 | **15** | paper-architecture 4（P9、P16、P39、P52）/ code-architecture §1-§6 10（C7、C9、C11、C16、C27、C32、C38、C40、C42、C45）/ §7 1（W9） |
| ? 无法核实 | **2** | W11、W15（`research-vault/`、`.context/memory-bench-r2n3/` 两条证据路径不在本机可见挂载内） |
| **合计** | **119** | |

**按文档分**：`paper-architecture.md` 52 条 = 48 ✓ / 4 ◐ / 0 ✗ / 0 ?；`code-architecture.md` 67 条 = 50 ✓ / 4 ✗ / 11 ◐ / 2 ?。

**行号锚点抽检**：实际打开核对的 `file.py:NNN` 共 63 个，命中 60 个，偏移 3 个（C7 `nodes.py:499-504` 的 `name` 实在基类 `nodes.py:95`；C9 `nodes.py:687-690` 的"无时间戳"忽略了基类 `nodes.py:98` 的 `created_at`；C45 的 `reflect` 计数应为 3 处、漏 `graphiti.py:1415`），**文件不存在 0 个**。实测数据抽检 3 组（`llm_calls`/`embed_calls`/`body_chars`、105 次 retrieve 的 reranker 与 communities 计数、首条 retrieve 的 `edge.bfs hits_per_call`），**数字全部精确命中**。

# 记忆/意图系统统一接口规范 v0.1

> 状态：v0.1（2026-08-18 起草）。这是 memory-bench 所有 MCP 封装与适配层的**唯一契约**。
> 覆盖：A档 5 系统（Mem0 / Graphiti / MemOS / A-MEM / Mandol）+ 意图系统适配层。B档（Letta / MRAgent）仅预留 §9 钩子。
> 原则：**评测循环（ingest → retrieve → answer → score）不在本规范内**——本规范只约束被测系统如何被驱动。

---

## 0. 设计原则

1. **同一契约，同一工具名**：每个系统一个独立 MCP server（stdio），六个工具名完全一致，评测脚本对系统无感知
2. **公平性优先于性能**：内部 LLM、温度、截断、渲染格式全部统一（§7），否则比的是配置不是记忆
3. **状态外置**：server 无跨 run 状态，数据落在各系统自己的存储（`MEMBENCH_STATE_DIR` 指定目录），reset/snapshot 操作的是这些存储
4. **归一化发生在 envelope，不侵入系统内部**：各系统保持原生机制，只在返回边界翻译成统一格式

## 1. 工具总览

| 工具 | 用途 | 幂等性 |
|---|---|---|
| `add_conversation` | 灌入一段会话（ingest 阶段） | 否（重复调用会重复写入，由评测循环保证只调一次） |
| `retrieve` | 检索（评测阶段，forced-call） | 是 |
| `reset` | 清空全部状态，每次 run 前 | **是（必须）** |
| `stats` | 用量/状态报告 | 是 |
| `snapshot` / `restore` | 状态快照与恢复 | snapshot 是；restore 恢复到快照点 |

## 2. `add_conversation`

```json
{
  "session_id": "locomo_conv1001_session03",   // 必填，benchmark 原生 session 标识
  "turns": [
    {"role": "user" | "assistant", "content": "…", "timestamp": "ISO8601 或 null"}
  ],
  "scope": {"kind": "user" | "session" | "episode", "id": "locomo_conv1001"},
  "metadata": {"benchmark": "locomo", "ingest_index": 3}   // 可选，透传溯源
}
```

返回：

```json
{"accepted_turns": 24, "native_notes": "mem0 extracted 11 facts"}
```

**scope 归一化规则**（各系统原生语义差异在这里吃掉）：

| 系统 | scope 映射 |
|---|---|
| Mem0 | `user_id = scope.id`（kind 一律折算到 user） |
| Graphiti | `group_id = scope.id`；每 session 一个 episode |
| Mandol | session 级存储，`scope.id` 作 namespace |
| MemOS / A-MEM | 内部不分 scope，`scope.id` 记入 metadata 供过滤 |
| MemHarness | `scope.id` 写入每条记忆并作为检索硬过滤；同时做 memory_id 前缀（`<scope>::<session>#<n>`），隔离可用编号判定而不依赖关键词 |
| GraphMemix | `scope.id` 写入每条记忆并作检索硬过滤；**关系图也按 scope 分组构建**（语义 mutual-kNN 不跨 scope 连边，否则跨对话泄漏） |
| 意图系统 | session 级索引，`session_id` 直接用 |

## 3. `retrieve`

```json
{
  "query": "……",                // fixed 模式 = benchmark 题面/金标 query；model_formulated 模式 = 评测循环让模型写好的 query
  "query_mode": "fixed" | "model_formulated",
  "top_k": 5,
  "filter": {                    // 可选；scope_id 为对话间隔离主键（mem0→user_id），其余过滤不支持时忽略并声明 FILTER_IGNORED
    "scope_id": "locomo_conv1001",
    "before_timestamp": "ISO8601",
    "session_ids": ["…"]
  }
}
```

返回：

```json
{
  "results": [ /* CanonicalEnvelope[]，见 §4 */ ],
  "query_used": "…",
  "query_mode": "fixed",
  "latency_ms": 412,
  "native_notes": ""
}
```

`query_mode` 说明：**query 的撰写永远发生在评测循环里**，retrieve 只忠实执行并回显。该字段的价值是让 stats 和 run 记录能归因"这批分数用的是什么模式的 query"。

## 4. Canonical Result Envelope（返回归一化，核心公平性机制）

```json
{
  "memory_id": "opaque-native-id",
  "text": "- 2024-05-12 · 用户提到他 6 月要搬去 Oakland（session03）",
  "source": {"session_id": "locomo_conv1001_session03", "turn_range": [4, 7]},
  "timestamp": "2024-05-12T00:00:00Z",
  "score": 0.83,
  "raw_format": "mem0_fact"
}
```

**渲染规则（全部系统强制一致）**：
- `text`：单条 markdown 列表项，≤ **600 字符**，超出截断加 `…`；`时间戳 · 内容要点 （session 溯源）` 结构
- 排序：score 降序；无原生分数的系统按检索顺序，`score: null`
  - **intent 系臂豁免（2026-09-07，同 turn_range null 先例）**：intent_full/intent_tier2 按**事实时间升序**返回（score 只决定入选）——时间线组装是该系统的原生机制（BASELINE-DESIGN.md B6），属系统属性非格式漂移；对应 run 报告须声明证据排序为跨臂变量
- `turn_range`：能定位就给，不能给 `null`——**意图系统的原生粒度是 session 级，turn_range 允许为 null**（粒度差异在论文里显式声明，不藏）
- **这批 envelope 的渲染结果就是喂给答题 LLM 的证据文本**——格式不同 = 混淆，所以格式必须锁死

**各臂 envelope 的原生粒度**（`top_k` 计数的是 envelope 条数，不跨臂等价；
locomo-r2-n3 实测，top_k=20）：

| 臂 | 一条 envelope 是 | evidence_text 中位长度 |
|---|---|---|
| `rag_baseline` | 一个 turn（对话原文单条） | ~2.9k 字符 |
| `mem0` | 一条 fact（LLM 抽取的事实陈述） | ~3.6k 字符 |
| `graphiti` | 一个图元素（edge / entity / community，MIX 3:1:1，20 条时 12/4/4） | ~3.7k 字符 |
| `intent` | 一个 session（整段会话，附原文摘录或 Tier2 精读引用） | ~9.6k 字符 |

同样 `top_k=20`，喂给答题 LLM 的证据体量差 3 倍——跨臂对比结论必须附带粒度声明。

> [!important] `memharness` 是唯一一个不保证返回满 `top_k` 的臂（2026-09-12 入矩阵）
> 它的一条 envelope 是一条经重写的指引（从一条 (情境, 原则) 二元组改写而来）。论文的一号机制
> 允许在使用前判定某条记忆不适用并整条丢弃，因此实际返回条数 = 召回条数 − 被拒条数。
> 35 turns 端到端实测（非 r2n3 全量）：拒绝率 70.15%，召回 10 条时实际交付 2-6 条；
> 且同题跨轮次的 envelope 集合不稳定（三次交集 1 条 / 并集 4 条）。做证据体量或方差归因时
> 不能假设它与其他臂同样喂满 20 条。详见 `servers/memharness/REPRO-NOTES.md` §4.2。

> [!important] `graphmemix` 同样不保证返回满 `top_k`（2026-09-12 入矩阵）
> 它的一条 envelope 是一个 turn，但选哪些 turn 是每题现算一次组合优化的解：论文 Eq.13
> 把“到底给几条”当成变基数问题精确求解，效用低于开辟一条独立证据链的成本（`pruning_root_cost=0.12`）
> 的节点会被主动剔掉，逐题以 `VARIABLE_CARDINALITY` 上报。LoCoMo conv0 实测幅度很小
> （平均保留 19.9/20），远不及 memharness，但做证据体量统计时仍不能按“恒为 20 条”假设。
> 另外它的 envelope **排序不是 score 降序**：按论文 Appendix A.5 的森林序（每个连通分量取效用
> 最高节点作根、按根排分量、分量内 BFS），“先给直接锚点、再给经可信关系恢复的上下文”
> 本身是机制的一部分，以 `ORDER=forest_bfs` 声明。

## 5. `reset` / `stats` / `snapshot` / `restore`

```json
// reset() →
{"ok": true, "cleared": {"memories": 214, "sessions": 35}}

// stats() →
{
  "n_memories": 214, "n_sessions": 35,
  "tokens_used": {"ingest": 18240, "retrieve": 3510, "internal_llm": 45120},
  "llm_calls": 47,
  "last_reset_at": "2026-08-18T10:00:00Z",
  "snapshots": ["ingested"]
}
```

- `tokens_used` 各字段：拿不到就 `null` + native_notes 说明；**internal_llm 单列**（Mem0 抽事实、意图系统推断都算），成本归因靠它
- `snapshot(tag)` / `restore(tag)`：
  - 支持方式按系统定：原生导出（Mem0）/ 数据库 dump（Graphiti→neo4j-admin）/ 存储目录拷贝（SQLite、jsonl）
  - 实在不支持 → 返回错误码 `SNAPSHOT_UNSUPPORTED`，评测循环对该臂退化为重灌（慢路径，只影响该臂时间线）
  - 用途：LongMemEval ingest 几十分钟/轮，**ingest 完 snapshot("ingested")，之后所有 run 从 restore 起**

## 6. 错误语义

工具**正常返回**内嵌错误码（不走 MCP 协议错误），评测循环统一处理：

| 码 | 含义 | 评测循环动作 |
|---|---|---|
| `SNAPSHOT_UNSUPPORTED` | 该系统无快照能力 | 该臂重灌 |
| `FILTER_IGNORED` | 时间/session 过滤不支持 | 照常出分，记入 run 报告 |
| `PARTIAL_INGEST` | 部分 turn 灌入失败 | 中止该 run 并报警 |

## 7. 公平性统一配置（防"比配置不比记忆"）

| 项 | 规定 |
|---|---|
| 内部 LLM | 所有系统内部调 LLM（抽取/推断）**必须同一 endpoint、同一模型、temperature=0**；配置从环境变量读，逐系统写入 run manifest |
| 答题 LLM | 各臂完全一致（评测循环职责，与本规范无涉但在此声明） |
| embedding | 有原生 embedding 的系统用其默认并记录模型名；无嵌入系统记 "none" |
| top_k | **默认 20，全 arm 一致**（2026-08-30 由 5 改为 20；依据：主流记忆系统的默认 top_k 普遍在 10–20，例如 mem0 v3 `top_k=20`、graphiti `DEFAULT_SEARCH_LIMIT`。旧 run（locomo-r1 / s2b-mock）用的是 5，**与新 run 不可混表**） |
| 检索阈值 | **各系统保持上游默认，不强行统一**（三家有、四家无，且作用在不同分数尺度上，不可通约）：<br>· mem0 `threshold=0.1`——卡语义 cosine 分，**融合前**排除（`utils/scoring.py:74-75`）<br>· memos `relativity=0.45`——服务端卡 `metadata.relativity`（`product_models.py:166`）<br>· graphiti `sim_min_score=0.6`——只卡 cosine 通道，BM25/BFS 不受影响（`search_utils.py:65`）<br>· mandol / rag_baseline / mock / intent——**无阈值**<br>· plugmem——检索侧无分数阈值。约束来自别处：记忆类型由 LLM 三选一，所选类型的可用节点不足时条数低于 top_k，用 `MODE_LIMITED` 上报（同 atommem 的 `SEED_LIMITED` 口径，不是 `TRUNCATED_BELOW_TOP_K`）。上游写死的路由阈值（标签 0.8、意图 0.1、切段 0.75、意图判等 0.8）保持不动，换 embedding 后的漂移由该 arm 的 `stats().threshold_probes` 观测<br>· atommem——检索侧无分数阈值，但有**符号过滤**：query 解析出具名人物时，`people` 不与之相交的 fact 一律被拒且无回退（`src/retrieval.py:284-288`）。它不是分数截断，用 `SEED_LIMITED` 而非 `TRUNCATED_BELOW_TOP_K` 上报。构建侧另有三个硬编码阈值（去重 0.95、冲突门 0.6、画像免 LLM 0.55），换 embedding 后会漂，由该 arm 的 `stats().threshold_probes` 逐次观测<br>· graphmemix——检索侧无分数阈值，但有**效用阈值**：变基数精修里一个孤立节点要被保留，效用 p_i 必须高于开辟一条证据链的成本（`pruning_root_cost=0.12`）。p_i 由检索分与 verifier 分经论文 Eq.14 的 sigmoid 得出，**换 embedding 后尺度会漂**，由 `stats().prize_probes` 逐次观测（LoCoMo 实测 p_i 中位数 0.14-0.16，与上游拟合记录的 prevalence 0.135 同量级）。被剔掉时用 `VARIABLE_CARDINALITY` 上报<br>**硬要求**：每个有阈值的 arm 必须逐题上报是否触发截断（`TRUNCATED_BELOW_TOP_K`），出分时单独统计 |
| 截断/渲染 | §4 锁死 |

**逐系统实际配置清单**（P6 声明，2026-08-19 核查后补齐；偏离统一配置的均为系统原生属性，论文显式声明）：

| system | 内部 LLM | embedding | 已知偏离 |
|---|---|---|---|
| mem0 | 智谱 glm-5.3，temp=0，reasoning_effort=low（extra_body 钉） | embedding-3（2048d） | 无 |
| graphiti | 同上（GenericClient + extra_body 钉） | embedding-3（2048d） | 无 |
| mandol | 无 LLM（纯 embedding 聚合） | embedding-3（cloud 适配器重定向，MODEL_CONFIG 注入） | ingest 零 LLM 调用 |
| amem | 智谱 glm-5.3，temp=0 + reasoning_effort=low（P4 修复后强制） | **本地 all-MiniLM-L6-v2**（原生设定，中文弱是系统属性） | 嵌入模型不同 |
| memos | 容器内 glm-5.3（温度/reasoning 均无透传口） | embedding-3（2048d） | **温度与推理深度未受控，接受容器默认** |
| intent | 智谱 glm-5.3，temp=0，reasoning_effort=low（P5 修复后） | 无独立 embedding（关键词匹配） | Tier 1 无语义向量 |
| memharness | 智谱 glm-5.3，temp=0 + thinking 三态映射同 mem0；两个调用点（会话蒸馏、逐条批判重构）同一套配置 | embedding-3（2048d） | ① 偏离论文/上游的 BGE-M3，与其他臂同口径，代价是两条 0.85 去重阈值尺度漂移（实测均未触发，由 `threshold_probes` 观测）；② 重构宽度取全部命中而非上游默认的 top-1（否则 19/20 证据绕过论文一号机制）；③ 蒸馏提示词做了 agent 域→对话域迁移（上游原版由 `DISTILL_STYLE=agentic` 保留）；④ 温度 0 偏离上游重构层的 temperature=1；⑤ 每段会话蒸馏至多 8 条，偏离上游实际的 1 条（上游 `min(num_memories_per_trajectory=1, max_pairs_per_episode=8)`；8 只是硬上限）。上游一条轨迹=一个单一任务，LoCoMo 一个 session 是多话题对话，取 1 会让全库只剩百条量级 |
| plugmem | 智谱 glm-5.3，temp=0 + thinking 三态映射同 mem0（自实现 `LLMClient` 替身，上游 client 无 extra_body 通道） | embedding-3（2048d） | ① 上游与论文原生用 NV-Embed-v2，此处换 embedding-3 与其余臂同口径，代价是上游四个硬编码相似度阈值的尺度漂移（由 `threshold_probes` 观测）；② 三处按论文补齐上游退化的能力（处方质量分、意图语义判重、多跳控制器），一处按契约默认关（推理压缩模块），逐条理由见 `servers/plugmem/arm-reproduction.md`；③ `max_tokens` 提到 8192（上游 4096），因命题抽取截断是静默的，截断次数由 `stats().truncated_completions` 上报 |
| atommem | 智谱 glm-5.3，temp=0 + thinking 三态映射同 mem0；**4 个内部 LLMInterface 实例全部钉住**（抽取/元数据/B1、冲突检测、事件归属与摘要、画像抽取与时间链） | embedding-3（2048d） | ① 上游与论文原生用本地 all-MiniLM-L6-v2（384d），此处换成 embedding-3 与其余四臂同口径，代价是上游三个构建侧硬编码阈值的尺度漂移（由 `threshold_probes` 观测）；② 论文一号贡献（LoRA 微调抽取器）上游无权重无推理代码，抽取按论文 Figure A.1 五条规则以统一 backbone 补齐；③ `max_tokens` 沿用上游写死的 2000（代码原生），仅在 thinking 非 low 档时提到 128k 防空回复 |
| graphmemix | 智谱 glm-5.3，temp=0 + thinking 三态映射同 mem0；两个调用点（节点 verifier、锢点条件关系验证 ECV）同一套配置，且**真并行发出**（论文 §4.1/§4.4.4 的断言；上游因 query-image caption 的数据依赖被迫顺序执行） | embedding-3（2048d） | ① 偏离论文/上游的 gme-Qwen2-VL-2B-Instruct（1536d 多模态编码器），代价是节点效用 sigmoid 的输入尺度漂移（由 `prize_probes` 观测）；② 证据预算 K 取契约 top_k 而非论文写死的 `reader_k=10`（否则比的是证据预算不是选证据能力）；③ 节点效用用论文 Eq.14 的固定超参展开，不用上游用 gold 标签在 dev fold 拟合的系数；④ 多视角在纯文本 LoCoMo 上退化为单视角，多模态部分未被测到；⑤ schema 关系只有 consecutive_turn（LoCoMo 不暴露配对的 native round 字段，同论文对 H2HMem 的处理）；⑥ 加了查询级结果缓存以满足契约的 retrieve 幂等性，代价是检索侧方差被归零（要测它用 `MEMBENCH_GRAPHMEMIX_CACHE=off` 单独跑对照） |

| ingest 时间上下文 | **评测循环统一把轮次时间以 `[YYYY-MM-DD]` 前缀编进 content**（2026-08-19 核查发现：glm-5.3 抽取会擅自补全年份且补错，原文“五月”→“2027年5月”；带前缀后修正。loaders/locomo.py 已实现。必须 harness 层对所有系统统一做） |

**retrieve 路径是否调 LLM，成本与延迟要分栏**（2026-09-10 随 atommem 入矩阵补）：

| 检索面 | arm | 说明 |
|---|---|---|
| 零 LLM 纯检索 | mock / rag_baseline / mem0 / graphiti / mandol / memos | retrieve 内无任何文本 LLM 调用 |
| 查询理解调 LLM | atommem | 每次 retrieve 有 1 次 B1 意图解析（论文 §3.5.1：人物/关键词/时间/是否要画像）。**只读 query，不读记忆内容**，不构成 active retrieval |
| 检索侧读记忆内容 | intent（Tier2）、plugmem（默认 T_max=2） | 在检索路径里精读候选内容，属 active retrieval。plugmem 的多跳控制器每跳要读本轮命中的记忆判断证据够不够（论文 §3.2 的默认能力）；设 `MEMBENCH_PLUGMEM_MAX_HOPS=1` 可退回「查询理解调 LLM」栏作纯被动对照，当前落在哪一栏由 `stats().retrieval_face` 回报 |
| 检索侧改写并可丢弃记忆 | memharness | 每条命中都走一次独立 LLM 调用做批判+重写（论文一号机制），判定不适用则整条丢弃。属 active retrieval，且比 intent Tier2 更进一步：**它会改写证据文本本身并减少证据条数** |
| 检索侧读记忆内容并做组合优化 | graphmemix | 每题 2 次 listwise 调用（并行）：一次读完全部 48 条候选给直接效用打分，一次判定锢点与候选之间的关系角色。属 active retrieval；与 memharness 的区别是**不改写证据文本**，只决定选哪几条与以什么顺序给；成本集中在检索侧（构建侧零生成式调用），LoCoMo conv0 实测约 6.8k internal_llm token/题 |

四栏的检索延迟与 internal_llm 成本不可直接并列。atommem 不需要像 intent Tier2 那样从主表拿出去（它没有用 LLM 看过记忆），
但也不能放进“零 LLM 检索面”那一栏做成本对比。
memharness 与 intent Tier2 同属 active retrieval，但两者不等价：Tier2 只是用 LLM 挑选和引用已有内容，
memharness 则以题面为条件重写每一条证据的文本，并会成批丢弃被判定不适用的记忆。
它的 internal_llm 成本主要发生在检索侧而非构建侧（端到端实测 19.2k token 中约 15k 在重构），
与 mem0/atommem 这类构建期重的臂正好相反，成本归因时不能把两类放进同一张表排名。

## 8. Server 工程约定

```
memory-bench/
  servers/
    common/            # envelope 渲染、scope 映射、stats 计数的共享实现
    mem0/server.py     # FastMCP，stdio
    graphiti/server.py
    memos/server.py
    a-mem/server.py
    mandol/server.py
    intent/server.py   # intent-recall-mcp 适配层
  servers.yaml         # system → 启动命令 + 环境变量声明（评测循环按此拉起 MCP client）
  scripts/smoke_test.py
```

- FastMCP 模板 100-200 行/系统；工具名、签名、返回结构**逐字段对本规范负责**
- `MEMBENCH_STATE_DIR`：每个 server 把自己系统的数据写到这里面的子目录，snapshot/reset 围绕它操作
- API key 一律环境变量，不进代码

## 9. B档预留（v1 再实现，此处只锁形状）

```
agent_decide(phase: "ingest" | "before_answer", context: {...})
  → {action: "call_tool", tool: "retrieve", args: {...}}
  | {action: "answer_directly", reason: "…"}
```

- 只给 Letta / MRAgent：控制权交给被测系统的内部决策（self-editing / 主动遍历）
- 评测循环把 agent_decide 的返回当作工具调用指令执行——**B档测的才是论文机制本身**
- 实现时论文必须声明：A档测被动检索面，B档测 agentic 面，两者不可混表

## 10. Smoke Test = 契约测试（`scripts/smoke_test.py`）

每个 server 封装完成后**必须全绿**才能进实验矩阵，对任意 server 依次执行：

1. `add_conversation`（3 turns）→ 断言 `accepted_turns == 3`
2. `retrieve(query="刚才说了什么", query_mode="fixed")` → 断言 ≥1 条 envelope 且**字段齐全、text ≤600 字符**
3. `snapshot("smoke")` → `reset()` → `stats()` 断言 `n_memories == 0`（reset 幂等性）
4. 再次 `reset()` → 仍为 0（重复调用安全）
5. `restore("smoke")` → `retrieve(同 query)` → 断言结果与步骤 2 一致（快照可复现）
6. 输出 PASS/FAIL 明细 + 耗时

## 11. 版本

- v0.1（2026-08-18）：初版。六个工具 + envelope + 公平性配置 + smoke 协议
- 修改规则：任何签名/envelope 变更 bump minor 并同步全部 server，smoke test 作为回归门禁

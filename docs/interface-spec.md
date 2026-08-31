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
- `turn_range`：能定位就给，不能给 `null`——**意图系统的原生粒度是 session 级，turn_range 允许为 null**（粒度差异在论文里显式声明，不藏）
- **这批 envelope 的渲染结果就是喂给答题 LLM 的证据文本**——格式不同 = 混淆，所以格式必须锁死

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
| 检索阈值 | **各系统保持上游默认，不强行统一**（三家有、四家无，且作用在不同分数尺度上，不可通约）：<br>· mem0 `threshold=0.1`——卡语义 cosine 分，**融合前**排除（`utils/scoring.py:74-75`）<br>· memos `relativity=0.45`——服务端卡 `metadata.relativity`（`product_models.py:166`）<br>· graphiti `sim_min_score=0.6`——只卡 cosine 通道，BM25/BFS 不受影响（`search_utils.py:65`）<br>· mandol / rag_baseline / mock / intent——**无阈值**<br>**硬要求**：每个有阈值的 arm 必须逐题上报是否触发截断（`TRUNCATED_BELOW_TOP_K`），出分时单独统计 |
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

| ingest 时间上下文 | **评测循环统一把轮次时间以 `[YYYY-MM-DD]` 前缀编进 content**（2026-08-19 核查发现：glm-5.3 抽取会擅自补全年份且补错，原文“五月”→“2027年5月”；带前缀后修正。loaders/locomo.py 已实现。必须 harness 层对所有系统统一做） |

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

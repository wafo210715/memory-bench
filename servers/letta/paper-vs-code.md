---
title: Letta / MemGPT Paper ↔ Code 对照
date: 2026-09-06
tags:
  - memory-bench
  - paper-vs-code
  - letta
---

# Letta / MemGPT Paper ↔ Code 对照

> [!note] 口径
> paper = arXiv:2310.08560v2（Packer et al. 2023/2024，13 页）
> code = letta repo @ `origin/archive` `56ba9c25`（v0.16.8, 2026-08-13），默认 `letta_v1_agent` → `LettaAgentV3`
> 事实依据以同目录 `verification.md` 为准。两者相隔近三年。
> 空格 = 该阶段在这一侧不存在。「默认死」= 代码完整但默认不可达，非损坏、非缺凭证。

## A 段 · 形成期（query-independent）

| 阶段 | Paper | Code |
|---|---|---|
| A1 intake | 四类事件：用户 / 系统 / 交互 / 定时（§2.4） | 三类消息：user / assistant / tool |
| A2 distill | 滚动式递归摘要（旧摘要 + 被驱逐消息）。是否独立 LLM 调用未说明（P18） | `compact_messages`，摘要模型可换更便宜的。旧 `Summarizer`（驱逐 30%）仅 V2/legacy 可达 |
| A3 admit | 警告 70% → 冲刷 100%、驱逐 50%，三个数都是 e.g. 不是硬编码；外加 LLM 自编辑工作上下文 | 阈值：非 GPT-5 100%、GPT-5 家族 90%；外加 Block append/replace——`core_memory_replace` 不检查唯一性，替换所有匹配 |
| A4 index | Wikipedia 语料离线预 embedding（实验装置，非运行时）+ archival insert（论文描述，无实验走过 P22/P45） | |
| A5 commit | pgvector + HNSW 存向量；recall storage 双写 | `messages` 表 ORM 行（活）/ Passage 向量表（默认死）/ Block 的 git + Markdown（双重开关） |
| A6 internalize | | |

## B 段 · 动员期（query-conditioned）

| 阶段 | Paper | Code |
|---|---|---|
| B1 cue | LLM 自主发起检索（§2.3「完全是自主的」） | 同为 LLM 自主，形式是写 search 工具参数 |
| B2 recall | 两通道：recall storage search（算法从未给出 P30）+ archival search（余弦、分页） | 单通道：`conversation_search` 走 `ILIKE` / `JSON_EXTRACT…LIKE` 子串匹配，无词权重无分数。向量检索默认死 |
| B3 expand | | |
| B4 appraise | | |
| B5 select | | |
| B6 deliver | 函数返回值拼回主上下文，运行时错误一并喂回，分页防溢出 | `Memory.compile()` 渲染 Block（标准/带行号/git）→ 工具结果转 Message 进下一轮 prompt |
| B7 generate | 边界外，LLM Processor 只吃 prompt token 吐 completion token（§3.3） | 纯文本输出即回复 |
| B8 loop | heartbeat：`request_heartbeat=true` 链式继续。无步数上限、无安全阀（grep 零命中 P48） | `_decide_continuation`：有工具调用则继续。`request_heartbeat` 写死 `False`，不读 |

> [!tip] B3/B4/B5 两侧都空，成因相反
> paper 空 = 没写清楚（search 是黑盒，无算法无重排无 top-k）；
> code 空 = 没东西可做（单通道，无可融合/排序/组合选择，结果按 `created_at` 排）。

## 三点最大区别

### 1. 语义检索整条线消失

不是一个节点变了，是一串格子塌了：A4 有→空，B2 双通道→单一子串匹配，B4/B5 因此必然空
（`LIKE` 不产生分数）。论文 Fig.6/8 的分页多步归档查询演示在默认配置下不存在。

而 `conversation_search` 的 docstring 至今写着 `hybrid search (text + semantic similarity)`——
文档在承诺已被摘掉的能力。这条属「没跟上」，不是演进。

### 2. 「要不要再来一轮」的判据换了

paper 是模型显式举手（`request_heartbeat=true`），code 是从「有没有调工具」反推。
`letta_agent_v3.py:2071` 写死 `False`；读旧标志的逻辑仍在 `agent.py:563,834-842` 与
`letta_agent_v2.py:1126,1241-1250`，两套控制流并存但默认不走。

自主权从显式声明降为隐式推断——但论文那条链没有任何安全阀，这次替换未必是退步。

### 3. 代码新增了论文没有的记忆版本管理（纯加法）

Block 以 Markdown + YAML frontmatter 存进 git 仓库，每次改动一次 commit，
git 是 source of truth、Postgres 只当 cache。

| 项 | 实现 |
|---|---|
| 格式 | `block_markdown.py`；frontmatter 仅非默认值时渲染，`limit` 故意排除 |
| 路径 | `persona.md` ↔ label `persona`；特例 `skills/{name}/SKILL.md` ↔ `skills/{name}` |
| 位置 | `{base}/{prefix}/{org_id}/{agent_id}/repo.git/`，OSS 默认 `~/.letta/memfs` |
| 历史 | `git log` 取 sha / parent / author / 时间戳 / message；但 `files_changed`、`additions`、`deletions` 写死空值——查得到何时谁改，查不到改了什么 |
| 开关 | 服务端 `LETTA_MEMFS_SERVICE_URL` 加 agent 的 `git-memory-enabled` tag，双重 |
| 边界 | OSS 只有 `LocalStorageBackend`；云版 `memfs_client.py` 不在本仓库 |

## 附：两条推导

1. A4 两侧其实都空（就运行时对话记忆而言）。paper 那格填的是 Wikipedia 语料离线预处理，
   `verification.md` W0 原话归类为「实验装置，不是运行时机制」。
   A4 空 → B2 只能弱是因果，不是巧合。
2. `conversation_search` 两条 SQL 分支不等价：Postgres 用 `json_array_elements` 展开后只匹配
   `type='text'` 的 `text` 字段；SQLite 用 `JSON_EXTRACT(content,'$')` 把整个 JSON 当字符串做
   `LIKE`，字段名和 type 标记都在匹配范围内。同一查询词在两个后端可能返回不同结果。
   代码注释自承是 SQLite 不支持 `$[*]` 的绕道。`verification.md` C54 记了实现，未展开成此结论。

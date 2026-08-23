# Phase 2 评测循环设计 v0.1（bench-design）

> 状态：**待批**（2026-08-21 晚起草）。批复后开写 `bench/runner.py`。
> 前置：`interface-spec.md` v0.1（被测系统契约）、`PLAN.md` §6（臂矩阵与流程）、§10（风险预案）。
> 本日新增输入：**glm-5.3 云端额度不足 → 答题/判分/系统内部 LLM 全部切换到 Linux vLLM（qwen 系 27B，OpenAI 兼容 endpoint）**；embedding 维持云端 embedding-3 不动。

---

## 0. 相对 PLAN.md 的三个增量决策（本次批复对象）

| # | 决策 | 理由 |
|---|---|---|
| D1 | 答题/判分/内部 LLM endpoint 切换 vLLM | 云端额度不足；自部署后边际成本≈电费，全量+n=3 均可行 |
| D2 | embedding 不切，维持云端 embedding-3 | LLM 与 embedding 分开计费；所有 embedding 用户已统一，动它无收益徒增部署 |
| D3 | 判分双轨：本地 F1 + LLM-judge 全题 | LoCoMo 官方即 LLM-judge；F1 免费且可复核判分器本身 |

## 1. 循环总览

```
┌─ 一次性（每系统）────────────────────────────┐
│ ingest: 10 conv × 逐 session add_conversation │
│   （[日期]前缀 loader 已内建；内部 LLM→vLLM）  │
│ → snapshot("locomo_full")                    │
└──────────────────────────────────────────────┘
┌─ 每 run（系统 × conv × 重复 n）────────────────┐
│ restore("locomo_full")（无快照系统走重灌慢路径）│
│ 逐题: retrieve(question, fixed, top_k=5)       │
│   → envelope[] 渲染为 evidence 文本（spec §4） │
│   → 答题 LLM → {answer, ...} JSON             │
│   → 判分: F1(本地) + LLM-judge(vLLM)          │
│   → answers.jsonl append（含全部原始输出）     │
└──────────────────────────────────────────────┘
┌─ 出分 ────────────────────────────────────────┐
│ 5 类题型 × 8 臂 总表；cat1-4 主表，cat5 单列   │
└──────────────────────────────────────────────┘
```

- 跑台 = 无头 Python asyncio + MCP stdio client（复用 `scripts/smoke_test.py` 的拉起/解析模式）
- full-context 基线不调 retrieve，直接把 conv 全文渲染成 evidence（runner 内置，不占 server）
- 其余 7 检索臂（含新写的 rag_baseline）全部走 MCP 契约，评测循环对系统无感知

## 2. 配置层：vLLM 切换清单

### 2.1 endpoint 分工（2026-08-21 晚实测后定稿）

| 组件 | endpoint | 模型 | 说明 |
|---|---|---|---|
| **被测系统内部 LLM**（mem0/graphiti/amem/memos/intent） | 云端智谱（**不动**） | glm-5.3, temp=0, thinking=low | = Phase 1 门禁配置零改动；所有被测系统统一，保记忆形成公平；额度消耗集中在 ingest（1-10M tok/系统，分批灌） |
| **答题 LLM** | ngrok 隧道 → Linux vLLM，**Anthropic 兼容接口** | `qwen38-27b-nvfp4`, temp=0 | `.env` 新增 `MEMBENCH_ANSWER_*` 四变量；实测 30k input 单发 7.2s、无 think 污染、JSON 干净 |
| **判分 LLM** | 待定 | — | 候选 A 云端 glm-5.3；候选 B 同网关 `qwen3.8-max` 异模型判分（零部署成本规避 same-model bias）；候选 C 同模型 |
| embedding（全部） | 云端 embedding-3 | **不动** | 2026-08-21 冒烟复验 2048 维正常 |

额外好处：内部 LLM（智谱）与答题 LLM（qwen）异源，规避“答题模型偏爱自家生成内容”的偏差。

### 2.2 thinking 控制（对应原 reasoning_effort=low 的"钉住"决策）

qwen3 系 hybrid thinking 必须显式关闭，否则判分/答题输出被 `<think>` 污染且耗时翻倍：

- vLLM chat API：`extra_body={"chat_template_kwargs": {"enable_thinking": false}}`
- 若模型不支持该参数 → 部署侧 `--enable-reasoning --reasoning-parser` 关闭，或 system prompt 追加 `/no_think`
- 落地后跑 3 题验证输出无 `<think>` 段，写入 run manifest

### 2.3 待确认清单（2026-08-21 实测后收窄）

| 项 | 状态 |
|---|---|
| 模型确切名 | ✅ `qwen38-27b-nvfp4`（网关另有 `qwen3.8-max`） |
| 接口协议 | ✅ Anthropic 兼容 `/v1/messages`，无 think 污染，temp=0 生效 |
| 并发能力 | ✅ 16 并发 × ~30k tok 实测 16/16 成功，聚合 ~10.7k tok/s；runner 默认并发 16（可配） |
| max_model_len | ✅ 隐式验证：30k input 正常返回 |
| ngrok 隧道长稳 | ⚠️ 免费版重启换 URL；runner `--resume` 断点续跑兑冲，变更只改 `.env` |
| memos 容器网络 | N/A（memos 内部 LLM 维持智谱云端，不再指向 vLLM） |

## 3. 臂矩阵（8 臂）

| 臂 | evidence 来源 | 实现位置 |
|---|---|---|
| `full_context` | conv 全文（272 sessions 拼接渲染） | runner 内置 |
| `rag_baseline` | turn 级 chunk + embedding-3 余弦 top-5 | **新写 `servers/rag_baseline/server.py`** |
| `mem0` / `graphiti` / `memos` / `amem` / `mandol` | 各自 retrieve | 已有 server |
| `intent` | intent retrieve | 已有适配层 |

### rag_baseline 设计（第 8 个 server，防止"记忆系统只是向量检索"的质疑缺锚点）

- chunk = 单 turn（`[日期] speaker: text`，与 ingest 渲染一致）；scope 过滤 = `scope_id` 精确匹配
- embedding-3 云端 + 本地余弦（无索引库，272 sessions ≈ 6k 向量，暴力扫毫秒级）
- 全部走 interface-spec 六工具契约，**过同一套 8 步 smoke 门禁后才能进矩阵**

## 4. ingest 协议

1. 逐系统顺序执行（一次只起一个 server，避免资源互踩）；逐 conv 逐 session `add_conversation`
2. 每 conv 灌完即写 ingest 进度文件（`.state/ingest_progress/<system>.json`，记已完成 session_id）——**中断续灌靠它**，`add_conversation` 非幂等（spec §1），恢复时跳过已灌
3. 全部灌完 → `snapshot("locomo_full")`；`SNAPSHOT_UNSUPPORTED` 的系统标记走重灌慢路径（预期只有 memos）
4. ingest 内部 LLM 已随 §2.1 切 vLLM；thinking 关闭同 §2.2

## 5. 答题协议

- **温度 0，thinking 关**；所有臂同一 prompt、同一渲染。temp=0 是“把答题器当测量仪器”的方差控制手段，不是产品主张；真实温度下的部署效度归二轮 free-call 臂（PLAN §9）。若 qwen 在 temp=0 出现明显输出退化（重复/截断），退 temp≤0.3 并在 manifest 声明 + 全臂统一，n≥3 补方差
- prompt（英文，与语料一致；full-context 臂 evidence 段换为全文，其余完全一致）：

```text
System: You answer questions about a two-person conversation history,
using ONLY the evidence provided. If the evidence does not contain the
answer, reply exactly "Invalid question" (some questions are designed
to be unanswerable). Answer concisely.

User:
## Evidence
{evidence_text}          ← 检索臂: top-5 envelope 渲染；full-context 臂: conv 全文

## Question
{question}

Reply in JSON: {"answer": "...", "quote": "<short supporting quote or null>"}
```

- 输出解析：取首个 JSON 对象；解析失败重试 1 次（附格式纠错指令），再失败落盘 `PARSE_ERROR` 由判分记 0
- `quote` 字段落盘供人工抽检证据归因（不参与判分）

## 6. 判分协议（双轨）

### 6.1 轨 1 · F1（本地，免费）

- SQuAD 式词级 F1：prediction vs gold（cat1-4）；multi-answer（gold 为数组）取 max
- cat5 adversarial：金标语义为"应拒绝"，F1 不适用 → 只走 LLM-judge

### 6.2 轨 2 · LLM-judge（全题 1986 × 8 臂）

```text
System: You grade answers against a gold answer. Output JSON
{"correct": 0|1, "reason": "<one line>"}.
Rules: semantically equivalent = correct; partial = incorrect (strict);
if gold indicates the question is unanswerable/invalid, correct only when
the answer also refuses ("Invalid question" or equivalent).

User: Question: {q}\nGold: {gold}\nPrediction: {p}
```

### 6.3 判分模型：**已定（2026-08-22）＝同模型 qwen38-27b（vLLM）**

- 用户拍板：打分模型不需要很聪明（生态先例：LoCoMo 系 judge 主流就是 gpt-4o-mini 小模型），统一 qwen38-27b 打分零智谱成本、不抢 graphiti 额度
- same-model judge 偏差已知，manifest 声明；二轮换异模型（云端 glm-5.3 或更强）复核（~1.6M tok/n）
- 备选 A（云端 glm-5.3 独立 judge）仍保留为论文轮口径对齐选项

- 主表口径 = LLM-judge correct rate（与 LoCoMo 官方/mandol 92.21% 声明同口径）；F1 作副表交叉验证
- **cat1-4 主表、cat5 单列 abstention 正确率**（对齐 mem0 原版判分排除 cat5 的惯例，保证与 SOTA 数字可比）
- 判分原始输出全量落盘，支持事后复核与人工抽检 20%

## 7. 落盘结构与断点续跑

```
runs/
  2026-08-22_locomo_r1/
    manifest.json        # 臂×系统×seed×配置快照(env hash, model, prompt 版本)
    answers.jsonl        # append-only: {arm, system, conv, qa_id, category,
                         #   question, gold, evidence_envelopes, answer_raw,
                         #   answer_parsed, f1, judge_raw, judge_correct, ts}
    ingest_progress/     # §4 续灌游标
    summary.json         # 出分脚本产物：5 类 × 8 臂矩阵
```

- **挂起条件**：LLM 连续 5 次失败/超时 → run 标记 `SUSPENDED` 落盘退出；`--resume` 从 answers.jsonl 已有 qa_id 之后继续（幂等键 = arm+system+conv+qa_id+n）
- MCP server 崩溃 → 该系统本轮标 `FAILED`，不阻塞其他臂

## 8. 成本与吞吐参考（2026-08-21 实测 cl100k 估算）

| conv | sessions | QA | transcript tok |
|---|---|---|---|
| conv-26 | 19 | 199 | 17.2k |
| conv-30 | 19 | 105 | 13.8k |
| conv-41 | 32 | 193 | 26.7k |
| conv-42 | 29 | 260 | 22.9k |
| conv-43 | 29 | 242 | 26.2k |
| conv-44 | 28 | 158 | 25.5k |
| conv-47 | 31 | 190 | 25.3k |
| conv-48 | 30 | 239 | 24.2k |
| conv-49 | 25 | 196 | 19.7k |
| conv-50 | 30 | 204 | 24.2k |

| 项 | input tokens |
|---|---|
| full-context 臂全量 n=1 | ~46M |
| 7 检索臂全量 n=1（~1k tok/题） | ~14M |
| 判分（8 臂 × 1986 × ~100 tok） | ~1.6M |
| **跑分合计 n=1 / n=3** | **~62M / ~190M** |
| ingest 内部 LLM | 量级 1-10M/系统（mem0/graphiti 偏高） |

> cl100k 与 qwen tokenizer 有 ±10% 级差异；够 concurrency 规划用，manifest 记真实用量。

## 9. 执行顺序（批复后）

| 步 | 内容 | 验收 |
|---|---|---|
| S1 | `servers/rag_baseline/` 封装 | 8 步 smoke 门禁全绿 |
| S2 | `bench/runner.py` + mock 臂 1 conv 端到端（LLM 指 vLLM） | answers.jsonl 完整、判分可解析、--resume 生效 |
| S3 | intent + mem0 + full-context 三臂 × 1 conv shakeout | 人工抽 10 题证据质量；分数有区分度（非全 0/全 1） |
| S4 | 8 臂 × 3 conv 第一版对比表 | `summary.json` + 表格 |
| S5 | 全量 10 conv × n=3（后台，跨夜） | Phase 4 粗结论地基 |

S1-S2 不依赖 vLLM 就绪（mock 臂可先指任意 OpenAI 兼容 endpoint 空跑管线）；S3 起需要 vLLM `max_model_len≥32k` + thinking 关闭确认。

## 10. S2b shakeout 发现（2026-08-21 深夜，conv-30 三臂）

| 臂 | judge_acc | 结论 |
|---|---|---|
| full_context | 0.476 | 基线健康，管线可信 |
| mock | 0.276 | 弱检索弱分，符合契约靶定位 |
| **intent** | **0.048** | ⚠️ 结构性拖后腿，非管线 bug |

intent 低分归因（证据已落盘可复核）：
1. **envelope 只有意图摘要无原文细节**——LoCoMo 多为事实题（日期/数字/人名），摘要不含答案；avg evidence 仅 671 字符
2. **Tier 1 关键词中英错配**——英文 query vs 中文摘要，score 均 ≤0.14，排序基本失效（不同问题返回同一批热门 session）
3. **envelope timestamp 是 ingest 时间非对话时间**——temporal 题全废
4. **Tier 2 精读未接入适配层**——intent-recall-mcp 的完整形态是 search（Tier 1）+ read_session_detail（Tier 2 LLM 精读原文），适配层只实现了前者；原文已落盘（sessions/*.jsonl）修复不需重灌

修复选项与执行结果（2026-08-21 深夜，conv-30 验证）：

| 步 | 内容 | 成本 | conv-30 结果 |
|---|---|---|---|
| A | envelope 附 query 命中 turn 原文摘录 + timestamp 改对话时间 | 零 LLM | 0.048 → 0.152；evidence 671→2340 字符；召回 0.429（瓶颈仍在排序） |
| A+ | Tier 1 双通道打分：意图摘要 ∨ 原文 turn（取 max）——修复英文 query vs 中文摘要错配 | 零 LLM | **0.152 → 0.257，追平 mock（0.276）**；召回 0.429 → **0.733（反超 mock 0.657）**；空 evidence 0 |
| B | 适配层接入 Tier 2 精读（Tier 1 候选 → LLM 读原文提炼针对性证据） | ~1 次 LLM/题（智谱，记 internal_llm） | **0.257 → 0.286，反超 mock（0.276）**；105 次调用 / 430k tok；精读 quote 覆盖 22% envelope（无关 session 兜底机械摘录），p50 2.4s/题 |

附带根因修复（B 实现过程中发现）：**tokenize 中文 bigram 非重叠 bug**——JS `match(/[\u4e00-\u9fff]{2}/g)` 非滑窗，"帕丁森"只切"帕丁"丢"丁森"（与 mock 的 Python 滑窗语义不一致）；改逐 run 滑窗后 smoke 抖动根治（连续 3 次 8/8）。此 bug 影响真实使用场景的中文匹配能力，非 benchmark 特有。

A+ 公平性叙事：intent(摘要+原文双通道) vs rag_baseline(纯原文) —— 正增益可归因到意图摘要层。
结论：**“通用 benchmark 打平不拖后腿”的预期在 A+ 后达成**；B 负责把召回优势（0.733）转化为分数优势（现差距在 envelope 证据密度：命中 turn 摘录非 gold turn/截断损伤）。

## 11. 版本

- v0.1（2026-08-21）：初版待批。D1-D3 增量决策 + vLLM 切换清单 + 双轨判分 + rag_baseline 设计。

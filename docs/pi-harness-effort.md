# Pi Harness 工程量评估（可复现性轨道 · 第二轮地基）

> 状态：调研稿（2026-08-18，fork 会话产出）。另一会话正在执行 PLAN.md 的 Phase 0-4（forced-call 无头轨道）；本文档覆盖**第二条轨道**：基于 Pi 的 free-call 真实场景 harness。
> **与 `REPRO-PLAN.md` 的关系**：REPRO-PLAN 定义语言无关的契约层（A-G + BG 模块，Python 优先，起步落 `harness/` 子目录）；本文档是其中生态效度臂的 **Pi 侧实现选型**，契约以 REPRO-PLAN 为准，不重复定义，只做映射（见 §1.5）。
> 双轨关系：无头 forced-call 测"检索质量 × 证据利用"（隔离变量）；Pi harness free-call 测"真实工作场景中的部署价值"（生态效度）。两轨共用同一批 MCP 封装的记忆/意图系统。

## 0. 定位：Pi harness 解决什么

**生态效度**：headless 脚本调 API 证明不了"系统在真实工作流里有用"。Pi harness 用最低限度的真实工具集（read/write/edit/bash/grep/browser/search + MCP）还原大部分人的工作场景，让记忆/意图系统在**同一个标准化 agent 循环**里自由发挥——SUT = (模型 + 工具集 + harness + 记忆/意图接线)，跨臂只变接线，其余全同。

**标准化 SUT**：所有记忆/意图系统跑在同一个 harness 上，这正是 controlled comparison 在 free-call 轨的实现方式。

## 1. 现有资产盘点（调研结论，2026-08-18）

| 资产 | 位置 | 对我们的价值 |
|---|---|---|
| **pi-agent-core** | `~/Documents/repo/pi/packages/agent` | 完整 agent runtime：agent-loop、tool calling、session 事件、skills、system prompt 组装。`createAgentSession` 支持自定义工具集（`noTools` 选项）、system prompt 变换 |
| **pi-ai** | `packages/ai` | 多 provider 统一 LLM API——模型作为实验变量的基础设施 |
| **pi evals** ⭐ | `packages/evals` | **现成的 benchmark 跑台雏形**：`createPiCodingAgentHarness` 基于 vitest-evals，把真实 AgentSession 跑在隔离目录里，session JSONL 全落盘（runs.jsonl 索引 + sessions/ 附件）。README 明说用于"compare prompts, tools, skills, models, or other harness configurations"——就是控制变量比较 |
| **session JSONL 持久化** | `packages/session-backends` + evals 附件机制 | "model-visible means logged" 已有一半：pi 原生就把 session 事件写 JSONL，replay 有基础 |
| **MCP client 参考实现** | Proma `apps/electron/src/main/lib/*`（`@modelcontextprotocol/sdk`） | ⚠️ **pi 核心不带 MCP**——Proma 自己在 electron 层实现的。MCP→AgentSession 工具桥接要自己写，但 Proma 代码就是移植模板 |
| **Benchmark-Agent** | `~/Documents/repo/Benchmark-Agent`（Python） | benchmark 生成管线，三种接入方式见 §3 |

## 1.5 与 REPRO-PLAN 模块映射（避免两轨重复造）

| 本文档 | REPRO-PLAN 对应 | 关系 |
|---|---|---|
| M1.2 run manifest | E1 | 契约抄 E1，Pi 侧只写 TS 类型绑定 |
| M1.3 ContextInjector 缝 | D1/D3/D4 | 接口照 D1；Pi 侧落点是 `transformSystemPrompt` vs message 组装，需实验定 |
| M1.4 占位工具 | F2 | 直接实现 |
| M2.2 benchmark 适配器 | B1-B4 | Adapter 接口照 B1；ingest/判分复用 Python 侧 |
| M4 可复现层 | E2-E5 | event log 不变式在 Pi 侧天然占优（session JSONL 原生落盘），但要补"注入也落盘" |
| M3(b) L1 原生 skills | BG1-BG3 | BG 产出 SOP-as-code 后，Pi 侧包成 skill 即可 |

**原则：Pi 轨不定义契约，只消费契约。** 两轨通过 `docs/interface-spec.md` + REPRO-PLAN 的 E1 manifest schema 对齐。

## 2. 工程模块分解

### M1 · Harness 核心（~1 周）

| 子模块 | 内容 | 工作量 | 风险 |
|---|---|---|---|
| M1.1 MCP 桥接 | 移植 Proma 的 MCP client 模式：per-run MCP server 清单（= 实验臂的接线开关）→ 注册为 AgentSession 工具 | 2-3d | Proma 实现在 electron main 里，剥离依赖要一天 |
| M1.2 Run manifest | `(benchmark × SUT 配置 × MCP 集 × seed × 重复次数)` 声明式 JSON，配置即数据 | 1d | 低 |
| M1.3 ContextInjector 缝 | 意图/记忆的 ambient 注入面：system prompt 变换（pi 已支持 `transformSystemPrompt`）或 user message 组装注入；**注入内容也要作为事件落盘**（补齐 model-visible-means-logged） | 1-2d | 注入不落盘 = 不可归因，这是硬要求 |
| M1.4 占位工具 | off 臂放等长描述的 no-op 工具，消工具列表混淆 | 0.5d | 低 |

### M2 · Benchmark 跑台（~1 周）

| 子模块 | 内容 | 工作量 |
|---|---|---|
| M2.1 跑台选型 | 两条路：(a) 直接用 pi evals（vitest-evals 套件）——最贴现有代码，但绑定 vitest 生态；(b) 自写薄 runner 用 `packages/client/server` 无头驱动——更自由。**推荐先 (a) 后 (b)**：(a) 两天能跑通 | 2d（a 路线） |
| M2.2 benchmark 适配器 | LoCoMo/LongMemEval/free-call 版自家 benchmark 三族。ingest 与判分**复用 memory-bench 的 Python 代码**（Phase 2 产物），TS↔Python 走 JSONL 文件 + subprocess 桥 | 每族 1-2d |
| M2.3 场景工具集预设 | "最低限度还原工作场景"落为 SUT preset：`{read/write/edit/bash/grep}` / `+browser` / `+search` 三档，跨臂固定 | 1d |

### M3 · Benchmark-Agent 植入（三种方式，按序推进）

题型设计参照 PAST-Bench（[arXiv 2608.04003](https://arxiv.org/abs/2608.04003)）能力轴（memory / procedural reuse / information gathering / update）+ retained-experience on/off 对照协议——后者与我们的 b 臂、M4 replay 落盘同构。

| 方式 | 做法 | 工作量 | 适用 |
|---|---|---|---|
| **(a) 子进程工具** ⭐先做 | 把 `generate_benchmark.py` 包成 pi 的一个 skill/command，数据集卡指向 Proma QA，产物 evaluation.json 直接进 M2.2 适配器 | 1-2d | 粗结论期，最快 |
| (b) 方法论原生化 | L1 三件套（schema 契约 / grounding / 三态验证）写成 pi skills，生成-验证分离成两个 agent，验证 agent 不见生成上下文 | 3-5d | 需要生成过程感知 harness 上下文时 |
| (c) 完整移植 | Design/Grounding/Allocation 全部 port 成 pi subagent | 2-3 周 | 不推荐，维护两份管线 |

### M4 · 可复现层（~0.5 周）

- run manifest 版本化 + benchmark 快照版本化（1d）
- replay：session JSONL → 报告重建（1-2d）
- n≥3 重复编排 + 均值方差聚合（1d）

### M5 · 双轨一致性（0.5d）

MCP server 是两轨共用资产；canonical envelope / interface-spec 的契约同步（memory-bench Phase 0 产物直接沿用）。

## 3. 总量与节奏

| 里程碑 | 内容 | 累计 |
|---|---|---|
| **MVP** | M1.1+M1.2 + M2.1(a) + 一个 benchmark 族跑通 free-call | ~2 周 |
| **+生成植入** | M3(a) 子进程接入 | +2d |
| **+严格性** | M1.3 注入落盘 + M1.4 占位 + M4 全部 + M3(b) 原生 L1 skills | +1.5 周 |

**进展（2026-08-18 晚）**：repo 已建 `~/Documents/repo/pi-bench-harness`（决策点 1 落地：独立 repo，不 fork pi，消费 npm 包 0.84.2）。✅ M1.1 MCP 桥已移植（实例化 + probeArm 臂校验）；✅ E1 manifest TS 类型；✅ 冒烟通过（桥 → memory-bench mock server 六工具契约 → Pi customTools 映射 → 直调 execute）。下一个关键路径：M2.1 pi evals 跑台接入。

**建议节奏**：等 memory-bench 粗结论为正再全速投入；但 M1.1（MCP 桥接）和 M2.1(a)（evals 跑通）可以提前垫——它们不依赖粗结论，且是 MVP 的关键路径。

## 4. 决策点（开工前要定）

1. **repo 形态**：新建独立 repo（如 `pi-bench-harness`），消费已发布的 `@earendil-works/pi-agent-core` / `pi-coding-agent` 包 + 从 Proma 移植 MCP 桥。**不 fork pi**（避免追 upstream churn），不做 pi 的 package（这是我们的私产）
2. **TS/Python 边界**：harness 在 TS（pi 生态），ingest/判分在 Python（复用 memory-bench），桥 = JSONL + subprocess
3. **ContextInjector 落点**：system prompt 变换 vs user message 组装——影响注入时序（每 turn vs 每 session），做 M1.3 前定
4. **evals 生态锁定**：vitest-evals 的 judge 断言够不够自家 benchmark 的判分；不够则 Python 判分侧补

## 5. 风险

| 风险 | 缓解 |
|---|---|
| pi 快速迭代 breaking change（它和 dsh 一样在活跃期） | 锁版本 + 只依赖 agent-core/ai 两个最稳定包 |
| MCP 桥从 electron 剥离比预期难 | Plan B：不用移植，直接用 `@modelcontextprotocol/sdk` 官方 client 重写桥（stdio 三行起 server，工作量类似） |
| free-call 臂方差大到测不出差异 | n≥3 + 按题型切片 + 效应量报告；必要时 forced/free 混合协议（强制首轮调用，后续自由） |
| vitest-evals 判分表达力不足 | 判分全部落 Python 侧，evals 只管跑和落盘 |

# Agent Memory 痛点-方法论-批评矩阵

> **定位**：覆盖 AgentOS L3 Memory/Context 层的 14 个记忆系统（9 论文 + 5 业界开源），回答四个问题：① 各自 address 什么痛点 ② 方法论是什么 ③ 方法论自身的痛点 ④ 用什么 benchmark / 谁值得部署对比。初版 2026-08-18，基于 speed-read 笔记 + 业界调研，未做全文精读，后续逐篇深化。

## 一、总矩阵（痛点 → 方法论 → 方法论自身的痛点）

| 系统 | address 的痛点 | 方法论（一句话） | 方法论自身的痛点 |
|---|---|---|---|
| **Mem0** | full-context 成本爆炸、RAG 噪声 | 两阶段 extraction→retrieval + 增量 ADD/UPDATE/DELETE | 写入每 turn 一次 LLM call；提取即有损（关键信息写入时丢失）；图记忆规模化退化；自评 LoCoMo 既当运动员又当裁判 |
| **MemGPT/Letta** | context 装不下、被动检索、agent 不能自学 | OS 虚拟内存隐喻 + self-editing memory blocks | agent 写错/垃圾堆积无治理；整套 runtime 侵入性强；core memory 天花板=context window；DMR 被 Zep 反超 |
| **Zep/Graphiti** | 事实随时间演化、多跳崩溃 | 时间感知 KG（episodic/semantic/community 三子图，边带双时间戳，invalidate 不删除） | 图构建全靠 LLM 抽取，写入成本最重（Mandol 主攻击面）；矛盾判断无统计置信（vs TEPA）；依赖 Neo4j 栈重 |
| **MemOS** | 异构记忆无统一管理 | MemCube 统一明文/激活/参数记忆 + MemScheduler 调度 | 分类学 > 调度理论；三种记忆统一编址的机制难题未解；LoCoMo 单点评测；工程成熟度 vs 论文叙事落差 |
| **A-MEM** | 固定 schema 无法应对开放经验 | Zettelkasten 笔记网络 + 动态链接 + memory evolution | 链接生成每条新记忆都要 LLM（token 约为 GAMER 2 倍）；演化无版本/撤销语义；k 跳检索噪声累积 |
| **GAMER** | inference-time scaling 无状态、LLM 蒸馏记忆太贵 | Action-Centric Graph + 双流 TD（Q⁺/Q⁻），记忆=计算优化信号非检索模块 | 只吃带奖励信号的任务轨迹（AgentBoard 类）；对无奖励的对话/个性化场景不适用；TD 价值估计对非平稳环境漂移未处理 |
| **Mandol** | 异构库组合碎片化 + 跨库 I/O 延迟 + RAG 噪声 | memory-native 单地址空间（SemanticMap+SemanticGraph+DuckDB）+ 全程无 LLM 定量检索 | 组件全是 IR 经典件（创新=组合）；单进程 in-memory 可扩展性未讨论；无 LLM 检索的表达力上限（被动检索，MRAgent Theorem 4.1 直接证伪其假设类） |
| **PlugMem** | 任务专用记忆不可迁移 / 任务通用记忆 knowledge sparsity | 命题/处方/情景三层知识图 + 抽象-具体交替多跳检索 + 推理压缩 | 三层图构建仍依赖 LLM 抽取（同 Mem0/Zep 成本病）；插件接口的跨 agent 适配实际未充分验证 |
| **TEPA** | append-only 记忆在 reversal 阶段比无记忆还差 | 显式生命周期状态机 + Beta-Bernoulli 后验 revoke，归档可审计 | conflict key 设计依赖先验正确性；revoke 阈值在低证据场景误杀；目前只在自建 reversal benchmark 验证 |
| **MemHarness** | 检索回放导致 negative transfer | Retrieve→Critique→Reconstruct→Act，RL(GRPO) 训 critique/reconstruct | critique 无 ground truth（RL 奖励信号设计绕弯）；重构每步都在线 LLM call，延迟叠加；与 MRAgent 同名"重构"但路线分裂（RL vs 在线推理），领域术语尚未收敛 |
| **MRAgent** | 检索是无状态一次性的 | Cue–Tag–Content 图上 LLM 驱动主动多步重构，Theorem 4.1 证明 active ⊋ passive | 图单调增长不做遗忘/更新（作者自认）；新旧记忆同等对待（无时效性）；遍历错误传播——一步选错 Tag 全路径偏 |
| **Σ-Mem** | MAS 中 peer 回答不可验证、一致可能是相关错误 | 存可靠性而非内容：谱方法在线更新 peer 能力/关系矩阵 | 只覆盖 MAS trust 维度，不做内容记忆（正交而非替代）；事后 correctness feedback 在开放任务难以获得 |
| **PAST-Bench** | "越用越好"真假不可归因 | trajectory 级评测 + persistence on/off 消融 + 机制证据分 | 非系统而是 benchmark；26 scenarios 规模尚小 |
| **Huang Survey** | 领域无统一地图 | 200+ 系统三维分类（Substrate × 认知机制 × Subject） | catalog 型：分类有余、批判不足，不评各方法失败模式 |

## 二、方法论路线聚类（识别"路线级痛点"）

> **六条路线及其路线级痛点**（跨系统共性，比单系统 limitation 更有攻击价值）

1. **LLM 抽取管线**（Mem0 / Zep / A-MEM / PlugMem）：写入即有损 + 写入成本线性增长 + 错误在图/网络里沉淀。→ 被 Mandol（无 LLM 定量）与 GAMER（免蒸馏）两面夹击。
2. **Self-editing / agentic 写入**（Letta / A-MEM evolution）：无治理生命周期，写权限失控；与"symbolic 治理必须随 neural 自主性 explicit 化"的 neural-harness 公式同构——**记忆写入是 agent 自主性最高的部位，却是治理最薄弱的部位**（这是我们能填的洞）。
3. **时间维度显式化**（Zep invalidate / TEPA revoke）：方向对，但矛盾判定要么靠 LLM 直觉要么靠统计先验，缺统一置信框架；归档语义（audit）刚起步。
4. **主动重构检索**（MRAgent / MemHarness）：表达力理论上限最高，但每查询多次 LLM call + 错误传播；两篇"重构"路线术语打架（在线推理 vs RL），说明范式未收敛。
5. **定量确定性检索**（Mandol）：延迟/成本最优，但被动检索假设类被 MRAgent 理论证伪——确定性与表达力是一对未解 trade-off。
6. **记忆=优化信号**（GAMER）：最反主流（记忆不是 context 而是 value function），但依赖奖励信号，对话/个性化场景不适用。

## 三、Benchmark 地图

| Benchmark | 测什么 | 谁在用 | 备注 |
|---|---|---|---|
| **LoCoMo** | 长对话 QA（单/多跳/时序/开放域） | Mem0（自建）、Zep、Mandol、MRAgent、PlugMem、A-MEM | 事实上的主战场，但各家口径互相反超（Mem0 vs Zep 打架） |
| **DMR**（Deep Memory Retrieval） | 对话事实检索准确率 | MemGPT 自建、Zep | MemGPT 自建自评，Zep 用它反超 MemGPT |
| **LongMemEval** | 长期记忆（跨 session） | Mandol、MRAgent | 相对更新、口径更严 |
| **AgentBoard**（AlfWorld/SciWorld/PDDL/Tool-Query） | agent 任务成功率 | GAMER | 带奖励信号的任务型，与对话型互补 |
| **PAST-Bench** | self-improvement 归因（trajectory 级） | Xue et al. | 新范式：消融+机制证据，2026-08 新出 |
| **TEPA 自建 reversal benchmark** | 记忆冲突/反转 | TEPA | 尚未成为公共基准 |

> **benchmark 生态批评**：对话型（LoCoMo/DMR/LongMemEval）与任务型（AgentBoard）**几乎不交叉**——没有基准同时测"对话记忆 + 任务记忆 + 记忆治理（reversal/audit）"。各家在自家主场刷分，跨路线不可比。

## 四、开源部署对比候选

| 优先级 | 系统 | 部署形态 | 选它的理由 |
|---|---|---|---|
| P0 | **Mem0** | `pip install mem0ai`，API 最简 | 最主流 baseline，所有论文都对它，结果可直接对表 |
| P0 | **Letta** | Docker 自托管，完整 runtime | 唯一"OS 形态"参照，与 AgentOS 概念正面对话（也是侵入性对照组） |
| P1 | **Graphiti（Zep 引擎）** | Python lib + Neo4j/FalkorDB | 图路线最强开源代表 |
| P1 | **MemOS** | `pip install mem-os` | 与 AgentOS L3 命名/概念重叠最大，必须辨析 + 对比 |
| P2 | **A-MEM** | pip，代码简洁 | 学界开源代表，GAMER/PlugMem 都拿它对表 |
| P2 | **Mandol** | [AgentCombo/Mandol](https://github.com/AgentCombo/Mandol) | 无 LLM 检索路线代表，延迟数据最全 |
| P2 | **MRAgent / MemHarness / GAMER** | 均开源 | 论文配套代码，深度对比用 |

## 五、待办

- [ ] 精读 MemHarness 与 PAST-Bench（与 intention/situated 概念最对齐）
- [ ] 部署 Mem0 + Letta 跑通 LoCoMo 评测，拿到第一手延迟/成本数据
- [ ] 补 ReasoningBank（Google，arXiv:2509.25140）入库——GAMER 对比对象之一
- [ ] 与樊嘉铭对齐：MemOS 命名冲突的对外口径

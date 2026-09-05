---
title: 跨系统 methodology 骨架（实证推导）
date: 2026-09-05
tags:
  - memory-bench
  - methodology-flow
  - skeleton
---

# 跨系统 methodology 骨架

> [!note] 这份文件回答一个问题
> 14 个记忆系统能不能塞进**同一套流程骨架**？如果能，骨架的阶段该怎么划？
> 结论：**能**，而且空格子本身就是分类学结果。推导过程见 §1，骨架见 §2，覆盖矩阵见 §3。

## 1. 推导方法（自下而上，不预设阶段名）

不从"入库/检索/索引/取回/注入/loop"这类现成词汇出发，而是先把每个系统**实际执行的操作**逐条列出来，再看哪些操作在跨系统层面反复出现。

- 14 个独立复核 agent 各自读完一个系统的论文全文 + 源码仓库 + 两份架构文档，产出**论文侧**与**代码侧**两条"操作步骤序列"，共 **28 条**（amem 额外一条 fixed 臂、mandol 额外一条 adapter 臂，共 30 条）。
- 每一步只允许贴一个 **primitive 标签**，标签取自一份 32 条的种子词表；实在没有匹配的才准新造，并须写明为什么现有标签会丢失信息。
- 14 个 agent 互不通信，因此"哪些步骤长得一样"是**独立复现**出来的，不是我事后归并的。

新登记的 primitive 共 **10 条**（种子 32 → 全表 42），每条的立项理由都指向一处会被现有标签抹掉的跨系统差异：

| 新标签 | 来自 | 不能并进现有标签的原因 |
|---|---|---|
| `P-NLPEXTRACT` | mem0 | 确定性 NLP 抽取（spaCy），零 LLM；并进 `P-EXTRACT` 会抹掉"这一步要不要花 LLM"这个论文↔代码最大差异维度 |
| `P-SELFCHECK` | graphiti | LLM 对自己刚产出的结果做复检并修补；输入是上一步 LLM 的输出而非原始素材。这正是 Zep 最大的一条 paper-only 分歧（`reflexion` 代码零命中） |
| `P-REVISE` | amem | 回溯改写已存记忆的语义字段，**增益型、非冲突触发**；Zep 的 `t_invalid`、mem0 的 UPDATE/DELETE 属 `P-CONFLICT`，A-Mem 的 evolution 不属 |
| `P-CAPTION` | graphmemix | 跨模态描述生成（图/视频→可检索文本视图）；是"写入侧要不要付生成式成本"的关键计费点 |
| `P-EDGEVERIFY` | graphmemix | 锚点条件下的**边级**增量价值验证，决策单元是 (anchor, candidate) 边、产物是带权可信边集；压成 `P-RERANK` 会丢掉冗余/冲突识别与边权→森林结构 |
| `P-UTILITY` | memharness | 基于下游任务反馈的非 LLM 条目级打分（命中/成败计数 + Laplace 平滑）；`P-META` 限定 LLM 标注、`P-EVICT` 只是删除动作 |
| `P-SUBSTR` | letta | 子串 / SQL `LIKE` 包含匹配，无词项权重、无相关性打分；`P-SPARSE` 特指 BM25，`P-SYMFILTER` 是叠加过滤而这里是**主召回通道** |
| `P-ACTSELECT` | transmem | 按确定性位置规则从**已算出的**隐状态里挑稀疏记忆槽；无 kv 结构、无编码前向、无组合优化、不落盘 |
| `P-SIDEINIT` | livemem | 副路参数构造与拷贝初始化（q/k/v 从主干拷贝、输出投影零初始化）；对所有"给冻结主干加副路"的系统可复用 |
| `P-TRANSMUTE` | memos | 同一记忆内容在 plaintext / activation / parameter 三种载体间迁移；`P-TRAIN` 只覆盖单向蒸馏。它恰恰是 MemOS 代码零实现的那块，用近似标签会把缺口掩盖掉 |

## 2. 骨架

### 2.1 顶层二分不是"写入/检索"

**30 条序列全部自发地在同一个位置断成两段**——包括三个 forward-pass 内部的系统（它们既没有"写入"也没有"检索"，agent 自己把断点命名成"离线训练 / 在线推理"）。

所以顶层二分的正确名字不是写入/检索，而是：

- **A · 形成期（query-independent）**——查询还不知道时就能做完的一切
- **B · 动员期（query-conditioned）**——必须等查询到达才能做的一切

这个命名是被数据逼出来的：Memory Decoder 的 `P-DENSE`（稠密检索）**发生在 A 段**（建 datastore 时自查询 top-K），推理时 datastore 和 Faiss 索引根本不加载。若把 `P-DENSE` 定义成"检索阶段"的标志，这个系统就无法归类。

### 2.2 十四个阶段

```
A · 形成期 (query-independent)
  A1 INTAKE       接住原始素材，划定系统边界
  A2 DISTILL      炼成记忆单元（改写/抽取/标注/描述/摘要）
  A3 ADMIT        准入与并轨（去重/冲突/回溯改写/自检/效用）
  A4 INDEX        建立可寻址性（向量/稀疏/边/datastore/ANN）
  A5 COMMIT       落到载体（文件/向量库/图库/权重 checkpoint）
  A6 INTERNALIZE  把记忆压进参数（梯度训练/副路嫁接）

B · 动员期 (query-conditioned)
  B1 CUE          查询侧线索准备（意图解析/查询编码/时间范围）
  B2 RECALL       首轮召回（稠密/BM25/符号过滤/子串）
  B3 EXPAND       关联扩展（图跳数/BFS/PPR 扩散）
  B4 APPRAISE     评估与排序（重排/融合/边验证/效用）
  B5 SELECT       定选（组合优化/阈值截断/配额）
  B6 DELIVER      交付给推理体  ← 唯一 14/14 全有
  B7 GENERATE     推理体产出
  B8 LOOP         回到 B1/B2（工具循环/多跳/重构）
```

### 2.3 阶段 → 允许的 primitive（画图时的硬约束）

| 阶段 | 允许出现的 primitive |
|---|---|
| A1 INTAKE | `P-INTAKE` |
| A2 DISTILL | `P-REWRITE` `P-EXTRACT` `P-NLPEXTRACT` `P-META` `P-CAPTION` `P-AGGREGATE` |
| A3 ADMIT | `P-DEDUP` `P-CONFLICT` `P-REVISE` `P-SELFCHECK` `P-UTILITY` `P-EVICT` |
| A4 INDEX | `P-EMBED` `P-SPARSE` `P-ANNINDEX` `P-LINK` `P-DATASTORE` `P-KNNDIST` |
| A5 COMMIT | `P-PERSIST` |
| A6 INTERNALIZE | `P-TRAIN` `P-SIDEINIT` `P-TRANSMUTE` |
| B1 CUE | `P-QUERYPARSE` `P-EMBED`(query) `P-CAPTION`(query) |
| B2 RECALL | `P-DENSE` `P-SPARSE` `P-SYMFILTER` `P-SUBSTR` |
| B3 EXPAND | `P-GRAPHEXPAND` `P-DIFFUSE` `P-LINK`(查询期建边) |
| B4 APPRAISE | `P-RERANK` `P-FUSE` `P-EDGEVERIFY` `P-UTILITY` |
| B5 SELECT | `P-SELECT` |
| B6 DELIVER | `P-ASSEMBLE`（文本） / `P-INJECT`（隐状态） / `P-INTERP`（输出分布） / `P-KVWINDOW`（激活） |
| B7 GENERATE | `P-GENERATE` `P-FROZENFWD` |
| B8 LOOP | `P-TOOLLOOP` |

> [!important] 跨系统一致性硬规则
> 同一 primitive 在**所有系统**的图里必须落在**同一个阶段泳道**、用**同一个节点形状与配色**、写**同一个标签词**。
> 例：BM25 只能是 B2 泳道里的 `Retrieval:BM25`，不允许某图写 `KeywordMatch`、某图并进"混合检索"一个框。
> 节点命名前缀与 classDef 沿用 `METHODOLOGY-FLOW-SPEC.md` §1/§3；本文件补充的是**它落在哪个阶段**。

## 3. 覆盖矩阵

格式 `论文侧|代码侧`。`✓` 有 / `◐` 有但退化或部分 / `~` 可选、默认关、或论文未展开 / `✗` 无。
差异格（两侧不同）就是该系统 divergence 图的骨干。

| 系统 | A1 | A2 | A3 | A4 | A5 | A6 | B1 | B2 | B3 | B4 | B5 | B6 | B7 | B8 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **AtomMem** | ✓\|✓ | ✓\|**◐** | ✓\|✓ | ✓\|✓ | ✓\|✓ | ✓\|**✗** | ✓\|✓ | ✓\|✓ | ✓\|**~** | ✓\|✓ | **✗**\|✓ | ✓\|✓ | ✓\|✓ | ✗\|✗ |
| **Mem0** | ✓\|✓ | ✓\|✓ | ✓\|**◐** | **~**\|✓ | ✓\|✓ | ✗\|✗ | **✗**\|✓ | ✓\|✓ | **~**\|**✗** | **✗**\|✓ | **✗**\|✓ | ✓\|✓ | ✓\|✓ | ✗\|✗ |
| **Zep/Graphiti** | ✓\|✓ | ✓\|✓ | ✓\|✓ | ✓\|✓ | ✓\|✓ | ✗\|✗ | **✗**\|✓ | ✓\|✓ | ✓\|✓ | ✓\|✓ | **✗**\|✓ | ✓\|✓ | ✓\|✓ | ✗\|✗ |
| **MemOS** | ✓\|✓ | ✓\|✓ | ✓\|**~** | **~**\|✓ | ✓\|✓ | **~**\|**✗** | ✓\|✓ | ✓\|✓ | **~**\|✓ | ✓\|✓ | ✓\|✓ | ✓\|✓ | ✓\|✓ | ✗\|✗ |
| **A-MEM** | ✓\|✓ | ✓\|**✗** | ✓\|✓ | ✓\|**◐** | ✓\|✓ | ✗\|✗ | ✗\|✗ | ✓\|✓ | **~**\|**◐** | ✗\|✗ | **✗**\|✓ | ✓\|✓ | ✓\|✓ | ✗\|✗ |
| **Mandol** | ✓\|✓ | ✓\|✓ | ✓\|✓ | ✓\|✓ | ✓\|✓ | ✗\|✗ | ✓\|✓ | ✓\|✓ | ✓\|**~** | ✓\|✓ | ✓\|✓ | ✓\|✓ | ✓\|✓ | ✗\|✗ |
| **MRAgent** | ✓\|✓ | ✓\|✓ | **✗**\|**◐** | ✓\|✓ | ✓\|✓ | ✗\|✗ | ✓\|✓ | ✓\|✓ | ✓\|✓ | ✓\|**◐** | ✗\|✗ | ✓\|✓ | ✓\|✓ | ✓\|✓ |
| **GraphMemix** | ✓\|✓ | **~**\|**~** | ✗\|✗ | ✓\|✓ | **~**\|✓ | ✗\|✗ | ✓\|✓ | ✓\|✓ | ✓\|✓ | ✓\|✓ | ✓\|✓ | ✓\|✓ | ✓\|✓ | ✗\|✗ |
| **PlugMem** | ✓\|✓ | ✓\|✓ | ✓\|**◐** | ✓\|✓ | ✓\|✓ | ✗\|✗ | ✓\|✓ | ✓\|✓ | ✓\|✓ | ✓\|**◐** | ✗\|✗ | ✓\|✓ | ✓\|✓ | ✓\|**✗** |
| **MemHarness** | ✓\|✓ | ✓\|✓ | ✓\|✓ | ✓\|✓ | ✓\|✓ | ✓\|✓ | **~**\|**~** | ✓\|✓ | ✗\|✗ | ✓\|✓ | ✗\|✗ | ✓\|✓ | ✓\|✓ | ✓\|✓ |
| **Letta/MemGPT** | ✓\|✓ | ✓\|✓ | ✓\|✓ | ✓\|**◐** | ✓\|✓ | ✗\|✗ | ✓\|✓ | ✓\|**◐** | ✗\|✗ | ✗\|✗ | ✗\|✗ | ✓\|✓ | ✓\|✓ | ✓\|✓ |
| **TransMem** | **~**\|**~** | ✗\|✗ | ✗\|✗ | ✗\|✗ | ✓\|✓ | ✓\|✓ | ✗\|✗ | ✗\|✗ | ✗\|✗ | ✗\|✗ | ✗\|✗ | ✓\|✓ | ✓\|✓ | ✗\|✗ |
| **LiveMem** | **~**\|✓ | ✗\|✗ | ✗\|✗ | ✗\|✗ | ✓\|✓ | ✓\|✓ | ✗\|✗ | ✗\|✗ | ✗\|✗ | ✗\|✗ | ✗\|✗ | ✓\|✓ | ✓\|✓ | ✗\|✗ |
| **Memory Decoder** | ✓\|✓ | ✗\|✗ | ✗\|✗ | ✓\|✓ | ✓\|✓ | ✓\|✓ | ✗\|✗ | ✗\|✗ | ✗\|✗ | ✗\|✗ | ✗\|✗ | ✓\|✓ | ✓\|✓ | ✗\|✗ |

## 4. 从矩阵读出来的四条结论

**① B6 DELIVER 是唯一 14/14 全有的阶段。**
每个记忆系统都必须有一个时刻，记忆真的碰到推理体。而**碰法只有三种**，这三种恰好就是三个家族的定义：
- `P-ASSEMBLE`（拼进 prompt 文本）——11 个系统
- `P-INJECT`（改隐状态/激活）——TransMem（门控残差）、LiveMem（`o_main + o_side`）
- `P-INTERP`（改输出分布）——Memory Decoder（`p_final = (1-λ)p_θ + λp_ψ`）

跨系统对比真正咬合的地方在这里，不在"用没用 BM25"。

**② 参数化家族占据的是矩阵的补集，不是矩阵之外。**
TransMem / LiveMem / Memory Decoder 在 A2·A3·B1–B5 全空，同时是**唯二三个填了 A6 的**（另加 MemHarness）。这不是"塞不进骨架"，这是它们的机制本身：**把动员期的全部工作前移进了形成期**。Memory Decoder 最干净地演示了这一点——它的 `P-DENSE` 真实存在，只是发生在 A4 建 datastore 的时候，推理时一次检索都不做。

**③ A3 ADMIT 是论文↔代码退化最集中的一列。**
9 个系统的论文侧有 A3，代码侧有 **4 个退化**：Mem0（四操作 ADD/UPDATE/DELETE/NOOP → 实际 ADD-only + md5 精确去重）、PlugMem（→ 字符串级）、MemOS（→ 默认关）、MRAgent（论文根本没有，代码只有去重）。A-MEM 更极端，退化的是 A2：论文 Eq.2 的 note construction 在上游代码里**从未被调用过**（`analyze_content` 全仓零调用点）。
**"论文的方法论贡献往往落在准入与并轨这一步，而这一步最容易在实现里被省掉"** ——这是矩阵给出的最有价值的一条横向观察。

**④ B5 SELECT 与 B8 LOOP 是两条"少数派"列，而且互斥得很干净。**
填 B5 的 7 个系统靠一次性算出最优集合（GraphMemix 的 Kruskal 森林、Mandol 的级联仲裁、MemOS 的 MMR）；填 B8 的 4 个靠反复试（MRAgent 的 ≤8 轮工具循环、Letta 的心跳、PlugMem 的多跳、MemHarness 的重构）。**同时填两列的系统一个都没有。**"一次算准" vs "多次逼近"是检索侧的根本路线分歧。

## 5. 与 `METHODOLOGY-FLOW-SPEC.md` 的关系

那份 spec 定义的是**节点长什么样**（命名前缀、形状、配色、classDef），本文件定义的是**节点摆在哪**（十四个阶段泳道、以及每个阶段允许出现哪些 primitive）。两份配合使用，缺一不可：
- 只有 spec → 同一个 BM25 在两张图里样式一致，但可能一张画在召回、一张画在重排，横向仍不可比。
- 只有骨架 → 位置对齐了，但同一模块在不同图里可能叫不同名字。

spec §2 原本规定图内固定 `INGEST` / `RETRIEVE` 两个 subgraph，本文件把它细化为 A1–A6 / B1–B8 两组泳道；`INGEST ≡ A 段`、`RETRIEVE ≡ B 段`，向后兼容，已生成的 26 张 PNG 不作废，但重绘时按泳道对齐。

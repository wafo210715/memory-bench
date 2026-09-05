---
title: Methodology 流程图统一规范（canonical vocabulary）
date: 2026-09-05
tags:
  - memory-bench
  - methodology-flow
  - spec
---

# Methodology 流程图统一规范

> [!note] 目的
> 把 14 个记忆系统的 paper-architecture / code-architecture 转成**跨系统可对比**的 methodology 流程图。核心原则：**同一 module 在所有系统图中用同一节点形式与命名**（如 BM25 永远是同一样式的 `Retrieval:BM25` 节点）。

## 0. 双层交付

- **最终可视层**：调用 GPT Image 生成 `assets/<system>-paper-flow.png` / `assets/<system>-code-flow.png`，正文优先展示 PNG。
- **核验真源层**：保留 Mermaid/结构化流程，承载精确的 `§x.x / Eq.n / file.py:NNN` 引用，便于 diff、复核和后续重绘。
- 生图节点只写 canonical module 名和关键参数，避免把长引文、页码和代码行号塞入图片导致文字失真。
- 所有系统使用同一横向学术图模板、泳道布局、配色、形状与 legend；第一张获批样图作为后续生图的风格参考图。
- GPT Image 由父会话串行调用，子会话只交付已验证的流程结构与生图 prompt 素材，避免并发生成造成速率限制和样式漂移。

## 1. 统一 module 词汇表（canonical vocabulary）

每个系统的图只允许从这个表里选 module 名；遇到表外的，按同样命名格式自拟，并在该系统 `methodology-flow.md` 文末"新登记 module"一节列出，统一裁决后回填本表。

| 类别 | 命名格式 | 统一样式 | 已登记例子 |
|---|---|---|---|
| LLM 调用 | `LLM:<动词>` | 矩形·蓝 | `LLM:Extract` `LLM:Resolve` `LLM:Summarize` `LLM:Rewrite` `LLM:Answer` `LLM:RelGen` `LLM:Tag` `LLM:NER` `LLM:Judge` `LLM:SelfEdit` `LLM:Dedup` `LLM:TimeExtract` `LLM:Reflect` `LLM:Caption` `LLM:Verify` `LLM:VerifyEdge` `LLM:Evolve` `LLM:Query` `LLM:Act` `LLM:Predict` `LLM:Select` `LLM:Route` `LLM:Rerank` `LLM:MemReader` |
| 检索算法 | `Retrieval:<算法>` | 矩形·橙 | `Retrieval:Emb` `Retrieval:BM25` `Retrieval:Graph` `Retrieval:EntityLink` `Retrieval:FullScan` `Retrieval:KVProbe` `Retrieval:Recurrent` `Retrieval:Evidence` `Retrieval:Parametric` `Retrieval:EntityBoost` `Retrieval:SymFilter` `Retrieval:RuleFilter` `Retrieval:Rerank` `Retrieval:CueMatch` `Retrieval:Timeline` `Retrieval:kNN` `Retrieval:Substring` `Retrieval:FTS` `Retrieval:Unspecified` `Retrieval:SPLADE` |
| 传统 NLP/算法 | `NLP:<工具>` | 矩形·绿 | `NLP:NER` `NLP:Lemmatize` `NLP:HashDedup` `NLP:TextDedup` `NLP:EmbDedup` `NLP:PrefixDedup` `NLP:Cluster` `NLP:SchemaLink` `NLP:MutualKNN` |
| 融合/门控 | `Fusion:<方式>` | 矩形·黄 | `Fusion:Add` `Fusion:RRF` `Fusion:Gate` `Fusion:Interp` `Fusion:Concat` `Fusion:MMR` `Fusion:Union` `Fusion:Quota` `Fusion:Cascade` `Fusion:CrossEncoder` `Fusion:EpisodeMentions` `Fusion:NodeDistance` |
| 调度/路由 | `Sched:<名>` | 矩形·黄 | `Sched:MemScheduler` `Sched:Heartbeat` `Sched:Evict` `Sched:Batch` `Sched:BalancedSample` `Sched:UtilityPrune` `Sched:Lifecycle` `Sched:PathResolver` `Sched:TaskQueue` `Sched:QueueManager` `Sched:ToolLoop` `Sched:Sleeptime` |
| 存储层 | `Store:<载体>` | 圆柱·灰 | `Store:Vector` `Store:Graph` `Store:SQLite` `Store:Database` `Store:Entity` `Store:KVCache` `Store:Plaintext` `Store:Activation` `Store:Parametric` `Store:Hierarchy` `Store:RecurrentState` `Store:SparseDist` `Store:JSON` `Store:Git` |
| 可学习模块 | `Learn:<名>` | 矩形·紫 | `Learn:TransMem` `Learn:Decoder` `Learn:Recurrent` `Learn:FactExecutor` `Learn:GRPO` `Learn:Backbone` |
| 记忆形态转化 | `Convert:<A>→<B>` | 矩形·紫虚线 | `Convert:Plaintext→Activation` `Convert:Plaintext→Parametric` `Convert:Plaintext→Prompt`；若转化主体是 LLM 调用，优先用 `LLM:` 节点 + 转化注释 |
| 输入/输出 | `IO:<名>` | 圆角·淡紫 | `IO:Query` `IO:Answer` `IO:TurnPair` `IO:Session` `IO:Episode` `IO:Context` `IO:MultimodalArchive` `IO:TokenStream` `IO:Corpus` `IO:Stream` `IO:Trajectory` `IO:Observation` `IO:Action` `IO:TrajectoryReward` `IO:RetrievedMemory` `IO:Diagnostics` `IO:Evidence` `IO:MemCube` `IO:Structured` |
| 论文有/代码无 | 同名节点 | 红虚线 `dead` | paper 图实线、code 图里标"论文宣称但代码不存在" |
| 环境退化 | 节点保留+备注 | callout 警告 | 如 mem0 实测 chroma+无 spaCy 退化单通道 |

> [!important] 跨图一致性硬规则
> 同一 canonical module 在**所有系统**的图中必须用相同的前缀、形状与颜色（classDef 定义见下方模板），不允许同义异名（如某图写 `BM25Search` 另一图写 `KeywordMatch`——统一用 `Retrieval:BM25`）。

## 2. 布局约定

- 每系统两张图：**paper 视角**（节点标注 `§x.x / Eq.n / Fig.n`）与 **code 视角**（节点标注 `file.py:NNN / Phase N`）；amem/mandol 例外（仅 code 单图，基于实测版 ARCHITECTURE.md）
- 图内固定两个 subgraph：**写入路径 INGEST**（上）与 **检索路径 RETRIEVE**（下）；旁路模块（异步任务、训练期组件、离线构建）单独 subgraph；非"写入/检索"二分的系统（参数化记忆等）适配为"离线训练/在线推理"等对应路径，subgraph 命名与 module 前缀仍遵守词汇表
- 数据流恒为左→右：输入在左，存储在右

## 3. classDef 模板（所有图复制使用）

```text
classDef llm fill:#dbeafe,stroke:#2563eb,stroke-width:2px
classDef alg fill:#ffedd5,stroke:#ea580c,stroke-width:2px
classDef nlp fill:#ecfccb,stroke:#65a30d
classDef store fill:#e5e7eb,stroke:#6b7280
classDef io fill:#f3e8ff,stroke:#9333ea
classDef dead fill:#fee2e2,stroke:#dc2626,stroke-dasharray:5 5
classDef async fill:#f0fdf4,stroke:#16a34a,stroke-dasharray:4 3
classDef learn fill:#fae8ff,stroke:#a21caf
classDef sched fill:#fef9c3,stroke:#ca8a04
classDef fusion fill:#fef9c3,stroke:#ca8a04
classDef convert fill:#f3e8ff,stroke:#9333ea,stroke-dasharray:5 5
```

## 4. 输出文件模板（methodology-flow.md）

每个系统的 `servers/<name>/methodology-flow.md` 结构：

1. YAML frontmatter：`title` / `date` / `tags: [memory-bench, methodology-flow, <系统名>]`
2. 一段说明 callout：指向同目录的 paper/code-architecture.md 与 verification.md（如有），注明勘误以 verification 为准
3. `## Paper 视角`：先嵌入 `assets/<system>-paper-flow.png`，再附 Mermaid 核验真源；节点精确引用标 `§x.x / Eq.n / Fig.n`
4. `## Code 视角`：先嵌入 `assets/<system>-code-flow.png`，再附 Mermaid 核验真源；节点精确引用标 `file.py:NNN / Phase N`；论文有/代码无的模块用 `dead` 样式单独 subgraph；环境退化用 callout
5. `## 新登记 module`：列出词汇表外自拟的 module 名与理由（无则写"无"）
6. `## 不确定处`：画图中发现的文档缺口/矛盾（无则写"无"）
7. `## 生图 prompt 素材`：英文、短标签、明确节点/边/泳道；供父会话串行调用 GPT Image

## 5. verification.md 格式（补验证的 5 个系统）

letta / livemem / memharness / memorydecoder / transmem 的验证报告对齐 `servers/mem0/verification.md` 结构：头注（复核日期/材料源）→ `## 1. 总评`（可信度+问题分类）→ `## 2. 逐条核对表`（paper/code 分表，`✓` 属实 / `✗` 不实 / `◐` 部分属实 / `?` 无法核实，证据落到 txt 行号+换算页码或 `file.py:NNN`）→ 小计。

> [!warning] 验证纪律
> 逐条核对不是抽查——paper 文档的每一条可验证断言（机制/数字/引文/页码）都要过；code 文档的每个行号引用都要打开读上下文；否定式断言（"代码里没有 X"）必须用 grep/读码主动证伪后才能标 ✓。

## 6. 决策记录（2026-09-05 用户确认）

- 样例格式（mem0 双图）：按本规范批量做
- 验证：缺的 5 个全量深验（对齐已有 7 份深度）
- amem/mandol：只画 code 视角单图（不补 paper 版）
- 输出：每个 server 目录新增 methodology-flow.md，规范固定在本文件
- 可视化：最终图必须调用生图模型生成，Mermaid 只作为核验真源
- 协作：同时运行的子 Agent 不超过 7 个；已有会话完成后可按空槽补位

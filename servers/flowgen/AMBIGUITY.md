# 已标注的模糊项

> 由 `flowgen/check.py --ambiguity` 生成。

**这不是免责声明，是发现清单。** 分类学上卡住的地方，往往正是这篇论文
做了不常规的事、或实现与论文意图分岔的地方。默认把每一条当作线索来读。

两个现成例子：GraphMemix 的节点效用打分卡在 B4/B5 之间，是因为 PCSF 把
「打分」和「选集合」融进了同一个优化目标 —— 而那就是它论文的贡献；
Memory Decoder 的 `P-DENSE` 落在 A4 而非 B2，当时像归类异常，结果它直接
逼出了整个顶层二分的命名（SKELETON §2.1）。

| 系统 | 视图 | 阶段 | 母节点 | 节点 | 候选 prim | 跨阶段 | 说明 |
|---|---|---|---|---|---|---|---|
| graphiti | code | A3 | A-II 内容 | Retrieval:Recent — Recall last 10 episodes — | P-DEDUP \| P-ORCHESTRATE | 是 | 读近期历史为抽取提供上下文：它确实查了库存（故在 A3），但服务的是 A2 抽取而非准入判定 |
| letta | paper | B2 | B-II 候选 | Retrieval:Unspecified — recall_storage.searc | P-DENSE \| P-SPARSE | 是 | 论文只写 recall_storage.search()，未说明检索机制 |
| mem0 | code | A3 | A-II 内容 | Retrieval:Recent — Recall last 10 turns | P-DEDUP \| P-ORCHESTRATE | 是 | 读近期历史为抽取提供上下文：它确实查了库存（故在 A3），但服务的是 A2 抽取而非准入判定 |
| memos | code | B5 | B-III 收敛 | Fusion:MMR — dedup="mmr" default, over ×3 ca | P-SELECT \| P-FUSE | 是 | MMR 既可当重排器（graphiti 在 B4）也可当定选去重（MemOS 在 B5）；SKELETON §4④ 原文把 MemOS 的 MMR 归在 B5 |

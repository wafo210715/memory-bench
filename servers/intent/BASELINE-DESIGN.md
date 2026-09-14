---
title: "意图系统 Robust Baseline v1 设计（全机制 + 全开关）"
date: 2026-09-07
tags:
  - intent-system
  - baseline
  - memory-bench
status: implementing
---

# 意图系统 Robust Baseline v1

> [!abstract] 策略（wafo 2026-09-07 02:26 定）
> ① 现在：按意图系统设计理念组装 **robust baseline**——所有机制全上，每个机制预埋开关；
> ② 用 LoCoMo 出**粗结论**（唯一全部对手都复现过的可比场）；
> ③ 之后消融：逐个关开关做归因，届时再定制适合意图系统的 benchmark。
> Robust ≠ 堆机制：被验尸的 14 个系统一半死于"装了不测"（mem0 混合检索死代码 / amem 演化坏实现 /
> mandol stage2 零贡献 / graphiti 时间字段读取端不用）。开关就是将来的归因闸门。

## 0. 两条硬约束（涉及判断，可否决）

1. **检索确定性**：效用记账（P-UTILITY）只记录不反馈——若反馈进打分，同一 query 的证据会随答题顺序漂移，破坏 n=3 方差纪律（r2n3 的 99.1–100% 证据一致性是可信度基石）。消融期单独开反馈档。
2. **A 档被动面**：查询期**零文本 LLM**；embedding 调用允许（mem0/rag/graphiti/amem_fixed 同口径）。Tier2 精读与 B8 循环属 agent 形态，留 `intent_tier2` 臂单列，不进 baseline 主表。

## 1. 构建期（每 session：2 次 LLM + 1 次 embedding 批调用）

| # | 机制 | 来源证据 | 实现 | 开关 |
|---|---|---|---|---|
| A2-1 | 蒸馏：英文四段式意图摘要 + 5–10 条自包含事实（三人称、代词消解、[YYYY-MM-DD] 绝对日期、名字数字照抄）+ keywords | mandol L0 消融 +18.9；mem0 日期规则；atommem 五规则 | 1 次 LLM，temp=0 | 常开（这是系统本体） |
| A2-2 | 自检：第二次 LLM 对照 transcript 修补摘要+事实（日期/人名/自包含性） | graphiti 论文有代码无（全领域空白）；loader 注明 glm 会补错年份 | 1 次 LLM；解析失败保留初稿 | `selfcheck` |
| A3-1 | 非破坏修订：entry 带 version/status/history；同 session 重灌归档旧版不覆盖 | 骨架结论③（领域集体逃掉）；memos item.py 结构；mandol 重灌销毁事故 | schema + 归档逻辑；LoCoMo 单灌不触发但路径存在 | 常开（结构） |
| A3-2 | 效用记账：per-session retrieval_count / last_used | memharness MemoryRecord | utility.json，检索后回写；**不反馈打分** | 记账常开 |
| A4-1 | 双索引：facts+摘要 embedding（embedding-3，与四个对手同口径）+ 关键词 token 集 | 0829 受控实验（关键词本语料强）+ 跨语言鲁棒需求 | 1 次批量 embeddings；向量存 sidecar | 向量常算，用途见 `dense` |
| A4-2 | 意图链：新 session 摘要向量与库内最相似 session 比对，cos≥0.60 挂链（存 sessionId 指针，不存位置——amem 验尸坑） | amem 理念 + 三坑绕行；意图粒子=设计第二层 | chains.json {prev, chainId}；增量构建 | `chains` |

## 2. 查询期（每 query：1 次 embedding，零文本 LLM）

| # | 机制 | 来源证据 | 实现 | 开关 |
|---|---|---|---|---|
| B1 | 线索：tokenize + query embedding | — | 失败重试 ×3 后降级纯关键词并记 note | — |
| B2 | 五路召回排名：facts-kw / facts-dense / summary-kw / summary-dense / raw-kw → **RRF(k=60)** | graphiti RRF；raw 不上 dense（0829：关键词召回 0.363 > 向量 0.314） | 每路 score>0 才进排名 | `dense`（关两路稠密） |
| B3 | 链扩展：入选 session 的链邻居以 0.5 折扣进候选，全局上限 +5 | mandol 检索层增益集中 multi-hop；atommem 邻居上限防噪 | prev + 反查 next | `expand` |
| B4 | MMR 去冗定选：候选池 2×top_k → λ=0.7，相似度用摘要向量 | memos MMR（B5 定选先例）；mandol λ_mmr=0.7 | 归一化 RRF 分后迭代选 | `mmr` |
| B5 | top_k 截断（600 char/envelope × 20 ≈ 12k 预算等效，不另做预算逻辑） | — | — | — |
| B6 | 时间线组装：score 决定入选、**时间升序决定顺序**；envelope = head + 意图概要 + 命中事实≤2 + 原文摘录；turn_range 落地；timestamp 用事实时间 | intent 原生立场；graphiti 错年反例 | 已实现（v2） | 常开 |
| B8 | 循环：OFF | Theorem 4.1 属 agent 形态 | `intent_tier2` 臂另跑 | — |

## 3. 数据 schema（.state/intent/scopes/<scope>/）

```text
sessions/<id>.jsonl        原文全留（不动）
session-intent.json        [{sessionId,title,startedAt,settledAt,abstract{4},keywords,facts[],version,status,history[]}]
vectors.json               {sessionId:{summary:[...],facts:[[...]]}}   # sidecar，快照随 scopes 目录整体走
chains.json                {sessionId:{prev,chainId}}
utility.json               {sessionId:{retrievals,last_used}}          # 记账不反馈
```

## 4. 评测口径与排期

- **验证轮（今晚）**：conv-26/30/49（63 session / 500 QA），n=3、top_k=20、glm-5.3 thinking-on、同判分器；对手锚点从已有 runs 切片（mandol 74.0 / mem0 / amem_fixed / rag / graphiti 同 conv 集）。
- **正式粗结论（明天）**：验证轮无异常 → 全量 10-conv 重灌重跑，与 r2n3 / mandol-full / amem-ab 三表交集口径并列。
- 成本：3-conv 构建 ≈ 0.4–0.6M token（126 次 LLM + 63 次 embedding）；全量 ≈ 1.8–2.6M。
- 诚实性声明沿用 r2n3 清单 + 一条新增：baseline 构建期 2 次 LLM/session（mem0 1 次、memos 1–3 次、graphiti 2+2×边），token 账本随 stats 上报。

## 5. 消融预埋（将来逐个关，不是今晚做）

`MEMBENCH_INTENT_ABLATE` 逗号开关：`selfcheck` / `dense` / `chains` / `expand` / `mmr`；
另有独立臂：`intent_facts`（纯事实库替身，意图层归因用）、`intent_tier2`（agent 形态）。
届时按"关一个测一轮、增量 < 2×CI 即回退"的闸门执行，并同步定制意图专属 benchmark（c2/t3/t3b）。

> [!failure] 别抄清单（验尸结论，照旧）
> mem0 死代码冲突消解 / graphiti 读取端不用的边失效 / amem 坏 evolution / mandol gold-category router / graphmemix gold 拟合校准。

---
title: "意图系统实验阶梯（预注册）：baseline v1 → 理想态"
date: 2026-09-07
tags:
  - intent-system
  - experiment-ladder
  - pre-registration
status: registered
---

# 实验阶梯（预注册）

> [!abstract] 与 wafo 对齐的定义（2026-09-07 03:31）
> 本文件的"消融实验"= **加法阶梯**：从 baseline v1 出发，一步一个模块化变动，爬向设想的最佳状态，每步单一变量、可归因（mandol P1→P2→P3 同形态）。减法消融（关 baseline 内部开关）是 S8 的收尾包，不是主线。
> **目标**：multi-hop 与 temporal 都打败 mandol（3-conv 切片：55.0 / 81.1；当前 35.1 / 81.8）。
> **纪律**：每步 3-conv n=3（~45 分钟/轮），判停闸门 = 增量 > 2×CI 半宽之和（≈1.3pp）才并入主线，否则回退并记录。不着急，不为好看跳步。

## 0. S0 诊断结论（2026-09-07 03:40，已完成）

79 道题文本对齐的 cat1 共同题（rep0）：

| | acc | gold 含于证据 |
|---|---|---|
| ours | 36.7 | 40.5% |
| mem0 | 46.8 | 45.6% |
| mandol | 51.9 | 49.4% |

- 我们 50 错题：**34 道（68%）证据缺答案**（检索/展示层），16 道证据有但答错（转化层）
- mandol 净胜的 17 题：mandol 证据含答案 11/17，我们 7/17
- 典型失败模式：**枚举型 hop 题**（"What activities…"），query 词泛化 → envelope 的事实位（≤2）由**关键词门控**选择 → 答案词（camping/pottery）与 query 零重叠 → 事实在库里但从不上台面
- 判定：主要是 **B6 展示层选择 + B1 查询扩展**问题，不是 A2 构建质量问题（事实抽查合格）

## 1. 阶梯

| 步 | 变量（唯一） | 机制 | 假设（预注册） | 成本/ETA | 依赖 |
|---|---|---|---|---|---|
| **S4** | 交付粒度：session envelope → 裸 fact 条目（`intent_facts` 臂） | 同一份构建状态，mem0 形态归因臂 | 若 single-hop 显著 ↑ → 失分在包装形态；反哺 S5 | 0 实现（已就绪）；~30 min | 无 |
| **S1** | envelope v2：事实位 2→4、选择门控 kw→max(kw, dense cos≥0.30)、gist 仅在命中事实<2 时保留 | 攻 S0 的展示层门控 | cat1 +5~8、cat4 +4~6、cat2 不降 | ~30 min 码 + ~40 min 跑 | 无 |
| **S2** | 查询扩展：PRF 二跳（首轮 top-3 envelope 的高频实体词并入 token 集重打分；纯本地零 LLM、确定性） | 攻桥接实体/枚举词不在 query 里 | cat1 +6~12 | ~40 min 码 + ~40 min 跑 | S1 后 |
| **S3** | tokenize 修复：数字 token（`\d+`）进 query/facts/turns 三侧 | 审查 MAJOR-5；年份日期关键词失配 | cat2 +2~4（拉开 mandol 噪声边际）、cat4 +2~3 | ~15 min 码 + ~40 min 跑 | 任意 |
| **S5** | 混合粒度交付：top_k 预算 = session envelope + 裸 fact 条目按比例混合（如 8+12） | 由 S4 结果定比例；session 保时间线、fact 保密度 | cat4 +5~8 且 cat2 不降 | ~30 min 码 + ~40 min 跑 | S4 结果 |
| **S6** | 构建升级（唯一重灌步，打包）：facts 上限 10→15 + 枚举汇总型事实（"本 session 提到的爱好：X/Y"）+ 关系型事实（hop 导向）+ 每事实日期前缀 | 攻 containment 天花板（40.5→49+） | cat1 +5~8、整体 +2~4 | prompt ~30 min + 重灌 63 session ~25 min/~250k tok + 跑 40 min | S1/S2 落定后 |
| **S7** | 10-conv 全量确认轮 | 去掉检索层饱和（声明④），正式粗结论表 | 与 3-conv 趋势一致；检索机制首次真正被测 | 构建 ~2h/~1M tok + 答题挂夜 ~4h | S1-S6 主线定型 |
| **S8** | 减法消融包：全开 vs 逐关 selfcheck/dense/chains/expand/mmr | 防"装了不测"（mandol stage2 教训） | 预期 chains/expand 在 LoCoMo 无贡献（诚实预期） | 5 × ~45 min | S7 前后均可 |

**里程碑映射**：multi-hop 35.1 → S1(+5~8) → S2(+6~12) → S6(+5~8) ≈ 51~63 区间，目标 >55.0；temporal 81.8 → S3(+2~4) ≈ 84+，目标显著 >81.1。假设兑现不了就止于闸门，如实报。

## 2. 运行规约

- 每步独立 run-id（`intent-s1-3conv` …），`scripts/seed_progress.py` 复用共享 state 跳过重灌（S6 除外）
- 固定 conv-26/30/49、n=3、top_k=20、glm-5.3 thinking-on、同判分器；切片 `scripts/slice_anchors.py`
- 每步结果追加到 `wafo-base/.context/memory-bench-r2n3/ladder-log.md`（步名/主表行/vs 上一步增量/判停结论）
- 每步收尾自查：跨 rep 证据一致率、DENSE_FALLBACK/EMBED_FAIL 计数、429 丢失率
- 代码每步单独 commit（单变量可回溯）

## 3. 今晚自动执行序列（2026-09-07 凌晨）

S4（intent_facts，无码）→ S1（envelope v2，码已备）由 automation 接力跑完并记录 ladder-log；S2 起明天白天按闸门推进。

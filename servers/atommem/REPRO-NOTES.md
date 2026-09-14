---
title: AtomMem 复现口径与门禁记录
date: 2026-09-10
tags:
  - memory-bench
  - atommem
  - repro
---

# AtomMem 复现口径与门禁记录

> [!note] 这个文件是什么
> `servers/atommem/` 这条臂的工程记录：封装时每个分叉怎么判的、判据是什么、门禁停在哪一步、
> 开跑前要先知道什么。论文↔上游代码的对照在同目录 `paper-vs-code.md`，机制拆解在
> `methodology-flow.md`，契约在 `docs/interface-spec.md`；本文件只记这条臂的复现决策与验证证据。
> 上游 MINE-USTC/AtomMem @ `776f880` 全程只读，未做任何修改。

## 1. 口径决策表

前三条由用户 2026-09-10 直接指定，其余按 memory-system-analysis 的自主决策总则自行判定并在此留痕。

| # | 分叉 | 裁决 | 判据 |
|---|---|---|---|
| 1 | A1/A2 抽取用哪套 | 按论文 Figure A.1 五条规则重写提示词，模型用全 arm 统一的 glm-5.3 temp=0 | 用户定。上游跑分链路根本不抽事实（差异 1），仓库自带的那份提示词又丢了「第三人称改写」「视觉信息作主要来源」两条（差异 13） |
| 2 | envelope 放不放事件摘要 | 放，拼进对应 fact 的 text | 用户定。论文三处说事件摘要参与生成，上游算出来后在生成函数入口丢弃（差异 3） |
| 3 | embedding | 换 embedding-3（2048d），偏离论文与上游的 all-MiniLM-L6-v2（384d） | 用户定。与 mem0/graphiti/mandol/rag_baseline 同口径，排除嵌入强度这个跨臂变量。代价见 §4 阈值观测 |
| 4 | facts 与 profiles 的条数分配 | 共享 top_k 预算：profiles ≤5 先占位，facts 取剩余 | 自主。画像是论文的独立一路证据（Table 2 去掉它单跳 F1 从 56.66 掉到 50.91），不能砍；但额外追加会让本臂证据体量系统性高于其他臂。graphiti 三类混合同样塞在 top_k 内，照此先例 |
| 5 | 检索侧 people 硬交集过滤要不要加兜底 | 不加。归零时上报 `PEOPLE_FILTER_EMPTY`，不改判定 | 自主。见下方专节 |
| 6 | max_tokens | 沿用上游写死的 2000（代码原生）；仅当 thinking 切到非 low 档时提到 128k | 自主。同 amem 保留 max_tokens=1000 的理由；但思考与正式回复共用额度，高档位下 2000 必爆，故留防线并在 stats 留痕 |
| 7 | B7 答案生成 | 不在本臂内执行，`_generate_answer` 替换为空实现 | 论文 §3.5.3 把这一跳划在系统边界外，契约也要求 retrieve 只回证据 |

### 决策 5 的完整论证（唯一一处「明知会掉门禁也不改」的地方）

上游 `src/retrieval.py:284-288` 的主召回过滤：query 解析出具名人物时，`people` 不与之相交的 fact
一律被拒（含 `people` 为空的 fact），且没有任何回退。一旦 B1 把 query 里的非人名实体误判成人名，
召回直接归零。

不加兜底的理由，按优先级：

1. 论文 txt:233-235 明写主召回按人物和时间做符号过滤。加兜底属于「擅自改进论文设计」，
   落在 memory-system-analysis 的硬约束①之外。注意这与「论文主张而代码退化就按论文补齐」
   （决策 1、2 走的那条）方向相反：这里是代码比论文更严，不是代码没实现论文。
2. 风险面已量化，不足以污染结论。2026-09-10 对 LoCoMo 全库分层采样 200 题，只跑 B1 意图解析，
   统计 query 解析出的人名落在该 conv 说话人名单外的比例：1.0%（2/200），且两例都是对话中提到的
   第三方人物（Jean/John、Anthony），这些名字大概率本就出现在某些 fact 的 `people` 里，
   所以 1.0% 是上界。分题型：multi-hop 2.4%、open-domain 2.8%、temporal / single-hop / adversarial 均为 0%。
3. 端到端验证复核：conv-26 前两个 session、4 个真实 QA，`people_filter_empty` 探针
   evaluated=4 / fired=0。

已知的反向证据（记录在案，不改变裁决）：上游自身并不一致——图通道过滤
（`multichannel_graph.py:612-614`）与写入侧 `people_sets_compatible`（`fact_storage.py:15`）
都放行空集，只有主召回是严格交集。若将来要做消融，这是现成的一个消融项。

代偿措施：归零不得静默。retrieve 在 query 有具名人物且主召回为空时，`native_notes` 报
`PEOPLE_FILTER_EMPTY`，`stats().threshold_probes.people_filter_empty` 累计 evaluated / fired，
出分时可单独统计它吃掉了多少题。这是纯观测，不改任何判定。

## 2. 门禁状态（implement-check-run 三层）

### 第一层 机器门禁

| 检查 | 结果 |
|---|---|
| `python main.py smoke atommem` | 6/8。步骤 2、7 的 retrieve 返回 0 条 |
| `pytest` | 全绿，12 项无新增红（慢臂按设计 skip） |
| env / 解释器 | `main.py arms` 显示 atommem env 齐；主 venv 即可，无需独立 venv |
| stdio 通道 | 上游 print 已全部改道 stderr，重跑后 JSONRPC 解析错误 0 次 |

smoke 两步失败的归因：不是封装缺陷，是决策 5 那条上游机制在 smoke 样本上的必然结果。
smoke 用的是中文且无具名说话人的 3-turn 样本，抽出的 fact `people` 为空或为说话人本身，
而 query「帕丁森 猫」被 B1 解析成 `people=['Pattinson']`（猫名被当人名），于是全滤光。
实测三种样本对照：

| 样本 | fact.people | query.people | 召回 |
|---|---|---|---|
| smoke 原样本（中文、无具名） | `[]` | `['Pattinson']` | 0 |
| 中文 + 具名 | `['李明']` | `['帕丁森']` | 0 |
| LoCoMo（英文、具名） | `['Caroline']` | `['Caroline']` | 6-7 |

即根因是 B1 与 A3 两套提示词对「什么算人名」判断不一致，中文样本上暴露；
两套提示词都是上游的，未做修改。

> [!warning] 豁免声明
> 这两步按 MAJOR 处理并豁免，不按 CRITICAL。理由：契约链路本身已被证明完好——
> smoke 步骤 8（双 scope 隔离）里 scopeB 正常检索到内容，§3 的 LoCoMo 端到端验证
> 全部通过。启动正式 run 时须把本节连同 `PEOPLE_FILTER_EMPTY` 的逐题统计一并写进 run manifest。
> 附带记录：smoke 步骤 5 在步骤 2 为空时是空集比空集的 vacuous pass，证据强度实为 5/8；
> 真正的 restore 可复现性由 §3 在真实数据上验证。

### 第二层 对抗审查

2026-09-10 派 fable 5.1 子会话做只读对抗审查，产出 3 CRITICAL / 6 MAJOR / 15 MINOR。
三条 CRITICAL 全部已修并实证：

| # | 问题 | 修法与验证 |
|---|---|---|
| C1 | 封装把 ISO 日期传给只认 `on 8 May, 2023` 的上游 `parse_session_datetime`，匹配失败静默落到 `datetime.now()`，导致每条 fact 的 interaction_time 与每条 profile 的 valid_from 都变成跑批当天，连带破坏检索侧时间过滤与画像版本链 | 新增 `_to_native_session_time` 翻成上游格式（月名硬编码，不用受 locale 影响的 `%B`）。实测 `time=['2023-05-07','2023-05-08']` |
| C2 | `_pin_llm` 只钉了 4 个内部 LLMInterface 实例中的 1 个；冲突检测、事件归属与摘要、画像抽取与时间链三个实例跑在服务端默认推理深度，配合上游写死的 max_tokens=2000 会复现 amem 2026-08-30 的静默空回复事故 | 改为按 `get_aggregate_llm_statistics` 的同一份清单枚举，实测 pin 4/4，`stats().pin_targets` 上报 n/N |
| C3 | token 只读 `pipeline.llm`，构建期成本大头（冲突/事件/画像）全漏；`llm_calls` 用赋值导致一个进程灌多个 conversation 时被覆盖 | 改用 `get_aggregate_llm_statistics()` 前后差值 + 累加 |

同时修掉的 MAJOR / MINOR：探针口径（conflict 探针原本包在 `_detect_conflict` 上，统计的是
LLM 确认冲突数而非 0.6 门触发率，改包 `_llm_detect_conflict`；`max_sim` 原本在全量 existing_facts
上取而非上游的候选集，会出现 max>0.95 但 fired=0 的误读；补上画像 0.55 探针；reset 时归零）、
`PARTIAL_INGEST` 语义反转（原本把「LLM 合法判定无高价值事实」报成灌入失败，把「部分 turn 抽取
失败」漏报，现拆成 `PARTIAL_INGEST` 与 `NO_FACTS`）、envelope timestamp 改用会话日期与
mem0/rag_baseline 对齐、thinking 三态映射对齐 mem0、`TRUNCATED_BELOW_TOP_K` 改用 `SEED_LIMITED`
（§7 把前者留给阈值截断）、extractor 的解析分支不可达与 api_fail/parse_fail 混计、
memory_id 加 scope 前缀、会话日期表 key 与 dia_id 前缀统一。

### 第三层 口径核查

- thinking：4/4 实例钉住 `thinking={"type":"enabled"} + reasoning_effort=low`，与 mem0/graphiti/amem 同款；
  35 turns 抽取 parse_fail=0 / api_fail=0，无 thinking 吃满额度的迹象。
- 同口径对比：本臂 retrieve 每次有 1 次 B1 意图解析 LLM 调用，不能与 mem0/graphiti/mandol/rag_baseline
  的零 LLM 检索面并列做成本对比。已在 `docs/interface-spec.md` §7 新增三栏分类；它只读 query
  不读记忆内容，因此不构成 intent Tier2 那种 active retrieval，不必从主表拿出。
- 公平性偏离项：embedding-3、按论文补齐的抽取器、max_tokens 三项已登记进 spec §7。
- 统一配置：top_k=20、temp=0 未动；n=3 属跑分参数，由 runner 控制。
- 配置漂移：本臂为新增，无历史 run 可比，无漂移。

## 3. 端到端验证（真实 benchmark 数据，走完整 MCP 工具链）

2026-09-10，conv-26 前 2 个 session（35 turns），top_k=20：

- 契约合规：每题返回 20 条且不超 top_k，envelope 无超长（≤600 字符）、无缺字段。
- 口径 2 生效：fact 的 text 带上了 `｜ 事件: …` 的事件摘要。
- 口径 4 生效：cat3 那题返回 16 facts + 4 profiles，`native_notes` 报 `PROFILE_SLOTS=4`。
- C1 修复生效：envelope 时间戳为 `2023-05-08` / `2023-05-25` 等会话日期，非跑批当天。
- 图游走开启：`graph=on; score_kind=ppr`。
- snapshot/restore 在真实数据上 id 集合完全一致（20 条对 20 条），非空集比空集。
- 抽取质量抽样：论文规则 2 的相对时间消解确实生效，原文 `yesterday` 被写成
  `Caroline attended an LGBTQ support group on 2023-05-07`。

## 4. 开跑前须知

### 4.1 阈值探针基线（embedding-3 尺度漂移的观测起点）

35 turns / 46 facts 上的实测，作为后续判断漂移的对照基线：

| 探针 | evaluated | fired | max top-1 | mean top-1 | ≥0.90 | ≥0.95 |
|---|---|---|---|---|---|---|
| duplicate_0.95 | 46 | 2 | 0.9965 | 0.7616 | 5 | 2 |
| conflict_0.6 | 19 | 0 | — | — | 0 | 0 |
| profile_0.55 | 10 | 3 | 0.6774 | 0.5362 | 0 | 0 |
| people_filter_empty | 4 | 0 | — | — | — | — |

值得盯的一项：画像候选的 top-1 相似度均值 0.5362、最大 0.6774，几乎贴着 0.55 这条免 LLM 门槛线，
10 次里只有 3 次过门。这个阈值原本是在 384d MiniLM 尺度上调的，换到 2048d 后落在了分布的正中间，
意味着画像层的行为对该阈值高度敏感。若后续发现画像质量异常，先查这一项。

> [!important] 全量实测已证实这条预警（2026-09-11，atommem-p1-3conv，1297 turns / 1815 memories）
> 上面那张是 35 turns 的小样本基线，以下是同口径的全量对照：
>
> | 探针 | evaluated | fired | 触发率 | mean top-1 | 基线 mean top-1 | 漂移 |
> |---|---|---|---|---|---|---|
> | duplicate_0.95 | 1912 | 63 | 3.29% | 0.7941 | 0.7616 | +0.033 |
> | conflict_0.6 | 1056 | 34 | 3.22% | — | — | — |
> | profile_0.55 | 443 | 345 | 77.88% | 0.6290 | 0.5362 | +0.093 |
> | people_filter_empty | 1485 | 7 | 0.47% | — | — | — |
>
> 去重探针基本稳定（1912 次评估下属小幅波动）。画像阈值则按预警方向明确漂了：
> 过门率从小样本的 30%（3/10）升到 77.88%（345/443），mean top-1 从 0.5362 升到 0.6290。
> 0.55 这条线在 embedding-3 尺度下已明显偏向“放行”，画像通路的实际启用频率远高于小样本观察
> （与 24.40% 的题动用 PROFILE_SLOTS 互相一致）。本 run 未做消融，无法判断该漂移对分数是正向还是负向；
> 要回答需要在同一 run 内跑 profile 阈值的对照臂。
> 另：`people_filter_empty` 的 evaluated=1485 与实际 1500 次 retrieve 差 15 次，探针覆盖面未覆盖全部路径，
> 下次复现时需核实这条旁路。

### 4.2 成本与时长（外推，非实测）

35 turns 实测：186 次 LLM 调用、109187 internal_llm token、572 秒。
按 LoCoMo 全量 5882 turns 线性外推约 18.4M internal_llm token——与论文 Table 1 报告的
AtomMem 21357.06K（21.4M）量级吻合，可作为复现忠实度的一个旁证。

> [!warning] 下面这段“按超线性估时长”的判断已被全量实测推翻（2026-09-11），保留原文仅作沿革记录
> 实测（atommem-p1-3conv，1297 turns）：**墓钟维度未出现超线性**。三个 conv 的内部速率依次为
> 24.4 / 26.5→21.9 / 15.3 秒per-turn，**最大的 conv-49（509 turns）反而全程最快**（两个独立区间重复验证）。
> 全量 ingest 均值 20.1 秒/turn，总耗时 7 小时 14 分，**低于原估 9-14 小时的下界**。
> `MEMBENCH_INGEST_TIMEOUT`（1800 秒）全程未逼近：最长的 33-turn session 约 505 秒完成。
>
> 但 per-turn token 消耗确实在涨：35 turns 时 3120 tok/turn，1297 turns 时 5304 tok/turn，增长 1.70x。
> 即**计算量随库增长在上升，墓钟没有同步上升**。原因未核实（可能涉及系统级 warmup、服务端夜间负载、
> embedding 缓存命中率随库增大而提高、或三个 conv 的单 turn 文本长度差异），不给因果结论。
> 全量 token 外推也随之从 18.4M 上修到约 31.2M（高于论文 Table 1 的 21.4M 约 46%）；
> 但线性外推的前提已被证伪，这个数只能当量级参考。

（原判断，已被上方实测推翻）时长要按超线性估，不能线性外推：s01（18 turns）216 秒即 12 秒/turn，s02（17 turns）355 秒即
21 秒/turn，随库增长明显变慢——去重、冲突检测、事件归属都要在全量 facts 上遍历并调 LLM。
全量 ingest 属于「十几到几十小时」量级的过夜作业，排期时按此准备，并注意
`MEMBENCH_INGEST_TIMEOUT` 默认 1800 秒是单次 add_conversation 的上限，长 conversation 后段的
session 可能逼近它。

### 4.3 I/O 放大

上游 `utils.save_json` 用 `indent=2`，2048d 向量下每个 float 独占一行，每条 fact 入库触发 2-3 次
`facts_<conv>.json` 全量重写。这是上游行为，未改动；配合 harness 逐 session 的 snapshot 目录拷贝，
磁盘写入量可观，跑前确认 `.state/` 所在盘有余量。

### 4.4 首跑结果（atommem-p1-3conv，2026-09-11）

完整报告：`~/Documents/wafo-base/.context/memory-bench-atommem/report-2026-09-11.md`。
主表 ALL(1-4) = 62.5 ± 1.3（multi-hop 41.8 / temporal 69.7 / open-domain 44.2 / single-hop 70.2），
cat5 adversarial 7.5 ± 1.0 单列。1496/1500 答案（1500 evidence），差的 4 题全部是 Phase B 的 429 退避耗尽，
账目可解释；judge 解析失败与 PARSE_ERROR 均为 0，无 failures.jsonl，无进程重启。

一个超出预期的观测：**本臂的检索层不确定**——500 题中仅 211 题（42.2%）的 evidence 跨 rep 逐字相同。
根因是口径 4 里那次 B1 查询意图解析 LLM 调用（temp=0 仍非确定），解析出的 people/keywords/time 一变，
符号过滤与召回就变。这使 atommem 成为目前唯一检索层非确定的臂（mem0/graphiti/rag_baseline 都是纯向量或图运算），
跨 rep σ 里同时含检索噪声与答题噪声，两者未分离。做方差分析时不能套用“检索确定性 → σ 只含答题噪声”那套推论。

PEOPLE_FILTER_EMPTY 实测 0.47%（7/1500 行）、去重 0.60%（3/500 题），低于跑前 200 题采样的 ~1% 预期，
远低于 5% 复核门槛——决策 5（不加兑底、只留痕）经全量验证成立。且全 run 的召回归零事件与它 100% 重合，
没有第二条归零路径。三道命中题中有一道（conv-26/q35）只在 3 个 rep 里的 1 个触发，又一次印证了检索非确定性。

## 5. 尚未做的

- 10conv 全量跑未启动；臂间对比未做（跨 run 不可横比，要对比必须同 run 内加跑对照臂）。
- Table 2 的三个消融变体在上游没有对应开关（差异 5），本臂同样跑不出来；
  若要做消融，决策 5 记录的「主召回 people 过滤」是一个现成且自然的消融项。
- Figure A.1 规则 4（多模态整合）在本口径下无输入：LoCoMo 原始数据有 blip_caption / img_url，
  但 `loaders/locomo.py:98` 只交 {role, content, timestamp}，图像描述在 loader 层已丢弃。
- 中文语料适用性存疑：决策 5 的三样本对照显示，中文样本上 B1 与 A3 对人名的判断不一致会让召回归零。
  若将来要用自家 Proma QA 中文语料跑这条臂，必须先复核这一点。

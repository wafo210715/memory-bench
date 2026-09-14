---
title: Mandol Paper ↔ Code 对照
date: 2026-09-07
tags:
  - memory-bench
  - paper-vs-code
  - mandol
---

# Mandol Paper ↔ Code 对照

> [!note] 口径
> paper = arXiv:2606.29778v1（Zhang et al. 2026），正文行号指 `literature/papers/Zhang-et-al-2026-Mandol-….txt`
> 上游代码 = `AgentCombo/Mandol` @ `6d7af4f`（2026-08-02 快照），以产生论文数字的 `run_reproduction_suite.sh` 路径为准
> memory-bench 臂 = `memory-bench` @ `947c136`，`servers/mandol/{server.py,towers/*.py}`
> 事实依据以同目录 `verification.md` 为准（104 条逐条判定，含 5 条证伪）。`ARCHITECTURE.md` 已于 2026-09-05 按该报告修正。
> 论文与上游快照几乎同期（相隔数月），所以两者的差异默认不按「三年演进」解释；论文声明而实现里零 footprint 的，判为文档脱节。
> 第三列三态并列：P1 = 只灌原始对话、单路稠密检索；P2 = 加三塔离线构建、检索仍单路；P3 = 三塔检索 + 级联剪枝。三态共用的写法不分段。
> 空格 = 该阶段在这一侧不存在。「默认死」= 代码完整、逻辑齐全，但默认配置不可达，能指到关掉它的那行。

## A 段 · 形成期（query-independent）

| 阶段 | Paper | 上游代码 | memory-bench 臂 |
|---|---|---|---|
| A1 intake | 对话先切 chunk，再抽成细粒度记忆单元，每条带内容、说话人、时间三类信息（§4 txt:735-740）。新对话到达只更新受影响的单元与边，不重建整个空间（txt:758-762） | 离线三条 pipeline 直接读数据集的 session 文件，没有切分这一步；在线接口逐条收单元，只服务于论文的 Add 延迟实验（`semantic_graph.py:376-382`） | 每 turn 建一个单元，uid 为 `{session}#{i}`，正文存 "role: content"（`server.py:221-229`）。P2/P3 在建塔前把已入库单元再解析一遍，正则拆出说话人和日期，短于 15 字符的丢弃（`hierarchical.py:71-103`） |
| A2 distill | 四类记忆源并行抽取：情节事件链、实体图、偏好演化链，都交给 LLM 聚合（§3.1.2/§4 txt:283-289,747-758）。另有一步会话级上下文增强，给短句补 `[Time \| Topic]` 前缀（txt:292-299）。记忆空间按 session/task/topic 划分（§3.1.1 txt:256-260） | 改写实为 God Mode：每条 message 都重发整段 transcript，让 LLM 做指代消解和绝对时间换算（`step1_generate_l0_graph.py:29,568-611`，max_tokens=250）。抽象分两级，L1 每 session 抽结构化 JSON、L2 每 conv 全局聚合。情节与实体各走一条独立 pipeline。偏好类不建，LoCoMo 的类型表只选 STRUCTURED（`hierarchical_prompts.py:35-38`） | P1 无此步。P2/P3 复刻上游五条 LLM 链：L0 逐 turn 改写、L1 每 session、L2 每 conv、情节事实每 session、实体每 session 外加两轮关系抽取（`hierarchical.py` / `episodic.py` / `kg.py`）。构建温度压到 0（上游 0.1），模型统一 glm-5.3。全量 10 conv 共 8,071 次调用、1,111 万输入 token |
| A3 admit | 偏好的状态更新边即状态版本化（§3.1.2 txt:285-288）。没有任何去重步骤 | 两条线各有一次「聚类 + 逐簇 LLM 合并」：情节事实用 DBSCAN（eps=0.25）后按信息合并/频次计数/状态演化三种模式合并；实体按相似度 0.85 归并（`step2_deduplicate_and_enhance.py`；`step1_locomo_entity_extractor.py:483-500,618-667`） | P1 无此步。P2/P3 同构复刻，情节用 MiniLM+DBSCAN、实体用层次聚类阈值 0.85，簇内元素少于 2 个就不调 LLM（`episodic.py:76-150`；`kg.py:114-157`） |
| A4 index | 每条单元编码成统一语义向量（§3.1.1 txt:250-254），同时建倒排、稠密、稀疏三套索引（§3.2 txt:411-417）。结构边由规则解析产生，覆盖时序、实体指代、状态更新三类，明确不用 LLM（txt:262-266）。抽象节点回指基础单元（txt:289-292） | 载入时把检索正文换成改写后的文本、原文另存（`step4:360,367`）；FAISS、BM25、SPLADE 随写增量更新（`semantic_map.py:1217-1246`）。实体与关系进同一张统一图（`build_unified_graph.py`），建边缺任一端时返回 False 而不抛异常（`semantic_graph.py:646,649`） | 向量换成云端 embedding-3、2048 维（`server.py:187-193`），SPLADE 稀疏编码默认开。P2/P3 多三件事：用改写文本重新嵌入并覆盖原正文（`load.py:34-69`）、把 L1/L2 的 JSON 展平成自然语句再入库（均值 1,228 字符，`load.py:124-178`）、给相邻 message 连时序边。实体关系抽了 5,208 条但 0 条落地，情节与实体两塔的溯源边同样 0 条 |
| A5 commit | 持久化到进程内 DuckDB，内存超阈值时按 LRU/LFU 驱逐冷单元，图里只留轻量引用，命中时回调载入（§3.2/§4 txt:790-802） | `save_graph`/`load_graph` 落 json、pkl、safetensors、faiss，负载存 rocksdict；关系换出支持 LRU/LFU（`semantic_graph.py:1626,1852,1234-1251`） | 按 conversation 分图。P1 每 conv 一张；P2/P3 每 conv 三张（base、`__episodic`、`__kg`），10 conv 共 30 张（`orchestrator.py:71,80`）。每 conv 写一个 `.done.json` 做断点续跑。快照是整目录拷贝，恢复先删后拷、全量替换不合并（`common/base.py:22-36`） |
| A6 internalize | | | |

## B 段 · 动员期（query-conditioned）

| 阶段 | Paper | 上游代码 | memory-bench 臂 |
|---|---|---|---|
| B1 cue | 轻量意图分类器从查询本身的特征（时间表达、实体提及）判断激活哪些记忆源、各分多少候选预算，明确不调 LLM（§3.3.1 txt:461-472） | 路由读的不是查询特征，而是数据集自带的问题类别标签（`locomo_triple_router.py:1177`）。查出来是一张静态表，论文最好成绩所用的 GPT-4.1-mini 那一档五类全部映到同一个配置，路由不产生任何差异（`locomo_tower_router.py:106-119`） | 不接路由，固定等价于上游的全塔配置；查询文本原样透传，不做改写（`server.py:259-263`） |
| B2 recall | BM25、SPLADE、稠密三路并行召回（§3.3.1 txt:472-476） | 三塔并行，每塔内部都走这三路：hierarchical 取 15 条并按 L0/L1/L2 分层检索，实体塔与情节塔各取 30 条（`locomo_triple_router.py:1938-1946,2018-2050`） | P1/P2 是单路稠密检索取 20 条，并按 conversation 空间做硬过滤（`server.py:281`）。该空间只挂 L0 单元，L1/L2 从未加入，候选集在打分之前就不含抽象层——实测 conv-26 空间 419 个 uid 全是 L0，P2 的 30,000 条证据 100% 来自 L0。P3 与上游同构，三塔并行取 15+30+30（`retrieve.py:275-279`） |
| B3 expand | 从排名靠前的单元沿图做选择性子图扩展，按边类型和预算剪枝，是论文给出的多跳证据补全机制（§3.3.1 txt:477-480） | 遍历接口存在，但产生论文数字的配置把 topk_graph 设为 0、实体关系开关设为假，调用被门控挡在外面，主复现路径一次也没执行（`locomo_tower_router.py:66-74`；`locomo_triple.py:3359`）。默认死 | |
| B4 appraise | 三路结果先用 RRF 融合（txt:476-477），再由轻量 cross-encoder 重排打分（txt:480-483） | 每塔内先 RRF 再重排；三塔合并后还有一次统一的 cross-encoder，对全部 75 条重新打分，然后按塔预筛——hierarchical 全保留、另两塔各取前 20，约 35 条进下一步（`locomo_triple_router_quantification.py:690,698-710`） | P1/P2 无此步。P3 每塔内部的 RRF 与重排与上游一致（重排精度从 bfloat16 改成 float32），但三塔结果直接拼成 75 条送进剪枝，没有跨塔重排也没有加权融合（`retrieve.py:282-289`，实测进入剪枝的候选数恒为 75） |
| B5 select | 三级级联。先在每个源内部按 `median − κ·MAD` 去噪，κ 取 2.5（Eq.1 txt:655-673）；再按仲裁分做跨源冲突消解，分数由相关度、时间衰减、来源可信度三项加权，来源权重 basic 1.0 / episodic 0.8 / semantic 0.6（Eq.2 txt:626-648）；最后在 token 预算内做 MMR 打包，λ 全文没给数值（Eq.3 txt:674-692） | 同样三级。MAD 系数脚本传 3.0 而不是论文写的 2.5；仲裁分权重硬编码为 0.5 相关度 + 0.3 塔可信度 + 0.2 时间衰减（720 小时指数），塔可信度沿用 1.0/0.8/0.6；MMR 的 token 上限按 section 传 1500/1800/2000，另有 5 种剪枝模式，其中一种再按数据集类别标签查参数表（`cascade_pruner.py:186,616-650`；`run_reproduction_suite.sh:354-358`） | P1/P2 无此步，直接取前 20。P3 三级都在：MAD 用 3.0（实测 97.3% 的查询一条都没剔）；跨塔冲突消解需要 `CASCADE_IDS_ON`，默认关，定稿脚本置 1（`retrieve.py:155`；`run_mandol_full.sh:29`）；MMR 的 λ 用 0.7，但 token 上限没传，退回类默认 4096，实测中位 2,682、98% 的查询超过脚本的 1500。最后按 uid 去重截断到 20 条 |
| B6 deliver | 选中集拼成紧凑上下文交给 backbone（§4 txt:786-789） | 按三塔分节组装完整答题 prompt，实体塔只放前 10 条，并把数据集的问题类别标签连同针对性提示一起写进 prompt（`locomo_triple_router.py:2147-2175`） | 输出统一 envelope，每条正文截到 600 字符、最多 20 条；P1/P2 标 `mandol_unit`，P3 标 `mandol_tritower`（`server.py:274,294-302`）。答题 prompt 由评测框架统一构造，不注入类别标签 |
| B7 generate | backbone 作答，论文把它划在系统边界之外（§5.1 txt:1040-1044） | backbone 作答后再由 LLM 判分 | 评测框架统一调用 backbone，全臂同一套 prompt（`bench/runner.py:270-305`） |
| B8 loop | | | |

> [!tip] A6 与 B8 三侧都空
> 论文明确记忆不进模型参数，检索全程不调 LLM，也没有查询期的工具循环（abstract txt:31-33、§1 txt:110-112、§3.3 txt:459）。上游与臂都照此实现，没有可填的格子。

> [!tip] B3 三侧状态各不相同，不是同一种空
> 论文把子图扩展列为多跳证据补全的关键机制；上游代码完整但被基准配置关掉（topk_graph=0）；臂根本没有这一步，而且实体图的 5,208 条关系一条也没落地，即使做遍历也无边可走。

## 差异清单

对比侧：`P↔U` = 论文 ↔ 上游代码，`U↔M` = 上游代码 ↔ memory-bench 臂。
末尾方括号回指 `verification.md`：`§6.x-XX` 是分歧清单的编号，`#NN` 是逐条核对表的条目号。

| # | 阶段 | 对比侧 | 差异 | 类型 | 重要度 |
|---|---|---|---|---|---|
| 1 | A2 | P↔U | 偏好类记忆从不构建。论文四处声明四类记忆源，代码的类型表在两个 benchmark 上都不选它 [§6.1-A5] | 能力损失 | 高 |
| 2 | A2 | P↔U | God Mode 逐句改写。论文只写了给短句加前缀的轻量增强，代码对每条 message 重发整段 transcript 做全局指代消解，成本量级完全不同 [§6.1-A13] | 纯加法 | 高 |
| 3 | A2 | U↔M | 构建侧温度：上游各 step 用 0.1（实体去重 0.05），臂强制 0 [§6.2-B6] | 设计演进 | 低 |
| 4 | A2 | U↔M | 构建侧模型：上游用 qwen3.5-plus-thinking / deepseek 系，臂统一 glm-5.3 [§6.2-B14] | 设计演进 | 中 |
| 5 | A2 | U↔M | 臂多一步 L1/L2 展平：把结构化 JSON 摊成自然语句再入库，限长 1200/2000，实测均值 1,228 字符。展平前那 20 个抽象单元从未进过 BM25 倒排 [§6.2-B9] | 纯加法 | 中 |
| 6 | A3 | P↔U | 写入期的 LLM 去重与合并整条线论文没有；代码在情节与实体两条线各有一次聚类加逐簇合并 [§6.1-A12] | 纯加法 | 中 |
| 7 | A1 / B2 | P↔U | Table 2 列出的三个核心 API 全仓库零出现：`quantitative_search`、`search_unit`、`build_memory_from_raw` [§6.1-A2] | 文档脱节 | 高 |
| 8 | A4 / B2 | P↔U | 论文说隐式语义边「查询时按需计算」，代码里没有任何隐式边实体，那句话描述的就是稠密与稀疏检索本身 [§6.1-A15] | 设计演进 | 低 |
| 9 | A4 | U↔M | 实体关系 5,208 条抽出来 0 条落地，四层错误叠加：候选清单漏 entity_id、载入读错键名、按名字反查 uid 全部 miss、跨会话结果键名不符 [§6.2-B4] | 能力损失 | 高 |
| 10 | A4 | U↔M | 溯源边 0 条。上游三塔同在一张统一图可以连边，臂分三张图，跨图建边静默返回 False，改存成 metadata 字段 [§6.2-B5]（成因见 #12） | 能力损失 | 高 |
| 11 | A4 | U↔M | 向量后端：论文与上游用 Qwen3-Embedding-0.6B 本地模型，臂用云端 embedding-3、2048 维 [§6.2-B13] | 设计演进 | 中 |
| 12 | A5 | U↔M | 图架构：上游按 sample 分图但三塔合入统一图，臂是 base / 情节 / 实体三张独立图 × 10 conv = 30 张 [§6.2-B15] | 设计演进 | 高 |
| 13 | A5 | P↔U | 论文三处声明的 DuckDB 持久化后端全仓库零命中，实际用的是 rocksdict [§6.1-A1] | 文档脱节 | 高 |
| 14 | A5 | U↔M | 臂多一层 conversation 粒度断点续跑（每 conv 一个 marker），上游 8 个 step 零 resume [§6.2-B8] | 纯加法 | 低 |
| 15 | B1 | P↔U | 路由输入换了：论文是从查询特征在线判断的意图分类器，代码直接读数据集自带的问题类别标签 [§6.1-A3] | 能力损失 | 高 |
| 16 | B1 | P↔U | 路由表在论文最好成绩那一档是恒等映射，五类全部指向同一配置，路由不产生任何差异 [§6.1-A4]（依赖 #15） | 能力损失 | 高 |
| 17 | B1 | U↔M | 臂完全不接路由，固定走全塔配置。副作用是免疫了类别标签泄漏 [§6.2-B10] | 设计演进 | 中 |
| 18 | B2 | U↔M | 臂多出 P1/P2 两个对照态，上游没有「只用单路稠密」这种形态；且该形态下抽象层被空间过滤结构性排除 [§6.2-B12] | 纯加法 | 高 |
| 19 | B3 | P↔U | 选择性子图扩展在主复现路径上是死代码，论文却把它列为多跳证据补全的关键机制 [§6.1-A6] | 能力损失 | 高 |
| 20 | B4 | U↔M | 臂缺二段统一重排与预筛：上游把 75 条合并后统一重打分再筛到约 35 条，臂把 75 条原样送进级联 [§6.2-B1] | 能力损失 | 高 |
| 21 | B4 | U↔M | 融合权重只存在于注释里：`retrieve.py:12` 的 docstring 列了 0.34/0.33/0.33，实现体中零使用点 [§6.2-B3] | 文档脱节 | 中 |
| 22 | B4 | U↔M | 重排精度：上游无条件用 bfloat16 且只分 cuda/cpu 两支，臂 monkeypatch 成 float32 [§6.2-B7] | 设计演进 | 低 |
| 23 | B5 | P↔U | Eq.(1) 的 κ：论文写 2.5，代码默认也是 2.5，但产生论文数字的脚本十四处全传 3.0 [§6.1-A7] | 设计演进 | 中 |
| 24 | B5 | P↔U | Eq.(3) 的 λ 论文全文没给数值；代码默认 0.6、脚本传 0.7 [§6.1-A8] | 纯加法 | 中 |
| 25 | B5 | P↔U | Eq.(2) 的三个权重论文只给了符号；代码硬编码 0.5 / 0.3 / 0.2 [§6.1-A9] | 纯加法 | 中 |
| 26 | B5 | P↔U | 论文没有「剪枝模式」这一维；代码有 5 种，脚本对同一 backbone 跑了其中四种，token 上限各不相同 [§6.1-A10] | 纯加法 | 中 |
| 27 | B5 | P↔U | 来源可信度的三档对象换了：论文是 basic/episodic/semantic，代码是三塔，而 hierarchical 塔把 L0 基础层和 L1/L2 抽象层混在同一档 1.0 里 [§6.1-A11] | 设计演进 | 中 |
| 28 | B5 | U↔M | token 预算：脚本传 1500/1800/2000，臂没传，退回类默认 4096，实测 98% 的查询超过 1500 [§6.2-B2] | 设计演进 | 中 |
| 29 | B5 | U↔M | 跨塔冲突消解在臂的默认配置下不可达：`CASCADE_IDS_ON` 默认关，关时只有实体塔带 entity_ids，凑不出跨塔同 id。定稿脚本置 1，故定稿数字不受影响 [#65] | 能力损失 | 中 |
| 30 | B6 | P↔U | 答题 prompt 注入数据集自带的问题类别标签及针对性提示，论文全文未提 [§6.1-A14] | 纯加法 | 高 |
| 31 | B6 | U↔M | 输出形态：上游产出三塔分节的完整答题 prompt 并注入类别标签，臂产出扁平去重的 20 条 envelope，prompt 由评测框架统一构造 [§6.2-B11] | 设计演进 | 中 |

## 重点差异详述

只展开重要度为「高」的条目。#15/#16、#10/#12、#7/#13 三组各自是同一件事的两面，合并成一条讲。

### 论文声明在实现里零 footprint（#13 + #7）

论文 §3.2、§4 与 Table 1 三处声明用进程内 DuckDB 做持久化后端（txt:220,437-439,797-801），
整个上游仓库（含 pyproject、docs、website，排除 lockfile）grep `duckdb` 零命中，
实际嵌入式存储是 `rocksdict==0.3.29`（`pyproject.toml:53`，`storage/rocksdb_payload_store.py`）。
Table 2 列出的三个核心 API 同样全仓库零出现（txt:706-716）；存在的是 `traverse_explicit_nodes`
（`semantic_graph.py:1337`）、`traverse_implicit_nodes`（`:1434`）、`add_relationship`（`:610`）、`save_graph`（`:1626`）。
论文与代码快照相隔数月，不适用「演进」的解释——读者照 Table 1/2 去仓库里找会一无所获。

### 路由从在线判断退化成读答案标签（#15 + #16）

论文 §3.3.1 说轻量意图分类器从查询的时间表达和实体提及在线判断激活哪些源（txt:461-472）。
代码里这个分类器不存在：`locomo_triple_router.py:1177` 直接取 `qa_item["category"]`，
即 LoCoMo 数据集给每道题标注的类型，再查静态表（`locomo_tower_router.py:106-119`）。
而论文最好成绩（92.21%）所用的 GPT-4.1-mini 那一档，五个类别全部指向同一个 `_cfg_full()`，
路由实际上不做任何区分。所以这条既是能力缺失，也意味着论文声称的自适应路由对主结果没有贡献。

### 偏好类记忆四处声明，零处构建（#1）

论文在摘要、§3.1.2、§3.3.1 和 §4 四次把 emotional memory 列为四类记忆源之一，
描述为偏好演化链（txt:89,285-288,460,755-758）。代码里 `L1_EMOTIONAL_PROMPT` 和枚举都在
（`hierarchical_prompts.py:23,139`），但 `locomo_types()` 只返回 STRUCTURED（`:35-38`），
`longmemeval_types()` 返回 EPISODIC 和 KNOWLEDGE（`:40-43`）——两个 benchmark 都不建它。
论文的四类记忆源，实验里只有三类产生过证据。

### 多跳的关键机制被基准配置关掉（#19）

论文把选择性子图扩展列为跨会话补全证据的核心（§3.3.1 txt:477-480）。
`_cfg_full()` 把 `topk_graph` 设为 0 且 `use_entity_relation` 设为假（`locomo_tower_router.py:66-74`），
`locomo_triple.py:3359` 又把遍历开关定义成两者的合取，而 `--topk-graph` 默认就是 0——
脚本的四个 section 全部不走边，`entity_retriever.search()` 一次都没被调用。
这是默认死，不是缺失：代码完整，被配置摘除。论文 92.21% 里没有一分来自图遍历。

### God Mode 改写：论文没写，却是性能的主要来源（#2）

论文 §3.1.2 举的例子是给短句补 `[Time | Topic]` 前缀（txt:292-299），读起来像一次轻量标注。
代码的 `CONTEXTUAL_RETRIEVAL_PROMPT` 自称 God Mode，对每一条 message 都重发整段 session
transcript，让 LLM 做全局指代消解和绝对时间换算（`step1_generate_l0_graph.py:29,568-611`）。
本仓库实测这一步占构建调用数的 72.5%，而 P1→P2 的 +18.9 个点全部来自它——同一套单路稠密检索，
搜改写过的文本比搜原文高 19 个点，多跳从 23.6 翻到 48.5。论文最贵也最有效的一步没有被写进论文。

### 答题 prompt 注入数据集类别标签（#30）

论文反复强调检索全程不调 LLM（txt:31-33,110-112,459），这一点代码属实。
但上游自己的评测脚本在答题 prompt 里写进了 `QUESTION CATEGORY: {category} - {guidance}`
（`locomo_triple_router.py:2147-2149`），category 来自数据集标注（`:1177`）。
论文全文未提这件事。本仓库全臂统一不注入（`bench/runner.py:276`），因此臂的数字与论文的不可直接比。

### 实体关系抽了 5,208 条，落地 0 条（#9）

四层错误叠加：候选实体清单没输出 entity_id（`towers/kg.py:90-111`），而关系抽取 prompt 明确要求
用 ID 填 head/tail 并禁止用名字（`prompts.py:131`）；载入时读的键是 `source/subject/head`，
prompt 返回的是 `head_entity/tail_entity`（`towers/load.py:223-234`）；退化成按名字查 uid 后全部 miss；
跨会话那一支读 `relations`，prompt 返回的是 `cross_session_relations`（`kg.py:220`）。
marker 实证：conv-41 到 conv-50 的 `kg.edges` 全为 0。上游 `step2:381` 的候选清单是带 ID 的，
这是移植时丢的。

### 三张独立图与 0 条溯源边（#12 + #10）

臂把 base、情节、实体拆成三张图（`orchestrator.py:71,80`），上游是三塔合入一张统一图
（`build_unified_graph.py`）。后果是跨图建边时 `add_relationship` 找不到对端节点，
静默返回 False 而不抛异常（`semantic_graph.py:644-649`），情节与实体两塔的溯源边各 0 条，
只能把 `source_unit_uids` 降级存进 metadata。这是一条因果链：图架构的选择直接决定了
论文 §3.1.2 的抽象回指基础单元（txt:289-292）在臂里无法成立。

### 缺二段统一重排与预筛（#20）

上游把三塔的 75 条合并之后，用同一个 cross-encoder 对全部候选重新打分
（`locomo_triple_router_quantification.py:690`），再按塔预筛——hierarchical 全保留、另两塔各取前 20，
约 35 条进级联（`:698-710`）。臂直接把三塔结果拼接送入剪枝（`towers/retrieve.py:282-289`），
用的还是各塔内部的重排分，跨塔之间没有可比的统一标度。实测进入级联的候选数恒为 75，从未是 35。
这是臂与上游在检索侧最大的一处未复刻。

### P1/P2 对照态与抽象层的结构性排除（#18）

上游没有「只用单路稠密」这种形态，P1/P2 是本仓库为拆解增益来源专门造的。
其中 P2 有一个容易误判的现象：证据 100% 来自 L0。原因不是稠密检索把 L1/L2 排到了后面，
而是 `retrieve()` 传 `ms_names=[conv_id]` 做空间硬过滤（`server.py:281`），
而 L1/L2 只挂在 `hierarchical_memory:L1_Summary` 和 `:L2_Insight` 两个空间，从未加入 conv 自己的空间。
实测 conv-26 空间 419 个 uid 全是 L0、`child_space_names` 为空——FAISS 打分之前候选集里就没有抽象层
（`semantic_map.py:2186-2192,2539-2557`）。这是索引可见性问题，不是排序问题；
结论（+18.9 来自改写）不变，但改进方向完全不同。

## Benchmark

论文与本仓库都用 LoCoMo，年份也都是 2026，但口径不同，所以分开列、不并成一张表。

### 论文侧（arXiv:2606.29778v1，2026）

| 数据集 | 题型 | 指标 | Mandol 数字 | backbone |
|---|---|---|---|---|
| LoCoMo（10 段对话，1,986 题） | single-hop / multi-hop / temporal / open-domain | accuracy % | overall 89.48 | GPT-4o-mini |
| LoCoMo | 同上 | accuracy % | overall 92.21；分项 single 95.36 / multi 92.20 / temporal 87.85 / open 79.17，均 1.9k token | GPT-4.1-mini |
| LongMemEval（500 题） | 六类，含偏好、时间、多会话、知识更新 | accuracy % | overall 85.00 | GPT-4o-mini |
| LongMemEval | 同上 | accuracy % | overall 88.40 | GPT-4.1-mini |
| LoCoMo 检索延迟（Table 5，Server 部署） | — | ms | mean 82.2 / P90 88.5 / P99 94.8 | — |

论文的对比基线是 Mem0、MemU、MemOS、Zep、EverMemOS，其中 EverMemOS 标注为自行复现（txt:798）。

### 本仓库实测（memory-bench，2026-09-04，LoCoMo）

| 形态 | 3-conv ALL(1–4) | 全量 10-conv | 查询延迟中位 |
|---|---|---|---|
| P1 单路稠密、原始文本 | 52.4 | | 239 ms |
| P2 单路稠密、改写文本 | 71.3 | | 225 ms |
| P3 三塔 + 级联剪枝 | 74.4 | ALL(1–4) 76.4；overall 0.6020 | 10,199 ms |

多跳单列：P1 23.6 → P2 48.5。构建总账：全量 8,071 次 LLM 调用、1,111 万输入 token、301 万输出 token、21 次失败。
全量限制到同 3 个 conv 与独立 3-conv 跑分相差 0.41pp。

### 两组数字为什么不能直接比

三处口径差异，每一处都独立地把数字推向不同方向：

1. 向量后端不同。论文用本地 Qwen3-Embedding-0.6B，臂用云端 embedding-3、2048 维。
   延迟差两个数量级（82 ms 对 10,199 ms）主要由此而来，不是算法效率的差异。
2. 答题 prompt 不同。上游把数据集的问题类别标签写进 prompt，臂全臂统一不注入。
3. 判分口径不同。臂用统一 judge，且答案里的 ISO 日期会让词重叠 F1 跨臂失效，
   本仓库主表读的是 judge 判定而不是 F1。

## 附：推导

### 图这条线全断，为什么臂仍拿到主表第一

臂的实体关系 0 条落地、溯源边 0 条、子图扩展不存在——按论文叙事，多跳能力应该垮掉。
实测却是全量 ALL(1–4) 76.4、全类别第一。可解释的路径只剩一条：多跳增益来自 L0 改写而不是图。
证据链是闭合的——P2 尚未启用任何塔的检索，多跳已经从 23.6 涨到 48.5，而该形态下证据 100% 是 L0；
P2 到 P3 再加三塔检索只多 3.1 个点。也就是说，把每条 message 改写成自包含句子这一步，
承担了论文归给图结构的大部分工作。

### 级联剪枝的第二级在 LoCoMo 规模上无可测量贡献

`docs/mandol-repro-plan.md` §12 的消融给出 Δ=+0.0051、t=0.89、p≈0.42。
配合 stage1 实测 97.3% 的查询一条都没剔，三级级联在这个数据规模上实际起作用的只有第三级的 MMR 打包。
论文 §3.3.2 用三个公式描述的这套机制，在 LoCoMo 上的可测量收益集中在其中一个。

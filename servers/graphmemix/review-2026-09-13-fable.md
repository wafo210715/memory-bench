---
title: GraphMemix MCP Server 对抗审查（fable 5.1 正式轮）
date: 2026-09-13
tags:
  - memory-bench
  - graphmemix
  - review
---

# GraphMemix MCP Server 对抗审查报告（2026-09-13，claude-fable-5-1）

## 0. 流程背景

仓库纪律规定实现审查由 `claude-fable-5-1` 执行。2026-09-12 该模型连续两次渠道 503 零产出，临时改由 `claude-opus-4-6` 完成了一轮审查（`servers/graphmemix/review-2026-09-12.md`，判定 CRITICAL 0 / MAJOR 0 / MINOR 5，"可以开跑"）。那轮审查没有抓到随后在正式跑分中当场暴露的 CRITICAL 级缺陷：内部 LLM 调用把 429 限流与 JSON 格式错误放在同一个 except 分支，三次快速重试后静默降级为"全部候选零分"，产出看不出问题的证据（`runs/graphmemix-p1-3conv.VOID.md`）。

本轮是 fable 5.1 可用后的正式审查，独立重做，不以上一轮结论为锚。审查对象是冻结指纹 `8a6d72c7e2d31ffc` 的 `servers/graphmemix/server.py`（962 行，已核对与 `runs/graphmemix-p1-3conv-v2.freeze.txt` 一致，其余 9 个冻结文件指纹也全部一致），以及配套文档、上游仓库 `~/Documents/repo/graphmemix @ d0ea01d`（只读）、论文全文 txt（`literature/papers/Li-2026-GraphMemix-...txt`）和已完成 run `runs/graphmemix-p1-3conv-v2/` 的实测产物。

审查方法：每条否定式断言都先 grep 或读码；两处数学/机制主张用可执行的小实例证伪或证实；实测数据从 evidence/answers/system_stats 原文重新统计，不引用别处的转述数字。未修改任何被审查文件（唯一的写入是本报告；口径 5 的复现实验在 `/tmp/gm_state` 临时目录里跑，没有碰 `.state/`）。

## 1. 分级 findings

计数：CRITICAL 0 · MAJOR 3 · MINOR 6。

### F1 · MAJOR · 口径 5 的连通分量分解不等价于 Eq.13：每个分量被强制非空，效用低于 κ 的孤立节点永远不会被剔除

位置：`server.py:671-709`（`_exact_prune`）；上游 `evaluate_graphmemix_exact_pruning.py:74`（`for mask in range(1, 1 << n)`）；论文 Eq.13（txt:1096-1115，"∅≠S⊆S̄_q … globally optimal over all nonempty subsets of S̄_q"）。

问题：上游 `exact_subset` 只枚举非空子集，这是论文 Eq.13 的"∅≠S"约束，作用在整个提案 S̄_q 上。`_exact_prune` 把提案按正收益边切成连通分量后逐块调用 `exact_subset`，于是"非空"约束被复制到了每一个分量上。凡是没有正收益边的节点都自成一个单点分量，`exact_subset([m], …)` 只有 `mask=1` 一个候选，无论 p_m 多低都会保留。全局穷举下，一个孤立节点 m 的贡献是 p_m − κ，p_m < 0.12 时严格为负、必被丢弃（除非提案里所有节点都为负，此时保留最优的一个）。目标函数在分量间可加这一点是对的，但"非空子集的全局最优 = 各分量非空最优之并"不成立：等价的分解必须允许分量取空集，只在全体为负时退回保留全局最优单点。

证据：
- 小实例：两个孤立节点 p=(0.15, 0.10)，κ=0.12。上游 `exact_subset` 返回 `['a']`；`_exact_prune` 返回 `['a','b']`。
- 随机实例 300 组（3-12 节点、p∈[0.08,0.30]、随机正角色边）：138 组两者结果不同；全部 p>0.12 的实例 0 组不同。差异只出现在存在 p≤κ 节点时，与上面的机理完全吻合。
- 实测 run：499 个真实计算的 query 共返回 9,968 条 envelope，其中 365 条 score（即 p_i）< 0.12，分布在 115 个 query 里；141 个 `FOREST_DEGENERATE` query（提案阶段 chosen_edges=0，因此精修阶段也不可能有正收益边、所有节点都是单点分量）里有 87 条 p<0.12 的 envelope、分布在 10 个 query，这 87 条在忠实的 Eq.13 下必定被剔除。剔除量的区间是 [87, 365] 条 / [10, 115] 个 query。

后果：
- 口径 5"数学等价的加速，非近似"（`server.py:33-40`、REPRO-NOTES §1 第 5 行、freeze §已声明偏离项第 3 条、上一轮审查问题 3 结论）不成立。
- run 报出的"变基数少给 12/499（2.4%）"是低估；`interface-spec.md` §4 引用块"效用低于开辟一条独立证据链的成本的节点会被主动剔掉"与 §7 阈值表的 graphmemix 行对当前代码不成立。REPRO-NOTES §4.1"保留判据就是效用高于 0.12"同样不成立。
- 对答题准确率的影响有界（至多 3.7% 的 envelope，且都是低效用节点），方向不明；对"机制统计"的影响是确定的。

修复建议：`_exact_prune` 内改用 `exact_subset` 返回的 `_diag["objective_value"]`：逐块求 (value_b, kept_b)；只并入 value_b > 0 的块（value_b == 0 按上游 tie-break"更少节点优先"丢弃）；若没有任何块为正，则保留 value 最大的那一块（与全局非空最优一致，tie-break 按上游的 (value, −len, 更早提案序)）。修完后把本节的小实例和随机对照写成 `tests/` 里的等价性测试，口径 5 才允许继续写"等价"。

### F2 · MAJOR · ECV 把锚点自身排除在候选之外，偏离论文 Eq.7 与上游代码，系统性少验一批最高置信的 schema 边

位置：`server.py:574-575`（`if mid in anchor_set: continue`）；论文 Eq.7（txt:617-624，E_q^elig = {(a,i)∈E_schema : a∈A_q, i∈C_q}，i 的取值域是整个 C_q，A_q⊆C_q）；论文 A.4（txt:2174-2176，候选字段含 `is_atomic_anchor`）；上游 `score_graphmemix_ecv.py:457-478`（只排除 `anchor == mid`，锚点与另一锚点有 schema 边时同样进入 `edge_candidates`）。

问题：论文与上游都允许"锚点 i 相对另一锚点 a 的增量价值"被验证；本臂只验"非锚点候选 ↔ 锚点"。LoCoMo 上唯一的 schema 关系是 consecutive_turn，而相邻两轮（问与答）经常同时排进检索前 10，这类"锚点—锚点"边恰恰是最可能被判为 new_fact/clarification 的边。

估算（用返回的 20 条 envelope 里按 p_i 排名前 10 作为锚点集合的代理，因为 p_i 以检索分为主导）：499 个真实 query 里，平均每题 1.75 对相邻轮同时落在代理锚点集合内，387/499 个 query 至少有 1 对，合计 873 对从未进入 ECV。对照实测 avg_eligible_edge_pairs=17.57、avg_trusted_edges=2.26、ECV 正角色率 (393+302+409)/7638 ≈ 14.5%：按同样正角色率，这 873 对约能多产出 120-130 条可信边（每题 +0.25，约 +11%），并会让一部分 `FOREST_DEGENERATE` 翻面。代理估算的方向是确定的：忠实实现的可信边只会更多、退化率只会更低。

后果：本 run 的"森林退化 28.3%"是忠实实现下退化率的上界，不是点估计；REPRO-NOTES §4.2 与 freeze 把它当成"LoCoMo 任务性质决定的真实退化"来解读，需要收回一部分。paper-vs-code.md 三列对照里没有登记这条偏离（grep "锚点" 无相关条目），属未声明偏离。

修复建议：删除 `server.py:574-575` 的跳过，改为 `opts = [a for a, _sim, rel in adjacency.get(mid, []) if a in anchor_set and a != mid and rel == "explicit"]`；候选 payload 补 `is_atomic_anchor` 字段（论文 A.4 明文字段）。同时 `_ecv` 的 edge key 从 `f"{anchor}|{mid}"` 改为上游的 `sorted((mid, anchor))` 并对同一无向边取最大 incremental，否则锚点—锚点边可能以两个方向出现两次。

### F3 · MAJOR · `_llm_json` 仍有一条"非瞬时 API 错误 → 走格式分支 → 三次后降级为零分"的路径；且三次格式失败后降级本身偏离上游（上游 raise）

位置：`server.py:281-315`；对照 `bench/llm.py:76,112-113`（"其余 4xx 直接 LLMError"）；上游 `score_graphmemix_verifier.py:325-345`、`score_graphmemix_ecv.py:571-593`（`except (json.JSONDecodeError, ValueError, TypeError)`，三次后 `raise RuntimeError`）。

问题：修复把瞬时错误（`RateLimitError` / `APIConnectionError` / `APITimeoutError` / `InternalServerError` / status 429 / ≥500）分了出来，这部分正确。但 except 仍是 `except Exception`，所有其它异常都落进"格式分支"：`BadRequestError`（400，例如智谱 1301 内容安全拦截、上下文超长）、`AuthenticationError`（401，key 失效/轮换）、`PermissionDeniedError`（403）、余额类错误（智谱可能以 400/429 之外的码返回）。这些错误"回灌校正"毫无意义，三次后 `return None`，调用方降级为全零分并打 `NODE_VERIFIER_FAILED` / `ECV_FAILED`。于是一次 401 会让此后每一题都以"打了标的降级证据"跑完整个 run，runner 不会停，`summarize()` 也不看 native_notes。与事故前的差别只是多了一个标记，"不再降级产出证据"这句修复声明只对瞬时错误成立。另外上游在三次格式失败后 raise（论文 A.4 也只说"retried at most three times"，没说降级），本臂改为降级且没有写进口径。

本 run 未触发：`system_stats.jsonl` 首条 node_verifier_failed=0 / ecv_failed=0 / llm_parse_failures=0（覆盖 486/499 题），evidence 1500 行无任何 `*_FAILED` 标记（覆盖全部 499 题）。

修复建议：
1. 格式分支只接 `json.JSONDecodeError / ValueError / TypeError / KeyError`（解析 + schema 校验），与上游同域；`openai.APIStatusError` 里非瞬时的（400/401/403/404/422 等）立即 raise，与 `bench/llm.py` 对齐。
2. 三次格式失败后 raise 而不是返回 None（与上游一致）；如果坚持降级，必须写进口径并在 runner 侧设阈值（例如降级率 > 1% 挂起）。
3. 在 `runner.summarize()` 或出分脚本里统计 `*_FAILED` 标记数并打印，作为 run 完成时的门禁项。

### F4 · MINOR · ECV prompt 与 schema 有四处措辞偏离论文 A.4，且缺少上游的覆盖率校验与对应探针

位置：`server.py:586-621`、`623`；论文 A.4（txt:2580-2616）；上游 `score_graphmemix_ecv.py:520-567`、`640-645`、`validate_candidate_rows`（:45-100）。

偏离：(a) system message 由"You are a conservative personal-memory evidence-chain verifier."改成"You assess conditional evidence chains."，丢掉了"conservative"这个直接影响正角色率的限定词；(b) 候选缺 `is_atomic_anchor`；(c) `output_schema` 顶层键 `rows` 与关系字段名 `relations`，论文/上游是 `candidates` 与 `relation_types`；(d) 上游要求"complete and unique candidate coverage"，缺行时 raise（:640-645），本臂不校验，模型漏掉的候选静默变成"无边"。探针只记了 `ecv_rows_returned / ecv_rows_dropped`，没有 `ecv_rows_expected`，因此事后无法区分"模型判无关"与"模型漏答"。REPRO-NOTES §4.2"丢弃 0 行这个数字排除了实现层面的嫌疑"只排除了非法行，没排除漏行。

修复建议：prompt 与 schema 逐字回到论文 A.4；加 `ecv_rows_expected` 探针与逐题 `ECV_COVERAGE_SHORT` 标记；漏行率进入出分统计。

### F5 · MINOR · 缓存指纹只覆盖 memories.jsonl，不含 vectors.npy 与关系图；缓存让 smoke 第 5/7 步对本臂空转

位置：`server.py:343-351`（`_corpus_fingerprint`）、`780-782`（cache_key）、`scripts/smoke_test.py` 第 5/7 步。

问题：`reset()` 后用相同文本重灌，`memories.jsonl` 逐字节相同（memory_id、sequence 都由 session_id 与顺序决定），指纹相同、命中旧缓存，但向量是新一次 embedding 调用的结果。这就是"库内容不同（向量）但指纹相同"的路径；只要 embedding 端点逐比特确定它就无害，但契约没有这个保证。本 run 没有暴露：语料只灌了一次，之后都是 restore 同一快照。smoke 第 5 步（restore 后同 query 一致）与第 7 步（reset→add→retrieve）在本臂上都命中缓存，没有再走 LLM 路径，"8/8"对本臂的证明力弱于其它臂。

修复建议：指纹加入 `vectors.npy` 的 sha（10MB，几十毫秒）；smoke 对 graphmemix 增加一次 `MEMBENCH_GRAPHMEMIX_CACHE=off` 的第 5 步，接受 id 集合 Jaccard≥0.9 而不是完全一致，把幂等性与确定性分开测。

### F6 · MINOR · `_embed` 无退避；retrieve 侧 embedding 失败会让整臂 Phase A 中止，而 runner 中止后 manifest 仍写 DONE

位置：`server.py:232-235`；`bench/runner.py:476-480`（Phase A 异常 → failures.jsonl → continue）、`488`（无条件 `status="DONE"`）。

问题：`_embed` 只有 openai SDK 默认的 2 次短重试（0.5-8 s），遇到与本次同规模的 429 风暴会直接抛错。ingest 阶段抛错状态一致（先 embed 再落盘），是干净失败；retrieve 阶段抛错会让 `evidence_for_arm` 整体退出，剩余题目全部跳过，runner 记 `failures.jsonl` 后继续 Phase B，最后 `status="DONE"`。不是静默降级，但"响亮程度"取决于有人去看 failures.jsonl 与 evidence 行数。

修复建议：`_embed` 复用 `_llm_json` 的瞬时错误退避（抽成公共 helper）；runner 在 `failures.jsonl` 非空时把 status 写成 `PARTIAL`（runner 不在本轮审查范围，仅记录）。

### F7 · MINOR · 服务端最坏退避耗时超过 runner 的 call_tool 超时

位置：`server.py:170`（8 段退避合计 290 s）+ 每次请求本身耗时；`bench/runner.py:245-248`（`timeout=300`）。

问题：退避耗尽需要 9 次请求 + 290 s 睡眠，单次 listwise 调用实测 7-10 s，最坏约 370-380 s > 300 s。真到那一步，错误会以 client 侧 `TimeoutError` 出现而不是服务端 `RuntimeError("退避耗尽")`，两者都会终止 Phase A，语义不同但结果一致。本 run 最长 215.8 s，未触发。

修复建议：runner 的 retrieve 超时提到 600 s，或把服务端退避总和压到 < 250 s；两处常量互相引用注释。

### F8 · MINOR · 探针是进程内状态，resume 后 `system_stats.jsonl` 分裂，最后一条全零

位置：`server.py:186-205`（`_probe`）、`bench/runner.py:262-263`（每次 Phase A 结束 append 一条 stats）。

问题：本 run 的 Phase A 重启过一次（log "skip 39，新增 1461"），第一个进程算的 13 题探针随进程消失；`system_stats.jsonl` 第一条覆盖 486/499 题，第二条是 2026-09-13 13:52 补跑对照臂时 graphmemix 新进程写的全零记录。任何直接读"最后一条 stats"的出分脚本都会得到 retrieve_calls=0。本报告与 freeze 里的机制统计都以 evidence 行的 native_notes 为准，不受影响。

修复建议：出分脚本对同 arm 的多条 stats 做累加并标注覆盖率，或把逐题探针（prize、trusted_edges、components、verifier_scored）直接写进 retrieve 返回的 `native_notes`，让 evidence 自包含。

### F9 · MINOR · 逐题失败标记依赖全局计数器前后比较，在并发调用下会错标

位置：`server.py:814-825`；FastMCP 3.4.7 用 `call_sync_fn_in_threadpool` 跑同步工具（`fastmcp/tools/function_tool.py:457`），并发调用是可能的。

问题：`NODE_VERIFIER_FAILED` 的判定是 `_probe["node_failed"] > node_fail_before`。两题并发时，一题失败会让另一题也被打标。当前 `bench/runner.py` Phase A 串行调用，未触发；但 `_probe` / `_stats` / `_adj_cache` 都无锁，这是隐含前提，代码里没有写。

修复建议：`_node_verifier` / `_ecv` 直接返回 `(scores, failed)`，不经全局计数器；文件头注明"本 server 假定 retrieve 串行调用"。

## 2. 事故复核两问

### 2.1 修复本身是否正确、完整；有没有遗漏的静默降级路径

正确的部分：
- 瞬时错误识别集合（`RateLimitError` / `APIConnectionError` / `APITimeoutError` / `InternalServerError` / status 429 / ≥500）与 openai SDK 2.54 的异常层次相符；退避序列 `[5,10,20,30,45,60,60,60]`、9 次尝试、8 段睡眠共 290 s，与 `bench/llm.py:34,101-108` 逐项一致；耗尽后 `raise RuntimeError`，经 FastMCP 以 tool error 返回，runner `acall` 抛异常、Phase A 终止并写 `failures.jsonl`，不会产出证据。
- 两类重试分开计数（`fmt_attempt` / `rl_attempt`），瞬时重试不回灌校正消息，`counted` 标志避免双计。
- 逐题打标与 stats 计数已落地；本 run 证据 1500 行零 `*_FAILED`，stats 首条 `llm_transient_retries=108`、`llm_calls=1080 = 972 次成功 + 108 次重试`，账目自洽；log 里 `RateLimitError` 与一次 `InternalServerError` 都走了"原样重发"分支。
- 缓存与修复的交互正确：抛错的题不会被缓存（缓存写入在函数末尾），rep2/rep3 会重新算。

不完整的部分（见 F3）：`except Exception` 的兜底域仍然把 400/401/403 等非瞬时 API 错误当格式错误，三次后降级；三次格式失败后降级本身也不是上游行为。这是本轮认定的唯一残留"降级产出证据"路径，已打标但未阻断。

其它外部依赖逐一核对：
- embedding（ingest 与 retrieve 各一处）：无退避，失败即抛错，不降级；retrieve 侧抛错会终止整臂（F6）。
- relation store 构建：纯本地 numpy，无外部依赖；构建失败（如向量行数与记录数不一致）由 `add_conversation` 的 assert 提前拦截；`_adjacency()` 缺文件时惰性重建，不会用旧图。
- snapshot / restore：目录拷贝；restore 失败返回 `{"ok": False, "error": "SNAPSHOT_NOT_FOUND"}`，runner `sys.exit`；restore 后 `_adj_cache` 置空、`_corpus_sha` 置空，不会用旧图或旧指纹。`server.py:956-957` 的 `SNAPSHOT_FAILED` 回填是死代码（BaseState 总会带 error），无害。
- 上游导入：启动即检查 `scripts/graphmemix_core.py` 存在，缺失直接抛错。
- 关系图与 scope：离线重建 1297 条记忆的 relation store，跨 scope 边 0 条，explicit 边 1234 = 1297 − 63 个 session，与 `load_adjacency` 的 explicit/semantic 标签也无丢失。

### 2.2 为什么上一轮漏掉；审查清单该加什么

漏掉的机理，从上一轮报告原文能直接看出来：
1. 它审的是"分支的意图"而不是"分支的异常域"。F1（llm_calls 双计）已经把 `_llm_json` 的 except 块逐行读过，但把它当作"JSON 解析失败分支"来审，没有问"`except Exception` 还会接住什么"。
2. 它把 smoke 8/8 当作"不存在会让 runner 静默出错的路径"的佐证（问题 1 结论原话）。smoke 只走成功路径，对失败行为零覆盖。
3. 它没有做"输出可区分性"检查：没有问"某个外部调用失败时，产出的 evidence 行与正常行能不能区分"。事故的本质正是这两种行无法区分。
4. 它接受了"探针为 0 即实现无嫌疑"的推理（问题 6 第 1 条），但探针只在成功路径上计数，失败路径当时根本没有计数器。

可复用的审查清单新增项（措辞可直接抄进 implement-check-run 的第二层）：

| # | 检查项 | 通过标准 |
|---|---|---|
| R1 | 外部依赖失败矩阵 | 列出每个外部调用点（LLM、embedding、子进程、文件、网络）× 失败类型 {429, 5xx, 超时/连接, 非瞬时 4xx(400/401/403), 响应格式/schema 失败, 空响应}，逐格填写行为 ∈ {抛错, 退避重试(次数/总时长), 降级}。任何 `except Exception` 必须在表里列出它实际会接住的异常族 |
| R2 | 降级三要件 | 允许存在的降级路径必须同时满足：逐题在 native_notes 打标、stats 有计数、出分脚本统计该计数。缺任一项即 CRITICAL |
| R3 | 输出可区分性断言 | 对每条降级路径写一句"降级行与正常行靠 X 字段区分"，并在 smoke 或单测里用故障注入（假 base_url 返回 429/500/401/非 JSON）实际产出一行、断言 X 存在 |
| R4 | 与上游失败语义对齐 | 上游在 N 次失败后 raise 的位置，封装不得改为降级；改了必须写进口径并给理由 |
| R5 | 退避对齐与超时预算 | 所有 arm 内部 LLM/embedding 调用的退避序列与 `bench/llm.py` 一致；server 最坏耗时 < runner `call_tool` timeout，两处常量互相注明 |
| R6 | 机制激活率门禁 | shakeout 后核对：验证/打分类调用的成功率、返回行数、可信边数在预期区间；"机制未激活"与"机制判定为空"必须能从逐题标记里分开统计 |
| R7 | 数学等价性必须有可执行对照 | 凡口径里写"等价/精确/无损"，必须附一个随机小实例对照测试（分解版 vs 原版逐实例一致），边界条件（空集、非空约束、tie-break、截断）单独列 |
| R8 | 引上游函数时核对输入域 | "引上游原版"只保证函数体一致；审查要核对喂进去的集合（谁能进候选、谁能进锚点、谁能进边）与论文公式的取值域逐项一致 |
| R9 | 探针的生命周期 | 探针若为进程内状态，出分脚本必须能处理 resume 造成的多条 stats；否则逐题指标写进 evidence |

R1-R6 直接对应本次事故与 F3/F6/F7；R7 对应 F1；R8 对应 F2；R9 对应 F8。

## 3. 其余六问逐条结论

### 问题 1 · 契约符合性

结论：合规，无阻断项。六工具签名与 `servers/atommem`、`servers/rag_baseline` 逐字一致（`top_k` 默认 5 是三臂共同写法，runner 总是显式传 20）。返回结构：`add_conversation` 给 `accepted_turns` + `native_notes`；`retrieve` 给 `results / query_used / query_mode / latency_ms / native_notes`；`reset` 给 `ok + cleared{memories, sessions}`；`stats` 经 `StatsTracker.to_dict` 给 §5 全部字段并追加 `prize_probes / paper_hyperparams / relation_store / thinking`；`snapshot / restore` 走 `BaseState` 目录拷贝。Envelope 由 `servers/common/envelope.py:make_envelope` 渲染，≤600 字符、六字段齐全、`turn_range=[i,i]`、`raw_format="graphmemix_forest_node"`。scope 隔离两层（关系图按 scope 分组建边 + retrieve 时邻接表按 scope 过滤），离线重建验证跨 scope 边为 0。错误码：`FILTER_IGNORED` 只在 filter 含 `before_timestamp/session_ids` 时追加；`SNAPSHOT_UNSUPPORTED` 不适用；无 `PARTIAL_INGEST` 路径（embed 失败整段抛错）。排序非 score 降序（1500 行里 963 行非单调）已以 `ORDER=forest_bfs` 声明并登记在 interface-spec §4。

### 问题 2 · 口径 note 与代码一致性

- 口径 4（K=top_k）：一致。`solve_forest_greedy(k=min(top_k, len(candidates)))`、`_exact_prune(..., top_k)`（`server.py:836-838, 852`）。
- 口径 5（连通分量分解）：不一致，见 F1。分解本身实现了，但"等价"这个断言为假。
- 口径 8（Eq.14 系数）：一致。`PRIZE_A/B/C = 4.16 / 0.208 / −3.64` 由 (0.8, 5.2, 0.7) 展开（`server.py:162-165`），与论文 Eq.14/15（txt:1871-1879）逐字对上；上游 `shared_dev.json` 的 `standardization` 字段在上游三个读取点都未使用（`evaluate_graphmemix_ecv.py:53`、`exact_pruning.py:148`、`probe_pcsf.py:308` 都是 `a*s + b*v + c` 原始尺度），因此"系数逐项差 2-8%"的比较口径是对的。
- 口径 9（真并行）：一致。`ThreadPoolExecutor(max_workers=2)` 同时提交，两个函数无数据依赖；一方抛错时 `with` 块会等另一方结束再传播，无孤儿线程。
- 口径 12（查询缓存）：实现与描述一致；安全性见问题 4。
- 口径 1/2/3/6/7/10/11：一致。口径 11 的森林序确实由上游 `solve_forest_greedy` 内置（`probe_graphmemix_pcsf.py:225-242`：分量按根效用排、分量内 BFS、tie 按效用再按检索序），精修后只做 mask 过滤不重排，与上游 `exact_subset` 的 `kept=[ids[i] for i in range(n) if mask>>i&1]` 同型，也与 paper-vs-code 差异 11 的登记一致。
- 未登记的偏离：F2（ECV 排除锚点候选）、F3 第二点（三次格式失败后降级而非 raise）、F4（prompt 措辞）。这三条在 server.py 文件头 12 条口径与 paper-vs-code.md 里都没有出现。

### 问题 3 · 口径 5 的数学等价性

结论：不等价。可加性论证正确（分量间无耦合项；B_e≤0 的边永远不会进最优森林，所以只按正收益边切分是 WLOG），benefit 判据 `root_cost − edge_weight·(−log max(sim,1e-6)) > 0` 与上游 `exact_subset` 内部（`evaluate_graphmemix_exact_pruning.py:73-76`）逐字一致，κ=0.12、λ=0.1 同值。断裂点在"非空"约束：上游枚举 `range(1, 1<<n)`，论文 Eq.13 写 ∅≠S⊆S̄_q，都是对整个提案非空；逐块调用把它变成逐块非空。证伪实例与实测量化见 F1。上一轮审查问题 3 的"tie-break 差异不改变目标值"结论对 p>κ 的实例成立，对含 p≤κ 节点的实例不成立。

### 问题 4 · 口径 12 的缓存安全性，以及缓存对 n=3 的影响

安全性：key = sha256(query | query_mode | top_k | scope_id | memories.jsonl 指纹)。失效点核对：`add_conversation` 与 `reset` 经 `_mark_relations_dirty` 置空指纹，`restore` 直接置空，三处都重算。"同指纹返回过期结果"：记录内容变则指纹变，envelope 从当前 `by_id` 现场重渲染，未找到过期路径。"库内容不同但指纹相同"：存在一条（F5）——指纹不含 `vectors.npy`，reset 后同文本重灌会命中旧缓存而向量已是新调用产物；本 run 未暴露（语料单次灌入、其后均为同一快照 restore）。FIFO 上限 4096 > 本 run 500 个唯一 key，未淘汰。

对 n=3 的影响判断：
- 对跨臂比较没有实质损害。被动检索臂（rag_baseline / mem0 / graphiti 等）三个 rep 的 evidence 本来逐字相同，n=3 在所有臂上测的都是答题器方差，缓存让 graphmemix 与它们同口径。
- 对本臂自身有一处未测量：verifier 浮点非确定性在 κ 临界值附近的进出（smoke 实测过 4 条 vs 5 条）被归零，且一次运气差的 verifier 调用会被 ×3 复制而不是被平均，逐题的 3-rep 一致性会高估本臂的稳定性。
- 报告应声明的措辞：`n=3 是同一检索样本上的 3 次答题采样；graphmemix 的检索侧方差未测量（1001/1500 行为 CACHE_HIT），需以 MEMBENCH_GRAPHMEMIX_CACHE=off 单独跑一轮界定；证据条数、退化率、变基数统计以 499 个唯一检索样本为分母`。另外 500 题里 conv-30 q95 与更早一题题面完全相同，因此 rep0 也命中缓存一次，唯一检索样本是 499 而不是 500，这一点也要写明。

### 问题 5 · 复现忠实度

- ECV 只判 schema 边：落实。`_ecv` 只收 `rel == "explicit"`（`server.py:576`），`load_adjacency` 在 explicit 与 semantic 同时存在时取 `explicit_similarity ≥ similarity` 才标 explicit——语义相似度 ≥0.99 时会被标成 semantic 而漏出 eligible；离线重建核对 258 条同时带两种关系的边里语义相似度 ≥0.99 的为 0 条，本语料未触发。
- 锚点按冻结检索序：落实。`candidate_pool` 保序返回种子（检索前 24）再接扩展，`anchors = candidates[:10]` 即检索前 10，等价于上游 `anchor_mode=atomic`。但锚点作为 ECV 候选被排除，偏离 Eq.7 与上游（F2）。
- 证据序列化为分量根优先 + 分量内 BFS：落实（由上游 `solve_forest_greedy` 内置），精修后 mask 过滤保序与上游一致。
- 节点 verifier prompt：与论文 A.4（txt:2537-2566）逐字一致（去掉了无图时的 caption 指令）；ECV prompt 有四处措辞偏离（F4）。
- 三次格式失败后降级而非 raise：偏离上游与论文 A.4 的重试语义（F3 第二点）。
- 其余（编码器、K、系数、并行、单视角、consecutive_turn、缓存）均已在口径与 interface-spec §7 登记。

### 问题 6 · 实测数据解读（森林退化 28.3%，adversarial 20/330）

森林退化 141/499：
- 属于实现偏差的部分：F2 让每题平均约 1.75 对最高置信的相邻轮边从未被验证，忠实实现下退化率只会更低。28.3% 应改述为"上界"。F1 不影响此项（退化在提案阶段判定）。
- 属于任务性质的部分：LoCoMo 只提供 consecutive_turn 一种 schema 关系；ECV 六角色分布 irrelevant 6052 / redundant 469 / 正角色 1104（14.5%），说明模型对大多数相邻轮确实判"无增量"。论文 Table 6 在自家四个数据集上 ECV 配置下也有 85%-97.5% 的节点是孤立点（分量数 8.53-9.75 / K=10），本 run avg_forest_components=18.13 / K=20（≈90.7% 孤立）落在同一区间；"退化"是 ECV 设计的保守输出，不是异常。
- 属于答题器因素的部分：退化题 judge 准确率 0.415（n=422 行）vs 非退化 0.501（n=1069 行），差距在 cat2/cat4 上最大。但退化与否和题目难度同源（ECV 找不到可信边的题往往证据本身就弱），不能据此说"森林有效"。要拆开需要 CACHE=off + 修 F2 之后的对照。

adversarial 20/330（6.1%）：属于任务与答题器因素，不是机制。同一 3 个 conv、同一答题器与判分器下，rag_baseline 26/333（7.8%）、atommem 25/333（7.5%）、memharness_noadapt 17/333（5.1%）、mem0 全量 52/1338（3.9%）、graphiti 44/1338（3.3%）——所有被动检索臂都在 3-8%。cat5 要求答题器在给了 20 条证据的前提下说"对话里没有"，forced-call 协议下的答题 prompt 与 judge 口径决定了这一切片的下限，graphmemix 在其中处于中位。

## 4. 其它核对结果（无 finding）

- 冻结指纹：`freeze.txt` 10 个文件全部与当前工作区一致。
- 运行完整性：evidence 1500 行（499 真实 + 1001 CACHE_HIT），answers 1500 行（Phase B 首次 1491 行，9 题答题侧 429/连接失败已由后续 resume 补齐），judge 解析失败 0，PARSE_ERROR 0。judge 准确率 0.477、分类切片与 freeze/父任务给的数字一致（cat1 74/240、cat2 195-196/287-288、cat3 34-36/76-78、cat4 388-389/558-561、cat5 20/330-333，两组数字差异来自 1491 与 1500 的分母）。
- 延迟：真实计算 499 题中位 8.8 s、最大 215.8 s（退避所致），未触及 runner 300 s 超时。
- 成本：internal_llm 3.57M token / 486 题 ≈ 7.3k/题，与 REPRO-NOTES §3 的 6.8k 同量级。
- 探针：prize 中位 0.146、最小 0.096、最大 0.31，与 REPRO-NOTES §4.1 基线一致；prune_kept 均值 19.98（受 F1 影响，忠实实现下会更低）。

## 5. 判定

一句话：当前 run 的答题结果可以作为"本臂现实现 vs rag_baseline"的对比数据继续使用并继续补跑对照臂，但它不能作为论文机制的忠实复现结论——森林退化 28.3% 只能报"上界"，变基数 2.4% 必须收回，口径 5"等价"必须收回；要给出机制层面的结论，需修 F1-F3（连同 F2/F3/F4 补进口径）后另开 v3 重跑 graphmemix 臂，并补一轮 `MEMBENCH_GRAPHMEMIX_CACHE=off` 对照。

分级依据：CRITICAL 定义为"结果不可用或结论已被静默污染"。F1/F2 都改变了机制统计的正确性，但对答题准确率的影响有界且方向可述，evidence 本身没有被不可见的错误污染；F3 的残留路径在本 run 未触发且有证据证明未触发。因此三条为 MAJOR。

CRITICAL: 0 · MAJOR: 3 · MINOR: 6

# memharness 架构文档复核报告

> 复核日期 2026-09-05；论文源 `Wu-2026-MemHarness.txt`（1593 行）；代码源 `MemHarness` @ `31329e8`（2026-08-07 "add cold start data"）
> 复核范围：`servers/memharness/paper-architecture.md`（180 行）、`servers/memharness/code-architecture.md`（208 行）。
> 同目录 `methodology-flow.md` 是这两份文档 + 前一版 verification 的下游合成产物，本次不单独逐条判定，仅在第 5 节引用。
> 方法：论文侧每条断言用 `grep -n` 定位到 txt 行号并核对章节/公式编号；代码侧每个 `file.py:NNN` 都实际 `sed -n` 打开该行前后确认，控制流断言顺调用链读到函数体，否定式断言主动全仓搜索反例。
> 判定：`✓` 属实 / `✗` 不实 / `◐` 部分属实或需加限定 / `?` 无法核实。

## 1. 总评

两份文档的**行号级精度很高**：code-architecture.md 引用的 40 余个 `file.py:NNN` 中只有 1 处指错行（`_neighbor_has_similar_memory_text`），其余（含 `ppo_trainer.yaml` 的 15 处配置行、`rollout_loop.py:444/460/552/604`、`mem_adaptor_rollout.py:192/494/556/732`、`env_manager.py:318/734`）全部逐行核对无误；paper-architecture.md 的原文引语基本是逐字准确的。最有价值的两条结论——检索标签 `<retrieve_memory>` / `<memory_retrieve>` 词序论文写反、"unified policy" 只是代码配置空间里被选中的一支——均已顺调用链证实。

但有**三类系统性问题**：

1. **两份文档都完全没有"冷启动 SFT"这一整个训练阶段**。论文 §4.1（txt:569-574）与 Appendix A.4（txt:1286-1307）明写：先用 GPT-5.1 从 AgentGym 造 2×200 条冷启动数据，做 2 epoch SFT（lr 1e-5、有效 batch 2），再进 RL；仓库里 `scripts/cold_start_sft.sh`（`trainer.total_epochs=2` / `optim.lr=1e-5` / `data.train_batch_size=2`）与 `scripts/build_{alfworld,webshop,summarizer}_coldstart_data.py`（`--retrieve-model` 默认 `gpt-5.1`）一一对应。paper-architecture.md §1 却写"完全靠 GRPO 端到端优化…隐式学会"，code-architecture.md 从头到尾没有出现 `scripts/` 目录。
2. **code-architecture.md 把"训练脚本覆盖值"当成了"代码默认值"**：`experience_summarizer.mode` 基础默认是 `none` 不是 `self`（yaml:419）；`prune_score_threshold` 基础默认是 `0.35` 不是 `0.3`（yaml:462），且 `prune_every_n_global_steps: 0` 默认是**关闭**剪枝的（yaml:461）。文档在别处（write_back、retrieval_mode、use_actor_rollout_wg）都正确区分了"基础默认 vs 脚本覆盖"，这三处是漏网。
3. **最承重的一条机制断言被漏掉**：论文 §3.4（txt:268-269）说轨迹级优势"被同等分配给思考、**重构**、动作生成的所有 token"，两份文档都照抄了；但在论文实际使用的配置（`use_actor_rollout_wg=True`）下，`train_memory_adaptor_enabled()` 直接返回 False（`mem_adaptor_training.py:336-337`）→ `adaptor_train_buf=None`（`rollout_loop.py:534-539`）→ `ray_trainer.py:1890` 整段 adaptor GRPO 被跳过，**重构这次生成的 completion token 不进入任何梯度更新**。code-architecture.md 把 `train_memory_adaptor=false` 解读成"不单独训练它"，容易被读成"和主策略联合训练"，实际是"完全不训练"。

另有若干否定式断言被证伪：论文"通篇没有出现每一步都检索"（A.3 txt:1261-1262 就写了 "at each step"）、"没说是否 zero-shot"（txt:729 明写 zero-shot）、"批判没有可观测判定量"（Table 4 的 RR 拒绝率、Figure 3 的 Reject/Traj 就是）、代码"只有真的检索到东西才会跑重构"（零命中也会跑）。Milvus schema 是 19 个字段不是 18 个。

## 2. 逐条核对表

### 2.1 `paper-architecture.md`

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| P1 | 抬头 | `arXiv:2607.28272` | ✓ | txt:12 `arXiv:2607.28272v1 [cs.AI] 30 Jul 2026` | |
| P2 | §1 | 人类回忆"重构"非"复现"，§1 引认知科学 [11] | ✓ | txt:50-51；[11]=Loftus & Palmer 1974，txt:1075-1076 | |
| P3 | §1 | 同一策略在"取回"与"生成动作"之间插入一次"批判并重写" | ✓ | txt:58-62（五阶段）、txt:182-192（三阶段+unified policy） | |
| P4 | §1 | 判定不适用则回退自主推理 | ✓ | Eq.5 txt:224-231；`pself` 定义 txt:231 | |
| P5 | §1 | "没有人工标注" | ✓ | txt:73 `requires no additional human annotation` | 冷启动数据由 GPT-5.1 生成，确非人工标注 |
| P6 | §1 | **"完全靠 GRPO 端到端优化任务成功率隐式学会"** | ◐ | 反证：txt:569-574 `we perform a brief cold-start stage before RL training…200 multi-turn interaction trajectories…200 question–answer examples`；A.4 txt:1286-1307（GPT-5.1 造数、SFT 2 epoch、lr 1e-5、batch 2） | 论文摘要/§1 确实这么宣称，但 §4.1+A.4 明确有前置 SFT；文档全篇未提冷启动，且论文自己也说 `the actual reconstruction and decision-making capabilities are subsequently learned through task-level RL`（txt:1305-1307），应写成"格式/协议先 SFT 对齐，能力归因于后续 RL" |
| P7 | §2 | `B={mi}`，`mi=(ei,osrc_i)`，`ei` 抽象策略、`osrc_i` 来源观察 | ✓ | txt:149-155 | |
| P8 | §2 | 来源观察用于重构阶段比较历史/当前状态 | ✓ | txt:162 `The source observations enable comparison between historical and current states during reconstruction.` | |
| P9 | §2 | 存的不是原始轨迹全文，也不是图像/结构化状态 | ✓ | txt:149-151 `periodically distilling collected trajectories into natural-language experiences` | "不是图像/结构化状态"论文未正面说，但与 natural-language 描述一致 |
| P10 | §2 | §3.1 原文只说 "periodically"，没给具体周期 | ◐ | ✓ 于 txt:149-151、txt:156-157；但 Appendix C txt:1390 `After an episode is completed, the trajectory summarization prompt extracts…`、Figure 9 标题 txt:1476 `offline trajectory summarization` 已给出粒度 | 该断言在 §5 重复出现（P42），同判 |
| P11 | §2 | §4.1 "Memory Configuration" 引文（库从空开始、随 RL 增长） | ✓ | txt:579-581 逐字一致 | |
| P12 | §2 | A.3 "Memory Initialization"：蒸馏用的正是同一个正在训练的 πθ | ✓ | txt:1263-1267 逐字一致 | |
| P13 | §2 | 只保留 50% 轨迹，优先成功/失败均衡，配额不够随机补齐 | ✓ | txt:1267-1271 逐字一致 | |
| P14 | §2 | 写入去重 `θsim` 默认 0.85，WebShop 开 / ALFWorld 关 | ✓ | txt:1273-1276 | |
| P15 | §2 | 检索去重：先取更大候选池 → 贪心 embedding 去重 → 截断 top-k | ✓ | txt:1276-1278 | |
| P16 | §2 | EvolveR([27]) 式 Laplace 效用分 `(c_succ+1)/(c_use+2)`，`θprune`=0.3，`min_uses_before_prune`=3 | ✓ | txt:1278-1281；[27]=EvolveR，txt:1118-1120；另 txt:570 `Following Deepseek-R1 and EvolveR [32, 27]` 佐证编号 | |
| P17 | §2 | 用 BGE-M3 编码存入条目，引文标注为 **§4.1** `We use BGE-M3 as the embedding model to encode both the retrieval query qt and the stored entries` | ✗ | 该句在 **Appendix A.3**，txt:1260-1261；§4.1 的原句是 txt:580-581 `We use BGE-M3 [34] as the embedding model and retrieve the top-3 most relevant principles.` | 引文内容对，章节锚点错 |
| P18 | §2 | 后端是 Milvus 向量数据库 [37]，A.3 引文 | ✓ | txt:1257；[37]=Milvus，txt:1150-1152 | |
| P19 | §3 | §3.2 Step 1 引文 `At step t, the agent decides whether to query…` | ✓ | txt:186-188 逐字一致 | |
| P20 | §3 | **"论文里检索触发方式只描述了一种…通篇没有出现'每一步都强制检索'这类替代模式的讨论"** | ✗ | 反证：A.3 txt:1261-1262 `retrieve the top-k (k = 3) most relevant experiences **at each step** based on cosine similarity` | 否定式断言被证伪；这是论文 §3.2 与 A.3 的内部张力，应写成张力而非"通篇没有" |
| P21 | §3 | Eq.1 `Et=R(qt,B), \|Et\|=k`，"a context-derived query qt" | ✓ | txt:157-165 | |
| P22 | §3 | §4.1 "we retrieve the top-3 most relevant principles"（k=3） | ✓ | txt:580-581 | |
| P23 | §3 | 按余弦相似度（A.3 "based on cosine similarity"） | ✓ | txt:1262 | |
| P24 | §3 | §1 五阶段：观察→检索→批判→重构→动作 | ✓ | txt:58-62 | |
| P25 | §3 | §3.2 收缩为三阶段，"memory critique is folded into the reconstruction stage" | ✓ | txt:182-185 逐字一致 | |
| P26 | §3 | Eq.3 = xrecon 拼接；Eq.4 = 第一次采样；Eq.5 = `<EMPTY>` 回退；Eq.6 = 第二次采样 | ✓ | Eq.3 txt:205-215；Eq.4 txt:220-221；Eq.5 txt:224-231；Eq.6 txt:232-235 | 编号与内容全部对得上 |
| P27 | §3 | §3.2 "MemHarness thus separates reconstruction from action generation while implementing both with a unified policy" | ✓ | txt:192 逐字一致；另 txt:175-176 `Both stages share the unified policy πθ` | |
| P28 | §3 | 不是把 `Et` 原文直接拼进动作 prompt，而先经重构 | ✓ | txt:167-171（对比 verbatim replay）、txt:186-188 | |
| P29 | §3 | §3.3 "By comparing each source observation…produce context-specific guidance" | ✓ | txt:222-223 逐字一致 | |
| P30 | §3 | `gt` 无标注、当隐变量、只用 episode 级奖励端到端 GRPO | ✓ | txt:238-240、txt:247-250 | |
| P31 | §3 | `R(τi)=Routcome+0.1×Rformat`，成功 10 / 失败 0 | ✓ | txt:251-252 | 代码侧亦证实（见 C55） |
| P32 | §3 | `Rformat∈[0,1]` 三项标准（think+action / 检索频率 / 严格英文） | ✓ | txt:253-255 逐字一致 | 与代码实现不同，见第 5 节 D3 |
| P33 | §3 | 轨迹级优势 Ai（Eq.7）同等分配给"思考、重构、动作生成"所有 token | ✓ | txt:263（Eq.7）、txt:268-269 逐字一致 | 论文属实；但代码在论文配置下不成立，见第 5 节 D1 |
| P34 | §4 图 | 检索器 cosine top-k=3（§4.1） | ✓ | txt:580-581、txt:1261 | |
| P35 | §4 图 | 写入去重 θ_sim=0.85（ALFWorld 关 / WebShop 开） | ✓ | txt:1275-1276 | |
| P36 | §4 图 | 效用剪枝 θ_prune=0.3（Appx A.3） | ✓ | txt:1280 | |
| P37 | §4 边界 | "explicit, attributable memories，§1" | ✓ | txt:49 | |
| P38 | §4 边界 | "parameterizing their state-conditioned critique and reconstruction within a single policy，**§2.2**" | ✗ | 该句在 **§1 Introduction**，txt:68-70；§2.2 的对应句是 txt:131-132 `It retains explicit memory banks for traceability but parameterizes their state-conditioned reconstruction.`（无 "critique"、无 "within a single policy"） | 引语逐字对，章节锚点错 |
| P39 | §4 边界 | 论文没讨论重构在工程上是否需要单独一次模型调用 | ✓ | 全文搜索无 forward/call 层面的讨论；Figure 2 caption txt:114-117 只描述三阶段 | |
| P40 | §5 | 正文 §3.4 说 "three criteria" 且实际列三条 | ✓ | txt:253-255 | |
| P41 | §5 | **"Appendix A.2 复述时…先说 three criteria 后面却编号到 (4)"** | ✗ | 该复述在 **Appendix A.1**（Environment and Evaluation Setup），txt:1227-1229；A.1 标题 txt:1213-1215，A.2 标题 txt:1230-1232 是 Training Hyperparameters | 实质发现（三/四不一致、(1) 脱字、(3) 重复 think block）全部属实，仅章节号错 |
| P42 | §5 | (1) 疑似脱字 "exactly one valid block followed by" | ✓ | txt:1227-1228 | |
| P43 | §5 | "1 到 5 次每 episode" 只出现在 §3.4/**A.2** 的 format reward 段落 | ◐ | 出现处：txt:254（§3.4）与 txt:1228（**A.1**，非 A.2） | 实质属实，锚点错 |
| P44 | §5 | §3.2 描述检索机制本身时完全没提频率上下限 | ✓ | txt:186-188 无任何频率约束 | |
| P45 | §5 | **"批判阶段没有可观测的独立产物…没有给出显式的'接受/拒绝'标量或文本字段"** | ◐ | 反证：Table 4(a) 报告 per-memory **reject rate (RR)**，txt:972-987、caption txt:1027-1029；Figure 3 曲线含 `Reject / Traj`、`Accepted / Traj`，txt:825-827、txt:869-870、caption txt:886-887；§4.6 txt:1030-1033 | 拒绝/接受确实是被量化、被画曲线的可观测量（虽然它正是"gt 是否 `<EMPTY>`"的二元反推，与文档后半句自洽） |
| P46 | §5 | Table 2 "generic LLM reconstruction" 未说 prompt、**是否 zero-shot**、是否共享上下文 | ◐ | 反证：txt:729 `This demonstrates that **zero-shot** text rewriting is insufficient`；prompt/上下文细节确实缺失（txt:727-730 全文） | 应删掉"是否 zero-shot"一项 |
| P47 | §5 | 记忆蒸馏 "periodically" 未给数值 | ◐ | 同 P10：Appendix C txt:1390 给了"After an episode is completed"，Figure 9 txt:1476 称 offline | 具体"每多少 GRPO step"确实未给 |
| P48 | §5 | Table 4(a) Random source 只写 "replacing osrc with a mismatched state from a random memory" | ✓ | txt:751-752 | |
| P49 | §5 | Table 4(b) counterfactual probe 在 Appendix B 有 Figure 10/11 的生成 prompt | ✓ | B 正文 txt:1311-1318（2000 例：ALFWorld 1000 + WebShop 1000）；Figure 10 txt:1518、Figure 11 txt:1546 | |
| P50 | §5 | (a)(b) 两组消融是否同一批数据，论文未明确关联 | ✓ | 通读 §4.5 txt:747-754 与 Appendix B txt:1309-1318，无关联陈述 | |
| P51 | §6 | 与 §5 合并陈述，五处缺口 | ✓ | 与 §5 一致，无新断言 | |
| P52 | 前言 | "本文档只依据论文正文与 Appendix 的文字/公式/图表写出" | ◐ | Appendix C（Prompt Templates，txt:1373-1477）与 Appendix A.4 全篇未被使用；Figure 8（txt:1428-1445）的重构 prompt 模板只有单个 `{s_old}/{p_old}`，与 §3 引用的 Eq.3 `⋃_{i=1..k}` 冲突，文档未发现 | 覆盖不全 |

**paper-architecture.md 小计：✓ 41 / ✗ 4 / ◐ 7 / ? 0**（共 52 条）

### 2.2 `code-architecture.md`

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| C1 | 前言 | 官方 KnowledgeXLab/MemHarness，HEAD=`31329e8` | ✓ | `git rev-parse --short HEAD` → `31329e8`；论文 txt:35 `Github Repo: https://github.com/KnowledgeXLab/MemHarness` | |
| C2 | 前言 | "只读源码写出，不采信 README（有出入处见第 6 节）" | ◐ | §6 三条全部是"与论文的冲突点"，无任何 README 出入条目 | 前言承诺与正文不符 |
| C3 | §1 | 重构是"额外插入的一次独立批量 `generate_sequences` 调用"，`mem_adaptor_rollout.py:556` `maybe_apply_memory_adaptor` | ✓ | `mem_adaptor_rollout.py:556` 正是 `def maybe_apply_memory_adaptor(`；批量生成在 `:732` | |
| C4 | §1 | 三件事是三次互相独立、各自 tokenize/detokenize 的模型调用 | ✓ | `rollout_loop.py:444`（主策略）→ `mem_adaptor_rollout.py:725-735`（`build_adaptor_dataproto`→`generate_sequences`→`batch_decode`）→ 下一轮 `rollout_loop.py:444` | |
| C5 | §2 | 只在 `is_train=True` 的 rollout 收完一批后写回，验证/测试不写回 | ✓ | `rollout_loop.py:602-605` 含注释 `Avoid writing summarized trajectories from validation/test into the training memory store`；`is_train` 全文仅在 :604/:737/:741 起作用 | |
| C6 | §2 | `base.py:211-214` 直接转发给 `MemoryManager.maybe_write_rollout_memories` | ✓ | `environments/base.py:211-214` 逐行一致 | |
| C7 | §2 | 实现在 `memory_manager.py:458` | ✓ | `memory_manager.py:458` `def maybe_write_rollout_memories` | |
| C8 | §2 | 默认 `write_back: False`（`ppo_trainer.yaml:414`） | ✓ | yaml:414 逐行一致 | |
| C9 | §2 | 两个训练脚本都显式 `MEMORY_WRITE_BACK=True` → `env.memory.write_back` | ✓ | `train_alfworld.sh:43` + `:265`；`train_webshop.sh:40` + `:253` | |
| C10 | §2 | compact schema 系统提示词见 `experience_summarizer.py:96` | ✓ | `:96 DEFAULT_COMPACT_JSON_SYSTEM_PROMPT` | 基础默认 `schema: full`（yaml:422），compact 来自脚本 `train_alfworld.sh:45` |
| C11 | §2 | 用户模板见 `experience_summarizer.py:107` | ✓ | `:107 DEFAULT_COMPACT_JSON_TRAJECTORY_USER_PROMPT_TEMPLATE` | |
| C12 | §2 | `MemoryRecord` 字段定义在 `types.py:12-29` | ✓ | `types.py:12` `@dataclass` / `:13 class MemoryRecord`，字段延伸到 `:31` | 12-29 覆盖文档列举的全部字段 |
| C13 | §2 | `state_text` 对应蒸馏出的 situation，取不到时用 `MEMORY_STATE_UNAVAILABLE_PLACEHOLDER`（`types.py:9`） | ✓ | `types.py:9`；`experience_summarizer.py:7` 注释 `Stored state_text is seeded from situation (then placeholder)`；`:1046` `sit = memory.get("situation")`；`:1085` 占位符回填 | |
| C14 | §2 | **"默认 `experience_summarizer.mode=self`"** | ✗ | 基础默认是 `mode: none`（`ppo_trainer.yaml:419` `mode: none   # none \| self … \| teacher …`）；`self` 来自 `train_alfworld.sh:44` / `train_webshop.sh` | 把脚本覆盖值当成了代码默认值 |
| C15 | §2 | mode=self 复用同一份 actor rollout 权重批量生成（`experience_summarizer.py:785`） | ✓ | `:785 def _summarize_batch_self`；`:820 out_pad = actor_rollout_wg.generate_sequences(dp_pad)` | |
| C16 | §2 | mode=teacher 走独立 OpenAI 兼容 HTTP API（`experience_summarizer.py:659`） | ✓ | `:659 def _summarize_batch_teacher` | |
| C17 | §2 | 两个训练脚本用的都是 `self` | ✓ | `train_alfworld.sh:44`、`train_webshop.sh`（`EXPERIENCE_SUMMARIZER_MODE="self"`） | |
| C18 | §2 | JSON 解析失败在 `parse_max_attempts`（默认 3）内重试，`experience_summarizer.py:1154` 内 while 循环 | ✓ | yaml:428 `parse_max_attempts: 3`；`:1154 def maybe_summarize_and_write_experiences`；`:1316 parse_max_attempts = max(1,…)`；`:1340 while active:`；`:1377` 达上限放弃 | |
| C19 | §2 | 一次 rollout 只蒸馏 `grpo_summarize_keep_fraction`（默认 0.5，yaml:427）比例的轨迹，与论文 50% 一致 | ✓ | yaml:427；`experience_summarizer.py:1286-1296`（按 `env.rollout.n` 分组）、`:542 k_nominal = round(group_n*keep_fraction)` | |
| C20 | §2 | 优先成功/失败均衡采样（`experience_summarizer.py:490`），配额不够按 GRPO group 补齐随机样本 | ✓ | `:490 def _select_env_indices_balanced_success_fail`；`:552 picked = set(_select_env_indices_balanced_success_fail(items, k, rng))` | |
| C21 | §2 | 写入前最近邻探测去重，阈值 `memory_text_insert_dedupe_similarity_threshold`（默认 0.85，yaml:488），命中即跳过插入 | ✓ | yaml:488；`milvus_store.py:341-348`（`>= insert_thr` → `continue`） | 代码用 `>=`，论文写 "exceeds"（`>`），量级无影响 |
| C22 | §2 | 引用位置：**`milvus_store.py:296-317`** `_neighbor_has_similar_memory_text` + `add_records` 内判断逻辑，`add_records` 定义于 `:320` | ◐ | `add_records` 于 `:320` ✓；但 `_neighbor_has_similar_memory_text` 定义在 **`:199`**，调用点在 **`:346`**，判断分支在 `:341-349`；`:296-317` 是 `initialize()` 里的 rebuild / 建集合逻辑 | 行号漂移；正确应为 `milvus_store.py:199`（定义）+ `:341-349`（调用） |
| C23 | §2 | `train_alfworld.sh` 把插入去重显式设 `null`（关闭），`train_webshop.sh` 未覆盖维持 0.85 | ✓ | `train_alfworld.sh:136`；`train_webshop.sh` 全文无 dedupe 覆盖 | |
| C24 | §2 | 本地单文件 Milvus-Lite，`milvus_store.py:97 MilvusMemoryStore`，`db_path` 为进程本地磁盘文件 | ✓ | `:97-98` `class MilvusMemoryStore: """Local Milvus-Lite backed vector memory store` | |
| C25 | §2 | **"18 个标量/向量字段的 flat schema（`milvus_store.py:785` `_create_collection`）"** | ✗ | `_create_collection` 于 `:785` ✓，但字段是 **19 个**：`milvus_store.py:793-811`（memory_id / task_name / item_id / source_episode_id / source_step / vector / state_text / action_text / memory_text / reward / success / created_step / retrieval_count / last_used_step / metadata / value / value_source / value_update_step / created_at） | 数字错 1 |
| C26 | §2 | 向量字段 `FLAT` 索引 + `COSINE` 度量 | ✓ | `milvus_store.py:821` `index_params.add_index(field_name=…, index_type="FLAT", metric_type="COSINE")` | |
| C27 | §2 | Embedding 由远端 OpenAI 兼容接口提供（`milvus_store.py:52` `RemoteEmbeddingProvider`，默认 `bge_m3`/1024，yaml:475-476），本地进程不跑 embedding 模型 | ✓ | `:52-60`；yaml:475-476；`:64` 在 `embedding_api_url` 未设时直接 `raise ValueError` | yaml:473 注释 "Use local sentence-transformers when null" 是**过时注释**，代码没有本地 ST 分支；文档结论比注释更准 |
| C28 | §2 | 初始效用分 Laplace 先验 `(0+1)/(0+2)=0.5`（`experience_utility.py:14` / `:30`） | ✓ | `:14 def compute_utility_score` 返回 `(c_succ+1)/(c_use+2)`；`:30 def initial_utility_metadata` 注释 `prior score (0,0) == 0.5` | |
| C29 | §3 | `retrieval_mode` 基础默认 `fixed`（每次观察无条件检索，yaml:389） | ✓ | yaml:389 含注释 `fixed: retrieve on every observation; agentic: let the model decide when to retrieve` | |
| C30 | §3 | 两个训练脚本都显式覆盖成 `agentic` | ✓ | `train_alfworld.sh:46`、`train_webshop.sh:43` | |
| C31 | §3 | 真实生效的标签常量见 yaml:517-518 | ✓ | yaml:517 `retrieval_query_open_tag: "<memory_retrieve>"`、:518 close tag | |
| C32 | §3 | `MemoryManager.extract_query`（`memory_manager.py:389`）用正则抽出 | ✓ | `:389-398`，`re.search(f"{open_tag}(.*?){close_tag}", …, re.DOTALL)` | |
| C33 | §3 | 这一步不算环境动作，下一步观察才带回记忆 | ✓ | `env_manager.py:341` `env_step_mask = np.zeros(...)`、`:358-370`（memory_query 分支不 step env）、`:396` `_inject_memory_queries_into_observations` | |
| C34 | §3 | ALFWorld 见 `env_manager.py:318`，WebShop 同名方法在 `env_manager.py:734` 前后 | ✓ | `:318 def step_with_memory`（`AlfWorldEnvironmentManager`，类定义 `:215`）；`:734 def step_with_memory`（`WebshopEnvironmentManager`，类定义 `:597`） | WebShop 恰为 :734 |
| C35 | §3 | 默认 `count_query_as_step: True`（yaml:465），查询这一步仍计入 `max_steps` | ✓ | yaml:465；`rollout_loop.py:394`、`:522`（`if count_query_as_step:`）、`:528 episode_lengths[counted_step_mask] += 1`、`:395/:416` `max_env_steps` | |
| C36 | §3 | 检索键默认 `retrieve_key: memory_text`（yaml:478），纯 cosine（`milvus_store.py:383 retrieve`） | ✓ | yaml:478；`:383 def retrieve`；`:388 query_vector = self._embed_texts([query_text])[0]` | |
| C37 | §3 | **没有关键词/BM25 混合，也没有二次 rerank 模型** | ✓ | 全仓 `grep -rn -i "bm25 / rerank / cross-encoder / hybrid_search" agent_system/ --include=*.py`（排除 vendored `env_package`）零命中 | 否定式断言，已主动证伪失败 |
| C38 | §3 | 检索宽度 `top_k=3`（yaml:480） | ✓ | yaml:480 | |
| C39 | §3 | 命中项按 `min_score`（默认 0.0）过滤 | ✓ | `milvus_store.py:418 if score < self.min_score: continue`；配置键为 `min_retrieval_score: 0.0`（yaml:481） | 属性名/配置键不同名，值正确 |
| C40 | §3 | 检索去重阈值（默认 0.85，yaml:486）→ 候选池贪心去重 → 截断 top_k，算法在 `memory_text_dedupe.py` `dedupe_indices_by_embedding_similarity` | ◐ | yaml:486 ✓；`milvus_store.py:389-392`（prefetch 扩宽）、`:440-445`（去重后 `retrieved[: top_k]`）✓；`memory_text_dedupe.py:26` ✓ | 漏了 `train_alfworld.sh:135` 也把**检索去重**设为 `null` 关闭——论文 A.3 把它写成无条件的第 (2) 阶段，代码在 ALFWorld 上是关的 |
| C41 | §3 | 检索默认不限定只查成功轨迹（`only_successful: False`，yaml:482；`milvus_store.py:410` 的 filter 只有开关为真才生效） | ✓ | yaml:482；`milvus_store.py:409-410` `if self.only_successful: search_kwargs["filter"] = "success == true"` | |
| C42 | §3-1 | 主策略第一次前向 `rollout_loop.py:444 actor_rollout_wg.generate_sequences(batch_input_padded)` | ✓ | `:444` 逐行一致 | |
| C43 | §3-2 | 环境把命中记忆格式化成 `--- Memory k ---\nSituation: …\nPrinciple: …`（`memory_manager.py:535 _format_memory_prompt`） | ✓ | `:535 def _format_memory_prompt`；`:556 f"--- Memory {index} ---"`、`:561 f"Situation: {st}"`、`:562 f"Principle: {memory.memory_text}"` | |
| C44 | §3-2 | 拼进下一步观察的 `<memory>…</memory>`（`base.py:217 _append_external_memory`） | ✓ | `environments/base.py:217-224`，`wrapped = f"<memory>\n{block}\n</memory>"` | |
| C45 | §3-2 | 产出发生在 `rollout_loop.py:460 envs.step_with_memory(...)` 内部，尚未调用策略 | ✓ | `:460-464` | |
| C46 | §3-3 | `mem_adaptor.enable=true`，两个脚本都显式开着（`train_alfworld.sh:255`） | ✓ | `train_alfworld.sh:255 mem_adaptor.enable=True`；`train_webshop.sh:244 mem_adaptor.enable=true` | |
| C47 | §3-3 | `rollout_loop.py:552 maybe_apply_memory_adaptor(...)` → `mem_adaptor_rollout.py:732 out_pad = wg.generate_sequences(dp_pad)` | ✓ | 两处逐行一致 | |
| C48 | §3-3 | 把 `<memory>` 块内容原地替换或整块删掉换兜底提示语（`mem_adaptor_rollout.py:494 _patch_one_obs_text`） | ✓ | `:494` 定义 + docstring `:503` `Replace the last <memory>…</memory> inner with adaptor output; on <EMPTY> remove the block and append replacement (empty_retrieval_message)`；`:460 _splice_out_memory_block` | |
| C49 | §3-3 | **"触发条件 `on_memory_only`——只有真的检索到东西才会跑这一步（`mem_adaptor_rollout.py:192`）"** | ✗ | `:192-207` 的条件是 `return bool(injected) or has_ret`；零命中时 `MemoryManager` 仍注入 `empty_retrieval_message`（`memory_manager.py:23-25`、`:165-170`、`:432-440` `injected_text=empty_msg`），使 `injected` 非空 → 通过；`mem_adaptor_rollout.py:636-640` 明写 `if not pairs and injected: pairs = [("", "", "")]  # memory injected without structured retrieved list — single adaptor call with empty S_old/P_old` | 行号对，控制流断言错：零命中也会发一次重构调用 |
| C50 | §3-3 | `use_actor_rollout_wg` 两个脚本都设 True（`train_alfworld.sh:256`） | ✓ | `train_alfworld.sh:256`、`train_webshop.sh:245`；生效点 `mem_adaptor_rollout.py:587-589` `wg = adaptor_rollout_wg; if wg is None and use_actor_rollout_wg: wg = generate_wg` | |
| C51 | §3-3 | **"`train_memory_adaptor=false`（`train_alfworld.sh:257`）表示不单独训练它——即论文实验里'重构'用的确实是同一份权重"** | ◐ | 行号 ✓（`:257`）、权重共享 ✓；但"不单独训练"读作"联合训练"是错的：`mem_adaptor_training.py:331-338` `train_memory_adaptor_enabled()` 在 `use_actor_rollout_wg=true` 时**直接 return False**（`:336-337`）→ `rollout_loop.py:534-539` `adaptor_train_buf = None` → `mem_adaptor_rollout.py:746 if adaptor_training_buffer is not None` 不成立 → `ray_trainer.py:1890 if train_memory_adaptor_enabled(self.config):` 整段跳过 | 结论：论文配置下重构 completion **完全不进梯度**，与论文 §3.4（txt:268-269）冲突，见 D1 |
| C52 | §3 | 检索 `top_k=3` 但送进重构 prompt 默认只取 `retrieval_top_k=1` 条（yaml:557） | ✓ | yaml:557 `retrieval_top_k: 1   # take top-k retrieved (S_old,P_old) hits; one batched generate`；`mem_adaptor_rollout.py:586 top_k = max(1, int(ma["retrieval_top_k"]))`、`:627 pairs = _retrieved_state_principle_pairs(ev, top_k)` | 论文 Appendix C Figure 8（txt:1433-1437）的模板也只有单个 `{s_old}/{p_old}`，与代码一致、与正文 Eq.3 不一致 |
| C53 | §3 | 效用闭环：命中 +1 / 成功 +1（`experience_utility.py:39`、`:59`；由 `memory_manager.py:254`、`:279` 触发写回） | ✓ | `experience_utility.py:39 def collect_memory_ids_from_info_list`、`:59 def episode_success_from_batch`；`memory_manager.py:254 _apply_retrieval_utility_updates`（被 `:442` 调用）、`:279 _apply_episode_utility_updates` | |
| C54 | §3 | 效用分低于 `prune_score_threshold`（**默认 0.3**）且用满 `min_uses_before_prune`（默认 3）次会被**定期物理删除**（`milvus_store.py:613`） | ◐ | `:613 def prune_low_utility_memories` ✓、`min_uses_before_prune: 3`（yaml:463）✓；但 `prune_score_threshold` 基础默认是 **0.35**（yaml:462），0.3 来自 `train_alfworld.sh:72` / `train_webshop.sh:70`；且 `prune_every_n_global_steps: 0   # 0 = disabled`（yaml:461）基础默认**不剪枝**，脚本设 20（alf:71 / web:69） | 两处默认值问题 |
| C55 | §5 | "outcome reward 的 0/10 具体赋值点未验证" | ◐ | 实际可核实且成立：`environments/env_package/alfworld/envs.py:48-53` `reward = 10.0 * float(info['won'])`（text 模式）；`env_package/webshop/envs.py:50` `reward = 10.0` / `:53 reward = 0`；调用链 `env_manager.py:219-221` 导入为 `self._compute_reward`、`:376` 调用 | 文档诚实标注了未验证，但结论应升级为已验证 |
| C56 | §5 | `weight_outcome=1.0` / `weight_format=0.1` 量级吻合 | ✓ | yaml:261、:263；`train_alfworld.sh:190-191`、`train_webshop.sh:179-180` | |
| C57 | §5 | 仓库里没有与 "RL + Raw Memory" / "w/o reconstruction" 消融行一一对应的独立脚本 | ✓ | `run_scripts/` 只有 `train_alfworld.sh`、`train_webshop.sh`、`memory_eval_helpers.sh`（71 行，只处理 `MEMORY_ENABLED`/`RETRIEVAL_MODE` 提示词切换）；`examples/` 只有 `data_preprocess` | |
| C58 | §5 | 仓库内没搜到锁/事务相关代码 | ✓ | `grep -rn "threading.Lock / filelock / FileLock / multiprocessing.Lock / fcntl / flock" agent_system/memory/*.py` 零命中 | |
| C59 | §5 | `RemoteHTTPMemoryStore` 走 HTTP backend | ✓ | `memory_store.py:80 class RemoteHTTPMemoryStore`；`:211 MemoryStoreDispatcher`、`:237-254` 按 `backend` 分流；yaml:408 `backend: milvus` 默认，脚本未覆盖 | |
| C60 | §6-1 | 论文里出现该标签的所有位置统一写 `<retrieve_memory>` | ✓ | txt:254（§3.4）、txt:1228（A.1）、txt:1367（Fig.5）、txt:1419（Fig.6）、txt:1457（Fig.9）；全文 grep `retrieve_memory` 与 `memory_retrieve` 只有这 5 处，无 `<memory_retrieve>` | |
| C61 | §6-1 | 引 "**Appendix A.2** valid `<retrieve_memory>…</retrieve_memory>` blocks" | ✗ | 该句在 **Appendix A.1**（txt:1228）；A.2 标题在 txt:1230-1232 | 与 P41 同源错误 |
| C62 | §6-1 | Figure 5/6 = ALFWorld/WebShop 系统提示词；Figure 9 = 轨迹摘要提示词 | ✓ | txt:1371 `Figure 5: Agent system prompts used in ALFWorld.`、txt:1423 `Figure 6:`、txt:1476 `Figure 9: Prompt used for offline trajectory summarization.` | |
| C63 | §6-1 | 代码里唯一真正生效的常量是 `<memory_retrieve>` / `</memory_retrieve>`（yaml:517-518），并被正则解析/格式奖励/摘要提示词共同使用 | ✓ | yaml:517-518；格式奖励 yaml:285-286 `memory_open_tag: ${env.memory.retrieval_query_open_tag}`；解析 `memory_manager.py:392-394`；摘要提示词 `experience_summarizer.py:104` `- Do not copy raw <think>, <action>, or <memory_retrieve> text.` | |
| C64 | §6-1 | "这个词序在 `agent_system/memory/prompt_defaults.py`…里全部一致" | ◐ | `prompt_defaults.py`（全 19 行）只有 `{open_tag}` / `{close_tag}` 占位符，**没有字面标签**；字面标签在 yaml:517-518 与 `experience_summarizer.py:104` | 该文件不能作为词序证据 |
| C65 | §6-1 | `mem_adaptor_rollout.py` 判定协议标签的正则 `r"<\s*(?:redacted_thinking\|action\|memory_retrieve\|memory)\b"` | ✓ | `mem_adaptor_rollout.py:91` 逐字一致 | |
| C66 | §6-2 | `mem_adaptor.use_actor_rollout_wg` 基础默认 `false`（yaml:556，注释 `false -> second Role on mem_adaptor_pool`） | ✓ | yaml:556 逐行一致 | |
| C67 | §6-2 | 配上 `train_memory_adaptor: true` 会启动独立 GRPO 训练的 MemAdaptor（独立 WorkerGroup、独立 KL 锚点、独立奖励塑形），整份 `mem_adaptor_training.py` 为此路径而写 | ✓ | yaml:566 `train_memory_adaptor: false`、:569-575（独立 model.path / ref_model）、:577-579（`actor_use_kl_loss` 等）、:644-658（`grpo_reward` / `grpo_english_shaping`）；`mem_adaptor_training.py:331-338`、`:341` | |
| C68 | §6-3 | 代码里是两次完全解耦的 `generate_sequences`，中间 detokenize→拼观察→重新 tokenize，各自独立 prompt | ✓ | `mem_adaptor_rollout.py:725-735`（独立 dataproto + `apply_chat_template` `:347-352`）与 `rollout_loop.py:444`；`:456` `batch_decode` | |
| C69 | §6-3 | 重构这次调用默认**不算作** `env.max_steps` 步数消耗 | ✓ | `rollout_loop.py:528`（`episode_lengths` 只在 `counted_step_mask` 上 +1，发生在 `:520-528`）先于 `:552` 的 adaptor 调用，adaptor 路径不触碰 `episode_lengths` | |
| C70 | §4 边界 | 记忆系统本体 = 向量库 + embedding 客户端 + 检索/去重 + 摘要 prompt/解析 + 效用剪枝，不依赖策略权重即可独立运作 | ✓ | 与代码结构一致；`mem_adaptor_*` 确实依赖 WorkerGroup 权重（`:587-589`） | 划分合理 |

**code-architecture.md 小计：✓ 59 / ✗ 4 / ◐ 7 / ? 0**（共 70 条）

### 2.3 两份文档共同的重大漏项（不计入上表判定）

| 漏项 | 论文证据 | 代码证据 |
|---|---|---|
| **冷启动 SFT 阶段整段缺失** | §4.1 txt:569-574；Appendix A.4 txt:1286-1307（GPT-5.1 从 AgentGym[38] 造 2×200 例；SFT 2 epoch、lr 1e-5、有效 batch 2；"GPT-5.1 is used only for offline cold-start data construction and is not involved in RL training or evaluation"）；消融 txt:720-721（cold-start 模型单独只有 7.6%） | `scripts/cold_start_sft.sh`：`data.train_batch_size=2`(:57)、`optim.lr=1e-5`(:63)、`trainer.total_epochs=2`(:70)；`scripts/build_alfworld_coldstart_data.py:573` `--retrieve-model` 默认 `gpt-5.1`；另有 `build_webshop_coldstart_data.py`、`build_summarizer_coldstart_data.py`、`extract_memory_records.py` |
| **format reward 的实际实现从未被读** | txt:253-255 | `agent_system/reward_manager/format_reward.py`（575 行）：三个等权项是 think/action/memory（yaml:273-275），"英文"是 CJK 命中即把 format 分**整体置 0** 的硬门（`:204-209`、自测 `:527-528`），`max_think_segments: 0`（yaml:266）表示 think 块**无上限** |

## 3. 步骤清单 — 论文侧

系统边界标记：**[MEM]** 记忆系统本体 / **[AGENT]** 策略/agent 决策链路 / **[TRAIN]** 训练框架 / **[OFFLINE]** 离线预处理。

| # | name（论文自己的叫法） | trigger | in → out | llm | store | prim | 边界 |
|---|---|---|---|---|---|---|---|
| 1 | Cold-Start Dataset Construction (A.4) | 离线一次（RL 之前） | AgentGym seed 轨迹 → 200 条 memory-augmented 交互轨迹 + 200 条 trajectory→memory 摘要对 / benchmark | GPT-5.1 ×2 角色（生成 retrieval query；把源轨迹蒸馏成可复用 guidance），txt:1288-1301 | - | P-EXTRACT | [OFFLINE] |
| 2 | brief cold-start stage / SFT (§4.1, A.4) | 离线一次 | 冷启动数据 → 协议对齐后的 πθ（2 epoch, lr 1e-5, batch 2） | no（梯度） | - | P-TRAIN | [OFFLINE] |
| 3 | GRPO rollout（group sampling, A.2） | 每 training step（G=8/prompt，16 groups，128 并行 env） | 任务 T → G 条轨迹 τi | πθ 每 step 至少 1 次 | - | P-TOOLLOOP | [AGENT] |
| 4 | retain only 50% of the trajectories (A.3) | 每 GRPO 周期（"periodically"） | 组内轨迹 → 50% 保留（成功/失败均衡，余量随机） | no | - | P-INTAKE | [MEM] |
| 5 | Memory Initialization / distill trajectories (§3.1, A.3, Appx C) | episode 完成后、周期性 | 完整轨迹 → `(ei, osrc_i)` | 1 次/轨迹，蒸馏者=同一个 πθ（txt:1264-1267）；prompt=Figure 9（txt:1449-1477） | - | P-EXTRACT | [MEM] |
| 6 | BGE-M3 encoding (§4.1, A.3) | 每次写入 | 条目文本 → 稠密向量 | no（编码器） | Milvus | P-EMBED | [MEM] |
| 7 | Write-time deduplication (A.3) | 每次插入前（WebShop 开 / ALFWorld 关） | 新条目向量 → 保留 or skip（max cos > θsim=0.85） | no | Milvus kNN probe | ~P-DEDUP | [MEM] |
| 8 | insert into B (§3.1, A.3) | 每次写入 | `(ei, osrc_i)` → Milvus 行 | no | Milvus | P-PERSIST | [MEM] |
| 9 | track empirical utility（EvolveR 式 Laplace 分，§3.1/A.3） | 每次检索命中 + 每 episode 结束 | 命中/成功计数 → `s(p)=(c_succ+1)/(c_use+2)` | no | Milvus metadata | P-UTILITY **[NEW]** | [MEM] |
| 10 | periodically prune low-utility entries (A.3) | 周期性（论文未给周期） | s(p)<θprune=0.3 且 c_use≥3 → 删除 | no | Milvus delete | ~P-EVICT | [MEM] |
| 11 | Retrieval —— agent decides whether to query (§3.2 Step 1) | 每 step（A.3 txt:1261 另说 "at each step"，见 D12） | `ht` → 是否检索 + context-derived query `qt` | 与 think/action 同一次 πθ 采样 | - | ~P-QUERYPARSE | [AGENT]（决策）→[MEM]（接单） |
| 12 | `Et = R(qt, B)`，top-k=3 cosine (Eq.1, §4.1, A.3) | 每次触发检索 | `qt` → k=3 条 `(et,i, osrc_t,i)` | no | Milvus | P-DENSE | [MEM] |
| 13 | Retrieval-time deduplication (A.3) | 每次检索 | 大候选池 → 贪心去重 → top-k | no | - | P-DEDUP | [MEM] |
| 14 | reconstruction context `xrecon = T ⊕ ht ⊕ ⋃(et,i,osrc_t,i)` (Eq.3) | 每次检索命中 | T + ht + k 条二元组 → 重构 prompt | no | - | P-ASSEMBLE | [AGENT] |
| 15 | Critique & Contextual Memory Reconstruction `gt ~ πθ(·\|xrecon)` (Eq.4, §3.3) | 每次检索命中 | 重构 prompt → guidance `gt` 或 `<EMPTY>`（critique 已 folded in） | 1 次 πθ 采样；prompt=Figure 8（txt:1428-1445） | - | P-REWRITE | [AGENT] |
| 16 | fallback `g̃t = pself if gt=<EMPTY>` (Eq.5, Figure 7) | 重构判为不适用时 | `gt` → `g̃t` | no | - | ~P-ASSEMBLE | [AGENT] |
| 17 | Action Generation `at ~ πθ(·\|T,ht,g̃t)` (Eq.6) | 每 step | T+ht+g̃t → 可执行动作 | 1 次 πθ 采样 | - | P-GENERATE | [AGENT]（记忆系统边界之外） |
| 18 | Reward Design + Policy Update (§3.4, Eq.7-10) | 每 training step | τi → `R=Routcome+0.1·Rformat`；Ai 分给 τi 全部 token（含 reconstruction） | no（梯度） | - | P-TRAIN | [TRAIN] |

**PAPER-SEQ**（`>` 顺序，`+` 并行，`~` 可选/条件，`||` 分隔写入/检索）：
`[离线] P-EXTRACT > P-TRAIN ; [训练态写入] P-INTAKE > P-EXTRACT > P-EMBED > ~P-DEDUP > P-PERSIST > P-UTILITY > ~P-EVICT > P-TRAIN || ~P-QUERYPARSE > P-DENSE > P-DEDUP > P-ASSEMBLE > P-REWRITE > ~P-ASSEMBLE > P-GENERATE`

## 4. 步骤清单 — 代码侧

| # | name（代码里的叫法） | trigger | in → out | llm | store | prim | 边界 |
|---|---|---|---|---|---|---|---|
| 1 | `scripts/build_{alfworld,webshop,summarizer}_coldstart_data.py` | 手动调用 / 离线一次 | AgentGym 轨迹 → cold_start parquet | GPT-5.1（`--retrieve-model` 默认，:573） | jsonl | P-EXTRACT | [OFFLINE] |
| 2 | `scripts/cold_start_sft.sh` | 离线一次 | parquet → cold-start ckpt（2 epoch / 1e-5 / bs 2，:57,63,70） | no | - | P-TRAIN | [OFFLINE] |
| 3 | `actor_rollout_wg.generate_sequences` #1（`rollout_loop.py:444`） | 每 turn | 观察 → `<think>+<action>` 或 `<memory_retrieve>query</memory_retrieve>` | 1 次批量 | - | P-TOOLLOOP + ~P-QUERYPARSE | [AGENT] |
| 4 | `MemoryManager.extract_query`（`memory_manager.py:389`） | 每 turn（agentic 模式） | 响应文本 → query 或 None（正则，`max_query_chars=1200`） | no | - | P-QUERYPARSE | [MEM] |
| 5 | `envs.step_with_memory`（`rollout_loop.py:460` → `env_manager.py:318/734`） | 每 turn | 分流：env action 走 `env.step`；memory query 不推进 env（`env_step_mask=0`） | no | - | —（路由） | [AGENT]/[MEM] 粘合层 |
| 6 | `MilvusMemoryStore.retrieve`（`milvus_store.py:383`） | 每次 query | query → 远端 BGE-M3 向量 → cosine top_k=3，`min_score=0.0`，`only_successful=False` | no | Milvus-Lite（FLAT/COSINE） | P-EMBED + P-DENSE | [MEM] |
| 7 | retrieval dedupe（`milvus_store.py:389-392,440-445` + `memory_text_dedupe.py:26`） | 每次检索（WebShop 0.85 开 / ALFWorld `null` 关，`train_alfworld.sh:135`） | prefetch≥10 → 贪心去重 → `[:top_k]` | no | - | ~P-DEDUP | [MEM] |
| 8 | `_apply_retrieval_utility_updates`（`memory_manager.py:254`，由 `:442` 调用） | 每次检索命中 | 命中 memory_id → `utility_use_count+1`，重算 Laplace 分 | no | Milvus update | P-UTILITY **[NEW]** | [MEM] |
| 9 | `_format_memory_prompt` + `_append_external_memory`（`memory_manager.py:535` / `base.py:217`） | 每次检索 | RetrievedMemory[] → `<memory>--- Memory k --- Situation/Principle</memory>` 拼进**下一步**观察 | no | - | P-ASSEMBLE | [MEM]→[AGENT] |
| 10 | 零命中注入 `empty_retrieval_message`（`memory_manager.py:432-440`） | 检索 0 命中时 | → `"(No validated memory principle applies; rely on observation and reasoning.)"` | no | - | ~P-ASSEMBLE | [MEM] |
| 11 | `maybe_apply_memory_adaptor` → `wg.generate_sequences`（`rollout_loop.py:552` → `mem_adaptor_rollout.py:556,732`） | 每个"记忆被注入"的 turn（含零命中；`schedule=on_memory_only`，`:192-207`） | `{task,s_curr,s_old,p_old}`（模板 yaml:610-630 ≙ 论文 Fig.8）→ adapted principle 或 `<EMPTY>` | 1 次批量（`retrieval_top_k=1` → 每 env 1 行）；权重=主 actor（`:587-589`） | - | P-REWRITE | [AGENT]（文件在 `memory/` 下） |
| 12 | `_patch_one_obs_text` / `_splice_out_memory_block`（`mem_adaptor_rollout.py:494` / `:460`） | 同上 | 原地替换 `<memory>` 内容；`<EMPTY>` 则删块并追加兜底句 | no | - | P-ASSEMBLE | [AGENT] |
| 13 | `actor_rollout_wg.generate_sequences` #2（下一轮 `rollout_loop.py:444`） | 每 turn | 改写后的观察 → 环境动作 | 1 次批量 | - | P-GENERATE | [AGENT] |
| 14 | `maybe_write_rollout_memories`（`rollout_loop.py:604` → `base.py:211` → `memory_manager.py:458` → `experience_summarizer.py:1154`） | 每 rollout batch，**仅 `is_train=True`** | 全批轨迹 → 待蒸馏候选 | no | - | P-INTAKE | [MEM] |
| 15 | `_select_env_indices_balanced_success_fail`（`experience_summarizer.py:490`，调用于 `:1288-1296`） | 每 rollout batch | 每个 GRPO group 保留 `round(n·0.5)` 条，成功/失败均衡 | no | - | P-INTAKE | [MEM] |
| 16 | `_summarize_batch_self`（`experience_summarizer.py:785` → `:820`） | 每 rollout batch | 轨迹文本（结构化压缩后）→ JSON `{"memories":[{situation, memory}]}` | 1 次批量，复用 actor 权重（base 默认 `mode: none`，脚本设 `self`；`teacher` 走 `:659` 外部 API） | - | P-EXTRACT | [MEM] |
| 17 | JSON 解析 + 重试 + `MemoryRecord` 构造（`:1340` while / `parse_max_attempts=3` / `types.py:12-31`） | 每 rollout batch | JSON → MemoryRecord（`state_text`←situation，缺失用占位符；初始 `value=0.5`） | 失败时最多再 2 次 | - | P-EXTRACT | [MEM] |
| 18 | `add_records` → `_embed_texts` → `RemoteEmbeddingProvider`（`milvus_store.py:320,824,52`） | 每次写入 | 文本 → 1024 维 bge_m3 向量（远端 OpenAI 兼容 API，未配 URL 直接报错 `:64`） | no | Milvus | P-EMBED | [MEM] |
| 19 | insert dedupe：batch 内（`:343`）+ `_neighbor_has_similar_memory_text`（`:199`，调用于 `:346`） | 每次插入前（WebShop 0.85 / ALFWorld `null`，`train_alfworld.sh:136`） | 新向量 → 保留 or skip | no | Milvus kNN probe（limit 10） | ~P-DEDUP | [MEM] |
| 20 | Milvus-Lite insert（19 字段 flat schema，`milvus_store.py:785-822`） | 每次写入 | MemoryRecord → 集合行 | no | Milvus-Lite | P-PERSIST | [MEM] |
| 21 | `_apply_episode_utility_updates`（`memory_manager.py:279` + `experience_utility.py:39,59`） | 每 rollout batch（按 episode 成败） | 该轨迹用过的 memory_id → `utility_succ_count+1` | no | Milvus update | P-UTILITY **[NEW]** | [MEM] |
| 22 | `prune_low_utility_memories`（`milvus_store.py:613`） | 每 N 个 global step（base 默认 `0`=关闭；脚本 `20`） | s<0.35(base)/0.3(脚本) 且 uses≥3 → 物理删除 | no | Milvus delete | ~P-EVICT | [MEM] |
| 23 | format + episode reward → GRPO（`reward_manager/format_reward.py`、`episode.py`、`ray_trainer.py`） | 每 training step | τi → advantage → 更新 actor（**adaptor completion 不在其中**，`ray_trainer.py:1890` gate） | no | - | P-TRAIN | [TRAIN] |
| 24 | （代码有、论文未用）`mem_adaptor_training.py` 独立 adaptor GRPO | 每 training step，需 `use_actor_rollout_wg=false` + `train_memory_adaptor=true` | adaptor rows → 独立 GRPO（独立 KL 锚点、english/identical/step 三种 shaping，yaml:644-670） | no | - | ~P-TRAIN | [TRAIN] |

**CODE-SEQ**：
`[离线] P-EXTRACT > P-TRAIN ; [每 rollout batch 写入] P-INTAKE > P-EXTRACT > P-EMBED > ~P-DEDUP > P-PERSIST > P-UTILITY > ~P-EVICT > P-TRAIN || [每 turn 检索] ~P-QUERYPARSE > P-EMBED > P-DENSE > ~P-DEDUP > P-UTILITY > P-ASSEMBLE > P-REWRITE > P-ASSEMBLE > P-GENERATE`

**系统边界一句话**：记忆系统本体只有 `agent_system/memory/{milvus_store, memory_store, memory_manager, experience_summarizer, experience_utility, memory_text_dedupe, types}.py` —— 本地 Milvus-Lite 向量库、远端 BGE-M3 embedding 客户端、cosine 检索与两处去重、轨迹→JSON 蒸馏的 prompt 与解析、Laplace 效用打分与剪枝；而"批判+重构"（`mem_adaptor_rollout.py` / `mem_adaptor_training.py`，虽然文件放在 `memory/` 目录下）、检索触发决策、动作生成、GRPO 更新全部跑在策略权重上，属 agent / 训练框架一侧。

## 5. 论文↔代码分歧

| # | 分歧 | 分类 | 论文证据 | 代码证据 |
|---|---|---|---|---|
| D1 | **重构 token 的信用分配**：论文说轨迹优势同等分给"思考、重构、动作生成"所有 token；代码在论文配置下重构 completion 完全不进梯度 | 两边都有但行为不同 | txt:268-269 `The trajectory-level advantage Ai is assigned to all tokens in τi, providing shared credit to thinking process, reconstruction and action generation.`；txt:238 `Reconstruction and action generation share parameters θ and are optimized jointly.` | `mem_adaptor_training.py:336-337`（`use_actor_rollout_wg=true` → `train_memory_adaptor_enabled()` return False）→ `rollout_loop.py:534-539` `adaptor_train_buf = None` → `mem_adaptor_rollout.py:746` 缓冲不写 → `ray_trainer.py:1890` 整段 adaptor GRPO 跳过；脚本 `train_alfworld.sh:256-257` / `train_webshop.sh:245-246` 正是该配置 |
| D2 | **检索标签词序相反** | 两边都有但参数不同 | `<retrieve_memory>`：txt:254, 1228, 1367, 1419, 1457（全文仅此 5 处） | `<memory_retrieve>`：yaml:517-518、`experience_summarizer.py:104`、`mem_adaptor_rollout.py:91`、格式奖励 yaml:285-286 引用同一常量 |
| D3 | **format 三条标准的构成不同**：论文 (1) think+action 合一条 / (2) 检索频率 / (3) strict English；代码三个等权项是 think / action / memory，"英文"是硬门不是加权项 | 两边都有但行为不同 | txt:253-255 | yaml:273-275 `weight_think/action/memory: 1.0`；`format_reward.py:266-268`（三项加权和 `/denom`）；`:204-209` 出现 CJK 直接 `return reward=0.0`；判定正则只查 `[一-鿿]`（`:96`），自测 `:527-528` |
| D4 | **"exactly one valid `<think>` per step"** 未被强制 | 两边都有但参数不同 | txt:253-254 `(1) exactly one valid <think> and <action> block per step` | yaml:266 `max_think_segments: 0`（无上限）+ `format_reward.py:70-72` `at_most <= 0` 关闭上界 → think 只要求 ≥1；`<action>` 才是恰好 1（yaml:267） |
| D5 | **检索频率 1–5 的硬/软性**：base 默认根本不要求检索 | 两边都有但行为不同 | txt:254、txt:1228（"between one and five times per episode"） | yaml:272 `require_memory_retrieve: false` → `format_reward.py:260-262` 走 `_optional_memory_ok`（0 次也满分，且 `w_mem=0` 把 memory 项踢出分母）；两个训练脚本设 `require_memory_retrieve=True`（alf:192 / web:181）才真正强制 `[1,5]`（`:255-258`） |
| D6 | **k=3 检索 vs 只有 1 条进重构**（论文正文与自身附录也不一致） | 两边都有但参数不同 | 正文 Eq.3 txt:205-215 拼接 `⋃_{i=1..k}`、§4.1 txt:580-581 top-3；**但** Appendix C Figure 8 模板 txt:1433-1437 只有单个 `{s_old}` / `{p_old}` | yaml:557 `retrieval_top_k: 1`；`mem_adaptor_rollout.py:586,627`；代码站在附录一侧 |
| D7 | **零命中仍触发一次重构调用** | code-only | §3.2 Step 1 txt:186-188 只在 `If triggered, retrieval returns relevant experiences Et` 之后进重构 | `memory_manager.py:432-440`（零命中注入 `empty_retrieval_message`）→ `mem_adaptor_rollout.py:203-207` `bool(injected) or has_ret` 为真 → `:636-640` `pairs = [("", "", "")]`，仍发一次 `generate_sequences` |
| D8 | **蒸馏器可以不是 πθ** | code-only | A.3 txt:1264-1267 明写蒸馏由 `the policy model πθ` 做 | yaml:419 base 默认 `mode: none`；`experience_summarizer.py:659 _summarize_batch_teacher` 走外部 OpenAI 兼容 API（yaml:446-457 的 `openai_api` 块） |
| D9 | **重构模块可与主策略解耦并单独 GRPO 训练** | code-only | §3.1 txt:175-176 / §3.2 txt:192 只讲 unified policy，通篇无第二种可能 | yaml:556 base 默认 `use_actor_rollout_wg: false`（`second Role on mem_adaptor_pool`）+ yaml:566 `train_memory_adaptor` + 整份 `mem_adaptor_training.py`（492 行：独立 WorkerGroup / 冻结 KL 锚点 / `grpo_english_shaping` / `grpo_identical_rewrite_penalty` / `grpo_step_reward_shaping`，yaml:644-670） |
| D10 | **剪枝阈值与剪枝开关** | 两边都有但参数不同 | txt:1280-1281 `θprune (default 0.3)`、`min_uses_before_prune (default 3)` | yaml:462 `prune_score_threshold: 0.35`（**base 默认 0.35**）；yaml:461 `prune_every_n_global_steps: 0   # 0 = disabled`（**base 默认不剪枝**）；`train_alfworld.sh:71-72` / `train_webshop.sh:69-70` 才设成 20 / 0.3；`min_uses_before_prune: 3` 两边一致（yaml:463） |
| D11 | **检索时去重在 ALFWorld 也被关掉** | 两边都有但行为不同 | A.3 txt:1276-1278 把 retrieval-time dedup 写成无条件的第 (2) 阶段；只给 write-time dedup 标了"WebShop 开 / ALFWorld 关"（txt:1275-1276） | `train_alfworld.sh:135` `memory_text_retrieval_dedupe_similarity_threshold=null`（与 `:136` 的 insert dedupe 一起关）；`train_webshop.sh` 两者都不覆盖 |
| D12 | **检索触发模式**：论文自身 §3.2（agentic）与 A.3（"at each step"）打架；代码两种都实现了 | 两边都有但行为不同 | §3.2 txt:186-188 agentic；A.3 txt:1261-1262 `at each step` | yaml:389 base 默认 `retrieval_mode: fixed  # fixed: retrieve on every observation`；`train_alfworld.sh:46` / `train_webshop.sh:43` 覆盖为 `agentic`；另有 `retrieval_mode_phases`（yaml:390-391）支持按 global_step 切换 |
| D13 | **记忆条目字段远多于二元组** | code-only | §3.1 txt:151-155 `mi = (ei, osrc_i)` 二元组 | `types.py:12-31` 另存 `action_text` / `reward` / `success` / `retrieval_count` / `last_used_step` / `value` / `value_source` 等；Milvus 集合 19 字段（`milvus_store.py:793-811`） |
| D14 | **每条轨迹默认只蒸馏 1 条记忆** | code-only | 论文未给该数值 | yaml:423 `num_memories_per_trajectory: 1`；Figure 9 模板 txt:1461 的 `{num_memories}` 占位符正对应该配置 |
| D15 | **检索键是 memory_text 而非 source observation** | code-only | Eq.1 txt:158-165 只写 `R(qt,B)`，未指明用哪一侧做索引 | yaml:478 `retrieve_key: memory_text  # memory_text \| state_text`；`milvus_store.py:325` 按 `retrieve_key` 取字段做 embedding |
| D16 | **Embedding 必须是远端服务，本地不跑模型** | code-only | §4.1 txt:580-581 / A.3 txt:1260 只说"用 BGE-M3" | `milvus_store.py:52 RemoteEmbeddingProvider`、`:64` 未配 `embedding_api_url` 直接 `raise ValueError`；两个脚本指向 `http://localhost:8001/v1`（alf:51 / web:48） |
| D17 | **写入去重比较符**：论文 "exceeds"（>），代码 `>=` | 两边都有但参数不同 | txt:1274-1275 `if its maximum cosine similarity … exceeds the threshold θsim` | `milvus_store.py:343,346` + `:223` / `memory_text_dedupe.py:33` 全部用 `>= threshold` |

## 6. 新造的 primitive 标签

| 标签 | 含义 | 造它的理由 |
|---|---|---|
| **P-UTILITY**（效用统计：命中/成功计数与平滑打分） | 每次检索命中把 `utility_use_count+1`、每 episode 结束按成败把 `utility_succ_count+1`，并写回 Laplace 平滑分 `s=(c_succ+1)/(c_use+2)`，作为后续剪枝的判据 | 种子词表里没有"非 LLM 的、基于下游任务反馈的条目级计数/打分"这一原语：`P-META` 明确限定为 **LLM 元数据标注**（关键词/标签/参与者/时间），本步全程零 LLM；`P-EVICT` 是删除动作本身，而效用统计在没有开启剪枝时（代码 base 默认 `prune_every_n_global_steps: 0`）仍然持续运行并被写进 Milvus 的 `value` 字段；`P-CONFLICT` 是冲突消解，与"用得好不好"无关。这是 MemHarness（承自 EvolveR）区别于纯写入-检索系统的独立机制，值得单列。 |

## 7. 复核统计

| 文档 | ✓ | ✗ | ◐ | ? | 合计 |
|---|---|---|---|---|---|
| `paper-architecture.md` | 41 | 4 | 7 | 0 | 52 |
| `code-architecture.md` | 59 | 4 | 7 | 0 | 70 |
| **总计** | **100** | **8** | **14** | **0** | **122** |

另有 2 项两份文档共同的重大漏项（冷启动 SFT 阶段整段缺失；format reward 实现从未被读），不计入上表判定，见 2.3 节。

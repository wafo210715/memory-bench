---
title: TransMem 架构文档复核报告
date: 2026-09-05
tags:
  - memory-bench
  - verification
  - transmem
---

# TransMem 架构文档复核报告

> 复核日期 2026-09-05；论文源 `Lei-2026-TransMem-Transforming-Hidden-States-into-Memory-for-Large-Language-Models.txt`（1,639 行，arXiv:2607.29032v1）；代码源 `TransMem` @ `6d7a612`（`6d7a6127967ad44482c958b555d8c83bfb75e9b9`，commit message `vanish`）。
> 复核对象：`paper-architecture.md`（179 行）、`code-architecture.md`（235 行）。同目录 `methodology-flow.md` 是这两份文档的下游派生图，其自身声明"勘误以 verification 为准"，本次只做锚点抽查（见 §2.3），不计入统计。
> `servers/transmem/` 下**没有 .py 文件**——本系统在 memory-bench 侧没有 MCP 适配层，所有代码事实都落在上游仓库。
> 方法：论文断言逐条 `grep -n` 定位到 txt 行号；代码断言逐条 `sed -n` 打开 `file:line` 上下文，控制流断言顺调用链读到调用方。

## 1. 总评

两份文档的**主干机制判断是对的**，而且对这个系统"没有存储、没有检索"的反直觉本质抓得很准：TransMem 就是冻结 backbone 一次前向内部、挂在最后 4 层 decoder 输出端的一小段旁路网络，全仓确实找不到任何向量库 / BM25 / 图 / embedding 依赖，也确实没有任何跨请求持久化。121 条事实性断言里 92 条完全属实，多数引用锚点（`layered.py:43/244/252/327/407/420/453/480/488/512/572`、`transmem.py:212/247/293/359`、`objectives.py:63`、`extract_features.py:115/124-127`、`README.md:148/310`、`.gitignore:224-230`、vanish 删 75 文件 3215 行、45 条提交与作者邮箱）**逐字对得上**，考古部分（仓库是作者私人工作区快照、README 引用的配方脚本被自己删掉）质量很高。

最严重的两个问题都在 `code-architecture.md`：**（a）§2 说 prefill 是"一次不带 TransMem 修正的标准前向"，这是错的**——hook 在 `layered.py:519-520` 就已注册，`layered.py:528` 那次前向里 hook 的 prefill 分支同时完成"读 H_M"和"写修正"（`:512`），文档自己下一句也说 hook 会在这次前向中触发，前后自相矛盾；顺带那条 `layered.py:565` 行号也指错了地方（实为 `:528`）。**（b）§6.5 称 `config_layered_dynamic_gate.json` 与论文 Eq.6 `g=2σ(z)`"精确对应"，漏掉了一个真实的架构级分歧**：论文 Eq.6 写 `W_g ∈ R^{d×d}`、Eq.7 用 `⊙`（逐维向量门控），代码是 `nn.Linear(dim, 1)` 且 `gate_granularity` 被硬性限死为 `"token_scalar"`（`transmem.py:111-114, 213`），参数量差一个数量级；有意思的是论文**附录自己也是标量口径**（"because the gate is token-dependent"，txt:1344-1347），落单的是论文正文。

`paper-architecture.md` 只有一条硬错：§3 的否定式断言"论文没有用『检索（retrieval）』这个词描述这一步"被 txt:432-433 直接证伪（"the gating mechanism facilitates the **retrieval** and utilization of relevant memory representations"）——它的实质判断（没有相似度打分/排序）仍然成立。其余 8 条 ◐ 集中在**引用锚点的出处标错**（把 *Method* 段的句子标成 *Experimental Setup*、把 *Baselines* 段末的 seed=42 标成 *Implementation Details*、B=4 声称出现在 Table 6 但实际只在 Table 13 小节）。两份文档共有的一处措辞错误是"和主干 LLM 结构一样的小 Transformer"——`layers.py:48 to_qwen3_config` 永远造 `Qwen3Config`，Llama3.1-8B backbone 下并不同构，论文 txt:387-389 反而说清楚了。

另有 5 条文档标为"**未验证**"的条目其实是**可以验证的**，本次给出了结论（warm start 是死代码、LoCoMo 从不触发 chunk-wise 等，见 §5 D3/D6 与 C53）。

## 2. 逐条核对表

判定：`✓` 属实 / `✗` 不实 / `◐` 部分属实或需加限定 / `?` 无法核实

### 2.1 `paper-architecture.md`（50 条）

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| P1 | 头部 | arXiv:2607.29032v1，2026-07-31，东南大学+上海AI Lab，AAAI 投稿格式 © 2027 AAAI | ✓ | txt:1-11, 10, 46-47 | 一字不差 |
| P2 | §1 | 已算过的隐状态本身足够当记忆，不需另花计算重新编码整段历史 | ✓ | txt:20 "without repeatedly encoding the preceding context"；txt:74-79；txt:302-306 | |
| P3 | §1 | "一个轻量的、**和主干 LLM 结构一样**的小 Transformer" | ◐ | txt:352-353 "follows the Qwen3 transformer architecture"；txt:387-389 明说 Llama3.1-8B backbone 下 block 仍用 Qwen3 架构 | 只在 Qwen3 backbone 下成立；代码同样固定 Qwen3（见 C5、D5） |
| P4 | §1 | ECSD：同一冻结 LLM，一边只看(E,Q)当老师、一边看完整 C 挂 TransMem 当学生，KL 逼近 | ✓ | txt:192-218；"no separate teacher model is introduced" txt:207-208；ECSD 缩写定义 txt:884-885 | |
| P5 | §1 | 学到的是"如何提炼"的能力而非死记某篇文章 | ✓ | txt:399-404（只在 HotpotQA 训练却泛化到 LoCoMo/MAB） | |
| P6 | §2 | 触发时机：prefill 阶段 | ✓ | txt:157, 175-177 | |
| P7 | §2 | `x_{1:t}=[C;A_≤t]`，`C=x_{1:L}`，`A_≤t=(y_{L+1},…,y_t)` | ✓ | txt:159-163 | |
| P8 | §2 | 引 "The context features H_C are computed during prefill, during which TransMem does not intervene in generation"（**Eq.1、2 之后一段**） | ◐ | 引文 ✓ txt:175-177 | 位置错：该句在 Eq.1（txt:169）之后、Eq.2（txt:188）**之前** |
| P9 | §2 | 存的是原始未压缩隐状态；按段长 n=L/B 切 B 段取每段最后一个 token，`H_M=[h_n^K,…,h_L^K]` | ✓ | txt:243-248；n=L/B 定义在 txt:322-325 | 两处都在 Method>Inference with TransMem 小节内 |
| P10 | §2 | 引 "The size of HM remains small, with the optimal value being only 5, which ensures the sparsity…" | ✓ | txt:248-250 | |
| P11 | §2 | 逐层各自独立一份 H_M，插几层就有几份互不共享 | ✓ | txt:236-239（每层各有 f_m^K / W_Δ^K / f_g^K）+ 上标 K 记号 | 论文没写"不共享"字样，是由记号推得；代码确证（C9） |
| P12 | §2 | 超长上下文：C 切 S 个 chunk，各产 H_M^i，`H_M=Concat(H_M^1,…,H_M^S)` | ✓ | txt:330-341 | 论文自称 "chunk-wise memory **extraction** strategy"，文档写"聚合"；txt:338-339 确有 "aggregating" |
| P13 | §2 | 该段位于"Eq.4 之后、Experiments 之前的最后一段" | ✓ | Eq.4 txt:260；chunk 段 txt:328-345；Experiments txt:347 | |
| P14 | §2 | 论文没有描述"额外调用一个 LLM 去做抽取/摘要"这一步 | ✓ | 全文 grep 无此描述；txt:303-305 反向佐证 "does not store additional information" | 否定式断言，已证伪失败 |
| P15 | §2 | "lightweight inference-time parametric memory module"（Abstract） | ✓ | txt:19-21 | |
| P16 | §3 | Eq.7 写 `t ≥ L+1` 并注 "the memory correction is applied only during answer generation" | ✓ | txt:290-293 | 与代码有一位差，见 D4 |
| P17 | §3 | **论文没有用"检索（retrieval）"这个词描述这一步** | ✗ | txt:432-433 "the gating mechanism facilitates the **retrieval** and utilization of relevant memory representations" | 论文在 Ablation Studies 段正是用 retrieval 描述这一步；实质判断（无显式相似度/排序）仍成立 |
| P18 | §3 | 引 "they first undergo standard autoregressive attention to produce the memory feature h_m" | ✓ | txt:257-259 | |
| P19 | §3 | 没有"检索→反思→再检索"式循环，单次前向 | ✓ | 全文无迭代/多跳描述 | |
| P20 | §3 | 引 "inserting memory modules into only the last four layers"（标注 *Experimental Setup > Implementation Details* 段） | ◐ | 引文 ✓ txt:315-316 | 出处错：该句在 *Method* 段（"TransMem is not applied to all layers…"）；Implementation Details（txt:351-352）用的是另一句 "inserted into the final four transformer layers" |
| P21 | §3 | 引 "memory corrections interact with different stages of the backbone computation"（Appendix > Early Final-Hidden） | ✓ | txt:1133-1134 | |
| P22 | §3 | Eq.4-8 五步链：h_m → Δh=W_Δh_m → g=ασ(W_gh_m/τ), α=2 → ĥ=h+g⊙Δh (t≥L+1) → h^{K+1}=f_θ(ĥ) | ✓ | txt:260, 264-265, 271-278, 290-292, 296-298 | 公式编号 (1)-(8) 分别在 txt:169/188/218/260/265/274/290/298 |
| P23 | §3 | `W_Δ ∈ R^{d×d}`、`W_g ∈ R^{d×d}` 均可学习 | ✓ | txt:254-256, 277-279 | 与代码不符，见 D1 |
| P24 | §3 | 引 "Not every memory shift Δh is useful, and noisy shifts may adversely affect the output" | ✓ | txt:269-271 | |
| P25 | §3 | 纯向量级叠加，不文本化、不重拼 prompt；对比 Introduction "summarizing, retrieving, or storing information outside the current computation" | ✓ | txt:61-63 | |
| P26 | §4 | 引 "During inference, the frozen backbone performs its standard forward computation, while TransMem abstracts a small set of historical hidden states into a memory shift" | ✓ | txt:148-151 | |
| P27 | §4 | 图注"仅最后 4 层最优，Table 4" | ✓ | txt:888-900（Last-2 53.14 / **Last-4 54.11** / Last-8 53.27 / Middle 28-31 52.85 / 22-25 52.32 / 18-21 51.54 / 12-16 51.11） | |
| P28 | §4 | Figure 2(a)=推理，2(b)=训练师生对照 | ✓ | txt:280-287 | |
| P29 | §4 | forward KL 只更新 TransMem，backbone 梯度为 0 | ✓ | txt:209-218 + txt:224-226 "The backbone receives no parameter updates" | |
| P30 | §4 | 论文没有说调用方怎么发起请求、传什么参数、返回什么格式 | ✓ | 全文无接口/协议描述 | |
| P31 | §5 | Figure 1/2/3/4 是图片，本次未做图像解析 | ✓ | 论文确有 4 图：txt:81, 280, 951, 1353 | 自陈式限定，成立 |
| P32 | §5 | Table 1/2 文本抽取列错位，`-4.11`/`+0.19` 等穿插在数字中间 | ✓ | txt:445-530（如 txt:452 `36.68-4.11`、`40.98+0.19` 与列名完全错位） | |
| P33 | §5 | Table 3（消融）抽取清晰、已核对 | ✓ | txt:836-846（54.11 / 53.09 / 40.79） | |
| P34 | §5 | Table 4 的层区间怎么选出来的没说明，也没测更浅区间（如 0-4） | ✓ | txt:888-900 最浅为 Middle 12-16；txt:870-882 只给结论不给选取依据 | |
| P35 | §5 | 引 Table 8 "the final row … is included as a reference rather than a directly controlled comparison" | ✓ | txt:1073-1077 | |
| P36 | §5 | Figure 3"只给出定性结论…没有报告 GPU 型号、batch size、**是否分离 prefill/decode 计时**" | ◐ | txt:711-713 明写 "We report the additional latency introduced by the memory module, **excluding the frozen backbone prefill computation**"；txt:713-722 给了 10K→100K 上下文与 δ-mem "nearly 100 GFLOPs per 10k" 的定量描述 | 计时口径**已说明**；GPU 型号/batch 确未在 Figure 3 处复述（训练用 A100 见 txt:353-354）；"只给出定性结论"也偏重 |
| P37 | §6 | B=5 vs B=4 是论文自身内部矛盾 | ✓ | txt:248-250（"optimal value being only 5"） vs txt:1397 "trained with B = 4"、txt:1406 "retain B = 4 as the default" | 文档最有价值的发现之一 |
| P38 | §6 | "要到 Appendix 里 **Table 6**/13 等零散位置才第一次看到 B=4 字样" | ◐ | 全文 "B = 4" 仅出现在 txt:1397、1406（均属 *Sensitivity to the Number of Memory Segments* / Table 13 小节） | Table 6 小节（txt:1020-1055）**没有** B=4；主结果部分确实全程只用符号 |
| P39 | §6 | B=4 是作为消融对象出现（"we vary only B at inference time"），未被正式声明为主结果固定值 | ✓ | txt:1397-1398 | |
| P40 | §6 | 门控温度 τ 从未给出具体数值 | ✓ | τ 仅见 txt:275, 277, 1059，三处均无数值 | 否定式断言，实际证伪失败 |
| P41 | §6 | Gate Parameterization 比较三种：g=1 / g=2σ(z) / g=3σ(z)−1，但没报 τ | ✓ | txt:1056-1062；Table 7 数据 txt:1296-1310（53.09 / 54.11 / 54.01） | |
| P42 | §6 | "w/o Transformer Block"实现方式没描述，分数 40.79"**接近**纯 backbone 基线" | ◐ | 实现方式确未描述（txt:426-436 只给结论）；但 40.79 与 Table 1 的 Qwen3-4B-Instruct 基线 40.79（txt:449）**完全相等**，不是"接近" | 相等这一点比"接近"更值得写——说明该消融等于关掉整个模块 |
| P43 | §6 | "是否使用某种初始化策略完全没有提及" | ◐ | *Method*/*Experimental Setup*（txt:146-355）确实没提 | 但 Appendix Table 7 图注 txt:1064-1065 明写 "All dynamic gates are initialized at g = 1"（代码 `gate_init=1.0` 与之一致，见 C41） |
| P44 | §6 | 引 "All experiments are conducted with a fixed random seed of 42"（标注 *Implementation Details* 段） | ◐ | 引文 ✓ txt:416-417 | 出处错：该句落在 *Baselines* 段**末尾**；*Implementation Details* 从 txt:418 才开始 |
| P45 | §6 | 所有表格看起来是单次运行，没有标准差/置信区间 | ✓ | 全文唯一的 std 是 Figure 4/Table 11 的**答案 token 维**描述统计（txt:1345-1352），非跑次方差 | |
| P46 | §6 | "Table 4 里 53.14 vs 54.11" | ✓ | txt:891-900 | |
| P47 | §6 | LoCoMo 约 16K token | ✓ | txt:371-373 | |
| P48 | §6 | MemoryAgentBench 一句 "many examples exceeding 256K tokens" | ✓ | txt:378-380、393-395 | |
| P49 | §6 | 三个 backbone：Qwen3-4B、Qwen2.5-14B、Llama3.1-8B | ✓ | txt:419-423 | |
| P50 | §6 | 论文没交代 LoCoMo/HotpotQA 是否真的触发了 chunk-wise 溢出策略 | ✓ | 全文无此交代 | **代码回答了这个问题**：LoCoMo 从不触发，见 D6 |

### 2.2 `code-architecture.md`（71 条）

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| C1 | 头部 | origin = github.com/Haodong-Lei-Ray/TransMem；HEAD=6d7a6127…；message `vanish`；2026-08-09 | ✓ | `git remote -v`；`git rev-parse HEAD`；`git log -1` | |
| C2 | 头部 | 核心逻辑集中在 transmem.py / layered.py / extract_features.py / train_inloop.py | ✓ | 四文件分别 393 / 702 / 1386 / 1203 行，且互为调用链 | |
| C3 | 头部 | 不是独立进程/数据库，没有任何跨请求持久化，前向结束即丢 | ✓ | 全仓 grep 无 faiss/chromadb/qdrant/sentence_transformers/bm25/networkx/neo4j；唯一落盘是训练侧 Stage-0 `.pt`（extract_features.py:135-147） | 关键的反直觉判断，成立 |
| C4 | §1 | 默认切成 4 段，每段取最后一个 token | ✓ | `layered.py:119 n_mem: int = 4`；`extract_features.py:115-127` | |
| C5 | §1 | "结构和主干 LLM **完全一样**的小 Transformer block" | ◐ | `layers.py:48 to_qwen3_config` 永远构造 `Qwen3Config`；仓库存在 `config_layered_llama31_8b_dynamic_gate.json` | Llama backbone 下并不同构；`layers.py:49` 自己的注释"使 block 与 backbone 同款"同样只在 Qwen 系成立 |
| C6 | §1 | 只有 1 层 | ✓ | `layered.py:107 block_depth: int = 1` → `block_config()` 传 `depth=self.block_depth`（`layered.py:182`） | 注意 `TransMemConfig.depth` 默认是 4（transmem.py:71），层级路径靠 block_depth 覆盖 |
| C7 | §1 | 可学习 sigmoid 门控决定折扣，原地加回，作为残差往上传 | ✓ | `transmem.py:277-290`（_read_gate）、`:359-366`（correct） | |
| C8 | §1 | Last-4 对 36 层 Qwen3-4B 就是 32/33/34/35（`layered.py:43 resolve_inject_layers`） | ✓ | `layered.py:43` def；`layered.py:93 return list(range(resolved_stop - depth, resolved_stop))`；论文 txt:872-873（36 层）与 txt:1355-1358（Layer 32/33-34/35 逐层 gate）双向佐证 | |
| C9 | §1 | 各装一份，互不共享参数（`layered.py:244 TransMemLayered`） | ✓ | `layered.py:244` class；`:252-253 nn.ModuleDict({str(l): TransMem(bcfg) …})` | |
| C10 | §1 | 训练时只更新这些小模块，LLM 主干一个字节都不改（引 `layered.py:244`） | ◐ | 结论 ✓：`train_inloop.py:366 self.model.requires_grad_(False)`；optimizer 只取 `self.mem.parameters()`（`:457-464`）；clip 也只作用于 `self.mem`（`:584`） | 所引 `layered.py:244` 只是模块类定义，不是冻结证据 |
| C11 | §2 | 触发时机 prefill；推理侧对应 `LayeredRollout.generate_from_ids`（`layered.py:453`） | ✓ | `layered.py:453` def | |
| C12 | §2 | "先对完整 context+question 做一次**不带 TransMem 修正**的标准前向（`layered.py:565` 附近 `self.model.model(...)`）" | ✗ | 两处都错：(a) 该调用在 `layered.py:528`（`:565` 是 `values = (torch.stack(chosen_log_probs)`）；(b) hook 在 `:519-520` 就已注册，`:528` 这次前向里 hook 的 prefill 分支同时读 H_M（`:488`）**并写修正**（`:512 h[:, -1, :] = block.correct(...)`） | 文档下一句"在这次前向过程中 hook 会被触发"与本句自相矛盾；真正"不挂 TransMem"的纯前向是 overflow 路径 `capture_memory_from_ids`（`:391-394 use_cache=False`，无注入） |
| C13 | §2 | 挂在 32~35 层的 forward hook（`layered.py:480 mk_hook`）会被触发 | ✓ | `layered.py:480` def mk_hook；`:519-520` 注册 | |
| C14 | §2 | 存的是该层输出的原始隐状态张量本身（`hm_limit = source[0, hm_idx_t, :]`，`layered.py:488`） | ✓ | `layered.py:488` 逐字一致 | |
| C15 | §2 | 选哪几个位置由 `hm_positions(len_cl, N, mode)` 决定（`extract_features.py:115-127`） | ✓ | `extract_features.py:115` def，函数体到 `:127` | |
| C16 | §2 | `n_mem` 默认 4（`layered.py:119` / `transmem.py:85`） | ✓ | 两处行号均精确 | |
| C17 | §2 | floor：`seg=len_cl//N; idx=(i+1)*seg-1`，历史默认（`extract_features.py:126-127`） | ✓ | `:126-127` | 代码另有 `max(min(...), 0)` 钳位，文档略去（无害） |
| C18 | §2 | frac：`idx=ceil((i+1)*len_cl/N)-1`（`extract_features.py:124-125`） | ✓ | `:124-125` | |
| C19 | §2 | frac"末位严格对齐文末、不同 N 的取位集合互为子集，为记忆池消融设计，论文正文完全没提" | ✓ | `extract_features.py:120-122` docstring 明写；论文只写 n=L/B（txt:322-325） | |
| C20 | §2 | 每个注入层各自独立取一份 H_M（4 位置 × hidden_dim） | ✓ | hook 逐层闭包，`layered.py:487-492` 每层各取一次 | |
| C21 | §2 | overflow：`capture_memory_from_ids`(`:327`)/`capture_memory_from_context`(`:407`)，每 chunk 单独一次**不挂 TransMem、不带 LLM KV cache** 的纯前向，`_normalize_overflow_memory`(`:420`) 校验拼接 | ✓ | 三个行号全对；`:332-338` docstring "runs the frozen student without TransMem injection and without an LLM KV cache"；`:391-394 use_cache=False` | 文档在这里的措辞是对的——错的是它把同一措辞也套到了主路径 prefill 上（C12） |
| C22 | §2 | "这仍然只发生在**同一次推理请求内部**，结束就丢" | ◐ | 分块与拼接实际在**调用方**：`scripts/eval/eval_memory_agent_bench.py:937-947`；且同一份 `overflow_memory` 在同一个 ContextWindow 的**多个问题之间复用**（`:951-963` for question in questions 共用） | 不持久化 ✓，但"一次请求内"需限定为"一个 context window 内、跨多个问题" |
| C23 | §2 | 存的过程不额外调"另一个"LLM | ✓ | 全链路只有冻结 backbone 自身前向 | |
| C24 | §2 | 会调的是 TransMem 自己的前向（1 层 Qwen3 decoder block，`transmem.py:293 forward`） | ✓ | `transmem.py:293` def forward；`:204-205 [Qwen3DecoderLayer(qcfg, layer_idx=i) …]` | |
| C25 | §2 | "有**三条**并行存在的路子：① Stage 0 离线特征 ② on-policy ③ in-loop" | ◐ | 实际至少 5 个训练入口：`train_offpolicy.py`(1303行)、`train_layered.py`(573行，`layered.py:10-16` 自述"v3 P6 离线特征，已被排除—存档")、`train_onpolicy.py`、`train_inloop.py`、`train_grpo.py`+`rl.py` | 恰好对应论文 Table 5 四种目标（SFT=`train_offpolicy.py --loss ce`"SFT-on-golden"`:329,720`；GRPO；OPD；ECSD），文档漏掉了 GRPO/SFT 这两支 |
| C26 | §2 | in-loop 调 `LayeredRollout.teacher_forced_forward`（`layered.py:572`） | ✓ | `layered.py:572` def；`train_inloop.py:529` 确有调用 | |
| C27 | §2 | 引"梯度经真实 LLM 上层流回各块…这就是『LLM 层进训练环』"，称是"**该函数**（teacher_forced_forward）的 docstring" | ◐ | 引文 ✓ `layered.py:617-618` | 但它是 `_teacher_forced_forward_with_handles`（`:608`）的 docstring，不是 `:572` 那个函数的 |
| C28 | §2 | 三条路子共用同一个 `hm_positions` 取位逻辑 | ✓ | `extract_features.py`(5处)、`train_onpolicy.py`(3处)、`layered.py`(6处，in-loop 经此) 均调用 | |
| C29 | §3 | 只在生成答案 token 位生效，**context/question 本身的 token 完全不受影响** | ◐ | prefill 时被改写的正是**提示最后一位**：`layered.py:511-512 h = target.clone(); h[:, -1, :] = block.correct(...)` | 该位确实是产出第一个答案 token 的位置，但字面上"完全不受影响"需限定；论文 Eq.7 的 `t≥L+1` 与代码从 `len_cq-1` 起注入差一位（见 D4） |
| C30 | §3 | `phase["mode"]` 从 prefill 切到 decode（`layered.py:494-512`） | ✓ | 机制正确；prefill 分支 `:487-499`、decode 分支 `:500-503`、写回 `:512` 均在或紧邻该区间 | 切换赋值本身在 `:533` |
| C31 | §3 | 训练侧 `qpos = arange(len_cq-1, len_cq+M-1)`（`layered.py:614`） | ◐ | 语句实际在 `layered.py:627` | `:614` 是描述该行为的 docstring 行（"注入位 = M 个答案生成位 qpos = len_cq-1 .. len_cq+M-2"） |
| C32 | §3 | `_teacher_forced_forward_with_handles`（`layered.py:598` 起） | ◐ | def 实际在 `layered.py:608` | 行号漂移 10 行 |
| C33 | §3 | 不是"检索"：没有相似度打分、没有 top-k 排序、没有向量库查询 | ✓ | 全仓 grep 无 faiss/bm25/cosine_similarity/embedding 依赖 | 否定式断言，实际证伪失败 |
| C34 | §3 | `X = torch.cat([hm, hq_source], dim=1)`（`layered.py:497-499`） | ✓ | 语句在 `:496-498`，引用区间覆盖到 | ±1 行，可接受 |
| C35 | §3 | 喂进 1 层 Qwen3 decoder block 做**因果自注意力**（`transmem.py:293`；`layers.py:48 to_qwen3_config`） | ✓ | `transmem.py:83 causal: bool = True`；`:334 build_additive_causal_mask(...)`；`layers.py:48` def | |
| C36 | §3 | 单次前向无循环；"多步"体现在层间（`layered.py:252`）；是"深注入"（layered.py 顶部 docstring 语） | ✓ | `layered.py:3-6` 文件顶部 docstring 确有"深注入"；`:304-306` 再述"纠正后的 hidden 继续流入上层" | |
| C37 | §3 | `out_proj` 是零初始化的线性层（`transmem.py:212`） | ✓ | `:212 self.out_proj = nn.Linear(dim, dim, bias=False)`，`:211` 注释"读出: 零初始化 -> 初始 MS=0"；实际置零在 `:247-248` | |
| C38 | §3 | `gate = 2·sigmoid(z)`（gate_mode="centered_sigmoid" 时，`transmem.py:262-271 _read_gate`） | ◐ | 公式 ✓：`transmem.py:281-289`，`scale = gate_max = 2.0` | `_read_gate` def 在 `:277`（体 `:277-290`）；`:262-271` 是 `_init_weights` 尾部与 `warm_start_from` 开头 |
| C39 | §3 | `correct()`（`transmem.py:359`）把 `hidden + gate*MS` 写回；推理侧落地在 `layered.py:512` | ✓ | 两处行号逐字精确（`transmem.py:359` def correct；`:364-366 hq_stu + delta`） | |
| C40 | §3 | `out_proj` 零初始化保证恒等启动（`transmem.py:247 if self.config.zero_init_out`） | ✓ | `:247` 逐字一致 | |
| C41 | §3 | 零初始化"论文正文没有提这个工程细节" | ✓ | 全文无 | 但论文 Table 7 图注 txt:1064 报了 **gate** 初始化 g=1，与代码 `gate_init=1.0`+bias=τ·logit(0.5)=0（`transmem.py:259-266`）精确一致 |
| C42 | §4 | 图：调用方脚本 `eval_locomo.py` / `train_inloop.py`；F1/EM/LLM-judge 打分都在这一层 | ✓ | `scripts/eval/eval_locomo.py:212 score_locomo_prediction`、`:243 overall_f1`；`scripts/eval/eval_memory_agent_bench_judge.py` | |
| C43 | §4 | 图：选择 `mode=student`（不挂）还是 `mode=transmem`（挂） | ◐ | `evaluate.py:51 --mode required choices=["teacher","student","transmem"]` | 实为三选一，图里漏了 teacher 模式（ECSD 的老师侧） |
| C44 | §4 | 图：36 层 decoder；lm_head 冻结、`tie_word_embeddings=true` | ✓ | `transmem/README.md:76`；`objectives.py:136`；论文 txt:872-873 | |
| C45 | §4 | 图：`register_forward_hook`（`layered.py:480`）"**只在『生成答案』的 token 位触发**" | ◐ | hook 在被注入层的**每次前向**都触发（prefill 整段一次 + 每个 decode 步一次） | 只有**修正的写入位置**限于末位/qpos；"触发"与"生效"被混为一谈（同 C29） |
| C46 | §4 | 图：`objectives.py:63 DistillLoss` forward KL | ✓ | `objectives.py:63 class DistillLoss`；`:94-95 forward_kl → _kl_from_logits(t, s) = KL(P_tea‖P_stu)` | 与论文 Eq.3 方向一致 |
| C47 | §4 | 边界说明：调用方不知道内部，窄接口（token id 进 / 文本或 logits 出） | ✓ | `evaluate.py` / `eval_locomo.py` 只经 `predict()` 与 `student_rollout` 交互 | |
| C48 | §5 | `run_inloop.sh` 默认 `CONFIG=transmem/config_layered.json`，其 `gate_mode="constant"`（`config_layered.json:26`） | ✓ | `scripts/train/run_inloop.sh:37`；`config_layered.json:26` | 两处逐字精确 |
| C49 | §5 | 要复现头号结果"必须显式把 CONFIG 换成 `config_layered_dynamic_gate.json`"（`:27 gate_mode="centered_sigmoid"`） | ◐ | 行号 ✓（`:27`） | **不充分**：该文件 `inject_layers: [35]`（`:33`），即 Last-**1**；Last-4 必须另外靠 `run_inloop.sh:30` 强制要求的 `D=4`（或 `--inject_layers`）覆盖（`train_inloop.py:112, 381-388`） |
| C50 | §5 | 产出论文数字的 sbatch 命令大概率在已删除的 `scripts/version5/` 下，现已找不到 | ✓ | `git show --stat 6d7a612` 列出 21 个 `scripts/version5/` 文件被删 | |
| C51 | §5 | `transmem/README.md` 自评"CPU 已验证 … 需 GPU + 模型验证 …" | ✓ | `transmem/README.md:81-82` 逐字一致 | |
| C52 | §5 | 所有 config json 的 `warm_start` 均为 false/未出现；`config.json` 无此字段走 dataclass 默认 False；`LayeredConfig` 没有 `warm_start` 字段（对照 `layered.py:101-141`） | ✓ | `configs_nmem/*.json:21 "warm_start": false`；`transmem.py:95 warm_start: bool = False`；`layered.py:101-139` 字段列表确无该字段 | |
| C53 | §5 | "热启动逻辑是否完整实现，**没有看到调用点**，未验证" | ◐ | 可以判定：`warm_start_from`（`transmem.py:269`）全仓**零调用点**；且 `layered.py:191` 在 `block_config()` 里**硬编码 `warm_start=False`** | 层级（论文头号）路径下热启动结构性不可达＝死代码；"未验证"标注过于保守 |
| C54 | §5 | `gate_temperature=1.0`、`gate_shift=0.0` 是配置默认（如 `config_layered_dynamic_gate.json`） | ◐ | `gate_temperature: 1.0` 在该文件 `:30` ✓ | `gate_shift` **不在**该文件里（走 dataclass 默认 0.0），且 `transmem.py:124-126` 强制非 shifted_sigmoid 模式必须为 0——不是"配置默认"而是"被校验强制" |
| C55 | §5 | checkpoints/eval_results/data 三目录被 `.gitignore` 排除 | ✓ | `.gitignore:224 /data`、`:228 /checkpoints`、`:230 /eval_results` | |
| C56 | §5 | README 提到 HF 权重 `Rayleihaodong/TransMem-qwen3-4B-D4` 等 | ✓ | `README.md:64-65` | |
| C57 | §6.1 | 全仓找不到任何 `n_mem=5`；`configs_nmem/` 覆盖 n4/n8/n16/n32/n64/n128/n256/n384 共 8 个粒度、**没有 n5** | ✓ | 逐文件确认 8 个 json，`"n_mem"` 取值 {4,8,16,32,64,128,256,384} | 否定式断言，实际证伪失败 |
| C58 | §6.1 | 所有默认/训练配置的 `n_mem` 一律 4（`config.json`、`config_layered.json:18`、各 `*_dynamic_gate.json`）；`layered.py:119 n_mem: int = 4` | ✓ | 14 个 json 全部 `n_mem: 4`（仅 `config_pool256.json` 为 256，属池化消融） | |
| C59 | §6.2 | `git remote` 确为该地址；45 条提交；多数作者邮箱 gitee noreply / seu.edu.cn | ✓ | 45 条；39× `16002677+lei-haodong-ray@user.noreply.gitee.com`、4× `leihaodong@seu.edu.cn`、2× `220246386@seu.edu.cn` | |
| C60 | §6.2 | commit `e3f33f9`（"项目首个正结果…"）、`ac0988e`（"我也不知道写个inloop是为了什么"） | ✓ | `git log` 逐字一致 | |
| C61 | §6.2 | 硬编码私有 Slurm 分区 `DataFrontier_Explore`、endpoint `d-ceph-ssd-inside.pjlab.org.cn`、绝对路径 `/mnt/petrelfs/leihaodong/Project4` | ✓ | `scripts/train/run_inloop.sh:3, 27, 24` | |
| C62 | §6.2 | "`transmem/README.md` 引用的设计文档 `docs/plan.md`、`docs/version2/…md`"因 `/docs` 被排除而不存在 | ◐ | `docs/` 确不存在（`.gitignore:226`）；`transmem/README.md:7` 只引用 `../docs/plan.md` | `docs/version2/transmem正常化修改意见.md` 是被 `transmem.py:3`、`train_offpolicy.py:7`、`train_onpolicy.py:10`、`test_shapes.py:126` 引用的，**不是** README |
| C63 | §6.2 | 最后一次提交 `vanish` 一次性删除 75 个文件、3215 行，覆盖 version3/4/5 整批目录 | ✓ | `git show --stat 6d7a612`：`75 files changed, 3215 deletions(-)`；version3 8 / version4 10 / version5 21 个路径 | 数字逐字精确 |
| C64 | §6.3 | `README.md:148` 引 `scripts/version4/run_eval_locomo_s32_parallel.sh`；`:310` 引 `scripts/version5/run_train_inloop_generic.sh` 并称其为 "the current layered dynamic-gate recipe" | ✓ | `README.md:147-150`、`:309-311` | 行号逐字精确（recipe 那句在 `:311`） |
| C65 | §6.3 | 两个文件都在 `vanish` 里被删除，此后无补回 | ✓ | `git show --stat 6d7a612` 两行均在删除列表；`vanish` 是 HEAD | |
| C66 | §6.3 | 只能靠 `train_inloop.py:91-222` 的 argparse 反推 | ✓ | 首个 `add_argument` 在 `:91`，末个在 `:222` | 区间逐字精确 |
| C67 | §6.4 | 论文 "K-th layer" 记号易读岔；代码 `TransMemLayered`（`layered.py:244-252`）消除歧义 | ✓ | `:244-253` | |
| C68 | §6.5 | 默认配置"是论文 Table 3 消融里的『w/o Gating Network』**或更弱**的版本" | ◐ | `gate_mode="constant"` 对应 Table 7 的 g=1 固定残差（53.09）✓ | "更弱"这个补充恰好是关键：`inject_layers:[35]` 还把它退化成 Last-**1**——论文根本没测过的配置，比 w/o Gating 更远 |
| C69 | §6.5 | `config_layered_dynamic_gate.json`（`gate_max=2.0`）"与论文 Eq(6) `g=2σ(z)` **精确对应**" | ◐ | α=2 ↔ `gate_max=2.0` ✓（`:29`） | **粒度对不上**：论文 Eq.6 `W_g ∈ R^{d×d}` + Eq.7 `⊙`（逐维向量门控）vs 代码 `gate_proj = nn.Linear(dim, 1)`（`transmem.py:213`）且 `gate_granularity` 被硬性限死 `"token_scalar"`（`:111-114`）。这是文档整份里唯一漏报的**架构级**分歧，见 D1 |
| C70 | §5 | "仓库内部自评的验证状态是否已过期…**未验证**" | ? | 无法核实：仓库无 CI、无测试报告，`eval_results/` 被 `.gitignore:230` 排除 | 文档的"未验证"标注在此处成立 |
| C71 | §5 | HF 权重是否与论文数字一致"本次任务范围内没有下载验证" | ? | 无法核实：本机无法下载 `Rayleihaodong/TransMem-*` 权重 | |

### 2.3 `methodology-flow.md`（派生文档，抽查 5 条锚点，不计入统计）

该文件自述"基于同目录 paper-architecture 与 code-architecture，勘误以 verification 为准"，且**已经采用了本次独立复核得出的修正行号**（`transmem.py:277-290` 的 `_read_gate`、`layered.py:608-660` 的 `_teacher_forced_forward_with_handles`），也**已经正确标出了 D1 的向量/标量 gate 分歧**和 D6 的调用方 overflow。抽查其 txt 锚点：`txt:157-191`（Preliminaries+Eq.1-2）✓、`txt:241-250`（H_M 与"5"）✓、`txt:1396-1407`（Appendix B=4）✓、`txt:329-336`（chunk 前半）✓、`txt:337-344`（Concat 式）✓。→ **该派生图比它的两份上游文档更准确**；上游 `code-architecture.md` 仍带着 §2.2 中列出的旧锚点，尚未回填修正。

## 3. 步骤清单 — 论文侧

> 说明：TransMem 是 **in-forward-pass 隐状态注入**系统。种子词表里"写入侧"整组、"检索侧"整组在论文侧**都不存在**（详见本节末尾的"不存在的阶段"）。主要用"参数侧"标签。

### Lane A — 训练期（离线一次，ECSD；Figure 2(b)）

| # | name（论文自己的叫法） | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| A1 | Teacher: frozen backbone on (E, Q) | 训练时每样本一次 | (gold evidence E, question Q) → `p_T(·\|A_<i,E,Q)` | 1×，**冻结 backbone 自身充当 teacher**，与 student 共享同一份权重（txt:207-208 "no separate teacher model is introduced"） | - | P-FROZENFWD |
| A2 | teacher answer trajectory A | 同上 | teacher logits → 答案序列 A（student 随后 teacher forcing 跟随） | （同一次生成，非额外调用） | - | P-GENERATE |
| A3 | Student: frozen backbone + TransMem on full C | 同上 | 完整长上下文 C → 逐层 H_C | 1×（同一冻结 backbone，student 角色） | - | P-FROZENFWD |
| A4 | memory feature selection | 同上 | H_C → H_M（B 个段末隐状态） | no | - | **P-ACTSELECT [NEW]** |
| A5 | `f_m^K` + `W_Δ^K`（Eq.4-5） | 每答案位置 | `[H_M; h^A_{1:t}]` → `h_m` → `Δh` | no | - | P-SIDEPATH |
| A6 | gating + correction（Eq.6-7） | 每答案位置 × 每注入层 | `(h_m, Δh, h_t^K)` → `ĥ_t^K = h_t^K + g_m ⊙ Δh` | no | - | P-INJECT |
| A7 | forward KL `L_SD`（Eq.3） | 每 optimizer step | `(p_T, p_S)` → 损失；梯度穿冻结上层回到每个 TransMem，**backbone 零更新**（txt:222-226） | no | - | P-TRAIN |

### Lane B — 推理期（每 query 一次 forward pass；Figure 2(a)）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| B0 | （调用方）准备 C + Q | 每 query | 原始输入 → token 序列 `x_{1:L}` | no | - | P-INTAKE ⟨**边界外**，论文完全未描述⟩ |
| B1 | prefill / context features `H_C`（Eq.1） | 每 query，prefill 阶段 | token → `H_C = h^K_{1:L}`；"TransMem does not intervene"（txt:175-177） | 1×（**回答问题本身必须做的那次前向**，不算额外调用） | - | P-FROZENFWD |
| B1' | ~chunk-wise memory extraction | **仅当** `C` 超 backbone 上下文窗口（txt:328-341） | `C` → `{C_1..C_S}` → 各 `H_M^i` → `Concat(H_M^1,…,H_M^S)` | S× 冻结前向 | - | P-FROZENFWD + **P-ACTSELECT [NEW]** |
| B2 | segment-end memory `H_M` | 每 query，"once `h_t^K` is obtained" | `H_C` → `H_M=[h_n^K,…,h_L^K]`，B 槽，**逐层各一份** | no | - | **P-ACTSELECT [NEW]** |
| B3 | `f_m^K` autoregressive attention（Eq.4） | **每 answer token × 每注入层** | `[H_M; H_A]` → `h_m` | no | - | P-SIDEPATH |
| B4 | `W_Δ^K` memory shift（Eq.5） | 同上 | `h_m` → `Δh` | no | - | P-SIDEPATH |
| B5 | gating network `f_g^K`（Eq.6） | 同上 | `h_m` → `g_m = 2σ(W_g h_m/τ)` | no | - | P-INJECT |
| B6 | core correction（Eq.7，`t ≥ L+1`） | 同上 | `(h_t^K, g_m, Δh)` → `ĥ_t^K` | no | - | P-INJECT |
| B7 | 流入下一冻结层（Eq.8） | 同上 | `ĥ_t^K` → `h_t^{K+1}` | （同一次前向的后续层） | - | P-FROZENFWD |
| B8 | （B2-B7 在 Last-4 上**顺序发生 4 次**，txt:315-316） | 每 answer token | 32 → 33 → 34 → 35，后一层看到的是前一层已修正的流 | — | — | — |
| B9 | 生成答案 token | 每 answer token | logits → token | （backbone） | - | P-GENERATE ⟨**边界外**⟩ |
| B10 | （调用方）评分 | 每 query | answer → F1/EM/acc | 论文未描述 | - | — ⟨**边界外**⟩ |

### 论文侧**不存在**的阶段（明确声明）

- **写入侧整组不存在**：无 P-REWRITE / P-EXTRACT / P-META / P-EMBED / P-DEDUP / P-CONFLICT / P-LINK / P-AGGREGATE / P-PERSIST / P-EVICT。论文原话："Our method **does not store additional information** from the preceding context. Instead, its contextual awareness relies on the already computed vectors in `H_M`."（txt:302-306）。所谓"写"就是 backbone 本来就要做的那次 prefill。
- **检索侧几乎整组不存在**：无 P-QUERYPARSE / P-DENSE / P-SPARSE / P-SYMFILTER / P-GRAPHEXPAND / P-DIFFUSE / P-FUSE / P-RERANK / P-SELECT / P-ASSEMBLE / P-TOOLLOOP。没有相似度、没有 top-k、没有 prompt 拼接。全文唯一一次 "retrieval" 字样（txt:432-433）是对**门控作用**的比喻性描述，不是一个检索步骤。
- **参数侧也只用到一半**：无 P-DATASTORE / P-ANNINDEX / P-KNNDIST（不是 kNN-LM 家族，没有 (key,value) 库、没有 ANN 索引）；无 P-INTERP（不在输出**分布**上插值，只在**隐状态**上加残差）；无 P-KVWINDOW（不做 KV 驱逐；backbone KV cache 只是 Eq.2 的既有前提，txt:180-183）。

## 4. 步骤清单 — 代码侧

### Lane A — 训练期

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| S0 | Stage 0 特征抽取 `extract_features.py` | 离线一次（每数据集） | (evidence `C_S`, Q) → teacher greedy rollout 得 `answer_ids` + `hq_tea`；另 dump `lm_head.pt`（`:657-671`） | 1× 冻结 backbone（teacher 角色） | **本地/S3 分片 `.pt`（`atomic_save`, `:135-147`）——全系统唯一真正落盘的东西** | P-FROZENFWD + P-GENERATE + P-PERSIST |
| S1 | `train_inloop.py` 初始化 | 每次训练启动 | `model.requires_grad_(False)`（`:366`）；`resolve_inject_layers(--D)`（`:381-388`）建 `TransMemLayered`；optimizer 只吃 `self.mem.parameters()`（`:457-464`） | - | - | P-TRAIN(setup) |
| S2 | `teacher_forced_forward`（`layered.py:572` → `:608`） | 每 micro-batch | `full_ids=[CQ; A_1..M-1]` → 逐层 hook 取 `hm_idx=hm_positions(...)`（`:625`）与 `qpos=arange(len_cq-1, len_cq+M-1)`（`:627`）→ `X=cat([hm,hq])`（`:640`）→ `block(X, return_all_queries=True)` → `replace_query_positions(target, qpos, correct(...))`（`:649-650`）→ `h_q` | 1× 冻结 backbone（**在环**，梯度可通） | - | P-FROZENFWD + **P-ACTSELECT** + P-SIDEPATH + P-INJECT |
| S3 | `DistillLoss(divergence="forward_kl")` | 每 micro-batch | `(teacher_logits, student_logits)` → `KL(P_tea‖P_stu)·T²`（`objectives.py:94-95, 100`）；可选 `reg_weight·MSE(hq', hq_tea)`（`:105-107`，对应论文 Appendix Table 9） | no | - | P-TRAIN |
| S4 | backward + clip + step + checkpoint | 每 `grad_accum` 步 | 梯度只落 `self.mem`（`train_inloop.py:584`）→ ckpt（nvme/S3） | no | `.pt` ckpt | P-TRAIN + P-PERSIST |
| S5* | 其它训练分支（**非**论文头号路径） | — | `train_offpolicy.py`（含 `--loss ce` 即 "SFT-on-golden"，`:329,720`）、`train_layered.py`（`layered.py:10-16` 自述"v3 P6 离线特征，**已被排除—存档**"）、`train_onpolicy.py`（OPD）、`train_grpo.py`+`rl.py`（GRPO） | — | — | P-TRAIN 变体 |

> S5 恰好补全论文 Table 5 的四种目标（SFT / GRPO / OPD / ECSD，txt:963-975）——四支在仓库里**都有实现**。另：论文 Appendix Table 8 的 early final-hidden 单点设计也仍是一等公民代码（`train_offpolicy.py`，1303 行；`scripts/eval/eval_checkpoint_curve.py:141`、`eval_offpolicy_diagnostics.py:226`、`eval_hm_ablation.py` 明确只支持 final-hidden ckpt）。

### Lane B — 推理期（`LayeredRollout.generate_from_ids`, `layered.py:453`）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| R0 | （调用方）渲染 chat prompt / 分片 / 断点续跑 | 每 query | 样本 → `cq_ids` | no | 进度 `jsonl`（`eval_locomo.py:161-170`） | P-INTAKE ⟨**边界外**⟩ |
| R1 | ~（调用方，**仅 MAB 且 `--retain_overflow_hm`**）overflow 分块 | 每 context window | `window.overflow_chunks` → 每 chunk `capture_memory_from_context`（`:407`）→ `capture_memory_from_ids`（`:327`）：**真正不挂 TransMem、`use_cache=False` 的纯前向**（`:332-338, 391-394`），`hm_positions(..., "frac")` 强制 frac（`:359`）→ **调用方** `torch.cat` 逐层拼接（`eval_memory_agent_bench.py:937-947`） | S× 冻结前向 | 内存张量，**跨该 window 的多个问题复用**（`:951-963`） | P-FROZENFWD + **P-ACTSELECT** |
| R2 | `hm_positions(len_cl, n_mem=4, "floor")`（`:467`） | 每 query | `len_cl` → 4 个绝对 token 位置 | no | - | **P-ACTSELECT [NEW]** |
| R3 | 注册 hook（`:519-520`）+ prefill（`:528`） | 每 query | `cq_ids` → 全 36 层前向；**hook 在 32-35 层同时读 H_M 并写修正** | 1× 冻结 backbone | - | P-FROZENFWD |
| R4 | hook / prefill 分支（`:487-499`） | prefill 一次 × 每注入层 | `hm = source[0, hm_idx]`（+ overflow 前置 `:489-492`）、`hq = source[:, -1, :]`（`:494`）→ `X=cat`（`:496-498`）→ `block(X, past_key_values=DynamicCache, use_cache=True)`（`:495, 499`）→ `(ms, gate)` | no（TransMem 自身 1 层 Qwen3 block） | 每层一个 TransMem `DynamicCache` | **P-ACTSELECT** + P-SIDEPATH |
| R5 | `block.correct`（`:512` / `transmem.py:359-366`） | 同上 | `h[:, -1, :] = hidden + gate·MS` | no | - | P-INJECT |
| R6 | `phase["mode"]="decode"`（`:533`）+ 逐 token 循环（`:534-558`） | 每 decode token | 新 token → hook 增量喂 `[1,1,dim]` 进 TransMem KV cache（`:501-503`）→ 修正该位 | 1× backbone 增量前向 / 步（`:555-556`） | TransMem KV cache | P-SIDEPATH + P-INJECT |
| R7 | `lm_head` 贪心/采样（`:532, 558`） | 每 decode token | hidden → token id | （backbone） | - | P-GENERATE ⟨**边界外**⟩ |
| R8 | （调用方）canonicalize + token-F1 / EM / LLM-judge | 每 query | answer → 分数（`eval_locomo.py:212, 243`；`eval_memory_agent_bench_judge.py`） | judge 模式下 1× 外部 LLM | 结果 json | — ⟨**边界外**⟩ |

### 代码侧**不存在**的阶段

与论文侧同一份清单，且经全仓 grep 确证：无 `faiss` / `chromadb` / `qdrant` / `sentence_transformers` / `bm25` / `cosine_similarity` / `networkx` / `neo4j` 任何依赖或调用；没有向量库、没有图、没有去重/冲突消解/驱逐、没有 prompt 组装、没有 agent 工具循环。唯一的"存储后端"是训练侧 Stage-0 的 `.pt` 分片文件和 ckpt。

### 系统边界

**记忆系统本体** = `TransMemLayered`（`layered.py:244`）里的 D 个 1 层 Qwen3 block + 各自的 `out_proj`/`gate_proj`，加上把它们挂进 backbone 的 forward hook（`layered.py:480` / `:631`）。边界从"hook 读到该层输出 `H^K`"开始，到"把 `h + g·MS` 写回该层输出"结束——完全在一次 forward pass 内部，**没有进程边界、没有网络调用、没有跨请求状态**。

**属于调用方（agent / 评测脚本 / 训练脚本）一侧**：prompt 渲染与 tokenize、overflow 分块与拼接（`eval_memory_agent_bench.py:937-947`，且默认关闭）、生成循环的驱动、F1/EM/LLM-judge 打分（`eval_locomo.py:212`）、训练数据准备与 Stage-0 特征落盘。

**属于 backbone 一侧**：全部 36 层 decoder 的计算、KV cache、`lm_head` 采样。

## 5. 论文↔代码分歧

| # | 类型 | 分歧 | 论文证据 | 代码证据 | 文档是否标出 |
|---|---|---|---|---|---|
| D1 | **两边都有但行为不同** | **门控粒度：逐维向量 vs 每 token 标量。** 论文 Eq.6 `W_g ∈ R^{d×d}` + Eq.7 `g_m ⊙ Δh`（逐维）；代码是 `nn.Linear(dim, 1)`，且 `gate_granularity` 被 `__post_init__` 硬性限死 `"token_scalar"`。参数量 d² vs d，调制粒度也不同。**有意思的是论文附录反而与代码一致**（"because the gate is token-dependent"、逐层 gate 均值/方差），落单的是论文正文。 | txt:271-292（Eq.6-7）；txt:1344-1347（附录标量口径） | `transmem.py:213 gate_proj = nn.Linear(dim, 1, bias=True)`；`:111-114` "第一版只支持 gate_granularity='token_scalar'"；`:281-289` `scale*sigmoid(logits)` | ❌ `code-architecture.md` §6.5 反而称二者"精确对应"（`methodology-flow.md` 已标出） |
| D2 | **两边都有但参数不同** | **B / n_mem = 5 vs 4。** 论文正文称最优 5，全仓一律 4，论文附录自己也 retain 4。 | txt:248-250 vs txt:1397, 1406 | `layered.py:119`；全部 14 个 config `"n_mem": 4`；`configs_nmem/` 8 个粒度中无 n5 | ✅ 两份文档均已正确标出 |
| D3 | **两边都有但行为不同** | **记忆槽取位公式。** 论文 `H_M=[h_n, h_2n, …, h_L]`，**末槽是上下文最后一个 token `h_L`**；代码主路径默认 `hm_mode="floor"`，末槽 = `N·⌊len_cl/N⌋ − 1`，当 `N ∤ len_cl` 时**取不到 `h_L`**（最多差 N−1 个 token）。真正等价于论文写法的 `frac` 只在 overflow 路径被强制启用。 | txt:246-248, 322-325 | `layered.py:120 hm_mode: str = "floor"`；`extract_features.py:126-127`（floor）vs `:124-125`（frac）；`layered.py:357-359` overflow 强制 frac | ❌ 两份文档都没标 |
| D4 | **两边都有但行为不同** | **修正的起始位置差一位。** 论文 Eq.7 限定 `t ≥ L+1`；代码从 `len_cq−1`（提示**最后一位**）起注入。代码做法与论文另一句 "invoked only when the model begins generating the answer sequence"（txt:317-319）自洽，与 Eq.7 字面不自洽。 | txt:290-292 vs txt:317-319 | 推理侧 `layered.py:512 h[:, -1, :]`；训练侧 `:627 qpos = arange(len_cq-1, …)` | ❌ 两份文档都没标（`code-architecture.md` §3 反而说 context/question token"完全不受影响"，见 C29） |
| D5 | **文档与两边都不符** | **"TransMem block 与 backbone 同构"是文档自己的说法。** 论文和代码其实一致：block **恒为 Qwen3 架构**，与 backbone 是否 Qwen 无关。 | txt:352-353；txt:387-389（Llama3.1-8B 下仍用 Qwen3 block） | `layers.py:48 to_qwen3_config → Qwen3Config`；`config_layered_llama31_8b_dynamic_gate.json` 存在 | ❌ 两份文档都写成"和主干 LLM 结构一样"（P3 / C5） |
| D6 | **code-only** | **chunk-wise overflow 由调用方驱动、默认关闭、只在 MAB 生效。** 论文把它写成方法的一部分；代码里分块/拼接/复用全在评测脚本，开关是 `store_true`（默认关）且要求 `--mode=paired`。`eval_locomo.py` 全程不传 `overflow_memory` → **LoCoMo 从不触发 chunk-wise**——正好回答了 `paper-architecture.md` §6 最后一条的开放问题。 | txt:328-345 | `eval_memory_agent_bench.py:937-947`（分块）、`:1214`（`--retain_overflow_hm` store_true）、`:1264-1265`（要求 paired）；`eval_locomo.py` 无 overflow 调用点 | ❌（`methodology-flow.md` 已标出调用方归属，但未标"LoCoMo 从不触发"） |
| D7 | **code-only** | **overflow 时的实际槽数是 S·N + N。** 代码把 overflow chunk 的槽**前置**到窗口内那 N 槽之前；论文的 `Concat(H_M^1,…,H_M^S)` 字面只有 S·N。 | txt:340-341 | `layered.py:489-492 torch.cat([retained_overflow[layer_idx], hm_limit], dim=0)`；`eval_memory_agent_bench.py:976 "transmem_effective_memory_slots": overflow_slots + limit_slots` | ❌ |
| D8 | **两边都有但参数不同** | **训练规模。** 论文："one NVIDIA A100 … 15 gradient accumulation steps per rank … global batch size of 30"；仓库现存唯一训练脚本请求 8 GPU、`ACCUM` 默认 4（日志按 `world × grad_accum` 打印全局批 = 32）。 | txt:353-355 | `run_inloop.sh:5 --gres=gpu:8`、`:31 GPUS=${GPUS:-8}`、`:34 ACCUM=${ACCUM:-4}`；`train_inloop.py:1004` | ❌ |
| D9 | **两边都有但参数不同** | **随机种子。** 论文"All experiments … fixed random seed of 42"；训练脚本 `--seed` 默认 **None**（help 明写"默认保持历史随机行为"），只有 `--data_sample_seed` 和各 eval 脚本默认 42。 | txt:416-417 | `train_inloop.py:222`（seed=None）vs `:106`（data_sample_seed=42）、`eval_locomo.py:80`（seed=42） | ❌ |
| D10 | **code-only** | **论文未写的工程细节**：`out_proj` 零初始化恒等启动；每层 TransMem 各持独立 `DynamicCache`（这是"层间 KV 隔离"的实现前提）。 | —（论文全文无） | `transmem.py:247-248`；`layered.py:495` | ✅ 零初始化已标（C37/C41）；每层独立 KV cache 未标 |
| D11 | **两边一致（正向确认）** | 论文 Table 5 的四种训练目标（SFT / GRPO / OPD / ECSD）和 Table 8 的 early final-hidden 变体，在仓库里**都有对应实现**，不是 paper-only。 | txt:963-975；txt:1066-1122 | SFT=`train_offpolicy.py --loss ce`（`:329, 720`）；GRPO=`train_grpo.py`+`rl.py`；OPD=`train_onpolicy.py`；ECSD=`train_inloop.py`；final-hidden=`train_offpolicy.py` + `eval_checkpoint_curve.py:141` / `eval_offpolicy_diagnostics.py:226` / `eval_hm_ablation.py` | — |
| D12 | **两边一致（正向确认）** | 论文 Appendix "Additional Hidden-State Supervision"（`L = L_SD + β‖H'_last − H^tea_last‖²`）在代码里就是 `DistillLoss(reg_weight=β)`；论文 Table 7 图注 "All dynamic gates are initialized at g = 1" 对应 `gate_init=1.0` → bias = τ·logit(0.5) = 0；论文 "TransMem Feature Source" 消融对应 `transmem_before` 开关。 | txt:1137-1152；txt:1064-1065；txt:1334-1342 | `objectives.py:105-107`；`transmem.py:253-266`；`layered.py:138` | — |

## 6. 新造的 primitive 标签

### `P-ACTSELECT` — 按位置规则挑选已算出的激活作为记忆槽

**定义**：不做任何编码/压缩/打分，仅按一条**确定性的位置规则**（本系统：把上下文按段长 `n=L/B` 等分、取每段末位）从**已经算好的**隐状态张量里挑出一个稀疏子集，直接当作"记忆"参与后续计算。

**为什么必须新造**（逐条排除了种子词表里所有近邻）：
- 不是 `P-DATASTORE`：没有 (key, value) 结构、没有查找接口、不跨请求存在，也没有 kNN-LM 那种"用它去查最近邻"的用途。
- 不是 `P-EMBED`：没有任何编码前向——这正是论文的核心卖点（"without repeatedly encoding the preceding context"，txt:20）。
- 不是 `P-SELECT`：那是"组合优化选择（Kruskal 森林 / 贪心 / 1-swap / 阈值截断）"，是检索侧对候选集做优化；这里既无候选集也无目标函数，只有一条整除公式。
- 不是 `P-KVWINDOW`：不管 KV cache、不驱逐任何东西，挑的是 hidden state 不是 K/V。
- 不是 `P-INTAKE`/`P-PERSIST`：既不摄入原始输入，也不落盘。

**它在本系统里的地位**：这是 TransMem 整个"写入侧"**唯一**的动作——把它标成别的任何东西，跨系统骨架合成时都会错配。预计对其它 in-forward-pass / 激活复用类系统（EAGLE、DeepSeek-MTP 式的隐状态复用，论文 txt:307-309 自己也点了这个亲缘关系）同样可复用。

其余步骤全部复用了已有标签：`P-FROZENFWD`、`P-SIDEPATH`、`P-INJECT`（种子词表原文即"隐状态注入(**门控残差**)"，正好覆盖 Eq.6+Eq.7 的 gate+residual）、`P-TRAIN`、`P-PERSIST`、`P-GENERATE`、`P-INTAKE`。

## 7. 复核统计

| 文档 | ✓ | ✗ | ◐ | ? | 合计 |
|---|---|---|---|---|---|
| `paper-architecture.md` | 41 | 1 | 8 | 0 | 50 |
| `code-architecture.md` | 51 | 1 | 17 | 2 | 71 |
| **总计** | **92** | **2** | **25** | **2** | **121** |

- ✗（2 条）：P17（"论文没用 retrieval 这个词"被 txt:432-433 证伪）、C12（把已挂 hook 的 prefill 说成"不带 TransMem 修正的标准前向"，并把行号指到 `:565`）。
- ◐ 里最实质的 5 条：C69（漏报向量 gate vs 标量 gate 这一架构级分歧）、C49/C68（`*_dynamic_gate.json` 单独并不构成 Last-4，其 `inject_layers:[35]`）、C29/C45（把 hook "触发"与修正"生效"混为一谈）、P3/C5（"与主干同构"实为恒 Qwen3）、C25（训练入口从 5 个说成 3 个）。
- 其余 ◐ 多为**引用锚点出处/行号偏移**：P8、P20、P38、P44（论文段落归属）；C27、C31、C32、C38（代码行号漂移 6–14 行，函数与文件均正确）。
- ?（2 条）：C70（仓库自评验证状态是否过期，无 CI/日志可查）、C71（HF 权重与论文数字是否一致，本次无法下载）。
- 文档标为"**未验证**"但本次**实际给出了结论**的：warm start 是死代码（C53）、LoCoMo 从不触发 chunk-wise（D6）、默认配置除了缺门控还退化成 Last-1（C68）。

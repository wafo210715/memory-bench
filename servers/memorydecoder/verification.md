# memorydecoder 架构文档复核报告

> 复核日期 2026-09-05；论文源 `Wei-2026-Memory-Decoder-at-Scale.txt`（6645 行，同名 PDF 用 `pdftotext -layout` 交叉核对图 2）；代码源 `MemoryDecoder-at-Scale` @ `bbbfee85`（origin = github.com/LUMIA-Group/MemoryDecoder-at-Scale，单 commit "Initial release"）。
> 本次复核对象：`paper-architecture.md`、`code-architecture.md`（主表），外加 `methodology-flow.md` 的抽检（§2.3）。所有 txt 行号均为我本次亲自 `grep -n` / `sed -n` 看到的行；所有 `file.py:NNN` 均已逐条 `sed -n` 打开确认。

## 1. 总评

两份文档整体可信度高：机制描述（离线蒸馏、推理零检索、双前向 + 分布插值）与论文和代码完全对得上，代码侧 40 多个 `file.py:NNN` 锚点里绝大多数指向正确文件，`code-architecture.md` 第 6 节列的 5 个论文↔代码冲突点全部属实且是这套材料里最有价值的部分。最严重的问题集中在三类：**(a) 否定式断言被附录证伪**——`paper-architecture.md` 说"论文没给 β 默认值"，但附录 B 的 Table 9/10 里 "Memory loss weight" 一行三处都是 0.5，正好等于代码 `alpha` 默认值，这条"缺口"其实不存在；α 的候选值范围同样写在附录 F。**(b) 两处引用锚点指错**——"Both [RAG, kNN-LM] require external retrieval during inference" 被标成 §7 Related Work，实际在 §1 Introduction（txt:216）；图 2 被描述成"两个并列且都标 ACTIVE 的框"，实际全图只有一个 ACTIVE 标签且标在被选中的 General Memory 上。**(c) 一处机制描述与代码不符**——`--ignore_first` 被描述成"丢掉和自己完全重合的最近邻"，代码 `saveKNNMulti.py:138-139` 是**无条件**丢掉 top-1，不做 key==query 判断，这和论文 txt:302 的条件式表述是实质分歧，且顺带把有效邻居数从 K 变成 K−1。
另外，冲突点 4（λ 选取机制）的分界线画错了：不是"lm-eval 用 auto / opencompass 用 0.3"，而是"general 套件用 auto / 其余全部（含 lm-eval 树内的 FinEval 与 knowledge 脚本）写死 0.3"。代码侧行号漂移有十余处（多为 ±2~30 行），单独看不致命，但 `saveEmbedMulti.py:296-312`（Arrow schema）和 `save_knn_pipeline.sh:76-88`（Step 1 入口）漂到了完全不相干的代码块。

## 2. 逐条核对表

判定：`✓` 属实 / `✗` 不实 / `◐` 部分属实或需加限定 / `?` 无法核实

### 2.1 paper-architecture.md

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| P1 | 抬头 L3 | Wei/Cao/Wang/Zhang/Guo/Zhou/Lin (2026), arXiv:2607.27919 | ✓ | txt:3（作者）、txt:33（`arXiv:2607.27919v1 [cs.CL] 30 Jul 2026`）、README:27 | — |
| P2 | 抬头 L4 | 全文路径 `/Users/guanhongli/.../Wei-2026-...txt` | ? | 本机同名 txt 存在（6645 行），但该绝对路径属于另一台机器 | 非内容性断言 |
| P3 | 抬头 L5 | `M_θ` 冻结主干；`M_ψ` 独立训练的 Transformer 解码器、目标不同；`p_ret` 是离线检索得到的训练监督信号、不是推理时的东西 | ✓ | txt:253-259、txt:269-273 | — |
| P4 | §1 L9 | "用一个独立的、**和主干模型规模相当**的 Transformer 解码器" | ◐ | txt:784-788、Fig.1 txt:84-85 | 论文的头条结论恰恰是**不必**规模相当：410M backbone + 6.9B memory 超过 12B；"规模相当"只在 §5.1 的匹配设置成立 |
| P5 | §1 L9 | 推理时只需 `M_ψ` 一次前向 + 与冻结主干插值，全程不需要外部数据库或最近邻搜索；引 §2"Retrieval is used only to construct offline supervision" | ✓ | txt:259、txt:274-277 | 引文逐字准确 |
| P6 | §2 L13 | 触发：只在记忆预训练/CPT 之前一次性离线构造，不是运行时触发 | ✓ | txt:259、txt:429-449 | — |
| P7 | §2 L17 | key = 冻结 `M_θ` **最后一层**隐藏态 `φ_θ(c_t)`；value = 该位置下一个真实 token；组成 `R_mem`（§3.1 Eq.3） | ✓ | txt:294-296（"the hidden state from the final layer of M_θ at the final position"）、Eq.3 txt:306 | 与代码取法不同，见 C55/C56 |
| P8 | §2 L18 | 用同一批语料每位置隐藏态当 query，检索 K 个最近邻，按距离做温度 τ 的 softmax 加权投票得 `p_ret`（§3.1 Eq.4-5） | ✓ | txt:300-320（Eq.4 txt:311、Eq.5 txt:319） | — |
| P9 | §2 L18 | 检索时丢弃与 query 完全重合（key=query）的最近邻，§3.1 原文明确写此设计 | ✓ | txt:302 "discarding the top-ranked match **if its key equals** q_t to avoid trivial self-retrieval" | 论文是**条件**丢弃；代码不是，见 C20 |
| P10 | §2 L19 | 207B token 去重 Pile；N 个 token → N 个 key + N 次查询 → O(N²)；key 是 Pythia-6.9B 最后一层 4096 维；标准 Faiss 不可行 | ✓ | txt:429-435、txt:496、Table 8 txt:2031-2035 | — |
| P11 | §2 L20 | 步骤 1：训练 OPQ256，把 4096 维 key 压成 256 维检索向量 | ✓ | txt:436-438、Fig.3 caption txt:425-426 | — |
| P12 | §2 L21 | 步骤 2：压缩空间上学 IVF 划分，IndexHNSW 当量化器（分配向量 + 路由 query）；每分片存一段连续质心区间做成独立 `IndexIVFPQ` | ✓ | txt:439-442 | — |
| P13 | §2 L22 | 步骤 3：HNSW 路由 → 按分片分组 → 各分片自己 GPU 局部 IVFPQ 搜索（不跨分片随机访问）→ writer 按 query id 合并取 top-K → `p_ret` 稀疏缓存 | ✓ | txt:443-449、Fig.3 caption txt:427-428 | — |
| P14 | §2 L23 | 不调任何"生成式"能力；LM 只当特征提取器；检索是经典 ANN | ✓ | txt:294-296、txt:429-449 全程无 prompt/生成描述 | 否定式断言，已在正文+附录范围内证伪失败（即成立） |
| P15 | §2 L24 | §3.2 Eq.6；Pile 上每行平均保留 **64.95** 个非零 token；词表 **50,304**；约 **250×** 压缩；只留 p>ε；offset 标行边界；O(N·\|V\|) → O(N+M) | ✓ | txt:458-472（64.95 与 250× 在 txt:469-470，Eq.6 在 txt:462-464） | — |
| P16 | §2 L25 | 预处理把对齐的分布行区间挂到每条打包样本上；worker 用 offset + 只读 memmap 读连续切片；同一套 batching/collator 既喂标签又喂稀疏 `p_ret` 三元组 | ✓ | txt:473-479 | 论文还多一句"GPU 上 FP32 重归一化后再算 KL"（txt:478-479），文档未提，代码 `cal_loss.py:84-90` 有 |
| P17 | §2 L30-31 | `L_mem = β·D_KL(p_ret‖p_ψ) + (1-β)·(-log p_ψ)`；KL 让 `M_ψ` 模仿检索分布，CE 防偏离；β∈[0,1] | ✓ | Eq.1 txt:269-271、说明 txt:271-273 | — |
| P18 | §2 L32 | `M_ψ` 与 `M_θ` 同 tokenizer 同输出词表；**不读取检索到的原文**，只从 `c_t` 预测 | ✓ | txt:257-259 | — |
| P19 | §2 L33 | 通用记忆初始化自对应规模 Pythia checkpoint（1.4B/2.8B/6.9B） | ✓ | txt:515-517 | 括注"与 backbone 规模对应"仅在 §5.1 匹配设置成立；§5.2（txt:779-788）把同一批记忆配到 410M–12B 各种 backbone |
| P20 | §2 L33 | 去重 Pile 训练 300B tokens，约 1.5 epoch | ✓ | txt:528-529、Table 9 txt:2132/2150/2168 | — |
| P21 | §2 L33 | **256 张 NVIDIA A800 80GB** + Megatron-LM | ◐ | txt:526 确实这么写；但附录 Table 9 的 "Number of GPUs" 一行是 **64 / 64 / 256**（txt:2147 / 2165 / 2183） | 论文自身不一致；文档只转述了 §4，读者会误以为三档记忆都用 256 卡 |
| P22 | §2 L33 | AdamW β1=0.9、β2=0.95、wd=0.01；余弦衰减到峰值 10%；2000 步 warmup | ✓ | txt:530-532；Table 9 txt:2136-2144 逐项吻合（min lr 3e-5 对 peak 3e-4） | 论文 §4 写 "All runs ... 2,000 warmup"，但 Table 10 域记忆是 1000/1000/200（txt:2220/2235/2250），又是一处论文内部不一致 |
| P23 | §2 L34 | 域记忆架构/目标/稀疏训练流水线与通用记忆完全一致 | ✓ | txt:481 "follow the same architecture, objective, and sparse training pipeline" | — |
| P24 | §2 L34 | 先用 Qwen3-4B-Base 对领域语料做一轮 CPT，再用 CPT 后模型构造该领域 kNN 分布 | ✓ | txt:482-484、txt:533-534 | — |
| P25 | §2 L34 | 记忆初始化自 Qwen3-1.7B-Base；训练预算 = 一次 Qwen3-8B-Base CPT epoch 的算力 | ✓ | txt:534-536 | — |
| P26 | §2 L34 | 应用于生物/法律/金融，最多 4.4B tokens | ✓ | txt:485；Table 8 txt:2049-2051（552M / 125M / 4.4B） | — |
| P27 | §2 L35 | 存的不是可读记忆条目，是弥散进权重的统计规律，读不出也不能单独增删 | ✓ | 全文无任何按条读写/删除记忆的接口描述 | 否定式断言成立 |
| P28 | §2 L37 | 证据锚点 §2(Eq.1)、§3.1(Eq.3-5, Fig.3)、§3.2(Eq.6)、§3.3、§4 | ✓ | 章节起止：§2 txt:249、§3 txt:285、§3.1 txt:291、§3.2 txt:454、§3.3 txt:480、§4 txt:487 | 编号全部对得上 |
| P29 | §3 L41 | 触发：推理阶段每一次 next-token 预测；引 §2 "At inference, M_θ and M_ψ process the same context in parallel." | ✓ | txt:274（引文逐字）；附录 I.4 txt:3669-3671 "linearly interpolated **for each next token prediction**" | — |
| P30 | §3 L43 | 推理时完全不做检索，不接触检索原文，不查任何数据库 | ✓ | txt:259、txt:1727-1729 | — |
| P31 | §3 L45 | **一步到位**：`M_θ` 与 `M_ψ` 并行处理同一段上文 | ✓ | txt:274 | — |
| P32 | §3 L45 | 图 2 中间 "Inference" 栏画的是**两个并列且都标 "ACTIVE"** 的框：Base Model 与某个 Memory | ✗ | PDF 第 2 页 `pdftotext -layout`：中栏只有 **一个** "ACTIVE" 标签，位于 Law/General/Biology 三个 memory 之中被选中的 General Memory 上方；Base Model 无 ACTIVE 标；txt:104 是全文唯一一处 "ACTIVE" | 实质结论（base + 某一个 memory 并行）不受影响，但"两个都标 ACTIVE"是编造的图面细节 |
| P33 | §3 L46 | `p_final=(1-α)p_θ+α p_ψ`, `y∈V`（§2 Eq.2） | ✓ | Eq.2 txt:275-277 | — |
| P34 | §3 L47 | 没有"先检索候选、再重排、再生成"的多轮结构 | ✓ | 全文只有 Eq.2 一步插值 | 否定式断言成立 |
| P35 | §3 L47 | 这是与 RAG/kNN-LM 的关键区别，**§7 Related Work 明确对比**："Both [RAG, kNN-LM] require external retrieval during inference" | ✗ | 该句在 **§1 Introduction**，txt:216（§1 = txt:189-248，§7 = txt:1715-1756）；§7 的对应表述是 txt:1729 与 txt:1742-1748，措辞完全不同 | 引文内容真实，章节锚点错 |
| P36 | §3 L49 | 不存在"交给"动作，插值后分布即最终输出分布 | ✓ | txt:275-278 | — |
| P37 | §3 L49 | α 在验证集调好后固定用于测试；引 §4 Implementation Details **末句** | ✓ | txt:543-544，确为 Implementation Details 段落最后一句（§5 起于 txt:546） | — |
| P38 | §3 L51-54 | §6.7：1,024 个 BioInst 域训练样本；Top token 一致 86.62%；Pearson r=0.9174；平均 KL 0.1820；平均 TV 0.0823 | ✓ | §6.7 txt:1601-1604；Table 7 txt:1621-1624 + 数值 txt:1660-1663；正文复述 txt:1668-1669 | 四个数字逐一吻合 |
| P39 | §3 L53 | Pearson r 是"`p_ret` 众数对应 token 上两个分布概率值的相关性" | ✓ | txt:1609-1611、附录 I.2 txt:3578-3580 | — |
| P40 | §3 L56 | 论文解读：学到的是结构不只是众数；不是 100% 精确；残差主要出现在 `p_ret` 分散的样本上 | ✓ | txt:1671-1673 "learns the structure ... Residual errors arise mainly for diffuse targets" | — |
| P41 | §3 L58 | §5.3 引文 "Switching domains only requires activating the corresponding domain memory from the memory bank at inference, while the backbone remains frozen" | ✓ | txt:804-805（原句尾还有 "and requires no continued pretraining"，文档截断但不改义） | — |
| P42 | §3 L58 | 同一 backbone 可配不同记忆（通用/生物/法律/金融），两者在推理时可独立替换、只通过插值这一窄接口耦合 | ✓ | txt:794-806、txt:1754-1755、Fig.2 caption txt:186-187 | — |
| P43 | §3 L60 | 证据锚点 §6.7（Table 7，Figure 8-9） | ✓ | Table 7 txt:1621、Fig.8 txt:1649、Fig.9 txt:1709，均在 §6.7（txt:1601-1674）内 | — |
| P44 | §4 图 | mermaid 各节点的 §/Eq/Fig 锚点（Eq.3 / Eq.4-5 / Eq.6 / Eq.1 / Eq.2 / 图 3） | ✓ | 见 P7/P8/P15/P17/P33 | — |
| P45 | §4 L97 | 边界：MEMPRE 只在训练时发生一次、推理时完全不存在；两边只交换 next-token 分布；α 是唯一接口参数；论文没有描述任何文本/向量/embedding 在两者间传递 | ✓ | txt:259、txt:274-277 | 否定式断言成立 |
| P46 | §5 L103 | §2 是对前作 Cao et al. (2026, NeurIPS) 机制的复述 | ✓ | txt:250-251；参考文献 txt:1821-1823（NeurIPS 38:115487-115510） | — |
| P47 | §5 L104 | 跨词表迁移实验在 §5.4，做法是"换 embedding + LM head" | ◐ | 做法写在 **§4 Implementation Details** txt:536-538；§5.4（txt:807-816）只报结果 | 锚点略偏，内容正确 |
| P48 | §5 L104 | 正文没解释同词表假设与跨词表场景下 Eq.2 的 `V` 如何统一、是否需要额外对齐步骤 | ✓ | 通读 §2/§4/§5.4/附录 B、C 后未见任何说明 | 否定式断言成立（代码里倒是有 `_match_embedding_vocab_size`，见 C-额外项） |
| P49 | §5 L105 | §6.7 的保真度数字没有参照基准（随机基线／更小记忆／未蒸馏对照） | ✓ | 附录 I（txt:3552-3675）只给单/多 token 分层（Table 19 txt:3582-3622）和 bootstrap CI（Table 20 txt:3640-3660），没有任何外部基线 | — |
| P50 | §5 L105 | "strong correspondence" 是作者自己的定性判断 | ✓ | txt:1665 | — |
| P51 | §5 L106 | §9 提到联合/分阶段训练"could weaken cross-backbone transfer"，是推测、无实验支持 | ✓ | txt:1787-1789，原文措辞逐字吻合 | — |
| P52 | §6 L112 | α 具体怎么调：论文没给**搜索算法、候选值范围或优化目标** | ◐ | 附录 F txt:2970-2976 明确给出 α∈{0.00, 0.05, …, 1.00}；Fig.11 caption txt:3211 "all 21 coefficients at intervals of 0.05"；Table 15（txt:2977-）逐任务列出实际选定的 α | "候选值范围/步长"其实写了；只有搜索算法与优化目标确实缺失 |
| P53 | §6 L113 | **β 默认取值论文没有给出一个类似 "β=0.5" 的数值** | ✗ | 附录 B **Table 9** 的 "Memory loss weight" 行三档全是 **0.5**（txt:2145 / 2163 / 2181，行名对照 txt:2200）；**Table 10** 域记忆同样是 0.5（txt:2225 / 2240 / 2255，行名 txt:2271） | 文档自设"仅通读正文"口径（L110）并在 L119 预留了附录更正条款，但结论层面这是错的：β=0.5，且与代码 `alpha` 默认 0.5、launcher `ALPHA=0.5` 完全一致 |
| P54 | §6 L113 | §6.5 "Memory Training Objective" 做的是 attached CPT vs attached memory 的模块对比，不是 β 取值消融 | ✓ | txt:1482-1489；Table 5 txt:1493-1529 | 判断准确 |
| P55 | §6 L114 | 分布式 Faiss 的规模参数（分片数 S、每分片质心数、HNSW M/efSearch、OPQ 训练样本量）论文没给 | ✓ | 全文 grep：`efSearch`/`nprobe` 零命中；`shard`/`centroid` 只出现在 Fig.3 与 §3.1 的定性描述（txt:233/350-441） | 附录也没有 |
| P56 | §6 L115 | K 与 τ 的实际数值论文没给 | ✓ | 全文只在 Eq.4-5（txt:311-320）以符号出现；`temperature` 仅 txt:314 一处 | — |
| P57 | §6 L116 | "memory bank" 的工程形态论文没描述 | ✓ | 全文 `memory bank` 仅 txt:805 一处 | — |
| P58 | §6 L117 | 构造 datastore 的前向成本论文没单独核算；§9 只笼统提 "indexing and retrieval overhead" | ✓ | txt:1782-1784 | — |
| P59 | §6 L119 | "已在正文全文范围内核查（final layer / feed-forward / A800 / Megatron / memory bank 等关键词）" | ◐ | 这些关键词在正文确实核查到位（txt:295、txt:526、txt:805）；但附录 B/F 未核，导致 P52/P53 两条结论错误 | 文档自己预留了更正条款 |

### 2.2 code-architecture.md

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| C1 | 抬头 L3 | 官方 LUMIA-Group 仓库 | ✓ | `git remote -v` → `https://github.com/LUMIA-Group/MemoryDecoder-at-Scale` | — |
| C2 | 抬头 L3 | 克隆时 HEAD=`bbbbee85` | ✗ | `git rev-parse --short HEAD` → **`bbbfee85`**（full `bbbfee85457f114c4ce64bd83a8cf8be058bb3ae`，"Initial release", 2026-07-31） | 第 4 个字符错，`b`→`f` |
| C3 | 抬头 L4 | 仓库里的 "memory" 是另一个独立训练的 Transformer LM（memdec）；backbone 冻结不训练 | ✓ | `train_memdec_trainer.py:1165`（只加载 `AutoModelForCausalLM`）、`hf_memdec.py:146` `base_lm.eval()` | — |
| C4 | §1 L8 | "和主干规模相当的独立 Transformer 解码器" | ◐ | README:118 的 Quick Start 例子就是 pythia-1.4b-deduped + MemoryDecoder-Pythia-**2.8B**-general | 同 P4；代码里 base 与 memory 规模无任何绑定 |
| C5 | §1 L8 | KL 模仿提前算好的 kNN 分布 + 正常下一词预测损失；推理时两模型各一次前向、按固定权重线性插值 | ✓ | `utils/cal_loss.py:94-98`、`memdec_model.py:73-98` | — |
| C6 | §2 L12 | "存"完全在训练/CPT 阶段，一次性批处理（非运行时事件驱动），**分 5 步** | ◐ | 机制判断 ✓；但公开流水线实际有第 0 步：`scripts/data/preprocess_text.sh` → `utils/preprocess_dataset.py`（分词、按 `block_size` 默认 2048 打包、生成 `dstore_range`，见 `preprocess_dataset.py:111-167`、README:131-145），后面每一步都依赖它产出的 `dstore_range` 对齐 | 文档的 5 步清单和 mermaid 图都从①datastore 起步，漏了这一步 |
| C7 | §2 L12 | 全程没有生成式 LLM 调用，LM 只当特征提取器或被训练对象 | ✓ | `grep -n "\.generate(" train_base.py train_memdec_trainer.py knn_utils/*.py utils/*.py` → 零命中 | 否定式断言成立 |
| C8 | §2 ① L15 | 触发点：`save_knn_pipeline.sh` Step 1/3，跑 `train_base.py --save_knnlm_dstore`（`save_knn_pipeline.sh:76-88`） | ◐ | 事实 ✓，但行号漂移：Step 1 的 `accelerate launch ... train_base --save_knnlm_dstore` 实际在 **`save_knn_pipeline.sh:101-112`**；L76-88 是 `run()` 函数尾部和 banner echo | — |
| C9 | §2 ① L16 | 每 token 位置用冻结 base LM 前向，抓隐藏向量当 key（float16），下一个真实 token id 当 value | ✓ | `saveEmbedMulti.py:340-341`（fp16/int32）、`:347-351`（shift=1 取下一 token）、`:353-355`（-100 padding mask）；step 1 走 `trainer.evaluate()`（`train_base.py:389`），纯前向无梯度 | — |
| C10 | §2 ① L16 | key 类型**固定为** `KEY_TYPE.last_ffn_input`（`saveEmbedMulti.py:37`） | ◐ | `:37` 只是枚举成员定义；真正的默认值在 `saveEmbedMulti.py:293` 与 `train_base.py:195`，且可用 `--knn_keytype last_ffn_output` 覆盖 | 是默认而非"固定"；锚点指向枚举而非默认赋值 |
| C11 | §2 ① L16 | qwen2/qwen3/llama 固定读 `model.base_model.layers[-1].mlp` 的输入（`saveEmbedMulti.py:257-284` `model_layer_to_capture`） | ✓ | 字典 `:257-286`；llama `:274-276`、qwen2 `:278-280`、qwen3 `:282-284`，均 `capture_input=True` | 区间末尾差 2 行，可忽略 |
| C12 | §2 ① L17 | monkey-patch `model.forward` + 注册 forward hook（`:377-415` `KNNSaverMulti.break_into`） | ✓ | `break_into` 实际 `:377-411`（monkey-patch 在 `:389-396`，hook 在 `:386`/`:400`）；`:413` 起是 `pre_forward_hook` | 区间越界 4 行 |
| C13 | §2 ① L17 | `ActivationCapturer`（`:483`） | ✓ | `class ActivationCapturer(nn.Module)` 在 `saveEmbedMulti.py:483` | 精确 |
| C14 | §2 ① L17 | `post_forward_hook`（`:419`）里调 `_save_step_data`（`:334`） | ✓ | `:419-424`、`:422` 调用；`_save_step_data` 定义于 `:334` | 两个锚点都精确 |
| C15 | §2 ① L17 | 流式写 Arrow，schema `keys=float16 list, vals=int32`（`saveEmbedMulti.py:296-312`） | ◐ | schema 实际在 `_setup_arrow_writer`（`:319-332`），字段定义 `:324-327`；`:296-312` 是 `__init__` 里的多卡变量与建目录 | 行号漂到不相干代码块（`methodology-flow.md` 写的 `:319-332` 是对的） |
| C16 | §2 ② L20 | `build_index.py:126` `build_index()`：从 Arrow 抽样（默认最多 100 万条）训练 `IndexIVFPQ`，粗量化器 `IndexFlatL2`（`:177-178`），全部向量顺序 `add_with_ids`（`:198`） | ✓ | `build_index()` 定义 `:126`；`IndexFlatL2` `:177`、`IndexIVFPQ` `:178`；`sample_size=min(1000000, len(dstore))` `:182`；`add_with_ids` `:198` | 抽样方式是 `select_continuous_chunks(..., num_chunks=1000)`（`:183`），即 1000 段连续块而非均匀随机采样 |
| C17 | §2 ② L21 | `ncentroids=4096`；`code_size` 脚本默认 **64**（`save_knn_pipeline.sh:47`）/ CLI 默认 **32** | ◐ | 数值全对：`build_index.py:129` 与 `:225` = 4096；`:237` = 32；`save_knn_pipeline.sh:54` `CODE_SIZE="${CODE_SIZE:-64}"`。但 `save_knn_pipeline.sh:47` 是注释行 `# KNN Configuration`，正确行号是 **54** | — |
| C18 | §2 ② L22 | **没有分片、没有 OPQ 降维、没有 HNSW 路由**——单机单索引 | ✓ | 全仓 `grep -rni "hnsw"` 零命中；`OPQ` 只在 lm-eval 无关任务文件中以 `topq` 假阳性出现；无 `IndexShards`/索引分片代码 | 否定式断言，实际证伪失败（即成立） |
| C19 | §2 ③ L25 | `saveKNNMulti.py::KNNSearchMulti.process()`：把①的向量再当 query，搜 top-K（默认 1024，argparse 默认） | ✓ | `process()` `:248-273`；`batch['keys']` 直接当 query `:253-257`；`--k` 默认 1024 `:288`（构造函数默认同为 1024 `:27`；launcher `K=1024` `save_knn_pipeline.sh:50`） | — |
| C20 | §2 ③ L25 | `--ignore_first True`（`save_knn_pipeline.sh:158`）**丢掉和自己完全重合的最近邻** | ✗ | 行号 ✓（`:158`）。但 `get_knns` 的实现是 `if ignore_first: return dists[:,1:], knns[:,1:]`（`saveKNNMulti.py:138-139`）——**无条件**丢弃排第一的邻居，从不比较 key 是否等于 query；论文 txt:302 是 "**if its key equals** q_t" 的条件式丢弃 | 副作用：实际参与投票的邻居是 K−1=1023 个，不是 K 个；这是论文↔代码的实质分歧，两份文档都没列出来 |
| C21 | §2 ③ L26 | 距离转 softmax 概率（`knns_to_probs`, `saveKNNMulti.py:143-153`） | ✓ | 函数 `:143-153`；`:145` `softmax(neg_dists / knn_temp)`、`:147-149` `scatter_add` 到词表、`:151` L1 归一化 | 锚点精确；launcher 的 τ = `KNN_TEMP=16.0`（`save_knn_pipeline.sh:51`），CLI 默认 1.0（`:290`） |
| C22 | §2 ③ L26 | 只保留概率 > 阈值（CLI `--threshold` 默认 **0**）的 token，按概率降序存成 `id_cnt/token_id/prob/label` 四列 Arrow（`sparsify_distribution`, `:155-177`） | ✓ | 函数 `:155-178`；`> self.threshold` `:165`；降序 `:170-172`；四列 schema `:115-120`；`--threshold` 默认 0 在 `:292` | 构造函数默认其实是 `1e-10`（`:33`），走 CLI/`main()` 时被 0 覆盖（`:322`）——文档未提这一层 |
| C23 | §2 ④ L29 | `utils/flatten_arrow.py` 转成 `offset.npy / flatten_token_id.npy / flatten_prob.npy / label.npy / shape.json` memmap 分片，供训练随机访问 | ✓ | `create_memmaps` `:70-81`（四个 .npy）、`write_shape_json` `:84-103`；README:177-183 同款目录树；训练默认随机采样（`train_memdec_trainer.py:124-125` `use_random_sampler=True`） | — |
| C24 | §2 ⑤ L32 | `MemDecTrainer.compute_loss`（L765-802）调 `cal_loss.py::kl_loss_token_memdec_sparse`（`cal_loss.py:47-98`） | ◐ | `compute_loss` 实际 `:765-811`；且它有**两条**分支——稠密路径 `kl_loss_token`（`:774-786`）与稀疏路径（`:787-804`），文档只描述了稀疏一条；`kl_loss_token_memdec_sparse` 实际 `cal_loss.py:47-99` | 行号轻微漂移 + 漏掉稠密回退分支 |
| C25 | §2 ⑤ L33 | `total_loss = alpha * kl_loss + (1 - alpha) * ce_loss`（`cal_loss.py:98`） | ✓ | `cal_loss.py:98` 逐字吻合 | 精确 |
| C26 | §2 ⑤ L33 | `kl_loss` 是 `Σ p_ret·(log p_ret − log p_ψ)`（`:94-97`）；`ce_loss` 是标准 CE（`:77`） | ✓ | KL 在 `:94-96`（并按行数归一 `/ max(rows,1)`）；CE 在 `:77` | CE 锚点精确；KL 区间多 1 行 |
| C27 | §2 ⑤ L34 | `alpha` 默认 0.5（`train_memdec_trainer.py:139`） | ✓ | `:139` `alpha: float = field(default=0.5, ...)`；launcher `ALPHA="${ALPHA:-0.5}"`（`train_domain_memdec.sh:27`） | 与论文 Table 9/10 的 "Memory loss weight 0.5" 完全一致（见 P53） |
| C28 | §2 ⑤ L34 | 经 `memdec_alpha` 传入 `MemDecTrainer`（`:701`, `:1213-1224` 附近实例化） | ◐ | `:701` 精确；但 `:1213-1224` 是 **`KNNDstore(...)`** 的实例化，`MemDecTrainer(...)` 在 **`:1239-1253`**，`memdec_alpha=memdec_args.alpha` 在 **`:1246`** | 行号漂移 ~26 行、指到了别的对象 |
| C29 | §2 ⑤ L35 | `M_ψ` 是普通 `AutoModelForCausalLM`，从 `model_name_or_path` 的已有 checkpoint 继续训练，除非显式 `--from_scratch` | ✓ | `:1130` 条件、`:1165` `from_pretrained`、`:1186` `from_config`（from_scratch 分支）、`:97` 参数定义 | — |
| C30 | §2 ⑤ L36 | 存的不是可读条目，不能单独增删查 | ✓ | 仓内无任何按条读写记忆的接口 | 否定式断言成立 |
| C31 | §3 L42 | 触发：推理/评测阶段**每一次 next-token 前向传播**（token 级） | ✓ | `memdec_model.py:145-167` 自回归循环，每 token 两次前向 + 一次融合 | 补充限定：`loglikelihood` 打分路径是对整段序列做一次 teacher-forced 前向，一次前向同时产出所有位置的融合分布；另外 λ 本身是**每个 task 分组**设一次（`hf_memdec.py:213-214`），不是每 token |
| C32 | §3 L44 | 完全不检索；核心是融合类 `MemoryDecoder`，代码里有两份彼此独立、**逻辑几乎相同**的实现 | ◐ | "不检索" ✓（两份实现里都没有任何 faiss/datastore 调用）。但"几乎相同"需限定：opencompass 版额外支持采样（`memdec.py:170-195` `_sample_token`，top-p/温度）、会把两边词表 pad 到同长（`:80-101` `_align_vocab_logits`，用 -inf 补齐）、还能算 NLL loss（`:151-159`）——lm-eval 版三者都没有 | — |
| C33 | §3 L45 | `eval/lm-evaluation-harness/lm_eval/models/memdec_model.py:25-97`（供 general/knowledge/FinEval 评测用） | ◐ | `class MemoryDecoder` 起于 `:25` 但结束于 `:169`；分工描述 ✓（README:220-231；knowledge 脚本 `evaluate_multihopqa.py:26` 直接 import 这个类） | 区间只覆盖到 forward |
| C34 | §3 L46 | `eval/opencompass/opencompass/models/memdec.py:22-`（供 BioInst/LawBench 用） | ✓ | `class MemoryDecoder(PreTrainedModel, GenerationMixin)` 在 `:22`；README:226-227、论文附录 C.2 txt:2293 | — |
| C35 | §3 L49 | `forward()`（`:64-97`）把同一 `input_ids` 喂给 `base_lm` 与 `memdec_lm`，各自前向、各自维护 `past_key_values` / `memdec_past_key_values` | ✓ | `forward` 实际 `:64-104`；两路前向 `:73-86`；两份 cache `:102-103` 与 `:156-157` | — |
| C36 | §3 L50 | 两边各自 `log_softmax`（`:93-94`） | ✓ | `:93-94` | 精确 |
| C37 | §3 L51-52 | `torch.logaddexp` 加权融合（`:95-97`），等价 `p_final=(1-λ)p_base+λ p_memdec` | ✓ | `:95-98`；`_log_base_weight/_log_memdec_weight` 在 `:55-62` | 数学等价性成立 |
| C38 | §3 L54 | 一步到位无多轮；`generate()` 逐 token 循环，每 token 只两次前向 + 一次融合；只支持贪心（`do_sample=True` 直接报错） | ✓ | `:117-120` 抛 ValueError；`:141`/`:165` argmax；`:145-167` 循环 | 限定：仅 lm-eval 版；opencompass 版可采样（见 C32） |
| C39 | §3 L54 | `generate()` 约 105-171 行 | ✓ | 实际 `:106-169` | "约"已自带余量 |
| C40 | §3 L56 | 融合后分布即最终输出分布，直接 argmax 或用于 `loglikelihood` 打分 | ✓ | `:141`/`:165`；`hf_memdec.py:238-243` 走 `HFLM.loglikelihood` | — |
| C41 | §3 L58 | λ 从 `hf_memdec.py::HFMemDec` 来（`:90-91` `@register_model("hf-memdec", "memdec")`） | ✓ | `:90` 装饰器、`:91` 类定义 | 精确 |
| C42 | §3 L58 | 可手动指定 `lmbda`，也可 `lmbda="auto"`（默认，`:114-133`） | ✓ | 默认值在 `:98`；auto 分支 `:114-130`，显式数值分支 `:131-137` | — |
| C43 | §3 L58 | 按 base 规模 + memory 规模 + 任务名查一张 **288 条**组合的 JSON 表（`memorydecoder_defaults.py::resolve_default_lambda`） | ✓ | `memorydecoder_defaults.py:22` 强校验 `default_count != 288` 报错；`resolve_default_lambda` `:118-141`，key = `[base_size, memory_size, task]`（JSON `key` 字段）；实测遍历 = 288 = 6 base × 3 memory × 16 task | 表本体在同目录 `memorydecoder_default_lambdas.json`；另有 `tasks_without_single_default`（halu、gpqa_main_zeroshot）会直接抛错 |
| C44 | §3 L58 | opencompass 侧（BioInst/LawBench）没有 auto 机制，只用固定值（环境变量 `LMBDA`，默认 0.3，`eval_bioinst_memdec.py:45`） | ◐ | 事实 ✓，但行号是 **44**：`eval/opencompass/configs/eval_bioinst_memdec.py:44` `lmbda = float(_os.getenv("LMBDA", "0.3"))`；`eval_lawbench.py:83` 同 | — |
| C45 | §5 L103 | `KNNWrapperMulti`（`train_base.py:353`）在 `eval/` 下从未被调用，只存在于 `train_base.py --knn` 分支 | ✓ | 全仓 grep：仅 `saveEmbedMulti.py`（自身定义/静态成员引用）与 `train_base.py:62`（import）、`:353`（唯一实例化，在 `if knn_args.knn:` 下）；`--knn` 未出现在任何 .sh | 否定式断言成立，锚点精确 |
| C46 | §5 L103 | README 致谢称 datastore 工具和 `train_base.py` "adapted from" 原始 MemoryDecoder 仓库 | ✓ | README:253-258 | — |
| C47 | §5 L104 | `MODEL_PATH` 由用户手填，代码不校验是否与 backbone 同规模/同 family | ✓ | `train_domain_memdec.sh:7-11,37`；`train_memdec_trainer.py` 全程没有 backbone 的概念，只有 `model_name_or_path` | 否定式断言成立 |
| C48 | §5 L105 | `scripts/` 下没有 Qwen3-4B-Base 领域 CPT 的训练脚本；`preprocess_text.sh` 只是文本预处理 | ✓ | `scripts/` 只有 `data/{preprocess_text,save_knn_pipeline,flatten_knn_arrow}.sh` + `train/train_domain_memdec.sh`；README:128-129 只列三阶段 | 否定式断言成立 |
| C49 | §5 L106 | `--threshold` CLI 默认 0，`save_knn_pipeline.sh` 也没覆盖 | ✓ | `saveKNNMulti.py:292`；`save_knn_pipeline.sh:145-159` 的 Step 3 参数表里确实没有 `--threshold` | — |
| C50 | §5 L107 | 没有任何名为 "memory bank" 的数据结构/注册表/服务化代码；只看到手动传 `--memdec_path` / `knn_model_path` | ✓ | 全仓 `grep -rni "memory.bank\|memory_bank"` 零命中；`memdec_path` `hf_memdec.py:97`、`knn_model_path` `eval_bioinst_memdec.py:62` / `eval_lawbench.py:130` | 补充：确实存在一张按 HF repo id 索引三个公开记忆 checkpoint 的表（`memorydecoder_default_lambdas.json` 的 `memory_model_ids`），但它只决定 λ，不做记忆切换 |
| C51 | §6 冲突1 | 论文的分布式 Faiss pipeline 开源代码没有；`build_index.py:126-201` 只有单机单 `IndexIVFPQ`（quantizer=`IndexFlatL2`，无 OPQ/HNSW）；`saveKNNMulti::_load_faiss_index` 每进程加载**同一份完整索引**到自己 GPU（数据并行不是索引分片） | ✓ | `build_index.py:177-178,198,200`（函数实际 126-202）；`saveKNNMulti.py:92-109`，`gpu_id = self.process_index % faiss.get_num_gpus()` `:102` | 这是全篇最有价值的判断，完全属实。附带 bug：`:99-109` 无 GPU 时 `gpu_index` 未定义仍被 return，CPU fallback 必崩（`code-architecture.md` 未提，`methodology-flow.md` 提了） |
| C52 | §6 冲突2 | 代码 `alpha`（`train_memdec_trainer.py:139`，默认 0.5）= 论文 **β**；eval 的 `lmbda`/λ = 论文 **α** | ✓ | `cal_loss.py:98` vs 论文 Eq.1 txt:269-271；`memdec_model.py:95-98` vs Eq.2 txt:275 | 判断准确；再叠加 P53 可以进一步说：论文 Table 9/10 的 β 也正好是 0.5 |
| C53 | §6 冲突3 | `--threshold` 默认 0，"默认配置下这一步不做真正的稀疏化" | ◐ | ε 剪枝确实没做 ✓；但输出仍是稀疏表示：`sparsify_distribution:165` 用 `> 0` 剔除所有零项，支持集上限本来就只有 K−1 个不同 token（`knns_to_probs` 只往 knn 命中的 token 上 scatter_add） | 准确说法是"K 诱导的稀疏支持集被保留，但论文 Eq.6 的 ε 概率剪枝没有执行" |
| C54 | §6 冲突4 | lm-eval 侧默认 `lmbda="auto"` 查 288 表，opencompass 侧只有写死 0.3，两套评测框架不统一 | ◐ | 分界线画错了。lm-eval 树内的 **FinEval** launcher 也写死：`eval/lm-evaluation-harness/scripts/domain/evaluate_fineval.sh:21` `lmbda=${LMBDA:-0.3}`；knowledge 任务的独立脚本 `knowledge-tasks/evaluate_multihopqa.py:54` 与 `evaluate_halueval.py:43` 的 `--lmbda` 默认也是 **0.3** 且完全绕过注册表（直接 `MemoryDecoder(...)`，`evaluate_multihopqa.py:148-153`）。真正用 auto 的只有 general 套件：`scripts/general/evaluate.sh:18,28,35` | 正确表述："只有 general 套件默认 auto 查表；FinEval / knowledge / BioInst / LawBench 四条路径全部默认固定 0.3"，共三套彼此独立的 λ 选取实现 |
| C55 | §6 冲突5 | 代码固定用 `last_ffn_input` = 最后一个 block 的 FFN **输入**，即"注意力子层输出之后、MLP 之前的**残差流**" | ◐ | 子层位置 ✓（`saveEmbedMulti.py:274-285` + `ActivationCapturer:492-493` 取 `input[0]`）。但对 llama/qwen2/qwen3，`layers[-1].mlp` 收到的是 `post_attention_layernorm(hidden)` 的输出，是**归一化之后**的向量，不是残差流本身；gpt2 同理（`h[-1].mlp` 的输入是 `ln_2` 输出） | "残差流"这个措辞不准确 |
| C56 | §6 冲突5 | "代码比论文更具体（**不算矛盾**），论文文字不足以反推代码选择" | ◐ | 论文两处都写 "hidden state from the **final layer**"（txt:295、txt:431-432），常规读法是最后一层的**输出**（甚至 final norm 之后），而代码取的是最后一个 block **MLP 的输入**——这两者是 transformer 内部不同位置的向量 | 更像一处未被标注的实质分歧，而不只是"论文写得糙" |
| C57 | §4 L99 | 边界：ONLINE 内部才是一次 forward pass；两边只通过两个概率分布向量的加权和交换信息（无文本、无向量检索、无 embedding 传递）；OFFLINE 在推理时完全不存在 | ✓ | `memdec_model.py:73-104` 的接口面就是 logits→log_softmax→logaddexp；eval 路径无任何 faiss import | 否定式断言成立 |
| C58 | §4 图 | ① 锚点 `saveEmbedMulti.py:377-425` | ✓ | 覆盖 `break_into`(377-411) + `pre/post_forward_hook`(413-424) | — |
| C59 | §4 图 | ② 锚点 `build_index.py:126-201` | ✓ | 函数 126-202 | — |
| C60 | §4 图 | ⑤ 锚点 `train_memdec_trainer.py:765-802` | ◐ | 同 C24，`compute_loss` 实际 765-811 | — |
| C61 | §4 图 | FUSE 锚点 `memdec_model.py:93-97` | ✓ | `:93-98` | — |

### 2.3 methodology-flow.md（抽检）

| # | 断言 | 判定 | 证据 |
|---|---|---|---|
| M1 | 域 CPT `§3.3 / §4, txt:480-485,533-536` | ✓ | §3.3 起于 txt:480，内容 481-485；§4 实现细节 533-536 |
| M2 | memory bank 只表示选择已训练 checkpoint（§5.3, txt:803-805） | ✓ | txt:804-805 |
| M3 | `beta=0.5 · §2 Eq.1 / Appx.B` | ✓ | Table 9 txt:2145/2163/2181、Table 10 txt:2225/2240/2255 |
| M4 | `alpha validation-tuned, grid 0:0.05:1 · Appx.F` | ✓ | txt:2970-2976、Fig.11 caption txt:3211 |
| M5 | Table 9 run 级 GPU 数为 64/64/256，不是所有规模都用 256 | ✓ | txt:2147 / 2165 / 2183（行名 txt:2202） |
| M6 | 稀疏分布 64.95 nonzeros/row、~250× | ✓ | txt:469-470 |
| M7 | `saveEmbedMulti.py:319-332` = Arrow schema | ✓ | 精确（优于 code-architecture.md 的 296-312） |
| M8 | `build_index.py:177-200`、`saveKNNMulti.py:143-178`、`flatten_arrow.py:70-180`、`cal_loss.py:47-99`、`memdec_model.py:73-79 / 80-86 / 88-98`、`train_base.py:352-361` | ✓ | 逐条打开确认，全部落在正确函数体内 |
| M9 | `self-query top-K=1024, temperature=16, nprobe=32, ignore first`（`save_knn_pipeline.sh:145-159`） | ✓ | `:50` K=1024、`:51` KNN_TEMP=16.0、`:52` PROBE=32、`:158` `--ignore_first True` |
| M10 | `threshold=0` 不执行 Eq.6 的 ε 剪枝，但输出仍是 K-induced sparse support | ✓ | 表述比 code-architecture.md 冲突点 3 更准确 |
| M11 | `_load_faiss_index()` CPU fallback 会因未绑定 `gpu_index` 失败（`saveKNNMulti.py:92-109`） | ✓ | `gpu_index` 只在 `:99` 的 if 分支内赋值，`:109` 无条件 return |
| M12 | "lm-eval 使用 task-aware 288-entry `lmbda=auto` registry；OpenCompass 默认固定 `LMBDA=0.3`，两套评测默认不一致" | ◐ | 同 C54：lm-eval 树内的 FinEval（`evaluate_fineval.sh:21`）与 knowledge 脚本（`evaluate_multihopqa.py:54`、`evaluate_halueval.py:43`）默认同样是 0.3 |
| M13 | `IO:Corpus ... README:131-145` | ✓ | README 131-145 正是 "1. Preprocess text" 到 `dstore_range` 说明 |

## 3. 步骤清单 — 论文侧

> 这是一个**参数化**记忆系统，不存在"写入侧 / 检索侧"的二分。真正的分界是**离线工厂线（一次性，产出 `M_ψ` 权重）** 与 **在线一次 forward pass**。下面按实际执行顺序列出；标 `~` 的是条件触发。
>
> **推理时压根不存在的检索侧阶段**（不是"省略"，是"没有"）：没有 `P-QUERYPARSE`（不解析 query，`M_ψ` 拿到的就是原始 token ids）、没有 `P-DENSE` / `P-SPARSE`（推理时没有任何最近邻搜索或 BM25，datastore 与 Faiss 索引在这个阶段根本没被加载）、没有 `P-SYMFILTER` / `P-GRAPHEXPAND` / `P-DIFFUSE`（没有符号属性、没有图）、没有 `P-FUSE`（没有多路候选可融）、没有 `P-RERANK`（没有候选列表）、没有 `P-SELECT`（没有组合优化）、没有 `P-ASSEMBLE`（没有任何文本被拼进 prompt——`M_ψ` 与 `M_θ` 收到的是**同一段未经修改的上下文**）、没有 `P-TOOLLOOP`。同样地，写入侧的 `P-INTAKE / P-REWRITE / P-EXTRACT / P-META / P-DEDUP / P-CONFLICT / P-LINK / P-AGGREGATE / P-EVICT` 在运行时全部不存在——这个系统**没有运行时写入路径**，每 turn / 每 session 末都不发生任何事。也没有 `P-SIDEPATH`（无副路状态）、没有 `P-INJECT`（**不注入隐状态**，唯一的耦合面是输出概率分布）。

**A. 离线工厂线（memory pretraining，全系统一次；域记忆按域各跑一次）**

| # | name（论文自己的叫法） | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| A0 | Continued pretraining of the datastore model（§3.3 / §4，txt:482-484, 533-534） | 离线一次（**仅域记忆**） | 领域语料 → CPT 后的 Qwen3-4B-Base | no（是梯度训练，不是生成调用） | 模型 checkpoint | `~P-TRAIN` |
| A1 | Retrieval key extraction `φ_θ(c_t)`（§3.1 Eq.3，txt:294-296） | 离线一次，语料每个 token 位置 | 语料 `D_mem` → 冻结 `M_θ` 最后一层隐藏态 | no（纯前向，当特征提取器） | — | `P-FROZENFWD` |
| A2 | Key-value datastore `R_mem = {(k_t, x_t)}`（Eq.3，txt:306） | 同上，随 A1 流式产出 | (隐藏态, 下一个真实 token) → datastore | no | 向量库（离线，推理时不加载） | `P-DATASTORE` |
| A3 | Distributed Faiss index build（§3.1 + Fig.3 步骤 1-2，txt:436-442） | 离线一次 | N×4096 keys → OPQ256 压到 256 维 → IVF（IndexHNSW 量化器）→ 按连续质心区间切成 S 个 `IndexIVFPQ` 分片 | no | ANN 索引 | `P-ANNINDEX` |
| A4 | Large-scale parallel retrieval（§3.1 Fig.3 步骤 3，txt:443-448） | 离线一次，语料每个位置一次 query | 每 token 的 query → HNSW 路由到分片 → 各 GPU 局部 IVFPQ 搜索 → writer 按 query id 合并出 top-K | no | 读 ANN 索引 | `P-DENSE`（**离线**，非推理时） |
| A5 | kNN distribution `p_ret`（§3.1 Eq.4-5，txt:311-320） | 同 A4 | K 个邻居距离 → `softmax(-d/τ)` 归一权重 → 按 value token 加权投票 | no | — | `P-KNNDIST` |
| A6 | Sparse kNN distribution storage（§3.2 Eq.6，txt:458-472） | 同 A5 | 稠密 `p_ret` → FP32 聚合重复 target → 丢掉 `p ≤ ε` → 分片扁平数组 + offset（平均 64.95 项/行，≈250×） | no | 稀疏分布存储（Arrow/扁平数组） | `P-PERSIST`（ε 剪枝这一子动作最接近 `P-EVICT` 的"压缩"语义） |
| A7 | Distributed streaming of kNN distributions（§3.2，txt:473-479） | 训练时每个 batch | offset + 只读 memmap → 该 batch 需要的连续切片 → 稀疏坐标三元组 → GPU 上 FP32 重归一化 | no | 读 A6 | （纯 I/O，无对应种子 primitive；不新造标签，归入 A8 的数据通路） |
| A8 | Memory pretraining `L_mem = β·KL + (1−β)·CE`（§2 Eq.1，txt:269-271；β=0.5，Table 9/10） | 离线一次（300B tokens / 域记忆一个 CPT epoch 预算） | (`c_t`, `p_ret`, `x_t`) → `M_ψ` 权重 | no（被训练对象，不是被调用者） | 写出 `M_ψ` checkpoint | `P-TRAIN` |

**B. 评测协议（不是运行时步骤，属评测脚本一侧）**

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| B1 | Interpolation coefficient tuning（§4 txt:543-544；附录 F txt:2970-2976，α∈{0.00,0.05,…,1.00}；Table 15 逐任务值） | 每个 benchmark 离线一次（**有验证集时才做**） | 验证集 → 固定的 α | no | — | `~P-INTERP`（标定，非推理动作） |

**C. 在线（每一次 next-token 预测）**

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| C1 | `M_θ` forward（§2 txt:274） | 每 token / 每 forward pass | 上下文 `c_t` → `p_θ(·\|c_t)` | 1 次冻结主干前向（**backbone 侧，不属记忆系统**） | — | `P-FROZENFWD` |
| C2 | `M_ψ` forward（§2 txt:274；"without taking retrieved text as input" txt:258） | 每 token，与 C1 并行 | **同一段** `c_t` → `p_ψ(·\|c_t)` | 1 次冻结记忆模型前向 | **不碰任何存储** | `P-FROZENFWD` |
| C3 | Interpolation（§2 Eq.2，txt:275-277） | 每 token | `p_θ`, `p_ψ`, α → `p_final=(1−α)p_θ+α p_ψ` | no | — | `P-INTERP` |
| C4 | 采样/打分并自回归回灌 | 每 token | `p_final` → next token | —（backbone/评测框架侧） | — | `P-GENERATE`（边界外） |

## 4. 步骤清单 — 代码侧

**A. 离线工厂线（`scripts/` 三条 launcher 串起来）**

| # | name（代码自己的叫法） | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| A0 | Preprocess text（`scripts/data/preprocess_text.sh` → `utils/preprocess_dataset.py:111-167`） | 离线一次 | JSONL `text` → HF DatasetDict（`input_ids`/`attention_mask`/`labels`/**`dstore_range`**），`block_size` 默认 2048、stride 默认 `block_size-1` | no（只用 tokenizer） | 磁盘 HF dataset | `P-INTAKE` |
| A0' | *（论文有、代码没有）* domain backbone CPT | — | — | — | — | **缺失**：`scripts/` 无对应 launcher |
| A1 | Save datastore（`save_knn_pipeline.sh:101-112` → `train_base.py --save_knnlm_dstore` → `KNNSaverMulti.break_into` `saveEmbedMulti.py:377-411`） | 离线一次，每 token 位置 | `input_ids` → hook 抓 `layers[-1].mlp` 的**输入**（fp16）当 key，shift 后的 label（int32）当 value，`-100` 位置丢弃（`:347-355`） | no（`trainer.evaluate()` 纯前向，`train_base.py:389`） | Arrow `dstore_*.arrow`（`:319-332`） | `P-FROZENFWD` → `P-DATASTORE` |
| A2 | Build index（`save_knn_pipeline.sh:126-131` → `knn_utils/build_index.py:126-202`） | 离线一次 | Arrow keys → `IndexIVFPQ(IndexFlatL2, d, ncentroids=4096, code_size=64, nbits=8)`，用 1000 段连续块共 ≤1e6 向量训练（`:182-183`），全量 `add_with_ids`（`:198`）→ **单个** `.index` 文件 + `*_vals.pkl` | no | Faiss 索引（单机、不分片、无 OPQ/HNSW） | `P-ANNINDEX` |
| A3 | Save KNN results / self-query（`save_knn_pipeline.sh:145-159` → `saveKNNMulti.KNNSearchMulti.process` `:248-267`） | 离线一次，datastore 每行一次 query | 同一批 keys 当 query → 每进程各自 `read_index` 整份索引并放到自己那张 GPU（`:92-109`）→ `index.search(q, k=1024)`（`:133`）→ `ignore_first` **无条件**砍掉 top-1（`:138-139`），剩 1023 个 | no | 读 Faiss 索引 | `P-DENSE`（离线） |
| A4 | `knns_to_probs`（`saveKNNMulti.py:143-153`） | 同 A3 | `softmax(-d/τ)`（τ=16.0，`save_knn_pipeline.sh:51`）→ `scatter_add` 到词表 → L1 归一 | no | — | `P-KNNDIST` |
| A5 | `sparsify_distribution` + `_save_step_data`（`:155-178`, `:180-246`） | 同 A3 | 留 `p > threshold`（**默认 0**，`:292`），概率降序 → 跨 rank gather → rank0 写 Arrow（`id_cnt/token_id/prob/label`，`:115-120`） | no | Arrow 稀疏分布 | `P-PERSIST`（论文 Eq.6 的 ε 剪枝**默认不执行**） |
| A6 | `flatten_knn_arrow.sh` → `utils/flatten_arrow.py:70-180` | 离线一次 | Arrow → 每分片 `offset.npy`/`flatten_token_id.npy`/`flatten_prob.npy`/`label.npy`/`shape.json` memmap | no | memmap 分片 | `P-PERSIST` |
| A7 | Train memory（`scripts/train/train_domain_memdec.sh` → `train_memdec_trainer.py`） | 离线一次 | `KNNDstore.get_batch_sparse`（`:300-373`）按 `dstore_range` 读 memmap → `MemDecTrainer.compute_loss`（`:765-811`）→ `cal_loss.kl_loss_token_memdec_sparse`（`:47-99`）：行内重归一（`:84-90`）、`total = alpha*KL + (1-alpha)*CE`（`:98`），`alpha=0.5`（`:139`）；模型 = `AutoModelForCausalLM.from_pretrained(MODEL_PATH)`（`:1165`），`resize_token_embeddings` 到 tokenizer（`:1206`），可选 reinit（`:1209-1211`） | no | 写 `M_ψ` checkpoint | `P-TRAIN` |

**B. 评测框架侧（不属记忆系统本体）**

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| B1 | λ 选取，**三套彼此独立的实现** | (a) `HFMemDec._run_with_task_defaults`（`hf_memdec.py:181-236`）按 **task 分组**查 288 条表（`resolve_default_lambda`）后 `set_lmbda`（`:214`）——只有 general 套件默认走这条（`scripts/general/evaluate.sh:28`）；(b) FinEval 与 knowledge 脚本写死 0.3（`evaluate_fineval.sh:21`、`evaluate_multihopqa.py:54`、`evaluate_halueval.py:43`）；(c) opencompass 写死 0.3（`eval_bioinst_memdec.py:44`、`eval_lawbench.py:83`） | 任务名 → λ | no | 读 JSON 注册表 | `~P-INTERP`（参数选取） |

**C. 在线（`MemoryDecoder.forward`，每 token / 每次打分前向）**

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| C1 | `base_lm` forward（`memdec_model.py:73-79`） | 每 forward | `input_ids` → `logits_base`，自己的 `past_key_values`（`:102`） | 1 次冻结主干前向（backbone 侧） | — | `P-FROZENFWD` |
| C2 | `memdec_lm` forward（`:80-86`） | 每 forward，与 C1 同一 `input_ids` | → `logits_memdec`，自己的 `memdec_past_key_values`（`:103`）；可选 `memdec_temp` 除法（`:90-91`） | 1 次冻结记忆前向 | **不碰任何存储** | `P-FROZENFWD` |
| C3 | Fuse（`:93-98`） | 每 forward | `log_softmax` 两路 → `logaddexp(logp_base+log(1-λ), logp_mem+log λ)` | no | — | `P-INTERP` |
| C4 | 解码/打分（`:141`/`:165` argmax，或 `HFLM.loglikelihood`） | 每 token / 每请求 | `p_final` → token 或 score | —（评测框架侧） | — | `P-GENERATE`（边界外） |

**D. 仓内可达但不在主链路上**

- `KNNWrapperMulti`（`saveEmbedMulti.py:47-286`，唯一实例化点 `train_base.py:353`，仅 `--knn` 分支）：经典**在线** kNN-LM 插值器（`P-DENSE` + `P-INTERP` at inference）。没有任何 launcher、评测配置或 README 章节调用它——如果它被启用，这个系统就退化成 kNN-LM，正是论文声称要消除的东西。
- `KNNSaverMulti.build_index`（`saveEmbedMulti.py:444-481`）：**第二份**索引构建实现（抽样 200k、`code_size` 默认 32），全仓无调用点，被 `knn_utils/build_index.py` 完全取代。两份文档都没提。

## 5. 论文↔代码分歧

| # | 分歧 | 分类 | 论文证据 | 代码证据 |
|---|---|---|---|---|
| D1 | **分布式 Faiss 流水线**：OPQ256 压缩 + IndexHNSW 量化器 + 按连续质心区间的 `IndexIVFPQ` 分片 + 路由/并行 GPU 局部检索 + writer 合并 | [paper-only] | txt:436-449、Fig.3 caption txt:424-428 | 全仓 `grep -rni "hnsw"` 零命中、无 OPQ、无索引分片；只有单机单 `IndexIVFPQ(IndexFlatL2, …)`（`build_index.py:177-178`），且每进程加载**整份**索引到各自 GPU（`saveKNNMulti.py:96-103`，`gpu_id = process_index % num_gpus`）——是 query 数据并行，不是索引分片 |
| D2 | **key 取在网络里的哪个位置**：论文 = "hidden state from the **final layer**"；代码 = 最后一个 block **MLP 的输入**（即 `post_attention_layernorm` 的输出） | [两边都有但行为不同] | txt:294-296、txt:431-432 | `saveEmbedMulti.py:274-285`（`layers[-1].mlp`, `capture_input=True`）+ `ActivationCapturer:492-493`（取 `input[0]`） |
| D3 | **自检索剔除规则**：论文 = 只在 top-1 的 key **等于** query 时丢弃（条件式）；代码 = 只要 `ignore_first` 为真就**无条件**丢掉 top-1 | [两边都有但行为不同] | txt:302 | `saveKNNMulti.py:138-139`；launcher 恒传 `--ignore_first True`（`save_knn_pipeline.sh:158`）。后果：有效邻居数 K−1=1023 |
| D4 | **ε 稀疏化**：论文 Eq.6 用小阈值 ε 剪掉可忽略概率；代码 CLI 默认 `threshold=0` 且 launcher 不覆盖 | [两边都有但参数不同] | txt:461-464（Eq.6）、txt:469 "each row retains 64.95 token-probability pairs" | `saveKNNMulti.py:292`（default 0）、`:165`（`> threshold`）；`save_knn_pipeline.sh:145-159` 不传该参数。注意构造函数默认其实是 `1e-10`（`:33`），但 CLI 路径会覆盖成 0 |
| D5 | **域 backbone CPT**：论文明确要求先用 Qwen3-4B-Base 做一轮领域 CPT 再建 datastore | [paper-only] | txt:482-484、txt:533-534 | `scripts/` 只有 3 个 data 脚本 + 1 个 train 脚本；README:128-129 只列三阶段，无 CPT launcher |
| D6 | **memory bank** | [paper-only] | txt:804-805 | 全仓无 `memory bank` 数据结构/注册表/服务；只有显式 `--memdec_path`（`hf_memdec.py:97`）/ `knn_model_path`（`eval_bioinst_memdec.py:62`）。存在的只是一张按 HF repo id 索引 3 个公开记忆的 **λ** 表（`memorydecoder_default_lambdas.json`） |
| D7 | **λ/α 的取值机制**：论文只说"有验证集时在验证集上调好后固定"（一套说法覆盖全部评测）；代码有**三套**互不相同的实现 | [两边都有但行为不同] | txt:543-544、附录 F txt:2970-2976 | (a) 288 条 task-aware 注册表 + 按 task 分组 `set_lmbda`（`hf_memdec.py:203-214`、`memorydecoder_defaults.py:118-141`），只有 general 套件默认启用（`scripts/general/evaluate.sh:18,28`）；(b) FinEval / knowledge 默认写死 0.3（`evaluate_fineval.sh:21`、`evaluate_multihopqa.py:54`、`evaluate_halueval.py:43`）；(c) opencompass 默认写死 0.3（`eval_bioinst_memdec.py:44`、`eval_lawbench.py:83`）。注册表元数据自称值来自 "audited report"、部分是 "retained near-optimal point"，不等价于论文说的验证集调参 |
| D8 | **记忆模型输出温度 `memdec_temp` / `knn_temp`**：把 `p_ψ` 换成温度缩放后的分布再插值，Eq.2 里没有这一项 | [code-only] | Eq.2 txt:275-277 无温度 | `memdec_model.py:33,43,90-91`；`hf_memdec.py:99,170`；opencompass `memdec.py:34,48,135-136`；launcher 暴露 `MEMDEC_TEMP`/`KNN_TEMP`（`evaluate_fineval.sh:21`、`eval_bioinst_memdec.py:64`）。默认 1.0，默认行为与论文一致 |
| D9 | **跨词表对齐的实现**：论文只说"替换 embedding 层和 LM head 后继续训练"，没说 Eq.2 的 `V` 怎么统一；代码有两处具体但不同的做法 | [code-only] | txt:536-538；`V` 的处理正文未解释（见 P48） | 训练侧 `train_memdec_trainer.py:1206-1211`（resize + 可选 reinit）；lm-eval 侧把 memdec 的 embedding resize 到 base 词表（`hf_memdec.py:163`）；opencompass 侧改为把两边 logits **用 -inf 补齐到 max 词表**再融合（`memdec.py:80-101`）——同一篇论文的两套评测代码对同一件事有两种不兼容处理 |
| D10 | **CPU fallback 崩溃**：`_load_faiss_index` 在无 GPU / `--knn_gpu` 未开时仍 `return cpu_index, gpu_index`，而 `gpu_index` 只在 GPU 分支里赋值 | [code-only] | — | `saveKNNMulti.py:99-109`（`UnboundLocalError`） |
| D11 | **在线 kNN-LM 死代码**：论文全篇主张推理时不做检索，仓里却留着一个完整的在线 kNN 检索插值器 | [code-only] | txt:259、txt:1727-1729 | `KNNWrapperMulti`（`saveEmbedMulti.py:47-286`），仅 `train_base.py:353` 的 `--knn` 分支可达，无 launcher/评测路径调用 |
| D12 | **打包块长与 GPU 数**：论文附录 A 说按 4096 打包（域记忆 Table 10 seq len 4096；通用记忆 Table 9 是 2048）；代码预处理默认 `block_size=2048`。另论文 §4 说全部实验用 256 卡，Table 9 却是 64/64/256 | [两边都有但参数不同] | txt:2018-2019、Table 9 txt:2135/2147、Table 10 txt:2214 | `utils/preprocess_dataset.py:59`、`scripts/data/preprocess_text.sh:12` |

## 6. 新造的 primitive 标签

**无。** 全部步骤都能用种子词表覆盖。两处做过取舍、在此说明理由：

1. **`M_ψ` 的推理前向标成 `P-FROZENFWD` 而不是新造标签**：种子词表里没有"参数化记忆读取"这一项，但这一步本质上就是"一个权重冻结的 transformer 解码器做一次前向、输出词表分布"，与 `P-FROZENFWD` 的定义完全同构；它与 backbone 那一路的区别是**角色**（记忆 vs 主干）而不是**动作**，角色靠步骤名和边界标注区分即可。特别地，它**不是** `P-DENSE`——没有任何最近邻搜索发生；也**不是** `P-INJECT`——没有隐状态被注入任何地方。
2. **`p_ret` 的稀疏流式加载（论文 A7）没有单独标签**：它是训练数据通路的 I/O 实现，不是记忆操作本身，强行造一个 `P-STREAM` 只会污染跨系统对齐的词表；已归并进 `P-TRAIN` 的描述里。
3. **域 backbone CPT 复用 `P-TRAIN`**：它是 CE-only 的梯度训练，落在 `P-TRAIN 梯度训练(KL蒸馏/CE)` 的定义内；它与写入记忆的那次 `P-TRAIN` 的区别是**训练对象**（datastore 用的 backbone vs 记忆本体），在步骤表里已标明。

## 7. 复核统计

| 文档 | ✓ | ✗ | ◐ | ? | 小计 |
|---|---|---|---|---|---|
| paper-architecture.md（P1-P59） | 50 | 3 | 5 | 1 | 59 |
| code-architecture.md（C1-C61） | 43 | 2 | 16 | 0 | 61 |
| methodology-flow.md（抽检 M1-M13） | 12 | 0 | 1 | 0 | 13 |
| **合计** | **105** | **5** | **22** | **1** | **133** |

`✗` 五条：P32（图 2 "两个 ACTIVE" 不存在）、P35（引文错标 §7，实为 §1 txt:216）、P53（β 默认值论文其实给了，Table 9/10 = 0.5）、C2（HEAD `bbbbee85` → `bbbfee85`）、C20（`--ignore_first` 不是"丢掉完全重合的邻居"，是无条件丢 top-1）。
`◐` 二十二条里，**8 条是纯锚点问题**（C8/C15/C17/C28/C33/C44/C60 的行号漂移，P47 的章节归属），表内已逐条给出正确行号；C10、C24 是行号 + 描述各错一半；其余 12 条（P4/P21/P52/P59/C4/C6/C32/C53/C54/C55/C56/M12）是需要加限定的实质性判断。另有 3 条判 ✓ 但区间末端越界几行、不影响定位的（C11 差 2 行、C12 越界 4 行、C26 多 1 行），已在备注里注明。

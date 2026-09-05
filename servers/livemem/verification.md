---
title: LiveMem 架构文档复核报告
date: 2026-09-05
tags:
  - memory-bench
  - verification
  - livemem
---

# livemem 架构文档复核报告

> 复核日期 2026-09-05；论文源 `Liu-etal-2026-LiveMem-Maintaining-Memory-State-Continuity-in-Long-Running-LLM-Inference.txt`（1921 行，行号均为本次 `grep -n` 亲验；表格类证据另以 `pdftotext -layout -f N -l N` 从同名 PDF 复核版面）；代码源 `LiveMem` @ `71a6a8b`（唯一提交 `Initialize repository`，Chen \<12011125@mail.sustech.edu.cn\>，2026-08-06）。
> 复核范围：`paper-architecture.md`（183 行）、`code-architecture.md`（223 行）。同目录 `methodology-flow.md` 是基于这两份文档的下游产物，不在本次断言核对范围内。

## 1. 总评

两份文档整体质量高，机制层面的核心判断全部站得住：LiveMem 是"每 token、每层、前向传播内"的递归副路 + KV 窗口驱逐，没有任何外部记忆库、没有检索、没有额外 LLM 调用——这些结论我逐条追到了论文原句和代码实现，无一处夸大。定量交叉验证尤其干净：论文 Table 5 的五行 fixed-stride 参数与 `train/sft/eviction_policy.py:57-64` 的 `RULE_TABLE` 完全一致，附录 C.4 的训练超参与 `livemem_sft_stage1/2.yaml` 完全一致，附录 C.1 的 `32×128×128 / FP32` 与 `gdn2_side.py:200,208` 完全一致。

问题集中在三类。第一类是**否定式断言过头**：`paper-architecture.md` 说"论文没有描述任何门控是否采纳记忆读出的机制"，但附录 C.1（txt:1622-1623）白纸黑字写了读出要过一层 **gated RMS normalization**（代码里就是 `FusedRMSNormGated`）；同样地"论文从未讨论跨请求延续"也被 C.3 的 "preventing accidental state leakage between requests"（txt:1713-1714）部分证伪。第二类是**一处硬性事实错误**：`paper-architecture.md` 第 5 节说 Table 1 里 Recurrent 列在 Wiki QA 有空格且论文没解释——实际空格全在 **RAG** 列，且附录 D.3（txt:1816-1817）明确解释了原因。第三类是**行号漂移**：`code-architecture.md` 的 44 处代码引用里绝大多数精确到行，但 `copy_init_side_branch` 的 `395-450` 实际在 `529-590`，`PREFIX_MODELS` 的 `64-65` 实际在 `60`。

`code-architecture.md` 第 5 节"message 与 stride 两种驱逐策略在 8k/32k 恰好重合"是唯一一条硬错误：`RULE_TABLE` 的最大 window 只有 8192，**根本没有 32768 这一档**，chunk 也是 512 而非 1024；而且论文 C.2（txt:1683-1685）已经把这个"开放问题"回答了。顺带我发现了两份文档都没抓到的一处真实论文↔代码分歧：论文 C.2 说 "serving ... use deterministic fixed-stride chunks"，但评测用的 `scripts/serve_livemem.sh` 走的是按 `<|im_start|>` 消息边界切块的 **message 模式**，只有 RL rollout（`run_grpo_dev.sh:124`）才是 fixed-stride。

## 2. 逐条核对表

### 2.1 `paper-architecture.md`

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| P1 | 表头 | arXiv:2608.02515v2 | ✓ | txt:18 | — |
| P2 | §1 | 提出 state continuity under context turnover 作为独立问题 | ✓ | txt:23-25（Abstract）、txt:1023-1024（Conclusion） | — |
| P3 | §1 | 每层挂并行递归状态；主路只保留固定窗口 + system prompt 作 attention sink | ✓ | txt:194（side branch to each attention layer）、txt:252-256（system prompt as attention sink + FIFO 队列） | — |
| P4 | §1 | §2.1 定义 reconstructive inference | ✓ | txt:140 | — |
| P5 | §1 | §2.2 Eq(2)(3) 定义 `M_{t+1}=U_φ(M_t,X_{t+1})`、`y_t~p_{θ,φ}(y_t|C_t,M_t)` | ✓ | txt:147-148 | — |
| P6 | §2 触发时机 | 引 "The read and update operations are performed per token ... no additional write operations are performed."，位于 §3.1 Eq(7)-(9) 之后 | ✓ | txt:241-243；Eq(9) 在 txt:233-235 | 逐字无误 |
| P7 | §2 存什么 | GDN2 状态矩阵 `S_t ∈ R^{d_k×d_v}`；引 Hatamizadeh et al. 2026 | ✓ | txt:217、txt:195 | — |
| P8 | §2 | "We do not require that Mt be able to reconstruct every token exactly."（§2.2） | ✓ | txt:155-156 | — |
| P9 | §2 Eq7 | forget：`S̄_t = Diag(exp(g_t))·S_{t-1}`，`g_t≤0` | ✓ | txt:226-227、txt:218 | — |
| P10 | §2 Eq8 | erase and prepare：`ρ_t = w_t⊙v_t − S̄_tᵀ(b_t⊙k_t)`，`b_t∈[0,1]^{d_k}` | ✓ | txt:230-231、txt:218 | — |
| P11 | §2 Eq9 | write and read：`S_t = S̄_t + k_tρ_tᵀ`（写）、`r_t = S_tᵀq_t`（读），`w_t∈[0,1]^{d_v}` | ✓ | txt:233-235、txt:218 | 读用的是更新后的 `S_t`，文档"先写后读"的表述正确 |
| P12 | §2 | 附录 C.1 给出等价单行形式 Eq(15) | ✓ | txt:1620 | — |
| P13 | §2 | 三个门"用同一个隐藏表示 `h_t^ℓ` 算出来，和主路 attention 共享输入" | ◐ | txt:196-197、txt:199/203（Eq4/5） | 属实但漏了一步：C.1 txt:1619 明说 q/k/v 投影**前**还有一个宽度 4 的短因果卷积；文档全篇未提 |
| P14 | §2 调不调 LLM | 论文没提"额外调一次 LLM 做摘要/压缩记忆" | ✓ | 全文 `summar` 仅 5 处：txt:22,51,107,694,1755，均非 LiveMem 自身机制 | 否定式断言，已实际证伪尝试 |
| P15 | §2 | Eq(4)-(6) 原式 | ✓ | txt:199,203,204 | — |
| P16 | §2 参数初始化 | q/k/v 从主干复制、其余独立初始化、输出投影零初始化、"刚接上时等价原模型" | ✓ | txt:244-247（逐字）、txt:1630-1632（C.1 复述） | — |
| P17 | §2 | C.1：36 层 / 32 query head / 8 KV head / head dim 128；记忆路径每层 32 q/k/v head、dim 128；每层每请求 `32×128×128`，FP32 | ◐ | txt:1624-1629 | 数字全对；但原文紧接一句 "**in addition to the short-convolution state**"，文档把状态说成只有一块矩阵 |
| P18 | §2 触发范围 | "attached as a side branch to each attention layer"（§3.1 开头），每层都装 | ✓ | txt:194 | — |
| P19 | §3 触发时机 | 每 token、每层都算一次读出，不是提问时才检索 | ✓ | txt:241-242、txt:267（"eqs. (7) to (9) scan over the entire sequence"） | — |
| P20 | §3 | 用当前 token 的 `q_t`，经 `r_t = S_tᵀq_t` 读出（Eq(9) 后半） | ✓ | txt:233 | — |
| P21 | §3 | 论文根本没把这个过程叫 retrieval；"This mechanism is complementary to external retrieval systems." | ✓ | txt:158；全文 21 处 `retriev` 无一处指 LiveMem 自身读出 | 否定式断言，已逐条排查 |
| P22 | §3 | `o_t^ℓ = a_t^ℓ + r_t^ℓ`（Eq6）；图 2 图注"Their outputs are combined at every decoder layer" | ✓ | txt:204、txt:166 | — |
| P23 | §3 | "论文没有描述任何『筛选/加权/门控是否采纳记忆读出』的显式机制……就是简单相加" | ✗ | txt:1622-1623："The readout St⊤qt passes through a **gated RMS normalization** and an output projection before it is added to the softmax-attention output." | 附录 C.1 明写了作用在读出上的 sigmoid 门（代码即 `FusedRMSNormGated`，`third_party/flash-linear-attention/fla/layers/gdn2.py:197`）。同目录 `code-architecture.md` §3 反而写对了"过一层 gated RMSNorm"，两份文档自相矛盾 |
| P24 | §3 | §4.3 标题 "Does the Recurrent State Carry Evicted Evidence?" | ✓ | txt:700-702 | — |
| P25 | §3 | Table 2 的 "State"/"Trunc." 定义 | ✓ | txt:716-718 | — |
| P26 | §3 | "Table 2 显示多数数据集上 State 优于 Trunc." | ✓ | txt:707-710 | 原文更强（SFT 除 LongMemEval 外全部提升，RL 全部提升）；文档说法偏保守但不算错 |
| P27 | §3 | Figure 3：证据被完全挤出时 LiveMem 比 Qwen3-4B/δ-Mem 高十个百分点以上 | ✓ | txt:897-899（"outperforms them by more than ten percentage points"）；PDF p9 图内数值 Qwen3-4B 3.1% / δ-Mem 3.6% / C2L 9.4% / LiveMem-SFT 14.3% / LiveMem-RL 16.5% | 差值 +11.2 / +13.4 pp，属实 |
| P28 | §3 | Figure 4：以 K token 为单位控制 evidence-to-window distance；轻微下降但整体稳定，未在驱逐边界断崖归零 | ✓ | txt:903-906、txt:894-896（图注）；PDF p9 横轴 8/16/32/48/64 K | 逐字对应 "slight downward trend ... remains at a stable level" |
| P29 | §3 | 附录 D.2 "LiveMem instead scans up to 256K input tokens while maintaining only the stated live KV budget" | ✓ | txt:1786 | 逐字无误 |
| P30 | §3 | 附录 E.2：RoPE 最大位置 262,144 token | ✓ | txt:1907-1908 | 另可交叉验证 `models/vllm/memory_qwen3/configuration_memory_qwen3.py:31` `max_position_embeddings=262144` |
| P31 | §4 边界说明 | Eq(2)(3) 的 `p_{θ,φ}` 是同一模型两组参数；图 2 分 "full-attention main path" / "recurrent side path" | ✓ | txt:145-148、txt:163-165 | — |
| P32 | §4 图 | §3.2 Eq(10) `visible(i,j)` | ✓ | txt:261 | — |
| P33 | §4 边界说明 | "forward pass 之外……谁来发起推理请求、历史怎么拼进 prompt——论文完全没有建模" | ◐ | txt:1795-1797（D.3 规定输入格式 `[system prompt, user prompt (memory documents, question), assistant answer]`）、txt:1777-1791（D.2 规定统一 system instruction、截断规则、生成预算） | 正文确实没建模，但附录 D.2/D.3 把请求组装作为**评测协议**规定得相当具体；"完全没有建模"过强 |
| P34 | §5 | 数据配比确切数字论文没给；正文只说 "removed the majority of the long-text QA data"；Table 3(b) 三设置 | ✓ | txt:1005-1007；PDF p10 Table 3(b) 三行 Direct mixture / Rebalanced mixture / Long warmup + rebalanced | — |
| P35 | §5 | "Table 1 里 **Recurrent** 方法在 Wiki QA 部分若干格是空的（'-'），正文没有解释" | ✗ | PDF p7 Table 1：Wiki QA 区块的 3 个 "-" 全部落在 **RAG** 列（2Wiki-MQ / Hotpot-MQ / MuSiQue-MQ）；Recurrent 列六格全有数值 0.775 / 0.204 / 0.819 / 0.256 / 0.483 / 0.165。且 txt:1816-1817 明确解释："Since RAG's top-k fundamentally cannot meet the evidence requirements of the MQ task, we omit RAG's performance on MQ." | 列名错 + "没有解释"错，两处都不实。这是本次唯一的硬性事实错误 |
| P36 | §5 | Eq(10) 处没给 chunk 大小/驱逐阈值具体数值，要翻 C.2 Table 5 | ✓ | txt:261-266（正文无数值）、txt:1660-1675（Table 5） | — |
| P37 | §5 | "（这张表用于 RL rollout 和 serving 场景）" | ◐ | txt:1660-1661 表题为 "used for RL rollout serving and policy recomputation"；txt:1683-1685 明说 benchmark inference **覆盖**为 chunk 1,024 / budget 8K 或 32K | 表里的 "serving" 专指 RL rollout serving；文档措辞容易被读成"评测服务也用 Table 5"，实际不用 |
| P38 | §5 | SFT 语料切块附录只说了一句 "SFT examples use dataset-defined semantic or fixed-token chunks"，未展开 | ✓ | txt:1641-1642 | — |
| P39 | §5 | "完全没有找到 Design Y / 写门控这类描述" | ✓ | 全文 grep `design x`/`design y`/`write mask`/`write_mask`/`gated read`/`read-only` 零命中；`frozen` 仅 txt:286,1303,1342 三处且与写门控无关 | 否定式断言，已实际证伪尝试，成立 |
| P40 | §5 | living memory state 三条要求，第三条没有独立于下游准确率的量化指标 | ✓ | txt:174-179（三条要求）；全文仅 §4.3 间接支撑 | — |
| P41 | §6 | "多轮/多请求之间状态是否复用，论文正文完全没提……C.3 从未讨论跨请求延续这个问题" | ◐ | txt:1713-1714："This explicit lifecycle implements continuity within a stream while **preventing accidental state leakage between requests**." | C.3 确实只做单请求生命周期，但它给出了明确的跨请求设计立场（禁止泄漏）。准确说法应是"论文明确禁止跨请求泄漏，但没有讨论多轮 agent 主动复用状态的可能" |
| P42 | §6 | README 补了"当前 OpenAI-compatible API 不会在两个独立 request 之间自动复用该 state" | ✓ | `README.md:39` / `README_zh.md:39` | 逐字无误 |
| P43 | §6 | E.1/E.2 写得清楚：NIAH Table 6 显示状态有损；RoPE 262,144 是硬约束；没做超过 256K 实验 | ✓ | txt:1826-1846（Table 6 与讨论）、txt:1901-1910 | — |
| P44 | §6 | "'For δ-Mem, we adopt its TSW setting'，但 TSW 具体是什么……没有解释" | ◐ | txt:1801-1804 | 缩写确实未展开，但紧接一句给出了所采用的行为语义（"directly discarding the portion that exceeds the context window limit"）；"没有解释"过强 |
| P45 | §6 | Context2LoRA `rank=4, alpha=8, lr=5×10⁻⁴` 只陈述配置无依据 | ✓ | txt:1806-1807 | — |
| P46 | §6 | RAG chunk 512 token、以 20 篇文档为界切 top-1/top-3，未解释为何是这两个数字 | ✓ | txt:1812-1815 | — |
| P47 | 相关 | §3 LiveMem 覆盖 Eq4-14 | ✓ | txt:199-204（Eq4-6）… txt:340（Eq14） | — |
| P48 | 相关 | 附录 A Related Work 含 δ-Mem 脚注 3 | ✓ | txt:1351 `3 https://github.com/declare-lab/delta-Mem.`，紧跟 txt:1342-1345 的 δ-Mem 段落 | — |
| P49 | 相关 | 附录 C Infrastructure and State Lifecycle Details（Eq15, Table5） | ✓ | txt:1613、txt:1620、txt:1660 | — |
| P50 | 相关 | 附录 E Limitations（Table6） | ✓ | txt:1822、txt:1827 | — |
| P51 | 表头 | "References 和 Appendix A 在文本流里顺序有点怪" | ◐ | txt:1020 Conclusion → txt:1044 References → txt:1294 Appendix A → 1400 B → 1611 C → 1740 D → 1820 E | 这个顺序完全正常，举的例子不成立。真正的抽取错位是图表标题插进正文（如 Figure 2 图注落在 §2.2 中段 txt:163-168，Table 2 标题落在 §4.3 中段 txt:716-718） |

### 2.2 `code-architecture.md`

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| C1 | 表头 | remote origin = `github.com/cafeii/LiveMem`；单一提交 `71a6a8b`；作者 `Chen <12011125@mail.sustech.edu.cn>` | ✓ | `git remote -v` / `git log -1` 三项逐一吻合 | — |
| C2 | §1 | 给 Qwen3-4B 每层 attention 并联 GDN2 侧支路 | ✓ | `models/modeling_memory_qwen3.py:165-168`、`models/configuration_memory_qwen3.py:75-77`、`train/sft/config/base.yaml:7`（注释 "null = all 36 layers"） | — |
| C3 | §1 | `models/modeling_memory_qwen3.py:80` = `class MemoryAttention` | ✓ | 该行逐字为 `class MemoryAttention(nn.Module):` | — |
| C4 | §1 | `models/modeling_memory_qwen3.py:137` = `o_total = o_main + o_side` | ✓ | 逐字命中 | — |
| C5 | §2 | Design X/Y 共用骨架，靠 `write_mask` 是否为 `None` 切换 | ✓ | `models/memory_gdn2.py:12-14`（文件头说明）、`:128-133`（`if write_mask is not None: g/b/w *= wm`）、`models/modeling_memory_qwen3.py:219-222` | — |
| C6 | §2 | 三处独立证据表明发布模型用 Design X | ✓ | `livemem_sft_stage1.yaml:6`、`livemem_sft_stage2.yaml:7`、`tools/export_checkpoint.py:47`、`models/vllm/memory_qwen3/gdn2_side.py:14` | 实际是**四处**；另有 `train/sft/data.py:177-178` "Design X: RNN scans all tokens, attention evicts; no write_mask is emitted"（`mixture` 走的 `MixedArrowDataset`），第五处 |
| C7 | §2 | 状态几何 32 head × 128 × 128，每层每请求一份，**全程 FP32** | ◐ | `gdn2_side.py:208`（`ssm_state_shape=(num_v_heads/tp, head_k_dim, head_v_dim)`）、`:193-200`（`get_state_dtype` 返回 `(conv_dtype, torch.float32)`） | 形状与"每层每请求一份"✓；但 FP32 只覆盖 SSM 状态，返回的是**二元组**，`conv_dtype` 由 vLLM 计算器给出。且每请求还有第二块分页状态 `conv_state`（`:206-207`），文档未提 |
| C8 | §2 | 证据 `models/configuration_memory_qwen3.py:20-38`：无覆盖时等于 backbone 的 32 头、128 维 | ◐ | 20-38 只有 `mem_head_dim/mem_num_heads/mem_num_v_heads = None` 的**声明**（:28-30）；"等于 backbone" 的解析在 **:58-64**，落在引用范围之外 | 行号轻度漂移 |
| C9 | §2 | `gdn2_side.py` 的 `get_state_shape()` / `get_state_dtype()` | ✓ | `:202-209` / `:193-200` | — |
| C10 | §2 | `models/memory_gdn2.py:6-9` 给出完整数学形式与 `o_t = q_t·S_t` | ✓ | `:6` 与 `:9` 逐字命中 | 与论文 Eq(15)（txt:1620）形式一致 |
| C11 | §2 | 证据 `models/memory_gdn2.py:104-138`（g/b/w 计算 + `chunk_gdn2`/`fused_recurrent_gdn2` 两个 kernel） | ◐ | g/b/w 在 `:116-118`（范围内）；两个 kernel 在 **`:146-156`**（范围外） | 正确范围应为 `:116-156` |
| C12 | §2 | 存的过程不调 LLM，写状态与生成下一 token 同一次 forward | ✓ | `models/modeling_memory_qwen3.py:115-151` 全函数内无任何外部/网络调用 | 结构性成立 |
| C13 | §2 | 证据 `models/modeling_memory_qwen3.py:395-450`（`copy_init_side_branch` 函数） | ◐ | `copy_init_side_branch` 实际定义在 **`:529-590`**；`395-450` 落在 `MemoryQwen3ForCausalLM.forward` 的签名与函数体里 | 内容属实（q/k/v 复制 `:566,570,580`，`zero_o` 分支 `:582-583`），但行号错约 130 行——本次最大的一处漂移 |
| C14 | §2 | `configuration_memory_qwen3.py` 的 `mem_o_proj_zero_init: bool = True` | ✓ | `:36` | — |
| C15 | §2 | `SyntheticPackDataset` 显式生成 `write_mask`（1=M 段，0=QA 段），是 Design Y 的真实使用样例 | ✓ | `train/sft/data.py:321-326`（docstring "Emits write_mask (1 on M, 0 on QA)"）、`:354` | — |
| C16 | §2 | `train/sft/train_sft.py:186-189` 只在 `kind == synthetic/synthetic_pack` 时实例化 | ✓ | 逐字命中 | — |
| C17 | §2 | 两份发布训练配置的 `data.kind` 都是 `mixture` | ✓ | `stage1.yaml:13`、`stage2.yaml:14` | — |
| C18 | §3 | 每 token、每层读一次，不是提问时才检索 | ✓ | 同 C12 + `memory_gdn2.py:146-156` | — |
| C19 | §3 | `r_t = Sᵀq_t`，不存在 encode→相似度→top-k 这类检索步骤 | ✓ | `memory_gdn2.py:6-9,146-156`；全仓库 `models/` 下无向量库/相似度检索代码 | 否定式断言成立 |
| C20 | §3 | 证据 `models/memory_gdn2.py:167-169`（`o_norm`/`o_proj`） | ✓ | `:167` `o = self.o_norm(...)`、`:169` `o = self.o_proj(o)` | — |
| C21 | §3 | o_side 过 gated RMSNorm 与 o_proj 后直接与 o_main 相加，"代码层面没有额外的门控或过滤" | ◐ | `o_norm` 即 `FusedRMSNormGated(head_v_dim, activation="sigmoid")`（`third_party/flash-linear-attention/fla/layers/gdn2.py:197`），由 `g_proj(hidden_states)` 驱动 | 同一句里先承认 gated RMSNorm 又说"没有额外门控"，措辞自相矛盾；只在"两路相加处没有第二重门控"的意义上成立 |
| C22 | §3 | 证据 `models/modeling_memory_qwen3.py:120-138`（`MemoryAttention.forward`） | ◐ | `def forward` 在 **`:115`**，`:120` 是签名中的 `past_key_values` 一行 | 范围确实覆盖 `o_main`/`o_side`/`o_total`（`:123,130,137`），起点轻度漂移 |
| C23 | §3 | 客户端不用取记忆：memory 全文与 query 拼进同一个 user turn | ✓ | `eval/prompt.py:11-13`（头注释）、`:73-77`（`f"{mem}{MEM_SEP}{user_text}"`） | 与论文 D.3 txt:1795-1797 一致 |
| C24 | §3 | 证据 `eval/pipeline.py:64-65`：`PREFIX_MODELS = {"delta","c2l","rag","recurrent"}`，不含 livemem | ◐ | 该定义在 **`:60`**；`:64` 是 `HF_MODELS = {"delta","c2l"}` | 内容属实（`:60` + `:244` `is_delta = args.model in PREFIX_MODELS`），行号错 |
| C25 | §3 | vLLM paged KV，边处理边释放"中间"已过期块，只留 sink + 最近窗口；GDN2 状态槽单独一块不受影响 | ✓ | `evict_manager.py:71-111`（静态回退窗口 `[sink_len, computed-keep_recent)`，`remove_skipped_blocks` 释放）、`gdn2_side.py:113-126`（gather/scatter 独立于 KV）；论文侧 txt:1704-1706 "the memory slot is unaffected" | — |
| C26 | §3 | `models/vllm/memory_qwen3/gdn2_side.py:51` = `gdn2_paged_compute` | ✓ | 逐字命中 | — |
| C27 | §3 | "不跨请求持久化，请求结束状态就释放"，证据 `evict_registry.py`（`finish_requests` 时 `pop_request`/`EVICT_REG.clear()`） | ◐ | `evict_registry.py:266-275` 确实如此；但它 pop 的是**驱逐记录**（chunk span 表），不是 GDN2 状态槽 | 结论✓（README.md:39 支持），证据错位：状态槽回收由上游 vLLM 的 mamba/GDN 状态管理器负责，本仓库无对应代码（论文 C.3 txt:1712 把这两件事分开写作 "removes the request's turnover record **and** the state manager releases its recurrent slot"） |
| C28 | §4 图 | "36 层全装，mem_layers=None，`modeling_memory_qwen3.py:159-168`" | ◐ | `:165-168` 确实按 `memory_layer_indices` 替换 self_attn；`configuration:75-77` 给出 None→全层 | 只对训练/HF 路径成立：`grep -rn 'mem_layers\|memory_layer_indices' models/vllm/` **零命中**，服务侧 `vllm/modeling_memory_qwen3.py:92-94` 每层无条件挂 GDN2，根本不读 `mem_layers` |
| C29 | §4 图 | 主路 = 原生 Qwen3Attention，训练时权重冻结 | ✓ | `stage1.yaml:26-29` / `stage2.yaml:34-37`（`rnn: full / attn: frozen / ffn: frozen`）；论文 txt:286 | — |
| C30 | §4 图 | `memory_gdn2.py:104-149` | ◐ | 同 C11：g/b/w 在 `:116-118`，`chunk_gdn2` 在 `:146-150`，`fused_recurrent_gdn2` 在 `:152-156` 被截断 | — |
| C31 | §4 图 | `modeling_memory_qwen3.py:92` / `memory_gdn2.py:35` | ✓ | `:92` = `self.mem = MemoryGatedDeltaNet2(`；`memory_gdn2.py:35` = `class MemoryGatedDeltaNet2(GatedDeltaNet2):` | — |
| C32 | §4 | 边界说明：外层只发消息收回复；记忆系统只存在于服务进程内一次 forward 的每层副路 | ✓ | `eval/pipeline.py:60,244` + `eval/prompt.py:73-77` + `vllm/modeling_memory_qwen3.py:119-125` | — |
| C33 | §5 | Design Y 实现完整但未出现在任何 stage1/stage2/RL 训练配置里 | ✓ | 三份 yaml 均为 `memory_design: X`（含 `base.yaml:6`）；`grep -rn 'memory_design' train/rl/ scripts/rl/` 零命中（RL 从导出的 checkpoint 读 config） | 否定式断言成立 |
| C34 | §5 | 两套 Config 默认值矛盾：训练侧 `:20` 默认 `Y`，vLLM 侧 `:45` 默认 `X`，`from_qwen3` `:460` 默认 `Y` | ✓ | 三处逐行核对全部精确命中 | 少见地三个行号全对 |
| C35 | §5 | `MEM_EVICT_MODE` 默认 `"message"`；`scripts/serve_livemem.sh` 走这条路径，固定 `chunk_size=1024`、`token_limit=WINDOW_SIZE` | ✓ | `evict_registry.py:67,70,193`、`chunking.py:17-36`；`serve_livemem.sh:53-55`（脚本从不设置 `MEM_EVICT_MODE`） | — |
| C36 | §5 | "stride 模式按 `RULE_TABLE` 自适应选参数……两者在数值上于 8k/32k 这两个评测档位『恰好』重合" | ✗ | `train/sft/eviction_policy.py:57-64` 的 `RULE_TABLE` 五行最大 window = **8192**，无 32768 档；chunk 为 **512**（≠1024）。另 `evict_registry.py:151-152`：stride 模式下 `MEM_EVICT_CHUNK_SIZE`/`MEM_EVICT_TOKEN_LIMIT` 会**覆盖**规则表，所以"自适应选参数"这个前提在设了环境变量时也不成立 | 两条子断言都不实。而且论文 C.2 txt:1683-1685 已经回答了这个"开放问题"：benchmark inference 就是**覆盖**为 chunk 1,024 / budget 8K 或 32K。附带确认：RL 侧 `run_grpo_dev.sh:124` 只设 `MEM_EVICT_MODE=stride`、不设 chunk/limit，所以 RL 确实走 `RULE_TABLE`，两条路径参数**不同**而非重合 |
| C37 | §5 | GDN2 kernel 内部数值实现没有细读（自认未验证） | ✓ | 自认属实；本次同样未做 kernel 级对拍 | — |
| C38 | §5 | LoRA 路径无对应 yaml；`export_checkpoint.py` 支持自动识别并折叠 LoRA | ✓ | `grep -rn lora train/sft/config/*.yaml train/rl/*.yaml` 零命中；`tools/export_checkpoint.py:35-36,49-56` | — |
| C39 | §5 | 仓库只有一次已 squash 的 "Initialize repository" 提交 | ✓ | `git log` 单条 | — |
| C40 | §6 | 代码有 Design Y 而论文全文只字未提 | ✓ | 见 P39 | — |
| C41 | §6 | 论文通讯作者信息正下方写着 "Code Release: https://github.com/cafeii/LiveMem" | ✓ | txt:58（紧接 txt:56 的通讯作者邮箱脚注） | — |
| C42 | §6 | `declare-lab/delta-Mem` 出现在附录 Related Work 脚注 3，指的是 δ-Mem 那篇论文 | ✓ | txt:1351，紧跟 txt:1342-1345 的 δ-Mem 段落 | — |
| C43 | §6 | `eval/delta_server.py` 是该 baseline 的适配服务端 | ✓ | 文件存在；`eval/pipeline.py:60` 把 `delta` 列入 `PREFIX_MODELS` | — |
| C44 | §6 | 附录 D.3 "For δ-Mem, we adopt its TSW setting... we choose to strictly follow its code behavior" | ✓ | txt:1801-1804 | — |
| C45 | §6 | git 作者邮箱与论文通讯作者同为 SUSTech 域名 | ✓ | `12011125@mail.sustech.edu.cn`（git）vs `liuzc2024@mail.sustech.edu.cn`（txt:56） | — |
| C46 | §6 | README 的架构描述 "parallel GDN2 branch to every attention layer" 与 `mem_layers=None` 一致 | ◐ | `README.md:21` 原文为 "LiveMem adds a parallel Gated DeltaNet-2 (GDN2) recurrent memory branch to every attention layer of a pretrained Qwen3 model" | 结论✓；但引号内是压缩转述而非原文逐字，且结论只对训练路径成立（见 C28） |
| C47 | §6 | "cafeii 这个 GitHub 账号具体对应哪位署名作者"未验证 | ? | 仓库内无任何绑定文档；本环境无法核 GitHub 账号身份 | 文档自认未验证，本次同样无法核实 |

## 3. 步骤清单 — 论文侧

系统性质：**in-forward-pass 内在记忆**。论文没有"写入侧/检索侧"两条独立流水线——读与写是同一个 GDN2 delta-rule 步骤的两半，每 token 同时发生。因此下表按"离线参数构建 ‖ 在线前向"划分。

### 3.1 离线（参数侧，一次性）

| # | name（论文原称） | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| 1 | side-branch attachment + copy initialization（§3.1 末段 / C.1） | 离线一次（构造模型时） | 预训练 Qwen3-4B 权重 → 带 GDN2 副路的模型；q/k/v 从主干拷贝，衰减/擦除/写入/输出门与短卷积独立初始化，输出投影零初始化 | no | — | `P-SIDEINIT` **[NEW]** |
| 2 | Answer-based Supervised Learning（§3.3, Eq11；C.4） | 离线一次（两阶段：100 步 + 500 步） | 长文档/多跳 QA 混合语料 + 动态 turnover mask → LiveMem-SFT | no（被训练的就是 backbone 自身，无外部 LLM） | — | `P-TRAIN` + `P-FROZENFWD`（主干冻结） + `P-KVWINDOW`（FlexAttention 模拟 turnover） |
| 3 | Exploration with Memory / RL（§3.3, Eq12-14；C.4） | 离线一次 | prompt+memory → G=8 rollout → GRPO/DAPO 更新 | 1 次 judge LLM（EM 失败时回退，D.1：Qwen3.6-35B-A3B judge） | — | `P-TRAIN` |

### 3.2 在线（一次 request 内）

| # | name（论文原称） | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| 4 | chunking + sink 划定（§3.2；C.2） | 每 request（状态只在 chunk 边界变） | token 序列 → chunk spans + eviction schedule；system prompt 恒为 sink | no | — | `P-KVWINDOW` |
| 5 | main path `a_t^ℓ = Attn^ℓ(h_≤t^ℓ; C_t)`（Eq4；Eq10 约束可见性） | 每 token、每层 | `h_t^ℓ` + 可见 KV 窗口 → `a_t^ℓ` | no（backbone 自身） | 分页 KV cache | `P-FROZENFWD` + `P-KVWINDOW` |
| 6 | GDN2 forget → erase and prepare → write（Eq7-9 / Eq15） | 每 token、每层（与 5 并行） | `h_t^ℓ`, `S_{t-1}^ℓ` → `S_t^ℓ` | no | 递归状态 + 短卷积状态（C.1） | `P-SIDEPATH` |
| 7 | read `r_t = S_t^⊤ q_t` → gated RMSNorm → output projection（Eq9；C.1 txt:1622-1623） | 每 token、每层 | `q_t`, `S_t` → `r_t^ℓ` | no | — | `P-SIDEPATH` |
| 8 | `o_t^ℓ = a_t^ℓ + r_t^ℓ`（Eq6） | 每 token、每层 | `a_t^ℓ`, `r_t^ℓ` → `o_t^ℓ` | no | — | `P-INJECT` |
| 9 | context turnover：释放已驱逐 KV 页（§3.2；C.3） | 每 chunk 边界 | 中间 KV 页 → 归还 allocator；memory slot 不受影响 | no | 分页 KV cache | `P-KVWINDOW` |
| 10 | 生成 `y_t ~ p_{θ,φ}(y_t|C_t,M_t)`（Eq3） | 每 token | 末层 hidden → token | backbone 自身 | — | `P-GENERATE`（记忆系统边界之外） |
| 11 | lifecycle 收尾：removes turnover record + releases recurrent slot（C.3） | 每 request 末 | 状态槽 → 归还 | no | 递归状态槽 | `P-EVICT`（此处指整块销毁，非选择性剪枝） |

**论文侧压根不存在的阶段**（不要往骨架里硬塞）：`P-INTAKE`（作为记忆系统步骤）、`P-REWRITE`、`P-EXTRACT`、`P-META`、`P-EMBED`、`P-DEDUP`、`P-CONFLICT`、`P-LINK`、`P-AGGREGATE`、`P-PERSIST`（跨请求落盘）、以及**整个检索侧**（`P-QUERYPARSE`/`P-DENSE`/`P-SPARSE`/`P-SYMFILTER`/`P-GRAPHEXPAND`/`P-DIFFUSE`/`P-FUSE`/`P-RERANK`/`P-SELECT`/`P-ASSEMBLE`/`P-TOOLLOOP`）。参数侧的 `P-DATASTORE`/`P-ANNINDEX`/`P-KNNDIST` 也不存在——没有 (key,value) datastore、没有 ANN 索引、不生成 kNN 目标分布。特别注意 **`P-INTERP` 不适用**：LiveMem 不做输出分布插值（那是 kNN-LM 的做法），它在**每层隐状态**上做残差相加，因此是 `P-INJECT`。

## 4. 步骤清单 — 代码侧

### 4.1 离线（构建与训练）

| # | name（代码原称） | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| 1 | `tools/data_process/run_preprocess.py` → `tokenize_train.py` | 离线一次 | 原始数据集 → 统一 memory/QA schema → `dataset/train/<ds>/*.arrow` | no | 本地 arrow 文件 | `P-INTAKE`（**边界外**：数据流水线，不是运行时记忆写入） |
| 2 | `MemoryQwen3ForCausalLM.from_qwen3` + `copy_init_side_branch`（`modeling_memory_qwen3.py:457-500, 529-590`） | 离线一次 | Qwen3-4B → 带 GDN2 副路模型 | no | — | `P-SIDEINIT` **[NEW]** |
| 3 | SFT stage1（`train/sft/`，`livemem_sft_stage1.yaml`） | 离线一次（100 步，warmup 50） | 长文本语料 + `MixedArrowDataset` 逐样本 eviction schedule → `chunk_id/evict_step` → `make_memory_and_mask`（`modeling:55-56` 谓词 `evict_step[kv] > chunk_id[q]`）+ FlexAttention | no | `trainable.pt` | `P-KVWINDOW` + `P-FROZENFWD` + `P-TRAIN` |
| 4 | SFT stage2（`livemem_sft_stage2.yaml`） | 离线一次（500 步，constant 50 → cosine） | 多跳/长 QA + 分类混合 → LiveMem-SFT | no | `trainable.pt` | `P-TRAIN` |
| 5 | `tools/export_checkpoint.py` | 手动调用 | `trainable.pt`（+ 可选 LoRA 折叠）→ 可服务 checkpoint | no | 磁盘 checkpoint | `P-PERSIST`（落的是**参数**，不是记忆内容） |
| 6 | RL（`train/rl/` + verl；`scripts/rl/run_grpo_dev.sh`） | 离线一次 | `mem_stride_policy=true` 自导出 stride mask；rollout server 走 `MEM_EVICT_MODE=stride`；`reward.py:82-100` 复用 eval 打分 | 1 次 judge LLM（EM 失败回退，`reward.py:59-76`） | — | `P-TRAIN` |

### 4.2 在线（每 query / 每 request）

| # | name（代码原称） | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| 7 | `eval/prompt.py::_messages` | 每 query | memory_docs + user_text → `[system, user(mem+"\n\n"+query)]` | no | — | `P-ASSEMBLE`（**边界外**：评测脚本，LiveMem 不在 `PREFIX_MODELS` 里，无 memory/query 切分协议） |
| 8 | `Scheduler.add_request` → `register_request` → `compute_chunk_spans` + `compute_evict_at`（`evict_registry.py:183-199`；`chunking.py:17-36`） | 每 request | prompt_token_ids → chunk spans（按 `<\|im_start\|>` 消息边界，超 1024 再切）+ evict 表 | no | 进程内 `EVICT_REG` | `P-KVWINDOW` |
| 9 | main path：`self.self_attn(positions, hidden_states)`（`vllm/modeling_memory_qwen3.py:119`） | 每 forward pass、每层 | `h` + 可见分页 KV → `attn_out` | no | 分页 KV | `P-FROZENFWD` + `P-KVWINDOW` |
| 10 | side path：`gdn2_paged_compute`（`gdn2_side.py:51-126`）——gather `ssm_state[state_idx]` → 短卷积 → g/b/w 门 → `chunk_gdn2`(prefill)/`fused_recurrent_gdn2`(decode) → scatter 回槽 | 每 forward pass、每层（与 9 并行） | `h`, 槽内状态 → `o`, 新状态 | no | 分页 `ssm_state` + `conv_state` | `P-SIDEPATH` |
| 11 | `o_norm`(FusedRMSNormGated) + `o_proj` → `side_out`；`hidden = attn_out + side_out`（`vllm/modeling_memory_qwen3.py:123-125`；训练侧同构 `modeling_memory_qwen3.py:137`） | 每 forward pass、每层 | `attn_out`, `side_out` → 层输出 | no | — | `P-INJECT` |
| 12 | `ChunkEvictManager.remove_skipped_blocks`（`evict_manager.py:96-111`）+ FlashInfer builder 丢 kernel page | 每调度步 / 每 chunk 边界 | 完全落在已驱逐 span 内的整块 KV → `free_blocks` | no | 分页 KV | `P-KVWINDOW` |
| 13 | decode 生成 completion | 每 token | → 文本 | backbone 自身 | — | `P-GENERATE`（**边界外**） |
| 14 | `Scheduler.finish_requests` → `pop_request` / `EVICT_REG.clear()`（`evict_registry.py:266-275`）+ 上游 vLLM 回收 mamba state slot | 每 request 末 | 驱逐记录与状态槽 → 释放 | no | `EVICT_REG` / 状态槽 | `P-EVICT` |
| 15 | `eval/extract.py` → EM → `eval/judge.py` → `eval/metrics.py` | 每 query | 生成文本 → 分数 | 1 次 judge LLM | 结果 jsonl | —（**边界外**：评测，不对应任何记忆 primitive） |

### 4.3 系统边界

- **记忆系统本体**：`MemoryAttention.mem`（= `MemoryGatedDeltaNet2`）及其分页状态槽（`ssm_state` + `conv_state`），加上让它"必须"承担记忆的 context-turnover 调度（训练侧 `make_memory_and_mask`、服务侧 `ChunkEvictManager`/`evict_registry`）。唯一被训练的参数也只有这条副路。
- **backbone 侧**：主路 `Qwen3Attention`、`Qwen3MLP`、`lm_head`、KV cache 本身——训练时全部冻结。
- **agent / 评测脚本侧**：prompt 拼装（`eval/prompt.py`）、HTTP 调度与并发（`eval/pipeline.py`）、答案抽取与 LLM judge（`eval/extract.py`/`judge.py`）。调用方对记忆一无所知，也无任何记忆 API。
- **不存在的边界**：没有跨 request、跨 session 的任何存储。LiveMem 的"记忆"生命周期 = 一次 request。

## 5. 论文↔代码分歧

| # | 分类 | 分歧 | 论文证据 | 代码证据 |
|---|---|---|---|---|
| X1 | **[两边都有但行为不同]** | **评测服务的分块方式**：论文说 serving 用确定性 fixed-stride chunk（纯位置函数、页对齐）；实际评测服务走的是按 `<\|im_start\|>` **聊天消息边界**切块、超长再按 1024 分割的 message 模式，chunk 边界不保证 32-token 页对齐（代码改用"只释放完全落在驱逐 span 内的整块"来兜底）。只有 RL rollout 才是 fixed-stride | txt:1641-1642 "SFT examples use dataset-defined semantic or fixed-token chunks; **serving** and RL recomputation use deterministic fixed-stride chunks."；txt:1683-1685 "Benchmark inference uses the same oldest-first transition and **page-alignment rules**, while overriding the chunk size to 1,024 and the live-token budget to 8K or 32K" | `scripts/serve_livemem.sh`（全文不设 `MEM_EVICT_MODE`）→ `evict_registry.py:67` 默认 `"message"` → `evict_registry.py:193` `compute_chunk_spans` → `chunking.py:17-36`（按 `<\|im_start\|>` 切）；对照 `scripts/rl/run_grpo_dev.sh:124` `MEM_EVICT_MODE=stride`；`evict_manager.py:73-75,87` 的保守整块判定 |
| X2 | **[code-only 代码有论文没写]** | **Design Y（`write_mask=is_evicted` 门控读写）**：完整实现 + 专门的合成数据集，论文全文零提及。发布 checkpoint 用 X，故不影响复现结论 | 全文 grep `design x/y`、`write mask`、`gated read`、`read-only` 零命中 | `models/memory_gdn2.py:12-14,128-133`；`models/modeling_memory_qwen3.py:219-222`；`train/sft/data.py:321-326,354` |
| X3 | **[两边都有但参数不同]** | **`memory_design` 默认值**：论文与所有发布配置一律 X；训练侧 Python Config 和 `from_qwen3` 默认却是 **Y**（vLLM 侧默认 X）。不走发布 checkpoint 直接构模会静默拿到 Y | txt:224-226、txt:267（只描述连续扫描） | `models/configuration_memory_qwen3.py:20`（`"Y"`）、`models/modeling_memory_qwen3.py:460`（`"Y"`）vs `models/vllm/memory_qwen3/configuration_memory_qwen3.py:45`（`"X"`）、`base.yaml:6`（`X`） |
| X4 | **[paper-only 论文写了本仓库没实现]** | **状态槽回收**：论文把请求收尾拆成"scheduler 删 turnover record"+"state manager 释放 recurrent slot"两件事；本仓库只实现了前者，后者依赖上游 vLLM 的 mamba 状态管理，仓库内无对应代码 | txt:1712-1714 | `models/vllm/memory_qwen3/evict_registry.py:266-275`（只 `pop_request`/`EVICT_REG.clear()`）；`grep -rn 'release.*slot\|free.*ssm_state' models/vllm/` 无命中 |
| X5 | **[code-only 代码有论文没写]** | **服务侧忽略 `mem_layers`**：训练侧支持只在部分层挂副路；vLLM 插件根本不读这个字段，每层无条件挂 | txt:194 "each attention layer"（与"全层"一致，但没讨论可选性） | `grep -rn 'mem_layers\|memory_layer_indices' models/vllm/` 零命中；`models/vllm/memory_qwen3/modeling_memory_qwen3.py:92-94` |
| X6 | **[code-only 代码有论文没写]** | **RL 打包工程细节**：`mem_rl_pad_multiple` 定形右填充、`derive_stride_eviction` 从 `input_ids` 反推 mask、`_record_o_stats` 单层诊断统计 | 论文只在 C.2 说"trainer derives the same per-token chunk and eviction fields"，未提填充与诊断 | `models/modeling_memory_qwen3.py:224-291`、`models/stride_glue.py:45`、`models/modeling_memory_qwen3.py:110-113,138-151` |
| X7 | **[一致性正面交叉验证]** | Table 5 五行 fixed-stride 参数 ↔ `RULE_TABLE` **逐行完全一致**；"multiples of the 32-token serving page size" ↔ `PAGE_SIZE = 32`；C.4 训练超参（100/50 步、500/50 步、lr 5e-5、wd 0.01、clip 1.0、16 packs/step）↔ 两份 yaml **完全一致**；`32×128×128 / FP32` ↔ `gdn2_side.py:200,208`；Eq(14) 奖励 ↔ `reward.py:92-98` | txt:1660-1675、txt:1668、txt:1716-1731、txt:1624-1629、txt:340 | `train/sft/eviction_policy.py:45,57-64`；`livemem_sft_stage1.yaml:30-45` / `stage2.yaml:38-53`；`gdn2_side.py:200,208`；`train/rl/reward.py:92-98` |

## 6. 新造的 primitive 标签

| 标签 | 含义 | 为什么必须新造 |
|---|---|---|
| `P-SIDEINIT` | **副路参数构造与拷贝初始化**：把递归副路挂到冻结主干的每一层，q/k/v 投影从主干对应权重拷贝，门控与短卷积参数独立初始化，输出投影零初始化以保证"接上瞬间行为等价原模型" | 种子词表参数侧只有 `P-TRAIN`（梯度训练）、`P-FROZENFWD`（冻结前向）、`P-SIDEPATH`（运行时状态更新），都不覆盖"训练开始之前的一次性结构嫁接与权重初始化"。这一步在 LiveMem 里是被论文单独成段描述（§3.1 末段 + 附录 C.1 专节）、且在代码里是独立函数（`copy_init_side_branch`）的关键步骤——零初始化输出投影是"侧支路可以安全地后接到预训练模型"这一整套方法能成立的前提。对任何"给冻结主干加副路"的系统（δ-Mem、Titans、Context2LoRA 的适配层）都会复用，值得单列 |

其余步骤全部复用已有标签，未新造第二个。

## 7. 复核统计

| 判定 | 条数 | 分布 |
|---|---|---|
| ✓ 属实 | **76** | paper-architecture 42 / code-architecture 34 |
| ✗ 不实 | **3** | P23（论文"没有门控"被 C.1 证伪）、P35（Table 1 空格列名 + "没有解释"两处皆错）、C36（message/stride "恰好重合"） |
| ◐ 部分属实/需加限定 | **18** | paper 7（P13 P17 P33 P37 P41 P44 P51）/ code 11（C7 C8 C11 C13 C21 C22 C24 C27 C28 C30 C46） |
| ? 无法核实 | **1** | C47（cafeii GitHub 账号 ↔ 署名作者身份：仓库内无绑定文档，本环境无法核 GitHub） |
| **合计** | **98** | |

代码引用行号命中率：44 处 `file.py:NNN` 中 **精确命中 37 处**、漂移 6 处（C8 C11 C13 C22 C24 C30）、文件不存在 0 处。论文锚点（§/Eq/Table/Figure/附录编号）**全部对应正确**，无一处编号张冠李戴——唯一的编号类错误是 P35 的表内**列**认错，不是表号认错。

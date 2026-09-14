# intent 臂 Handoff：为什么这么设计、借了谁、分从哪来、怎么跑

> 给拿到这个仓库的人（首先是樊嘉铭）。读完这份就能在自己电脑上把 intent 臂跑起来、
> 复现我们的数字、并知道哪些数字**不能**并列。代码：`servers/intent/`；设计与实验真源：
> `BASELINE-DESIGN.md`、`EXPERIMENT-LADDER.md`（同目录）。

---

## 1. 为什么这么设计（三句话）

1. **意图系统不是替代记忆库，是叠在记忆库之上的一层**：记忆系统回答"agent 能不能记住"，
   意图系统回答"agent 能不能读懂人当时想干什么、在当下场景里该投射哪一段"。
2. **压缩在使用时，不在存储时**：原文 JSONL 全留、永不销毁；摘要/事实/向量只做**索引**，
   证据出口永远是原文或原文级事实（"不压缩信息，建索引网"）。
3. **session 是意图的天然单元**：一次对话的意图是一个整体；检索返回 session 级 envelope，
   按**事实时间升序**拼成时间线（score 只决定入选、时间决定顺序），让答题模型沿时间回溯。

对应 14 个记忆系统的横向骨架（`servers/METHODOLOGY-SKELETON.md`）：
A 形成期 = 我们的构建期（A1 session 边界 → A2 蒸馏+自检 → A3 版本归档/效用记账 → A4 双索引+意图链 → A5 落盘），
B 动员期 = 查询期（B1 tokenize+embed → B2 五路召回 RRF → B3 链扩展 → B4 MMR → B6 时间线交付）。
查询期**零文本 LLM**（只有一次 embedding 调用），与 mem0/rag/graphiti 同属 A 档被动检索面。

## 2. 学习了哪些记忆系统（借法分三种）

| 机制 | 借自 | 借法 | 结果 |
|---|---|---|---|
| 自包含事实改写（三人称/代词消解/绝对日期） | mandol L0（分层消融 +18.9）、mem0 日期规则、atommem 五规则 | 正面 | 常开（系统本体） |
| 事实条目作为高密度证据 | mem0（20 条查询定向事实） | 正面 | S1 事实位 2→4，唯一过闸步 +5.2 |
| 关键词/向量双打分 + RRF | graphiti hybrid 思想（其自身实现在 mem0 代码里是死的）；graphiti RRF | 正面（借思想不借实现） | 常开 |
| 摘要自检（LLM 复检修补） | graphiti 论文写了 reflexion、**全领域代码零实现** | 论文空白 | 常开（`selfcheck`） |
| 非破坏版本归档（status/history/evolve_to） | memos `item.py` 结构；mandol 重灌销毁事故 | 正面 + 反面 | 常开 |
| 效用记账（retrieval_count/last_used，只记不馈） | memharness MemoryRecord | 正面 | 常开（反馈期留消融） |
| 意图链（存 sessionId 指针非位置） | amem 理念 + 三个验尸坑（位置索引/切片截死/元数据从未生成） | 反面绕行 | `chains`，LoCoMo 规模惰性 |
| MMR 定选 | memos B5 | 正面 | `mmr` |
| 混合粒度交付（session + 裸事实） | mandol 三塔证据流本就是混合粒度 | 正面 | S5 `MIX=8,12`，+1.2 边缘 |
| 数字 token | 审查发现分词弱于 mock 靶；mandol/mem0 日期显式化 | 对齐 | S3，+0.5 不过闸 |
| PRF 二跳扩展 | MRAgent ActiveSetInit 的被动退化版 | 正面借用 | S2，在有稠密门控的架构里**冗余** |
| rollup/关系事实 + 日期前缀 | atommem profile 层、graphiti 边事实（降维为平面文本）、mandol `[Date:]` | 正面借用 | S6，**复现了 mandol 的失败模式**（L1/L2 抽象单元从不被检回）：构建加货、交付层运不出去 |
| **别抄** | mem0 死代码冲突消解 / graphiti 读取端不用的边失效 / amem 坏 evolution / mandol gold-category router / graphmemix gold 拟合校准 | 验尸清单 | — |

## 3. 表现的增加主要来自哪里

**归因臂（S4）**：同一份蒸馏产物，只用事实关键词单路检索、裸事实交付 = **49.5**（≈ rag 51.7 档）；
整条意图管线（摘要+事实+向量 × 五路 RRF × session 时间线交付）= **60.1**。
**+10.6 全类别为正**——它是蒸馏产物 × 查询期管线 × 交付形态的**整链协作增益**，不可单归任一层。

**阶梯（3-conv：conv-26/30/49，n=3，top_k=20，judge_acc %）**：

| 步 | 变量 | multi-hop | temporal | open-dom | single-hop | ALL | 闸门（>1.3） |
|---|---|---|---|---|---|---|---|
| v1 | baseline 全机制 | 35.1 | 81.8 | 45.4 | 61.6 | 60.1 | 起点 |
| **S1** | envelope v2：事实位 2→4，选择门控 kw→max(kw, dense≥0.30) | 51.5 | 83.6 | 50.0 | 63.8 | **65.3** | **✓ 主线** |
| S2 | +PRF | 50.2 | 82.2 | 49.4 | 64.4 | 64.9 | ✗ |
| S3 | +数字 token | 55.2 | 84.1 | 48.7 | 63.4 | 65.8 | ✗ |
| S5 | +混合粒度 8+12 | 52.9 | 85.1 | 52.7 | 64.6 | 66.5 | ✗（边缘） |
| S3+S5 | 叠加复核 | 53.2 | 84.0 | 51.3 | 64.6 | 66.1 | ✗（z=1.07） |
| S6 | 蒸馏 v2 重灌 | 52.5 | 82.1 | 44.9 | 61.9 | 63.8 | ✗ |

S1 的机制（`stage-attribution` 报告）：证据含金量 41.9%→50.9%（gold 含于 evidence），
dense 门控把"库里有但不上台面"的事实摆出来；cat1 翻转 +50/−13。S3/S5/S3+S5 三次复核
配对检验均不显著（z≈1.0–1.2），故主线定格 S1。

**同切片对手**（3-conv）：mandol 74.0 / amem_fixed 69.8 / mem0 67.2 / rag 51.7 / graphiti 42.3。
- temporal：**三个配置全部超 mandol**（83.6–85.1 vs 81.1）——时间线组装 + 绝对日期是稳健优势
- multi-hop：51.5 vs mandol 55.0，差在**转化端**不在证据（我们 cat1 证据含金量 52.5% 已高于 mandol 49.4%）
- single-hop：63.8 vs 81.5，是最大缺口——4 事实位给简单题引入干扰项（cat4 转化率 90→83）

> [!warning] 数字不可混列
> 上表全是 **3-conv 切片**。mandol 0.7641 / amem_fixed 0.6944 / mem0 0.6901 那些是 **10-conv 全量表**（`runs/mandol-full-10conv` 等）。
> intent **尚无 10-conv 全量 run**（EXPERIMENT-LADDER S7，未跑）。把 intent 的 3-conv 数与别人的 10-conv 数放同一张表会误导——
> conv 间极差 15pp 是主导方差源（report-2026-09-04 V-8）。要并表，先跑 S7。

## 4. 怎么用（在别人电脑上解压后）

### 4.1 前置

- 仓库通用环境按 `README.md` 快速开始第 1–2 步（`uv venv -p 3.12` + `.env`）；intent 臂**不用主 venv**
- **Bun**（TS 运行时）：`curl -fsSL https://bun.sh/install | bash`；然后 `cd servers/intent && bun install`
- 数据：`data/locomo/locomo10.json` 已随仓库提供（来源 HF `mem0ai/locomo`，见 `DEPLOY.md` 附录 A）

### 4.2 LLM 配置——所有臂共用一组 key（这是公平性约定，不是省事）

`.env` 里这三个变量是**全部记忆系统共享的构建期 LLM**（interface-spec §7），intent 也只读它们：

```text
MEMBENCH_LLM_API_KEY=<你的 key>
MEMBENCH_LLM_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4   # 智谱 coding 通道示例
MEMBENCH_LLM_MODEL=glm-5.3
MEMBENCH_EMBED_MODEL=embedding-3
```

- embedding 走 `MEMBENCH_LLM_BASE_URL` 去掉 `/coding` 的普通通道（coding 通道无 embedding 权限），
  可用 `MEMBENCH_EMBED_BASE_URL` / `MEMBENCH_EMBED_API_KEY` 显式覆盖
- 任何 OpenAI 兼容端点都能用（`/chat/completions` + `/embeddings`）；换模型只改 `.env`，**不要改代码里的默认值**——否则与其他臂口径不一致
- 成本：构建期每 session 2 次 LLM（蒸馏+自检，~3k token）+ 1 次 embedding 批调用；查询期每 query 1 次 embedding、零文本 LLM。3 conv（63 session）约 20 万 token；10 conv 约 90 万
- 答题/判分用另一组 `MEMBENCH_ANSWER_*`（与所有臂相同），见 `DEPLOY.md` §2

### 4.3 跑起来

```bash
# 1. 门禁（8/8 才算过；注意 smoke 会 reset 共享 state，正式跑分期间别碰）
python main.py smoke intent_full

# 2. 3-conv 验证轮（与阶梯同口径，约 45 分钟；答题并发 16 是实测稳定值）
python main.py run --arms intent_full --convs conv-26,conv-30,conv-49 \
  --n 3 --top-k 20 --run-id intent-mine-3conv --concurrency 16

# 3. 与已有 run 同 conv 集合并表（自动在本仓 runs/ 与主仓 runs/ 两处找 answers.jsonl）
.venv/bin/python scripts/slice_anchors.py --runs intent-mine-3conv,mandol-full-10conv,locomo-r2-n3,amem-ab-3conv
```

- 长跑用 `screen`/`nohup caffeinate -i`（终端关闭的 SIGHUP 会杀进程）；断了同 run-id 加 `--resume`
- **复用已入库状态、只换查询期配置**：`scripts/seed_progress.py --from-run <已灌 run> --to-run <新 run> --arms intent_full`，
  然后带 `--resume` 启动——跳过 63 次蒸馏，直接进检索（阶梯 S2–S5 就是这么跑的）
- state 在 `.state/intent/scopes/<conv>/`：`sessions/`（原文）、`session-intent.json`（摘要+事实+版本）、
  `vectors.json`、`chains.json`、`utility.json`；快照 `.state/intent/__snapshots__/`

### 4.4 三个臂与消融开关

| 臂（servers.yaml） | 入口 | 是什么 |
|---|---|---|
| `intent_full` | `server.ts` | **baseline / 主线**（S1 代码默认） |
| `intent_facts` | `server_facts.ts` | 归因臂：同一份状态只用裸事实（mem0 形态），量"意图层值几分" |
| `intent_tier2` | `server_tier2.ts` | agent 形态：检索期对 top-5 session 原文做一次 LLM 精读（active，**不与被动臂混表**） |
| `intent` | `server.ts` | 旧名，等价 `intent_full` |

三臂共享 state：先跑 `intent_full` 入库，其余用 `seed_progress.py` 复用。

阶梯开关（环境变量，默认全关 = S1 主线）：

```bash
MEMBENCH_INTENT_NUMTOK=on        # S3 数字 token
MEMBENCH_INTENT_MIX=8,12         # S5 混合粒度：8 session envelope + 12 裸事实
MEMBENCH_INTENT_PRF=on           # S2 PRF（已证冗余，留作对照）
MEMBENCH_INTENT_DISTILL=v2       # S6 蒸馏 v2（需配独立 MEMBENCH_STATE_DIR 重灌）
MEMBENCH_INTENT_ABLATE=selfcheck,dense,chains,expand,mmr   # 减法消融：逗号列出要关的机制
```

例：复现 S3+S5 = `MEMBENCH_INTENT_NUMTOK=on MEMBENCH_INTENT_MIX=8,12 python main.py run --arms intent_full ...`

### 4.5 复现纪律（我们踩过的）

- 同一 conv 集合才能横比；`n=3` 起步，报 mean±std；闸门 = 增量 > 2×CI 半宽之和（≈1.3pp）
- 分类别 ±3–4pp 的"信号"要过**证据同一性检验**（比对两 run 的 evidence_text 是否逐字节相同）——
  thinking-on 答题的采样噪声足以制造这种幅度（S3 的 cat1 "+3.7" 就是这样被撤回的）
- 出分前 `grep -c DENSE_FALLBACK evidence/intent_full.jsonl` 应为 0（embedding 降级会污染跨 rep 一致性）
- 每步单独 run-id、单独 commit；结果写 ladder-log，不改历史行

## 5. 文件索引

| 文件 | 内容 |
|---|---|
| `server.ts` | 实现（~800 行，头注释是机制总表） |
| `BASELINE-DESIGN.md` | baseline v1 设计：机制表、两条硬约束、schema |
| `EXPERIMENT-LADDER.md` | 阶梯预注册：S0 诊断、S1–S8 假设/判停/ETA |
| `../METHODOLOGY-SKELETON.md` | 14 系统横向骨架（A1–A6/B1–B8）与覆盖矩阵 |
| `../../docs/interface-spec.md` | 六工具契约；§4 有 intent 时间升序豁免声明 |
| `../../scripts/slice_anchors.py` / `seed_progress.py` | 并表 / 复用状态 |

## 6. 当前状态与未做

- 主线 S1 = 65.3（3-conv）；S7 10-conv 全量**未跑**；S8 减法消融包未跑
- 已知可改进：single-hop 干扰项（按题型自适应事实位）、multi-hop 转化端（hop 事实共现排布）、S6 库存 × 更大交付容量（两变量拆步）
- 意图特有能力（意图变化检测、场景化投射、negative transfer）LoCoMo 测不到，需自家 benchmark（`docs/` 与 wafo 侧 `intention-benchmark-design-v1`）

# memory-bench

在**统一 MCP 接口**下横向评测 agent 记忆系统：把 Mem0 / Graphiti / A-MEM / MemOS / Mandol
和意图系统 intent-recall 封装成同一套契约，用同一份数据、同一个答题模型、同一套判分口径跑分，
回答"谁的检索准"以及"意图层带来多少增量"。

对照锚点：`rag_baseline`（裸向量检索，无 LLM）与 `full_context`（整段历史塞进上下文）。
没有这两个，"记忆系统是不是只是向量检索"这个质疑就没有落点。

**当前状态**：Phase 1（8 臂封装 + 契约门禁）完成；Phase 2 跑分：locomo-r2-n3（2026-08-30，mem0 / graphiti /
rag_baseline × 10 conv × n=3）、mandol-full-10conv（09-04）、amem-ab-3conv（含 amem_fixed 全量）；
**2026-09-10–13 新入矩阵四臂** atommem / memharness / graphmemix / plugmem（各有 3-conv 首轮 run，
见下方快速开始；**仅 atommem 结果已审查，其余三臂待审**）。路线与阶段划分见 [PLAN.md](PLAN.md)。

---

## 快速开始（mem0 / graphiti 的 MCP 用法）

按顺序走完这八步，就能从零跑通一次评测。每步细节看括号里指向的文档。

1. **装环境**：`uv venv -p 3.12` 起主 venv 并装依赖；跑测试另需 `uv pip install --group dev`。
   `python main.py ...` 会自动 re-exec 进 `.venv`，不用手动激活。三个 venv 为什么分开见
   [DEPLOY.md](DEPLOY.md) §1。
2. **配密钥**：`cp .env.example .env` 后填两组 key——`MEMBENCH_LLM_*`（ingest/内政 LLM）与
   `MEMBENCH_ANSWER_*`（答题+判分）。字段语义见 [DEPLOY.md](DEPLOY.md) §2。
3. **起外部依赖**（只有 graphiti 需要；mem0 用 chroma，无外部依赖）：
   `docker start membench-neo4j`。首次创建见 [DEPLOY.md](DEPLOY.md) §4。
4. **看可用臂**：`python main.py arms`——列出全部臂及各自 env 是否就绪。
5. **过契约门禁**：`python main.py smoke mem0`、`python main.py smoke graphiti`，
   **断言 8/8 全过**才能进实验矩阵（覆盖 add/retrieve/snapshot/reset/restore 复现/双 scope 隔离，
   断言清单见 [docs/interface-spec.md](docs/interface-spec.md) §10）。2026-09-04 复验两臂均 8/8。
6. **正式跑分**：

   ```bash
   python main.py run --arms mem0,graphiti,rag_baseline \
     --run-id my-run --n 3 --top-k 20 --concurrency 10
   ```

   两阶段协议（Phase A 检索串行 / Phase B 答题并发）与产物结构见
   [docs/bench-design.md](docs/bench-design.md)。先小规模验证端到端可用
   `--convs conv-30` 单 conv。
   > [!warning] 快照已存在时必须预置 progress
   > 若 `.state/__snapshots__/<arm>/locomo_full` 已在：**先预置
   > `runs/<run-id>/ingest_progress/progress.json`**，否则 runner 会在 restore 后把 10 个 conv
   > 全量重灌并 `snapshot` 覆盖快照（2026-08-30 实测踩过）。机理与预置方法见
   > [DEPLOY.md](DEPLOY.md) §6。
7. **断了就续**：同一 run-id 加 `--resume`。幂等键 `arm|conv|qa_id|rep`，两阶段各自跳过
   已完成行，已答的题绝不重算。注意 `--resume` 不建目录——手工建过 run 目录的先确认
   `evidence/` 存在。补跑单臂也是同一条命令（`--arms intent` 只跑它）。
8. **看结果**：`runs/<run-id>/answers.jsonl`（逐题答案+判分）、`evidence/<arm>.jsonl`
   （检索 envelope 原文，可审计）。主表口径与方差读法见 [docs/bench-design.md](docs/bench-design.md) §5–§6。

MCP 六工具的逐字段语义（含 canonical envelope 与各臂原生粒度）见
[docs/interface-spec.md](docs/interface-spec.md)。`main.py` 只是分发器，等价的直接调用是
`.venv/bin/python scripts/smoke_test.py <system>` 和 `.venv/bin/python -m bench.runner ...`。

---

## Mandol 快速开始（三层复现版）

与通用八步并行的专用路径：mandol 的三层复现由三个环境开关控制，全量跑走专用脚本。

1. **一次性准备**（顺序不可换）：
   - 独立 venv：`.venv-mandol`（mandol 锁 `numpy<2`，与主 venv 的 chromadb 冲突，见 [DEPLOY.md](DEPLOY.md) §1）；
   - **先跑 `bash scripts/fix_mandol_openmp.sh`**：torch 与 faiss 各自捆绑一份 libomp，
     同进程加载两份会在检索时 SIGSEGV（crash report 已定位）。server 启动时还有
     `_assert_single_libomp()` 硬检查，不修直接拒启；
   - 两个本地模型：`naver/splade-v3`（**gated repo，需 HF token + 同意条款**）与
     `BAAI/bge-reranker-v2-m3`。步骤见 [docs/mandol-repro-plan.md](docs/mandol-repro-plan.md) §9。
2. **三个开关**（默认值保证“Phase 1 态”基线可重复）：

   | 环境变量 | 控制层 | 默认 | 说明 |
   |---|---|---|---|
   | `MEMBENCH_MANDOL_SPARSE` | 存储 | `1` | ingest 时生成 SPLADE 稀疏向量；stats() 逐 unit 监测静默降级 |
   | `MEMBENCH_MANDOL_TOWERS` | 构建 | `0` | snapshot 落盘前触发三塔离线构建（LLM 重，见 §时间预算） |
   | `MEMBENCH_MANDOL_TRITOWER` | 检索 | `0` | retrieve 走三塔并行召回 + RRF + bge 重排 + 级联剪枝 |
   | `MEMBENCH_MANDOL_CASCADE_IDS` | 检索 | `0` | 级联剪枝读 source_unit_uids（定稿跑 =1，详见 repro-plan §5） |

3. **过门禁**：`python main.py smoke mandol`（8/8）。
4. **全量定稿跑**：`bash scripts/run_mandol_full.sh [run-id]`——三段串行、全程幂等、断点重跑
   本脚本即续：ingest 剩余 conv（约 40 min）→ 三塔构建（约 2 h，独立阶段
   `timeout=36000`）→ 考试 1,986 题 × n=3（约 18 h）。需 `.env` 已配好 embedding key。
5. **结果口径**：定稿 run `mandol-full-10conv` 总体判对率 0.6020，cat1-4 口径 0.7641
   （全类别第一）。**与论文 92.21% 不可并列**：构建侧 glm-5.3 vs 官方 qwen-thinking，
   且本复现不含 gold category 注入。剩余保真度偏离清单（KG 塔实为实体集合等）见
   [docs/mandol-repro-plan.md](docs/mandol-repro-plan.md) §5，对论文逐条 diff 见同文档 §3–§4。

> [!warning] 三个会在半夜静默炸掉的坑（均已在本仓踩过）
> - `runner --ingest-only` 只跳过 Phase B，Phase A 的 5,958 次检索照跑（`runner.py:473`）；
> - harness 的 `snapshot` 用 `timeout=600`，而 `TOWERS_ON=1` 时 snapshot 会先建塔
>   （7 conv 约 2 h）→ 必然超时，所以全量跑必须走三段编排，不许直连 `main.py run`；
> - `caffeinate -i` 不防终端关闭（SIGHUP，实际断在 41%）→ 用 `screen` 起长跑。

---

## 新四臂快速开始（atommem / memharness / graphmemix / plugmem，2026-09-10–13 入矩阵）

四臂都跑在**主 venv**，只读共享的 `MEMBENCH_LLM_*` 三个变量，embedding 统一 embedding-3（均偏离各自论文/上游的
原生编码器，代价是上游硬编码阈值的尺度漂移，由各臂 `stats().threshold_probes` 逐次观测）。

| 臂 | 上游代码 | 检索面 | 口径与门禁记录 | 首轮 run | 审查 |
|---|---|---|---|---|---|
| `atommem` | 需 clone `MINE-USTC/AtomMem` 到 `~/Documents/repo/AtomMem`（`MEMBENCH_ATOMMEM_REPO` 可覆盖）；脚本式仓库，`sys.path` 引入不 pip 装 | retrieve 有 1 次 B1 意图解析 LLM（只读 query 不读记忆，不算 active）；符号过滤人物不交则拒（`SEED_LIMITED`） | [servers/atommem/REPRO-NOTES.md](servers/atommem/REPRO-NOTES.md) | `atommem-p1-3conv` | ✅ 已审 |
| `memharness` | 不依赖上游运行（上游是 verl/Ray 训练栈），存取引擎按论文重写 | **active**：retrieve 读记忆内容并调 LLM 批判重构；不保证返回满 top_k（拒绝率实测 ~70%） | [servers/memharness/REPRO-NOTES.md](servers/memharness/REPRO-NOTES.md) | `memharness-p1-3conv` | 待审 |
| `memharness_noadapt` | 同上，`MEMBENCH_MEMHARNESS_ADAPTOR=off` | 消融对照：关掉批判重构，零 LLM 纯检索面；**必须复用主臂快照**不单独灌 | 同上 | — | 待审 |
| `graphmemix` | 需 clone 上游（`MEMBENCH_GRAPHMEMIX_REPO` 可覆盖） | **active**：节点 verifier + 锰点条件关系验证两处 LLM 并行；变基数返回（`VARIABLE_CARDINALITY`），排序为森林 BFS 非 score 降序；查询级缓存保幂等（`MEMBENCH_GRAPHMEMIX_CACHE=off` 测方差） | [servers/graphmemix/REPRO-NOTES.md](servers/graphmemix/REPRO-NOTES.md) | `graphmemix-p1-3conv-v3`（v1/v2 已 VOID） | 待审 |
| `plugmem` | 需 clone 到 `~/Documents/repo/PlugMem`（`MEMBENCH_PLUGMEM_REPO` 可覆盖） | 默认 `T_max=2` 多跳属 **active**；纯被动对照设 `MEMBENCH_PLUGMEM_MAX_HOPS=1`；记忆类型由 LLM 三选一，不足时 `MODE_LIMITED` | [servers/plugmem/arm-reproduction.md](servers/plugmem/arm-reproduction.md) | `plugmem-p1-3conv` | 待审 |

跑法与通用八步相同：`python main.py smoke <arm>`（8/8）→ `python main.py run --arms <arm> --convs conv-26,conv-30,conv-49 --n 3 --top-k 20`。

> [!warning] 三个 active 臂不与零 LLM 检索臂并列成本/延迟
> memharness / graphmemix / plugmem(T_max=2) 在 retrieve 路径里调 LLM，属 active retrieval 面（同 intent_tier2）。
> 分数可比，但成本/延迟表必须分栏，见 [docs/interface-spec.md](docs/interface-spec.md) §7 “retrieve 路径是否调 LLM”。
> 各臂的论文↔代码分歧清单在 `servers/<arm>/paper-vs-code.md`；可视化流程图在 `servers/flowgen/`（方法论骨架 `servers/METHODOLOGY-SKELETON.md`）。

---

## 臂矩阵

| 臂 | 类型 | venv | 外部依赖 |
|---|---|---|---|
| `mock` | 契约参照（固定返回） | `.venv` | — |
| `mem0` | 记忆系统 | `.venv` | LLM |
| `graphiti` | 记忆系统（图） | `.venv` | LLM + Neo4j 容器 |
| `memos` | 记忆系统（纯 REST） | `.venv` | MemOS compose 栈 :8000 |
| `amem` | 记忆系统 | `.venv-amem` | LLM（走 OpenAI SDK env 约定） |
| `mandol` | 记忆系统 | `.venv-mandol` | cloud embedding |
| `rag_baseline` | 对照臂（裸向量） | `.venv` | embedding，无 LLM |
| `atommem` | 记忆系统（原子事实 + 画像 + 符号过滤） | `.venv` | LLM + 上游 repo clone |
| `memharness` / `memharness_noadapt` | 记忆系统（批判重构，active）/ 其消融对照 | `.venv` | LLM |
| `graphmemix` | 记忆系统（关系图 + 变基数定选，active） | `.venv` | LLM + 上游 repo clone |
| `plugmem` | 记忆系统（三层知识图 + 多跳，默认 active） | `.venv` | LLM + 上游 repo clone |
| `intent` | 意图系统（TS/Bun） | — | LLM |
| `full_context` | 对照臂（runner 内置，非 server） | — | — |

**为什么是三个 venv**：`mandol` 锁 `numpy<2`，与 chromadb 冲突；`amem` 要 `pip -e` 装上游
repo。二者各自独立 venv，主 venv 装其余。哪个臂用哪个解释器写在 `servers.yaml` 里，
runner 和 smoke test 都从那里读——改解释器只改 `servers.yaml`。

---

## 目录结构

```
bench/          评测循环：runner.py（两阶段）/ scoring.py（双轨判分）/ llm.py（答题+判分客户端）
servers/        每个记忆系统一个 MCP server；common/ 是共享的契约基类与 envelope 归一化
loaders/        benchmark → 统一 add_conversation 形状
scripts/        smoke_test.py = 契约测试（也是回归门禁）
tests/          pytest 包装层，见下
data/           locomo/locomo10.json
runs/<run-id>/  跑分产物，见下
docs/           设计文档，见下
servers.yaml    server 注册表：命令、解释器、必需环境变量
```

## 跑分是怎么跑的

两阶段，幂等键 `arm|conv|qa_id|rep`，`--resume` 对两阶段各自跳过已完成行：

- **Phase A**（串行，单 server）：ingest（断点续灌）→ `snapshot("locomo_full")` →
  逐题 forced-call `retrieve` → `evidence/<arm>.jsonl`（存 envelope 原文，可审计）
- **Phase B**（默认 16 并发）：evidence → 答题 → 双轨判分 → `answers.jsonl`（append-only）

判分双轨：**轨 1** 本地词级 F1（SQuAD 式，免费确定性，cat5 adversarial 不计）；
**轨 2** LLM-judge（主表口径）。协议细节见 `docs/bench-design.md` §5–§6。

## 产物

`runs/<run-id>/` 下：

| 文件 | 入 git？ | 说明 |
|---|---|---|
| `manifest.json` | ✅ | run 配置快照：臂、模型、prompt 版本、起止时间 |
| `system_stats.jsonl` | ✅ | 各臂 `stats()`：记忆条数、token、延迟 |
| `failures.jsonl` | ✅ | 失败臂与原因 |
| `ingest_progress`, `*.log` | ✅ | 灌数进度与日志 |
| `answers.jsonl` | ❌ | ~58MB/run，逐题答案+判分 |
| `evidence/` | ❌ | ~73MB/run，检索 envelope 原文 |

后两者太大不入 git，用 `scripts/archive_run.sh <run-id>` 打包到 `archives/`（gzip 后约
1/7），再自行放到 laptop 以外的地方。**元数据入 git 意味着 `git push` 之后 provenance
就已经不在单机上了**——但原始答案还在，别只依赖这台机器。

## 文档

| 想知道什么 | 看哪份 |
|---|---|
| 整体路线、阶段、已锁定决策 | [PLAN.md](PLAN.md) |
| 装什么、怎么起、key 放哪 | [DEPLOY.md](DEPLOY.md) |
| MCP 接口契约（六个工具的语义） | [docs/interface-spec.md](docs/interface-spec.md) |
| 臂矩阵、ingest/答题/判分协议、成本 | [docs/bench-design.md](docs/bench-design.md) |
| 第二轮：论文级可复现的模块拆分 | [docs/REPRO-PLAN.md](docs/REPRO-PLAN.md) |
| Pi harness 工程量评估 | [docs/pi-harness-effort.md](docs/pi-harness-effort.md) |
| 痛点—方法论—批评矩阵（选型来历） | [docs/agent-memory-pain-points.md](docs/agent-memory-pain-points.md) |
| 14 个记忆系统的跨系统方法论骨架（A1–A6 / B1–B8 泳道） | [servers/METHODOLOGY-SKELETON.md](servers/METHODOLOGY-SKELETON.md) |
| 各系统论文↔代码分歧（逐机制带 file:line） | `servers/<arm>/paper-vs-code.md`（14 份） |
| 新四臂复现口径与门禁记录 | `servers/{atommem,memharness,graphmemix}/REPRO-NOTES.md`、`servers/plugmem/arm-reproduction.md` |
| 机制→产品形态示意 | `servers/<arm>/product-concepts/`（atommem / memharness / graphmemix / plugmem） |

## 公平性约定

所有臂共用同一 LLM 配置（`MEMBENCH_LLM_*`）、同一答题模型（`MEMBENCH_ANSWER_*`）、
同一 prompt 与 `temperature=0`，并把返回统一成 canonical envelope——目的是让差异只来自
记忆机制本身，而不是"谁的配置调得好"。改任何一项前先读 `docs/interface-spec.md` §7。

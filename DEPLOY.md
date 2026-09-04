# 部署 Runbook

> 装什么、怎么起、key 放哪、踩过哪些坑。路线与阶段划分见 [PLAN.md](PLAN.md)，
> 接口语义见 [docs/interface-spec.md](docs/interface-spec.md)，评测协议见 [docs/bench-design.md](docs/bench-design.md)。
>
> 环境：macOS，uv + Python 3.12，Docker 28。当前状态 = Phase 1 完成态（8 臂 6/6 过门禁）。
> 最后核实：2026-08-22（graphiti EdgeDuplicate patch）。

---

## 1. 环境与 venv

```bash
cd /Users/guanhongli/Documents/repo/memory-bench
uv venv -p 3.12                 # 主 venv
```

三个 venv，各自装谁、为什么分开：

| venv | 装了谁 | 分开的理由 |
|---|---|---|
| `.venv` | mock / mem0 / graphiti / memos / rag_baseline | 主环境 |
| `.venv-mandol` | mandol | mandol 锁 `numpy<2`，与 chromadb 冲突 |
| `.venv-amem` | amem | 装官方 repo `agiresearch/A-mem`（`pip -e`） |

> ⚠️ 系统 Python 是 3.14，一律走 venv，别直接 `pip3`。
>
> ⚠️ **A-MEM 必须装官方 repo**：PyPI 上的 `a-mem` 是假包，装了会静默跑错东西。

哪个臂用哪个解释器写在 `servers.yaml`，runner 与 smoke test 都从那里读——换解释器只改那一处。

## 2. 密钥与公平性 LLM 配置

`cp .env.example .env` 后填值。变量清单以 `.env.example` 为准，各臂必需项见
`servers.yaml` 的 `env_required`（缺失时 smoke test 显式报缺，不静默降级）。

记忆系统内部 LLM 统一走智谱 OpenAI 兼容端点，`temperature=0`（interface-spec §7，防"比配置不比记忆"）：

- `MEMBENCH_LLM_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4`
- `MEMBENCH_LLM_MODEL=glm-5.3`
- `MEMBENCH_EMBED_MODEL=embedding-3`

> ⚠️ 必须走 **coding 通道**（`/api/coding/paas/v4`）。普通 `/api/paas/v4` 端点对该 key 报 glm-5.3 无权限。

实测（2026-08-18）：glm-5.3 抽取 ~15s/次 add；embedding-3 正常。

答题/判分 LLM 走 `MEMBENCH_ANSWER_*`（Linux vLLM via ngrok，Anthropic 兼容面）。
⚠️ ngrok 免费隧道重启会换 URL——变更只改 `.env`。

## 3. 冒烟门禁

任何 server 进实验矩阵前必须全绿；这也是规范变更后的回归门禁。

```bash
python main.py smoke mock     # 无 LLM，验证契约链路本身
python main.py smoke mem0     # 真实系统
pytest                        # 全部 server 的契约测试（需依赖在位的臂会 skip）
```

八步断言，执行序为 1 add → 2 retrieve → 3 snapshot+reset → 4 reset 幂等 → 5 restore 可复现
→ **7 reset→add 链路**（防静默丢数据）→ **8 双 scope 隔离**（防跨 scope 泄漏）→ 6 清场。
7/8 是 2026-08-19 核查后补入的（对应 §6 的 P1/P3），编号沿用当时的断言号，所以 6 排在最后。

## 4. 外部依赖

跑全矩阵前先起：

```bash
docker start membench-neo4j                                # graphiti
cd ~/Documents/repo/MemOS/docker && docker compose up -d    # memos
```

**Neo4j 首次创建**（graphiti 用）：

```bash
docker run -d --name membench-neo4j -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/membenchpass \
  -v $PWD/.state/graphiti/neo4j-data:/data \
  -v $PWD/.state/graphiti/neo4j-logs:/logs \
  neo4j:5
```

快照/恢复 = 停容器拷卷（`neo4j-admin dump` 需 DB offline，直接停更稳），单次 ~15–20s。

MemOS compose 栈已去掉 neo4j/qdrant 的宿主端口映射（防与上面的容器冲突），服务在 `:8000`。

## 5. 全系统矩阵（Phase 1 完成态，2026-08-18 深夜）

| system | 门禁 | add 耗时(3turn) | 栈 | 快照方式 | 特殊注意 |
|---|---|---|---|---|---|
| mock | 6/6 | <10ms | 主 venv | 目录拷贝 | 契约靶 |
| mem0 | 6/6 | ~4s | 主 venv + chroma | 目录拷贝 | chroma 缓存须 `clear_system_cache()` |
| graphiti | 6/6 | ~12s | 主 venv + Neo4j 容器 | 停容器拷卷 ~15–20s | 需 membench-neo4j |
| mandol | 6/6 | ~22s | `.venv-mandol` | `save_graph` | `SILICONFLOW_*` 重定向智谱；MODEL_CONFIG 注入 |
| amem | 6/6 | ~35s | `.venv-amem`（官方 repo `pip -e`） | notes.json + homes | 内存 chroma 须注入重建 |
| memos | 6/6 | ~14s | 主 venv + compose 栈 :8000 | `SNAPSHOT_UNSUPPORTED`（重灌兜底） | 容器内温度/reasoning 未受控（已声明偏离） |
| intent | 6/6 | ~7.6s | Bun（TS，同 intent-recall 栈） | 目录拷贝 | LLM 生成意图摘要；Tier 1 检索 <5ms |

`rag_baseline`（裸向量对照臂）与 `full_context`（runner 内置）不在此表：前者随 bench-design §3
补入，后者不是 server。

意图适配层语义声明：`retrieve` = Tier 1（session 级意图摘要检索，`turn_range` 恒 null）；
Tier 2 精读（`read_session_detail` / `recall_timeline`）属 agent 用法，留给二轮 free-call 臂。

## 6. 已知坑与修复记录

**跨系统（都已修在代码里）**

- MCP stdio 子进程只继承最小环境，`MEMBENCH_*` 必须由客户端显式转发（smoke_test.py 已处理）
- chroma `PersistentClient` 按路径缓存 system 实例：reset/restore 前必须 `clear_system_cache()`，否则读到旧状态
- mem0 `add(timestamp=)` 是 Pro 功能，OSS 版走 metadata

**graphiti**

- `OpenAIClient` 走 OpenAI Responses API（`input`/`text_format`），智谱只有 chat/completions
  → 必须用 `OpenAIGenericClient` + `structured_output_mode="json_object"`
- GenericClient 不透传 `reasoning_effort` → 在 AsyncOpenAI 客户端上用 `extra_body` 钉（与 mem0 同款手法）
- `Graphiti()` 默认 reranker 无参构造会去找 `OPENAI_API_KEY`
  → 必须显式传 `cross_encoder=OpenAIRerankerClient(config=LLMConfig(同端点))`
- envelope 的 timestamp 语义 = 边创建时间（非事实时间）；graphiti 边有 `valid_at`，
  Phase 2 渲染层统一时再决定是否切换
- 🔴 **0.29.3 EdgeDuplicate 嵌套坑（2026-08-22 修复，且脆弱）**：glm-5.3 在 `json_object`
  模式下习惯返回嵌套 `{"answer": {...}}`，而库 `resolve_extracted_edge` 假定扁平
  `{duplicate_facts, contradicted_facts}` → `EdgeDuplicate(**llm_response)` pydantic 校验崩。
  已 patch site-packages `edge_operations.py` 第 732 行（先 `flat = llm_response.get("answer", llm_response)` 再构造）。
  **重装或重建 `.venv` 会丢这个 patch。** smoke 的 3 turns 边太少不触发，LoCoMo 大规模 ingest 才踩到。
  ✅ 2026-09-04 已物化进仓：两个 patch 后的完整文件在 `patches/graphiti/`（含 SHA256SUMS），
  重建 venv 后跑 `bash patches/apply.sh` 即可恢复（版本钉死 0.29.3，幂等，hash 校验）。

**2026-08-19 深度核查修复（子会话 deep-verification）**

| 编号 | 问题 | 修法 |
|---|---|---|
| P1 | mem0 reset 悬挂句柄：reset 后 add 静默丢数据（readonly database，假成功） | reset 以 `_drop_memory()` 收尾 |
| P2 | amem 多 scope collection 损坏：内存版 `chromadb.Client()` 同进程共享，写死 collection 名互踩 | per-scope 唯一 collection 名 `mem_<scope>` |
| P3 | mem0 `filter.scope_id` 被残留行覆盖（跨 scope 泄漏） | 已删 |
| P4 | amem `temperature=0.7` 违约 | monkeypatch 强制 0 |
| P5 | intent `reasoning_effort` 是死代码 | 真实现 |

**未修但已声明的偏离**

- mandol：add 后不自动落盘 → 评测须 `restore` 起跑，或在进程内完成 ingest→QA
- memos：容器内温度 / reasoning 未受控
- intent：检索期 Tier 2 精读依赖网络，失败降级为机械摘录（`native_notes` 记 `TIER2_FALLBACK`，
  基线降级率 ~12%）；且 `summarize()` 的中文 prompt 生成中文摘要，英文 query 的 token 重叠仅
  2/7（仅专有名词穿透）——英文语料上意图层基本未生效（locomo-r2-n3 退出原因，V-1）。
  修复方向：prompt 要求「用与原文相同的语言输出」后重灌
- 逐系统配置清单表见 interface-spec §7

**2026-08-30 全量 run（locomo-r2-n3）实录的运维坑**

- 🔴 **progress 机制陷阱（本轮头号坑）**：`ingest_system()` 只看
  `runs/<run_id>/ingest_progress/progress.json` 决定是否跳过 ingest。新 run-id 的 progress
  为空 → restore 之后照样全量重灌，并在最后 `snapshot` **覆盖快照**。快照已完备的臂，跑前
  必须预置 progress（从旧 run 复制，或按快照实际内容构造，构造脚本思路：
  mem0/graphiti 从 locomo-r1 复制；intent 取快照 scopes.json 的 sessions；rag_baseline 取
  chunks.jsonl 的 distinct session_id——标记数必须与快照内容一致，多标一个 session = 那段
  数据永远不被补灌）
- **`--resume` 跳过 `mkdir`**：`Run.__init__` 只在非 resume 时建 `evidence/`。手工建过 run
  目录（比如只为预置 progress）的，resume 前确认 `evidence/` 存在，否则 Phase A 写盘
  FileNotFoundError
- **Phase A 单臂失败不阻塞 Phase B**：retrieve 挂了会写 `failures.jsonl` 然后直接进
  Phase B（在不完整数据集上跑）。每次 run 后核对各臂 evidence 行数是否 = 1986 × n
- **并发与吞吐非线性**：`--concurrency` 只作用于 Phase B（Phase A 串行）。429 长退避
  （5/10/20/30/45/60s，最多 9 次）期间并发槽空转，实测 16 并发有效并发远低于 16；
  降到 10 吞吐仅 -7%（1.4→1.3 题/s）。**勿按比例外推并发调整的代价**；弃题由
  `--resume` 补回（不写入 answers.jsonl）
- **断电/断网恢复**：evidence 与 answers 均行级落盘 + 幂等键，中断后 `--resume` 零重复；
  jsonl 尾部可能留半写行，读取方需容错。网络类挂起看 `suspended_reason`：
  `ConnectError` = 断网，`HTTP 429` = 限流，恢复网络后直接 resume
- **graphiti 容器开销**：restore/snapshot 会自动 stop/start `membench-neo4j`（约 19s）；
  跑分只剩 Phase B 时可 `docker stop` 省资源（Phase B 不碰任何 MCP server）

## 7. 跑分入口

```bash
python main.py run --arms mock,full_context --convs conv-30 --run-id shakeout
python main.py run --arms mem0,graphiti,intent --run-id locomo-r1 --resume
python main.py run --arms mem0 --run-id locomo-r1 --ingest-only     # 只灌数据+snapshot
```

产物落 `runs/<run-id>/`，字段与入 git 与否见 [README](README.md#产物)。

## 附录 A · Benchmark 数据与官方评测代码

| Benchmark | 数据 | 官方评测代码 |
|---|---|---|
| **LoCoMo** | HF `mem0ai/locomo`（本仓已存 `data/locomo/locomo10.json`） | `github.com/mem0ai/mem0` → `evals/unified_mem/` |
| **LongMemEval** | HF dataset（官方 repo） | `github.com/xiaowu0162/longmemeval`（oracle / haystack 两模式）；V2 = 451 题 |
| **DMR** | MemGPT 论文生成 | mem0 evals 内含实现 |

> 注：早期设想是直接复用 mem0 的 `evals/unified_mem` 当 harness。**最终没有采用**——
> forced-call 协议、canonical envelope、snapshot/restore 都需要自己的跑台，
> 见 `bench/runner.py`。上表现在只作为**数据来源与口径参照**。

## 附录 B · 已废弃的初版计划（2026-08-18）

初版 runbook 里的"记忆系统安装矩阵"含 **Letta**，并按 P0/P1/P2 排了接入优先级。
该分档已被 PLAN.md §2 的 A档/B档筛选框架取代：Letta 与 MRAgent 的记忆机制住在 agent loop
内部，被动 MCP 化即变质，**延后到第二轮**以其自身运行时为 SUT 整体评。
初版的"执行顺序"与"需要的 key"两节也已分别由 PLAN.md §3 和 `.env.example` 取代，故删除。

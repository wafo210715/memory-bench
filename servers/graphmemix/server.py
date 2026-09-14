# graphmemix：A档系统（arXiv:2608.26983，GraphMemix: Query-Aware Evidence Forests for
#   Long-Term Multimodal Agent Memory；上游 ligeng0197/graphmemix @ d0ea01d）
#
# 机制：写入侧只做"编码 + 建 query-independent 关系图"（A2/A4/A5）；查询到来后把"该给
#   agent 看哪些记忆"当成一次组合优化求解（B1-B5）——多视角检索定种子 → discovery graph
#   上 1 跳扩展出候选 → 两次 listwise LLM 打分（节点直接效用 / 锚点条件下的增量价值）
#   → 1-swap + Kruskal 定 K 节点提案 → 提案内穷举子集精确求变基数解 → 按森林分量序列化。
#
# ═══ 复现口径（2026-09-12 定，偏离论文/上游处全部列在这里，不静默）═══
#
# 口径 1 · 论文核心算法直接引上游原版，不重写
#   candidate_pool（Eq.4-5 候选图发现）、solve_forest_greedy（Eq.11-12 的 1-swap + Kruskal）、
#   exact_subset / positive_edges（Eq.13 的穷举 + Kruskal）三段都是 sys.path 引入上游
#   scripts/ 下的函数，只读、不改上游仓库。论文一号贡献（森林优化）因此是原版实现。
#
# 口径 2 · 胶水层按论文补齐（上游此处不可运行）
#   上游把"写入编码 / 多视角检索 / 证据序列化"放在 ConcreteMemixMethod，而它硬依赖一个
#   仓库里没有、README 也没给下载方式的私有包 vendor/memix-core（concrete_memix.py:48-52）。
#   这三段按论文 §3.3 Eq.3（多视角 max-pool）与 Appendix A.5（分量根优先 + 分量内 BFS）实现。
#
# 口径 3 · 编码器换 embedding-3（偏离论文/上游的 gme-Qwen2-VL-2B-Instruct 1536d）
#   与 mem0 / graphiti / mandol / rag_baseline / atommem 同口径，排除"嵌入强度"这个跨臂变量。
#   ⚠️ 代价：论文 Eq.14 的 (α,τ,δ) 是在 gme 的余弦尺度上定的（上游 dev-fold 拟合记录的
#     检索分均值 0.385、标准差 0.114，shared_dev.json）。换 embedding-3 后 s_i 分布会平移，
#     节点效用 p_i 随之漂移，直接决定 prune 保留多少条证据。
#     由 stats().prize_probes 逐次观测——这是本臂开跑前必须先看的观测项，不是可选调试信息。
#
# 口径 4 · 证据预算 K = 契约的 top_k，不用论文写死的 reader_k=10
#   K 在 Eq.1/Eq.11 里的语义就是"交给 reader 的证据条数上界"，与契约 top_k 同义。
#   固定 10 而其他臂给 20，比的是证据预算不是选证据能力（interface-spec §7 要防的正是这个）。
#   论文的 K=10 记为偏离项；top_k 由 harness 统一传入。
#
# 口径 5 · 穷举精修按连通分量分解（数学等价的加速，非近似）
#   Eq.13 的目标 J(S,F) = Σ_{i∈S}(p_i − node_cost − root_cost) + Σ_{e∈F} B_e。
#   正收益边不相连的两组节点之间没有任何耦合项，故 J 在连通分量间可加，
#   全局穷举的最优解 = 各分量独立穷举最优解的并集。上游 exact_subset 在 n>20 直接抛异常
#   （evaluate_graphmemix_exact_pruning.py:62），而口径 4 下 K=20 时全局穷举是 2^20 子集。
#   分解后逐分量调用同一个上游函数，实际每块通常 ≤8 个节点。
#   单个分量超过 EXACT_PRUNE_MAX_NODES=18 时按 p_i 降序截断，native_notes 标
#   EXACT_PRUNE_TRUNCATED（该情形在 LoCoMo 上未观测到，属防御分支）。
#
# 口径 6 · schema 关系只有 consecutive_turn，没有 same_round
#   上游 explicit_edges（build_graphmemix_relation_store.py:70-101）只认两个字段：
#   metadata.native_round_id → same_round，session_id + sequence 相邻 → consecutive_turn。
#   LoCoMo 经 loaders/locomo.py 交给 server 的 turn 只有 {role, content, timestamp}，
#   没有配对的 native round 字段。这与论文 Appendix A.1 对 H2HMem 的处理逐字对应
#   （"it does not expose the paired native-round field required by same_round"），
#   不是实现缺失。native_notes 标 SAME_ROUND_UNAVAILABLE。
#
# 口径 7 · 多视角（multi-view）在纯文本 LoCoMo 上退化为单视角
#   论文 Eq.3 的 s_i = max_{u∈U_i} sim(h(q), h(u)) 需要一条记忆有多个视角（原图/caption/
#   OCR/视频帧）。loaders/locomo.py 在 harness 层已丢弃图像描述，每条 turn 只有一个文本视角，
#   max-pool 退化成恒等。GraphMemix 的多模态部分因此**未被本臂测到**；被测到的是
#   discovery graph、两次验证、森林优化这条与模态无关的主干。native_notes 标 MULTIVIEW_DEGENERATE。
#
# 口径 8 · 节点效用用论文 Eq.14/15 的固定超参，不用上游 dev-fold 拟合系数
#   上游 shared_dev.json 的 (a,b,c)=(4.054, 0.2254, −3.711) 是**用 gold 证据标签**在四个
#   多模态数据集的 SHA256 fold-0 上拟合的（warning 字段自述）。我们没有对应的 dev fold，
#   嵌入也换了，那组系数不可移植。改用论文 Eq.14 (α,τ,δ)=(0.8, 5.2, 0.7) 展开的
#   p_i = σ(4.16·s_i + 0.208·v_i − 3.64)。与上游拟合值逐系数差 2-8%（a 2.6% / b 7.7% / c 1.9%），
#   同输入下输出 p_i 的差异更小（sigmoid 在这个区间压缩）；且论文明说四个数据集、
#   两个 backbone 都不重调——这正是"按论文理念复现"该取的那一版。
#
# 口径 9 · 两次 listwise 调用真并行
#   论文 §4.1/§4.4.4 两处无条件断言 node verifier 与 ECV 并行执行；上游因为 query-image
#   caption 只在 node 阶段生成，ecv 对 node 存在真实数据依赖，被迫编排成顺序 stage
#   （paper-vs-code 差异 3）。LoCoMo 无图、无 caption 调用，该依赖不存在，故本臂按论文
#   用线程池真并行发两个请求。
#
# 口径 10 · retrieve 路径调 2 次 LLM 且读记忆内容 → 属 active retrieval 面
#   node verifier 和 ECV 都要读候选记忆的正文才能打分（论文 Eq.6/Eq.7 的定义如此）。
#   这与 mem0 / graphiti / mandol / rag_baseline 的"零 LLM 纯检索"、以及 atommem 的
#   "只读 query 不读记忆"都不是同一个口径，与 intent Tier2 同属"检索侧读记忆内容"。
#   成本表、延迟表、纯检索面对比表必须单列，不得并入被动检索主表（interface-spec §7）。
#
# 口径 11 · envelope 顺序是森林序，不是 score 降序
#   Appendix A.5 规定的证据顺序（每个连通分量取效用最高节点作根、按根效用排分量、
#   分量内 BFS）本身是机制的一部分——"先给直接锚点，再给经可信关系恢复的上下文"。
#   §4 的 score 降序是给无原生顺序的系统设的默认值，这里不适用（graphiti 的 MIX 3:1:1
#   已有先例）。native_notes 标 ORDER=forest_bfs。
#
# 口径 12 · 查询级结果缓存（为满足契约的 retrieve 幂等性）
#   interface-spec §1 要求 retrieve 幂等，但本臂的 retrieve 路径调 LLM，服务端 batching 的
#   浮点非确定性会让 v_i 微动，在 prune 临界值（prize ≈ 0.12）附近的节点一进一出。
#   2026-09-12 smoke 第 5 步（restore 后同 query 结果一致）实测报 FAIL，就是这个原因。
#   做法：结果按 (query, query_mode, top_k, scope_id, 库内容 sha256) 缓存在进程内，
#   库变了自然失效；restore 回相同内容则命中，幂等成立。
#   ⚠️ 代价：runner 的 n=3 是同一 server 进程内重复调 retrieve（bench/runner.py:240），
#     缓存会把本臂的**检索侧**方差归零。这与 mem0/graphiti/rag_baseline 等确定性检索臂
#     的行为一致（它们三个 rep 的 evidence 本来就逐字相同），n=3 测的是答题 LLM 的方差。
#     要测 GraphMemix 自己的检索侧波动，用 MEMBENCH_GRAPHMEMIX_CACHE=off 单独跑一轮对照，
#     不混进主跑。
#
# 依赖：主 venv（.venv）。上游是脚本式仓库，用 sys.path 引入，不 pip 安装、不改上游仓库。
# 环境变量：MEMBENCH_LLM_API_KEY / MEMBENCH_LLM_BASE_URL / MEMBENCH_LLM_MODEL
#   （可选 MEMBENCH_GRAPHMEMIX_REPO 指向上游 clone，默认 ~/Documents/repo/graphmemix）

import hashlib
import json
import logging
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

MEMBENCH_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(MEMBENCH_ROOT))

# 日志改道 stderr，防污染 stdio JSON-RPC
logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

from fastmcp import FastMCP
from openai import OpenAI

from servers.common.base import BaseState
from servers.common.envelope import make_envelope
from servers.common.stats import StatsTracker

# ═══ 上游引入（只读，不改上游仓库）═══
GRAPHMEMIX_REPO = Path(
    os.environ.get("MEMBENCH_GRAPHMEMIX_REPO") or (Path.home() / "Documents" / "repo" / "graphmemix")
).resolve()
if not (GRAPHMEMIX_REPO / "scripts" / "graphmemix_core.py").exists():
    raise RuntimeError(f"上游 graphmemix 仓库不存在: {GRAPHMEMIX_REPO}（用 MEMBENCH_GRAPHMEMIX_REPO 指定）")
sys.path.insert(0, str(GRAPHMEMIX_REPO / "scripts"))
sys.path.insert(0, str(GRAPHMEMIX_REPO / "src"))

from graphmemix_core import candidate_pool, load_adjacency          # noqa: E402  Eq.4-5
from probe_graphmemix_pcsf import solve_forest_greedy               # noqa: E402  Eq.11-12
from evaluate_graphmemix_exact_pruning import exact_subset, positive_edges  # noqa: E402  Eq.13

mcp = FastMCP("graphmemix")

_state = BaseState("graphmemix")
_stats = StatsTracker()
_MEM_FILE = _state.state_dir / "memories.jsonl"
_VEC_FILE = _state.state_dir / "vectors.npy"
_REL_FILE = _state.state_dir / "relations.jsonl"
_REL_META = _state.state_dir / "relations_meta.json"

# ═══ 超参：全部取 configs/release/graphmemix.json 的生产值 ═══
SOURCE_TOP_K = 200          # 多视角检索保留的原始召回深度
SOURCE_TOP_L = 24           # 种子数 L（Eq.5）
CANDIDATE_LIMIT = 48        # 候选池 M（Eq.5）
SEMANTIC_K = 8              # 语义 mutual-kNN 的 k（Eq.4）
ANCHOR_COUNT = 10           # ECV 锚点数（论文未给，取上游 anchor_count）
EXPLICIT_SIMILARITY = 0.99  # schema 边可靠度上限 w^schema（论文 §4.1）
EDGE_WEIGHT = 0.1           # λ
PROPOSAL_ROOT_COST = 0.2    # κ（select 阶段）
PRUNING_ROOT_COST = 0.12    # κ（prune 阶段）
PRUNING_NODE_COST = 0.0     # 上游 --node-cost 默认
EDGE_POWER = 1.0
SNIPPET_CHARS = 420
VERIFIER_MAX_OUTPUT_TOKENS = 8192
EXACT_PRUNE_MAX_NODES = 18  # 口径 5 的防御上界

# 论文 Eq.14 → Eq.15 展开：p_i = σ(τ·α·s_i + τ·(1−α)/5·v_i − τ·δ)
PAPER_ALPHA, PAPER_TAU, PAPER_DELTA = 0.8, 5.2, 0.7
PRIZE_A = PAPER_TAU * PAPER_ALPHA                 # 4.16
PRIZE_B = PAPER_TAU * (1 - PAPER_ALPHA) / 5.0     # 0.208
PRIZE_C = -PAPER_TAU * PAPER_DELTA                # -3.64

# 429 限流退避序列，与 bench/llm.py:34 同一套（网关是分钟级 RPM 窗口，短退避无效）。
# 2026-09-12 v1 run 的教训：限流被当成 JSON 校验失败快速重试三次，然后静默降级为全零分，
# 证据质量退化却无法从输出看出来。两类错误必须分开处理：限流要等，格式错要重提。
_RL_BACKOFF = [5, 10, 20, 30, 45, 60, 60, 60]
_FORMAT_RETRIES = 3

POSITIVE_ROLES = {"new_fact", "clarification", "corroboration"}
ALL_ROLES = ["new_fact", "clarification", "corroboration", "redundant", "conflict", "irrelevant"]

_THINKING = os.environ.get("MEMBENCH_THINKING", "low")
_PRUNE_ENABLED = os.environ.get("MEMBENCH_GRAPHMEMIX_PRUNE", "on") != "off"
_CACHE_ENABLED = os.environ.get("MEMBENCH_GRAPHMEMIX_CACHE", "on") != "off"
_CACHE_LIMIT = 4096

# 进程内缓存（relation store 构建一次可服务全部查询；restore/reset 后必须失效）
_adj_cache: dict | None = None
# 查询级结果缓存（口径 12）：key → (ordered_ids, prizes, notes)，envelope 现场重渲染省内存
_query_cache: dict[str, tuple[list, dict, list]] = {}
_corpus_sha: str | None = None
_probe: dict = {}


def _reset_probes() -> None:
    global _probe
    _probe = {
        "retrieve_calls": 0,
        "prize_min": None, "prize_median": None, "prize_max": None,
        "select_k": [], "prune_kept": [],
        "trusted_edges": [], "candidate_pool_size": [],
        "eligible_edge_pairs": [], "llm_parse_failures": 0,
        "exact_prune_truncated": 0, "components": [],
        # ECV 是否真被激活：返回行数、六角色分布、被判无效丢弃数。
        # 缺了这三项就无法区分“模型判定这些边确实冗余”与“解析把边吃掉了”。
        "ecv_rows_returned": 0, "ecv_rows_dropped": 0, "llm_transient_retries": 0,
        "node_failed": 0, "ecv_failed": 0,
        "ecv_roles": {r: 0 for r in (
            "new_fact", "clarification", "corroboration", "redundant", "conflict", "irrelevant")},
        "verifier_scored": [], "swap_iterations": [], "forest_degenerate": 0,
    }


_reset_probes()


# ═══ embedding（与 rag_baseline / atommem 同口径）═══

_REQUIRED = ["MEMBENCH_LLM_API_KEY", "MEMBENCH_LLM_BASE_URL"]


def _require_env() -> None:
    missing = [k for k in _REQUIRED if not os.environ.get(k)]
    if missing:
        raise RuntimeError(
            f"缺少环境变量 {missing}——MCP stdio 子进程不继承父进程环境（见 interface-spec §7）"
        )


def _embed_client() -> OpenAI:
    _require_env()
    # embedding 走智谱普通通道：coding 通道无 embedding-3 权限（同 rag_baseline）
    base = os.environ.get("MEMBENCH_EMBED_BASE_URL") or os.environ["MEMBENCH_LLM_BASE_URL"].replace("/coding", "")
    key = os.environ.get("MEMBENCH_EMBED_API_KEY") or os.environ["MEMBENCH_LLM_API_KEY"]
    return OpenAI(api_key=key, base_url=base)


def _embed(texts: list[str]) -> tuple[list[list[float]], int]:
    """批量 embed。限流与服务端错误走与内部 LLM 同一套长退避（fable 审查 MINOR）。"""
    model = os.environ.get("MEMBENCH_EMBED_MODEL", "embedding-3")
    attempt = 0
    while True:
        try:
            r = _embed_client().embeddings.create(model=model, input=texts)
            return [d.embedding for d in r.data], r.usage.total_tokens
        except Exception as e:  # noqa: BLE001
            name = type(e).__name__
            status = getattr(e, "status_code", None)
            transient = (
                name in {"RateLimitError", "APIConnectionError", "APITimeoutError", "InternalServerError"}
                or status == 429 or (isinstance(status, int) and status >= 500)
            )
            if not transient or attempt >= len(_RL_BACKOFF):
                raise
            wait = _RL_BACKOFF[attempt]
            print(f"[graphmemix-embed] {name}，{wait}s 后重试（{attempt + 1}/{len(_RL_BACKOFF)}）", file=sys.stderr)
            time.sleep(wait)
            attempt += 1


# ═══ 内部 LLM（node verifier / ECV），thinking 三态与 mem0/atommem 对齐 ═══

def _llm_client() -> OpenAI:
    _require_env()
    return OpenAI(api_key=os.environ["MEMBENCH_LLM_API_KEY"], base_url=os.environ["MEMBENCH_LLM_BASE_URL"])


def _llm_json(messages: list[dict], tag: str) -> tuple[dict | None, int]:
    """listwise 调用，强制 JSON 对象输出。两类失败分开处理：

    格式类（JSON 解析/校验）——把错误回灌给模型再要一次，最多 3 次（上游同款协议，
      score_graphmemix_verifier.py:325-345）；耗尽后返回 None，调用方降级为全 0 分并打标。
    限流/服务端类（429、5xx、连接错误）——原样重发，走长退避；退避耗尽则招 RuntimeError。

    为什么限流耗尽要招而不是降级：降级会产出一条“看上去正常但两次验证都没跑”的证据，
    进而把机制未被激活误计成“森林在 LoCoMo 上退化”——这是静默产出错误结论，比该题失败严重得多。
    """
    client = _llm_client()
    model = os.environ.get("MEMBENCH_LLM_MODEL", "glm-5.3")
    extra: dict = {"thinking": {"type": "disabled" if _THINKING == "disabled" else "enabled"}}
    max_tokens = VERIFIER_MAX_OUTPUT_TOKENS
    if _THINKING == "low":
        extra["reasoning_effort"] = "low"
    else:
        # 思考与正式回复共用额度，非 low 档 8192 必爆（同 atommem/graphiti 处理）
        max_tokens = 128000
    tokens = 0
    attempt_messages = messages
    fmt_attempt = 0          # 格式重试次数
    rl_attempt = 0           # 限流/服务端退避次数，与格式重试分开计，不互相吃额度
    while True:
        counted = False      # 同一次 API 调用只计一次：调用成功但 JSON 解析失败时不能双计
        try:
            r = client.chat.completions.create(
                model=model, messages=attempt_messages, temperature=0,
                max_tokens=max_tokens, extra_body=extra,
                response_format={"type": "json_object"},
            )
            _stats.llm_calls += 1
            counted = True
            if getattr(r, "usage", None):
                tokens += int(r.usage.total_tokens or 0)
            return json.loads(r.choices[0].message.content or "{}"), tokens
        except Exception as e:  # noqa: BLE001
            if not counted:
                _stats.llm_calls += 1
            name = type(e).__name__
            status = getattr(e, "status_code", None)
            transient = (
                name in {"RateLimitError", "APIConnectionError", "APITimeoutError", "InternalServerError"}
                or status == 429 or (isinstance(status, int) and status >= 500)
            )
            # ★ 2026-09-13 修（fable 审查 F3）：非瞬时的 4xx（400 参数错、401 鉴权、403 无权限、
            # 404 模型不存在）既不是限流也不是格式问题，重试和回灌校正都没有意义。
            # 此前它们落进格式分支，三次后降级为全零分——又是一条静默降级路径。
            if (not transient and isinstance(status, int)
                    and 400 <= status < 500 and status not in (408, 409, 425, 429)):
                raise RuntimeError(f"graphmemix {tag}: 非瞬时 API 错误 HTTP {status}（{name}）: {e}") from e
            if transient:
                _probe["llm_transient_retries"] += 1
                if rl_attempt >= len(_RL_BACKOFF):
                    raise RuntimeError(
                        f"graphmemix {tag}: 限流/服务端错误退避耗尽（{rl_attempt} 次），最后一次 {name}: {e}"
                    ) from e
                wait = _RL_BACKOFF[rl_attempt]
                print(f"[graphmemix-{tag}] {name}，{wait}s 后原样重发（{rl_attempt + 1}/{len(_RL_BACKOFF)}）",
                      file=sys.stderr)
                time.sleep(wait)
                rl_attempt += 1
                continue     # 不回灌校正：限流不是模型的格式问题
            fmt_attempt += 1
            print(f"[graphmemix-{tag}] 格式失败 {fmt_attempt}/{_FORMAT_RETRIES}: {name}: {e}", file=sys.stderr)
            if fmt_attempt >= _FORMAT_RETRIES:
                _probe["llm_parse_failures"] += 1
                return None, tokens
            attempt_messages = messages + [{
                "role": "user",
                "content": (
                    f"Correction attempt {fmt_attempt + 1}: the previous response failed strict "
                    f"validation ({name}: {e}). Produce a fresh JSON object. "
                    "Do not emit prose or markdown."
                ),
            }]


# ═══ 状态读写 ═══

def _load_records() -> list[dict]:
    if not _MEM_FILE.exists():
        return []
    return [json.loads(line) for line in _MEM_FILE.read_text().splitlines() if line.strip()]


def _save_records(records: list[dict]) -> None:
    _MEM_FILE.parent.mkdir(parents=True, exist_ok=True)
    _MEM_FILE.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records))


def _load_vecs() -> np.ndarray | None:
    return np.load(_VEC_FILE) if _VEC_FILE.exists() else None


def _save_vecs(arr: np.ndarray | None) -> None:
    if arr is None or len(arr) == 0:
        if _VEC_FILE.exists():
            _VEC_FILE.unlink()
        return
    _VEC_FILE.parent.mkdir(parents=True, exist_ok=True)
    np.save(_VEC_FILE, arr)


def _corpus_fingerprint() -> str:
    """库内容指纹（口径 12 的缓存 key 组成部分）。restore 回相同内容时指纹也相同。"""
    global _corpus_sha
    if _corpus_sha is not None:
        return _corpus_sha
    h = hashlib.sha256()
    h.update(_MEM_FILE.read_bytes() if _MEM_FILE.exists() else b"")
    # 向量文件的字节数一并入指纹：记忆文本相同而向量不同的情形虽未观测到，
    # 但指纹漏掉它就等于给「同指纹返回过期结果」留了口子（fable 审查 MINOR）。
    h.update(str(_VEC_FILE.stat().st_size if _VEC_FILE.exists() else 0).encode())
    _corpus_sha = h.hexdigest()[:16]
    return _corpus_sha


def _mark_relations_dirty() -> None:
    # 注意：不清 _query_cache。它的 key 含库内容指纹，库变了自然不命中；
    # 而 reset 后再 restore 回相同内容时必须命中，那正是契约要求的幂等性（口径 12）。
    global _adj_cache, _corpus_sha
    _adj_cache = None
    _corpus_sha = None
    if _REL_META.exists():
        _REL_META.unlink()
    if _REL_FILE.exists():
        _REL_FILE.unlink()


# ═══ A4 INDEX：discovery graph（query-independent，写入侧产物）═══

def _mutual_neighbors(vectors: np.ndarray, max_k: int) -> list[tuple[int, int, int, int, float]]:
    """numpy 复刻上游 mutual_neighbors（build_graphmemix_relation_store.py:225-254）。

    上游用 faiss.IndexFlatIP；这里用归一化点积暴力扫，避免为 LoCoMo 这个规模引入 faiss。
    返回 (i, j, rank_i→j, rank_j→i, 双向余弦均值)，rank 为 1-based，只保留互为 top-k 的对。
    """
    if max_k <= 0 or len(vectors) < 2:
        return []
    normed = vectors / np.clip(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12, None)
    sims = normed @ normed.T
    n = len(vectors)
    take = min(max_k + 1, n)
    ranked: list[dict[int, tuple[int, float]]] = []
    for self_id in range(n):
        row = sims[self_id]
        # 与 faiss 一致：按分数降序，平分时取较小下标（argsort 稳定 + 负号）
        order = np.lexsort((np.arange(n), -row))[:take]
        current: dict[int, tuple[int, float]] = {}
        rank = 0
        for other in order:
            other = int(other)
            if other == self_id:
                continue
            rank += 1
            if rank > max_k:
                break
            current[other] = (rank, float(row[other]))
        ranked.append(current)
    result: list[tuple[int, int, int, int, float]] = []
    for left, values in enumerate(ranked):
        for right, (left_rank, score) in values.items():
            if right <= left or left not in ranked[right]:
                continue
            right_rank, reverse_score = ranked[right][left]
            result.append((left, right, left_rank, right_rank, (score + reverse_score) / 2.0))
    return result


def _build_relation_store() -> dict:
    """构建 discovery graph 并落盘成上游 load_adjacency 认得的 jsonl。

    schema 边：同 scope 同 session 内 sequence 相邻 → consecutive_turn（口径 6）。
    语义边：同 scope 内 mutual top-k=8（Eq.4）。**跨 scope 不连边**——LoCoMo 每个
      conversation 是独立记忆库，跨库连边等于泄漏（smoke 第 8 步测的就是这条）。
    """
    records = _load_records()
    vecs = _load_vecs()
    edges: dict[tuple[str, str], dict] = {}

    def add_explicit(left: str, right: str, relation: str) -> None:
        if left == right:
            return
        key = tuple(sorted((left, right)))
        row = edges.setdefault(key, {"left": key[0], "right": key[1], "explicit_relations": []})
        if relation not in row["explicit_relations"]:
            row["explicit_relations"].append(relation)

    # —— schema 边：consecutive_turn（对齐上游 explicit_edges 的 by_session 分支）——
    by_session: dict[tuple[str, str], list[dict]] = {}
    for r in records:
        by_session.setdefault((str(r.get("scope_id") or ""), str(r["session_id"])), []).append(r)
    for rows in by_session.values():
        ordered = sorted(rows, key=lambda r: (int(r.get("sequence", 0)), str(r["memory_id"])))
        for left, right in zip(ordered, ordered[1:]):
            add_explicit(str(left["memory_id"]), str(right["memory_id"]), "consecutive_turn")

    # —— 语义边：scope 内 mutual top-k ——
    n_semantic = 0
    if vecs is not None and len(vecs) == len(records):
        by_scope: dict[str, list[int]] = {}
        for i, r in enumerate(records):
            by_scope.setdefault(str(r.get("scope_id") or ""), []).append(i)
        for idxs in by_scope.values():
            sub = vecs[idxs]
            for li, ri, lrank, rrank, sim in _mutual_neighbors(sub, SEMANTIC_K):
                left, right = str(records[idxs[li]]["memory_id"]), str(records[idxs[ri]]["memory_id"])
                key = tuple(sorted((left, right)))
                row = edges.setdefault(key, {"left": key[0], "right": key[1], "explicit_relations": []})
                row["semantic_similarity"] = max(-1.0, min(1.0, sim))
                row["semantic_rank_left"] = lrank if left == key[0] else rrank
                row["semantic_rank_right"] = rrank if right == key[1] else lrank
                n_semantic += 1

    rows_out = []
    n_explicit = 0
    for key in sorted(edges):
        row = edges[key]
        present = bool(row.get("explicit_relations"))
        n_explicit += 1 if present else 0
        row["explicit_similarity"] = EXPLICIT_SIMILARITY if present else None
        row["explicit_cost"] = -math.log(EXPLICIT_SIMILARITY) if present else None
        sim = row.get("semantic_similarity")
        row["semantic_cost"] = -math.log(max(float(sim), 1e-6)) if sim is not None and float(sim) > 0 else None
        rows_out.append(row)
    _REL_FILE.parent.mkdir(parents=True, exist_ok=True)
    _REL_FILE.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows_out))
    meta = {"n_memories": len(records), "n_edges": len(rows_out),
            "n_explicit_edges": n_explicit, "n_semantic_edges": n_semantic,
            "semantic_k": SEMANTIC_K, "same_round": False}
    _REL_META.write_text(json.dumps(meta, ensure_ascii=False))
    return meta


def _adjacency() -> dict:
    """discovery graph 邻接表；relation store 缺失时惰性构建（语义边需全库向量）。"""
    global _adj_cache
    if _adj_cache is not None:
        return _adj_cache
    if not _REL_FILE.exists() or not _REL_META.exists():
        _build_relation_store()
    # mode="full"：explicit ∪ semantic（Eq.4 的 E_schema ∪ E_sem）
    _adj_cache = load_adjacency(_REL_FILE, "full", SEMANTIC_K)
    return _adj_cache


# ═══ B2 CUE/RECALL：多视角检索（Eq.3，口径 7 下退化为单视角）═══

def _snippet(record: dict) -> str:
    return str(record.get("content", ""))[:SNIPPET_CHARS]


def _envelope_for(mid: str, by_id: dict, prizes: dict) -> dict:
    r = by_id[mid]
    return make_envelope(
        memory_id=mid,
        text=r["content"],
        session_id=r["session_id"],
        turn_range=[r["turn_index"], r["turn_index"]],
        timestamp=r.get("timestamp"),
        score=round(float(prizes[mid]), 4),
        raw_format="graphmemix_forest_node",
    )


def _source_priors(query: str, keep: list[int], records: list[dict], vecs: np.ndarray) -> dict:
    qv_list, n_tok = _embed([query])
    _stats.add_tokens("retrieve", n_tok)
    qv = np.array(qv_list[0], dtype=np.float32)
    sub = vecs[keep]
    a_n = sub / np.clip(np.linalg.norm(sub, axis=1, keepdims=True), 1e-12, None)
    sims = a_n @ (qv / np.linalg.norm(qv))
    order = sorted(range(len(sims)), key=lambda i: (-sims[i], i))[:SOURCE_TOP_K]
    return {
        "retrieval_ids": [str(records[keep[i]]["memory_id"]) for i in order],
        "retrieval_scores": [float(sims[i]) for i in order],
    }


# ═══ B4 APPRAISE：两次 listwise 验证 ═══

def _node_verifier(query: str, candidates: list[str], by_id: dict, scores: dict,
                   floor: float) -> tuple[dict, bool]:
    """Eq.6 直接节点效用。payload 逐字段对齐上游 score_graphmemix_verifier.py:283-318。"""
    aliases = {mid: f"C{i:02d}" for i, mid in enumerate(candidates)}
    reverse = {v: k for k, v in aliases.items()}
    payload = {
        "question": query,
        "candidates": [{
            "id": aliases[mid],
            "modalities": ["text"],
            "date": str(by_id[mid].get("timestamp") or "")[:10],
            "retrieval_score": round(float(scores.get(mid, floor)), 4),
            "snippet": _snippet(by_id[mid]),
        } for mid in candidates],
        "instructions": [
            "Score final or necessary supporting evidence for the question.",
            "Use only candidate IDs provided.",
            "Be recall-oriented for list/count/multi-hop tasks.",
            "Omit candidates with score 0.",
            "Do not apply benchmark-specific rules.",
            "Return only candidate id and numeric score. Never return reasons or explanations.",
            "Return strict JSON only.",
        ],
        "output_schema": {"selected": [{"id": "candidate id", "score": "0-5 evidence usefulness"}]},
    }
    parsed, tokens = _llm_json([
        {"role": "system", "content": "You verify personal-memory evidence candidates. Return strict JSON only."},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ], "node")
    _stats.add_tokens("internal_llm", tokens)
    failed = parsed is None
    if failed:
        _probe["node_failed"] += 1
    out: dict[str, float] = {}
    for row in (parsed or {}).get("selected", []) or []:
        if not isinstance(row, dict):
            continue
        mid = reverse.get(str(row.get("id", "")).strip())
        if mid is None:
            continue
        try:
            value = max(0.0, min(5.0, float(row.get("score", 0))))
        except (TypeError, ValueError):
            continue
        if value > 0:            # 与上游一致（score_graphmemix_verifier.py:346 只收正分）
            out[mid] = value
    return out, failed


def _ecv(query: str, candidates: list[str], anchors: list[str], by_id: dict,
         adjacency: dict) -> tuple[dict, bool]:
    """Eq.7-9 锚点条件关系验证。只判 schema 边（语义边不参与，论文 §3.4）。"""
    aliases = {mid: f"C{i:02d}" for i, mid in enumerate(candidates)}
    reverse = {v: k for k, v in aliases.items()}
    anchor_set = set(anchors)

    # eligible：候选与锚点之间在 relation store 里已有 schema 边。
    # ★ 2026-09-13 修（fable 审查 F2）：锚点自身也是候选。论文 Eq.7 的候选域是整个 C_q，
    # 上游只排除自环（anchor == mid）。此前把锚点整体排除在候选外，导致锚点之间那些
    # 置信度最高的相邻轮关系从未被验证，森林比论文该有的样子更稀疏。
    eligible: dict[str, list[str]] = {}
    for mid in candidates:
        opts = [a for a, _sim, rel in adjacency.get(mid, [])
                if a in anchor_set and rel == "explicit" and a != mid]
        if opts:
            eligible[mid] = opts
    _probe["eligible_edge_pairs"].append(sum(len(v) for v in eligible.values()))
    if not eligible:
        return {}, False          # 没有可判的边不是失败

    payload = {
        "question": query,
        "task": "Assess conditional evidence-chain value for schema-linked candidates.",
        "definitions": {
            "incremental_support": (
                "0-5 NEW answer-relevant information added by this candidate when the chosen "
                "anchor is already known; relevance or adjacency alone is not enough."
            ),
            "best_anchor_id": "One ID from eligible_anchor_relations, or null.",
            "role": ", ".join(ALL_ROLES) + ".",
        },
        "anchor_evidence": [{
            "id": aliases[a],
            "date": str(by_id[a].get("timestamp") or "")[:10],
            "snippet": _snippet(by_id[a]),
        } for a in anchors],
        "anchor_selection": "atomic",
        "candidates": [{
            "id": aliases[mid],
            "date": str(by_id[mid].get("timestamp") or "")[:10],
            "snippet": _snippet(by_id[mid]),
            "eligible_anchor_relations": [
                {"anchor_id": aliases[a], "relations": ["consecutive_turn"]} for a in opts
            ],
        } for mid, opts in eligible.items()],
        "instructions": [
            "Return one row for every listed candidate and use only provided IDs.",
            "Set direct_support to 0; this edge-only setting reuses the locked node verifier.",
            "Choose an anchor only from that candidate's eligible_anchor_relations.",
            "Use new_fact/clarification/corroboration only when the candidate adds useful information beyond the anchor.",
            "Use redundant when it merely repeats the anchor and conflict for incompatible or stale evidence.",
            "Return strict JSON only without explanations.",
        ],
        "output_schema": {"rows": [{
            "id": "candidate id", "direct_support": "always 0 in this edge-only setting",
            "best_anchor_id": "anchor id or null",
            "incremental_support": "0-5", "role": "|".join(ALL_ROLES),
        }]},
    }
    parsed, tokens = _llm_json([
        {"role": "system", "content": "You assess conditional evidence chains. Return strict JSON only."},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ], "ecv")
    _stats.add_tokens("internal_llm", tokens)
    failed = parsed is None
    if failed:
        _probe["ecv_failed"] += 1

    edge_scores: dict[str, dict] = {}
    rows = (parsed or {}).get("rows", []) or []
    _probe["ecv_rows_returned"] += len(rows)
    for row in rows:
        if not isinstance(row, dict):
            _probe["ecv_rows_dropped"] += 1
            continue
        mid = reverse.get(str(row.get("id", "")).strip())
        anchor = reverse.get(str(row.get("best_anchor_id", "")).strip())
        role = str(row.get("role", "")).strip()
        if role not in ALL_ROLES:      # 上游同款规整（tests/test_score_graphmemix_ecv.py:63）
            role = "irrelevant"
        _probe["ecv_roles"][role] += 1
        if mid is None or anchor is None or anchor not in set(eligible.get(mid, [])):
            _probe["ecv_rows_dropped"] += 1
            continue
        try:
            inc = max(0.0, min(5.0, float(row.get("incremental_support", 0))))
        except (TypeError, ValueError):
            _probe["ecv_rows_dropped"] += 1
            continue
        edge_scores[f"{anchor}|{mid}"] = {
            "left": anchor, "right": mid, "incremental_support": inc, "role": role,
        }
    return edge_scores, failed


# ═══ B5 SELECT：森林优化（Eq.11-13）═══

def _conditioned_adjacency(edge_scores: dict) -> dict:
    """ECV 可信图（对齐上游 evaluate_graphmemix_ecv.py:31-45）。"""
    result: dict[str, list[tuple[str, float, str]]] = {}
    for edge in edge_scores.values():
        if edge["role"] not in POSITIVE_ROLES or edge["incremental_support"] <= 0:
            continue
        sim = EXPLICIT_SIMILARITY * (edge["incremental_support"] / 5.0) ** EDGE_POWER
        result.setdefault(edge["left"], []).append((edge["right"], sim, "ecv_explicit"))
        result.setdefault(edge["right"], []).append((edge["left"], sim, "ecv_explicit"))
    return result


def _exact_prune(ordered: list[str], prizes: dict, edges: list[tuple], k_budget: int) -> tuple[list[str], dict]:
    """Eq.13 变基数精修，按连通分量分解后逐块调用上游 exact_subset（口径 5）。"""
    benefit_edges = [
        e for e in edges
        if PRUNING_ROOT_COST - EDGE_WEIGHT * -math.log(max(e[0], 1e-6)) > 0
        and e[1] in prizes and e[2] in prizes
    ]
    parent = {mid: mid for mid in ordered}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for _sim, left, right, _role in benefit_edges:
        if left in parent and right in parent:
            parent[find(left)] = find(right)
    blocks: dict[str, list[str]] = {}
    for mid in ordered:
        blocks.setdefault(find(mid), []).append(mid)

    kept: set[str] = set()
    truncated = 0
    solutions: list[tuple[float, list[str]]] = []
    for members in blocks.values():
        if len(members) > EXACT_PRUNE_MAX_NODES:
            members = sorted(members, key=lambda m: (-prizes[m], ordered.index(m)))[:EXACT_PRUNE_MAX_NODES]
            truncated += 1
        member_set = set(members)
        block_edges = [e for e in benefit_edges if e[1] in member_set and e[2] in member_set]
        sub_kept, diag = exact_subset(
            members, prizes, block_edges,
            edge_weight=EDGE_WEIGHT, root_cost=PRUNING_ROOT_COST, node_cost=PRUNING_NODE_COST,
        )
        solutions.append((float(diag.get("objective_value", 0.0)), list(sub_kept)))

    # ★ 2026-09-13 修（fable 审查 F1）：分量分解只对目标函数成立，对「非空」这个约束不成立。
    # 上游枚举的是「整个提案集的全部非空子集」，允许某些分量一个节点都不选；
    # 逐块调用会把「非空」复制到每一块，于是目标值为负的块（典型是效用低于 root_cost 的
    # 孤立节点）永远剔不掉。这里显式补回那次比较：块的最优非空解若目标值不为正，
    # 不选整块更优；全部块都不为正时，为保住全局非空保留目标值最高的一块。
    positive = [(obj, ks) for obj, ks in solutions if obj > 0]
    if positive:
        for _obj, ks in positive:
            kept.update(ks)
    elif solutions:
        kept.update(max(solutions, key=lambda row: row[0])[1])
    if truncated:
        _probe["exact_prune_truncated"] += truncated
    result = [mid for mid in ordered if mid in kept][:k_budget]
    return result, {"blocks": len(blocks), "truncated_blocks": truncated,
                    "dropped_blocks": len(solutions) - len(positive)}


# ═══ 六工具 ═══

@mcp.tool
def add_conversation(session_id: str, turns: list[dict], scope: dict, metadata: dict | None = None) -> dict:
    """灌入一段会话。turn 级 canonical memory + 多模态编码器编码（口径 7 下单视角）。

    写入侧不调生成式 LLM（论文 §4.1 / 上游 ingest 路径同）；关系图在首次 retrieve 前惰性构建
    ——语义 mutual-kNN 需要全库向量，逐 session 增量重建等于重复计算。
    """
    t0 = time.perf_counter()
    texts = [t.get("content", "") for t in turns]
    if not texts:
        return {"accepted_turns": 0, "native_notes": "graphmemix: 空会话"}
    vecs, n_tok = _embed(texts)
    _stats.add_tokens("ingest", n_tok)

    records = _load_records()
    base_seq = len(records)
    new_records = [{
        "memory_id": f"{session_id}#{i}",
        "session_id": session_id,
        "turn_index": i,
        "sequence": base_seq + i,     # 上游 explicit_edges 用 sequence 判相邻
        "content": t.get("content", ""),
        "timestamp": t.get("timestamp"),
        "scope_id": scope.get("id"),
    } for i, t in enumerate(turns)]
    _save_records(records + new_records)

    old = _load_vecs()
    merged = np.array(vecs, dtype=np.float32) if old is None else np.vstack([old, np.array(vecs, dtype=np.float32)])
    _save_vecs(merged)
    assert len(_load_records()) == len(merged), f"records 与 vectors 行数漂移: {len(_load_records())} vs {len(merged)}"
    _mark_relations_dirty()          # 新记忆改变 mutual-kNN 拓扑，关系图作废

    _stats.n_sessions = len({r["session_id"] for r in _load_records()})
    return {
        "accepted_turns": len(turns),
        "native_notes": (
            f"graphmemix: canonical memory × {len(turns)}（单视角，MULTIVIEW_DEGENERATE），"
            f"embed {n_tok} tok，ingest 零生成式 LLM，{time.perf_counter() - t0:.2f}s"
        ),
    }


@mcp.tool
def retrieve(query: str, query_mode: str = "fixed", top_k: int = 5, filter: dict | None = None) -> dict:
    """查询到来后求解一次证据森林（论文 Eq.1 的 Π）。K = top_k（口径 4）。

    ⚠️ 本路径有 2 次 listwise LLM 调用且读记忆正文 → active retrieval 面（口径 10）。
    """
    t0 = time.perf_counter()
    notes: list[str] = ["MULTIVIEW_DEGENERATE", "SAME_ROUND_UNAVAILABLE", "ORDER=forest_bfs"]
    records = _load_records()
    vecs = _load_vecs()
    if not records or vecs is None:
        return {"results": [], "query_used": query, "query_mode": query_mode,
                "latency_ms": int((time.perf_counter() - t0) * 1000), "native_notes": "EMPTY"}

    scope_id = (filter or {}).get("scope_id")
    keep = [i for i, r in enumerate(records) if r.get("scope_id") == scope_id] if scope_id else list(range(len(records)))
    if filter and any(k in filter for k in ("before_timestamp", "session_ids")):
        notes.append("FILTER_IGNORED")
    if not keep:
        return {"results": [], "query_used": query, "query_mode": query_mode,
                "latency_ms": int((time.perf_counter() - t0) * 1000), "native_notes": "EMPTY_SCOPE"}

    by_id = {str(r["memory_id"]): r for r in records}
    cache_key = hashlib.sha256(
        f"{query}|{query_mode}|{top_k}|{scope_id}|{_corpus_fingerprint()}".encode()
    ).hexdigest()
    if _CACHE_ENABLED and cache_key in _query_cache:
        hit_ids, hit_prizes, hit_notes = _query_cache[cache_key]
        return {
            "results": [_envelope_for(mid, by_id, hit_prizes) for mid in hit_ids],
            "query_used": query, "query_mode": query_mode,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "native_notes": "; ".join(hit_notes + ["CACHE_HIT"]),
        }
    # 关系图惰性构建放在缓存判定之后：命中时用不到邻接表，没必要为它重建
    adjacency = _adjacency()

    # ① 多视角检索 → 种子（Eq.3）
    prior = _source_priors(query, keep, records, vecs)
    scores = {mid: s for mid, s in zip(prior["retrieval_ids"], prior["retrieval_scores"])}
    floor = min(prior["retrieval_scores"]) - 0.01

    # ② 候选图发现（Eq.4-5，上游原版）
    allowed = {str(records[i]["memory_id"]) for i in keep}
    scoped_adj = {
        mid: [(o, s, rel) for o, s, rel in nbrs if o in allowed]
        for mid, nbrs in adjacency.items() if mid in allowed
    }
    candidates = candidate_pool(prior, scoped_adj, source_top_l=SOURCE_TOP_L, candidate_limit=CANDIDATE_LIMIT)
    candidates = [c for c in candidates if c in by_id]
    _probe["candidate_pool_size"].append(len(candidates))
    if not candidates:
        return {"results": [], "query_used": query, "query_mode": query_mode,
                "latency_ms": int((time.perf_counter() - t0) * 1000), "native_notes": "; ".join(notes + ["NO_CANDIDATE"])}

    # ③ 两次 listwise 验证，真并行（口径 9）
    anchors = [c for c in candidates[:ANCHOR_COUNT]]
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_node = pool.submit(_node_verifier, query, candidates, by_id, scores, floor)
        f_ecv = pool.submit(_ecv, query, candidates, anchors, by_id, scoped_adj)
        verifier_scores, node_failed = f_node.result()
        edge_scores, ecv_failed = f_ecv.result()
    _probe["verifier_scored"].append(len(verifier_scores))
    # 逐题上报验证失败：不标就无法从证据里区分“机制判定无关”与“验证根本没跑成”。
    # ★ 2026-09-13 修（fable 审查 MINOR）：改用调用结果的返回值判定。
    # 原先靠全局计数器前后比较，runner 并发 16 路 retrieve 时会把别的题的失败错标到本题。
    if node_failed:
        notes.append("NODE_VERIFIER_FAILED")
    if ecv_failed:
        notes.append("ECV_FAILED")

    # ④ 节点效用（论文 Eq.14/15，口径 8）
    prizes = {
        mid: 1.0 / (1.0 + math.exp(-(PRIZE_A * scores.get(mid, floor) + PRIZE_B * verifier_scores.get(mid, 0.0) + PRIZE_C)))
        for mid in candidates
    }

    # ⑤ 1-swap + Kruskal 定 K 节点提案（Eq.11-12，上游原版）
    trusted = _conditioned_adjacency(edge_scores)
    _probe["trusted_edges"].append(sum(len(v) for v in trusted.values()) // 2)
    ordered, diag = solve_forest_greedy(
        candidates, prizes, trusted,
        k=min(top_k, len(candidates)), edge_weight=EDGE_WEIGHT, root_cost=PROPOSAL_ROOT_COST,
    )
    _probe["select_k"].append(len(ordered))
    _probe["components"].append(int(diag.get("components", 0)))
    _probe["swap_iterations"].append(int(diag.get("local_search_iterations", 0)))
    if int(diag.get("chosen_edges", 0)) == 0:
        # 可信图一条边都没留下来：森林退化成独立点集，此时 Eq.11 等价于按 p_i 取 top-K。
        # 逐题上报，否则无法在跑分后区分“森林优化有效”和“机制根本没被激活”。
        _probe["forest_degenerate"] += 1
        notes.append("FOREST_DEGENERATE")

    # ⑥ 变基数精修（Eq.13，上游原版 + 分量分解）
    if _PRUNE_ENABLED and ordered:
        edges = positive_edges({"edge_scores": edge_scores}, set(ordered), power=EDGE_POWER)
        ordered, prune_diag = _exact_prune(ordered, prizes, edges, top_k)
        if prune_diag["truncated_blocks"]:
            notes.append("EXACT_PRUNE_TRUNCATED")
    else:
        notes.append("PRUNE_DISABLED")
    _probe["prune_kept"].append(len(ordered))
    _probe["retrieve_calls"] += 1
    flat = sorted(prizes.values())
    _probe["prize_min"] = round(flat[0], 4)
    _probe["prize_median"] = round(flat[len(flat) // 2], 4)
    _probe["prize_max"] = round(flat[-1], 4)

    # ⑦ 证据序列化（Appendix A.5：分量根优先 + 分量内 BFS，顺序即机制）
    notes.append(f"K={top_k}; selected={len(ordered)}; candidates={len(candidates)}")
    if len(ordered) < top_k:
        notes.append("VARIABLE_CARDINALITY")     # 精修主动少给，是机制不是失败
    results = [_envelope_for(mid, by_id, prizes) for mid in ordered]
    if _CACHE_ENABLED:
        if len(_query_cache) >= _CACHE_LIMIT:
            _query_cache.pop(next(iter(_query_cache)))
        _query_cache[cache_key] = (list(ordered), {m: prizes[m] for m in ordered}, list(notes))
    return {
        "results": results,
        "query_used": query,
        "query_mode": query_mode,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
        "native_notes": "; ".join(notes),
    }


@mcp.tool
def reset() -> dict:
    """清空全部状态（memories / vectors / relation store）。幂等。"""
    before = _load_records()
    cleared = {"memories": len(before), "sessions": len({r["session_id"] for r in before})}
    _state.hard_reset_dir()
    _mark_relations_dirty()
    _reset_probes()
    _stats.mark_reset()
    _stats.n_sessions = 0
    return {"ok": True, "cleared": cleared}


@mcp.tool
def stats() -> dict:
    """用量与观测项。prize_probes 是口径 3 的必看项（换嵌入后 p_i 尺度是否漂）。"""
    records = _load_records()
    # n_sessions 从磁盘算：server 是长驻 stdio 进程，但 restore 后进程内计数会与落盘状态不符
    _stats.n_sessions = len({r["session_id"] for r in records})
    d = _stats.to_dict(n_memories=len(records))
    meta = json.loads(_REL_META.read_text()) if _REL_META.exists() else None

    def avg(xs: list) -> float | None:
        return round(sum(xs) / len(xs), 2) if xs else None

    d["thinking"] = _THINKING
    d["relation_store"] = meta
    d["prize_probes"] = {
        "retrieve_calls": _probe["retrieve_calls"],
        "prize_min": _probe["prize_min"], "prize_median": _probe["prize_median"],
        "prize_max": _probe["prize_max"],
        "avg_candidates": avg(_probe["candidate_pool_size"]),
        "avg_eligible_edge_pairs": avg(_probe["eligible_edge_pairs"]),
        "avg_trusted_edges": avg(_probe["trusted_edges"]),
        "avg_select_k": avg(_probe["select_k"]),
        "avg_prune_kept": avg(_probe["prune_kept"]),
        "avg_forest_components": avg(_probe["components"]),
        "avg_verifier_scored": avg(_probe["verifier_scored"]),
        "avg_swap_iterations": avg(_probe["swap_iterations"]),
        "forest_degenerate_queries": _probe["forest_degenerate"],
        "ecv_rows_returned": _probe["ecv_rows_returned"],
        "ecv_rows_dropped": _probe["ecv_rows_dropped"],
        "ecv_roles": dict(_probe["ecv_roles"]),
        "llm_parse_failures": _probe["llm_parse_failures"],
        "llm_transient_retries": _probe["llm_transient_retries"],
        "node_verifier_failed": _probe["node_failed"], "ecv_failed": _probe["ecv_failed"],
        "exact_prune_truncated": _probe["exact_prune_truncated"],
        "prune_enabled": _PRUNE_ENABLED,
        "cache_enabled": _CACHE_ENABLED, "cached_queries": len(_query_cache),
    }
    d["paper_hyperparams"] = {
        "source_top_l": SOURCE_TOP_L, "candidate_limit": CANDIDATE_LIMIT,
        "semantic_k": SEMANTIC_K, "anchor_count": ANCHOR_COUNT,
        "prize_formula": f"sigmoid({PRIZE_A:.3f}*s + {PRIZE_B:.3f}*v {PRIZE_C:+.3f})",
        "edge_weight": EDGE_WEIGHT, "proposal_root_cost": PROPOSAL_ROOT_COST,
        "pruning_root_cost": PRUNING_ROOT_COST,
    }
    return d


@mcp.tool
def snapshot(tag: str) -> dict:
    r = _state.snapshot(tag)
    _stats.snapshots = _state.tags()
    return r


@mcp.tool
def restore(tag: str) -> dict:
    global _adj_cache, _corpus_sha
    r = _state.restore(tag)
    _adj_cache = None                 # 目录被整体换掉，进程内邻接缓存必须失效
    _corpus_sha = None                # 查询缓存不清：指纹相同即库内容相同，命中正是幂等性
    _stats.snapshots = _state.tags()
    if not r.get("ok"):
        r["error"] = r.get("error", "SNAPSHOT_FAILED")
    return r


if __name__ == "__main__":
    mcp.run()  # stdio

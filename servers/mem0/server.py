# mem0：A档首个真实系统封装（interface-spec 契约）
# 公平性配置（spec §7）：LLM 全部走 MEMBENCH_* 环境变量，temperature=0。
# 存储落 MEMBENCH_STATE_DIR（chroma 本地目录），snapshot/restore = 目录拷贝 + 重建实例。
# env_required: MEMBENCH_LLM_API_KEY / MEMBENCH_LLM_BASE_URL / MEMBENCH_LLM_MODEL
# 可选: MEMBENCH_EMBED_MODEL（默认 text-embedding-3-small）、MEMBENCH_EMBED_BASE_URL / MEMBENCH_EMBED_API_KEY
#
# ── 检索参数显式化（2026-08-29）───────────────────────────────────────────────
# mem0 2.0.18 的 Memory.search 默认值是 top_k=20 / threshold=0.1 / rerank=False
# （memory/main.py:1383-1386）。之前本封装只传 top_k，threshold 与 rerank 靠包默认值
# 静默生效——而这两个默认值在 v2→v3 已经变过一次。评测可复现性要求"跑的时候到底用了
# 什么参数"可被审查，因此现在全部显式传入，且实际生效值写进 trace / native_notes / stats。
#   MEMBENCH_MEM0_THRESHOLD  默认 0.1（= 上游默认，保持与 locomo-r1 既有 run 语义一致）
#   MEMBENCH_MEM0_RERANK     默认 0（上游默认 False；且未配 reranker 时传 True 也是空操作）
#
# ── 三通道可观测（2026-08-29）─────────────────────────────────────────────────
# v3 检索 = semantic + BM25 + entity matching 三通道加权（memory/main.py:1628-1731）。
# 上游对不可用通道做 "graceful degradation"，且 BM25 是 **silently disabled**。本封装
# 用两层证据把通道状态钉死，不靠猜：
#   1) 启动期能力探针：向量库是否真的覆写 keyword_search（对比 VectorStoreBase）、
#      spaCy 与 en_core_web_sm 是否可用、entity 集合是否已建库。
#   2) 每次 retrieve 的运行期效果：search(explain=True) 返回的 score_details 里
#      max_possible_score 是自适应分母（utils/scoring.py:97-101）——
#      1.0=仅语义 / 2.0=+BM25 / 1.5=+entity / 2.5=三通道全开，这是通道是否真的
#      参与打分的**直接运行时信号**。explain 只追加 score_details，不改变排序。

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# MCP stdio 要求 stdout 纯净：chromadb 的 warning（"The 'chroma' vector store does not support
# keyword search..."）用裸 print/root handler 漏到 stdout，污染 JSON-RPC（2026-08-22 S4 第一批实测）
import builtins
import logging

# 根治：任何显式传 sys.stdout 的 StreamHandler 一律改道 stderr（logging 自身 lastResort 用无参构造不受影响）
_orig_sh_init = logging.StreamHandler.__init__


def _safe_sh_init(self, stream=None):
    if stream is sys.stdout:
        stream = sys.stderr
    _orig_sh_init(self, stream)


logging.StreamHandler.__init__ = _safe_sh_init

logging.basicConfig(stream=sys.stderr, level=logging.WARNING, force=True)
_orig_print = builtins.print


def _print_stderr(*args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    _orig_print(*args, **kwargs)


builtins.print = _print_stderr

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

# 关闭遥测：PostHog 配额限流会造成假死，评测机也不应外发数据
os.environ.setdefault("MEM0_TELEMETRY", "False")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "FALSE")

from fastmcp import FastMCP

from servers.common.base import BaseState
from servers.common.envelope import make_envelope
from servers.common.stats import StatsTracker

mcp = FastMCP("mem0")

_state = BaseState("mem0")
_stats = StatsTracker()
_SCOPE_FILE = _state.state_dir / "scopes.json"
_MEMORY = None  # 惰性单例：restore 后必须重建


# ---------------------------------------------------------------------------
# 可审查 trace：每行一个 JSON，stderr + 落盘双写
# ---------------------------------------------------------------------------
# 落盘位置优先级：MEMBENCH_TRACE_DIR > runs/<MEMBENCH_RUN_ID>/mcp_trace > runs/_mcp_trace
# 选 runs/ 而不是 native_notes/state_dir 的理由：
#   - state_dir 会被 reset() 清空、被 snapshot() 递归拷贝，trace 放那里会自毁 + 污染快照；
#   - native_notes 是单行字符串且逐条进 evidence，装不下 token / 参数 / 分通道明细；
#   - runs/ 是既有的 append-only 产物目录，与 evidence/system_stats 同级，事后 grep 最顺手。
# 三者不互斥：明细进 jsonl，逐题结论进 native_notes，累计量进 stats()。
# 未设 RUN_ID 时落在 runs/_mcp_trace（下划线开头，不会和真实 --run-id 撞名导致
# Run.__init__ 报"run 目录已存在"）。
_RUN_ID = os.environ.get("MEMBENCH_RUN_ID")
_TRACE_DIR = Path(
    os.environ.get("MEMBENCH_TRACE_DIR")
    or (REPO_ROOT / "runs" / _RUN_ID / "mcp_trace" if _RUN_ID else REPO_ROOT / "runs" / "_mcp_trace")
)
_TRACE_FILE = _TRACE_DIR / "mem0.jsonl"
_TRACE_STDERR = os.environ.get("MEMBENCH_TRACE_STDERR", "1") != "0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _trace(event: str, **fields) -> None:
    """结构化审计日志。绝不抛异常、绝不写 stdout（stdio MCP 的 stdout 只能是 JSON-RPC）。"""
    rec = {"ts": _now_iso(), "system": "mem0", "pid": os.getpid(), "event": event, **fields}
    try:
        line = json.dumps(rec, ensure_ascii=False, default=str)
    except Exception:  # 兜底：字段不可序列化也不能吞掉事件
        line = json.dumps({"ts": _now_iso(), "system": "mem0", "event": event, "trace_error": "unserializable"})
    if _TRACE_STDERR:
        _orig_print(f"[mem0-trace] {line}", file=sys.stderr, flush=True)
    try:
        _TRACE_DIR.mkdir(parents=True, exist_ok=True)
        with _TRACE_FILE.open("a") as f:
            f.write(line + "\n")
    except Exception as e:
        _orig_print(f"[mem0-trace] 落盘失败（已降级为仅 stderr）: {e}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# 内部 LLM / embedding 计量
# ---------------------------------------------------------------------------
# mem0 的 OpenAILLM.generate_response 只返回 message.content，usage 在它内部被丢弃
# （llms/openai.py:83）。但本封装本来就要 patch client.chat.completions.create 来钉
# thinking——在同一个切点上顺手把 response.usage 收下来，就能拿到真实 token，
# 无需侵入 mem0。计量器放模块级：restore/reset 会重建 Memory 实例，挂实例上会丢计数。
_METER = {
    "llm_calls": 0,
    "llm_errors": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "reasoning_tokens": 0,
    "total_tokens": 0,
    "usage_missing": 0,  # 服务端没回 usage 的次数——有它才知道 token 数是否可信
    "embed_calls": 0,
    "embed_tokens": 0,
    "embed_errors": 0,
}


def _meter_snapshot() -> dict:
    return dict(_METER)


def _meter_delta(before: dict) -> dict:
    return {k: _METER[k] - before.get(k, 0) for k in _METER}


def _collect_usage(usage) -> None:
    if usage is None:
        _METER["usage_missing"] += 1
        return
    get = (lambda k: getattr(usage, k, None)) if not isinstance(usage, dict) else usage.get
    _METER["prompt_tokens"] += get("prompt_tokens") or 0
    _METER["completion_tokens"] += get("completion_tokens") or 0
    _METER["total_tokens"] += get("total_tokens") or 0
    details = get("completion_tokens_details")
    if details is not None:
        rt = details.get("reasoning_tokens") if isinstance(details, dict) else getattr(details, "reasoning_tokens", None)
        _METER["reasoning_tokens"] += rt or 0


def _instrument_llm(memory) -> bool:
    """钉住推理深度 + 计量内部 LLM。MEMBENCH_THINKING ∈ low | enabled | disabled：
    - low: thinking enabled + reasoning_effort=low（实测 reasoning 压到 0，总 token -63%——快速出粗结论用）
    - enabled(默认): 服务端默认深度（glm-5.3 metadata: default_reasoning_level=max）
    - disabled: 关思考
    经 OpenAI SDK extra_body 注入，不侵入 mem0 内部；同一切点统计 calls/usage。"""
    mode = os.environ.get("MEMBENCH_THINKING", "enabled")
    try:
        create = memory.llm.client.chat.completions.create

        def create_with_thinking(**kwargs):
            extra = kwargs.setdefault("extra_body", {})
            extra["thinking"] = {"type": "disabled" if mode == "disabled" else "enabled"}
            if mode == "low":
                extra["reasoning_effort"] = "low"
            _METER["llm_calls"] += 1
            try:
                resp = create(**kwargs)
            except Exception:
                _METER["llm_errors"] += 1
                raise
            _collect_usage(getattr(resp, "usage", None))
            return resp

        memory.llm.client.chat.completions.create = create_with_thinking
        return True
    except Exception as e:
        _trace("instrument_llm_failed", error=str(e))
        return False  # 注入失败则退回服务端默认，不阻断启动（但已留痕，不再静默）


def _instrument_embedder(memory) -> bool:
    """embedding 调用计量：ingest 的向量化与 retrieve 的 query 向量化都走这里。"""
    try:
        create = memory.embedding_model.client.embeddings.create

        def create_counted(**kwargs):
            _METER["embed_calls"] += 1
            try:
                resp = create(**kwargs)
            except Exception:
                _METER["embed_errors"] += 1
                raise
            usage = getattr(resp, "usage", None)
            if usage is not None:
                _METER["embed_tokens"] += getattr(usage, "total_tokens", None) or getattr(usage, "prompt_tokens", None) or 0
            return resp

        memory.embedding_model.client.embeddings.create = create_counted
        return True
    except Exception as e:
        _trace("instrument_embedder_failed", error=str(e))
        return False


# ---------------------------------------------------------------------------
# 检索参数：全部显式，不吃包默认值
# ---------------------------------------------------------------------------
def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ[key])
    except (KeyError, ValueError):
        return default


def _env_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


# 上游 2.0.18 默认值，写死在这里作为"我们知道自己在覆盖什么"的锚点（memory/main.py:1383-1386）
UPSTREAM_SEARCH_DEFAULTS = {"top_k": 20, "threshold": 0.1, "rerank": False, "explain": False}


def _search_params(top_k: int) -> dict:
    """本次 retrieve 真正传给 mem0.search 的参数（不是代码默认值，是运行时生效值）。
    threshold 默认取 0.1 = 上游默认，保证与 locomo-r1 既有 run 的语义一致；
    要做阈值敏感性实验就设 MEMBENCH_MEM0_THRESHOLD=0（关闭过滤），改动会自动进 trace。"""
    return {
        "top_k": top_k,  # 契约要求全臂统一 5，由评测循环传入，本层不覆盖
        "threshold": _env_float("MEMBENCH_MEM0_THRESHOLD", 0.1),
        "rerank": _env_bool("MEMBENCH_MEM0_RERANK", False),
        # explain 只追加 score_details，不改排序（utils/scoring.py:118-129）。
        # 留 MEMBENCH_MEM0_EXPLAIN=0 旋钮不是为了平时关，而是为了能做"开/关结果是否一致"的 A/B 自证。
        "explain": _env_bool("MEMBENCH_MEM0_EXPLAIN", True),
    }


# ---------------------------------------------------------------------------
# 三通道能力探针（启动期一次，结果缓存）
# ---------------------------------------------------------------------------
_CHANNELS: dict | None = None


def _probe_spacy() -> tuple[bool, str]:
    """entity matching 与 BM25 lemmatize 都依赖 spaCy + en_core_web_sm。
    只做存在性检查，不触发 mem0 的自动下载（_ensure_model_available 会联网 download）。"""
    from importlib.util import find_spec

    if find_spec("spacy") is None:
        return False, "spacy_not_installed"  # 需 mem0ai[nlp]
    try:
        import spacy

        if not spacy.util.is_package("en_core_web_sm"):
            return False, "en_core_web_sm_missing"
        return True, "ok"
    except Exception as e:
        return False, f"spacy_import_error:{type(e).__name__}"


def _probe_channels(memory) -> dict:
    """启动期把三通道的**可用性**钉死。运行期是否真的贡献分数另看 score_details。
    每条通道给一个 ASCII 短码 code，便于 native_notes 携带与事后 grep。"""
    ch = {"semantic": {"enabled": True, "code": "ok", "detail": "vector_store.search 恒生效"}}

    # BM25：基类 keyword_search 默认 return None（vector_stores/base.py:68），
    # 未覆写的 store（chroma 就是）→ keyword_results is None → bm25_scores 恒空。
    try:
        from mem0.vector_stores.base import VectorStoreBase

        vs_cls = type(memory.vector_store)
        overridden = getattr(vs_cls, "keyword_search", None) is not getattr(VectorStoreBase, "keyword_search", None)
        ch["bm25"] = {
            "enabled": bool(overridden),
            "code": "ok" if overridden else "store_no_keyword_search",
            "vector_store": vs_cls.__name__,
            "detail": "store 覆写了 keyword_search" if overridden
            else "store 未覆写 keyword_search，基类返回 None → 通道恒空（上游称 graceful degradation，且是 silently disabled）",
        }
    except Exception as e:
        ch["bm25"] = {"enabled": None, "code": "probe_failed", "detail": str(e)}

    # entity matching：spaCy 依赖 + entity 集合是否已建库（entity 是 ingest 期抽取入库的，
    # 见 memory/main.py:1089 extract_entities_batch → Phase 7 批量 upsert；
    # 集合名 _entity_collection_name() = f"{collection}_entities"）
    spacy_ok, spacy_code = _probe_spacy()
    entity_store_ready, store_code, names = None, "probe_failed", []
    try:
        want = f"{memory.collection_name}_entities"
        client = getattr(memory.vector_store, "client", None)
        if client is not None and hasattr(client, "list_collections"):
            for c in client.list_collections():
                names.append(c if isinstance(c, str) else getattr(c, "name", str(c)))
        entity_store_ready = want in names
        store_code = "ok" if entity_store_ready else "entity_store_absent"
    except Exception as e:
        store_code = f"probe_failed:{type(e).__name__}"
    enabled = bool(spacy_ok and entity_store_ready)
    ch["entity"] = {
        "enabled": enabled,
        "code": "ok" if enabled else (spacy_code if not spacy_ok else store_code),
        "spacy_available": spacy_ok,
        "spacy_code": spacy_code,
        "entity_store_built": entity_store_ready,
        "collections_seen": names,
        "detail": "entity 需 ingest 期抽取入库；缺 spaCy 或缺 *_entities 集合时 boost 恒为 0",
    }

    # rerank 通道：未配 reranker 时 rerank=True 也是空操作（memory/main.py:1500）
    try:
        ch["reranker_configured"] = memory.reranker is not None
    except Exception:
        ch["reranker_configured"] = None
    return ch


def _channels() -> dict:
    return _CHANNELS or {}


def _channel_tag() -> str:
    """给 native_notes 用的紧凑通道标记，逐题落进 evidence/<arm>.jsonl。"""
    ch = _channels()
    if not ch:
        return "CHANNELS: unprobed"
    bits = []
    for name in ("semantic", "bm25", "entity"):
        c = ch.get(name) or {}
        bits.append(f"{name}=on" if c.get("enabled") else f"{name}=off:{c.get('code', 'unknown')}")
    return "CHANNELS: " + ",".join(bits)


def _channel_effect(res: list) -> dict:
    """从 score_details 反推**本次查询**各通道是否真的贡献了分数。
    max_possible_score 是 score_and_rank 的自适应分母（utils/scoring.py:97-101）：
    1.0 仅语义 / 2.0 语义+BM25 / 1.5 语义+entity / 2.5 三通道。"""
    details = [r.get("score_details") for r in res if isinstance(r.get("score_details"), dict)]
    if not details:
        return {"observed": False, "reason": "无 score_details（explain 未生效或结果为空）"}
    maxes = {d.get("max_possible_score") for d in details}
    return {
        "observed": True,
        "max_possible_score": sorted(x for x in maxes if x is not None),
        "n_bm25_nonzero": sum(1 for d in details if (d.get("bm25_score") or 0) > 0),
        "n_entity_nonzero": sum(1 for d in details if (d.get("entity_boost") or 0) > 0),
        "semantic_min": min((d.get("semantic_score") or 0) for d in details),
        "semantic_max": max((d.get("semantic_score") or 0) for d in details),
        "threshold_seen": next((d.get("threshold") for d in details), None),
    }


def _die_if_env_missing() -> None:
    missing = [k for k in ("MEMBENCH_LLM_API_KEY", "MEMBENCH_LLM_BASE_URL", "MEMBENCH_LLM_MODEL") if not os.environ.get(k)]
    if missing:
        # 用 RuntimeError 而非 SystemExit：让错误作为工具结果返回给客户端，不能无声杀死 server
        raise RuntimeError(f"缺少环境变量 {missing}——MCP stdio 子进程不继承父进程环境，须在 servers.yaml/客户端配置里显式传入（见 interface-spec §7）")


def _config() -> dict:
    chroma_path = _state.state_dir / "chroma"
    embed_base = os.environ.get("MEMBENCH_EMBED_BASE_URL") or os.environ["MEMBENCH_LLM_BASE_URL"]
    embed_key = os.environ.get("MEMBENCH_EMBED_API_KEY") or os.environ["MEMBENCH_LLM_API_KEY"]
    return {
        "llm": {
            "provider": "openai",
            "config": {
                "model": os.environ["MEMBENCH_LLM_MODEL"],
                "api_key": os.environ["MEMBENCH_LLM_API_KEY"],
                "openai_base_url": os.environ["MEMBENCH_LLM_BASE_URL"],
                "temperature": 0,
                # mem0 默认 max_tokens=2000（BaseLlmConfig），且其 _is_reasoning_model() 只按名字
                # 硬匹配 o1/o3/gpt-5 —— glm-5.3 不在名单里，会被当普通模型，2000 原样发出。
                # 思考与正式回复共用额度，MEMBENCH_THINKING 一旦调高就会重现 A-MEM 的空回复故障
                # （2026-08-30 定位）。取 128k 与其他 arm 对齐，当前 thinking=low 下行为不变、无需重灌。
                "max_tokens": int(os.environ.get("MEMBENCH_MAX_TOKENS", "128000")),
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": os.environ.get("MEMBENCH_EMBED_MODEL", "text-embedding-3-small"),
                "api_key": embed_key,
                "openai_base_url": embed_base,
            },
        },
        "vector_store": {
            "provider": "chroma",
            "config": {"path": str(chroma_path), "collection_name": "membench"},
        },
    }


def _mem():
    global _MEMORY, _CHANNELS
    if _MEMORY is None:
        _die_if_env_missing()
        import mem0
        from mem0 import Memory  # 惰性导入：环境就绪才加载

        t0 = time.perf_counter()
        _MEMORY = Memory.from_config(_config())
        llm_ok = _instrument_llm(_MEMORY)
        embed_ok = _instrument_embedder(_MEMORY)
        _CHANNELS = _probe_channels(_MEMORY)
        _trace(
            "boot",
            mem0_version=getattr(mem0, "__version__", "unknown"),
            state_dir=str(_state.state_dir),
            trace_file=str(_TRACE_FILE),
            llm={
                "model": os.environ.get("MEMBENCH_LLM_MODEL"),
                "base_url": os.environ.get("MEMBENCH_LLM_BASE_URL"),
                "temperature": 0,
                "thinking": os.environ.get("MEMBENCH_THINKING", "enabled"),
                "instrumented": llm_ok,
            },
            embedder={
                "model": os.environ.get("MEMBENCH_EMBED_MODEL", "text-embedding-3-small"),
                "instrumented": embed_ok,
            },
            search_params_effective=_search_params(5),
            upstream_search_defaults=UPSTREAM_SEARCH_DEFAULTS,
            channels=_CHANNELS,
            boot_ms=int((time.perf_counter() - t0) * 1000),
        )
    return _MEMORY


def _drop_memory() -> None:
    """弃实例 + 清 chroma 进程级缓存（2026-08-18 假数据事故根因：
    PersistentClient 按路径缓存 system，文件换了但缓存句柄读旧状态，
    reset 后 restore 会得到空 collection）。"""
    global _MEMORY, _CHANNELS
    if _MEMORY is not None:
        try:
            client = getattr(getattr(_MEMORY, "vector_store", None), "client", None)
            if client is not None and hasattr(type(client), "clear_system_cache"):
                type(client).clear_system_cache()
        except Exception:
            pass  # 清理失败不阻塞，最坏情况重建后读到旧状态
    _MEMORY = None
    _CHANNELS = None  # 通道探针含"entity 集合是否已建"，随存储变化，必须跟着实例作废


def _scopes() -> dict:
    if _SCOPE_FILE.exists():
        return json.loads(_SCOPE_FILE.read_text())
    return {"scope_ids": [], "sessions": []}


def _save_scopes(scope_id: str | None, session_id: str | None) -> None:
    s = _scopes()
    if scope_id and scope_id not in s["scope_ids"]:
        s["scope_ids"].append(scope_id)
    if session_id and session_id not in s["sessions"]:
        s["sessions"].append(session_id)
    _SCOPE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SCOPE_FILE.write_text(json.dumps(s, ensure_ascii=False))


# get_all 的 top_k 默认也是 20（memory/main.py:1259）——与 search 同一类隐式默认。
# 之前不传这个参数，stats().n_memories 每个 scope 最多只数到 20（实测：locomo_full
# 快照真实 1785 条，旧代码报 200）。现在显式传入大上限，并在饫和时显式报警。
GET_ALL_TOP_K = int(os.environ.get("MEMBENCH_MEM0_GET_ALL_TOP_K", "100000"))


def _n_memories() -> tuple[int, dict]:
    """返回（总数, 诊断）。诊断里记逐 scope 计数与饫和/失败情况，不把错误吹成 0。"""
    total, per_scope, saturated, errors = 0, {}, [], {}
    for uid in _scopes()["scope_ids"]:
        try:
            n = len(_extract(_mem().get_all(filters={"user_id": uid}, top_k=GET_ALL_TOP_K)))
            per_scope[uid] = n
            total += n
            if n >= GET_ALL_TOP_K:
                saturated.append(uid)  # 达到上限 = 数不全，必须暴露
        except Exception as e:
            errors[uid] = f"{type(e).__name__}: {e}"  # get_all 失败不阻塞 stats，但不静默
    return total, {"per_scope": per_scope, "top_k": GET_ALL_TOP_K,
                   "saturated_scopes": saturated, "errors": errors}


def _extract(res) -> list:
    """mem0 v2 返回兼容：{'results': [...]} 或直接 list。"""
    if isinstance(res, dict):
        return res.get("results", [])
    return res or []


@mcp.tool
def add_conversation(session_id: str, turns: list[dict], scope: dict, metadata: dict | None = None) -> dict:
    """灌入：整段会话一次 add（mem0 内部抽事实），metadata 记 session 溯源。"""
    t0 = time.perf_counter()
    meter0 = _meter_snapshot()
    messages = [{"role": t.get("role", "user"), "content": t.get("content", "")} for t in turns]
    first_ts = next((t.get("timestamp") for t in turns if t.get("timestamp")), None)
    # timestamp 是 mem0 Pro 功能，OSS SDK 不支持——塞进 metadata，envelope 从这里读回
    meta = {"session_id": session_id, **(metadata or {})}
    if first_ts:
        meta["timestamp"] = first_ts
    t_prep = time.perf_counter()
    try:
        res = _mem().add(messages, user_id=scope.get("id"), metadata=meta)
    except Exception as e:
        _trace("add_conversation_error", session_id=session_id, scope_id=scope.get("id"),
               error=f"{type(e).__name__}: {e}", meter_delta=_meter_delta(meter0),
               elapsed_ms=int((time.perf_counter() - t0) * 1000))
        raise
    t_add = time.perf_counter()

    # v3 是 single-pass ADD-only 抽取（官方 oss-v2-to-v3 迁移说明），不再有 UPDATE/DELETE 事件。
    # 这里如实统计返回的事件分布——若将来上游改回多事件，这个计数会立刻暴露差异。
    items = _extract(res)
    events: dict[str, int] = {}
    for it in items:
        ev = (it or {}).get("event") or "UNKNOWN"
        events[ev] = events.get(ev, 0) + 1

    _save_scopes(scope.get("id"), session_id)
    _stats.n_sessions = len(_scopes()["sessions"])
    delta = _meter_delta(meter0)
    # 之前 token 一律记 None（"未暴露"）；现在从 patch 过的 OpenAI client 上拿到了真实 usage。
    # 这里只累计**实测到的**量；若服务端有回合没回 usage（usage_missing>0），
    # stats() 会按契约 §5 把 tokens_used 降级为 null，实测部分仍保留在 mem0.meter 里。
    _stats.add_tokens("ingest", delta["total_tokens"])
    _stats.add_tokens("internal_llm", delta["total_tokens"])

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    _trace(
        "add_conversation",
        session_id=session_id,
        scope_id=scope.get("id"),
        n_turns=len(turns),
        n_chars=sum(len(m["content"]) for m in messages),
        metadata_keys=sorted(meta),
        n_facts=len(items),
        events=events,
        llm=delta["llm_calls"],
        llm_errors=delta["llm_errors"],
        tokens={
            "prompt": delta["prompt_tokens"],
            "completion": delta["completion_tokens"],
            "reasoning": delta["reasoning_tokens"],
            "total": delta["total_tokens"],
            "usage_missing": delta["usage_missing"],
        },
        embed_calls=delta["embed_calls"],
        embed_tokens=delta["embed_tokens"],
        timing_ms={
            "prep": int((t_prep - t0) * 1000),
            "mem0_add": int((t_add - t_prep) * 1000),
            "total": elapsed_ms,
        },
    )
    tok = f"{delta['total_tokens']} tok" + (f"（{delta['usage_missing']} 次未回 usage，为下界）" if delta["usage_missing"] else "")
    return {
        "accepted_turns": len(turns),
        "native_notes": (
            f"mem0 extracted {len(items)} facts {events or '{}'}；"
            f"内部 LLM {delta['llm_calls']} 次 / {tok}，embed {delta['embed_calls']} 次；耗时 {elapsed_ms}ms"
        ),
    }


@mcp.tool
def retrieve(query: str, query_mode: str = "fixed", top_k: int = 5, filter: dict | None = None) -> dict:
    """检索：mem0.search；turn_range 为 null（事实粒度，无轮次定位），粒度差异论文显式声明。"""
    t0 = time.perf_counter()
    meter0 = _meter_snapshot()
    notes = []
    scope_ids = _scopes()["scope_ids"]
    # scope_id 显式过滤（对话间隔离）：LoCoMo 200 条 conversation = 200 个独立 user，互不可见
    if filter and filter.get("scope_id"):
        uid = filter["scope_id"]
    else:
        if len(scope_ids) > 1:
            notes.append("MULTI_SCOPE: 未指定 filter.scope_id，仅检索首个 scope")
        uid = scope_ids[0] if scope_ids else "default"
    if filter and any(k for k in filter if k != "scope_id"):
        notes.append("FILTER_IGNORED: 仅支持 scope_id，其余过滤键忽略")

    params = _search_params(top_k)
    memory = _mem()  # 触发 boot trace + 通道探针（首次调用）
    t_pre = time.perf_counter()
    param_fallback = None
    try:
        res = _extract(memory.search(query, filters={"user_id": uid}, **params))
    except TypeError as e:
        # 上游签名变更时不静默降级：退回最小参数集，但把降级本身记成一等公民
        param_fallback = f"{type(e).__name__}: {e}"
        notes.append(f"PARAM_FALLBACK: search 拒绝显式参数（{e}），已退回 top_k-only")
        _trace("search_param_fallback", error=param_fallback, attempted=params)
        res = _extract(memory.search(query, top_k=top_k, filters={"user_id": uid}))
    t_search = time.perf_counter()

    effect = _channel_effect(res)
    results = [
        make_envelope(
            memory_id=r.get("id"),
            text=r.get("memory") or r.get("text", ""),
            session_id=(r.get("metadata") or {}).get("session_id"),
            turn_range=None,
            timestamp=(r.get("metadata") or {}).get("timestamp"),
            score=r.get("score"),
            raw_format="mem0_fact",
        )
        for r in res
    ]
    delta = _meter_delta(meter0)
    _stats.add_tokens("retrieve", delta["embed_tokens"])  # v3 检索不调 LLM，检索期 token = query 向量化
    latency_ms = int((time.perf_counter() - t0) * 1000)

    # 逐题可审查：参数生效值 + 通道状态 + 返回条数，直接落进 evidence/<arm>.jsonl 的 native_notes
    notes.append(
        f"PARAMS: top_k={params['top_k']},threshold={params['threshold']},"
        f"rerank={params['rerank']},explain={params['explain']}"
    )
    notes.append(_channel_tag())
    if effect.get("observed"):
        notes.append(
            f"EFFECT: max_possible={effect['max_possible_score']},"
            f"bm25_hits={effect['n_bm25_nonzero']},entity_hits={effect['n_entity_nonzero']}"
        )
    notes.append(f"RETURNED: {len(results)}/{top_k}")

    _trace(
        "retrieve",
        query=query[:200],
        query_mode=query_mode,
        scope_id=uid,
        filter=filter,
        params_effective=params,
        param_fallback=param_fallback,
        channels_capability=_channels(),
        channels_effect=effect,
        n_results=len(results),
        scores=[round(r["score"], 6) if isinstance(r.get("score"), float) else r.get("score") for r in results],
        truncated_below_top_k=len(results) < top_k,
        embed_calls=delta["embed_calls"],
        llm_calls=delta["llm_calls"],
        timing_ms={
            "pre": int((t_pre - t0) * 1000),
            "mem0_search": int((t_search - t_pre) * 1000),
            "render": int((time.perf_counter() - t_search) * 1000),
            "total": latency_ms,
        },
    )
    return {
        "results": results,
        "query_used": query,
        "query_mode": query_mode,
        "latency_ms": latency_ms,
        "native_notes": "; ".join(notes),
    }


@mcp.tool
def reset() -> dict:
    """mem0 官方 reset 清存储 + 重建实例。幂等。
    ⚠️ P1 修复（2026-08-19 核查）：必须以 _drop_memory() 收尾——否则 _MEMORY 持有指向
    已删目录的悬挂句柄，后续 add 全部静默失败（readonly database，accepted_turns 假成功）。"""
    t0 = time.perf_counter()
    degraded = None
    _drop_memory()
    try:
        _mem().reset()
    except Exception as e:
        degraded = str(e)
        print(f"[mem0-reset] reset 异常（降级为目录清理）: {e}", file=sys.stderr)
        _drop_memory()
        _state.hard_reset_dir()
    _state.hard_reset_dir()  # scopes.json 一并清掉
    _drop_memory()  # 关键：不留悬挂实例
    _stats.mark_reset()
    _stats.n_sessions = 0
    _trace("reset", degraded=degraded, elapsed_ms=int((time.perf_counter() - t0) * 1000))
    return {"ok": True, "cleared": {"system": "mem0"}}


@mcp.tool
def stats() -> dict:
    # n_sessions 从落盘 scopes.json 读，而不是只用进程内计数器——否则 restore(ingested)
    # 起跑的臂会报 n_sessions=0（状态在盘上，计数器却是新进程的 0），run 报告会失真。
    _stats.n_sessions = len(_scopes()["sessions"])
    n_mem, mem_diag = _n_memories()
    d = _stats.to_dict(n_memories=n_mem)
    d["llm_calls"] = _METER["llm_calls"]  # 计量器是唯一真源（含 retrieve 路径，虽然 v3 检索不调 LLM）
    notes = [_channel_tag()]
    if mem_diag["saturated_scopes"] or mem_diag["errors"]:
        notes.append(f"N_MEMORIES_UNRELIABLE: saturated={mem_diag['saturated_scopes']} errors={list(mem_diag['errors'])}")
    if _METER["usage_missing"]:
        # 契约 §5：拿不到就 null + native_notes 说明。部分缺失也按不可信处理，
        # 但实测到的分量保留在 mem0.meter 里，不丢证据。
        d["tokens_used"] = {k: None for k in d["tokens_used"]}
        notes.append(f"TOKENS_NULLED: {_METER['usage_missing']} 次 LLM 响应未回 usage，token 不可信（实测分量见 mem0.meter）")
    else:
        notes.append("TOKENS: 全部 LLM 响应均回了 usage，来自 patch 后的 OpenAI client")
    # 契约 §5 之外的附加字段（只增不改）：把"这批分数是在什么配置、什么通道下跑出来的"
    # 随 system_stats.jsonl 一起归档，事后无需回溯代码即可复原运行条件。
    d["mem0"] = {
        "search_params_effective": _search_params(5),
        "upstream_search_defaults": UPSTREAM_SEARCH_DEFAULTS,
        "channels": _channels(),
        "meter": _meter_snapshot(),
        "n_memories_diag": mem_diag,
        "trace_file": str(_TRACE_FILE),
    }
    d["native_notes"] = "；".join(notes)
    _trace("stats", n_memories=d["n_memories"], n_sessions=d["n_sessions"],
           tokens_used=d["tokens_used"], meter=_meter_snapshot(), n_memories_diag=mem_diag)
    return d


@mcp.tool
def snapshot(tag: str) -> dict:
    _drop_memory()  # 确保目录无句柄占用
    time.sleep(0.1)
    r = _state.snapshot(tag)
    _stats.snapshots = _state.tags()
    _trace("snapshot", tag=tag, ok=r.get("ok"))
    return r


@mcp.tool
def restore(tag: str) -> dict:
    _drop_memory()
    r = _state.restore(tag)
    if not r.get("ok") and r.get("error") == "SNAPSHOT_NOT_FOUND":
        _trace("restore", tag=tag, ok=False, error="SNAPSHOT_NOT_FOUND")
        return r
    _stats.snapshots = _state.tags()
    _mem()  # 触发重建 + 通道重探，校验快照可加载
    _trace("restore", tag=tag, ok=r.get("ok"), channels=_channels())
    return r


if __name__ == "__main__":
    mcp.run()  # stdio

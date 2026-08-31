# graphiti wrapper 的可审查追踪层（本轮新增）。
#
# 存在的理由：2026-08-29 的论文↔代码保真度核查发现，我们过去无法回答"这次检索到底走了哪几条通道"。
# graphiti 的 bfs 通道在 origin 为空时会**静默返回 []**（search_utils.py:456），cross_encoder 重排
# 在拿不到 logprobs 时会**抛 zip(strict=True)**——两种失效形态都不会体现在最终 envelope 上。
# 因此本模块把三件事写成可 grep 的结构化证据：
#   1) 每次调用的**运行时实际生效配置**（不是代码默认值）
#   2) **每条检索通道的真实命中数**（逐次调用记录，能区分"没配"和"配了但空转"）
#   3) LLM/embedding 调用次数与 token 用量 + 耗时分解
#
# ⚠️ 全部输出走 stderr / 文件，绝不碰 stdout——MCP 是 stdio 协议，stdout 混入非 JSON-RPC 即链路崩。

from __future__ import annotations

import json
import os
import sys
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]

# 单次工具调用的追踪上下文（contextvar：并发调用互不串味）
_CTX: ContextVar[dict[str, Any] | None] = ContextVar("membench_graphiti_ctx", default=None)


# ---------- stdout 净化（与 servers/mem0/server.py 同款手法） ----------

def harden_stdout() -> None:
    """任何显式传 sys.stdout 的 StreamHandler 改道 stderr；裸 print 也改道。幂等。"""
    import builtins
    import logging

    if getattr(harden_stdout, "_done", False):
        return
    orig_sh_init = logging.StreamHandler.__init__

    def _safe_sh_init(self, stream=None):  # noqa: ANN001
        if stream is sys.stdout:
            stream = sys.stderr
        orig_sh_init(self, stream)

    logging.StreamHandler.__init__ = _safe_sh_init
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, force=True)

    orig_print = builtins.print

    def _print_stderr(*args, **kwargs):  # noqa: ANN001
        kwargs.setdefault("file", sys.stderr)
        orig_print(*args, **kwargs)

    builtins.print = _print_stderr
    harden_stdout._done = True  # type: ignore[attr-defined]


# ---------- 落盘位置 ----------

def trace_path(system: str = "graphiti") -> Path:
    """run 内 → runs/<run_id>/mcp_trace/<system>.jsonl（与 evidence/manifest 同目录，便于归档比对）；
    无 run_id（smoke / 手工调用）→ .state/<system>/mcp_trace/<system>-<日期>.jsonl（不丢证据）。"""
    run_id = os.environ.get("MEMBENCH_RUN_ID")
    if run_id:
        p = REPO / "runs" / run_id / "mcp_trace"
    else:
        state_root = Path(os.environ.get("MEMBENCH_STATE_DIR") or REPO / ".state")
        p = state_root / system / "mcp_trace"
    p.mkdir(parents=True, exist_ok=True)
    name = f"{system}.jsonl" if run_id else f"{system}-{datetime.now().strftime('%Y%m%d')}.jsonl"
    return p / name


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def emit(event: str, payload: dict[str, Any], system: str = "graphiti") -> None:
    """写一行 JSONL + 一行 stderr 摘要。任何异常都吞掉——日志不许拖垮被测系统。"""
    rec = {"ts": _utcnow(), "event": event, "system": system, "pid": os.getpid(), **payload}
    line = json.dumps(rec, ensure_ascii=False, default=str)
    try:
        with trace_path(system).open("a") as f:
            f.write(line + "\n")
    except Exception as e:  # noqa: BLE001
        print(f"[trace] 落盘失败（已忽略）: {type(e).__name__}: {e}", file=sys.stderr)
    if os.environ.get("MEMBENCH_GRAPHITI_TRACE_STDERR", "1") == "1":
        print(f"[graphiti-trace] {line}", file=sys.stderr)


# ---------- 用量计量：LLM / embedding / reranker ----------

class Meter:
    """进程级累计 + 单次调用增量。graphiti 自身不外露 token，这里在 openai 客户端边界上截。"""

    def __init__(self) -> None:
        self.reset_totals()

    def reset_totals(self) -> None:
        self.llm_calls = 0
        self.llm_prompt = 0
        self.llm_completion = 0
        self.embed_calls = 0
        self.embed_tokens = 0
        self.rerank_calls = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "llm_calls": self.llm_calls, "llm_prompt_tokens": self.llm_prompt,
            "llm_completion_tokens": self.llm_completion,
            "embed_calls": self.embed_calls, "embed_tokens": self.embed_tokens,
            "rerank_calls": self.rerank_calls,
        }

    @staticmethod
    def delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
        return {k: after[k] - before[k] for k in after}

    def record_llm(self, usage: Any) -> None:
        self.llm_calls += 1
        self.llm_prompt += int(getattr(usage, "prompt_tokens", 0) or 0)
        self.llm_completion += int(getattr(usage, "completion_tokens", 0) or 0)

    def record_embed(self, usage: Any) -> None:
        self.embed_calls += 1
        self.embed_tokens += int(getattr(usage, "prompt_tokens", 0) or getattr(usage, "total_tokens", 0) or 0)


METER = Meter()


# ---------- 单次调用上下文 ----------

@contextmanager
def call_ctx(**seed: Any):
    """开一次工具调用的追踪上下文：通道计数 / span / 起始用量快照。"""
    ctx: dict[str, Any] = {"channels": {}, "spans": [], "meter_before": METER.snapshot(), **seed}
    token = _CTX.set(ctx)
    try:
        yield ctx
    finally:
        _CTX.reset(token)


def ctx() -> dict[str, Any] | None:
    return _CTX.get()


def note_channel(name: str, hits: int, ms: int) -> None:
    """记录一条检索通道的**单次**执行。同一通道被调多次（如 bfs 的 None 空转 + 自动播种）分别入账。"""
    c = _CTX.get()
    if c is None:
        return
    slot = c["channels"].setdefault(name, {"calls": 0, "hits_total": 0, "hits_per_call": [], "ms": 0})
    slot["calls"] += 1
    slot["hits_total"] += hits
    slot["hits_per_call"].append(hits)
    slot["ms"] += ms


# ---------- graphiti 原生 Tracer 适配：把上游 span 属性收进本地上下文 ----------

from graphiti_core.tracer import Tracer, TracerSpan  # noqa: E402


class _JsonlSpan(TracerSpan):
    def __init__(self, name: str) -> None:
        self.name = name
        self.attrs: dict[str, Any] = {}
        self.status: str | None = None
        self.t0 = time.perf_counter()

    def add_attributes(self, attributes: dict[str, Any]) -> None:
        self.attrs.update(attributes)

    def set_status(self, status: str, description: str | None = None) -> None:
        self.status = status if description is None else f"{status}: {description}"

    def record_exception(self, exception: Exception) -> None:
        self.status = f"exception: {type(exception).__name__}: {exception}"


class JsonlTracer(Tracer):
    """实现 graphiti 的 Tracer 抽象，把上游自带的 span 属性（候选数/重排器/BFS 播种数…）落进本地上下文。
    上游 create_tracer() 只认 OTel，所以构造后直接给 Graphiti.tracer / clients.tracer 赋值。"""

    @contextmanager
    def start_span(self, name: str):  # noqa: ANN201
        span = _JsonlSpan(name)
        try:
            yield span
        finally:
            c = _CTX.get()
            if c is not None and len(c["spans"]) < 64:  # 上限防爆
                c["spans"].append({
                    "name": name, "ms": int((time.perf_counter() - span.t0) * 1000),
                    "attrs": span.attrs, **({"status": span.status} if span.status not in (None, "ok") else {}),
                })


# ---------- 检索通道插桩：把上游各通道函数包一层计数 ----------

_CHANNEL_FUNCS = [
    ("edge_fulltext_search", "edge.bm25"),
    ("edge_similarity_search", "edge.cosine"),
    ("edge_bfs_search", "edge.bfs"),
    ("node_fulltext_search", "node.bm25"),
    ("node_similarity_search", "node.cosine"),
    ("node_bfs_search", "node.bfs"),
    ("community_fulltext_search", "community.bm25"),
    ("community_similarity_search", "community.cosine"),
    ("episode_fulltext_search", "episode.bm25"),
]


def install_channel_probes() -> list[str]:
    """在 graphiti_core.search.search 的模块命名空间里替换通道函数（它是 from-import 进来的，
    只能在这个命名空间打桩）。幂等；返回已插桩的通道名，供启动日志核对。"""
    import graphiti_core.search.search as gsearch

    if getattr(gsearch, "_membench_probed", False):
        return [label for _, label in _CHANNEL_FUNCS]

    def wrap(fn, label):  # noqa: ANN001
        async def probed(*args, **kwargs):  # noqa: ANN001
            t0 = time.perf_counter()
            try:
                out = await fn(*args, **kwargs)
            except Exception as e:  # noqa: BLE001
                note_channel(label + ".ERROR", -1, int((time.perf_counter() - t0) * 1000))
                raise e
            note_channel(label, len(out) if out is not None else 0,
                         int((time.perf_counter() - t0) * 1000))
            return out

        probed.__name__ = getattr(fn, "__name__", label)
        return probed

    installed = []
    for attr, label in _CHANNEL_FUNCS:
        fn = getattr(gsearch, attr, None)
        if fn is None:
            continue
        setattr(gsearch, attr, wrap(fn, label))
        installed.append(label)
    gsearch._membench_probed = True
    return installed

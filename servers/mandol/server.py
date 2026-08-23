# mandol：A档系统（arXiv:2606.29778，LoCoMo 92.21% SOTA 声明者）
# 机制：agglomerative 聚合式层级记忆图 + 定量检索；ingest 不调 LLM（embedding 聚合），检索带原生分数
# embedding：走 cloud 适配器（OpenAI 格式）重定向到智谱端点——
#   SILICONFLOW_EMBEDDINGS_URL=https://open.bigmodel.cn/api/coding/paas/v4/embeddings
#   SILICONFLOW_API_KEY=<智谱 key>（mandol 硬编码 SiliconFlow 品牌名，URL/key 均可 env 覆盖）
# scope 隔离：space_names=[scope_id]，mandol 原生 memory space
# 快照：save_graph/load_graph 原生持久化，落 MEMBENCH_STATE_DIR
# ⚠️ 独立 venv .venv-mandol（mandol 锁 numpy<2，与 chromadb 依赖冲突）

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# mandol 及其依赖（jieba/spacy）的日志会漏到 stdout 污染 stdio JSON-RPC——全部改道 stderr
import logging

logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(name)s %(levelname)s %(message)s")
for _n in ("httpx", "urllib3", "filelock", "huggingface_hub", "sentence_transformers", "faiss", "jieba", "spacy"):
    logging.getLogger(_n).setLevel(logging.ERROR)

# MCP stdio 要求 stdout 纯净：mandol 库 get_logger 给 module logger 挂 StreamHandler(sys.stdout)
# 且 propagate=False（2026-08-22 S4 第一批实测），basicConfig 管不到。
# 根治：monkeypatch StreamHandler.__init__，强制任何显式传 sys.stdout 的 handler 改道 stderr。
import builtins

_orig_sh_init = logging.StreamHandler.__init__


def _safe_sh_init(self, stream=None):
    if stream is sys.stdout:
        stream = sys.stderr
    _orig_sh_init(self, stream)


logging.StreamHandler.__init__ = _safe_sh_init

_orig_print = builtins.print


def _print_stderr(*args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    _orig_print(*args, **kwargs)


builtins.print = _print_stderr

from fastmcp import FastMCP

from servers.common.base import BaseState
from servers.common.envelope import make_envelope
from servers.common.stats import StatsTracker

mcp = FastMCP("mandol")

_state = BaseState("mandol")
_stats = StatsTracker()
_SIDECAR = _state.state_dir / "scopes.json"
_GRAPH_DIR = _state.state_dir / "graph"
_G = None  # 惰性 SemanticGraph 单例

EMBED_MODEL = os.environ.get("MEMBENCH_EMBED_MODEL", "embedding-3")


def _scopes() -> dict:
    if _SIDECAR.exists():
        return json.loads(_SIDECAR.read_text())
    return {"scope_ids": [], "sessions": []}


def _save_scope(scope_id: str | None, session_id: str | None, n_units: int) -> None:
    s = _scopes()
    if scope_id and scope_id not in s["scope_ids"]:
        s["scope_ids"].append(scope_id)
    if session_id and session_id not in s["sessions"]:
        s["sessions"].append(session_id)
    s["n_units"] = s.get("n_units", 0) + n_units
    _SIDECAR.parent.mkdir(parents=True, exist_ok=True)
    _SIDECAR.write_text(json.dumps(s, ensure_ascii=False))


def _patch_mandol_logging():
    """mandol 库 get_logger 给 module logger 挂 StreamHandler(sys.stdout) 且 propagate=False，
    污染 MCP stdio JSON-RPC（2026-08-22 S4 第一批实测）。强制所有 stdout handler 迁到 stderr，
    并包一层 get_logger 防止后续模块再挂 stdout handler。"""
    from mandol.utils import logging_config as _lc

    def _is_stdout_handler(h):
        return isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is sys.stdout

    for _n in list(logging.root.manager.loggerDict):
        _lg = logging.getLogger(_n)
        for _h in list(_lg.handlers):
            if _is_stdout_handler(_h):
                _lg.removeHandler(_h)
                if not _lg.handlers:
                    _lg.addHandler(logging.StreamHandler(sys.stderr))

    _orig_get_logger = _lc.get_logger

    def _safe_get_logger(*args, **kwargs):
        lg = _orig_get_logger(*args, **kwargs)
        for _h in list(lg.handlers):
            if _is_stdout_handler(_h):
                lg.removeHandler(_h)
                if not lg.handlers:
                    lg.addHandler(logging.StreamHandler(sys.stderr))
        return lg

    _lc.get_logger = _safe_get_logger


def _get_graph():
    global _G
    if _G is None:
        from mandol import SemanticGraph, SemanticMap

        _patch_mandol_logging()

        # MODEL_CONFIG 是内置注册表（按模型名查 config）——注入智谱 embedding-3 的 cloud 条目，
        # 走 SiliconFlow 适配器（URL/key 已重定向到智谱端点），避免拉本地 HF 模型
        dim = int(os.environ.get("MEMBENCH_EMBED_DIM", "2048"))
        if EMBED_MODEL not in SemanticMap.MODEL_CONFIG:
            SemanticMap.MODEL_CONFIG[EMBED_MODEL] = {
                "dim": dim, "type": "cloud", "provider": "siliconflow",
                "modalities": ["text"], "wrapper": None,
            }
        smap = SemanticMap(embedding_model_name=EMBED_MODEL, embedding_dim=dim)
        if _GRAPH_DIR.exists() and any(_GRAPH_DIR.iterdir()):
            _G = SemanticGraph.load_graph(str(_GRAPH_DIR), semantic_map_instance=smap)
        else:
            _G = SemanticGraph(semantic_map_instance=smap)
    return _G


def _drop_graph() -> None:
    global _G
    _G = None


def _persist() -> None:
    if _G is not None:
        _GRAPH_DIR.mkdir(parents=True, exist_ok=True)
        _G.save_graph(str(_GRAPH_DIR))


@mcp.tool
def add_conversation(session_id: str, turns: list[dict], scope: dict, metadata: dict | None = None) -> dict:
    """逐 turn 一个 MemoryUnit（mandol 原生消息粒度），space=scope.id 隔离。ingest 不调 LLM。"""
    t0 = time.perf_counter()
    from mandol import MemoryUnit

    g = _get_graph()
    n = 0
    for i, t in enumerate(turns):
        # 时间前缀由 harness 层统一加（spec §7），server 不重复处理
        g.add_unit(
            MemoryUnit(
                uid=f"{session_id}#{i}",
                raw_data={"text_content": f"{t.get('role', 'user')}: {t.get('content', '')}"},
                metadata={"session_id": session_id, "scope": scope.get("id"), "timestamp": t.get("timestamp")},
            ),
            space_names=[scope.get("id")] if scope.get("id") else None,
            generate_sparse_embedding=False,
        )
        n += 1
    _save_scope(scope.get("id"), session_id, n)
    _stats.n_sessions = len(_scopes()["sessions"])
    return {"accepted_turns": n, "native_notes": f"mandol 聚合完成，耗时 {int((time.perf_counter() - t0) * 1000)}ms（纯 embedding，无 LLM 调用）"}


@mcp.tool
def retrieve(query: str, query_mode: str = "fixed", top_k: int = 5, filter: dict | None = None) -> dict:
    """相似度检索，原生分数归一困难则透传（mandol 分数语义为图内相似度）。"""
    t0 = time.perf_counter()
    g = _get_graph()
    notes = []
    scope_ids = _scopes()["scope_ids"]
    if filter and filter.get("scope_id"):
        gid = filter["scope_id"]
    else:
        if len(scope_ids) > 1:
            notes.append("MULTI_SCOPE: 未指定 filter.scope_id，仅检索首个 space")
        gid = scope_ids[0] if scope_ids else None
    if filter and any(k for k in filter if k != "scope_id"):
        notes.append("FILTER_IGNORED: 仅支持 scope_id")
    raw = g.search_similarity_in_graph(query_text=query, top_k=top_k, ms_names=[gid] if gid else None, return_score=True)
    results = []
    for item in raw:
        unit, score = (item if isinstance(item, (tuple, list)) else (item, None))
        meta = getattr(unit, "metadata", None) or {}
        raw_data = getattr(unit, "raw_data", None) or {}
        uid = getattr(unit, "uid", "")
        turn_range = None
        if "#" in str(uid):
            try:
                turn_range = [int(uid.rsplit("#", 1)[1])] * 2
            except ValueError:
                pass
        results.append(make_envelope(
            memory_id=uid,
            text=str(raw_data.get("text_content", "")),
            session_id=meta.get("session_id"),
            turn_range=turn_range,
            timestamp=meta.get("timestamp"),
            score=round(float(score), 4) if isinstance(score, (int, float)) else None,
            raw_format="mandol_unit",
        ))
    return {
        "results": results,
        "query_used": query,
        "query_mode": query_mode,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
        "native_notes": "; ".join(notes),
    }


@mcp.tool
def reset() -> dict:
    """清图 + 清持久化目录。幂等。"""
    global _G
    _drop_graph()
    _state.hard_reset_dir()
    _stats.mark_reset()
    _stats.n_sessions = 0
    return {"ok": True, "cleared": {"system": "mandol"}}


@mcp.tool
def stats() -> dict:
    s = _scopes()
    return _stats.to_dict(n_memories=s.get("n_units", 0))


@mcp.tool
def snapshot(tag: str) -> dict:
    _persist()  # 先落盘再拷目录
    r = _state.snapshot(tag)
    _stats.snapshots = _state.tags()
    return r


@mcp.tool
def restore(tag: str) -> dict:
    _drop_graph()
    r = _state.restore(tag)
    if not r.get("ok"):
        return r
    _get_graph()  # 触发 load_graph 校验快照可加载
    _stats.snapshots = _state.tags()
    _stats.n_sessions = len(_scopes()["sessions"])
    return r


if __name__ == "__main__":
    mcp.run()  # stdio

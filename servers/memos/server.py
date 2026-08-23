# memos：A档系统（arXiv:2507.03724，MemTensor 记忆操作系统，Self-Host REST）
# 部署：~/Documents/repo/MemOS docker compose（API :8000 + Neo4j + Qdrant，见 DEPLOY.md）
# REST：/product/add（sync 模式）、/product/search；cube 自动创建（add 时 writable_cube_ids 不存在也不报错）
# scope 隔离：scope_id → user_id + cube_id（bench_<scope>）
# 快照：SNAPSHOT_UNSUPPORTED（Neo4j+Qdrant 双卷，v1 重灌兜底——spec §5 允许）
# thinking 深度：容器内 LLM 调用无 effort 透传口，接受服务端默认（与 mem0/amem 的 low 有差异，native_notes 声明）
# 运行 venv：主 .venv（纯 requests，无额外依赖）

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import logging

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

import requests
from fastmcp import FastMCP

from servers.common.base import BaseState
from servers.common.envelope import make_envelope
from servers.common.stats import StatsTracker

mcp = FastMCP("memos")

_state = BaseState("memos")
_stats = StatsTracker()
_SIDECAR = _state.state_dir / "scopes.json"
BASE = os.environ.get("MEMOS_API_BASE", "http://localhost:8000") + "/product"
_S = requests.Session()
_S.headers.update({"Content-Type": "application/json"})
_TIMEOUT = int(os.environ.get("MEMOS_TIMEOUT", "300"))


def _scopes() -> dict:
    if _SIDECAR.exists():
        return json.loads(_SIDECAR.read_text())
    return {"scope_ids": [], "sessions": [], "n_units": 0}


def _save_scopes(scope_id, session_id, n) -> None:
    s = _scopes()
    if scope_id and scope_id not in s["scope_ids"]:
        s["scope_ids"].append(scope_id)
    if session_id and session_id not in s["sessions"]:
        s["sessions"].append(session_id)
    s["n_units"] = s.get("n_units", 0) + n
    _SIDECAR.parent.mkdir(parents=True, exist_ok=True)
    _SIDECAR.write_text(json.dumps(s, ensure_ascii=False))


def _cube(scope_id: str) -> str:
    return f"bench_{scope_id}"


def _post(path: str, payload: dict) -> dict:
    r = _S.post(f"{BASE}/{path}", data=json.dumps(payload), timeout=_TIMEOUT)
    try:
        return r.json()
    except Exception:
        return {"code": r.status_code, "message": r.text[:200], "data": None}


@mcp.tool
def add_conversation(session_id: str, turns: list[dict], scope: dict, metadata: dict | None = None) -> dict:
    """整段会话一次 /product/add（sync），MemOS 内部做抽取/结构化/时序标注。时间前缀由 harness 层统一加。"""
    t0 = time.perf_counter()
    sid = scope.get("id") or "default"
    res = _post("add", {
        "user_id": sid,
        "session_id": session_id,
        "writable_cube_ids": [_cube(sid)],
        "messages": [{"role": t.get("role", "user"), "content": t.get("content", "")} for t in turns],
        "async_mode": "sync",
    })
    ok = res.get("code") == 200
    if not ok:
        raise RuntimeError(f"MemOS add 失败: {res.get('message')}")
    n = len(turns)
    _save_scopes(sid, session_id, n)
    _stats.n_sessions = len(_scopes()["sessions"])
    _stats.add_tokens("internal_llm", None)
    return {"accepted_turns": n, "native_notes": f"MemOS 抽取完成，耗时 {int((time.perf_counter() - t0) * 1000)}ms（内部 LLM 计量未暴露；容器内 reasoning 深度未透传=服务端默认）"}


@mcp.tool
def retrieve(query: str, query_mode: str = "fixed", top_k: int = 5, filter: dict | None = None) -> dict:
    """/product/search；返回 text_mem[].memories[] → envelope。"""
    t0 = time.perf_counter()
    parts = []
    scope_ids = _scopes()["scope_ids"]
    if filter and filter.get("scope_id"):
        sid = filter["scope_id"]
    else:
        if len(scope_ids) > 1:
            parts.append("MULTI_SCOPE: 未指定 filter.scope_id，仅检索首个 scope")
        sid = scope_ids[0] if scope_ids else "default"
    if filter and any(k for k in filter if k != "scope_id"):
        parts.append("FILTER_IGNORED: 仅支持 scope_id")
    res = _post("search", {"query": query, "user_id": sid, "readable_cube_ids": [_cube(sid)], "top_k": top_k})
    if res.get("code") != 200:
        raise RuntimeError(f"MemOS search 失败: {res.get('message')}")
    results = []
    for block in (res.get("data") or {}).get("text_mem", []) or []:
        if _cube(sid) not in (block.get("cube_id"),):
            continue
        for mem in block.get("memories", []) or []:
            meta = mem.get("metadata") or {}
            results.append(make_envelope(
                memory_id=mem.get("id", ""),
                text=mem.get("memory", ""),
                session_id=meta.get("session_id"),
                turn_range=None,
                timestamp=None,
                score=mem.get("score"),
                raw_format="memos_text",
            ))
    return {
        "results": results[:top_k],
        "query_used": query,
        "query_mode": query_mode,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
        "native_notes": "; ".join(parts),
    }


@mcp.tool
def reset() -> dict:
    """按 user + cube 删除全部记忆。幂等（删不存在的返回非 200 不视为错误）。"""
    s = _scopes()
    for sid in s["scope_ids"]:
        _post("delete_memory", {"user_id": sid, "writable_cube_ids": [_cube(sid)], "auto_cleanup_working": True})
    _SIDECAR.unlink(missing_ok=True)
    _stats.mark_reset()
    _stats.n_sessions = 0
    return {"ok": True, "cleared": {"system": "memos", "scopes": len(s["scope_ids"])}}


@mcp.tool
def stats() -> dict:
    return _stats.to_dict(n_memories=_scopes().get("n_units", 0))


@mcp.tool
def snapshot(tag: str) -> dict:
    return {"ok": False, "error": "SNAPSHOT_UNSUPPORTED", "tag": tag,
            "hint": "Neo4j+Qdrant 双存储卷；重灌兜底（spec §5），Phase 2 可做 compose 卷级快照"}


@mcp.tool
def restore(tag: str) -> dict:
    return {"ok": False, "error": "SNAPSHOT_UNSUPPORTED", "tag": tag}


if __name__ == "__main__":
    mcp.run()  # stdio

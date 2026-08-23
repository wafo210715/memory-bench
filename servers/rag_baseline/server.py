# rag_baseline：裸向量 RAG 对照臂（bench-design §3）
# turn 级 chunk（与 ingest 渲染一致，[日期] 前缀由 harness loader 层加）+ embedding-3 云端 + 本地余弦暴力扫。
# 无内部 LLM（与 mandol 同类，ingest 零 LLM 调用）；无索引库（LoCoMo 尺寸 ~6k 向量，暴力扫毫秒级）。
# 用途：对照锚点——回应"记忆系统是否只是向量检索"的公平性质疑。
# 环境变量：MEMBENCH_LLM_API_KEY / MEMBENCH_LLM_BASE_URL（embedding 走智谱普通通道，
#   coding 通道无 embedding 权限时自动去 /coding；可显式用 MEMBENCH_EMBED_BASE_URL/API_KEY/MODEL 覆盖）

import json
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 让 servers.common 可导入

from fastmcp import FastMCP
from openai import OpenAI

from servers.common.base import BaseState
from servers.common.envelope import make_envelope
from servers.common.stats import StatsTracker

mcp = FastMCP("rag_baseline")

_state = BaseState("rag_baseline")
_stats = StatsTracker()
_MEM_FILE = _state.state_dir / "chunks.jsonl"
_VEC_FILE = _state.state_dir / "vectors.npy"

_REQUIRED = ["MEMBENCH_LLM_API_KEY", "MEMBENCH_LLM_BASE_URL"]


def _embed_client() -> OpenAI:
    missing = [k for k in _REQUIRED if not os.environ.get(k)]
    if missing:
        # RuntimeError 作为工具结果返回，不无声杀死 server（interface-spec §6 语义）
        raise RuntimeError(f"缺少环境变量 {missing}——MCP stdio 子进程不继承父进程环境（见 interface-spec §7）")
    # embedding 走智谱普通通道：coding 通道无 embedding-3 权限（2026-08-21 冒烟验证普通通道 OK）
    base = os.environ.get("MEMBENCH_EMBED_BASE_URL") or os.environ["MEMBENCH_LLM_BASE_URL"].replace("/coding", "")
    key = os.environ.get("MEMBENCH_EMBED_API_KEY") or os.environ["MEMBENCH_LLM_API_KEY"]
    return OpenAI(api_key=key, base_url=base)


def _embed(texts: list[str]) -> tuple[list[list[float]], int]:
    """批量 embed，返回 (向量列表, token 用量)。"""
    model = os.environ.get("MEMBENCH_EMBED_MODEL", "embedding-3")
    r = _embed_client().embeddings.create(model=model, input=texts)
    return [d.embedding for d in r.data], r.usage.total_tokens


def _load_records() -> list[dict]:
    if not _MEM_FILE.exists():
        return []
    return [json.loads(line) for line in _MEM_FILE.read_text().splitlines() if line.strip()]


def _save_records(records: list[dict]) -> None:
    _MEM_FILE.parent.mkdir(parents=True, exist_ok=True)
    _MEM_FILE.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records))


def _load_vecs() -> np.ndarray | None:
    if _VEC_FILE.exists():
        return np.load(_VEC_FILE)
    return None


def _save_vecs(arr: np.ndarray | None) -> None:
    if arr is None or len(arr) == 0:
        if _VEC_FILE.exists():
            _VEC_FILE.unlink()
        return
    _VEC_FILE.parent.mkdir(parents=True, exist_ok=True)
    np.save(_VEC_FILE, arr)


def _cosine_topk(vecs: np.ndarray, qv: np.ndarray, top_k: int) -> list[tuple[int, float]]:
    """余弦相似度 top-k，返回 [(原库行号, 相似度)]，降序、平分按行号升序（稳定可复现）。"""
    a_n = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
    q_n = qv / np.linalg.norm(qv)
    sims = a_n @ q_n
    order = sorted(range(len(sims)), key=lambda i: (-sims[i], i))
    return [(i, float(sims[i])) for i in order[:top_k] if sims[i] > 0]


@mcp.tool
def add_conversation(session_id: str, turns: list[dict], scope: dict, metadata: dict | None = None) -> dict:
    """灌入一段会话，turn 级 chunk，逐 turn embed。turns: [{role, content, timestamp?}]。"""
    t0 = time.perf_counter()
    texts = [t.get("content", "") for t in turns]
    vecs, n_tok = _embed(texts)
    _stats.add_tokens("ingest", n_tok)
    _stats.llm_calls += 1  # embedding 调用计入 llm_calls（无文本 LLM，internal_llm 恒 0）

    records = _load_records()
    base = len(records)
    new_records = [
        {
            "memory_id": f"{session_id}#{i}",
            "session_id": session_id,
            "turn_index": i,
            "content": t.get("content", ""),
            "timestamp": t.get("timestamp"),
            "scope_id": scope.get("id"),
        }
        for i, t in enumerate(turns)
    ]
    _save_records(records + new_records)

    old = _load_vecs()
    merged = np.array(vecs, dtype=np.float32) if old is None else np.vstack([old, np.array(vecs, dtype=np.float32)])
    _save_vecs(merged)
    assert len(_load_records()) == len(merged), f"records({len(records) + len(new_records)}) 与 vectors({len(merged)}) 行数漂移"

    _stats.n_sessions = len({r["session_id"] for r in _load_records()})
    return {
        "accepted_turns": len(turns),
        "native_notes": f"rag_baseline: turn 级 chunk × {len(turns)}，embed {n_tok} tok，{time.perf_counter() - t0:.2f}s",
    }


@mcp.tool
def retrieve(query: str, query_mode: str = "fixed", top_k: int = 5, filter: dict | None = None) -> dict:
    """余弦相似度检索。支持 filter.scope_id；before_timestamp / session_ids 不支持（FILTER_IGNORED）。"""
    t0 = time.perf_counter()
    records = _load_records()
    vecs = _load_vecs()
    notes = []
    if not records or vecs is None:
        return {"results": [], "query_used": query, "query_mode": query_mode,
                "latency_ms": int((time.perf_counter() - t0) * 1000), "native_notes": "EMPTY"}

    scope_id = (filter or {}).get("scope_id")
    if scope_id:
        keep = [i for i, r in enumerate(records) if r.get("scope_id") == scope_id]
    else:
        keep = list(range(len(records)))
    if filter and any(k in filter for k in ("before_timestamp", "session_ids")):
        notes.append("FILTER_IGNORED")

    qv_list, n_tok = _embed([query])
    _stats.add_tokens("retrieve", n_tok)
    _stats.llm_calls += 1

    sub = vecs[keep]
    sub_idx = _cosine_topk(sub, np.array(qv_list[0], dtype=np.float32), top_k)
    results = [
        make_envelope(
            memory_id=records[keep[gi]]["memory_id"],
            text=records[keep[gi]]["content"],
            session_id=records[keep[gi]]["session_id"],
            turn_range=[records[keep[gi]]["turn_index"], records[keep[gi]]["turn_index"]],
            timestamp=records[keep[gi]]["timestamp"],
            score=round(s, 4),
            raw_format="rag_turn",
        )
        for gi, s in sub_idx
    ]
    return {
        "results": results,
        "query_used": query,
        "query_mode": query_mode,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
        "native_notes": "; ".join(notes),
    }


@mcp.tool
def reset() -> dict:
    """清空全部状态（chunks.jsonl + vectors.npy）。幂等。"""
    _state.hard_reset_dir()
    _stats.mark_reset()
    _stats.n_sessions = 0
    return {"ok": True, "cleared": {"system": "rag_baseline"}}


@mcp.tool
def stats() -> dict:
    return _stats.to_dict(n_memories=len(_load_records()))


@mcp.tool
def snapshot(tag: str) -> dict:
    r = _state.snapshot(tag)
    _stats.snapshots = _state.tags()
    return r


@mcp.tool
def restore(tag: str) -> dict:
    r = _state.restore(tag)
    _stats.snapshots = _state.tags()
    if not r.get("ok"):
        r["error"] = r.get("error", "SNAPSHOT_FAILED")
    return r


if __name__ == "__main__":
    mcp.run()  # stdio

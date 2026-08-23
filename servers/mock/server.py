# mock：无 LLM 的契约验证靶（interface-spec 的最小合法实现）
# 内存 dict + 关键词重叠检索，状态持久化到 state_dir（jsonl），snapshot/restore 走 BaseState 目录拷贝。
# 用途：验证 common 模块、六工具契约、smoke test 全链路——不依赖任何外部服务。

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 让 servers.common 可导入

from fastmcp import FastMCP

from servers.common.base import BaseState
from servers.common.envelope import make_envelope
from servers.common.stats import StatsTracker

mcp = FastMCP("mock")

_state = BaseState("mock")
_stats = StatsTracker()
_MEM_FILE = _state.state_dir / "memory.jsonl"


def _load() -> list[dict]:
    if not _MEM_FILE.exists():
        return []
    return [json.loads(line) for line in _MEM_FILE.read_text().splitlines() if line.strip()]


def _save(records: list[dict]) -> None:
    _MEM_FILE.parent.mkdir(parents=True, exist_ok=True)
    _MEM_FILE.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records))


def _tokens(text: str) -> set[str]:
    # 中英混合粗分词：英文按词、中文按单字 bigram，够 mock 用
    words = set(w.lower() for w in re.findall(r"[a-zA-Z0-9]+", text))
    cn = re.findall(r"[\u4e00-\u9fff]", text)
    words |= {cn[i] + cn[i + 1] for i in range(len(cn) - 1)}
    return words


@mcp.tool
def add_conversation(session_id: str, turns: list[dict], scope: dict, metadata: dict | None = None) -> dict:
    """灌入一段会话。turns: [{role, content, timestamp?}]；scope: {kind, id}。"""
    records = _load()
    for i, t in enumerate(turns):
        records.append(
            {
                "memory_id": f"{session_id}#{i}",
                "session_id": session_id,
                "turn_index": i,
                "role": t.get("role"),
                "content": t.get("content", ""),
                "timestamp": t.get("timestamp"),
                "scope_id": scope.get("id"),
            }
        )
    _save(records)
    _stats.n_sessions = len({r["session_id"] for r in records})
    return {"accepted_turns": len(turns), "native_notes": "mock: 每轮原文即一条记忆"}


@mcp.tool
def retrieve(query: str, query_mode: str = "fixed", top_k: int = 5, filter: dict | None = None) -> dict:
    """关键词重叠检索。filter 不支持，返回 FILTER_IGNORED。"""
    t0 = time.perf_counter()
    records = _load()
    if filter and filter.get("scope_id"):
        records = [r for r in records if r.get("scope_id") == filter["scope_id"]]
    q = _tokens(query)
    scored = []
    for r in records:
        overlap = len(q & _tokens(r["content"]))
        score = overlap / max(len(q), 1)
        scored.append((score, r["memory_id"], r))
    scored.sort(key=lambda x: (-x[0], x[1]))  # 分数降序，id 升序保证稳定
    hits = [s for s in scored if s[0] > 0][:top_k]
    results = [
        make_envelope(
            memory_id=r["memory_id"],
            text=r["content"],
            session_id=r["session_id"],
            turn_range=[r["turn_index"], r["turn_index"]],
            timestamp=r["timestamp"],
            score=round(s, 4),
            raw_format="mock_turn",
        )
        for s, _, r in hits
    ]
    notes = []
    if filter:
        notes.append("FILTER_IGNORED")
    return {
        "results": results,
        "query_used": query,
        "query_mode": query_mode,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
        "native_notes": "; ".join(notes),
    }


@mcp.tool
def reset() -> dict:
    """清空全部状态。幂等：重复调用安全。"""
    _state.hard_reset_dir()
    _stats.mark_reset()
    _stats.n_sessions = 0
    return {"ok": True, "cleared": {"system": "mock"}}


@mcp.tool
def stats() -> dict:
    return _stats.to_dict(n_memories=len(_load()))


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

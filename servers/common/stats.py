# stats：用量统计（interface-spec §5）
# tokens_used.internal_llm 单列——Mem0 抽事实、意图推断这类内部消耗都记这里，成本归因靠它。

from datetime import datetime, timezone


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StatsTracker:
    def __init__(self) -> None:
        self.tokens: dict[str, int | None] = {"ingest": 0, "retrieve": 0, "internal_llm": 0}
        self.llm_calls: int = 0
        self.last_reset_at: str | None = None
        self.n_sessions: int = 0
        self.snapshots: list[str] = []

    def mark_reset(self) -> None:
        self.last_reset_at = utcnow_iso()

    def add_tokens(self, bucket: str, n: int) -> None:
        """bucket ∈ ingest | retrieve | internal_llm；拿不到的系统传 None 表示不可计量。"""
        if n is None:
            self.tokens[bucket] = None
        elif self.tokens[bucket] is not None:
            self.tokens[bucket] += n

    def to_dict(self, n_memories: int) -> dict:
        return {
            "n_memories": n_memories,
            "n_sessions": self.n_sessions,
            "tokens_used": dict(self.tokens),
            "llm_calls": self.llm_calls,
            "last_reset_at": self.last_reset_at,
            "snapshots": list(self.snapshots),
        }

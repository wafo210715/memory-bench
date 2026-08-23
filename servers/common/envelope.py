# envelope：Canonical Result Envelope 统一渲染（interface-spec §4）
# 所有系统的检索结果都必须经此渲染——格式即混淆源，锁死。

MAX_CHARS = 600


def render_text(text: str, timestamp: str | None = None, session_id: str | None = None) -> str:
    """渲染为单条 markdown 列表项：`- 时间戳 · 内容要点（session 溯源）`，整体 ≤600 字符。"""
    body = text.strip()
    if timestamp:
        body = f"{timestamp} · {body}"
    if session_id:
        body = f"{body}（session:{session_id}）"
    rendered = f"- {body}"
    if len(rendered) > MAX_CHARS:
        rendered = rendered[: MAX_CHARS - 1] + "…"
    return rendered


def make_envelope(
    memory_id: str,
    text: str,
    session_id: str | None = None,
    turn_range: list | None = None,
    timestamp: str | None = None,
    score: float | None = None,
    raw_format: str | None = None,
) -> dict:
    """构造一条标准 envelope。score 为原生相似度（尽力归一到 0-1），无则 None。"""
    return {
        "memory_id": str(memory_id),
        "text": render_text(text, timestamp, session_id),
        "source": {"session_id": session_id, "turn_range": turn_range},
        "timestamp": timestamp,
        "score": score,
        "raw_format": raw_format,
    }


ENVELOPE_FIELDS = {"memory_id", "text", "source", "timestamp", "score", "raw_format"}


def validate_envelope(env: dict) -> tuple[bool, str]:
    """smoke test 用：字段齐全 + text 不超限。"""
    missing = ENVELOPE_FIELDS - set(env.keys())
    if missing:
        return False, f"缺少字段: {sorted(missing)}"
    if len(env["text"]) > MAX_CHARS:
        return False, f"text 超长: {len(env['text'])} > {MAX_CHARS}"
    return True, "ok"

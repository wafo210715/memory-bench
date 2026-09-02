"""hierarchical 塔：L0 上下文改写 → L1 结构化抽取 → L2 全局聚合 → 载入图。

逐条对齐官方 dataset_maker/locomo_hierarchical_content_maker/：
  step1_generate_l0_graph.py      逐 message 上下文改写（成本最大项）
  step2_extract_l1.py             逐 session 结构化抽取
  step3_aggregate_l2.py           逐 conversation 全局聚合
  step4_load_to_semantic_graph.py 载入（含关键的 text_content 覆盖）

> [!important] 最易踩空的一条数据流
> step1 产出的 `indexing_text` 不进 MemoryUnit（step1:424 只传 raw_data/metadata），
> 要到 step4:360 才 `raw_data['text_content'] = indexing_text` 覆盖回去。
> 漏掉这次覆盖 → 烧完全部 L0 token 却仍用原文做 embedding，且完全静默。
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from .llm import TowerLLM
from .prompts import (
    CONTEXTUAL_RETRIEVAL_PROMPT,
    L1_EXTRACTION_PROMPT_TEMPLATE,
    L2_AGGREGATION_PROMPT_TEMPLATE,
)

# 官方 max_tokens（step1:604 / step2:619 / step3:534）——这些不受契约 §7 约束，保持官方
L0_MAX_TOKENS = 250
L1_MAX_TOKENS = 4000
L2_MAX_TOKENS = 8000

MIN_CONTENT_LENGTH = 15   # step1:340 过滤阈值
MIN_TRANSCRIPT_LENGTH = 50  # step2:593 跳过空 session

# harness 侧 content 形如 "user: [2023-05-01] Caroline: 正文"
# （loaders/locomo.py:97 拼 speaker+日期前缀，servers/mandol/server.py 再加 role 前缀）
_CONTENT_RE = re.compile(r"^(?:user|assistant):\s*\[(\d{4}-\d{2}-\d{2})\]\s*([^:]+):\s*(.*)$", re.S)


@dataclass
class L0Message:
    """一条 L0 观察单元（对齐 step1 的 conv_unit 结构）。"""

    uid: str
    speaker: str
    text: str                 # 原始正文（不含 role/日期/speaker 前缀）
    session_id: str
    session_date: str
    message_index: int
    dialogue_id: str
    indexing_text: str = ""   # L0 LLM 产物；载入时覆盖 text_content


@dataclass
class HierarchicalResult:
    l0: list[L0Message] = field(default_factory=list)
    l1: list[dict[str, Any]] = field(default_factory=list)
    l2: dict[str, Any] | None = None


def parse_stored_content(text_content: str) -> tuple[str, str, str] | None:
    """从 server 落库的 text_content 还原 (date, speaker, text)。解析失败返回 None。"""
    m = _CONTENT_RE.match(text_content.strip())
    if not m:
        return None
    return m.group(1), m.group(2).strip(), m.group(3).strip()


def collect_l0_messages(units: list[Any]) -> list[L0Message]:
    """把图里的原始 turn 单元整理成 L0Message；无法解析的单元跳过并计数。

    session_id / message_index / timestamp 直接取 metadata（Phase 1 已补 message_index），
    仅 speaker 与正文需要从 text_content 解析。
    """
    out: list[L0Message] = []
    session_seq: dict[str, int] = {}
    for u in units:
        raw = getattr(u, "raw_data", None) or {}
        meta = getattr(u, "metadata", None) or {}
        parsed = parse_stored_content(str(raw.get("text_content", "")))
        if not parsed:
            continue
        date, speaker, text = parsed
        if len(text.strip()) < MIN_CONTENT_LENGTH:   # 对齐 step1:340
            continue
        sid = str(meta.get("session_id") or "unknown")
        if sid not in session_seq:
            session_seq[sid] = len(session_seq) + 1
        idx = int(meta.get("message_index", len(out)))
        out.append(L0Message(
            uid=getattr(u, "uid", ""), speaker=speaker, text=text,
            session_id=sid, session_date=date, message_index=idx,
            dialogue_id=f"D{session_seq[sid]}:{idx + 1}",
        ))
    out.sort(key=lambda m: (m.session_id, m.message_index))
    return out


def _session_transcript(msgs: list[L0Message]) -> str:
    """step1:317-324 的整段 transcript：`[i] speaker: text`。"""
    return "\n".join(f"[{m.message_index + 1}] {m.speaker}: {m.text}" for m in msgs)


def build_l0(msgs: list[L0Message], llm: TowerLLM, max_workers: int = 8) -> int:
    """逐 message 上下文改写（step1:568-611）。就地写回 indexing_text，返回成功数。

    ⚠️ 官方实现对每条 message 都重发整段 session transcript（注释自称 "God Mode"），
    同一段 transcript 被付费 N 遍，占全量输入约 70%。按 Q6「保持官方实现不优化」照实现——
    优化会让分数变化产生归因歧义。
    """
    by_session: dict[str, list[L0Message]] = {}
    for m in msgs:
        by_session.setdefault(m.session_id, []).append(m)

    jobs: list[tuple[L0Message, str, list[str]]] = []
    for sid, group in by_session.items():
        transcript = _session_transcript(group)
        participants = sorted({m.speaker for m in group})
        for m in group:
            jobs.append((m, transcript, participants))

    def run(job: tuple[L0Message, str, list[str]]) -> bool:
        m, transcript, participants = job
        prompt = CONTEXTUAL_RETRIEVAL_PROMPT.format(
            date=m.session_date or "Unknown date",
            participants=", ".join(participants) if participants else "Unknown participants",
            full_session_transcript=transcript,
            speaker=m.speaker,
            message_text=m.text,
        )
        ctx = llm.complete(prompt, max_tokens=L0_MAX_TOKENS, context_id=m.uid)
        if ctx:
            # step1:608 —— 上下文描述 + 原文并存（双视图）
            m.indexing_text = f"{ctx.strip()}\nOriginal: {m.text}"
            return True
        # step1:613-615 的降级：退回带日期前缀的原文，不丢数据
        m.indexing_text = f"[{m.session_date}] {m.speaker}: {m.text}"
        return False

    ok = 0
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for fut in as_completed([ex.submit(run, j) for j in jobs]):
            if fut.result():
                ok += 1
    return ok


def build_l1(sample_id: str, msgs: list[L0Message], llm: TowerLLM,
             max_workers: int = 8) -> list[dict[str, Any]]:
    """逐 session 结构化抽取（step2:571-610）。LoCoMo 口径只建 STRUCTURED 一种 L1。"""
    by_session: dict[str, list[L0Message]] = {}
    for m in msgs:
        by_session.setdefault(m.session_id, []).append(m)

    def run(sid: str, group: list[L0Message]) -> dict[str, Any] | None:
        # step2:589 的 transcript 格式与 L0 不同：`{dialogue_id} [{speaker}]: {text}`
        transcript = "\n".join(f"{m.dialogue_id} [{m.speaker}]: {m.text}" for m in group)
        if len(transcript.strip()) < MIN_TRANSCRIPT_LENGTH:
            return None
        prompt = L1_EXTRACTION_PROMPT_TEMPLATE.format(
            session_id=sid,
            session_date=group[0].session_date if group else "unknown",
            participants=", ".join(sorted({m.speaker for m in group})),
            transcript=transcript,
        )
        got = llm.complete_json(prompt, max_tokens=L1_MAX_TOKENS, context_id=f"L1:{sid}")
        if got is None:
            return None
        got.setdefault("session_id", sid)
        got.setdefault("session_date", group[0].session_date if group else "unknown")
        got["_source_unit_uids"] = [m.uid for m in group]   # 可溯源（论文 §3.1.2）
        return got

    out: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(run, sid, g): sid for sid, g in by_session.items()}
        for fut in as_completed(futs):
            r = fut.result()
            if r is not None:
                out.append(r)
    out.sort(key=lambda d: str(d.get("session_id")))
    return out


def build_l2(sample_id: str, l1: list[dict[str, Any]], llm: TowerLLM) -> dict[str, Any] | None:
    """逐 conversation 全局聚合（step3:353-398）。整个 conv 一次调用。"""
    if not l1:
        return None
    import json
    from datetime import datetime, timezone

    dates = sorted(d.get("session_date", "") for d in l1 if d.get("session_date"))
    participants = sorted({p for d in l1 for p in (d.get("participants") or [])})
    if not participants:
        participants = ["Unknown"]
    first, last = (dates[0], dates[-1]) if dates else ("unknown", "unknown")

    prompt = L2_AGGREGATION_PROMPT_TEMPLATE.format(
        sample_id=sample_id,
        total_sessions=len(l1),
        participants=", ".join(participants),
        time_range=f"{first} ~ {last}",
        first_session_date=first,
        last_session_date=last,
        aggregation_time=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        session_data=json.dumps(l1, ensure_ascii=False)[:120_000],
    )
    got = llm.complete_json(prompt, max_tokens=L2_MAX_TOKENS, context_id=f"L2:{sample_id}")
    if got is not None:
        got["_source_session_ids"] = [d.get("session_id") for d in l1]
    return got

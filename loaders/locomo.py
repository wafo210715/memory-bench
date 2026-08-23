# locomo.py：LoCoMo 数据加载器（Phase 2 入口）
# 源：snap-research/locomo data/locomo10.json（10 条 conversation 子集，粗结论尺寸）
# 职责：原始格式 → 统一内部 schema + 生成 add_conversation 调用序列（[日期]前缀在此层统一加，spec §7）
#
# LoCoMo 原始结构：
#   conversation: {speaker_a, speaker_b, session_N_date_time: "1:56 pm on 8 May, 2023",
#                  session_N: [{speaker, dia_id: "D1:1", text}]}
#   qa: [{question, answer, evidence: ["D1:3"], category: 1-5}]
#   category 权威映射（Mandol task_eval/generate_locomo_triple_excel.py:9，与数据对齐验证）：
#     1=Multi-hop 2=Temporal 3=Open-domain 4=Single-hop 5=Adversarial
#     category=5 无 answer 字段、用 adversarial_answer；mem0 原版判分排除 cat5（evaluation.py:747）
#
# 统一 schema：
#   {conversation_id, speakers, sessions: [{session_id, date_time_iso, turns: [{speaker, dia_id, text}]}],
#    qa: [{question, answer, evidence, category}]}

import json
import re
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# "1:56 pm on 8 May, 2023" / "10:30 am on 15 June, 2023" / "N/A"
_DT = re.compile(r"(?:(\d{1,2}):(\d{2})\s*(am|pm)\s+)?on\s+(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})")
_MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}


def parse_session_dt(raw: str) -> str | None:
    """LoCoMo 的 session 时间字符串 → ISO；解析失败返回 None（不阻塞，前缀退化为无日期）。"""
    if not raw:
        return None
    m = _DT.search(raw)
    if not m:
        return None
    hh, mm, ap, day, mon, year = m.groups()
    month = next((v for k, v in _MONTHS.items() if k.lower().startswith(mon.lower()[:3])), None)
    if month is None:
        return None
    hour = int(hh) if hh else 0
    if ap and ap.lower() == "pm" and hour != 12:
        hour += 12
    if ap and ap.lower() == "am" and hour == 12:
        hour = 0
    try:
        return datetime(int(year), month, int(day), hour, int(mm or 0)).isoformat()
    except ValueError:
        return None


CATEGORY_NAMES = {1: "multi-hop", 2: "temporal", 3: "open-domain", 4: "single-hop", 5: "adversarial"}


def load_locomo(path: Path | None = None) -> list[dict]:
    """加载并归一化。返回统一 schema 的 conversation 列表。"""
    p = path or REPO / "data" / "locomo" / "locomo10.json"
    raw = json.loads(p.read_text())
    out = []
    for conv in raw:
        c = conv["conversation"]
        cid = conv["sample_id"]
        sessions = []
        n = 1
        while f"session_{n}" in c:
            turns = [{"speaker": t["speaker"], "dia_id": t["dia_id"], "text": t["text"]}
                     for t in c[f"session_{n}"]]
            sessions.append({
                "session_id": f"{cid}_s{n:02d}",
                "date_time_iso": parse_session_dt(c.get(f"session_{n}_date_time", "")),
                "turns": turns,
            })
            n += 1
        out.append({
            "conversation_id": cid,
            "speakers": [c.get("speaker_a"), c.get("speaker_b")],
            "sessions": sessions,
            "qa": [{"question": q["question"],
                    "answer": q.get("answer") or q.get("adversarial_answer"),
                    "is_adversarial": q.get("category") == 5,
                    "evidence": q.get("evidence", []), "category": q.get("category")}
                   for q in conv.get("qa", [])],
        })
    return out


def session_to_add_conversation(session: dict, conversation_id: str) -> dict:
    """一个 LoCoMo session → 一次 add_conversation 调用参数。
    role 固定 user（LoCoMo 是双人对话非 user/assistant，speaker 名编进 content 防非标 role 兼容性问题）；
    [日期] 前缀在此统一加（harness 层职责，spec §7——修复各系统年份幻觉）。"""
    dt = session.get("date_time_iso")
    prefix = f"[{dt[:10]}] " if dt else ""
    return {
        "session_id": session["session_id"],
        "turns": [{"role": "user",
                   "content": f"{prefix}{t['speaker']}: {t['text']}",
                   "timestamp": dt}
                  for t in session["turns"]],
        "scope": {"kind": "user", "id": conversation_id},  # 对话间隔离
        "metadata": {"benchmark": "locomo"},
    }


def stats(convs: list[dict]) -> dict:
    n_sessions = sum(len(c["sessions"]) for c in convs)
    n_turns = sum(len(s["turns"]) for c in convs for s in c["sessions"])
    n_qa = sum(len(c["qa"]) for c in convs)
    cats: dict[int, int] = {}
    for c in convs:
        for q in c["qa"]:
            cats[q["category"]] = cats.get(q["category"], 0) + 1
    return {"conversations": len(convs), "sessions": n_sessions, "turns": n_turns,
            "qa": n_qa, "qa_by_category": dict(sorted(cats.items()))}


if __name__ == "__main__":
    convs = load_locomo()
    s = stats(convs)
    print(json.dumps(s, ensure_ascii=False, indent=2))
    # 抽一个 session 验证 add_conversation 参数形状
    demo = session_to_add_conversation(convs[0]["sessions"][0], convs[0]["conversation_id"])
    print("\nsession→add_conversation 示例（首 turn）:")
    print(json.dumps({**demo, "turns": demo["turns"][:1]}, ensure_ascii=False, indent=2)[:400])
    no_dt = [s2 for c in convs for s2 in c["sessions"] if not s2["date_time_iso"]]
    print(f"\n时间解析失败 session 数: {len(no_dt)}/{s['sessions']}")

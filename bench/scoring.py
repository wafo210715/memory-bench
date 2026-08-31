# scoring.py：双轨判分（bench-design §6）——轨 1 本地词级 F1（免费确定性），轨 2 LLM-judge（主表口径）
# F1 为 SQuAD 式：小写、去冠词、去标点后词袋重叠；multi-answer 取 max；cat5 adversarial 不算 F1（None）。

from __future__ import annotations

import json
import re
from collections import Counter

# ---------- 答题 prompt（bench-design §5；全臂一致，full-context 仅 evidence 段不同） ----------

ANSWER_SYSTEM = (
    "You answer questions about a two-person conversation history, using ONLY the evidence "
    'provided. If the evidence does not contain the answer, reply exactly "Invalid question" '
    "(some questions are designed to be unanswerable). Answer concisely.\n"
    'Reply in JSON: {"answer": "...", "quote": "<short supporting quote or null>"}'
)


def answer_user(evidence_text: str, question: str) -> str:
    return f"## Evidence\n{evidence_text}\n\n## Question\n{question}\n\nReply in JSON."


# ---------- 判分 prompt（bench-design §6.2） ----------

JUDGE_SYSTEM = (
    "You grade answers against a gold answer. Output JSON "
    '{"correct": 0 or 1, "reason": "<one line>"}.\n'
    "Rules: semantically equivalent = correct; partial = incorrect (strict); "
    "if gold indicates the question is unanswerable/invalid, correct only when "
    'the answer also refuses ("Invalid question" or equivalent refusal).'
)


def judge_user(question: str, gold: str, prediction: str) -> str:
    return f"Question: {question}\nGold: {gold}\nPrediction: {prediction}"


# ---------- JSON 解析（容错：取首个 JSON 对象） ----------

def parse_json_loose(text: str) -> dict | None:
    if not text:
        return None
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(text[start : i + 1])
                    return obj if isinstance(obj, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def parse_answer(text: str) -> dict | None:
    obj = parse_json_loose(text)
    if obj and isinstance(obj.get("answer"), str):
        return obj
    return None


def parse_judge(text: str) -> dict | None:
    obj = parse_json_loose(text)
    if obj and obj.get("correct") in (0, 1, "0", "1"):
        obj["correct"] = int(obj["correct"])
        return obj
    return None


# ---------- 轨 1：SQuAD 式词级 F1 ----------

_ARTICLES = re.compile(r"\b(a|an|the)\b", flags=re.IGNORECASE)
_NON_ALNUM = re.compile(r"[^a-z0-9\u4e00-\u9fff ]")


def _norm_tokens(s: str) -> list[str]:
    s = _ARTICLES.sub(" ", s.lower())
    s = _NON_ALNUM.sub(" ", s)
    return s.split()


def f1_single(pred: str, gold: str) -> float:
    pt, gt = _norm_tokens(pred), _norm_tokens(gold)
    if not pt or not gt:
        return 1.0 if not pt and not gt else 0.0
    common = Counter(pt) & Counter(gt)
    ns = sum(common.values())
    if ns == 0:
        return 0.0
    precision = ns / len(pt)
    recall = ns / len(gt)
    return 2 * precision * recall / (precision + recall)


def f1_score(pred: str, golds) -> float:
    """multi-answer 取 max（LoCoMo answer 是数组）。

    ⚠️ gold 不一定是 str：LoCoMo 全量 1986 题里有 6 题的 answer 是 **int**（如 2022、2，全在
    conv-26）。旧实现只判 isinstance(golds, str)，int 会落到迭代分支 → TypeError → 整个
    Phase B 崩掉。历史 run 只跑过 conv-30/41/42，所以这个雷到 2026-08-29 首次全量跑才引爆。
    统一归一成 str；同时排掉 None（str(None)=="None" 会污染 F1）。
    """
    if not isinstance(golds, (list, tuple)):
        golds = [golds]
    return max(
        (f1_single(pred, str(g)) for g in golds if g is not None and str(g).strip()),
        default=0.0,
    )

#!/usr/bin/env python3
"""按 conv 集合切片对比多个 run 的 judge_acc（cat1-4 主表口径，cat5 单列）。

用途：intent-baseline-3conv 出分后，与已有 run 的对手臂在同一 conv 集合上并表。
  .venv/bin/python scripts/slice_anchors.py \
      --convs conv-26,conv-30,conv-49 \
      --runs intent-baseline-3conv,locomo-r2-n3,mandol-full-10conv,amem-ab-3conv

口径与 report-2026-09-04 一致：per-rep 求均值 → 跨 rep mean±std；
不足 n=3 或 conv 覆盖不全的臂照常输出但标注 coverage，由人判断可不可比。
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# 锚点 run 的 answers.jsonl 是 untracked，不随 worktree checkout 走（审查 MAJOR-3）：
# 默认同时查本 worktree 与主仓的 runs/，同名 run 以先命中者为准（worktree 优先）。
DEFAULT_ROOTS = [REPO / "runs", Path("/Users/guanhongli/Documents/repo/memory-bench/runs")]
CATS = {1: "multi-hop", 2: "temporal", 3: "open-domain", 4: "single-hop"}


def find_answers(run_id: str, roots: list[Path]) -> Path | None:
    for root in roots:
        p = root / run_id / "answers.jsonl"
        if p.exists():
            return p
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--convs", default="conv-26,conv-30,conv-49")
    ap.add_argument("--runs", required=True, help="逗号分隔 run-id 列表")
    ap.add_argument("--runs-root", action="append", default=None,
                    help="额外 runs 根目录（可多次传入）；缺省查本 worktree 与主仓的 runs/")
    args = ap.parse_args()
    roots = [Path(r) for r in args.runs_root] if args.runs_root else DEFAULT_ROOTS
    convs = set(args.convs.split(","))

    # (arm, rep) -> [correct...]；(arm, rep, cat) -> [correct...]
    per_rep: dict[tuple[str, int], list[int]] = defaultdict(list)
    per_cat: dict[tuple[str, int, int], list[int]] = defaultdict(list)
    per_rep5: dict[tuple[str, int], list[int]] = defaultdict(list)
    src: dict[str, str] = {}

    for run_id in args.runs.split(","):
        p = find_answers(run_id, roots)
        if p is None:
            print(f"⚠️  {run_id}: 在 {[str(r) for r in roots]} 均无 answers.jsonl，跳过")
            continue
        print(f"  {run_id} ← {p}")
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("conv") not in convs:
                continue
            arm, rep, cat = r.get("arm"), r.get("rep", 0), r.get("category")
            correct = 1 if r.get("judge_correct") in (1, True) else 0
            src.setdefault(arm, run_id)
            if cat == 5:
                per_rep5[(arm, rep)].append(correct)
                continue
            per_rep[(arm, rep)].append(correct)
            per_cat[(arm, rep, cat)].append(correct)

    arms = sorted({a for a, _ in per_rep}, key=lambda a: -_mean_of_reps(per_rep, a))
    print(f"\n== 切片：{sorted(convs)}，cat1-4 主表（judge_acc %），cat5 单列 ==\n")
    hdr = ["arm", "src-run", *CATS.values(), "ALL(1-4)", "±std", "reps", "n/rep", "cat5"]
    print(" | ".join(hdr))
    print(" | ".join(["---"] * len(hdr)))
    for arm in arms:
        reps = sorted(r for a, r in per_rep if a == arm)
        rep_means = [100 * statistics.mean(per_rep[(arm, r)]) for r in reps]
        allm = statistics.mean(rep_means)
        std = statistics.stdev(rep_means) if len(rep_means) > 1 else 0.0
        cats = []
        for c in CATS:
            cm = [100 * statistics.mean(per_cat[(arm, r, c)]) for r in reps if per_cat.get((arm, r, c))]
            cats.append(f"{statistics.mean(cm):.1f}" if cm else "—")
        c5 = [100 * statistics.mean(per_rep5[(arm, r)]) for r in reps if per_rep5.get((arm, r))]
        c5s = f"{statistics.mean(c5):.1f}" if c5 else "—"
        n_per_rep = len(per_rep[(arm, reps[0])]) if reps else 0
        print(f"{arm} | {src.get(arm,'?')} | " + " | ".join(cats) +
              f" | **{allm:.1f}** | ±{std:.1f} | {len(reps)} | {n_per_rep} | {c5s}")
    print("\n注意：n/rep 不一致的臂不可直接横比（覆盖不全或题目交集不同）；"
          "正式并表前按 report-2026-09-04 §6 逐项核对口径。")


def _mean_of_reps(per_rep, arm) -> float:
    import statistics as st
    reps = [r for a, r in per_rep if a == arm]
    if not reps:
        return 0.0
    return st.mean(100 * st.mean(per_rep[(arm, r)]) for r in set(reps))


if __name__ == "__main__":
    main()

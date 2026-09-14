#!/usr/bin/env python3
"""为新 run-id 预置 ingest 进度：复用已入库的共享 state，跳过重复 LLM 重灌。

用法：
  .venv/bin/python scripts/seed_progress.py \
      --from-run intent-baseline-3conv --to-run intent-facts-3conv --arms intent_facts

原理：runner 的 ingest_system 按 progress.json 判断"已灌完"；intent 三臂共享同一个
STATE_DIR（.state/intent），因此把源 run 里任一臂的 conv→sessions 映射复制给目标臂，
再用 `python main.py run --run-id <to-run> --resume ...` 启动即可直接进 evidence 阶段。
（快照命名空间错位问题——审查 MAJOR-4——的零代码绕行。）

前提：目标臂与源臂共享同一 STATE_DIR，且 state 仍在磁盘上（未被 reset）。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-run", required=True)
    ap.add_argument("--to-run", required=True)
    ap.add_argument("--arms", required=True, help="逗号分隔的目标臂名")
    args = ap.parse_args()

    src = REPO / "runs" / args.from_run / "ingest_progress" / "progress.json"
    if not src.exists():
        raise SystemExit(f"源 run 无 progress.json: {src}")
    progress = json.loads(src.read_text())
    if not progress:
        raise SystemExit("源 progress.json 为空")
    donor_arm = next(iter(progress))
    mapping = progress[donor_arm]
    n_sessions = sum(len(v) for v in mapping.values())

    dst_dir = REPO / "runs" / args.to_run
    (dst_dir / "ingest_progress").mkdir(parents=True, exist_ok=True)
    (dst_dir / "evidence").mkdir(parents=True, exist_ok=True)
    dst = dst_dir / "ingest_progress" / "progress.json"
    seeded = json.loads(dst.read_text()) if dst.exists() else {}
    for arm in args.arms.split(","):
        seeded[arm.strip()] = mapping
    dst.write_text(json.dumps(seeded, ensure_ascii=False, indent=2))
    print(f"已预置 {args.to_run} ← {donor_arm}@{args.from_run}（{len(mapping)} conv / {n_sessions} sessions）"
          f" → 臂: {args.arms}；启动请带 --resume")


if __name__ == "__main__":
    main()

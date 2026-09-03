#!/usr/bin/env python
"""只做 ingest：把尚未灌入的 conversation 补进 mandol，并刷新快照。

为什么不能用 `runner --ingest-only`：
  该参数只跳过 Phase B 答题，**Phase A 的全部检索照跑**（runner.py:473），
  全量下就是 5,958 次检索约 16.6 小时——不是我们这一步想要的。

为什么必须与三塔构建分开：
  `ingest_system` 结尾的 snapshot 用 `timeout=600`（runner.py:186），
  而 TOWERS_ON=1 时 snapshot 会先跑 `_build_towers()`——7 个 conv 约 2 小时，
  必然超时，且是在灌完一小时之后才炸。故本脚本强制 TOWERS=0，
  建塔交给 scripts/build_mandol_towers.py（那边 timeout=36000）。

顺带产出 runner 可直接使用的 progress.json，使后续考试 run 的 pending 为空
→ 走 restore 分支，不会重新 ingest 把增强后的 L0 覆盖回原文。

用法：
    .venv/bin/python scripts/ingest_mandol_full.py --run-id mandol-full-10conv
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from loaders.locomo import load_locomo, session_to_add_conversation  # noqa: E402
from smoke_test import SERVERS, load_dotenv, parse  # noqa: E402

SNAP_TAG = "locomo_full"


async def main(run_id: str, tag: str) -> int:
    load_dotenv()
    # ❗ 必须关：否则 snapshot 会触发 _build_towers，本步骤只想灌数据
    os.environ["MEMBENCH_MANDOL_TOWERS"] = "0"
    os.environ.setdefault("MEMBENCH_MANDOL_SPARSE", "1")

    convs = load_locomo()
    cfg = SERVERS["mandol"]
    env = {k: v for k, v in os.environ.items()
           if k.startswith(("MEMBENCH_", "SILICONFLOW_", "OPENAI_", "HF_", "HUGGING_FACE_"))}
    config = {"mcpServers": {"mandol": {"command": cfg["command"], "args": cfg["args"],
                                        "env": env}}}
    from fastmcp import Client

    t0 = time.perf_counter()
    async with Client(config) as c:
        r = parse(await c.call_tool("restore", {"tag": tag}, timeout=1800))
        print(f"restore({tag}) ok={r.get('ok')}", flush=True)

        # ❗ 不能从 stats 取：它只暴露 mandol.n_scopes（计数），没有 scope_ids（server.py:331）。
        # 曾因此误判为空集，导致重灌已建塔的 conv，差点把增强后的 L0 覆盖成原文。
        state_dir = Path(os.environ.get("MEMBENCH_STATE_DIR") or (REPO / ".state")) / "mandol"
        scopes_f = state_dir / "scopes.json"
        have = set(json.loads(scopes_f.read_text()).get("scope_ids") or []) if scopes_f.exists() else set()

        # 安全网：有塔 marker 就意味着该 conv 的 L0 已被 God Mode 改写，
        # add_conversation 同 uid 即覆盖，重灌会静默销毁它。宁可中止也不覆盖。
        built = {p.name[:-len(".done.json")] for p in (state_dir / "towers").glob("*.done.json")}
        print(f"已有 scope（{len(have)}）：{sorted(have)}", flush=True)
        print(f"已建塔（{len(built)}）：{sorted(built)}", flush=True)
        if built - have:
            print(f"❌ 不一致：有塔 marker 但不在 scope 里：{sorted(built - have)}", file=sys.stderr)
            return 1
        if not have:
            print("⚠️  scopes.json 为空，将从零灌入全部 conv", flush=True)

        progress: dict[str, list[str]] = {}
        n_turns = 0
        for conv in convs:
            cid = conv["conversation_id"]
            sids = [s["session_id"] for s in conv["sessions"]]
            if cid in have or cid in built:
                progress[cid] = sids          # 已灌，登记进度即可
                print(f"  · {cid} 已存在，跳过", flush=True)
                continue
            for s in conv["sessions"]:
                payload = session_to_add_conversation(s, cid)
                rr = parse(await c.call_tool("add_conversation", payload, timeout=1800))
                n_turns += rr.get("accepted_turns", 0)
                progress.setdefault(cid, []).append(s["session_id"])
            print(f"  ✅ {cid} 灌完（{len(conv['sessions'])} sessions）", flush=True)

        r = parse(await c.call_tool("snapshot", {"tag": tag}, timeout=3600))
        st = parse(await c.call_tool("stats", {}))
        m = st.get("mandol") or {}
        print(f"\nsnapshot ok={r.get('ok')} · 新增 {n_turns} turns · "
              f"耗时 {time.perf_counter() - t0:.0f}s", flush=True)
        print(f"scope 数 {m.get('n_scopes')} · n_memories {st.get('n_memories')}", flush=True)

    out = REPO / "runs" / run_id / "ingest_progress"
    out.mkdir(parents=True, exist_ok=True)
    (out / "progress.json").write_text(
        json.dumps({"mandol": progress}, ensure_ascii=False, indent=2))
    (REPO / "runs" / run_id / "evidence").mkdir(parents=True, exist_ok=True)
    print(f"progress.json → {out/'progress.json'}（{len(progress)} conv）", flush=True)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--tag", default=SNAP_TAG)
    sys.exit(asyncio.run(main(ap.parse_args().run_id, ap.parse_args().tag)))

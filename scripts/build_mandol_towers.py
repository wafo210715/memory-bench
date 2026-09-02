#!/usr/bin/env python
"""在已 ingest 的 mandol 状态上触发三塔构建（Phase 2）。

复用现有 .state/mandol（已灌好的 L0），不重新 ingest——省掉一次全量 embedding。
构建走 server 的 snapshot 钩子（TOWERS_ON=1 时在落盘前触发），
与 runner Phase A「灌完 → snapshot」的语义一致。

断点续跑：conversation 粒度，已完成的 conv 有 .done.json 标记，重跑自动跳过。

用法：
    .venv/bin/python scripts/build_mandol_towers.py [--tag locomo_full]
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

from smoke_test import SERVERS, load_dotenv, parse  # noqa: E402


async def main(tag: str) -> int:
    load_dotenv()
    os.environ["MEMBENCH_MANDOL_TOWERS"] = "1"
    cfg = SERVERS["mandol"]
    env = {k: v for k, v in os.environ.items()
           if k.startswith(("MEMBENCH_", "SILICONFLOW_", "OPENAI_", "HF_", "HUGGING_FACE_"))}
    config = {"mcpServers": {"mandol": {"command": cfg["command"], "args": cfg["args"],
                                        "env": env}}}
    from fastmcp import Client

    t0 = time.perf_counter()
    async with Client(config) as c:
        st = parse(await c.call_tool("stats", {}))
        print(f"构建前：n_memories={st.get('n_memories')} "
              f"scopes={st.get('mandol', {}).get('n_scopes')}", flush=True)

        print(f"→ snapshot('{tag}') 触发三塔构建，进度见 stderr …", flush=True)
        r = parse(await c.call_tool("snapshot", {"tag": tag}, timeout=36000))
        print(f"snapshot ok={r.get('ok')}  耗时 {time.perf_counter() - t0:.0f}s", flush=True)

        st = parse(await c.call_tool("stats", {}))
        towers = st.get("mandol", {}).get("towers", {})
        print("\n=== 三塔构建结果 ===", flush=True)
        for scope, d in (towers.get("detail") or {}).items():
            if d.get("error"):
                print(f"  ❌ {scope}: {d['error']}")
                continue
            print(f"  ✅ {scope}: L0 {d['l0_rewritten']}/{d['l0_messages']} 改写 · "
                  f"覆盖 {d['l0_text_overwritten']} · 时序边 {d['temporal_edges']}")
            print(f"     L1 {d['l1_sessions']} session · L2 {'✓' if d['l2'] else '✗'} · "
                  f"抽象 {d['hierarchical']['units']} 单元 {d['hierarchical']['edges']} 溯源边")
            print(f"     episodic {d['episodic']['units']} 事实 {d['episodic']['edges']} 边 · "
                  f"kg {d['kg']['units']} 实体 {d['kg']['edges']} 边")
            print(f"     LLM {d['llm']['calls']} 次 · "
                  f"in {d['llm']['tokens_in']:,} / out {d['llm']['tokens_out']:,} · "
                  f"失败 {d['llm']['failures']} · {d['elapsed_s']}s")
        Path("/tmp/towers_result.json").write_text(
            json.dumps(towers, ensure_ascii=False, indent=2))
        print("\n完整结果 → /tmp/towers_result.json", flush=True)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="locomo_full")
    sys.exit(asyncio.run(main(ap.parse_args().tag)))

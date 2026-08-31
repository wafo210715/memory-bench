#!/usr/bin/env python
"""amem native vs amem_fixed 行为对照验证（走真实 MCP stdio，不是单测桩）。

逐条验证 2026-08-30 讨论的修复目标是否真的在 MCP 层面生效：
  F3    向量含 keywords/tags/context —— 用「content 相同、语义描述不同」无法直接测 MCP，
        改为间接证据：fixed 臂 embed_calls>0（云端 embedding-3 被真正调用）
  F5    evolution 落到真实邻居 —— 检查 note 的 context 是否被改写（native 因 bug 改错对象，
        表现为最早插入的几条被改；fixed 应改在语义邻居上）
  F8    沿链邻居进入结果 —— native_notes 里的 `F8: 沿链邻居 n/N`
  F9    context 拼进 envelope.text —— 检查 text 里是否出现〔…〕
  F-emb embedding-3 生效 —— stats.embed_calls / embed_tokens

用法：
    .venv-amem/bin/python scripts/verify_amem_fixed.py            # 两臂都跑
    .venv-amem/bin/python scripts/verify_amem_fixed.py amem_fixed # 只跑一臂
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import yaml
from fastmcp import Client

SERVERS = yaml.safe_load((REPO / "servers.yaml").read_text())["servers"]


def load_dotenv(path: Path | None = None) -> None:
    p = path or REPO / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_dotenv()

# 刻意构造：前 4 turn 讲同一件事（露营装备），后 4 turn 完全无关，
# 这样「语义邻居」与「最早插入的前 k 条」是两个不同集合 —— F5 的判别关键。
TURNS = [
    {"role": "user", "content": "[2023-05-08] Ann: I'm planning a camping trip to Yosemite next month",
     "timestamp": "2023-05-08T10:00:00"},
    {"role": "user", "content": "[2023-05-08] Ben: Nice! Do you have a proper sleeping bag for the cold nights?",
     "timestamp": "2023-05-08T10:01:00"},
    {"role": "user", "content": "[2023-05-08] Ann: I bought a down sleeping bag rated to minus 5 degrees",
     "timestamp": "2023-05-08T10:02:00"},
    {"role": "user", "content": "[2023-05-08] Ben: Good choice, also bring a foam pad for insulation from the ground",
     "timestamp": "2023-05-08T10:03:00"},
    {"role": "user", "content": "[2023-05-09] Ann: By the way my sister just got a job at a law firm in Chicago",
     "timestamp": "2023-05-09T11:00:00"},
    {"role": "user", "content": "[2023-05-09] Ben: That is great news, is she specialising in corporate law?",
     "timestamp": "2023-05-09T11:01:00"},
    {"role": "user", "content": "[2023-05-10] Ann: I finally finished reading that book about quantum mechanics",
     "timestamp": "2023-05-10T09:00:00"},
    {"role": "user", "content": "[2023-05-10] Ben: Was it the one by Carlo Rovelli? I heard it is quite poetic",
     "timestamp": "2023-05-10T09:01:00"},
]
QUERY = "what camping gear did Ann prepare for the cold"


def parse(r):
    if hasattr(r, "content") and r.content:
        return json.loads(r.content[0].text)
    return r.data if hasattr(r, "data") else r


async def run_arm(system: str) -> dict:
    cfg = SERVERS[system]
    missing = [k for k in cfg.get("env_required", []) if not os.environ.get(k)]
    if missing:
        return {"system": system, "error": f"缺环境变量 {missing}"}

    child_env = {k: v for k, v in os.environ.items()
                 if k.startswith(("MEMBENCH_", "SILICONFLOW_", "OPENAI_"))}
    config = {"mcpServers": {system: {"command": cfg["command"], "args": cfg["args"], "env": child_env}}}

    out: dict = {"system": system}
    async with Client(config) as client:
        await client.call_tool("reset", {})

        t0 = time.perf_counter()
        r = parse(await client.call_tool("add_conversation", {
            "session_id": "amemfix_s1", "turns": TURNS,
            "scope": {"kind": "user", "id": "amemfix_user"},
        }, timeout=600))
        out["ingest_ms"] = int((time.perf_counter() - t0) * 1000)
        out["accepted"] = r.get("accepted_turns")
        out["ingest_notes"] = r.get("native_notes", "")

        r = parse(await client.call_tool("retrieve", {
            "query": QUERY, "query_mode": "fixed", "top_k": 5,
        }, timeout=300))
        results = r.get("results", [])
        out["n_results"] = len(results)
        out["retrieve_notes"] = r.get("native_notes", "")
        out["texts"] = [x.get("text", "") for x in results]
        out["has_ctx_marker"] = sum(1 for t in out["texts"] if "〔" in t)

        out["stats"] = parse(await client.call_tool("stats", {}))
    return out


def report(res: dict) -> None:
    s = res["system"]
    print("=" * 84)
    print(f"  {s}")
    print("=" * 84)
    if res.get("error"):
        print(f"  ✗ {res['error']}")
        return
    st = res.get("stats", {})
    print(f"  mode                 : {st.get('mode')}")
    print(f"  ingest               : accepted={res['accepted']}  {res['ingest_ms']}ms")
    print(f"    native_notes       : {res['ingest_notes']}")
    print(f"  retrieve             : {res['n_results']} 条")
    print(f"    native_notes       : {res['retrieve_notes'] or '(空)'}")
    print(f"  F9 context 进 text   : {res['has_ctx_marker']}/{res['n_results']} 条带〔…〕")
    print(f"  F-emb embed_calls    : {st.get('embed_calls', '—（native 用本地模型，无此计量）')}")
    print(f"        embed_tokens   : {st.get('embed_tokens', '—')}")
    ok, fail = st.get("n_evo_ok", 0), st.get("n_evo_fail", 0)
    tot = ok + fail
    rate = f"{fail / tot * 100:.0f}%" if tot else "—"
    print(f"  evolution            : llm_calls={st.get('n_evo_calls', st.get('n_llm_calls', '—'))} "
          f"ok={ok} fail={fail}  失败率={rate}")
    if "n_evo_fence_recoverable" in st:
        print(f"    其中仅 fence 可救  : {st['n_evo_fence_recoverable']}")
    if "n_construct_ok" in st:
        print(f"  F1 note construction : {st['n_construct_ok']} 次成功")
    if "n_links" in st:
        print(f"  F4 有效链接建立      : {st['n_links']} 条  (json_retry={st.get('n_json_retry', 0)})")
    print(f"\n  top-3 envelope.text:")
    for t in res["texts"][:3]:
        print(f"    {t[:150]}")
    print()


async def main() -> int:
    arms = sys.argv[1:] or ["amem", "amem_fixed"]
    results = []
    for a in arms:
        if a not in SERVERS:
            print(f"✗ 未知 arm: {a}（可选 {list(SERVERS)}）")
            return 2
        print(f"\n>>> 跑 {a} …（含真实 LLM/embedding 调用，请稍候）")
        try:
            results.append(await run_arm(a))
        except Exception as e:
            results.append({"system": a, "error": repr(e)})
    print()
    for r in results:
        report(r)

    # 对照结论
    by = {r["system"]: r for r in results}
    if "amem" in by and "amem_fixed" in by and not by["amem"].get("error") and not by["amem_fixed"].get("error"):
        print("=" * 84)
        print("  对照结论")
        print("=" * 84)
        nat, fix = by["amem"], by["amem_fixed"]
        print(f"  F8 沿链邻居   native: {nat['retrieve_notes'] or '无此字段（原生不上报）'}")
        print(f"                fixed : {fix['retrieve_notes']}")
        print(f"  F9 context    native: {nat['has_ctx_marker']}/{nat['n_results']}   "
              f"fixed: {fix['has_ctx_marker']}/{fix['n_results']}")
        print(f"  F-emb 云端调用 native: {nat['stats'].get('embed_calls', 0)}   "
              f"fixed: {fix['stats'].get('embed_calls', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

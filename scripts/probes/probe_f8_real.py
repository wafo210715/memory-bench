#!/usr/bin/env python
"""F8 真实数据探针：用 LoCoMo 真实对话 + 真实 QA，统计沿链扩展到底有没有动静。

不跑完整 runner（一个 conv 要 1.5-3 小时），只灌前若干 session + 抽样 QA 检索，
目的就一个：回答「F8 在真实数据上触发率是多少」。顺带拿到 F1/F4/F5 的真实统计。

    .venv-amem/bin/python scripts/probe_f8_real.py [conv-30] [n_sessions] [n_queries]
"""
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.chdir(REPO)
for line in (REPO / ".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

CONV = sys.argv[1] if len(sys.argv) > 1 else "conv-30"
N_SESS = int(sys.argv[2]) if len(sys.argv) > 2 else 6
N_Q = int(sys.argv[3]) if len(sys.argv) > 3 else 30
TOP_K = int(os.environ.get("PROBE_TOP_K", "20"))
MODE = os.environ.get("MEMBENCH_AMEM_MODE", "fixed")
os.environ["MEMBENCH_AMEM_MODE"] = MODE

from loaders.locomo import load_locomo, session_to_add_conversation  # noqa: E402
from servers.amem import server as S  # noqa: E402

raw = lambda f: getattr(f, "fn", None) or f  # noqa: E731
add_conv, retrieve, reset, stats = raw(S.add_conversation), raw(S.retrieve), raw(S.reset), raw(S.stats)

conv = next(c for c in load_locomo() if c["conversation_id"] == CONV)
sessions = conv["sessions"][:N_SESS]
n_turns = sum(len(s["turns"]) for s in sessions)
print(f"=== {MODE} 臂 | {CONV} | 前 {len(sessions)} session / {n_turns} turns | top_k={TOP_K} ===", flush=True)

print("\n--- reset ---", flush=True)
reset()

print(f"--- ingest {n_turns} turns（每 turn 含 LLM 调用，预计 {n_turns * 12 // 60}-{n_turns * 20 // 60} 分钟）---", flush=True)
t0 = time.perf_counter()
done = 0
for si, s in enumerate(sessions):
    payload = session_to_add_conversation(s, CONV)
    r = add_conv(session_id=payload["session_id"], turns=payload["turns"],
                 scope=payload["scope"], metadata=payload.get("metadata"))
    done += r["accepted_turns"]
    el = time.perf_counter() - t0
    print(f"  session {si + 1}/{len(sessions)}  +{r['accepted_turns']} turns  "
          f"累计 {done}/{n_turns}  {el / 60:.1f}min  ({r.get('native_notes', '')[:60]})", flush=True)

print(f"\n--- ingest 完成 {(time.perf_counter() - t0) / 60:.1f} min ---", flush=True)

st = stats()
print(f"  evolution      : ok={st.get('n_evo_ok')} fail={st.get('n_evo_fail')} "
      f"llm_calls={st.get('n_llm_calls')}")
print(f"  F1 construct   : {st.get('n_construct_ok', '—')}")
print(f"  F4 links 建立  : {st.get('n_links', '—')}  (json_retry={st.get('n_json_retry', '—')})")
print(f"  embed          : calls={st.get('embed_calls')} tokens={st.get('embed_tokens')}")

# links 分布（直接看内存里的 note）
sysm = S._get_system(CONV)
n_with = sum(1 for m in sysm.memories.values() if getattr(m, "links", None))
tot_links = sum(len(getattr(m, "links", []) or []) for m in sysm.memories.values())
valid = sum(1 for m in sysm.memories.values()
            for l in (getattr(m, "links", []) or []) if l in sysm.memories)
print(f"  links 分布     : {n_with}/{len(sysm.memories)} 条 note 有 link；"
      f"共 {tot_links} 条，其中指向真实存在记忆的 {valid} 条")

print(f"\n--- 抽样 {N_Q} 个真实 QA 检索，统计 F8 ---", flush=True)
qas = conv["qa"][:N_Q]
hit_q, tot_nb, tot_res = 0, 0, 0
for i, qa in enumerate(qas):
    # 走 retrieve 工具（端到端，含 envelope 渲染）
    r = retrieve(query=qa["question"], query_mode="fixed", top_k=TOP_K)
    res = r.get("results", [])
    tot_res += len(res)
    # is_neighbor 在 envelope 层会被丢弃，而 native 臂的 native_notes 也不带该字段，
    # 所以直接从 search_agentic 取——两臂同口径，才能真实对比。
    nb = sum(1 for x in sysm.search_agentic(qa["question"], k=TOP_K) if x.get("is_neighbor"))
    tot_nb += nb
    if nb:
        hit_q += 1
    if i < 5:
        print(f"  q{i}: {qa['question'][:52]!r} → {len(res)} 条，邻居 {nb}", flush=True)

print(f"\n{'=' * 70}")
print(f"  F8 触发率     : {hit_q}/{len(qas)} 个 query 的结果里含沿链邻居")
print(f"  邻居总数      : {tot_nb} 条 / 共返回 {tot_res} 条 "
      f"({tot_nb / tot_res * 100 if tot_res else 0:.1f}%)")
print(f"{'=' * 70}")

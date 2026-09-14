# memharness 端到端验证：走完整 MCP 工具链，用真实 LoCoMo 数据（英文）核对契约与机制。
#
# 存在理由：smoke 的样本是中文，而上游 MemHarness 的蒸馏/重构 prompt 全是英文且论文把
# 「strict English output」写进 format reward，两层都会把中文记忆改写成英文 —— smoke 步骤 8 的
# 中文关键词断言因此不成立。本脚本在目标语料域（英文 LoCoMo）上重做同等强度的检查，
# 并把 scope 隔离改用 memory_id 前缀这一硬证据判定，不依赖任何关键词匹配。
#
# 用法：.venv/bin/python servers/memharness/e2e_verify.py [conv_index_a] [conv_index_b]

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import yaml
from fastmcp import Client

from loaders.locomo import load_locomo, session_to_add_conversation
from servers.common.envelope import MAX_CHARS
from smoke_test import load_dotenv, parse

load_dotenv()
# 用独立的 state 目录：本脚本会反复 reset，若跑在共享的 .state/memharness 上，
# 正式 ingest 完成后误跑一次就会把当前状态清掉。
STATE_DIR = REPO / ".state-e2e-memharness"
os.environ["MEMBENCH_STATE_DIR"] = str(STATE_DIR)

CFG = yaml.safe_load((REPO / "servers.yaml").read_text())["servers"]["memharness"]
CHILD_ENV = {k: v for k, v in os.environ.items() if k.startswith(("MEMBENCH_", "OPENAI_"))}
TOP_K = 20


def _config(adaptor: str) -> dict:
    env = dict(CHILD_ENV)
    env["MEMBENCH_MEMHARNESS_ADAPTOR"] = adaptor
    return {"mcpServers": {"memharness": {"command": CFG["command"], "args": CFG["args"], "env": env}}}


CONFIG = _config("on")

_rows: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _rows.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main(idx_a: int, idx_b: int) -> int:
    convs = load_locomo()
    ca, cb = convs[idx_a], convs[idx_b]
    scope_a, scope_b = ca["conversation_id"], cb["conversation_id"]
    print(f"scope A = {scope_a}（前 2 个 session）｜ scope B = {scope_b}（第 1 个 session）\n")

    async with Client(CONFIG) as c:
        await c.call_tool("reset", {})

        # ---- ingest ----
        n_turns = 0
        for s in ca["sessions"][:2]:
            r = parse(await c.call_tool("add_conversation", session_to_add_conversation(s, scope_a)))
            n_turns += r.get("accepted_turns", 0)
            print(f"  ingest {s['session_id']}: {r.get('native_notes', '')}")
        rb = parse(await c.call_tool("add_conversation", session_to_add_conversation(cb["sessions"][0], scope_b)))
        print(f"  ingest {cb['sessions'][0]['session_id']}: {rb.get('native_notes', '')}\n")
        st = parse(await c.call_tool("stats", {}))
        check("ingest 落库", st["n_memories"] > 0, f"{st['n_memories']} 条记忆 / {st['n_sessions']} sessions / {n_turns} turns")

        # ---- 写入去重必须限在同一 scope 内（对话间隔离契约的写入侧回归）----
        # 把一段已灌过的会话原样灌进另一个 scope：若去重跨 scope 比，这一次会被全部跳过（增量 0），
        # 而 retrieve 又按 scope 过滤，新 scope 就永远拿不到证据且无告警
        before = st["n_memories"]
        dup = session_to_add_conversation(ca["sessions"][0], "dup_scope_probe")
        rdup = parse(await c.call_tool("add_conversation", dup))
        after = parse(await c.call_tool("stats", {}))["n_memories"]
        rdup2 = parse(await c.call_tool("retrieve", {
            "query": ca["qa"][0]["question"], "query_mode": "fixed", "top_k": TOP_K,
            "filter": {"scope_id": "dup_scope_probe"}}))
        check("写入去重不跨 scope", after > before and "INSERT_DEDUPED" not in rdup.get("native_notes", ""),
              f"重复灌入新 scope 后记忆数 {before}→{after}，新 scope 检索到 {len(rdup2['results'])} 条")

        # ---- retrieve：真实 QA 题，契约 + scope 隔离 ----
        qs = ca["qa"][:4]
        all_ok, bad, leaked_total, empty_q = True, [], 0, 0
        first_ids: set[str] = set()
        for i, q in enumerate(qs):
            r = parse(await c.call_tool("retrieve", {
                "query": q["question"], "query_mode": "fixed", "top_k": TOP_K,
                "filter": {"scope_id": scope_a}}))
            res = r["results"]
            if i == 0:
                first_ids = {e["memory_id"] for e in res}
            if not res:
                empty_q += 1
            for e in res:
                miss = [k for k in ("memory_id", "text", "source", "timestamp", "score", "raw_format") if k not in e]
                if miss:
                    bad.append(f"{e.get('memory_id')} 缺字段 {miss}")
                if len(e.get("text", "")) > MAX_CHARS:
                    bad.append(f"{e['memory_id']} text 超长 {len(e['text'])}")
            if len(res) > TOP_K:
                bad.append(f"q{i} 返回 {len(res)} 条 > top_k")
            leaked = [e for e in res if not e["memory_id"].startswith(f"{scope_a}::")]
            leaked_total += len(leaked)
            print(f"  q{i}(cat{q['category']}): 返回 {len(res)} 条｜{r['native_notes']}")
            if i == 0 and res:
                print(f"      样例 text: {res[0]['text'][:150]}")
        all_ok = not bad
        check("envelope 契约合规", all_ok, "; ".join(bad[:3]) if bad else f"{len(qs)} 题字段齐全、text ≤{MAX_CHARS}、条数 ≤top_k")
        check("scope 隔离（A 侧 id 前缀）", leaked_total == 0, f"跨 scope id {leaked_total} 条")
        # 这一条在 adaptor=on 下是概率性的：重构层有可能把一题的命中全部判拒
        check("A 侧无空召回", empty_q == 0, f"{empty_q}/{len(qs)} 题返回 0 条（重构层全拒时会出现，属机制行为）")

        # ---- B 侧自检：能检索到自己的内容，且不含 A 的 id ----
        rb2 = parse(await c.call_tool("retrieve", {
            "query": cb["qa"][0]["question"], "query_mode": "fixed", "top_k": TOP_K,
            "filter": {"scope_id": scope_b}}))
        b_res = rb2["results"]
        b_foreign = [e for e in b_res if not e["memory_id"].startswith(f"{scope_b}::")]
        check("scope 隔离（B 侧自检）", len(b_res) >= 1 and not b_foreign,
              f"B 返回 {len(b_res)} 条，其中非 B 的 id {len(b_foreign)} 条")
        if b_res:
            print(f"      B 样例 text: {b_res[0]['text'][:150]}")

        # ---- 重构层确定性观测：同 query 连跑 3 次，看最终 envelope 集合是否稳定 ----
        # 这不是断言而是量化观测：重构是 LLM 生成，temp=0 仍非确定，直接决定跨 rep 的 evidence 差异
        rep_sets = [first_ids]
        for _ in range(2):
            r = parse(await c.call_tool("retrieve", {
                "query": qs[0]["question"], "query_mode": "fixed", "top_k": TOP_K,
                "filter": {"scope_id": scope_a}}))
            rep_sets.append({e["memory_id"] for e in r["results"]})
        inter = set.intersection(*rep_sets)
        union = set.union(*rep_sets)
        print(f"\n  重构层确定性：同题 3 次返回 {[len(s) for s in rep_sets]} 条，"
              f"三次交集 {len(inter)} 条 / 并集 {len(union)} 条，逐字相同={rep_sets[0] == rep_sets[1] == rep_sets[2]}")

        # ---- 机制统计必须在 reset 之前读：reset 会清零探针与重构计数 ----
        st = parse(await c.call_tool("stats", {}))
        print(f"\n  机制统计（ingest {st['n_memories']} 条 + 上述全部 retrieve 的累计）：")
        print(f"    重构层 {json.dumps(st['adaptor'], ensure_ascii=False)}")
        print(f"    阈值探针 {json.dumps(st['threshold_probes'], ensure_ascii=False)}")
        print(f"    token {json.dumps(st['tokens_used'], ensure_ascii=False)}｜LLM 调用 {st['llm_calls']}")
        print(f"    配置 {json.dumps(st['config'], ensure_ascii=False)}")
        await c.call_tool("snapshot", {"tag": "e2e"})

    # ---- snapshot / restore：换 adaptor=off 的进程验，把存储恢复与重构层非确定性解耦 ----
    async with Client(_config("off")) as c2:
        r = parse(await c2.call_tool("retrieve", {
            "query": qs[0]["question"], "query_mode": "fixed", "top_k": TOP_K,
            "filter": {"scope_id": scope_a}}))
        base_ids = {e["memory_id"] for e in r["results"]}
        await c2.call_tool("reset", {})
        after_reset = parse(await c2.call_tool("stats", {}))["n_memories"]
        await c2.call_tool("restore", {"tag": "e2e"})
        r = parse(await c2.call_tool("retrieve", {
            "query": qs[0]["question"], "query_mode": "fixed", "top_k": TOP_K,
            "filter": {"scope_id": scope_a}}))
        back_ids = {e["memory_id"] for e in r["results"]}
        check("snapshot/restore 可复现（纯检索面）", bool(base_ids) and back_ids == base_ids,
              f"reset 后 {after_reset} 条；restore 后 id 集合一致={back_ids == base_ids}"
              f"（{len(back_ids)} vs {len(base_ids)} 条，非空集）")
        await c2.call_tool("reset", {})

    shutil.rmtree(STATE_DIR, ignore_errors=True)  # 不把 e2e 快照留给正式 run 的 stats().snapshots

    n_pass = sum(1 for _, ok, _ in _rows if ok)
    print(f"\n{'=' * 60}\n端到端验证：{n_pass}/{len(_rows)} 通过")
    return 0 if n_pass == len(_rows) else 1


if __name__ == "__main__":
    a = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    b = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    sys.exit(asyncio.run(main(a, b)))

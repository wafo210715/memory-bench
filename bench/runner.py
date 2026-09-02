# runner.py：LoCoMo forced-call 评测循环（bench-design §1/§4-§7）
#
# 用法：
#   .venv/bin/python -m bench.runner --arms mock,full_context --convs conv-30 --run-id shakeout
#   .venv/bin/python -m bench.runner --arms intent --convs conv-30 --run-id shakeout --resume
#   .venv/bin/python -m bench.runner --arms mem0 --ingest-only            # 只灌数据+snapshot
#
# 两阶段：
#   Phase A（串行，单 server）: ingest（断点续灌）→ snapshot("locomo_full") → 逐题 forced-call retrieve
#                               → evidence/<arm>.jsonl（含 envelope 原文，落盘可审计）
#   Phase B（16 并发）       : evidence → 答题（MEMBENCH_ANSWER_*，Anthropic 兼容）→ 双轨判分
#                               → answers.jsonl append-only
# 幂等键 = arm|conv|qa_id|rep；--resume 对两阶段各自跳过已完成行。

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml
from fastmcp import Client

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from loaders.locomo import load_locomo, session_to_add_conversation  # noqa: E402
from bench.llm import (LLMError, Suspended, answer_llm_from_env,  # noqa: E402
                       judge_llm_from_env, load_dotenv)
from bench import scoring  # noqa: E402

load_dotenv()  # 必须在任何 env 读取前

SNAP_TAG = "locomo_full"
SUSPEND_AFTER = 5  # 连续失败挂起阈值（bench-design §7）

SERVERS = yaml.safe_load((REPO / "servers.yaml").read_text())["servers"]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _endpoint_tag(url: str | None) -> str | None:
    """只取 host（+ /anthropic 这类协议面后缀）写进 manifest，不落盘 key。"""
    if not url:
        return None
    from urllib.parse import urlparse
    u = urlparse(url)
    return f"{u.netloc}{u.path.rstrip('/')}" or url


def _thinking_tag(on: bool) -> str:
    """on 时不传参数走 provider 默认态，写清楚以免事后无法复现。"""
    return "on(provider-default)" if on else "off(thinking.type=disabled)"


def parse(result) -> dict:
    data = getattr(result, "data", None)
    if isinstance(data, dict):
        return data
    raw = getattr(result, "content", None)
    if raw:
        return json.loads(raw[0].text)
    raise RuntimeError("工具返回为空")


async def acall(client: Client, tool: str, args: dict, timeout: float = 180.0) -> dict:
    r = await client.call_tool(tool, args, timeout=timeout)
    return parse(r)


def child_env() -> dict:
    """MCP stdio 子进程最小环境转发（与 scripts/smoke_test.py 同约定）。

    HF_/HUGGING_FACE_（2026-08-31 补）：mandol 的 SPLADE（naver/splade-v3，gated repo）
    与 cross-encoder 需 HF 鉴权；不转发则子进程拿不到 token → 401 → **静默降级**
    （SemanticMap 会 skip sparse embedding 而不报错）。
    """
    return {k: v for k, v in os.environ.items()
            if k.startswith(("MEMBENCH_", "SILICONFLOW_", "OPENAI_", "HF_", "HUGGING_FACE_"))}


def mcp_config(system: str) -> dict:
    cfg = SERVERS[system]
    return {"mcpServers": {system: {"command": cfg["command"], "args": cfg["args"],
                                    "env": child_env()}}}


# ---------- run 目录与幂等 ----------

class Run:
    def __init__(self, run_id: str, resume: bool) -> None:
        self.dir = REPO / "runs" / run_id
        self.answers = self.dir / "answers.jsonl"
        self.evidence = self.dir / "evidence"
        self.ingest = self.dir / "ingest_progress"
        self.manifest = self.dir / "manifest.json"
        if not resume:
            if self.dir.exists():
                sys.exit(f"run 目录已存在: {self.dir}（--resume 续跑或换 --run-id）")
            self.dir.mkdir(parents=True)
            self.evidence.mkdir()
            self.ingest.mkdir()

    def done_keys(self, path: Path) -> set[str]:
        if not path.exists():
            return set()
        keys = set()
        for line in path.read_text().splitlines():
            if line.strip():
                try:
                    keys.add(json.loads(line)["key"])
                except (json.JSONDecodeError, KeyError):
                    continue  # 残行（中断时半写）忽略，重写该行语义由 append 前跳过保证
        return keys

    def append(self, path: Path, obj: dict) -> None:
        with path.open("a") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def load_manifest(self) -> dict:
        return json.loads(self.manifest.read_text()) if self.manifest.exists() else {}

    def save_manifest(self, m: dict) -> None:
        self.manifest.write_text(json.dumps(m, ensure_ascii=False, indent=2))

    def load_progress(self) -> dict:
        p = self.ingest / "progress.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def save_progress(self, progress: dict) -> None:
        (self.ingest / "progress.json").write_text(json.dumps(progress, ensure_ascii=False, indent=2))


# ---------- Phase A：ingest + retrieve ----------

async def ingest_system(client: Client, system: str, convs: list[dict], run: Run,
                        progress: dict) -> dict:
    """断点续灌：progress[system] = {conv_id: [完成 session_id]}。add 非幂等，跳过已完成。"""
    sys_progress = progress.setdefault(system, {})
    state_root = Path(os.environ.get("MEMBENCH_STATE_DIR") or REPO / ".state")
    snap_dir = state_root / "__snapshots__" / system / SNAP_TAG
    ingested_convs = {c for c, sids in sys_progress.items()
                      if sids and len(sids) >= _conv_session_count(convs, c)}
    pending = [c for c in convs if c["conversation_id"] not in ingested_convs]

    if not pending:
        if snap_dir.exists():
            r = await acall(client, "restore", {"tag": SNAP_TAG})
            if r.get("ok"):
                print(f"  [{system}] 全部已灌，restore({SNAP_TAG}) OK")
                return {"ingested": 0, "restored": True}
            if r.get("error") == "SNAPSHOT_UNSUPPORTED":
                pass  # 慢路径：重灌（下方 pending 为空则说明状态已在，无需动作）
            else:
                sys.exit(f"  [{system}] restore 失败: {r}")
        return {"ingested": 0, "restored": False}

    # 有未完成 conv：先恢复到快照（若有），再补灌剩余
    if snap_dir.exists():
        r = await acall(client, "restore", {"tag": SNAP_TAG})
        if not r.get("ok") and r.get("error") != "SNAPSHOT_UNSUPPORTED":
            sys.exit(f"  [{system}] restore 失败: {r}")

    n_turns = 0
    for conv in pending:
        cid = conv["conversation_id"]
        done_sessions = set(sys_progress.get(cid, []))
        for session in conv["sessions"]:
            if session["session_id"] in done_sessions:
                continue
            payload = session_to_add_conversation(session, cid)
            r = await acall(client, "add_conversation", payload, timeout=600)
            n_turns += r.get("accepted_turns", 0)
            sys_progress.setdefault(cid, []).append(session["session_id"])
            run.save_progress(progress)
        print(f"  [{system}] {cid} 灌完（{len(conv['sessions'])} sessions）")

    r = await acall(client, "snapshot", {"tag": SNAP_TAG}, timeout=600)
    snap_ok = bool(r.get("ok"))
    print(f"  [{system}] 补灌 {len(pending)} conv / {n_turns} turns → snapshot {'OK' if snap_ok else r.get('error', 'FAIL')}")
    return {"ingested": n_turns, "restored": False}


def _conv_session_count(convs: list[dict], cid: str) -> int:
    for c in convs:
        if c["conversation_id"] == cid:
            return len(c["sessions"])
    return 10**9  # 不在本次列表里


async def evidence_for_arm(arm: str, convs: list[dict], run: Run, top_k: int, n: int) -> int:
    """Phase A 主函数：产出 evidence/<arm>.jsonl。full_context 臂不占 server。"""
    out = run.evidence / f"{arm}.jsonl"
    done = run.done_keys(out)
    todo = 0

    if arm == "full_context":
        for conv in convs:
            transcript = "\n".join(
                t["content"] for s in conv["sessions"]
                for t in session_to_add_conversation(s, conv["conversation_id"])["turns"])
            for qi, qa in enumerate(conv["qa"]):
                for rep in range(n):
                    key = f"full_context|{conv['conversation_id']}|q{qi}|rep{rep}"
                    if key in done:
                        continue
                    todo += 1
                    run.append(out, {
                        "key": key, "arm": "full_context", "conv": conv["conversation_id"],
                        "qa_id": f"q{qi}", "category": qa["category"], "rep": rep,
                        "question": qa["question"], "gold": qa["answer"],
                        "evidence_text": transcript, "envelopes": [], "latency_ms": None,
                    })
        print(f"  [full_context] evidence 就绪（skip {len(done)}，新增 {todo}）")
        return todo

    async with Client(mcp_config(arm)) as client:
        progress = run.load_progress()
        await ingest_system(client, arm, convs, run, progress)
        for conv in convs:
            cid = conv["conversation_id"]
            for qi, qa in enumerate(conv["qa"]):
                for rep in range(n):
                    key = f"{arm}|{cid}|q{qi}|rep{rep}"
                    if key in done:
                        continue
                    t0 = time.perf_counter()
                    r = await acall(client, "retrieve", {
                        "query": qa["question"], "query_mode": "fixed", "top_k": top_k,
                        "filter": {"scope_id": cid},
                    }, timeout=300)
                    envs = r.get("results", [])
                    evidence_text = "\n".join(e["text"] for e in envs)
                    todo += 1
                    run.append(out, {
                        "key": key, "arm": arm, "conv": cid, "qa_id": f"q{qi}",
                        "category": qa["category"], "rep": rep,
                        "question": qa["question"], "gold": qa["answer"],
                        "evidence_text": evidence_text,
                        "envelopes": envs, "latency_ms": r.get("latency_ms"),
                        "native_notes": r.get("native_notes", ""),
                        "retrieve_wall_ms": int((time.perf_counter() - t0) * 1000),
                    })
            print(f"  [{arm}] {cid} retrieve 完成（累计新增 {todo}）")
        st = await acall(client, "stats", {})
        run.append(run.dir / "system_stats.jsonl", {"arm": arm, "stats": st, "ts": utcnow()})
    print(f"  [{arm}] evidence 就绪（skip {len(done)}，新增 {todo}）")
    return todo


# ---------- Phase B：答题 + 双轨判分（并发） ----------

async def answer_and_judge(ev: dict, http: httpx.AsyncClient, ans: "AnthropicCompat",
                           jud: "AnthropicCompat", sem: asyncio.Semaphore) -> dict:
    """单题：答题 → F1（cat1-4）→ LLM-judge → 结果 dict（不含 key 等已有字段）。"""
    async with sem:
        # 答题（解析失败重试 1 次，附纠错指令；再失败记 PARSE_ERROR，判分按空答案处理）
        raw, usage_a, parsed = "", {}, None
        prompt = scoring.answer_user(ev["evidence_text"] or "(empty)", ev["question"])
        for attempt in range(2):
            # max_tokens 交给 client（按 thinking 开关分档：off=600 / on=2048），不再硬编码
            raw, usage_a = await ans.chat(http, scoring.ANSWER_SYSTEM,
                                          prompt if attempt == 0 else prompt + "\nOutput ONLY the JSON object.")
            parsed = scoring.parse_answer(raw)
            if parsed:
                break
        pred = parsed["answer"] if parsed else "PARSE_ERROR"
        quote = parsed.get("quote") if parsed else None

        f1 = None
        if ev["category"] != 5:
            f1 = round(scoring.f1_score(pred if parsed else "", ev["gold"]), 4)

        # 判分（同样 2 次解析机会；再失败兜底 correct=0 并标记，出分时可单独统计）。
        # max_tokens 同样交给 client：thinking 开时 reasoning 与正文共用额度，600 会截成空 content。
        jraw, usage_j, judged, jfail = "", {}, None, False
        jprompt = scoring.judge_user(ev["question"], str(ev["gold"]), pred)
        for attempt in range(2):
            jraw, usage_j = await jud.chat(http, scoring.JUDGE_SYSTEM,
                                           jprompt if attempt == 0 else jprompt + "\nOutput ONLY the compact JSON object.")
            judged = scoring.parse_judge(jraw)
            if judged:
                break
        if judged:
            correct = judged["correct"]
        else:
            correct, jfail = 0, True

        return {
            "answer_raw": raw, "answer_parsed": pred, "quote": quote,
            "f1": f1, "judge_raw": jraw, "judge_correct": correct,
            "judge_parse_fail": jfail,
            "usage": {"answer": usage_a, "judge": usage_j}, "ts": utcnow(),
        }


async def phase_b(arms: list[str], run: Run, concurrency: int, convs_filter: set[str] | None = None) -> None:
    ans, jud = answer_llm_from_env(), judge_llm_from_env()
    done = run.done_keys(run.answers)
    tasks: list[dict] = []
    for arm in arms:
        path = run.evidence / f"{arm}.jsonl"
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            ev = json.loads(line)
            if convs_filter is not None and ev["conv"] not in convs_filter:
                continue  # --convs 同时约束 Phase B（2026-08-22 修复：之前只约束检索，Phase B 会答全量 evidence）
            if ev["key"] not in done:
                tasks.append(ev)

    if not tasks:
        print(f"Phase B: 无待答题（done={len(done)}）")
        return
    print(f"Phase B: 待答 {len(tasks)} 题，并发 {concurrency}，答题={ans.model}，判分={jud.model}")

    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    fails_in_row = 0
    t0 = time.time()
    completed = 0

    async with httpx.AsyncClient() as http:
        async def one(ev: dict) -> None:
            nonlocal fails_in_row, completed
            try:
                res = await answer_and_judge(ev, http, ans, jud, sem)
            except LLMError as e:
                async with lock:
                    fails_in_row += 1
                    print(f"  LLM 失败（连续 {fails_in_row}）: {ev['key']}: {e}")
                    if fails_in_row >= SUSPEND_AFTER:
                        raise Suspended(str(e))
                return
            async with lock:
                fails_in_row = 0
                run.append(run.answers, {**ev, **res})
                completed += 1
                if completed % 25 == 0 or completed == len(tasks):
                    rate = completed / (time.time() - t0)
                    eta = (len(tasks) - completed) / max(rate, 1e-9)
                    print(f"  进度 {completed}/{len(tasks)}（{rate:.1f} 题/s，ETA {eta / 60:.1f} min）")

        try:
            await asyncio.gather(*[one(ev) for ev in tasks])
        except Suspended as e:
            m = run.load_manifest()
            m["status"] = "SUSPENDED"
            m["suspended_reason"] = str(e)
            m["suspended_at"] = utcnow()
            run.save_manifest(m)
            print(f"⚠️ 挂起：{e}（已答 {completed}/{len(tasks)} 落盘；--resume 续跑）")
            sys.exit(3)

    m = run.load_manifest()
    m.setdefault("phase_b", {})
    m["phase_b"].update({"completed": completed, "wall_s": round(time.time() - t0, 1), "ts": utcnow()})
    run.save_manifest(m)
    print(f"Phase B 完成：{completed} 题，{time.time() - t0:.0f}s")


# ---------- 汇总打印 ----------

def summarize(run: Run) -> None:
    if not run.answers.exists():
        return
    rows: dict[str, dict] = {}
    for line in run.answers.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        arm = r["arm"]
        agg = rows.setdefault(arm, {"n": 0, "judge": 0, "judge_none": 0, "f1": 0.0, "cat": {}})
        agg["n"] += 1
        if r.get("judge_correct") is None:
            agg["judge_none"] += 1
        else:
            agg["judge"] += r["judge_correct"]
        if r.get("f1") is not None:
            agg["f1"] += r["f1"]
        c = agg["cat"].setdefault(str(r["category"]), {"n": 0, "judge": 0})
        c["n"] += 1
        c["judge"] += r.get("judge_correct") or 0
    print(f"\n{'arm':<14} {'n':>4} {'judge_acc':>9} {'F1':>6}  cat 切片（1=multihop 2=temporal 3=open 4=single 5=adv）")
    for arm, agg in sorted(rows.items()):
        n = agg["n"]
        acc = agg["judge"] / n if n else 0
        f1m = agg["f1"] / max(n - agg["judge_none"], 1)
        cats = " ".join(f"c{k}:{v['judge']}/{v['n']}" for k, v in sorted(agg["cat"].items()))
        print(f"{arm:<14} {n:>4} {acc:>9.3f} {f1m:>6.3f}  {cats}")
    print(f"（judge 解析失败行: {sum(a['judge_none'] for a in rows.values())}）")


# ---------- CLI ----------

def main() -> None:
    p = argparse.ArgumentParser(description="LoCoMo forced-call runner（bench-design v0.1）")
    p.add_argument("--arms", required=True,
                   help="逗号分隔。检索臂 = servers.yaml 系统 名（mock/mem0/.../rag_baseline/intent）；full_context 为内置臂")
    p.add_argument("--convs", default="all", help="逗号分隔 conversation_id，默认全部 10 个")
    p.add_argument("--n", type=int, default=1, help="重复次数（LLM 非确定性方差）")
    p.add_argument("--top-k", type=int, default=20,
                   help="默认 20，与 interface-spec §7 一致（2026-08-30 由 5 改为 20；旧 run 用的是 5，不可混表）")
    p.add_argument("--concurrency", type=int, default=16, help="Phase B 答题并发（用户定：16 实测稳定；持续流 RPM 限流由 429 长退避扛）")
    p.add_argument("--run-id", required=True)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--ingest-only", action="store_true", help="只做 Phase A ingest+snapshot，不答题")
    args = p.parse_args()

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    unknown = [a for a in arms if a != "full_context" and a not in SERVERS]
    if unknown:
        sys.exit(f"未知臂: {unknown}；可选: {list(SERVERS)} + full_context")

    convs = load_locomo()
    if args.convs != "all":
        want = {c.strip() for c in args.convs.split(",")}
        missing = want - {c["conversation_id"] for c in convs}
        if missing:
            sys.exit(f"未知 conv: {sorted(missing)}")
        convs = [c for c in convs if c["conversation_id"] in want]

    # MCP server 侧的可审查日志按 run 归档（trace 落 runs/<run_id>/mcp_trace/）。child_env() 会把
    # MEMBENCH_* 透传给 stdio 子进程，所以这里设一次即可。
    os.environ["MEMBENCH_RUN_ID"] = args.run_id

    run = Run(args.run_id, args.resume)
    # 只为读配置写 manifest（纯配置对象，不建连接）；Phase B 会自己再取一次
    ans_cfg, jud_cfg = answer_llm_from_env(), judge_llm_from_env()
    m = run.load_manifest()
    m.update({
        "run_id": args.run_id, "benchmark": "locomo10",
        "convs": [c["conversation_id"] for c in convs],
        "arms": arms, "n": args.n, "top_k": args.top_k, "concurrency": args.concurrency,
        "answer_model": os.environ.get("MEMBENCH_ANSWER_MODEL"),
        "judge_model": os.environ.get("MEMBENCH_JUDGE_MODEL", os.environ.get("MEMBENCH_ANSWER_MODEL")),
        "answer_protocol": os.environ.get("MEMBENCH_ANSWER_PROTOCOL"),
        "answer_temp": 0.0,
        # ★ 换答题器/改 thinking = 换测量仪器，跨 run 不可比。这几项必须留痕
        #   （2026-08-29：locomo-r1 的 manifest 因单臂续跑被覆盖成 arms=[graphiti]，配置漂移无记录）
        "answer_endpoint": _endpoint_tag(os.environ.get("MEMBENCH_ANSWER_BASE_URL")),
        "judge_endpoint": _endpoint_tag(
            os.environ.get("MEMBENCH_JUDGE_BASE_URL", os.environ.get("MEMBENCH_ANSWER_BASE_URL"))),
        "answer_thinking": _thinking_tag(ans_cfg.thinking),
        "judge_thinking": _thinking_tag(jud_cfg.thinking),
        "answer_max_tokens": ans_cfg.max_tokens,
        "judge_max_tokens": jud_cfg.max_tokens,
        "prompt_version": "bench-design-v0.1",
        "started_at": m.get("started_at") or utcnow(),
        "status": "RUNNING",
    })
    run.save_manifest(m)
    print(f"run: {run.dir}\narms={arms} convs={len(convs)} n={args.n}")

    for arm in arms:
        try:
            asyncio.run(evidence_for_arm(arm, convs, run, args.top_k, args.n))
        except Exception as e:  # MCP server 崩溃等：该臂标 FAILED，不阻塞其他臂
            print(f"  ⚠️ [{arm}] Phase A 失败: {type(e).__name__}: {e}")
            run.append(run.dir / "failures.jsonl", {"arm": arm, "phase": "A", "error": str(e), "ts": utcnow()})
            continue

    if not args.ingest_only:
        want = {c["conversation_id"] for c in convs} if args.convs != "all" else None
        asyncio.run(phase_b(arms, run, args.concurrency, want))
        summarize(run)

    m = run.load_manifest()
    m["status"] = "DONE"
    m["finished_at"] = utcnow()
    run.save_manifest(m)
    print(f"\n完成。产物：{run.answers}")


if __name__ == "__main__":
    main()

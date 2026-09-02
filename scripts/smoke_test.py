# smoke_test.py：接口契约测试（interface-spec §10）
# 用法：.venv/bin/python scripts/smoke_test.py <system>
# 八步断言（执行序）：1 add → 2 retrieve → 3 snapshot+reset → 4 reset 幂等 → 5 restore 可复现
#                 → 7 reset→add 链路（防静默丢数据）→ 8 双 scope 隔离（防跨 scope 泄漏）→ 6 清场
# 7/8 于 2026-08-19 深度核查后补入（DEPLOY §6 P1/P3）；编号沿用当时的断言号，故 6 排在最后。
# 任何一步 FAIL 退出码非 0——这是 server 进入实验矩阵的门禁，也是规范变更的回归门禁。

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import yaml
from fastmcp import Client

REPO = Path(__file__).resolve().parents[1]
SERVERS = yaml.safe_load((REPO / "servers.yaml").read_text())["servers"]


def load_dotenv(path: Path | None = None) -> None:
    """极简 .env 加载（KEY=VALUE，忽略 #注释），不引入 python-dotenv 依赖。"""
    p = path or REPO / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


load_dotenv()  # 在构造子进程 env 之前生效

TURNS = [
    {"role": "user", "content": "我六月要搬去 Oakland，正在找房子。", "timestamp": "2024-05-12T10:00:00Z"},
    {"role": "assistant", "content": "好的，Oakland 六月的租房市场……", "timestamp": "2024-05-12T10:00:05Z"},
    {"role": "user", "content": "对了，我养了一只猫叫帕丁森。", "timestamp": "2024-05-12T10:02:00Z"},
]
QUERY = "帕丁森 猫"


def parse(result) -> dict:
    """fastmcp 结果解析：优先结构化 data，回退 content[0].text 的 JSON。"""
    data = getattr(result, "data", None)
    if isinstance(data, dict):
        return data
    raw = getattr(result, "content", None)
    if raw:
        return json.loads(raw[0].text)
    raise RuntimeError("工具返回为空")


class Checker:
    def __init__(self) -> None:
        self.rows: list[tuple[str, bool, str, int]] = []

    def check(self, name: str, ok: bool, detail: str = "", ms: int = 0) -> bool:
        self.rows.append((name, ok, detail, ms))
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name}" + (f" — {detail}" if detail else "") + (f" ({ms}ms)" if ms else ""))
        return ok

    @property
    def failed(self) -> list[str]:
        return [f"{name}（{detail}）" if detail else name
                for name, ok, detail, _ in self.rows if not ok]

    @property
    def ok(self) -> bool:
        return bool(self.rows) and not self.failed

    def __bool__(self) -> bool:
        return self.ok


async def run(system: str) -> "Checker":
    """跑完八步契约断言，返回 Checker（真值 = 全过）。tests/test_contract.py 依赖这个返回值。"""
    cfg = SERVERS[system]
    missing = [k for k in cfg.get("env_required", []) if not os.environ.get(k)]
    if missing:
        print(f"✗ 缺少环境变量: {missing}（见 interface-spec §7 公平性配置）")
        c = Checker()
        c.check("0 env_required", False, f"缺 {', '.join(missing)}")
        return c

    # 关键：MCP stdio 子进程只继承最小环境（PATH/HOME 等），不继承父进程变量——
    # MEMBENCH_* 与重定向变量（mandol 的 SILICONFLOW_*）必须显式转发
    # HF_/HUGGING_FACE_（2026-08-31 补）：mandol 的 SPLADE/cross-encoder 需 HF 鉴权，不转发会 401 静默降级
    child_env = {k: v for k, v in os.environ.items()
                 if k.startswith(("MEMBENCH_", "SILICONFLOW_", "OPENAI_", "HF_", "HUGGING_FACE_"))}
    config = {"mcpServers": {system: {"command": cfg["command"], "args": cfg["args"], "env": child_env}}}
    c = Checker()
    baseline_ids: set[str] = set()

    async with Client(config) as client:
        # 1. add_conversation：3 turns 全被接受
        t0 = time.perf_counter()
        r = parse(await client.call_tool("add_conversation", {
            "session_id": "smoke_s1", "turns": TURNS,
            "scope": {"kind": "user", "id": "smoke_user"},
        }))
        c.check("1 add_conversation", r.get("accepted_turns") == 3, f"accepted={r.get('accepted_turns')}",
                int((time.perf_counter() - t0) * 1000))

        # 2. retrieve：≥1 条 envelope，字段齐全、text ≤600
        t0 = time.perf_counter()
        r = parse(await client.call_tool("retrieve", {"query": QUERY, "query_mode": "fixed", "top_k": 5}))
        results = r.get("results", [])
        ok2 = len(results) >= 1
        detail = f"{len(results)} 条"
        if ok2:
            env = results[0]
            fields_ok = all(k in env for k in ["memory_id", "text", "source", "timestamp", "score", "raw_format"])
            ok2 = fields_ok and len(env["text"]) <= 600
            detail += f"，首条字段{'齐全' if fields_ok else '缺失'}，text={len(env['text'])} 字符"
            baseline_ids = {e["memory_id"] for e in results}
        c.check("2 retrieve", ok2, detail, int((time.perf_counter() - t0) * 1000))

        # 3. snapshot → reset → stats 归零（SNAPSHOT_UNSUPPORTED 是合法声明，记 SKIP）
        t0 = time.perf_counter()
        r = parse(await client.call_tool("snapshot", {"tag": "smoke"}))
        unsupported = (r.get("error") == "SNAPSHOT_UNSUPPORTED")
        snap_ok = bool(r.get("ok")) or unsupported
        r = parse(await client.call_tool("reset", {}))
        reset_ok = bool(r.get("ok"))
        r = parse(await client.call_tool("stats", {}))
        c.check("3 snapshot+reset", snap_ok and reset_ok and r.get("n_memories") == 0,
                f"snap={'SKIP(SNAPSHOT_UNSUPPORTED)' if unsupported else snap_ok} reset={reset_ok} n_memories={r.get('n_memories')}",
                int((time.perf_counter() - t0) * 1000))

        # 4. reset 幂等：再来一次仍安全
        t0 = time.perf_counter()
        parse(await client.call_tool("reset", {}))
        r = parse(await client.call_tool("stats", {}))
        c.check("4 reset 幂等", r.get("n_memories") == 0, f"n_memories={r.get('n_memories')}",
                int((time.perf_counter() - t0) * 1000))

        # 5. restore → 同 query 检索 → memory_id 集合一致（快照可复现）；SKIP 场景改为重灌验证
        t0 = time.perf_counter()
        r = parse(await client.call_tool("restore", {"tag": "smoke"}))
        ok5 = bool(r.get("ok"))
        detail = f"restore={ok5}"
        if r.get("error") == "SNAPSHOT_UNSUPPORTED":
            # 退化路径：重灌同样本，验证 add→retrieve 链路确定性（弱于快照，但保证 reset 后可重建）
            r = parse(await client.call_tool("add_conversation", {
                "session_id": "smoke_s1", "turns": TURNS,
                "scope": {"kind": "user", "id": "smoke_user"}}))
            r = parse(await client.call_tool("retrieve", {"query": QUERY, "query_mode": "fixed", "top_k": 5}))
            now_ids = {e["memory_id"] for e in r.get("results", [])}
            ok5 = len(now_ids) >= 1
            detail = f"SKIP(重灌验证): 重建后检索 {len(now_ids)} 条"
        elif ok5:
            r = parse(await client.call_tool("retrieve", {"query": QUERY, "query_mode": "fixed", "top_k": 5}))
            now_ids = {e["memory_id"] for e in r.get("results", [])}
            ok5 = now_ids == baseline_ids
            detail += f"，id 集合一致={ok5}（{len(now_ids)} 条）"
        c.check("5 restore 可复现", ok5, detail, int((time.perf_counter() - t0) * 1000))

        # 7. reset→add→retrieve≥1（P1 类门禁：reset 后不得静默丢数据）
        t0 = time.perf_counter()
        parse(await client.call_tool("reset", {}))
        parse(await client.call_tool("add_conversation", {
            "session_id": "smoke_s1", "turns": TURNS,
            "scope": {"kind": "user", "id": "smoke_user"}}))
        r = parse(await client.call_tool("retrieve", {"query": QUERY, "query_mode": "fixed", "top_k": 5}))
        c.check("7 reset→add 链路", len(r.get("results", [])) >= 1,
                f"reset 后重灌检索 {len(r.get('results', []))} 条",
                int((time.perf_counter() - t0) * 1000))

        # 8. 双 scope 隔离（P2/P3 类门禁：filter.scope_id 不得泄漏跨 scope 内容）
        t0 = time.perf_counter()
        turns_b = [{"role": "user", "content": "我下周要去冰岛看极光，已经订了雷克雅未克的民宿。",
                    "timestamp": "2024-06-01T10:00:00Z"}]
        parse(await client.call_tool("add_conversation", {
            "session_id": "smoke_sB", "turns": turns_b,
            "scope": {"kind": "user", "id": "smoke_scopeB"}}))
        r = parse(await client.call_tool("retrieve", {
            "query": "帕丁森 猫 冰岛", "query_mode": "fixed", "top_k": 10,
            "filter": {"scope_id": "smoke_user"}}))
        leaked = [e for e in r.get("results", []) if "冰岛" in e.get("text", "") or "极光" in e.get("text", "")]
        r2 = parse(await client.call_tool("retrieve", {
            "query": "极光 冰岛", "query_mode": "fixed", "top_k": 10,
            "filter": {"scope_id": "smoke_scopeB"}}))
        got_b = any("冰岛" in e.get("text", "") or "极光" in e.get("text", "") for e in r2.get("results", []))
        c.check("8 双 scope 隔离", len(leaked) == 0 and got_b,
                f"A 内 B 泄漏 {len(leaked)} 条；B 内自检 {'✓' if got_b else '✗'}",
                int((time.perf_counter() - t0) * 1000))

        # 6. 清场：reset 离开，不留脏状态
        t0 = time.perf_counter()
        parse(await client.call_tool("reset", {}))
        c.check("6 清场", True, "reset 完成", int((time.perf_counter() - t0) * 1000))

    print(f"\n{'=' * 50}")
    n_pass = sum(1 for _, ok, _, _ in c.rows if ok)
    print(f"{system}: {n_pass}/{len(c.rows)} 通过")
    return c


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "mock"
    if target not in SERVERS:
        print(f"未知 system: {target}；可选: {list(SERVERS)}")
        sys.exit(2)
    print(f"smoke test → {target}")
    sys.exit(0 if asyncio.run(run(target)).ok else 1)

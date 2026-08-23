# test_contract.py：把 scripts/smoke_test.py 的八步契约断言变成 pytest 门禁。
#
# 为什么要这层包装：smoke_test.py 本来就是契约测试（interface-spec §10），但它靠手跑
# `python scripts/smoke_test.py <system>` 一个个来。适配器的 envelope 形状一旦悄悄变了，
# 没有任何东西会响。这里让 `pytest` 一次跑全矩阵。
#
#   pytest                      # 跑所有依赖在位的臂，其余 skip
#   pytest -k mock              # 只跑契约靶（无 LLM，永远该绿）
#   pytest --runslow            # 含真实系统的慢臂（默认只跑 mock）
#
# 依赖不在位的臂会 skip 而不是 fail——缺 key、Neo4j 没起、bun 没装都不是契约破了。

from __future__ import annotations

import asyncio
import os
import shutil
import socket
from pathlib import Path

import pytest

from conftest import REPO, smoke

SYSTEMS = list(smoke.SERVERS)

# 除了 env_required 之外的外部前置条件（DEPLOY.md §4）
EXTERNAL = {
    "graphiti": ("Neo4j (membench-neo4j)", lambda: _port_open("127.0.0.1", 7687)),
    "memos": ("MemOS compose 栈 :8000", lambda: _port_open("127.0.0.1", 8000)),
    "intent": ("bun", lambda: shutil.which("bun") is not None),
}


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except OSError:
        return False


def _skip_reason(system: str) -> str | None:
    cfg = smoke.SERVERS[system]

    interp = cfg.get("command", "")
    if interp.startswith(".venv") and not (REPO / interp).exists():
        return f"{interp} 不存在（见 DEPLOY.md §1）"

    missing = [k for k in cfg.get("env_required", []) if not os.environ.get(k)]
    if missing:
        return f"缺环境变量 {', '.join(missing)}（cp .env.example .env）"

    if system in EXTERNAL:
        label, probe = EXTERNAL[system]
        if not probe():
            return f"{label} 未就绪（见 DEPLOY.md §4）"

    return None


@pytest.mark.parametrize("system", SYSTEMS)
def test_contract(system: str, request):
    """每个 server 必须八步全过，否则不许进实验矩阵。"""
    if system != "mock" and not request.config.getoption("--runslow"):
        pytest.skip("真实系统较慢（单臂十几秒到半分钟），加 --runslow 才跑")

    reason = _skip_reason(system)
    if reason:
        pytest.skip(reason)

    checker = asyncio.run(smoke.run(system))
    assert checker.ok, f"{system} 契约未过：{'; '.join(checker.failed)}"


def test_servers_yaml_interpreters_declared():
    """servers.yaml 是解释器的唯一事实来源——每个臂都必须显式声明 command/args。"""
    for name, cfg in smoke.SERVERS.items():
        assert cfg.get("command"), f"{name} 缺 command"
        assert cfg.get("args"), f"{name} 缺 args"


def test_env_example_covers_every_env_required():
    """servers.yaml 里要求的变量，.env.example 必须都列出来，否则新人照模板填不全。"""
    example = (REPO / ".env.example").read_text()
    declared = {
        line.split("=", 1)[0].strip()
        for line in example.splitlines()
        if "=" in line and not line.strip().startswith("#")
    }
    required = {k for cfg in smoke.SERVERS.values() for k in cfg.get("env_required", [])}
    missing = sorted(required - declared)
    assert not missing, f".env.example 漏了 servers.yaml 要求的变量: {missing}"

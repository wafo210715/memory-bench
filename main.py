#!/usr/bin/env python3
# main.py：统一入口分发器。
#
# 存在的理由有两个：
#   1) 入口可发现——以前真入口藏在 argparse 和 DEPLOY.md 里，新人（和三周后的自己）找不到；
#   2) 解释器防呆——系统 Python 是 3.14，直接跑会 ImportError，这里自动改用 .venv/bin/python。
#
# 用法：
#   python main.py smoke <system>          契约门禁（scripts/smoke_test.py）
#   python main.py run --arms ... --run-id ...   评测循环（bench.runner）
#   python main.py arms                    列出可用臂及其依赖
#
# run/smoke 的参数原样透传，--help 由被分发的目标自己回答。

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
VENV_PY = REPO / ".venv" / "bin" / "python"

USAGE = """用法：
  python main.py smoke <system>                     契约门禁，8/8 才算过
  python main.py run --arms <臂,...> --run-id <id>   评测循环（其余参数见 run --help）
  python main.py arms                               列出可用臂

例：
  python main.py smoke mock
  python main.py run --arms mock,full_context --convs conv-30 --run-id shakeout
  python main.py run --help
"""


def ensure_venv() -> None:
    """不在主 venv 里就换过去。系统 Python 是 3.14，缺依赖时报错很难看懂。

    用 sys.prefix 而非 sys.executable 判断：.venv/bin/python 是指向 uv 托管解释器的
    符号链接，resolve() 后与"直接用那个解释器"无法区分，只有 prefix 能分辨。
    """
    if Path(sys.prefix).resolve() == (REPO / ".venv").resolve():
        return
    if os.environ.get("_MEMBENCH_REEXEC"):  # 换过一次还不对，别转圈
        sys.exit(f"已切到 {VENV_PY} 但 sys.prefix 仍不是 {REPO / '.venv'}——venv 可能坏了，重建见 DEPLOY.md §1")
    if not VENV_PY.exists():
        sys.exit(f"找不到 {VENV_PY}——先 `uv venv -p 3.12`，见 DEPLOY.md §1")
    os.environ["_MEMBENCH_REEXEC"] = "1"
    os.execv(str(VENV_PY), [str(VENV_PY), str(REPO / "main.py"), *sys.argv[1:]])


def cmd_arms() -> None:
    import yaml

    from bench.llm import load_dotenv  # 复用既有的极简 .env 读取，别再写第三份

    load_dotenv()  # 让下面的"env 齐/缺"反映 .env，而不只是当前 shell
    servers = yaml.safe_load((REPO / "servers.yaml").read_text())["servers"]
    print("可用臂（来自 servers.yaml）：\n")
    for name, cfg in servers.items():
        need = cfg.get("env_required") or []
        interp = cfg.get("command", "")
        tag = "" if interp.startswith(".venv/") else f"  [{interp}]"
        print(f"  {name:<14}{tag}")
        if need:
            missing = [k for k in need if not os.environ.get(k)]
            mark = "缺" if missing else "齐"
            print(f"  {'':<14}  env {mark}: {', '.join(need)}")
    print("\n  full_context    [runner 内置对照臂，非 server]")
    print("\n外部依赖：graphiti 需 membench-neo4j 容器；memos 需 compose 栈 :8000（见 DEPLOY.md §4）")


def main() -> None:
    ensure_venv()

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(USAGE)
        sys.exit(0 if len(sys.argv) > 1 else 1)

    cmd, rest = sys.argv[1], sys.argv[2:]

    if cmd == "smoke":
        if not rest:
            sys.exit("用法：python main.py smoke <system>（`python main.py arms` 看可选值）")
        script = REPO / "scripts" / "smoke_test.py"
        os.execv(sys.executable, [sys.executable, str(script), *rest])

    elif cmd == "run":
        sys.argv = ["bench.runner", *rest]
        from bench.runner import main as runner_main

        runner_main()

    elif cmd == "arms":
        cmd_arms()

    else:
        print(f"未知子命令: {cmd}\n")
        print(USAGE)
        sys.exit(1)


if __name__ == "__main__":
    main()

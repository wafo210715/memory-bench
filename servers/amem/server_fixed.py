# amem_fixed 入口：与 amem 同一份 server.py，仅以 MEMBENCH_AMEM_MODE=fixed 拉起。
#
# 为什么要独立入口而不是在 servers.yaml 里配 env：
#   bench/runner.py:87-88 构造子进程时 env 一律取 child_env()，不读 yaml 的 env 字段，
#   所以模式只能在进程内、且必须在 import servers.amem.server 之前设置。
#
# 两臂差异见 servers/amem/fixed.py 顶部说明。state 目录 / chroma collection / FastMCP 名
# 均按 SYSTEM_NAME 分离，与原生臂互不影响。

import os
import sys
from pathlib import Path

os.environ["MEMBENCH_AMEM_MODE"] = "fixed"   # 必须早于下面的 import

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from servers.amem.server import mcp  # noqa: E402  （import 顺序刻意如此）

if __name__ == "__main__":
    mcp.run()  # stdio

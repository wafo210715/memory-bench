# memharness_noadapt：memharness 的消融臂——关掉论文一号机制「批判+重构」，其余完全相同。
#
# 对应论文 Table 2 的「去掉重构」那一行：检索命中后不再逐条改写、也不再判定丢弃，
# 直接把蒸馏出的原则原样交付。与主臂的唯一差别就是这一个开关，因此两臂之差
# 可以干净地归因到重构层本身（前提是两臂读同一份记忆库，见下）。
#
# 记忆库共享：本臂用独立的状态目录（.state/memharness_noadapt），但正式 run 的做法是
# 先由主臂灌入并产出 locomo_full 快照，再把该快照复制到本臂的命名空间，使两臂恢复出
# 逐条相同的记忆库。不这么做的话，蒸馏层本身的非确定性（同一 session 两次会抽出不同条数）
# 会把「记忆库差异」混进「重构层贡献」里，对照就不干净了。
#
# 同一份 server.py，只改两个环境变量后复用（amem_fixed 的先例）。

import os
import sys
from pathlib import Path

os.environ["MEMBENCH_MEMHARNESS_ADAPTOR"] = "off"  # 强制覆盖父进程可能传下来的值
os.environ["MEMBENCH_MEMHARNESS_ARM"] = "memharness_noadapt"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from server import mcp  # noqa: E402  必须在设置环境变量之后导入

if __name__ == "__main__":
    mcp.run()  # stdio

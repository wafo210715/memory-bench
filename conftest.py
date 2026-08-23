# conftest.py（仓库根）：pytest 的公共装置。
#
# 放在根而不是 tests/ 下，是因为 pytest_addoption 必须由 rootdir 的 conftest 提供。
#
# scripts/ 不是包（无 __init__.py），所以 smoke_test 按文件路径加载，
# 而不是 `from scripts.smoke_test import ...`。

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from bench.llm import load_dotenv  # noqa: E402

load_dotenv()  # 测试与手跑 smoke 用同一份 .env 约定


def _load_smoke():
    spec = importlib.util.spec_from_file_location(
        "smoke_test", REPO / "scripts" / "smoke_test.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["smoke_test"] = mod
    spec.loader.exec_module(mod)
    return mod


smoke = _load_smoke()


def pytest_addoption(parser):
    parser.addoption(
        "--runslow", action="store_true", default=False,
        help="跑真实记忆系统的契约测试（默认只跑 mock）",
    )

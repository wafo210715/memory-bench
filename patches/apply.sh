#!/bin/bash
# 把仓内物化的两个 graphiti patch 应用到当前 venv 的 site-packages。
#
# 为什么需要：DEPLOY.md §6 记录的两个手打 patch 长期只存在于 .venv 里（被 gitignore），
# 重建 venv 会丢——0.29.3 在 LoCoMo 规模 ingest 时 EdgeDuplicate pydantic 崩、
# community label_propagation 死循环且不可复现。smoke 的 3 turns 触发不了，大规模才炸。
#
# 用法：bash patches/apply.sh [venv-python]
#   默认用仓库根的 .venv/bin/python。幂等：已打过 patch 直接确认通过。
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${1:-.venv/bin/python}"
PINNED_VERSION="0.29.3"

# 1) 版本钉死：patch 是对 0.29.3 逐行打的，别的版本不保证上下文对齐
VER=$("$PY" -c 'from importlib.metadata import version; print(version("graphiti_core"))')
if [ "$VER" != "$PINNED_VERSION" ]; then
  echo "✗ graphiti_core 版本是 $VER，patch 只针对 $PINNED_VERSION。"
  echo "  升级 graphiti 后先核对 DEPLOY.md §6 两个坑是否仍在，再更新 patches/graphiti/。"
  exit 1
fi

# 2) 定位 site-packages
TARGET=$("$PY" -c 'import graphiti_core, os; print(os.path.dirname(graphiti_core.__file__) + "/utils/maintenance")')
[ -d "$TARGET" ] || { echo "✗ 找不到 $TARGET"; exit 1; }
echo "目标: $TARGET"

# 3) 逐文件：hash 一致 = 已打过；否则覆盖并复验
fail=0
for f in edge_operations.py community_operations.py; do
  want=$(awk -v fn="$f" '$2==fn {print $1}' patches/graphiti/SHA256SUMS)
  if [ -z "$want" ]; then echo "  $f: ✗ SHA256SUMS 里没有条目"; fail=1; continue; fi
  got=$(shasum -a 256 "$TARGET/$f" 2>/dev/null | awk '{print $1}' || echo missing)
  if [ "$got" = "$want" ]; then
    echo "  $f: 已是 patch 态 ✓"
    continue
  fi
  cp "patches/graphiti/$f" "$TARGET/$f"
  got=$(shasum -a 256 "$TARGET/$f" | awk '{print $1}')
  if [ "$got" = "$want" ]; then
    echo "  $f: 已应用 ✓"
  else
    echo "  $f: ✗ 应用后 hash 不符（$got）"; fail=1
  fi
done

if [ "$fail" = 0 ]; then
  echo "graphiti patches 就绪（版本 ${VER}）。"
else
  exit 1
fi

#!/usr/bin/env bash
# archive_run.sh：把一次 run 的大件产物打包，便于放到这台 laptop 以外的地方。
#
# 背景：runs/<id>/ 里 answers.jsonl（~58MB）和 evidence/（~73MB）不入 git（见 .gitignore），
# 但它们是真正的原始结果——重跑要花真实 API 成本。元数据 git push 就安全了，这两样得单独存。
#
# 用法：
#   scripts/archive_run.sh locomo-r1
#   scripts/archive_run.sh                 # 不给参数则列出所有 run
#
# 产物：archives/<run-id>-<日期>.tar.gz（jsonl 文本压缩比约 5-8 倍）

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

if [[ $# -lt 1 ]]; then
  echo "用法：scripts/archive_run.sh <run-id>"
  echo
  echo "现有 run："
  for d in runs/*/; do
    [[ -d "$d" ]] || continue
    printf '  %-16s %s\n' "$(basename "$d")" "$(du -sh "$d" | cut -f1)"
  done
  exit 1
fi

RUN_ID="$1"
SRC="runs/$RUN_ID"
[[ -d "$SRC" ]] || { echo "没有这个 run: $SRC"; exit 1; }

mkdir -p archives
OUT="archives/${RUN_ID}-$(date +%Y%m%d).tar.gz"

echo "打包 $SRC → $OUT"
tar czf "$OUT" "$SRC"

echo
echo "完成：$OUT （$(du -sh "$OUT" | cut -f1)，原始 $(du -sh "$SRC" | cut -f1)）"
echo "别把它留在本机——传到对象存储 / 外置盘 / 另一台机器。"

#!/usr/bin/env bash
# Phase 3 检索层考试（3-conv）。前置见 docs/mandol-repro-plan.md §12。
#
# 用法：
#   bash scripts/run_mandol_p3.sh                          # 默认：stage2 消融组
#   bash scripts/run_mandol_p3.sh mandol-p3-full-3conv 1   # 完整管线组（级联 id 全填）
#
# 三个必须成立的前置（启动前逐条核验，不要跳过）：
#   1. .state/__snapshots__/mandol/locomo_full 与当前 .state/mandol 一致
#      —— restore() 是 rmtree+copytree 全量替换，快照旧了会静默抹掉迁移成果。
#         校验：diff -rq .state/mandol .state/__snapshots__/mandol/locomo_full
#   2. runs/<id>/ingest_progress/progress.json 已从上一个 run 复制 —— 否则重新 ingest 会覆盖增强后的 L0
#   3. runs/<id>/evidence/ 已预建 —— Run.__init__ 只在 not resume 分支建它
set -euo pipefail

cd "$(dirname "$0")/.."
RID="${1:-mandol-p3-retrieval-3conv}"
CASCADE_IDS="${2:-0}"

set -a
# shellcheck disable=SC1091
. ./.env
set +a

export MEMBENCH_MANDOL_TRITOWER=1              # 三塔检索 + RRF + 重排 + 级联剪枝
export MEMBENCH_MANDOL_TOWERS=1
export MEMBENCH_MANDOL_SPARSE=1
export MEMBENCH_MANDOL_CASCADE_IDS="$CASCADE_IDS"   # 1=按官方对三塔填 entity/source id

echo "run=$RID  TRITOWER=1 SPARSE=1 CASCADE_IDS=$CASCADE_IDS"

nohup .venv/bin/python -m bench.runner \
  --arms mandol \
  --convs conv-26,conv-30,conv-49 \
  --n 3 \
  --top-k 20 \
  --concurrency 16 \
  --run-id "$RID" \
  --resume \
  > "runs/$RID/run.log" 2>&1 &

echo $! > "runs/$RID/main.pid"
echo "PID=$(cat "runs/$RID/main.pid")  日志: runs/$RID/run.log"

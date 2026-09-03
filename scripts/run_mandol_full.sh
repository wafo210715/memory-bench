#!/usr/bin/env bash
# mandol 全量 10-conv 定稿跑（进主表）。三段串行，全程 caffeinate 防休眠。
#
#   1. ingest 剩余 7 conv        约 40 min   （TOWERS=0，避免 snapshot 超时）
#   2. 三塔构建 7 conv           约 2.0 h    （timeout=36000，结尾自动刷新快照）
#   3. 全量考试 1986 题 × n=3    约 18 h     （可中断，重跑本脚本自动续）
#
# 为什么必须拆三段（都是会在半夜静默炸掉的坑）：
#   · `runner --ingest-only` 只跳过 Phase B，Phase A 的 5,958 次检索照跑（runner.py:473）
#   · `ingest_system` 结尾 snapshot 用 timeout=600（runner.py:186），
#     而 TOWERS_ON=1 时 snapshot 会先建塔（7 conv 约 2h）→ 必然超时
#   · restore() 是 rmtree+copytree 全量替换，快照陈旧会静默回滚已建好的塔
#
# 断点续跑：三段都幂等。ingest 按 scope 跳过、建塔按 .done.json 跳过、
# 考试按 evidence 的 done_keys 跳过。中断后重跑本脚本即可。
set -euo pipefail

cd "$(dirname "$0")/.."
RID="${1:-mandol-full-10conv}"
LOG="runs/$RID/orchestrator.log"
mkdir -p "runs/$RID/evidence" "runs/$RID/ingest_progress"

set -a
# shellcheck disable=SC1091
. ./.env
set +a
export MEMBENCH_MANDOL_TRITOWER=1
export MEMBENCH_MANDOL_SPARSE=1
export MEMBENCH_MANDOL_CASCADE_IDS=1     # 完整管线（级联三 stage 全开）

say() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }

say "=== 阶段 1/3：ingest 剩余 conv ==="
if .venv/bin/python scripts/ingest_mandol_full.py --run-id "$RID" >> "$LOG" 2>&1; then
  say "ingest 完成"
else
  say "❌ ingest 失败，见 $LOG"; exit 1
fi

say "=== 阶段 2/3：三塔构建 ==="
if .venv/bin/python scripts/build_mandol_towers.py >> "$LOG" 2>&1; then
  say "建塔完成（snapshot 已在脚本内刷新）"
else
  say "❌ 建塔失败，见 $LOG"; exit 1
fi

# 建塔后快照必须与状态一致，否则考试开跑时 restore 会回滚
if diff -rq .state/mandol .state/__snapshots__/mandol/locomo_full > /dev/null 2>&1; then
  say "快照一致性校验通过"
else
  say "⚠️ 快照与状态不一致，用当前状态刷新"
  rm -rf .state/__snapshots__/mandol/locomo_full
  cp -R .state/mandol .state/__snapshots__/mandol/locomo_full
  say "已刷新"
fi

say "=== 阶段 3/3：全量考试 ==="
.venv/bin/python -m bench.runner \
  --arms mandol --convs all --n 3 --top-k 20 --concurrency 16 \
  --run-id "$RID" --resume >> "runs/$RID/run.log" 2>&1
say "考试完成，结果见 runs/$RID/"

# ❗ 启动方式很重要：本脚本第三段是**前台**执行（三段必须串行）。
# 直接在终端里跑，终端一关整个进程组就收 SIGHUP 而死，
# 且 Python 不会留 traceback、系统不会生成崩溃报告，看上去就像“凭空消失”。
# 2026-09-03 02:05 就因此断在 41%。长时无人值守必须完全脱离终端：
#
#   nohup setsid caffeinate -i bash scripts/run_mandol_full.sh <run-id> \
#     > runs/<run-id>/nohup.log 2>&1 &
#
# caffeinate -i 只防空闲休眠，不防终端关闭；两者必须同时具备。

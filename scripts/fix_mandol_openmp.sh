#!/usr/bin/env bash
# 统一 .venv-mandol 内的 OpenMP 运行时（2026-08-31）
#
# 症状：启用 SPLADE 后 mandol server 在检索阶段静默 SIGSEGV，MCP 侧只见 Connection closed。
#       crash report 栈全在 libomp.dylib 的 __kmp_suspend_initialize_thread / __kmp_fork_barrier。
#
# 根因：多个 wheel 各自捆绑一份 libomp.dylib，install name 互不相同，dyld 当成不同库分别加载：
#         torch/lib/libomp.dylib          → /opt/homebrew/opt/libomp/lib/libomp.dylib   720K
#         faiss/.dylibs/libomp.dylib      → /DLC/faiss/.dylibs/libomp.dylib             740K
#         sklearn/.dylibs/libomp.dylib    → /DLC/sklearn/.dylibs/libomp.dylib           664K
#       但 OpenMP 运行时是全局单例语义——多份争抢同一套线程池元数据，worker 线程 barrier 处崩溃。
#       三者均为 LLVM OMP 5.0.20140926 / arm64，ABI 一致，故可统一到同一份。
#
# 处置：把其余各份符号链接到 torch 那份。dyld 解析 symlink 到同一 realpath 后只加载一次。
#       修复后 torch=12 / faiss=12 线程，无需任何降级手段。
#
# 为何不用那些常见 workaround：
#   KMP_DUPLICATE_LIB_OK=TRUE  只压住加载期 abort，运行期照样段错误
#   OMP_NUM_THREADS=1          能绕过，但把 torch 一并压成单线程，污染要上报的 Search 延迟指标
#
# ⚠️ 重装 torch / faiss-cpu / scikit-learn 会冲掉符号链接，需重跑本脚本。
#    server.py 启动时 _assert_single_libomp() 会自检并指向这里。
#
# sklearn 那份为何也要收：mandol 的 cluster/dbscan_method.py 用 sklearn.cluster.DBSCAN，
#    Phase 2 的实体/事实去重会走到，届时同样会触发冲突。

set -euo pipefail
cd "$(dirname "$0")/.."

SP=".venv-mandol/lib/python3.12/site-packages"
TORCH_OMP="$(cd "$SP/torch/lib" 2>/dev/null && pwd)/libomp.dylib"

[ -e "$TORCH_OMP" ] || { echo "✗ 未找到 torch 的 libomp: $TORCH_OMP"; exit 1; }

changed=0
for rel in "faiss/.dylibs/libomp.dylib" "sklearn/.dylibs/libomp.dylib"; do
  target="$SP/$rel"
  [ -e "$target" ] || { echo "· 跳过（不存在）: $rel"; continue; }
  if [ -L "$target" ] && [ "$(readlink "$target")" = "$TORCH_OMP" ]; then
    echo "✓ 已修复: $rel"
    continue
  fi
  [ -e "$target.bak" ] || cp "$target" "$target.bak"
  ln -sf "$TORCH_OMP" "$target"
  echo "✓ 已链接: $rel → torch/lib/libomp.dylib（原文件备份 .bak）"
  changed=1
done

.venv-mandol/bin/python - <<'PY'
import ctypes, sys
import torch, faiss
libc = ctypes.CDLL(None)
libc._dyld_image_count.restype = ctypes.c_uint32
libc._dyld_get_image_name.restype = ctypes.c_char_p
libc._dyld_get_image_name.argtypes = [ctypes.c_uint32]
imgs = [libc._dyld_get_image_name(i).decode() for i in range(libc._dyld_image_count())]
omp = [p for p in imgs if "libomp" in p]
print(f"✓ 验证：torch={torch.get_num_threads()} / faiss={faiss.omp_get_max_threads()} 线程")
print(f"✓ 进程内 libomp 映像数 = {len(omp)}")
for p in omp:
    print(f"    {p}")
sys.exit(0 if len(omp) == 1 else 1)
PY

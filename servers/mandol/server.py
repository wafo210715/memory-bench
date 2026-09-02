# mandol：A档系统（arXiv:2606.29778，LoCoMo 92.21% SOTA 声明者）
# 机制：agglomerative 聚合式层级记忆图 + 定量检索；ingest 不调 LLM（embedding 聚合），检索带原生分数
# embedding：走 cloud 适配器（OpenAI 格式）重定向到智谱端点——
#   SILICONFLOW_EMBEDDINGS_URL=https://open.bigmodel.cn/api/coding/paas/v4/embeddings
#   SILICONFLOW_API_KEY=<智谱 key>（mandol 硬编码 SiliconFlow 品牌名，URL/key 均可 env 覆盖）
# scope 隔离：每 conversation 一套独立 SemanticGraph（Phase 1 起，对齐官方 per-sample 图），叠加 space_names
# 快照：save_graph/load_graph 原生持久化，落 MEMBENCH_STATE_DIR
# ⚠️ 独立 venv .venv-mandol（mandol 锁 numpy<2，与 chromadb 依赖冲突）

import json
import os
import sys
import time
from pathlib import Path


# ⚠️ faiss 与 torch 各自捆绑的 OpenMP 运行时在同进程会冲突 → Segmentation fault: 11
# （2026-08-31 实测，macOS ARM / faiss 1.15.0 + torch 2.8.0）。开启 SPLADE 后才暴露。
#
# 冲突是**双向**的，实测矩阵：
#   faiss 先导入                  → SPLADE 前向崩
#   torch 先导入                  → SPLADE 前向 OK，但 FAISS 检索反过来崩
#   KMP_DUPLICATE_LIB_OK=TRUE     → 仍崩
#   OMP_NUM_THREADS=1             → 全过，但全局降速（torch 也被压成单线程）
#   faiss.omp_set_num_threads(1)  → 全过，且 torch 保留 12 线程  ← 采用此项
#
# ⚠️ OpenMP 双副本问题（2026-08-31 实测，macOS ARM / faiss-cpu 1.15.0 + torch 2.8.0）
# torch 与 faiss-cpu 各自捆绑一份 libomp.dylib（install name 不同，dyld 当两个库加载），
# 但 OpenMP 运行时是全局单例语义 → 两份抢同一套线程池元数据 →
# SIGSEGV 于 libomp 的 __kmp_suspend_initialize_thread（crash report 已确认）。
#
# 根治：让 faiss 复用 torch 那份（见 scripts/fix_mandol_openmp.sh）。
#   修复后 torch=12 / faiss=12 线程，无需任何降级手段。
# 已排除的替代方案：KMP_DUPLICATE_LIB_OK 只压住加载期报错，运行期仍段错误；
#   OMP_NUM_THREADS=1 可绕过但会把 torch 一并压成单线程，污染要上报的 Search 延迟。
import torch  # noqa: F401  （先于 faiss 导入，勿调整顺序）
import faiss


def _assert_single_libomp() -> None:
    """双 libomp 会在检索阶段段错误。失效时快速报错，而不是留下神秘 crash。"""
    fp = Path(faiss.__file__).parent / ".dylibs" / "libomp.dylib"
    tp = Path(torch.__file__).parent / "lib" / "libomp.dylib"
    if fp.exists() and tp.exists() and fp.resolve() != tp.resolve():
        raise RuntimeError(
            "faiss 与 torch 加载了两份不同的 libomp.dylib，检索时会 SIGSEGV。\n"
            "修复：bash scripts/fix_mandol_openmp.sh"
        )


_assert_single_libomp()

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# mandol 及其依赖（jieba/spacy）的日志会漏到 stdout 污染 stdio JSON-RPC——全部改道 stderr
import logging

logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(name)s %(levelname)s %(message)s")
for _n in ("httpx", "urllib3", "filelock", "huggingface_hub", "sentence_transformers", "faiss", "jieba", "spacy"):
    logging.getLogger(_n).setLevel(logging.ERROR)

# MCP stdio 要求 stdout 纯净：mandol 库 get_logger 给 module logger 挂 StreamHandler(sys.stdout)
# 且 propagate=False（2026-08-22 S4 第一批实测），basicConfig 管不到。
# 根治：monkeypatch StreamHandler.__init__，强制任何显式传 sys.stdout 的 handler 改道 stderr。
import builtins

_orig_sh_init = logging.StreamHandler.__init__


def _safe_sh_init(self, stream=None):
    if stream is sys.stdout:
        stream = sys.stderr
    _orig_sh_init(self, stream)


logging.StreamHandler.__init__ = _safe_sh_init

_orig_print = builtins.print


def _print_stderr(*args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    _orig_print(*args, **kwargs)


builtins.print = _print_stderr

from fastmcp import FastMCP

from servers.common.base import BaseState
from servers.common.envelope import make_envelope
from servers.common.stats import StatsTracker

mcp = FastMCP("mandol")

_state = BaseState("mandol")
_stats = StatsTracker()
_SIDECAR = _state.state_dir / "scopes.json"
# Phase 1（2026-08-31）：每 conversation 一套独立 SemanticGraph，对齐官方 benchmark
# （locomo_triple_router.py 按 sample_id 分别 load_graph + unload_sample）。
# 物理隔离而非 space 逻辑过滤：使 BM25/SPLADE 的语料统计（avgdl/IDF）不跨 conv 污染，
# 从而保证分批灌入（3-conv → resume 全量）与一次灌完在数学上等价。
# 快照无需改造：BaseState.snapshot 拷贝整个 state_dir，子目录自动包含。
_GRAPHS_ROOT = _state.state_dir / "graphs"
_GRAPHS: dict = {}  # scope_id -> SemanticGraph（惰性加载）
_DEFAULT_SCOPE = "_default"

EMBED_MODEL = os.environ.get("MEMBENCH_EMBED_MODEL", "embedding-3")
# SPLADE 稀疏向量：官方 add_unit 默认 True（semantic_graph.py:383），旧封装显式关闭以避免拉本地 HF 模型。
# Phase 1 起默认开启（三路召回的 sparse 通道依赖它）；置 0 可回退。
SPARSE_ON = os.environ.get("MEMBENCH_MANDOL_SPARSE", "1").lower() not in ("0", "false", "no")
# Phase 2 三塔构建：默认**关**。开启后在 snapshot 落盘前触发（ingest 已全部完成）。
# 默认关的理由：保证“Phase 1 态”基线可重复，且不会意外给旧 run 加上 LLM 成本。
TOWERS_ON = os.environ.get("MEMBENCH_MANDOL_TOWERS", "0").lower() in ("1", "true", "yes")
_towers_stat: dict = {}
# Phase 3 三塔检索：默认**关**。开启后 retrieve 走三塔并行召回 + 级联剪枝，
# 关闭时仍为单图 dense kNN（保证 Phase 1/2 的历史结果可复现）。
TRITOWER_ON = os.environ.get("MEMBENCH_MANDOL_TRITOWER", "0").lower() in ("1", "true", "yes")
# SPLADE 失败时 SemanticMap 只警告不报错（semantic_map.py:1644 skip sparse embedding）——
# 静默降级会让三路召回退化成两路而不自知。逐 unit 实测并记入 stats，
# 使降级在 run 产物里可见（对齐 mem0 arm 的 channels.bm25.enabled 报告惯例）。
_sparse_stat = {"attempted": 0, "generated": 0}


def _scopes() -> dict:
    if _SIDECAR.exists():
        return json.loads(_SIDECAR.read_text())
    return {"scope_ids": [], "sessions": []}


def _save_scope(scope_id: str | None, session_id: str | None, n_units: int) -> None:
    s = _scopes()
    if scope_id and scope_id not in s["scope_ids"]:
        s["scope_ids"].append(scope_id)
    if session_id and session_id not in s["sessions"]:
        s["sessions"].append(session_id)
    s["n_units"] = s.get("n_units", 0) + n_units
    _SIDECAR.parent.mkdir(parents=True, exist_ok=True)
    _SIDECAR.write_text(json.dumps(s, ensure_ascii=False))


def _patch_mandol_logging():
    """mandol 库 get_logger 给 module logger 挂 StreamHandler(sys.stdout) 且 propagate=False，
    污染 MCP stdio JSON-RPC（2026-08-22 S4 第一批实测）。强制所有 stdout handler 迁到 stderr，
    并包一层 get_logger 防止后续模块再挂 stdout handler。"""
    from mandol.utils import logging_config as _lc

    def _is_stdout_handler(h):
        return isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is sys.stdout

    for _n in list(logging.root.manager.loggerDict):
        _lg = logging.getLogger(_n)
        for _h in list(_lg.handlers):
            if _is_stdout_handler(_h):
                _lg.removeHandler(_h)
                if not _lg.handlers:
                    _lg.addHandler(logging.StreamHandler(sys.stderr))

    _orig_get_logger = _lc.get_logger

    def _safe_get_logger(*args, **kwargs):
        lg = _orig_get_logger(*args, **kwargs)
        for _h in list(lg.handlers):
            if _is_stdout_handler(_h):
                lg.removeHandler(_h)
                if not lg.handlers:
                    lg.addHandler(logging.StreamHandler(sys.stderr))
        return lg

    _lc.get_logger = _safe_get_logger


def _graph_dir(scope_id: str):
    return _GRAPHS_ROOT / scope_id


def _get_graph(scope_id: str | None = None):
    """取（并惰性加载）某个 conversation 的独立 SemanticGraph。"""
    sid = scope_id or _DEFAULT_SCOPE
    if sid not in _GRAPHS:
        from mandol import SemanticGraph, SemanticMap

        _patch_mandol_logging()

        # MODEL_CONFIG 是内置注册表（按模型名查 config）——注入智谱 embedding-3 的 cloud 条目，
        # 走 SiliconFlow 适配器（URL/key 已重定向到智谱端点），避免拉本地 HF 模型
        dim = int(os.environ.get("MEMBENCH_EMBED_DIM", "2048"))
        if EMBED_MODEL not in SemanticMap.MODEL_CONFIG:
            SemanticMap.MODEL_CONFIG[EMBED_MODEL] = {
                "dim": dim, "type": "cloud", "provider": "siliconflow",
                "modalities": ["text"], "wrapper": None,
            }
        smap = SemanticMap(embedding_model_name=EMBED_MODEL, embedding_dim=dim)
        d = _graph_dir(sid)
        if d.exists() and any(d.iterdir()):
            _GRAPHS[sid] = SemanticGraph.load_graph(str(d), semantic_map_instance=smap)
        else:
            _GRAPHS[sid] = SemanticGraph(semantic_map_instance=smap)
    return _GRAPHS[sid]


def _drop_graphs() -> None:
    _GRAPHS.clear()


def _persist() -> None:
    for sid, g in _GRAPHS.items():
        d = _graph_dir(sid)
        d.mkdir(parents=True, exist_ok=True)
        g.save_graph(str(d))


@mcp.tool
def add_conversation(session_id: str, turns: list[dict], scope: dict, metadata: dict | None = None) -> dict:
    """逐 turn 一个 MemoryUnit（mandol 原生消息粒度），space=scope.id 隔离。ingest 不调 LLM。"""
    t0 = time.perf_counter()
    from mandol import MemoryUnit

    g = _get_graph(scope.get("id"))
    n = 0
    for i, t in enumerate(turns):
        # 时间前缀由 harness 层统一加（spec §7），server 不重复处理
        unit = MemoryUnit(
            uid=f"{session_id}#{i}",
            raw_data={"text_content": f"{t.get('role', 'user')}: {t.get('content', '')}"},
            # message_index 对齐官方 L0（step1_generate_l0_graph.py:894 按此排序），Phase 2 建时序边要用
            metadata={"session_id": session_id, "scope": scope.get("id"),
                      "timestamp": t.get("timestamp"), "message_index": i},
        )
        g.add_unit(
            unit,
            space_names=[scope.get("id")] if scope.get("id") else None,
            generate_sparse_embedding=SPARSE_ON,
        )
        if SPARSE_ON:  # add_unit 就地回填 unit.sparse_embedding，成功与否在此实测
            _sparse_stat["attempted"] += 1
            if getattr(unit, "sparse_embedding", None) is not None:
                _sparse_stat["generated"] += 1
        n += 1
    _save_scope(scope.get("id"), session_id, n)
    _stats.n_sessions = len(_scopes()["sessions"])
    return {"accepted_turns": n, "native_notes": f"mandol 聚合完成，耗时 {int((time.perf_counter() - t0) * 1000)}ms（纯 embedding，无 LLM 调用）"}


@mcp.tool
def retrieve(query: str, query_mode: str = "fixed", top_k: int = 5, filter: dict | None = None) -> dict:
    """相似度检索，原生分数归一困难则透传（mandol 分数语义为图内相似度）。"""
    t0 = time.perf_counter()
    notes = []
    scope_ids = _scopes()["scope_ids"]
    if filter and filter.get("scope_id"):
        gid = filter["scope_id"]
    else:
        if len(scope_ids) > 1:
            notes.append("MULTI_SCOPE: 未指定 filter.scope_id，仅检索首个 conversation 图")
        gid = scope_ids[0] if scope_ids else None
    g = _get_graph(gid)  # per-conversation 独立图，先定 gid 再取图

    if TRITOWER_ON and gid:
        from servers.mandol.towers.retrieve import tower_retrieve

        pairs, tri_notes = tower_retrieve(
            g, _get_graph(f"{gid}__episodic"), _get_graph(f"{gid}__kg"), query, top_k)
        if tri_notes.get("tower_hits"):
            notes.append("TRITOWER: " + json.dumps(tri_notes, ensure_ascii=False))
        if pairs:
            results = [make_envelope(
                memory_id=str(getattr(u, "uid", "")),
                text=str((getattr(u, "raw_data", None) or {}).get("text_content", "")),
                session_id=(getattr(u, "metadata", None) or {}).get("session_id"),
                turn_range=None,
                timestamp=(getattr(u, "metadata", None) or {}).get("timestamp"),
                score=round(float(s), 4) if isinstance(s, (int, float)) else None,
                raw_format="mandol_tritower",
            ) for u, s in pairs]
            return {"results": results, "query_used": query, "query_mode": query_mode,
                    "latency_ms": int((time.perf_counter() - t0) * 1000),
                    "native_notes": "; ".join(notes)}
    if filter and any(k for k in filter if k != "scope_id"):
        notes.append("FILTER_IGNORED: 仅支持 scope_id")
    raw = g.search_similarity_in_graph(query_text=query, top_k=top_k, ms_names=[gid] if gid else None, return_score=True)
    results = []
    for item in raw:
        unit, score = (item if isinstance(item, (tuple, list)) else (item, None))
        meta = getattr(unit, "metadata", None) or {}
        raw_data = getattr(unit, "raw_data", None) or {}
        uid = getattr(unit, "uid", "")
        turn_range = None
        if "#" in str(uid):
            try:
                turn_range = [int(uid.rsplit("#", 1)[1])] * 2
            except ValueError:
                pass
        results.append(make_envelope(
            memory_id=uid,
            text=str(raw_data.get("text_content", "")),
            session_id=meta.get("session_id"),
            turn_range=turn_range,
            timestamp=meta.get("timestamp"),
            score=round(float(score), 4) if isinstance(score, (int, float)) else None,
            raw_format="mandol_unit",
        ))
    return {
        "results": results,
        "query_used": query,
        "query_mode": query_mode,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
        "native_notes": "; ".join(notes),
    }


@mcp.tool
def reset() -> dict:
    """清图 + 清持久化目录。幂等。"""
    _drop_graphs()
    # sparse 计数器必须一并归零：harness 在 arm/run 之间调 reset，
    # 残留计数会让 system_stats.jsonl 误报本轮的 sparse 覆盖率。
    _sparse_stat.update(attempted=0, generated=0)
    _state.hard_reset_dir()
    _stats.mark_reset()
    _stats.n_sessions = 0
    return {"ok": True, "cleared": {"system": "mandol"}}


@mcp.tool
def stats() -> dict:
    s = _scopes()
    d = _stats.to_dict(n_memories=s.get("n_units", 0))
    att, gen = _sparse_stat["attempted"], _sparse_stat["generated"]
    d["mandol"] = {
        "n_scopes": len(s.get("scope_ids", [])),  # per-conversation 独立图数
        "sparse": {
            "requested": SPARSE_ON,
            "attempted": att,
            "generated": gen,
            # SPLADE 不可用时 SemanticMap 静默跳过，此处显式暴露
            "code": ("ok" if att and gen == att else
                     "disabled" if not SPARSE_ON else
                     "splade_unavailable" if att and gen == 0 else
                     "partial" if att else "no_data"),
        },
        "towers": {"enabled": TOWERS_ON, "built": list(_towers_stat.keys()),
                   "detail": _towers_stat},
        "tritower_retrieval": TRITOWER_ON,
    }
    return d


def _build_towers() -> None:
    """三塔构建（Phase 2）。放在 snapshot 落盘前——此时 ingest 已全部完成，
    与官方 dataset_maker 的离线批处理语义一致（runner.py Phase A 本就是灌完再 snapshot）。"""
    from servers.mandol.towers.orchestrator import build_scope

    marker_dir = _state.state_dir / "towers"
    for sid in _scopes()["scope_ids"]:
        try:
            r = build_scope(sid, _get_graph(sid), _get_graph, marker_dir,
                            SPARSE_ON, log=lambda m: print(m, file=sys.stderr))
            _towers_stat[sid] = r
        except Exception as e:  # noqa: BLE001 单个 conv 失败不应阻断整批
            _towers_stat[sid] = {"scope": sid, "error": f"{type(e).__name__}: {e}"}
            print(f"[towers] {sid} 失败: {e}", file=sys.stderr)


@mcp.tool
def snapshot(tag: str) -> dict:
    if TOWERS_ON:
        _build_towers()
    _persist()  # 先落盘再拷目录
    r = _state.snapshot(tag)
    _stats.snapshots = _state.tags()
    return r


@mcp.tool
def restore(tag: str) -> dict:
    _drop_graphs()
    r = _state.restore(tag)
    if not r.get("ok"):
        return r
    for _sid in _scopes()["scope_ids"]:  # 触发 load_graph 校验每个 conversation 图可加载
        _get_graph(_sid)
    _stats.snapshots = _state.tags()
    _stats.n_sessions = len(_scopes()["sessions"])
    return r


if __name__ == "__main__":
    mcp.run()  # stdio

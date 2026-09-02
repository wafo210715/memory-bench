"""Phase 3 检索层：三塔并行召回 → 级联剪枝。

逐条对齐官方复现路径 benchmark_locomo/task_eval/locomo_triple_router.py：
  hierarchical  HierarchicalRetriever.search(top_k=15)        —— 内部按 L0/L1/L2 分层，三路召回
  kg            MultiRetriever.smart_search(top_k=30)         —— bm25+cosine+splade → RRF → rerank
  episodic      MultiRetriever.smart_search(top_k=30)         —— 同上
  三塔并行（ThreadPoolExecutor）→ 合并 → CascadeConfidencePruner → final_top_k=20

参数取自官方复现脚本 scripts/run_reproduction_suite.sh（作者跑出论文数字时的实际配置）：

    --topk-hierarchical 15 --topk-similarity 30 --topk-graph 0 --topk-episodic 30
    --final-top-k 20 --weight 0.34/0.33/0.33
    --enable-second-stage-rerank --rerank-strategy tower_separate --reranker-type baai
    --enable-cascade-pruner --cascade-mad-multiplier 3.0 --cascade-lambda-mmr 0.7
    --cascade-prune-mode STRICT_THRESHOLD --cascade-absolute-min-score -5.0

> [!warning] 脚本参数与论文正文不一致
> 论文 Eq.(1) 写 κ=2.5，代码默认也是 2.5，但**复现脚本用 3.0**；λ 代码默认 0.6、脚本 0.7。
> 这里采用脚本值（＝产生论文数字的实际配置），差异需写入诚实性声明。

router 不接：其论文主结果配置（GPT-4.1-mini）的路由表本身即恒等映射，
五类问题全部映射到 `_cfg_full()`，等价于三塔全开 + 固定预算。
"""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

# 官方复现脚本的预算与权重
TOPK_HIERARCHICAL = 15
TOPK_SIMILARITY = 30      # kg 塔
TOPK_EPISODIC = 30
FINAL_TOP_K = 20
RERANKER_TYPE = os.environ.get("MEMBENCH_MANDOL_RERANKER", "baai")

# 级联剪枝（脚本值，非代码默认值）
CASCADE_MAD_MULTIPLIER = 3.0
CASCADE_LAMBDA_MMR = 0.7
CASCADE_ABS_MIN_SCORE = -5.0
CASCADE_PRUNE_MODE = "STRICT_THRESHOLD"

_RERANK_ENABLED = os.environ.get("MEMBENCH_MANDOL_RERANK", "1").lower() not in ("0", "false", "no")

# ⚠️ 检索器必须缓存。每次查询新建 MultiRetriever 会重载 BM25/SPLADE 索引并重新
# 加载 2.3GB 的 cross-encoder，实测 **96 秒/查询**（1500 题 ≈ 40 小时）。
# 官方同样是每个 sample 建一次然后复用（locomo_triple_router.py 的 self.*_retrievers 字典）。
_RETRIEVER_CACHE: dict[int, Any] = {}     # id(graph) -> MultiRetriever
_HIER_CACHE: dict[int, Any] = {}          # id(graph) -> HierarchicalRetriever
_RERANKER_MANAGER: Any = None             # 全局共享，避免重复加载模型


# cross-encoder 的 dtype/设备：mandol 无条件用 bfloat16 + cuda☆cpu（rerank_manager.py:443,462），
# 这是为 CUDA 写的。macOS 上落到 CPU+bf16，bf16 在 CPU 上是软件模拟——实测：
#   CPU/bfloat16 125 ms/对 · CPU/float32 18 ms/对 · MPS/float32 14 · MPS/float16 8
# 只改 dtype（不改算法、不改候选集），属于硬件适配，不影响检索语义。
_RERANK_DTYPE = os.environ.get("MEMBENCH_MANDOL_RERANK_DTYPE", "float32")


def _patch_reranker_dtype() -> None:
    """把 cross-encoder 的 torch_dtype 从 bfloat16 改成可用 dtype。幂等。"""
    import torch
    from transformers import AutoModelForSequenceClassification as _M

    if getattr(_M, "_membench_dtype_patched", False):
        return
    orig = _M.from_pretrained
    want = getattr(torch, _RERANK_DTYPE, torch.float32)

    def patched(*a, **kw):
        if kw.get("torch_dtype") is torch.bfloat16:
            kw["torch_dtype"] = want
        return orig(*a, **kw)

    _M.from_pretrained = patched
    _M._membench_dtype_patched = True


def _reranker_manager():
    global _RERANKER_MANAGER
    if _RERANKER_MANAGER is None and _RERANK_ENABLED:
        _patch_reranker_dtype()
        from mandol.retrieval.rerank_manager import RerankerManager
        _RERANKER_MANAGER = RerankerManager()
    return _RERANKER_MANAGER


def _as_pairs(results: Any) -> list[tuple[Any, float]]:
    """把各检索器的返回统一成 [(unit, score)]。"""
    out: list[tuple[Any, float]] = []
    for r in results or []:
        if isinstance(r, tuple) and len(r) >= 2:
            out.append((r[0], float(r[1] or 0.0)))
        elif hasattr(r, "unit"):                      # RetrievalResult
            out.append((r.unit, float(getattr(r, "score", 0.0) or 0.0)))
        elif hasattr(r, "uid"):                       # 裸 MemoryUnit
            out.append((r, 0.0))
    return out


def _multi_retriever(graph: Any):
    """取（并缓存）某个图的 MultiRetriever，预先建好三路索引。"""
    key = id(graph)
    mr = _RETRIEVER_CACHE.get(key)
    if mr is None:
        from mandol.retrieval.advance_retriever import MultiRetriever
        from mandol.retrieval.retrieval_interface import RetrievalMethod

        mr = MultiRetriever(retrieval_source=graph, preload_rerankers=False,
                            reranker_manager=_reranker_manager())
        mr.build_all_indexes(methods_to_build=[
            RetrievalMethod.BM25, RetrievalMethod.COSINE_SIMILARITY, RetrievalMethod.SPLADE])
        _RETRIEVER_CACHE[key] = mr
    return mr


def _smart_search(graph: Any, query: str, top_k: int) -> list[tuple[Any, float]]:
    """kg / episodic 塔：三路召回 + RRF + 重排（locomo_triple_router.py:2050）。"""
    mr = _multi_retriever(graph)
    kwargs = dict(query=query, methods=["bm25", "cosine_similarity", "splade"],
                  fusion_method="rrf", top_k=top_k, return_detailed=False)
    if _RERANK_ENABLED:
        kwargs["rerank_method"] = RERANKER_TYPE
    return _as_pairs(mr.smart_search(**kwargs))


def _hierarchical_search(graph: Any, query: str, top_k: int) -> list[tuple[Any, float]]:
    """hierarchical 塔：分层检索（locomo_triple_router.py:1953）。

    HierarchicalRetriever 内部按 LAYER_TO_SPACE 逐层查 L0/L1/L2，
    因此单元必须挂在官方规范 space 上（见 scripts/migrate_tower_spaces.py）。
    """
    key = id(graph)
    hr = _HIER_CACHE.get(key)
    if hr is None:
        from mandol.hierarchical.hierarchical_retriever import create_hierarchical_retriever
        hr = create_hierarchical_retriever(graph, multi_retriever=_multi_retriever(graph))
        _HIER_CACHE[key] = hr
    kwargs = {"query": query, "top_k": top_k}
    if _RERANK_ENABLED:
        kwargs["rerank_method"] = RERANKER_TYPE
    return _as_pairs(hr.search(**kwargs))


# 级联剪枝的 id 提取（官方 locomo_triple_router_quantification.py:525-586）。
# ⚠️ _RE_PROPER_NOUN 的 (?:\s+[A-Z][a-z]+)+ 要求**至少两个连续大写词**，
# 单名字 "Caroline" 不匹配；这决定了 NER 兜底很少产出人名。
_RE_PROPER_NOUN = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")
_RE_QUOTED = re.compile(r'"([^"]{2,50})"')

# 官方对三塔均提取 entity_ids；本项目首版只填了 KG 塔，导致跨塔冲突（stage2）
# 与实体多样性惩罚（stage3 entity_penalty=0.15）同时失效。默认关，避免影响进行中的 run。
CASCADE_IDS_ON = os.environ.get("MEMBENCH_MANDOL_CASCADE_IDS", "0").lower() not in ("0", "false", "no")

_SPEAKER_STOP = ("unknown", "system", "assistant", "user")


def _fallback_entities(text: str) -> list[str]:
    """官方 `_extract_fallback_entities` 的逐句移植（:529-548）。"""
    if not text:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for sent in re.split(r"[.!?]\s+", text):
        words = sent.split()
        for m in _RE_PROPER_NOUN.finditer(sent):
            if m.start() == 0 and len(words) > 0:  # 句首大写不算专名
                continue
            key = m.group(1).lower()
            if key not in seen:
                seen.add(key)
                result.append(key)
    for m in _RE_QUOTED.finditer(text):
        key = m.group(1).lower()
        if key not in seen:
            seen.add(key)
            result.append(key)
    return result


def _entity_ids(raw: dict, meta: dict, tower: str, text: str) -> list[str]:
    """官方 `_extract_entity_ids_for_cascade` 的移植（:552-586）。

    官方的 source_type 取值为 graph / episodic / 其他；本项目的 kg 塔对应 graph。
    """
    ids: list[str] = []
    if tower == "kg":
        name = (raw.get("entity_canonical") or raw.get("entity_text")
                or raw.get("entity_name") or meta.get("entity_name") or "")
        if name:
            ids.append(str(name).lower().strip())
        target = raw.get("target_entity") or raw.get("related_entity") or ""
        if target:
            ids.append(str(target).lower().strip())
    elif tower == "episodic":
        ents = (raw.get("entities") or raw.get("entity_ids")
                or raw.get("involved_entities") or meta.get("entities") or [])
        if isinstance(ents, list):
            ids.extend(str(e).lower().strip() for e in ents if e)
    else:  # hierarchical：官方用说话人作实体
        sp = raw.get("speaker") or raw.get("role") or meta.get("speaker") or meta.get("role") or ""
        if sp and str(sp).lower() not in _SPEAKER_STOP:
            ids.append(str(sp).lower().strip())
    if not ids:
        ids = [f"ner:{e}" for e in _fallback_entities(text)]
    return ids


def _to_chunks(triples: list[tuple[Any, float, str]]) -> list[Any]:
    """构造 EnhancedCandidateChunk（级联剪枝的输入）。"""
    from mandol.quantification.cascade_pruner import EnhancedCandidateChunk, TowerSource

    tower_map = {"hierarchical": TowerSource.HIERARCHICAL,
                 "episodic": TowerSource.EPISODIC,
                 "kg": TowerSource.KG}
    chunks = []
    for i, (unit, score, tower) in enumerate(triples):
        raw = getattr(unit, "raw_data", None) or {}
        meta = getattr(unit, "metadata", None) or {}
        text = str(raw.get("text_content", "") or "")
        if not text.strip():
            continue
        ts = 0.0
        try:  # timestamp 供跨源仲裁的时间衰减用（Eq.2 的 f_time）
            d = str(meta.get("timestamp") or raw.get("date") or "")[:10]
            if len(d) == 10:
                from datetime import datetime
                ts = datetime.strptime(d, "%Y-%m-%d").timestamp()
        except Exception:  # noqa: BLE001
            pass
        cid = str(getattr(unit, "uid", f"c{i}"))
        if CASCADE_IDS_ON:
            ents = _entity_ids(raw, meta, tower, text)
            # 官方：`_extract_source_chunk_ids_for_cascade(unit) or [chunk_id]`（:737）
            src = raw.get("source_chunk_ids") or raw.get("source_ids") \
                or meta.get("source_unit_uids") or []
            src = [str(s) for s in src if s] if isinstance(src, list) else []
            src = src or [cid]
        else:  # 首版行为：只有 KG 塔有实体、source 全空（stage2 结构性失效）
            ents = [str(meta.get("entity_name"))] if meta.get("entity_name") else []
            src = []
        chunks.append(EnhancedCandidateChunk(
            chunk_id=cid,
            text=text, ce_score=float(score),
            rank_dense=i, rank_splade=i, rank_bm25=i,
            tower_source=tower_map.get(tower, TowerSource.HIERARCHICAL),
            timestamp=ts,
            entity_ids=ents,
            source_chunk_ids=src,
            memory_space=str(meta.get("memory_level", "")),
            raw_metadata=dict(meta),
        ))
    return chunks


def tower_retrieve(base_graph: Any, ep_graph: Any, kg_graph: Any, query: str,
                   top_k: int = FINAL_TOP_K) -> tuple[list[tuple[Any, float]], dict]:
    """三塔并行召回 + 级联剪枝。返回 ([(unit, score)], 诊断信息)。"""
    notes: dict[str, Any] = {}

    def run(fn, *a):
        try:
            return fn(*a)
        except Exception as e:  # noqa: BLE001 单塔失败不应拖垮整次检索
            notes.setdefault("tower_errors", []).append(f"{fn.__name__}: {type(e).__name__}: {e}")
            return []

    with ThreadPoolExecutor(max_workers=3) as ex:
        f_h = ex.submit(run, _hierarchical_search, base_graph, query, TOPK_HIERARCHICAL)
        f_e = ex.submit(run, _smart_search, ep_graph, query, TOPK_EPISODIC)
        f_k = ex.submit(run, _smart_search, kg_graph, query, TOPK_SIMILARITY)
        h, e, k = f_h.result(), f_e.result(), f_k.result()

    notes["tower_hits"] = {"hierarchical": len(h), "episodic": len(e), "kg": len(k)}
    triples = ([(u, s, "hierarchical") for u, s in h]
               + [(u, s, "episodic") for u, s in e]
               + [(u, s, "kg") for u, s in k])
    if not triples:
        return [], notes

    by_uid = {str(getattr(u, "uid", "")): u for u, _, _ in triples}
    chunks = _to_chunks(triples)
    if not chunks:
        return [], notes

    try:
        from mandol.quantification.cascade_pruner import CascadeConfidencePruner
        from mandol.quantification.confidence_pruner import PruneMode

        pruner = CascadeConfidencePruner(
            mode=PruneMode(CASCADE_PRUNE_MODE),
            mad_multiplier=CASCADE_MAD_MULTIPLIER,
            lambda_mmr=CASCADE_LAMBDA_MMR,
            absolute_min_score=CASCADE_ABS_MIN_SCORE,
        )
        res = pruner.prune(chunks)
        notes["cascade"] = {
            "stage1_in": res.stage1_input_count, "stage1_out": res.stage1_output_count,
            "stage2_conflicts": res.stage2_conflicts_found, "stage2_dropped": res.stage2_dropped_count,
            "stage3_penalties": res.stage3_diversity_penalties,
            "tokens": res.total_tokens_used, "mode": str(res.mode_used),
        }
        picked = [(by_uid.get(pc.chunk.chunk_id), pc.chunk.ce_score)
                  for pc in res.selected_chunks]
        picked = [(u, s) for u, s in picked if u is not None]
    except Exception as ex_:  # noqa: BLE001 剪枝失败则退回按分数排序，不丢结果
        notes["cascade_error"] = f"{type(ex_).__name__}: {ex_}"
        picked = sorted(((u, s) for u, s, _ in triples), key=lambda x: -x[1])

    # 去重后截断到 final_top_k
    seen, out = set(), []
    for u, s in picked:
        uid = str(getattr(u, "uid", ""))
        if uid in seen:
            continue
        seen.add(uid)
        out.append((u, s))
        if len(out) >= top_k:
            break
    return out, notes

#!/usr/bin/env python
"""把 L1/L2 单元的检索文本从原始 JSON dump 改写成展平自然语句（Phase 3 前置）。

背景：Phase 2 首版 `load_l1_l2` 直接存 `json.dumps(抽取结果)`。两个后果——

1. **伤检索**：键名、引号、转义占满 token，稀释语义信号；
2. **拖垮重排**：实测 hierarchical 塔 L1 层仅 19 个候选却占 37s，
   因为每条文本比 L0 长约 15 倍，cross-encoder 是按序列长度平方级付费的。

抽取结果本身没落盘（orchestrator 只写计数 marker），但**图里存的就是 JSON 原文**，
所以直接 `json.loads` 回来重新展平即可：零 LLM 调用，只重新嵌入 L1/L2 这几十个单元。

同 uid 再次 `add_unit` 即为更新（与 `apply_l0_indexing` 同一机制）。
文本变了 → BM25/SPLADE 稀疏索引必须重建，否则倒排里还是旧词项。

用法：
    .venv-mandol/bin/python scripts/migrate_l1l2_text.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

os.environ.setdefault("MEMBENCH_EMBED_DIM", "2048")

import torch  # noqa: E402,F401  （先于 faiss，见 server.py 的 OpenMP 说明）
import faiss  # noqa: E402,F401

from servers.mandol.towers.load import SPACE_L1, SPACE_L2, _flatten_extraction  # noqa: E402

LEVEL_TO_SPACE = {"L1_Summary": SPACE_L1, "L2_Insight": SPACE_L2}
SPARSE_ON = os.environ.get("MEMBENCH_MANDOL_SPARSE", "1").lower() not in ("0", "false", "no")


def main() -> int:
    from mandol import MemoryUnit, SemanticGraph, SemanticMap
    from mandol.retrieval.retrieval_interface import RetrievalMethod

    embed = os.environ.get("MEMBENCH_EMBED_MODEL", "embedding-3")
    dim = int(os.environ["MEMBENCH_EMBED_DIM"])
    root = Path(os.environ.get("MEMBENCH_STATE_DIR") or (REPO / ".state")) / "mandol" / "graphs"
    if not root.is_dir():
        print(f"✗ 找不到图目录 {root}", file=sys.stderr)
        return 1

    total_rewritten = 0
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        # L1/L2 只存在于 base 图；episodic/kg 是独立图，跳过省去一次全图重建
        if d.name.endswith("__episodic") or d.name.endswith("__kg"):
            continue

        if embed not in SemanticMap.MODEL_CONFIG:
            SemanticMap.MODEL_CONFIG[embed] = {
                "dim": dim, "type": "cloud", "provider": "siliconflow",
                "modalities": ["text"], "wrapper": None,
            }
        smap = SemanticMap(embedding_model_name=embed, embedding_dim=dim)
        g = SemanticGraph.load_graph(str(d), semantic_map_instance=smap)
        units = g.get_all_units() or []
        if not units:
            print(f"  · {d.name}: 空图，跳过")
            continue

        rewritten, skipped, before, after = 0, 0, 0, 0
        for u in units:
            meta = dict(getattr(u, "metadata", None) or {})
            space = LEVEL_TO_SPACE.get(str(meta.get("memory_level", "")))
            if not space:
                continue
            raw = dict(getattr(u, "raw_data", None) or {})
            text = str(raw.get("text_content") or "")
            # 只改还是 JSON 的那些；已展平过的再跑一次不会被误伤（幂等）
            if not text.lstrip().startswith(("{", "[")):
                skipped += 1
                continue
            try:
                obj = json.loads(text)
            except Exception:  # noqa: BLE001
                skipped += 1
                continue
            limit = 2000 if meta.get("memory_level") == "L2_Insight" else 1200
            flat = _flatten_extraction(obj, limit=limit)
            if not flat.strip():
                skipped += 1
                continue
            before += len(text)
            after += len(flat)
            raw["text_content"] = flat
            g.add_unit(MemoryUnit(uid=u.uid, raw_data=raw, metadata=meta),
                       space_names=[space], generate_sparse_embedding=SPARSE_ON)
            rewritten += 1

        if rewritten:
            # 文本变了，稀疏倒排必须重建（dense 已随 add_unit 重新嵌入）
            mr = g.get_multi_retriever() if hasattr(g, "get_multi_retriever") else None
            if mr is None:
                from mandol.retrieval.advance_retriever import MultiRetriever
                mr = MultiRetriever(retrieval_source=g, preload_rerankers=False)
            mr.build_all_indexes(
                methods_to_build=[RetrievalMethod.BM25, RetrievalMethod.SPLADE],
                force_rebuild=True)
        g.save_graph(str(d))
        total_rewritten += rewritten
        avg_b = before // rewritten if rewritten else 0
        avg_a = after // rewritten if rewritten else 0
        print(f"  ✅ {d.name}: 重写 {rewritten} 个（跳过 {skipped}）"
              f"  平均文本 {avg_b} → {avg_a} 字符")

    print(f"\n合计重写 {total_rewritten} 个 L1/L2 单元")
    return 0


if __name__ == "__main__":
    sys.exit(main())

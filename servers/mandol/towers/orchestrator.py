"""三塔构建编排（Phase 2）。

触发点：ingest 全部完成后、snapshot 落盘之前。
依据 bench/runner.py Phase A 本就是「批量灌完 → snapshot → 逐题答题」，
不存在在线增量需求，故按官方的离线批处理语义构建。

断点续跑：conversation 粒度（Q8）。官方 8 个 step 零断点，一次中断整个 conv 重来；
这里每个 conv 建完写 done 标记，重跑自动跳过。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from . import episodic as ep
from . import hierarchical as hi
from . import kg as kg_mod
from . import load as ld
from .llm import TowerLLM


def _log(cb: Callable[[str], None] | None, msg: str) -> None:
    if cb:
        cb(msg)


def build_scope(scope_id: str, base_graph: Any, get_graph: Callable[[str], Any],
                marker_dir: Path, sparse: bool,
                llm: TowerLLM | None = None,
                log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """为一个 conversation 构建三塔。已完成则跳过（conv 粒度断点）。"""
    marker = marker_dir / f"{scope_id}.done.json"
    if marker.exists():
        try:
            return {"scope": scope_id, "skipped": True, **json.loads(marker.read_text())}
        except Exception:  # noqa: BLE001 标记损坏就当没建过
            pass

    t0 = time.perf_counter()
    llm = llm or TowerLLM()
    units = list(getattr(base_graph, "get_all_units", lambda: [])() or [])
    if not units:
        smap = getattr(base_graph, "semantic_map", None)
        units = list(getattr(smap, "units", {}).values()) if smap else []

    msgs = hi.collect_l0_messages(units)
    _log(log, f"[{scope_id}] L0 候选 {len(msgs)} 条（原始单元 {len(units)}）")
    if not msgs:
        return {"scope": scope_id, "error": "无可解析的 L0 单元"}

    # ---- hierarchical：L0 上下文改写 → L1 → L2 → 覆盖 text_content + 建边 ----
    ok0 = hi.build_l0(msgs, llm, max_workers=8)
    _log(log, f"[{scope_id}] L0 改写 {ok0}/{len(msgs)}")
    l1 = hi.build_l1(scope_id, msgs, llm, max_workers=8)
    _log(log, f"[{scope_id}] L1 {len(l1)} 个 session")
    l2 = hi.build_l2(scope_id, l1, llm)
    _log(log, f"[{scope_id}] L2 {'✓' if l2 else '✗'}")

    n_over = ld.apply_l0_indexing(base_graph, msgs, sparse)
    n_temporal = ld.link_temporal(base_graph, msgs)
    hstat = ld.load_l1_l2(base_graph, scope_id, l1, l2, sparse)
    _log(log, f"[{scope_id}] hierarchical: 覆盖 {n_over} / 时序边 {n_temporal} / "
              f"抽象 {hstat['units']} 单元 {hstat['edges']} 溯源边")

    # ---- episodic（独立图）----
    facts = ep.build_facts(msgs, llm, max_workers=8)
    facts = ep.dedup_facts(facts, llm, max_workers=8)
    g_ep = get_graph(f"{scope_id}__episodic")
    estat = ld.load_episodic(g_ep, scope_id, facts, sparse)
    _log(log, f"[{scope_id}] episodic: {estat['units']} 事实 / {estat['edges']} 溯源边")

    # ---- kg（独立图）----
    ents = kg_mod.build_entities(msgs, llm, max_workers=10)
    ents = kg_mod.dedup_entities(ents, llm, max_workers=10)
    rels = kg_mod.build_relations(msgs, ents, llm, max_workers=10)
    rels += kg_mod.build_cross_session_relations(ents, llm)
    g_kg = get_graph(f"{scope_id}__kg")
    kstat = ld.load_kg(g_kg, scope_id, ents, rels, sparse)
    _log(log, f"[{scope_id}] kg: {kstat['units']} 实体 / {kstat['edges']} 边（关系 {len(rels)}）")

    result = {
        "scope": scope_id,
        "l0_messages": len(msgs), "l0_rewritten": ok0,
        "l1_sessions": len(l1), "l2": bool(l2),
        "l0_text_overwritten": n_over, "temporal_edges": n_temporal,
        "hierarchical": hstat, "episodic": estat, "kg": kstat,
        "facts": len(facts), "entities": len(ents), "relations": len(rels),
        "llm": llm.stats(),
        "elapsed_s": round(time.perf_counter() - t0, 1),
    }
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result

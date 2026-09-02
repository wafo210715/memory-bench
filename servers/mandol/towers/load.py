"""三塔载入层（对齐 step4_load_to_semantic_graph.py）。

两件关键的事：

1. **L0 的 text_content 覆盖**（step4:354-367）
   step1 产出的 indexing_text 不在 MemoryUnit 里，必须在载入时覆盖回 text_content，
   否则 embedding 用的仍是原文——L0 那笔最大的 token 开销完全空转，且静默。

2. **建显式边**
   memory-bench 此前实测 `5882 nodes / 0 EDGES`，因为 add_unit 从不建边。
   时序边（同 session 相邻 message）、溯源边（抽象层 → L0）、实体关系边都在这里落。
"""

from __future__ import annotations

from typing import Any

from .hierarchical import L0Message

# 溯源与结构边的类型名（论文 §3.1.1 的显式结构边：时间顺序 / 引用 / 状态更新）
EDGE_TEMPORAL = "temporal_next"
EDGE_DERIVED = "derived_from"
EDGE_RELATION = "entity_relation"

# ❗ space 名必须用官方规范值（src/mandol/core/memory_space_registry.py TowerSpace）：
# HierarchicalRetriever.LAYER_TO_SPACE 按这些名字做分层检索，名字不对就什么都检不到。
SPACE_L0 = "hierarchical_memory:L0_Observation"
SPACE_L1 = "hierarchical_memory:L1_Summary"
SPACE_L2 = "hierarchical_memory:L2_Insight"
SPACE_EPISODIC = "episodic_memory"
SPACE_KG = "entity_relation:entities"


def apply_l0_indexing(graph: Any, msgs: list[L0Message], sparse: bool) -> int:
    """把 indexing_text 覆盖进 L0 单元的 text_content 并重新嵌入（step4:360）。

    同 uid 再次 add_unit 即为更新（semantic_map 日志 "added or updated"）。
    """
    from mandol import MemoryUnit

    n = 0
    for m in msgs:
        if not m.indexing_text:
            continue
        graph.add_unit(
            MemoryUnit(
                uid=m.uid,
                raw_data={
                    "text_content": m.indexing_text,          # ← 覆盖，检索走增强文本
                    "original_text": m.text,                  # 双视图：原文保留可溯
                    "speaker": m.speaker,
                    "session_id": m.session_id,
                    "date": m.session_date,
                    "dialogue_id": m.dialogue_id,
                },
                metadata={
                    "memory_level": "L0_Observation",
                    "session_id": m.session_id,
                    "message_index": m.message_index,
                    "speaker": m.speaker,
                    "timestamp": m.session_date,
                    "retrieval_field": "indexing_text",       # step4:367
                },
            ),
            space_names=[SPACE_L0],
            generate_sparse_embedding=sparse,
        )
        n += 1
    return n


def link_temporal(graph: Any, msgs: list[L0Message]) -> int:
    """同 session 内相邻 message 建时序边（论文 §3.1.1 的时间顺序显式边）。"""
    by_session: dict[str, list[L0Message]] = {}
    for m in msgs:
        by_session.setdefault(m.session_id, []).append(m)
    n = 0
    for group in by_session.values():
        group.sort(key=lambda x: x.message_index)
        for a, b in zip(group, group[1:]):
            try:
                # ⚠️ add_relationship 节点缺失时**返回 False 而不抛异常**
                # （semantic_graph.py:648 仅 ERROR 日志）。只捕异常会把失败当成成功。
                if graph.add_relationship(a.uid, b.uid, EDGE_TEMPORAL):
                    n += 1
            except Exception:  # noqa: BLE001 单条边失败不应中断整批
                pass
    return n


def _add_abstract(graph: Any, uid: str, text: str, level: str, sparse: bool,
                  space: str, extra_meta: dict[str, Any] | None = None) -> bool:
    from mandol import MemoryUnit

    if not text.strip():
        return False
    meta = {"memory_level": level}
    meta.update(extra_meta or {})
    graph.add_unit(
        MemoryUnit(uid=uid, raw_data={"text_content": text}, metadata=meta),
        space_names=[space], generate_sparse_embedding=sparse,
    )
    return True


def _link_sources(graph: Any, uid: str, source_uids: list[str]) -> int:
    """抽象节点 → 原始 L0 单元的溯源边（论文 §3.1.2 的 source_unit_uids）。

    ⚠️ **只在同一图内生效**。episodic/kg 是独立图，其 source 指向 base 图的 L0 单元，
    跨图连边会被 `add_relationship` 静默拒绝（返回 False）。因此两塔的溯源信息
    另写入 metadata.source_unit_uids（见 _add_abstract 调用处），不依赖边。
    官方主路径（_cfg_full: topk_graph=0 / use_entity_relation=False）不做图遍历，故不影响检索。
    """
    n = 0
    for src in source_uids or []:
        try:
            if graph.add_relationship(uid, src, EDGE_DERIVED):   # 必须检查返回值
                n += 1
        except Exception:  # noqa: BLE001
            pass
    return n


def _flatten_extraction(d: dict[str, Any], limit: int = 1200) -> str:
    """把 L1/L2 的结构化抽取展平成可检索的自然语句。

    ❗ 不能直接存 json.dumps：原始 JSON 带大量键名与转义，既稀释了语义信号（伤检索），
    又把单条文本拉长 15 倍（实测：L1 仅 19 个候选却占 37s 重排）。
    """
    parts: list[str] = []

    def walk(v: Any, depth: int = 0) -> None:
        if len("; ".join(parts)) > limit or depth > 3:
            return
        if isinstance(v, str):
            s = v.strip()
            if len(s) > 2:
                parts.append(s)
        elif isinstance(v, (int, float)):
            parts.append(str(v))
        elif isinstance(v, list):
            for x in v[:12]:
                walk(x, depth + 1)
        elif isinstance(v, dict):
            for k, x in v.items():
                if str(k).startswith("_"):
                    continue
                walk(x, depth + 1)

    walk(d)
    return "; ".join(parts)[:limit]


def load_l1_l2(graph: Any, sample_id: str, l1: list[dict[str, Any]],
               l2: dict[str, Any] | None, sparse: bool) -> dict[str, int]:
    """L1（逐 session）与 L2（逐 conv）落入 hierarchical 塔，并连溯源边。"""
    units = edges = 0
    for i, d in enumerate(l1):
        sid = str(d.get("session_id", i))
        uid = f"{sample_id}_L1_{sid}"
        body = _flatten_extraction(d)
        if _add_abstract(graph, uid, body, "L1_Summary", sparse, SPACE_L1,
                         {"session_id": sid, "sample_id": sample_id}):
            units += 1
            edges += _link_sources(graph, uid, d.get("_source_unit_uids") or [])
    if l2:
        uid = f"{sample_id}_L2"
        body = _flatten_extraction(l2, limit=2000)
        if _add_abstract(graph, uid, body, "L2_Insight", sparse, SPACE_L2,
                         {"sample_id": sample_id}):
            units += 1
            for sid in l2.get("_source_session_ids") or []:
                try:
                    graph.add_relationship(uid, f"{sample_id}_L1_{sid}", EDGE_DERIVED)
                    edges += 1
                except Exception:  # noqa: BLE001
                    pass
    return {"units": units, "edges": edges}


def load_episodic(graph: Any, sample_id: str, facts: list[dict[str, Any]],
                  sparse: bool) -> dict[str, int]:
    """情景事实落入 episodic 塔（独立图），保留溯源边。"""
    units = edges = 0
    for i, f in enumerate(facts):
        text = str(f.get("content") or f.get("canonical_content") or "").strip()
        if not text:
            continue
        uid = f"{sample_id}_EP_{i}"
        t = f.get("time", {})
        when = t.get("absolute_start", "") if isinstance(t, dict) else ""
        if _add_abstract(graph, uid, text, "Episodic_Fact", sparse, SPACE_EPISODIC,
                         {"sample_id": sample_id, "fact_type": f.get("fact_type", "EVENT"),
                          "session_id": f.get("session_id"), "timestamp": when,
                          # 跨图边建不了，溯源改存 metadata（论文 §3.1.2）
                          "source_unit_uids": list(f.get("_source_unit_uids") or [])[:64]}):
            units += 1
            edges += _link_sources(graph, uid, f.get("_source_unit_uids") or [])
    return {"units": units, "edges": edges}


def load_kg(graph: Any, sample_id: str, entities: list[dict[str, Any]],
            relations: list[dict[str, Any]], sparse: bool) -> dict[str, int]:
    """实体 + 关系落入 kg 塔（独立图）。关系边是 `0 EDGES` 的直接修复点。"""
    units = edges = 0
    uid_by_name: dict[str, str] = {}
    for i, e in enumerate(entities):
        name = str(e.get("name", "")).strip()
        if not name:
            continue
        uid = f"{sample_id}_ENT_{i}"
        desc = str(e.get("description", "")).strip()
        text = f"{name} ({e.get('type', 'UNKNOWN')}): {desc}" if desc else \
               f"{name} ({e.get('type', 'UNKNOWN')})"
        if _add_abstract(graph, uid, text, "KG_Entity", sparse, SPACE_KG,
                         {"sample_id": sample_id, "entity_name": name,
                          "entity_type": e.get("type", "UNKNOWN"),
                          "source_unit_uids": list(e.get("_source_unit_uids") or [])[:64]}):
            units += 1
            uid_by_name.setdefault(name.lower(), uid)
            edges += _link_sources(graph, uid, e.get("_source_unit_uids") or [])

    for r in relations:
        s = str(r.get("source") or r.get("subject") or r.get("head") or "").strip().lower()
        o = str(r.get("target") or r.get("object") or r.get("tail") or "").strip().lower()
        su, ou = uid_by_name.get(s), uid_by_name.get(o)
        if not su or not ou or su == ou:
            continue
        rel = str(r.get("relation") or r.get("type") or EDGE_RELATION)
        try:
            if graph.add_relationship(su, ou, rel):   # 实体间关系同图，应当生效
                edges += 1
        except Exception:  # noqa: BLE001
            pass
    return {"units": units, "edges": edges}

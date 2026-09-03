"""kg 塔：逐 session 实体抽取 → 实体去重 → 关系生成（会话内 + 跨会话）。

对齐 dataset_maker/locomo_graph_maker/：
  step1_locomo_entity_extractor.py    实体抽取(:391) + 聚类去重(:618)
  step2_locomo_relation_generator.py  会话内关系(:398) + 跨会话关系(:546)

官方参数：similarity_threshold=0.85（:101）、簇 ≤12 单次调用 / >12 按 12 分批（:497,:667）。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .hierarchical import L0Message
from .llm import TowerLLM
from .prompts import (
    CROSS_SESSION_RELATION_PROMPT,
    ENTITY_DEDUPLICATION_PROMPT,
    ENTITY_EXTRACTION_PROMPT,
    ENTITY_TYPES_DESCRIPTION,
    RELATION_EXTRACTION_PROMPT,
)

ENTITY_MAX_TOKENS = 4000
RELATION_MAX_TOKENS = 4000
SIMILARITY_THRESHOLD = 0.85
CLUSTER_SINGLE_CALL_MAX = 12
BATCH_SIZE = 12
CLUSTER_EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def _conversation_text(group: list[L0Message]) -> str:
    return "\n".join(f"{m.speaker}: {m.text}" for m in group)


def build_entities(msgs: list[L0Message], llm: TowerLLM,
                   max_workers: int = 10) -> list[dict[str, Any]]:
    """逐 session 抽实体（step1:386-393）。"""
    by_session: dict[str, list[L0Message]] = {}
    for m in msgs:
        by_session.setdefault(m.session_id, []).append(m)

    def run(sid: str, group: list[L0Message]) -> list[dict[str, Any]]:
        prompt = ENTITY_EXTRACTION_PROMPT.format(
            session_id=sid,
            session_time=group[0].session_date if group else "unknown",
            speakers=", ".join(sorted({m.speaker for m in group})),
            conversation_text=_conversation_text(group),
            entity_types_description=ENTITY_TYPES_DESCRIPTION,
        )
        got = llm.complete_json(prompt, max_tokens=ENTITY_MAX_TOKENS, context_id=f"ENT:{sid}")
        ents = (got or {}).get("entities") or []
        out = []
        for e in ents if isinstance(ents, list) else []:
            if not isinstance(e, dict) or not e.get("name"):
                continue
            e["session_id"] = sid
            e["_source_unit_uids"] = [m.uid for m in group]
            e.setdefault("confidence", 1.0)
            out.append(e)
        return out

    ents: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for fut in as_completed([ex.submit(run, s, g) for s, g in by_session.items()]):
            ents.extend(fut.result())
    return ents


def _cluster_by_similarity(names: list[str], threshold: float) -> dict[int, list[int]]:
    """MiniLM 余弦相似度层次聚合（官方以 similarity_threshold=0.85 归并同名实体）。"""
    if len(names) < 2:
        return {i: [i] for i in range(len(names))}
    import numpy as np
    from sentence_transformers import SentenceTransformer
    from sklearn.cluster import AgglomerativeClustering

    emb = SentenceTransformer(CLUSTER_EMBED_MODEL).encode(
        names, normalize_embeddings=True, show_progress_bar=False)
    labels = AgglomerativeClustering(
        n_clusters=None, distance_threshold=1.0 - threshold,
        metric="cosine", linkage="average").fit_predict(np.asarray(emb))
    clusters: dict[int, list[int]] = {}
    for i, lab in enumerate(labels):
        clusters.setdefault(int(lab), []).append(i)
    return clusters


def _entity_candidates_text(ents: list[dict[str, Any]]) -> str:
    """候选清单格式。

    > [!warning] 已知偏离（导致 KG 塔零关系边，详见 docs §12）
    > 官方 step2:382 的格式是：
    >     `- ID: {entity_id} | Name: {name} | Type: {entity_type}`
    >     `  Context: ... / Temporal Info: ... / Spatial Info: ... / Aliases: ...`
    > 本函数漏了 **entity_id** 与上下文字段。而
    > `RELATION_EXTRACTION_PROMPT` 明确要求 head_entity/tail_entity 填
    > “EXACT Entity ID from the list above”并且禁止用实体名——
    > 清单里没给 ID，LLM 就无法产出可解析的关系。
    > 修复需同时改本函数与 `load.py:load_kg` 的键名与映射基准。
    > 因官方主路径 `_cfg_full()` 的 `topk_graph=0` / `use_entity_relation=False`
    > 从不做关系遍历，此缺陷**不影响分数**，但不得声称已构建知识图谱。
    """
    s = ""
    for i, e in enumerate(ents, 1):
        s += f"{i}. Name: {e.get('name', '')}\n"
        s += f"  Type: {e.get('type', 'UNKNOWN')}\n"
        s += f"  Session: {e.get('session_id', '')}\n"
        s += f"  Confidence: {e.get('confidence', 1.0)}\n\n"
    return s


def dedup_entities(ents: list[dict[str, Any]], llm: TowerLLM,
                   max_workers: int = 10) -> list[dict[str, Any]]:
    """相似度聚类 + 逐簇 LLM 归并（step1:483-500 分流，:667 分批）。"""
    if not ents:
        return []
    clusters = _cluster_by_similarity([str(e.get("name", "")) for e in ents], SIMILARITY_THRESHOLD)

    jobs: list[tuple[str, list[dict[str, Any]]]] = []
    passthrough: list[dict[str, Any]] = []
    for cid, idxs in clusters.items():
        group = [ents[i] for i in idxs]
        if len(group) <= 1:
            passthrough.extend(group)
        elif len(group) <= CLUSTER_SINGLE_CALL_MAX:
            jobs.append((str(cid), group))
        else:
            for b in range(0, len(group), BATCH_SIZE):
                jobs.append((f"{cid}_batch_{b // BATCH_SIZE}", group[b:b + BATCH_SIZE]))

    def run(cid: str, group: list[dict[str, Any]]) -> list[dict[str, Any]]:
        prompt = ENTITY_DEDUPLICATION_PROMPT.format(
            cluster_size=len(group), cluster_id=cid,
            entity_candidates=_entity_candidates_text(group))
        got = llm.complete_json(prompt, max_tokens=ENTITY_MAX_TOKENS, context_id=f"EDEDUP:{cid}")
        merged = (got or {}).get("merged_entities") or (got or {}).get("entities")
        if not isinstance(merged, list) or not merged:
            return group
        sessions = sorted({str(e.get("session_id")) for e in group})
        uids = sorted({u for e in group for u in (e.get("_source_unit_uids") or [])})
        out = []
        for me in merged:
            if not isinstance(me, dict) or not me.get("name"):
                continue
            me["_merged_from"] = len(group)
            me["_source_session_ids"] = sessions
            me["_source_unit_uids"] = uids
            out.append(me)
        return out or group

    result = list(passthrough)
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for fut in as_completed([ex.submit(run, c, g) for c, g in jobs]):
            result.extend(fut.result())
    return result


def build_relations(msgs: list[L0Message], entities: list[dict[str, Any]],
                    llm: TowerLLM, max_workers: int = 10) -> list[dict[str, Any]]:
    """会话内关系抽取（step2:385-398）。仅对实体数 ≥2 的 session 调用。"""
    by_session: dict[str, list[L0Message]] = {}
    for m in msgs:
        by_session.setdefault(m.session_id, []).append(m)
    ents_by_session: dict[str, list[dict[str, Any]]] = {}
    for e in entities:
        for sid in (e.get("_source_session_ids") or [e.get("session_id")]):
            if sid:
                ents_by_session.setdefault(str(sid), []).append(e)

    def run(sid: str, group: list[L0Message]) -> list[dict[str, Any]]:
        ents = ents_by_session.get(sid, [])
        if len(ents) < 2:
            return []
        prompt = RELATION_EXTRACTION_PROMPT.format(
            session_id=sid,
            session_time=group[0].session_date if group else "unknown",
            conversation_text=_conversation_text(group),
            entities_list=_entity_candidates_text(ents),
        )
        got = llm.complete_json(prompt, max_tokens=RELATION_MAX_TOKENS, context_id=f"REL:{sid}")
        rels = (got or {}).get("relations") or []
        out = []
        for r in rels if isinstance(rels, list) else []:
            if not isinstance(r, dict):
                continue
            r["session_id"] = sid
            out.append(r)
        return out

    rels: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for fut in as_completed([ex.submit(run, s, g) for s, g in by_session.items()]):
            rels.extend(fut.result())
    return rels


def build_cross_session_relations(entities: list[dict[str, Any]],
                                  llm: TowerLLM) -> list[dict[str, Any]]:
    """跨会话关系（step2:593-606）：按实体名分组，仅处理跨 >1 个 session 的组。"""
    groups: dict[str, list[dict[str, Any]]] = {}
    for e in entities:
        groups.setdefault(str(e.get("name", "")).strip().lower(), []).append(e)
    targets = {n: g for n, g in groups.items()
               if n and len({s for e in g for s in (e.get("_source_session_ids")
                                                   or [e.get("session_id")]) if s}) > 1}
    if not targets:
        return []

    cross_txt = "\n".join(
        f"- {n}: 出现于 {sorted({str(s) for e in g for s in (e.get('_source_session_ids') or [e.get('session_id')]) if s})}"
        for n, g in list(targets.items())[:200])
    ctx = "\n".join(f"{n}: {str(g[0].get('description', ''))[:300]}" for n, g in list(targets.items())[:200])

    got = llm.complete_json(
        CROSS_SESSION_RELATION_PROMPT.format(cross_session_entities=cross_txt,
                                             session_contexts=ctx),
        max_tokens=RELATION_MAX_TOKENS, context_id="XREL")
    rels = (got or {}).get("relations") or []
    out = []
    for r in rels if isinstance(rels, list) else []:
        if isinstance(r, dict):
            r["cross_session"] = True
            out.append(r)
    return out

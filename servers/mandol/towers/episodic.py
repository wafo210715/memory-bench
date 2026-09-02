"""episodic 塔：逐 session 事实抽取 → DBSCAN 聚类 → 逐簇 LLM 去重增强。

对齐 dataset_maker/locomo_episodic_memory/：
  step1_extract_episodic_facts.py   逐 session 抽取（:328 调用点）
  step2_deduplicate_and_enhance.py  聚类去重（:409 调用点）

官方默认参数（step2 config :45-70）全部保留：
  DBSCAN eps=0.25 / min_samples=2，聚类嵌入用 all-MiniLM-L6-v2（官方指定）
  llm_cluster_threshold=2   簇 size<2 不调 LLM
  large_cluster_threshold=15 / batch_size=12  大簇分批
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .hierarchical import L0Message
from .llm import TowerLLM
from .prompts import EPISODIC_EXTRACTION_PROMPT, LLM_DEDUP_PROMPT

FACT_MAX_TOKENS = 4000
DEDUP_MAX_TOKENS = 4000

DEFAULT_EPS = 0.25
DEFAULT_MIN_SAMPLES = 2
LLM_CLUSTER_THRESHOLD = 2
LARGE_CLUSTER_THRESHOLD = 15
BATCH_SIZE = 12
CLUSTER_EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def build_facts(msgs: list[L0Message], llm: TowerLLM,
                max_workers: int = 8) -> list[dict[str, Any]]:
    """逐 session 抽取情景事实（step1:321-333）。"""
    by_session: dict[str, list[L0Message]] = {}
    for m in msgs:
        by_session.setdefault(m.session_id, []).append(m)

    def run(sid: str, group: list[L0Message]) -> list[dict[str, Any]]:
        dialogue_text = "\n".join(f"[Turn {m.message_index + 1}] {m.speaker}: {m.text}"
                                  for m in group)
        if not dialogue_text.strip():
            return []
        speakers = sorted({m.speaker for m in group})
        prompt = EPISODIC_EXTRACTION_PROMPT.format(
            session_date=group[0].session_date if group else "unknown",
            speakers=" and ".join(speakers) if speakers else "Unknown",
            session_id=sid,
            dialogue_text=dialogue_text,
        )
        got = llm.complete_json(prompt, max_tokens=FACT_MAX_TOKENS, context_id=f"EP:{sid}")
        if not got:
            return []
        facts = got.get("facts") or got.get("episodic_facts") or []
        if not isinstance(facts, list):
            return []
        out = []
        for f in facts:
            if not isinstance(f, dict):
                continue
            f["session_id"] = sid
            f["session_date"] = group[0].session_date if group else "unknown"
            f["_source_unit_uids"] = [m.uid for m in group]
            out.append(f)
        return out

    facts: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [ex.submit(run, sid, g) for sid, g in by_session.items()]
        for fut in as_completed(futs):
            facts.extend(fut.result())
    return facts


def _cluster(texts: list[str]) -> dict[int, list[int]]:
    """MiniLM 嵌入 + DBSCAN（cosine）。返回 {簇号: [下标]}，噪声点各自成簇。"""
    if len(texts) < 2:
        return {i: [i] for i in range(len(texts))}
    from sentence_transformers import SentenceTransformer
    from sklearn.cluster import DBSCAN

    model = SentenceTransformer(CLUSTER_EMBED_MODEL)
    emb = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    labels = DBSCAN(eps=DEFAULT_EPS, min_samples=DEFAULT_MIN_SAMPLES,
                    metric="cosine").fit_predict(emb)
    clusters: dict[int, list[int]] = {}
    noise = 10_000
    for i, lab in enumerate(labels):
        key = int(lab) if lab != -1 else (noise := noise + 1)
        clusters.setdefault(key, []).append(i)
    return clusters


def _fact_candidates_text(facts: list[dict[str, Any]]) -> str:
    """step2:397-404 的候选清单格式。"""
    s = ""
    for i, f in enumerate(facts, 1):
        t = f.get("time", {})
        time_str = t.get("absolute_start", "unknown") if isinstance(t, dict) else "unknown"
        s += f'{i}. Content: "{f.get("content", "")}"\n'
        s += f'   Type: {f.get("fact_type", "EVENT")}\n'
        s += f"   Time: {time_str}\n"
    return s


def dedup_facts(facts: list[dict[str, Any]], llm: TowerLLM,
                max_workers: int = 8) -> list[dict[str, Any]]:
    """聚类 + 逐簇 LLM 合并（step2:602-608 的分流逻辑）。"""
    if not facts:
        return []
    clusters = _cluster([str(f.get("content", "")) for f in facts])

    jobs: list[tuple[str, list[dict[str, Any]]]] = []
    passthrough: list[dict[str, Any]] = []
    for cid, idxs in clusters.items():
        group = [facts[i] for i in idxs]
        if len(group) < LLM_CLUSTER_THRESHOLD:      # 单点簇直接透传，不调 LLM
            passthrough.extend(group)
        elif len(group) >= LARGE_CLUSTER_THRESHOLD:  # 大簇按 12 分批
            for b in range(0, len(group), BATCH_SIZE):
                jobs.append((f"{cid}_batch_{b // BATCH_SIZE}", group[b:b + BATCH_SIZE]))
        else:
            jobs.append((str(cid), group))

    def run(cid: str, group: list[dict[str, Any]]) -> list[dict[str, Any]]:
        prompt = LLM_DEDUP_PROMPT.format(cluster_size=len(group), cluster_id=cid,
                                         fact_candidates=_fact_candidates_text(group))
        got = llm.complete_json(prompt, max_tokens=DEDUP_MAX_TOKENS, context_id=f"DEDUP:{cid}")
        merged = (got or {}).get("merged_facts")
        if not isinstance(merged, list) or not merged:
            return group          # 合并失败则保留原始，绝不丢事实
        src_sessions = sorted({str(f.get("session_id")) for f in group})
        src_uids = sorted({u for f in group for u in (f.get("_source_unit_uids") or [])})
        out = []
        for mf in merged:
            if not isinstance(mf, dict):
                continue
            mf.setdefault("content", mf.get("canonical_content", ""))
            mf["_merged_from"] = len(group)
            mf["_source_session_ids"] = src_sessions
            mf["_source_unit_uids"] = src_uids
            out.append(mf)
        return out or group

    result = list(passthrough)
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [ex.submit(run, cid, g) for cid, g in jobs]
        for fut in as_completed(futs):
            result.extend(fut.result())
    return result

# amem：A档系统（arXiv:2502.12110，Zettelkasten 式自演化记忆网络，官方 repo agiresearch/A-mem）
# 机制：add_note 时 LLM 生成 keywords/tags/context 并建立 note 间链接（记忆演化）；检索走混合搜索 + 网络扩散
# LLM：llm_controller 用 OpenAI SDK（api_key + OPENAI_BASE_URL env）→ 智谱 coding 端点；reasoning_effort 同款 monkeypatch 钉 low
# embedding：本地 all-MiniLM-L6-v2（A-MEM 原生设定，嵌入强度是系统属性——与 embedding-3 的差异在 spec 声明）
# scope 隔离：无原生 scope → per-scope AgenticMemorySystem 实例 + HOME 切换（chroma 目录写死 ~/.chromadb，
#   重定向 HOME 到 state/amem/homes/<scope_id>；SENTENCE_TRANSFORMERS_HOME 共享模型缓存避免重复下载）
# ⚠️ 独立 venv .venv-amem
# ⚠️ PyPI 的 a-mem 包是第三方个人封装（DiaaAj/a-mem-mcp），非官方——别装错

import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# 日志全部改道 stderr，防污染 stdio JSON-RPC
import logging

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

from fastmcp import FastMCP

from servers.common.base import BaseState
from servers.common.envelope import make_envelope
from servers.common.stats import StatsTracker

mcp = FastMCP("amem")

_state = BaseState("amem")
_stats = StatsTracker()
_SIDECAR = _state.state_dir / "scopes.json"
HOMES = _state.state_dir / "homes"            # per-scope HOME（chroma 落 ~/.chromadb）
ST_CACHE = _state.state_dir / "st-cache"      # sentence-transformers 共享缓存
_SYSTEMS: dict[str, object] = {}


def _scopes() -> dict:
    if _SIDECAR.exists():
        return json.loads(_SIDECAR.read_text())
    return {"scope_ids": [], "sessions": [], "n_notes": 0}


def _save_scopes(scope_id: str | None, session_id: str | None, n: int) -> None:
    s = _scopes()
    if scope_id and scope_id not in s["scope_ids"]:
        s["scope_ids"].append(scope_id)
    if session_id and session_id not in s["sessions"]:
        s["sessions"].append(session_id)
    s["n_notes"] = s.get("n_notes", 0) + n
    _SIDECAR.parent.mkdir(parents=True, exist_ok=True)
    _SIDECAR.write_text(json.dumps(s, ensure_ascii=False))


def _strip_fence(s: str) -> str:
    """剥掉 ```json fence（仅用于观测，不影响原生臂行为）。"""
    s = (s or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s


def _wrap_llm_observability(system) -> None:
    """纯观测，不改行为：统计 evolution 的 LLM 返回有多少能被上游解析。

    上游 process_memory 用裸 `json.loads(response)` 并把异常吃掉（return False, note），
    从外部区分不了“LLM 说不需要演化”和“解析失败静默丢弃”——而这两者对评测结论
    的含义完全相反。这里在 get_completion 旁路复刻一次上游的裸解析来计数，
    **原样返回字符串**，不改变任何原生行为。

    n_evo_fence_recoverable 回答“失败里有多少只是 markdown fence 问题”——它与机制
    本身无关，属于输出格式噪声，需要单独计量才不会把两类原因混谈。
    """
    system.n_llm_calls = 0
    system.n_evo_ok = 0
    system.n_evo_fail = 0
    system.n_evo_fence_recoverable = 0
    try:
        orig = system.llm_controller.llm.get_completion

        def observed(prompt, response_format=None, temperature=0.7):
            raw = orig(prompt, response_format, temperature)
            system.n_llm_calls += 1
            try:
                json.loads(raw)                     # 与上游 process_memory 完全同口径
                system.n_evo_ok += 1
            except Exception:
                system.n_evo_fail += 1
                try:
                    json.loads(_strip_fence(raw))   # 仅 fence 导致？
                    system.n_evo_fence_recoverable += 1
                except Exception:
                    pass
            return raw                              # 原样返回，行为零变化

        system.llm_controller.llm.get_completion = observed
    except Exception as e:
        print(f"[amem-observe] 注入失败（仅影响计数，不影响结果）: {e}", file=sys.stderr)


def _pin_reasoning(system) -> None:
    """A-MEM 的 llm_controller 直接用 OpenAI SDK——同款 extra_body 手法钉 reasoning_effort；
    并强制 temperature=0（官方默认 0.7，违约 spec §7）。

    ⚠️ P7（2026-08-30）：原实现写的是 `system.llm.client`，但 AgenticMemorySystem 上
    没有 .llm 属性（真实路径是 .llm_controller.llm）——AttributeError 被下面的 except
    吃掉，只往 stderr 打一行，而 stdio 模式下那行不进评测日志。

    后果链：pin 从未生效 → temperature 一直是上游默认 0.7、reasoning_effort 从未钉住
    → 思考与正文共用额度，吃光上游写死的 max_tokens=1000 → content 返回空
    → json.loads 报 'Expecting value: line 1 column 1' → evolution **100% 静默失败**
    （实测 7/7）。修正路径后失败率降到 29%，且剩下的失败全是 markdown fence。

    同时新增 pin_ok 上报——不能再依赖 stderr 里一行没人看的提示。
    """
    mode = os.environ.get("MEMBENCH_THINKING", "low")
    try:
        client = system.llm_controller.llm.client
        create = client.chat.completions.create

        def create_pinned(**kwargs):
            kwargs["temperature"] = 0
            kwargs.setdefault("extra_body", {})["reasoning_effort"] = "low" if mode == "low" else "high"
            return create(**kwargs)

        client.chat.completions.create = create_pinned
        system.pin_ok = True
    except Exception as e:
        system.pin_ok = False
        print(f"[amem-pin] 注入失败（公平性受损，未静默）: {e}", file=sys.stderr)


def _get_system(scope_id: str):
    sysm = _SYSTEMS.get(scope_id)
    if sysm is None:
        from agentic_memory.memory_system import AgenticMemorySystem
        from agentic_memory.retrievers import ChromaRetriever

        home = HOMES / scope_id
        home.mkdir(parents=True, exist_ok=True)
        old_home = os.environ.get("HOME")
        os.environ["HOME"] = str(home)
        os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(ST_CACHE))
        try:
            sysm = AgenticMemorySystem(
                model_name="all-MiniLM-L6-v2",
                llm_backend="openai",
                llm_model=os.environ.get("MEMBENCH_LLM_MODEL", "glm-5.3"),
            )
        finally:
            if old_home is not None:
                os.environ["HOME"] = old_home
        # P2 修复（2026-08-19 核查）：A-MEM 用内存版 chromadb.Client()（同进程共享单例），
        # 多实例共用写死的 collection "memories" 会互相损坏。替换为 per-scope 唯一 collection 名。
        sysm.retriever = ChromaRetriever(
            collection_name=f"mem_{scope_id}", model_name="all-MiniLM-L6-v2"
        )
        _wrap_llm_observability(sysm)
        _pin_reasoning(sysm)
        _SYSTEMS[scope_id] = sysm
    return sysm


def _drop_systems() -> None:
    """清实例 + 清 chroma 进程级缓存（同目录重建时防读到旧句柄）。"""
    global _SYSTEMS
    for sysm in _SYSTEMS.values():
        try:
            client = getattr(sysm.retriever, "client", None)
            if client is not None and hasattr(type(client), "clear_system_cache"):
                type(client).clear_system_cache()
        except Exception:
            pass
    _SYSTEMS = {}


@mcp.tool
def add_conversation(session_id: str, turns: list[dict], scope: dict, metadata: dict | None = None) -> dict:
    """逐 turn 一条 note；A-MEM 内部 LLM 演化（keywords/tags/links）。时间前缀由 harness 层统一加。"""
    t0 = time.perf_counter()
    sid = scope.get("id") or "default"
    sysm = _get_system(sid)
    n = 0
    for i, t in enumerate(turns):
        sysm.add_note(f"{t.get('role', 'user')}: {t.get('content', '')}", time=t.get("timestamp"))
        n += 1
    _save_scopes(sid, session_id, n)
    _stats.n_sessions = len(_scopes()["sessions"])
    _stats.add_tokens("internal_llm", None)  # A-MEM 未暴露内部 LLM 计量
    return {"accepted_turns": n, "native_notes": f"A-MEM 记忆演化完成，耗时 {int((time.perf_counter() - t0) * 1000)}ms（每 note 含 LLM 演化调用）"}


@mcp.tool
def retrieve(query: str, query_mode: str = "fixed", top_k: int = 5, filter: dict | None = None) -> dict:
    """agentic 检索（混合搜索 + 网络扩散）。"""
    t0 = time.perf_counter()
    notes = []
    scope_ids = _scopes()["scope_ids"]
    if filter and filter.get("scope_id"):
        sid = filter["scope_id"]
    else:
        sid = scope_ids[0] if scope_ids else "default"
    sysm = _get_system(sid)
    results = sysm.search_agentic(query, k=top_k)
    for item in results:
        content = item.get("content", "")
        ts = item.get("timestamp") or item.get("last_accessed")
        results_note = make_envelope(
            memory_id=item.get("id", ""),
            text=content,
            session_id=None,
            turn_range=None,
            timestamp=str(ts) if ts else None,
            score=None,
            raw_format="amem_note",
        )
        notes.append(results_note)
    parts = []
    if len(scope_ids) > 1 and not (filter and filter.get("scope_id")):
        parts.append("MULTI_SCOPE: 未指定 filter.scope_id，仅检索首个 scope")
    if filter and any(k for k in filter if k != "scope_id"):
        parts.append("FILTER_IGNORED: 仅支持 scope_id")
    return {
        "results": notes,
        "query_used": query,
        "query_mode": query_mode,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
        "native_notes": "; ".join(parts),
    }


@mcp.tool
def reset() -> dict:
    """清全部 scope 实例 + 状态目录（含 homes/，st-cache 保留避免重下载模型）。幂等。"""
    _drop_systems()
    import shutil

    if HOMES.exists():
        shutil.rmtree(HOMES, ignore_errors=True)
    HOMES.mkdir(parents=True, exist_ok=True)
    _SIDECAR.unlink(missing_ok=True)
    _stats.mark_reset()
    _stats.n_sessions = 0
    return {"ok": True, "cleared": {"system": "amem", "note": "homes 清空，st-cache 保留"}}


@mcp.tool
def stats() -> dict:
    d = _stats.to_dict(n_memories=_scopes().get("n_notes", 0))
    # pin 是否真的注入成功——P7 的教训：静默失败必须可观测
    d["pin_ok"] = all(getattr(s, "pin_ok", False) for s in _SYSTEMS.values()) if _SYSTEMS else None
    # evolution 到底成功了多少次（上游把失败吞在 except 里，外部本来无从得知）
    for key in ("n_llm_calls", "n_evo_ok", "n_evo_fail", "n_evo_fence_recoverable"):
        d[key] = sum(getattr(s, key, 0) for s in _SYSTEMS.values())
    return d


def _dump_notes(scope_id: str) -> list[dict]:
    """从实例内存 dict 序列化 notes（A-MEM 的 self.memories 不落盘，快照必须带走）。"""
    sysm = _SYSTEMS.get(scope_id)
    if sysm is None:
        return []
    out = []
    for note in getattr(sysm, "memories", {}).values():
        d = dict(vars(note))
        for k, v in list(d.items()):
            if not isinstance(v, (str, int, float, bool, list, dict, type(None))):
                d[k] = str(v)
        out.append(d)
    return out


def _inject_notes(scope_id: str, notes: list[dict]) -> None:
    """restore 后重建实例并注入：A-MEM 的 chroma 是内存版（不落盘），
    快照恢复必须同步重建 chroma 索引（本地嵌入重算，毫秒级）。"""
    if not notes:
        return
    sysm = _get_system(scope_id)
    from agentic_memory.memory_system import MemoryNote

    for d in notes:
        nid = str(d.get("id") or d.get("_id"))
        try:
            note = MemoryNote(content=d.get("content", ""), **{k: v for k, v in d.items() if k not in ("content", "id")})
            note.id = nid
        except TypeError:
            note = MemoryNote(content=d.get("content", ""))
            note.id = nid
        sysm.memories[nid] = note
        # 重建 chroma 索引（照抄 add_note 的 metadata 构造，不调 LLM）
        meta = {
            "id": note.id,
            "content": note.content,
            "keywords": getattr(note, "keywords", None),
            "links": getattr(note, "links", None),
            "retrieval_count": getattr(note, "retrieval_count", 0),
            "timestamp": str(getattr(note, "timestamp", "") or ""),
            "last_accessed": str(getattr(note, "last_accessed", "") or ""),
            "context": getattr(note, "context", None),
            "evolution_history": getattr(note, "evolution_history", None),
            "category": getattr(note, "category", None),
            "tags": getattr(note, "tags", None),
        }
        meta = {k: (json.dumps(v, ensure_ascii=False, default=str) if isinstance(v, (dict, list)) else (str(v) if v is not None else "")) for k, v in meta.items()}
        sysm.retriever.add_document(note.content, meta, note.id)


@mcp.tool
def snapshot(tag: str) -> dict:
    """实例内存 notes + homes/ 目录 + sidecar；排除 st-cache（模型缓存不入快照）。"""
    import shutil

    dst = _state.snap_root / tag
    if dst.exists():
        shutil.rmtree(dst)
    _state.snap_root.mkdir(parents=True, exist_ok=True)
    dst.mkdir(parents=True, exist_ok=True)
    notes_dump = {sid: _dump_notes(sid) for sid in _scopes()["scope_ids"]}
    # P7 修复：防静默空快照覆盖——实例不在内存（server 重启后未 add）时拒绝快照
    expected = _scopes().get("n_notes", 0)
    actual = sum(len(v) for v in notes_dump.values())
    if expected > 0 and actual != expected:
        return {"ok": False, "error": "SNAPSHOT_STATE_MISMATCH",
                "hint": f"内存 notes({actual}) ≠ sidecar 计数({expected})——实例已丢失，快照会写空覆盖旧 tag", "tag": tag}
    (dst / "notes.json").write_text(json.dumps(notes_dump, ensure_ascii=False, default=str))
    _drop_systems()
    if HOMES.exists():
        shutil.copytree(HOMES, dst / "homes")
    if _SIDECAR.exists():
        shutil.copy2(_SIDECAR, dst / "scopes.json")
    _stats.snapshots = _state.tags()
    return {"ok": True, "tag": tag}


@mcp.tool
def restore(tag: str) -> dict:
    import shutil

    _drop_systems()
    src = _state.snap_root / tag
    if not (src / "homes").exists():
        return {"ok": False, "error": "SNAPSHOT_NOT_FOUND", "tag": tag}
    if HOMES.exists():
        shutil.rmtree(HOMES)
    shutil.copytree(src / "homes", HOMES)
    if (src / "scopes.json").exists():
        shutil.copy2(src / "scopes.json", _SIDECAR)
    else:
        _SIDECAR.unlink(missing_ok=True)
    notes_dump = json.loads((src / "notes.json").read_text()) if (src / "notes.json").exists() else {}
    for sid, notes in notes_dump.items():
        _inject_notes(sid, notes)
        # 诊断：restore 后实例内 chroma 与内存 dict 的实际状态
        sysm = _SYSTEMS.get(sid)
        if sysm is not None:
            try:
                n_chroma = sysm.retriever.collection.count()
            except Exception:
                n_chroma = -1
            print(f"[amem-restore] scope={sid} notes注入={len(notes)} chroma={n_chroma} 内存dict={len(getattr(sysm, 'memories', {}))}", file=sys.stderr)
    _stats.snapshots = _state.tags()
    _stats.n_sessions = len(_scopes()["sessions"])
    return {"ok": True, "tag": tag}


if __name__ == "__main__":
    mcp.run()  # stdio

# graphiti：A档第二个真实系统（interface-spec 契约）
# 依赖：Neo4j Docker 容器 membench-neo4j（数据卷挂在本 repo .state/graphiti/neo4j-data）
# 快照机制：docker stop → 目录拷贝 → docker start（neo4j-admin dump 需要 DB offline，直接停容器拷卷最稳）
# env_required: MEMBENCH_LLM_*（实体抽取 LLM）；可选 MEMBENCH_NEO4J_URI/USER/PASSWORD/CONTAINER

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("MEM0_TELEMETRY", "False")  # noqa: 无关 mem0，占位保持一致的环境卫生

from fastmcp import FastMCP

from servers.common.base import BaseState
from servers.common.envelope import make_envelope
from servers.common.stats import StatsTracker

mcp = FastMCP("graphiti")

_state = BaseState("graphiti")
_stats = StatsTracker()
DATA_DIR = _state.state_dir / "neo4j-data"          # docker 卷挂载点，reset 不许动它
SIDECAR = _state.state_dir / "scopes.json"          # scope/session 记账
_G = None                                           # 惰性 Graphiti 单例

NEO4J_URI = os.environ.get("MEMBENCH_NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("MEMBENCH_NEO4J_USER", "neo4j")
NEO4J_PASS = os.environ.get("MEMBENCH_NEO4J_PASSWORD", "membenchpass")
NEO4J_CONTAINER = os.environ.get("MEMBENCH_NEO4J_CONTAINER", "membench-neo4j")


def _die_if_env_missing() -> None:
    missing = [k for k in ("MEMBENCH_LLM_API_KEY", "MEMBENCH_LLM_BASE_URL", "MEMBENCH_LLM_MODEL") if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"缺少环境变量 {missing}——MCP stdio 子进程不继承父进程环境，须显式传入（interface-spec §7）")


async def _get_graphiti():
    global _G
    if _G is None:
        _die_if_env_missing()
        from graphiti_core import Graphiti
        from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
        from graphiti_core.llm_client.config import LLMConfig
        from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient

        thinking = os.environ.get("MEMBENCH_THINKING", "low")
        llm = OpenAIGenericClient(
            config=LLMConfig(
                api_key=os.environ["MEMBENCH_LLM_API_KEY"],
                base_url=os.environ["MEMBENCH_LLM_BASE_URL"],
                model=os.environ["MEMBENCH_LLM_MODEL"],
                temperature=0,
            ),
            structured_output_mode="json_object",  # 智谱无 Responses API/json_schema，用 json_object
        )
        # GenericClient 不透传 reasoning——在 AsyncOpenAI 客户端上钉 reasoning_effort（与 mem0 同款手法）
        _create = llm.client.chat.completions.create

        async def _create_pinned(**kwargs):
            kwargs.setdefault("extra_body", {})["reasoning_effort"] = "low" if thinking == "low" else "high"
            return await _create(**kwargs)

        llm.client.chat.completions.create = _create_pinned
        embedder = OpenAIEmbedder(
            config=OpenAIEmbedderConfig(
                embedding_model=os.environ.get("MEMBENCH_EMBED_MODEL", "embedding-3"),
                embedding_dim=int(os.environ.get("MEMBENCH_EMBED_DIM", "2048")),
                api_key=os.environ.get("MEMBENCH_EMBED_API_KEY") or os.environ["MEMBENCH_LLM_API_KEY"],
                base_url=os.environ.get("MEMBENCH_EMBED_BASE_URL") or os.environ["MEMBENCH_LLM_BASE_URL"],
            )
        )
        from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient

        # reranker 也走同一端点（Graphiti.__init__ 默认无参构造会去找 OPENAI_API_KEY，本地未设——坑）
        reranker = OpenAIRerankerClient(config=LLMConfig(
            api_key=os.environ["MEMBENCH_LLM_API_KEY"],
            base_url=os.environ["MEMBENCH_LLM_BASE_URL"],
            model=os.environ.get("MEMBENCH_RERANKER_MODEL", os.environ["MEMBENCH_LLM_MODEL"]),
        ))
        _G = Graphiti(NEO4J_URI, NEO4J_USER, NEO4J_PASS, llm_client=llm, embedder=embedder, cross_encoder=reranker)
        await _G.build_indices_and_constraints()  # 幂等
    return _G


async def _drop_graphiti() -> None:
    global _G
    if _G is not None:
        try:
            await _G.close()
        except Exception:
            pass
    _G = None


def _scopes() -> dict:
    if SIDECAR.exists():
        return json.loads(SIDECAR.read_text())
    return {"scope_ids": [], "sessions": []}


def _save_scope(scope_id: str | None, session_id: str | None) -> None:
    s = _scopes()
    if scope_id and scope_id not in s["scope_ids"]:
        s["scope_ids"].append(scope_id)
    if session_id and session_id not in s["sessions"]:
        s["sessions"].append(session_id)
    SIDECAR.write_text(json.dumps(s, ensure_ascii=False))


def _docker(*args: str) -> None:
    subprocess.run(["docker", *args], check=True, capture_output=True, timeout=180)


async def _wait_neo4j(timeout_s: int = 90) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            g = await _get_graphiti()
            await g.driver.execute_query("RETURN 1")
            return
        except Exception:
            await _drop_graphiti()
            await asyncio.sleep(3)
    raise RuntimeError("Neo4j 就绪超时——检查容器状态：docker logs membench-neo4j")


def _iso_or_now(ts: str | None) -> datetime:
    if ts:
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


@mcp.tool
async def add_conversation(session_id: str, turns: list[dict], scope: dict, metadata: dict | None = None) -> dict:
    """一个 session 一个 episode，body 为整段对话文本；group_id = scope.id（对话间隔离）。"""
    t0 = time.perf_counter()
    g = await _get_graphiti()
    body = "\n".join(f"{t.get('role', 'user')}: {t.get('content', '')}" for t in turns)
    ref_time = _iso_or_now(next((t.get("timestamp") for t in turns if t.get("timestamp")), None))
    await g.add_episode(
        name=session_id,
        episode_body=body,
        source_description="memory-bench ingest",
        reference_time=ref_time,
        group_id=scope.get("id"),
    )
    _save_scope(scope.get("id"), session_id)
    _stats.n_sessions = len(_scopes()["sessions"])
    _stats.add_tokens("ingest", None)  # graphiti token 计数不外露，诚实记 None
    _stats.add_tokens("internal_llm", None)
    return {
        "accepted_turns": len(turns),
        "native_notes": f"graphiti 抽取完成，耗时 {int((time.perf_counter() - t0) * 1000)}ms（实体抽取 LLM 调用未计量）",
    }


@mcp.tool
async def retrieve(query: str, query_mode: str = "fixed", top_k: int = 5, filter: dict | None = None) -> dict:
    """hybrid 检索，返回 fact 边；分数不外露（保 relevance 排序），score=None。"""
    t0 = time.perf_counter()
    g = await _get_graphiti()
    notes = []
    scope_ids = _scopes()["scope_ids"]
    if filter and filter.get("scope_id"):
        gid = filter["scope_id"]
    else:
        if len(scope_ids) > 1:
            notes.append("MULTI_SCOPE: 未指定 filter.scope_id，仅检索首个 scope")
        gid = scope_ids[0] if scope_ids else None
    if filter and any(k for k in filter if k != "scope_id"):
        notes.append("FILTER_IGNORED: 仅支持 scope_id")
    edges = await g.search(query, group_ids=[gid] if gid else None, num_results=top_k)
    results = [
        make_envelope(
            memory_id=e.uuid,
            text=e.fact,
            session_id=None,       # fact→episode 映射 v1 未做，见 spec 粒度声明
            turn_range=None,
            timestamp=getattr(e, "created_at", None),
            score=None,            # 排序即相关性，原生分数未外露
            raw_format="graphiti_fact",
        )
        for e in edges
    ]
    return {
        "results": results,
        "query_used": query,
        "query_mode": query_mode,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
        "native_notes": "; ".join(notes),
    }


@mcp.tool
async def reset() -> dict:
    """清图：cypher DETACH DELETE。⚠️ 不能动 neo4j-data 目录（docker 卷挂载中）。幂等。"""
    g = await _get_graphiti()
    await g.driver.execute_query("MATCH (n) DETACH DELETE n")
    SIDECAR.unlink(missing_ok=True)
    _stats.mark_reset()
    _stats.n_sessions = 0
    return {"ok": True, "cleared": {"system": "graphiti", "note": "cypher 全清，索引保留"}}


@mcp.tool
async def stats() -> dict:
    n_nodes = n_edges = 0
    try:
        g = await _get_graphiti()
        r1 = await g.driver.execute_query("MATCH (n) RETURN count(n) AS c")
        n_nodes = r1.records[0]["c"]
        r2 = await g.driver.execute_query("MATCH ()-[r]->() RETURN count(r) AS c")
        n_edges = r2.records[0]["c"]
    except Exception:
        pass
    return _stats.to_dict(n_memories=n_edges) | {"n_graph_nodes": n_nodes}


@mcp.tool
async def snapshot(tag: str) -> dict:
    """停容器 → 拷数据卷 → 起容器 → 等 bolt 就绪。约 15-30s。"""
    await _drop_graphiti()
    t0 = time.perf_counter()
    _docker("stop", NEO4J_CONTAINER)
    dst = _state.snap_root / tag
    if dst.exists():
        shutil.rmtree(dst)
    _state.snap_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(DATA_DIR, dst / "neo4j-data", ignore=shutil.ignore_patterns("neo4j-logs"))
    if SIDECAR.exists():
        shutil.copy2(SIDECAR, dst / "scopes.json")
    _docker("start", NEO4J_CONTAINER)
    await _wait_neo4j()
    _stats.snapshots = _state.tags()
    return {"ok": True, "tag": tag, "elapsed_ms": int((time.perf_counter() - t0) * 1000)}


@mcp.tool
async def restore(tag: str) -> dict:
    await _drop_graphiti()
    src = _state.snap_root / tag
    if not (src / "neo4j-data").exists():
        return {"ok": False, "error": "SNAPSHOT_NOT_FOUND", "tag": tag}
    t0 = time.perf_counter()
    _docker("stop", NEO4J_CONTAINER)
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)
    shutil.copytree(src / "neo4j-data", DATA_DIR)
    if (src / "scopes.json").exists():
        shutil.copy2(src / "scopes.json", SIDECAR)
    else:
        SIDECAR.unlink(missing_ok=True)
    _docker("start", NEO4J_CONTAINER)
    await _wait_neo4j()
    _stats.snapshots = _state.tags()
    _stats.n_sessions = len(_scopes()["sessions"])
    return {"ok": True, "tag": tag, "elapsed_ms": int((time.perf_counter() - t0) * 1000)}


if __name__ == "__main__":
    mcp.run()  # stdio

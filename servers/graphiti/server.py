# graphiti：A档第二个真实系统（interface-spec 契约）
# 依赖：Neo4j Docker 容器 membench-neo4j（数据卷挂在本 repo .state/graphiti/neo4j-data）
# 快照机制：docker stop → 目录拷贝 → docker start（neo4j-admin dump 需要 DB offline，直接停容器拷卷最稳）
# env_required: MEMBENCH_LLM_*（实体抽取 LLM）；可选 MEMBENCH_NEO4J_URI/USER/PASSWORD/CONTAINER
#
# ── 2026-08-29 论文对齐改造（Rasmussen et al. 2025, arXiv:2501.13956）────────────────────
# 改造前我们只接了 graphiti 的**降级面**：Graphiti.search()（官方 docstring 自陈是 "basic
# out-of-the-box search"），内部固定 EDGE_HYBRID_SEARCH_RRF，只有 edges、只有 bm25+cosine、
# envelope 只带入库墙钟 created_at。实测 9930 条 envelope 年份 100% = 2026，而图里 valid_at
# 的真实年份是 2022-2024——论文全部核心贡献（双时间轴）在 wrapper 边界被丢光。
#
# 现在改用 Graphiti.search_() + 显式 SearchConfig，逐条对齐论文：
#   §3   φ 返回 3-tuple (Es, Ns, Nc)：edges + entity nodes + community nodes
#   §3   χ 对 edge 返回 fact + tvalid/tinvalid；对 Ns 返回 name+summary；对 Nc 返回 summary
#   §3.1 三路检索 ϕcos + ϕbm25 + ϕbfs（bfs 此前完全没接）
#   §3.2 重排可选 rrf / mmr / cross_encoder
# 每个环节的**运行时实际生效值**和**每条通道的真实命中数**都写进 mcp_trace（见 trace.py）。

import asyncio
import json
import math
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("MEM0_TELEMETRY", "False")  # noqa: 无关 mem0，占位保持一致的环境卫生

from servers.graphiti import trace as gtrace

gtrace.harden_stdout()  # 必须早于任何可能 print/logging 的第三方 import（MCP stdio：stdout 只许走 JSON-RPC）

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


# ---------- 检索面配置（全部可用环境变量覆盖，且每次调用把**实际生效值**写进 trace） ----------

def _search_knobs(top_k: int) -> dict:
    """论文 §4：`retrieve the 20 most relevant edges (facts) and entity nodes`——所以 graphiti 内部
    候选/返回上限默认取 20，再由 wrapper 按契约 §7 的 top_k 裁到最终 envelope 数。
    这样 cross_encoder / rrf 是在 20 个候选上做重排（论文规模），而不是在 5 个上。"""
    return {
        "search_limit": max(top_k, int(os.environ.get("MEMBENCH_GRAPHITI_SEARCH_LIMIT", "20"))),
        "reranker": os.environ.get("MEMBENCH_GRAPHITI_RERANKER", "rrf"),      # rrf | mmr | cross_encoder
        "bfs_max_depth": int(os.environ.get("MEMBENCH_GRAPHITI_BFS_DEPTH", "3")),  # 上游 MAX_SEARCH_DEPTH=3
        "mix": os.environ.get("MEMBENCH_GRAPHITI_MIX", "3:1:1"),              # edges:nodes:communities 名额配比
        "triple": os.environ.get("MEMBENCH_GRAPHITI_TRIPLE", "1") == "1",     # φ 是否返回 3-tuple
        "sim_min_score": float(os.environ.get("MEMBENCH_GRAPHITI_SIM_MIN", "0.6")),  # 上游 DEFAULT_MIN_SCORE
    }


def _build_search_config(knobs: dict):
    """按 §3.1/§3.2 组 SearchConfig。刻意不用现成 recipe：recipe 里带 episode_config，而论文 §3 的
    φ: S → Es×Ns×Nc 是三元组、§3 的 context 模板也只有 FACTS/ENTITIES/COMMUNITIES，没有 EPISODES。"""
    from graphiti_core.search.search_config import (
        CommunityReranker,
        CommunitySearchConfig,
        CommunitySearchMethod,
        EdgeReranker,
        EdgeSearchConfig,
        EdgeSearchMethod,
        NodeReranker,
        NodeSearchConfig,
        NodeSearchMethod,
        SearchConfig,
    )

    r = knobs["reranker"]
    edge_rr = {"rrf": EdgeReranker.rrf, "mmr": EdgeReranker.mmr,
               "cross_encoder": EdgeReranker.cross_encoder,
               "episode_mentions": EdgeReranker.episode_mentions}.get(r, EdgeReranker.rrf)
    node_rr = {"rrf": NodeReranker.rrf, "mmr": NodeReranker.mmr,
               "cross_encoder": NodeReranker.cross_encoder,
               "episode_mentions": NodeReranker.episode_mentions}.get(r, NodeReranker.rrf)
    comm_rr = {"rrf": CommunityReranker.rrf, "mmr": CommunityReranker.mmr,
               "cross_encoder": CommunityReranker.cross_encoder}.get(r, CommunityReranker.rrf)

    edge_cfg = EdgeSearchConfig(  # §3.1 三路：ϕbm25 + ϕcos + ϕbfs
        search_methods=[EdgeSearchMethod.bm25, EdgeSearchMethod.cosine_similarity, EdgeSearchMethod.bfs],
        reranker=edge_rr, bfs_max_depth=knobs["bfs_max_depth"], sim_min_score=knobs["sim_min_score"],
    )
    node_cfg = comm_cfg = None
    if knobs["triple"]:
        node_cfg = NodeSearchConfig(
            search_methods=[NodeSearchMethod.bm25, NodeSearchMethod.cosine_similarity, NodeSearchMethod.bfs],
            reranker=node_rr, bfs_max_depth=knobs["bfs_max_depth"], sim_min_score=knobs["sim_min_score"],
        )
        comm_cfg = CommunitySearchConfig(  # §3.1：Nc 搜的是 community name（关键词/主题短语）
            search_methods=[CommunitySearchMethod.bm25, CommunitySearchMethod.cosine_similarity],
            reranker=comm_rr, sim_min_score=knobs["sim_min_score"],
        )
    return SearchConfig(edge_config=edge_cfg, node_config=node_cfg, community_config=comm_cfg,
                        episode_config=None, limit=knobs["search_limit"])


def _config_fingerprint(cfg, knobs: dict, gid) -> dict:
    """把**真正传给 graphiti 的**配置摊平成可 grep 的字典（不是代码里的默认值）。"""
    def methods(c):
        return [m.value for m in c.search_methods] if c else None

    def rr(c):
        return c.reranker.value if c else None

    return {
        "group_ids": gid, "search_limit": cfg.limit,
        "edge": {"methods": methods(cfg.edge_config), "reranker": rr(cfg.edge_config),
                 "bfs_max_depth": cfg.edge_config.bfs_max_depth if cfg.edge_config else None,
                 "sim_min_score": cfg.edge_config.sim_min_score if cfg.edge_config else None},
        "node": {"methods": methods(cfg.node_config), "reranker": rr(cfg.node_config)},
        "community": {"methods": methods(cfg.community_config), "reranker": rr(cfg.community_config)},
        "episode": {"methods": methods(cfg.episode_config)},
        "mix": knobs["mix"], "triple": knobs["triple"],
        "bfs_origin_node_uuids": None,  # 交给上游按 bm25/cosine 命中的 source node 自动播种（search.py:332）
    }


def _die_if_env_missing() -> None:
    missing = [k for k in ("MEMBENCH_LLM_API_KEY", "MEMBENCH_LLM_BASE_URL", "MEMBENCH_LLM_MODEL") if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"缺少环境变量 {missing}——MCP stdio 子进程不继承父进程环境，须显式传入（interface-spec §7）")


# ---------- cross-encoder：上游实现在智谱端点上不可用，这里做等价降级 ----------

def _make_reranker(llm_cfg):
    """上游 OpenAIRerankerClient 用 logit_bias + top_logprobs 取 True/False 的对数概率当连续分数。
    2026-08-29 实测：智谱 glm-5.3 **静默丢弃 logprobs**（返回 logprobs=None），上游会走到
    zip(passages, scores, strict=True) 抛 ValueError → 整条 retrieve 崩。
    这里保留上游**逐字相同的布尔分类 prompt**，改用文本判定给 1.0/0.0，并靠稳定排序保住候选原序。
    代价：分数退化为二值，判别力弱于论文用的 BGE-m3 cross-encoder（见报告 §3）。"""
    from graphiti_core.cross_encoder.client import CrossEncoderClient
    from graphiti_core.prompts import Message

    from openai import AsyncOpenAI

    class TextClassifierReranker(CrossEncoderClient):
        def __init__(self, cfg) -> None:  # noqa: ANN001
            self.config = cfg
            self.client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
            # 上游 semaphore_gather 默认 20 并发，edge/node/community 三路同时重排 → 实测 40 并发
            # 直接撑爆智谱限流（429 code 1302，2026-08-29 实测）。这里自己限流 + 退避。
            self._sem = asyncio.Semaphore(int(os.environ.get("MEMBENCH_GRAPHITI_RERANK_CONCURRENCY", "4")))

        async def _one(self, messages: list[dict]) -> float:
            delay = 2.0
            for attempt in range(4):
                try:
                    async with self._sem:
                        r = await self.client.chat.completions.create(
                            model=self.config.model, messages=messages, temperature=0,
                            max_tokens=64, extra_body={"reasoning_effort": "low"},
                        )
                    gtrace.METER.record_llm(getattr(r, "usage", None))
                    txt = (r.choices[0].message.content or "").strip().lower()
                    return 1.0 if txt.startswith("true") else 0.0
                except Exception as e:  # noqa: BLE001
                    if "429" not in str(e) and "rate" not in str(e).lower() or attempt == 3:
                        gtrace.note_channel("rerank.cross_encoder.ERROR", -1, 0)
                        raise
                    await asyncio.sleep(delay)
                    delay *= 2
            return 0.0

        async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
            if not passages:
                return []

            msgs = [[
                Message(role="system",
                        content="You are an expert tasked with determining whether the passage is relevant to the query"),
                Message(role="user", content=f"""
                           Respond with "True" if PASSAGE is relevant to QUERY and "False" otherwise.
                           <PASSAGE>
                           {p}
                           </PASSAGE>
                           <QUERY>
                           {query}
                           </QUERY>
                           """),
            ] for p in passages]
            t0 = time.perf_counter()
            scores: list[float] = list(await asyncio.gather(
                *[self._one([m.model_dump() for m in ms]) for ms in msgs]))
            gtrace.METER.rerank_calls += len(passages)
            gtrace.note_channel("rerank.cross_encoder", len(passages), int((time.perf_counter() - t0) * 1000))
            ranked = sorted(zip(passages, scores, strict=True), key=lambda x: x[1], reverse=True)  # 稳定排序保候选原序
            return ranked

    return TextClassifierReranker(llm_cfg)


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
                # graphiti 自带默认 16384，现在（thinking=low）够用；但思考与正式回复共用额度，
                # 调高 thinking 后同样会被吞掉。与 mem0/amem 对齐到 128k，去掉写死预算这个隐含假设。
                max_tokens=int(os.environ.get("MEMBENCH_MAX_TOKENS", "128000")),
            ),
            structured_output_mode="json_object",  # 智谱无 Responses API/json_schema，用 json_object
        )
        # GenericClient 不透传 reasoning——在 AsyncOpenAI 客户端上钉 reasoning_effort（与 mem0 同款手法）
        # 同一处顺带截 usage：graphiti 自身不外露 token，只有这个边界能拿到真实用量
        _create = llm.client.chat.completions.create

        async def _create_pinned(**kwargs):
            kwargs.setdefault("extra_body", {})["reasoning_effort"] = "low" if thinking == "low" else "high"
            resp = await _create(**kwargs)
            gtrace.METER.record_llm(getattr(resp, "usage", None))
            return resp

        llm.client.chat.completions.create = _create_pinned
        embedder = OpenAIEmbedder(
            config=OpenAIEmbedderConfig(
                embedding_model=os.environ.get("MEMBENCH_EMBED_MODEL", "embedding-3"),
                embedding_dim=int(os.environ.get("MEMBENCH_EMBED_DIM", "2048")),
                api_key=os.environ.get("MEMBENCH_EMBED_API_KEY") or os.environ["MEMBENCH_LLM_API_KEY"],
                base_url=os.environ.get("MEMBENCH_EMBED_BASE_URL") or os.environ["MEMBENCH_LLM_BASE_URL"],
            )
        )
        _ecreate = embedder.client.embeddings.create

        async def _ecreate_metered(**kwargs):
            resp = await _ecreate(**kwargs)
            gtrace.METER.record_embed(getattr(resp, "usage", None))
            return resp

        embedder.client.embeddings.create = _ecreate_metered

        # reranker 也走同一端点（Graphiti.__init__ 默认无参构造会去找 OPENAI_API_KEY，本地未设——坑）
        reranker = _make_reranker(LLMConfig(
            api_key=os.environ["MEMBENCH_LLM_API_KEY"],
            base_url=os.environ["MEMBENCH_LLM_BASE_URL"],
            model=os.environ.get("MEMBENCH_RERANKER_MODEL", os.environ["MEMBENCH_LLM_MODEL"]),
        ))
        _G = Graphiti(NEO4J_URI, NEO4J_USER, NEO4J_PASS, llm_client=llm, embedder=embedder, cross_encoder=reranker)
        # 上游 create_tracer() 只认 OTel，因此构造后直接换上我们的 JSONL tracer（clients 是 pydantic 模型，可赋值）
        tracer = gtrace.JsonlTracer()
        _G.tracer = tracer
        _G.clients.tracer = tracer
        probes = gtrace.install_channel_probes()
        await _G.build_indices_and_constraints()  # 幂等
        gtrace.emit("init", {"neo4j": NEO4J_URI, "llm_model": os.environ["MEMBENCH_LLM_MODEL"],
                             "embed_model": os.environ.get("MEMBENCH_EMBED_MODEL", "embedding-3"),
                             "thinking": thinking, "channel_probes": probes,
                             "knobs": _search_knobs(5), "trace_file": str(gtrace.trace_path())})
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


# ---------- constructor χ：论文 §3 的三类对象 → envelope ----------

def _d(dt) -> str | None:  # noqa: ANN001
    return dt.strftime("%Y-%m-%d") if dt else None


def _flat(s: str) -> str:
    """把换行/连续空白压成单空格。EntityNode.summary 是多行聚合文本，直接入 envelope 会把
    契约 §4 的“单条 markdown 列表项”撞成多行，与其他 arm 的证据版式不一致。"""
    return " ".join(str(s or "").split())


def _edge_envelope(e) -> tuple[dict, bool]:  # noqa: ANN001
    """§3 χ：对每条 ei ∈ Es 返回 fact 与 tvalid/tinvalid。
    上游 search_helpers.format_edge_date_range 的语义是 `valid_at - (invalid_at | present)`，
    §3 的 context 模板写作 `FACT (Date range: from - to)`。契约 §4 把渲染结构锁成
    `- 时间戳 · 内容（session 溯源）`，所以把**日期区间放进时间戳槽位**：既保住全臂位置一致，
    又把 tvalid/tinvalid 一起带给答题 LLM。
    第二个返回值：valid_at 是否缺失，用于统计与告警。
    ⚠️ valid_at 缺失时 timestamp 置 None 而**不回退 created_at**：created_at 是入库墙钟（2026），
    正是它把 9930 条 envelope 的年份污染成 100% 2026。宁可 null，也不要假时间——text 里同步写
    "date unknown"，答题 LLM 与事后审计看到的是同一个事实。"""
    valid, invalid = getattr(e, "valid_at", None), getattr(e, "invalid_at", None)
    missing = valid is None
    lo = _d(valid) or "date unknown"
    hi = _d(invalid) or "present"
    return make_envelope(
        memory_id=e.uuid,
        text=_flat(e.fact),
        session_id=None,       # fact→episode 映射 v1 未做，见 spec 粒度声明
        turn_range=None,
        timestamp=valid.isoformat() if valid else None,
        score=None,            # 排序即相关性，原生分数未外露（真实重排分写进 mcp_trace）
        raw_format="graphiti_fact",
        display_time=f"{lo} → {hi}",
    ), missing


def _node_envelope(n) -> dict:  # noqa: ANN001
    """§3 χ：对每个 ni ∈ Ns 返回 name 与 summary。实体节点没有 tvalid（双时间轴只在边上），
    created_at 是入库墙钟（2026），带上只会误导答题 LLM → timestamp 置 None。"""
    body = _flat(f"{n.name}: {n.summary}").strip().rstrip(":")
    return make_envelope(memory_id=n.uuid, text=body, session_id=None, turn_range=None,
                         timestamp=None, score=None, raw_format="graphiti_entity")


def _community_envelope(c) -> dict:  # noqa: ANN001
    """§3 χ：对每个 ni ∈ Nc 返回 summary（name 是检索用的关键词串，一并带出便于人工审查）。"""
    body = _flat(f"{c.name}: {c.summary}").strip().rstrip(":")
    return make_envelope(memory_id=c.uuid, text=body, session_id=None, turn_range=None,
                         timestamp=None, score=None, raw_format="graphiti_community")


def _allocate(top_k: int, mix: str, avail: dict[str, int]) -> dict[str, int]:
    """把 top_k 个名额按 mix 权重分给 edge/node/community（最大余额法），再按可用量裁剪，
    余下名额按 edge → node → community 顺序回填。总数恒 ≤ top_k：契约 §7 的 top_k 全臂一致不能破。"""
    order = ["edge", "node", "community"]
    try:
        w = [max(0.0, float(x)) for x in mix.split(":")]
        assert len(w) == 3 and sum(w) > 0
    except Exception:  # noqa: BLE001
        w = [3.0, 1.0, 1.0]
    total = sum(w)
    raw = {k: top_k * wi / total for k, wi in zip(order, w, strict=True)}
    quota = {k: int(math.floor(v)) for k, v in raw.items()}
    for k in sorted(order, key=lambda k: raw[k] - quota[k], reverse=True):
        if sum(quota.values()) >= top_k:
            break
        quota[k] += 1
    take = {k: min(quota[k], avail.get(k, 0)) for k in order}
    for k in order:  # 回填：某类不够就让给下一类（避免 community 为空时白白浪费名额）
        spare = top_k - sum(take.values())
        if spare <= 0:
            break
        take[k] = min(avail.get(k, 0), take[k] + spare)
    return take


@mcp.tool
async def add_conversation(session_id: str, turns: list[dict], scope: dict, metadata: dict | None = None) -> dict:
    """一个 session 一个 episode，body 为整段对话文本；group_id = scope.id（对话间隔离）。"""
    t0 = time.perf_counter()
    g = await _get_graphiti()
    body = "\n".join(f"{t.get('role', 'user')}: {t.get('content', '')}" for t in turns)
    ref_time = _iso_or_now(next((t.get("timestamp") for t in turns if t.get("timestamp")), None))
    with gtrace.call_ctx(tool="add_conversation") as ctx:
        t_llm = time.perf_counter()
        await g.add_episode(
            name=session_id,
            episode_body=body,
            source_description="memory-bench ingest",
            reference_time=ref_time,
            group_id=scope.get("id"),
        )
        usage = gtrace.Meter.delta(ctx["meter_before"], gtrace.METER.snapshot())
        gtrace.emit("add_conversation", {
            "session_id": session_id, "scope_id": scope.get("id"), "n_turns": len(turns),
            "body_chars": len(body), "reference_time": ref_time.isoformat(),
            "config": {"llm_model": os.environ.get("MEMBENCH_LLM_MODEL"), "temperature": 0,
                       "reasoning_effort": os.environ.get("MEMBENCH_THINKING", "low"),
                       "structured_output_mode": "json_object",
                       "embed_model": os.environ.get("MEMBENCH_EMBED_MODEL", "embedding-3")},
            "usage": usage, "spans": ctx["spans"],
            "timing_ms": {"total": int((time.perf_counter() - t0) * 1000),
                          "add_episode": int((time.perf_counter() - t_llm) * 1000)},
        })
    _save_scope(scope.get("id"), session_id)
    _stats.n_sessions = len(_scopes()["sessions"])
    _stats.add_tokens("ingest", usage["llm_prompt_tokens"] + usage["llm_completion_tokens"])
    _stats.add_tokens("internal_llm", usage["llm_prompt_tokens"] + usage["llm_completion_tokens"])
    _stats.llm_calls += usage["llm_calls"]
    return {
        "accepted_turns": len(turns),
        "native_notes": (f"graphiti 抽取完成，耗时 {int((time.perf_counter() - t0) * 1000)}ms；"
                         f"内部 LLM {usage['llm_calls']} 次 / {usage['llm_prompt_tokens'] + usage['llm_completion_tokens']} tok，"
                         f"embedding {usage['embed_calls']} 次"),
    }


@mcp.tool
async def retrieve(query: str, query_mode: str = "fixed", top_k: int = 5, filter: dict | None = None) -> dict:
    """Zep §3 的 f(α)=χ(ρ(ϕ(α)))：三路检索（bm25+cosine+bfs）→ 重排 → 构造带双时间轴的 envelope。
    返回 edges(fact+tvalid/tinvalid) + entity nodes(name+summary) + community nodes(summary)。"""
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

    knobs = _search_knobs(top_k)
    cfg = _build_search_config(knobs)
    group_ids = [gid] if gid else None
    fp = _config_fingerprint(cfg, knobs, group_ids)

    with gtrace.call_ctx(tool="retrieve") as ctx:
        t_search = time.perf_counter()
        res = await g.search_(query, config=cfg, group_ids=group_ids)
        ms_search = int((time.perf_counter() - t_search) * 1000)

        t_render = time.perf_counter()
        edge_envs, no_valid_at = [], 0
        for e in res.edges:
            env, miss = _edge_envelope(e)
            edge_envs.append(env)
            no_valid_at += int(miss)
        node_envs = [_node_envelope(n) for n in res.nodes]
        comm_envs = [_community_envelope(c) for c in res.communities]
        take = _allocate(top_k, knobs["mix"],
                         {"edge": len(edge_envs), "node": len(node_envs), "community": len(comm_envs)})
        results = edge_envs[:take["edge"]] + node_envs[:take["node"]] + comm_envs[:take["community"]]
        ms_render = int((time.perf_counter() - t_render) * 1000)

        usage = gtrace.Meter.delta(ctx["meter_before"], gtrace.METER.snapshot())
        channels = ctx["channels"]
        dead = [k for k, v in channels.items() if not k.endswith(".ERROR") and v["hits_total"] == 0]
        expected = ["edge.bm25", "edge.cosine", "edge.bfs"] + (
            ["node.bm25", "node.cosine", "node.bfs", "community.bm25", "community.cosine"] if knobs["triple"] else [])
        never_ran = [c for c in expected if c not in channels]
        if never_ran:
            notes.append(f"CHANNEL_NOT_INVOKED: {','.join(never_ran)}")
        if no_valid_at:
            notes.append(f"VALID_AT_MISSING: {no_valid_at}/{len(edge_envs)} 条 edge 无 valid_at（timestamp=null，text 标 date unknown）")

        n_valid = sum(1 for e in res.edges if getattr(e, "valid_at", None))
        n_invalid = sum(1 for e in res.edges if getattr(e, "invalid_at", None))
        gtrace.emit("retrieve", {
            "query": query, "query_mode": query_mode, "top_k": top_k,
            "config": fp,
            "channels": channels, "channels_zero_hit": dead, "channels_never_invoked": never_ran,
            "spans": ctx["spans"],
            "raw_counts": {"edges": len(res.edges), "nodes": len(res.nodes),
                           "communities": len(res.communities), "episodes": len(res.episodes)},
            "reranker_scores": {"edge": [round(s, 6) for s in res.edge_reranker_scores[:top_k]],
                                "node": [round(s, 6) for s in res.node_reranker_scores[:top_k]],
                                "community": [round(s, 6) for s in res.community_reranker_scores[:top_k]]},
            "bitemporal": {"edges_with_valid_at": n_valid, "edges_with_invalid_at": n_invalid,
                           "edges_without_valid_at": no_valid_at},
            "allocation": take, "returned": len(results),
            "usage": usage,
            "timing_ms": {"total": int((time.perf_counter() - t0) * 1000),
                          "search": ms_search, "render": ms_render},
        })
    _stats.add_tokens("retrieve", usage["llm_prompt_tokens"] + usage["llm_completion_tokens"])
    _stats.llm_calls += usage["llm_calls"]

    notes.append(f"CHANNELS: " + ",".join(f"{k}={v['hits_total']}" for k, v in sorted(channels.items())))
    notes.append(f"MIX: edge={take['edge']} node={take['node']} community={take['community']}"
                 f"（reranker={knobs['reranker']}, search_limit={knobs['search_limit']}）")
    return {
        "results": results,
        "query_used": query,
        "query_mode": query_mode,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
        "native_notes": "; ".join(notes),
    }


@mcp.tool
async def build_communities(scope_id: str | None = None) -> dict:
    """构建/刷新 community 子图（论文 §2.3：label propagation + map-reduce 摘要）。

    这是 §1 六工具之外的**维护工具**：契约要求的六个工具名不受影响，评测循环不会调用它。
    单列出来的理由是成本必须可度量——build 是 O(实体数) 次 LLM 调用，必须在同一进程里跟
    trace/Meter 打通才能拿到真实 token 账单。scope_id=None 会对**全图**构建，代价很高，慎用。"""
    t0 = time.perf_counter()
    g = await _get_graphiti()
    group_ids = [scope_id] if scope_id else None
    with gtrace.call_ctx(tool="build_communities") as ctx:
        nodes, edges = await g.build_communities(group_ids=group_ids)
        usage = gtrace.Meter.delta(ctx["meter_before"], gtrace.METER.snapshot())
        elapsed = int((time.perf_counter() - t0) * 1000)
        gtrace.emit("build_communities", {
            "scope_id": scope_id, "n_community_nodes": len(nodes), "n_community_edges": len(edges),
            "usage": usage, "timing_ms": {"total": elapsed},
            "sample": [{"name": n.name, "summary": n.summary[:200]} for n in nodes[:3]],
        })
    _stats.add_tokens("internal_llm", usage["llm_prompt_tokens"] + usage["llm_completion_tokens"])
    _stats.llm_calls += usage["llm_calls"]
    return {"ok": True, "scope_id": scope_id, "n_community_nodes": len(nodes),
            "n_community_edges": len(edges), "usage": usage, "elapsed_ms": elapsed}


@mcp.tool
async def reset() -> dict:
    """清图：cypher DETACH DELETE。⚠️ 不能动 neo4j-data 目录（docker 卷挂载中）。幂等。"""
    g = await _get_graphiti()
    await g.driver.execute_query("MATCH (n) DETACH DELETE n")
    SIDECAR.unlink(missing_ok=True)
    _stats.mark_reset()
    _stats.n_sessions = 0
    gtrace.emit("reset", {})
    return {"ok": True, "cleared": {"system": "graphiti", "note": "cypher 全清，索引保留"}}


@mcp.tool
async def stats() -> dict:
    n_nodes = n_edges = n_comm = 0
    try:
        g = await _get_graphiti()
        r1 = await g.driver.execute_query("MATCH (n) RETURN count(n) AS c")
        n_nodes = r1.records[0]["c"]
        r2 = await g.driver.execute_query("MATCH ()-[r:RELATES_TO]->() RETURN count(r) AS c")
        n_edges = r2.records[0]["c"]
        r3 = await g.driver.execute_query("MATCH (n:Community) RETURN count(n) AS c")
        n_comm = r3.records[0]["c"]
    except Exception:
        pass
    return _stats.to_dict(n_memories=n_edges) | {
        "n_graph_nodes": n_nodes, "n_community_nodes": n_comm,
        "meter_totals": gtrace.METER.snapshot(), "trace_file": str(gtrace.trace_path()),
    }


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
    gtrace.emit("snapshot", {"tag": tag, "elapsed_ms": int((time.perf_counter() - t0) * 1000)})
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
    gtrace.emit("restore", {"tag": tag, "elapsed_ms": int((time.perf_counter() - t0) * 1000)})
    return {"ok": True, "tag": tag, "elapsed_ms": int((time.perf_counter() - t0) * 1000)}


if __name__ == "__main__":
    mcp.run()  # stdio

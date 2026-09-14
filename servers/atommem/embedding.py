# atommem/embedding：把上游写死的本地 all-MiniLM-L6-v2（384d）换成云端 embedding-3（2048d）
#
# 为什么换：AtomMem 论文 §4.1 与代码都统一用 all-minilm-L6-v2，但 memory-bench 的
# mem0 / graphiti / mandol / rag_baseline 四臂用 embedding-3。用户 2026-09-10 定：
# atommem 走 embedding-3，与四臂同口径，把"嵌入强度"这个变量从跨臂对比里排除。
#
# ⚠️ 已知代价（决策时已声明，不是事后发现）：AtomMem 的构建侧阈值全部是在 384d MiniLM
# 尺度上调出来的硬编码值——去重 0.95（config.py:59）、冲突门 0.6、画像免 LLM 0.55。
# 换到 2048d embedding-3 后余弦分布会平移，这三个阈值的实际触发率会漂。
# server.py 的 _wrap_threshold_probes 逐次统计它们的触发情况，stats() 里单列上报。
#
# 接口与上游 src/embedding.py 的 EmbeddingModel 逐字段一致：dimension / encode / encode_batch。
# 上游 6 处都是无参构造 `EmbeddingModel()` 后只调这三个成员，故可整类替换。

import os
import time

from openai import OpenAI

# 上游 encode 是逐条同步调用（build_fact_tuple 每条 fact 一次），云端 RTT 会主导 ingest 时间。
# 进程内缓存吃掉重复文本（query 在 prepare_query_info 与 answer_query_with_query_info 各编码一次）。
_CACHE: dict[str, list[float]] = {}
_CACHE_MAX = 50000

# 全局用量：server.py 在 add_conversation / retrieve 前后读差值，归进对应 token bucket。
USAGE = {"tokens": 0, "calls": 0, "cache_hits": 0}

_BATCH = 32          # 智谱 embeddings 单请求条数上限保守取值
_MAX_RETRY = 4
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        missing = [k for k in ("MEMBENCH_LLM_API_KEY", "MEMBENCH_LLM_BASE_URL") if not os.environ.get(k)]
        if missing:
            raise RuntimeError(
                f"缺少环境变量 {missing}——MCP stdio 子进程不继承父进程环境（见 interface-spec §7）"
            )
        # 与 rag_baseline 同款：embedding 走智谱普通通道，coding 通道无 embedding-3 权限
        base = os.environ.get("MEMBENCH_EMBED_BASE_URL") or os.environ["MEMBENCH_LLM_BASE_URL"].replace("/coding", "")
        key = os.environ.get("MEMBENCH_EMBED_API_KEY") or os.environ["MEMBENCH_LLM_API_KEY"]
        _client = OpenAI(api_key=key, base_url=base)
    return _client


def _model_name() -> str:
    return os.environ.get("MEMBENCH_EMBED_MODEL", "embedding-3")


def _call_api(texts: list[str]) -> list[list[float]]:
    """一次 embeddings 调用，带指数退避重试（429/超时靠长退避扛，同 bench/llm.py 口径）。"""
    last_err: Exception | None = None
    for attempt in range(_MAX_RETRY):
        try:
            r = _get_client().embeddings.create(model=_model_name(), input=texts)
            USAGE["calls"] += 1
            USAGE["tokens"] += int(getattr(r.usage, "total_tokens", 0) or 0)
            return [d.embedding for d in r.data]
        except Exception as e:                      # noqa: BLE001 —— 网络层异常一律退避重试
            last_err = e
            if attempt < _MAX_RETRY - 1:
                time.sleep(2 ** attempt)            # 1s / 2s / 4s
    raise RuntimeError(f"embedding-3 调用失败（重试 {_MAX_RETRY} 次）: {last_err}")


def _embed_uncached(texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), _BATCH):
        out.extend(_call_api(texts[i : i + _BATCH]))
    return out


class CloudEmbeddingModel:
    """上游 EmbeddingModel 的替身：同名方法、同返回类型，向量来自 embedding-3。"""

    def __init__(self) -> None:
        self.dimension = int(os.environ.get("ATOMMEM_EMBEDDING_DIMENSION", "2048"))

    def encode(self, text: str) -> list[float]:
        return self.encode_batch([text])[0]

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        # 空串直接给零向量：上游有 profile/keyword 拼接为空的路径，不值得为它发请求
        results: list[list[float] | None] = [None] * len(texts)
        pending: list[str] = []
        pending_idx: list[int] = []

        for i, t in enumerate(texts):
            key = (t or "").strip()
            if not key:
                results[i] = [0.0] * self.dimension
                continue
            hit = _CACHE.get(key)
            if hit is not None:
                results[i] = hit
                USAGE["cache_hits"] += 1
            else:
                pending.append(key)
                pending_idx.append(i)

        if pending:
            # 同一批内的重复文本只发一次
            uniq: dict[str, int] = {}
            uniq_texts: list[str] = []
            for t in pending:
                if t not in uniq:
                    uniq[t] = len(uniq_texts)
                    uniq_texts.append(t)
            vecs = _embed_uncached(uniq_texts)
            for t, v in zip(uniq_texts, vecs):
                if len(_CACHE) < _CACHE_MAX:
                    _CACHE[t] = v
            for i, t in zip(pending_idx, pending):
                results[i] = vecs[uniq[t]]

        return [r if r is not None else [0.0] * self.dimension for r in results]


def reset_usage() -> None:
    USAGE.update({"tokens": 0, "calls": 0, "cache_hits": 0})


def clear_cache() -> None:
    _CACHE.clear()

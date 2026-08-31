# amem 两臂共用的向量层：embedding-3 云端 + chroma reset 隔离。
#
# 放在 fixed.py 之外，是因为这两件事都**不属于论文机制修复**，而是「统一配置」和「修 bug」：
#   · embedding-3   —— 与 mem0/graphiti/mandol/rag_baseline 同口径（interface-spec §7）。
#                      2026-08-30 决策：native 臂也换，否则 native vs fixed 的差异里
#                      混着 384d↔2048d 这个变量，机制收益无法归因。
#   · reset 隔离     —— A-MEM 的 AgenticMemorySystem.__init__ 里有一句
#                      `temp_retriever.client.reset()`，而 chroma 的 reset 是**全局**的
#                      （1.5.9 里 Client 实例虽不再是单例，但底层 system 共享）。
#                      每 new 一个 scope 就把之前所有 scope 的 collection 清空。
#                      LoCoMo 有 10 个 conversation = 10 个 scope，等于只有最后一个存活。
#                      2026-08-30 实测确认，native / fixed 两臂同时中招。

import contextlib
import logging
import os

import chromadb
from chromadb.config import Settings

from agentic_memory.retrievers import ChromaRetriever

logger = logging.getLogger(__name__)


def _embed_client():
    from openai import OpenAI

    # 与 rag_baseline 同款：embedding 走智谱普通通道（coding 通道无 embedding-3 权限）
    base = os.environ.get("MEMBENCH_EMBED_BASE_URL") or os.environ.get(
        "MEMBENCH_LLM_BASE_URL", ""
    ).replace("/coding", "")
    key = os.environ.get("MEMBENCH_EMBED_API_KEY") or os.environ.get("MEMBENCH_LLM_API_KEY")
    if not base or not key:
        raise RuntimeError(
            "amem 需要 MEMBENCH_LLM_BASE_URL / MEMBENCH_LLM_API_KEY"
            "（或 MEMBENCH_EMBED_* 覆盖）——见 interface-spec §7"
        )
    return OpenAI(api_key=key, base_url=base)


class CloudEmbeddingFunction:
    """ChromaDB embedding function：embedding-3 云端，与其他 arm 同口径。

    统计 (calls, tokens) 供 stats 上报——原生 A-MEM 用本地模型无此开销，换云端后必须显式记账。
    """

    def __init__(self):
        self.model = os.environ.get("MEMBENCH_EMBED_MODEL", "embedding-3")
        self.calls = 0
        self.tokens = 0
        self._client = None

    @staticmethod
    def name() -> str:
        # chromadb ≥0.5 要求 embedding function 提供 name()
        return "membench_cloud_embed"

    def embed_query(self, input):
        """chromadb 1.x 的 query 路径单独调这个（不走 __call__），
        不实现会报 'object has no attribute embed_query'。"""
        return self([input] if isinstance(input, str) else list(input))

    def embed_documents(self, input):
        return self([input] if isinstance(input, str) else list(input))

    def __call__(self, input: list[str]) -> list[list[float]]:
        if self._client is None:
            self._client = _embed_client()
        out: list[list[float]] = []
        for i in range(0, len(input), 64):   # 智谱 embeddings 单次 batch 上限保守取 64
            chunk = input[i : i + 64]
            r = self._client.embeddings.create(model=self.model, input=chunk)
            out.extend(d.embedding for d in r.data)
            self.calls += 1
            self.tokens += getattr(r.usage, "total_tokens", 0) or 0
        return out


class CloudChromaRetriever(ChromaRetriever):
    """与 ChromaRetriever 同接口，但 embedding 走云端 embedding-3。

    刻意不调父类 __init__：父类会先用 SentenceTransformerEmbeddingFunction 建好 collection，
    chromadb ≥0.5 会在事后更换 embedding_function 时抛
    "An embedding function already exists in the collection configuration"。
    父类的 add_document / search / delete_document / _convert_metadata_* 只依赖 self.collection，可直接复用。
    """

    def __init__(self, collection_name: str, embed_fn: CloudEmbeddingFunction):
        self.client = chromadb.Client(Settings(allow_reset=True))
        self.embedding_function = embed_fn
        try:
            self.client.delete_collection(collection_name)
        except Exception:
            pass
        self.collection = self.client.create_collection(
            name=collection_name, embedding_function=embed_fn
        )


@contextlib.contextmanager
def no_chroma_reset():
    """临时把 chroma 的全局 reset 变成 no-op。

    A-MEM 的 AgenticMemorySystem.__init__ 会执行 `temp_retriever.client.reset()`，
    意图只是清自己那个写死的 "memories" collection，但 chroma 的 reset 是全局的，
    会连带清掉同进程内所有 scope 的 collection。上游那句 reset 本身裹在 try/except 里，
    变成 no-op 不影响其语义（它本来就允许失败）。
    """
    K = chromadb.api.client.Client
    orig = K.reset
    K.reset = lambda self: True
    try:
        yield
    finally:
        K.reset = orig

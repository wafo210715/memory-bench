# plugmem：A档系统（arXiv:2603.03296，PlugMem: A Task-Agnostic Plugin Memory Module
#   for LLM Agents，ICML 2026；上游 TIMAN-group/PlugMem @ 3b2ce75）
#
# 机制：把交互轨迹（观察-动作对）逐步 LLM 标注（子目标/奖励/状态），按子目标相似度切段，
#   每步抽语义命题+概念标签、每段抽意图+处方（A2），入三张图（情景/语义/程序，A4/A5）；
#   检索期先由 LLM 三选一决定用哪类记忆并抽象出概念标签与下一步意图（B1），
#   两通道召回（稠密余弦 + 高层节点路由激活低层节点，B2/B3），按预算重排剪枝（B4），
#   多跳循环直到证据够或触顶（B8）。
#
# ═══ 复现口径（偏离上游或论文之处全部列在这里，不静默）═══
# 判据：memory-system-analysis §4「复现论文的理念优先于照抄代码」。逐条对应
# servers/plugmem/paper-vs-code.md 的差异编号。
#
# 1. A2 处方质量分按论文补齐（差异 #2，能力损失/高）
#    论文 txt:728-730、2426-2427：独立评委给每条处方打 1–10 分。上游函数定义在
#    （inference/structuring.py:96）但调用点零处，get_procedural 直接写死 return=0.0
#    （structuring.py:124）。本臂在 Memory.close() 之后逐条补调 get_return 并写回，
#    质量分随处方持久化，出现在 envelope 的 raw_format 元数据与 stats().paper_restored。
#    ⚠️ 只补"打分"这个论文承诺过的动作；**不改排序公式**——论文从未给出质量分进入
#      重排的权重（B4 原文只写 relevance 和 optional importance），自创权重属无据调参。
#      质量分因此可观测、可分析，但当前不影响名次。这条边界是刻意的。
#
# 2. A3 意图去重按论文改回语义判重（差异 #5，能力损失/高）
#    论文 txt:2428-2431：新意图与已有意图算 embedding 余弦，超过 θ_equal 才让 LLM 合并改写。
#    上游换成字典 key 精确字符串匹配（memory_graph.py:515），字面不同即新建，
#    语义级合并能力实际不存在，而程序检索侧又只取最好的 1 个意图，冗余直接稀释命中。
#    本臂在 insert 之前做一层"意图归并预处理"：新意图与图中已有意图算余弦，
#    ≥θ_equal 时把 proc_item["subgoal"] 改写成已有节点的字符串，从而触发上游原有的
#    LLM 合并路径（get_new_subgoal）。不改上游代码，只改喂进去的内容。
#    θ_equal 论文无取值，取上游 SubgoalEqual.value_threshold=0.8（代码内唯一的意图判等阈值）。
#
# 3. B8 多跳检索控制器按论文补齐，默认 T_max=2（差异 #1，能力损失/高）
#    论文 txt:755-757 与附录 C.3 把"迭代到证据足够或触顶"写成检索模块的默认能力，
#    F.2 明确说 T_max 是 default configuration 之上的 test-time 旋钮（2→4 有增益），
#    即默认值为 2。上游本体零实现，唯一实现在 HotpotQA 评测脚本且默认关。
#    本臂按论文 Listing 10 实现 MULTI HOP CTRL（judge 输出 {"enough", "top_node_ids"}），
#    下一跳 query 用论文默认的纯拼接（不启用可选的 LLM 改写器）。
#    ⚠️ 口径影响：stop-check 要读本轮命中的记忆内容 → 本臂属 **active retrieval**，
#      与 intent 的 Tier2 同栏，不能放进"零 LLM 检索面"的成本/延迟表直接并列
#      （interface-spec §7 检索面分栏）。需要纯被动对照时设 MEMBENCH_PLUGMEM_MAX_HOPS=1，
#      此时 retrieve 只剩 B1 的两次查询理解调用（只读 query 不读记忆，同 atommem 那一栏）。
#
# 4. B6 推理压缩模块默认关（差异 #3，能力损失/高）
#    论文把 Reasoning Module 列为三大组件之一（去掉它 LME 掉 2.7pt、token 涨约 26 倍，
#    Table 6），本质是把多条记忆压成一段可执行指导的压缩器。上游已把它移出系统边界，
#    由调用方各自解决。memory-bench 的 harness 已统一承担证据渲染与答题 prompt 组装
#    （interface-spec §4：envelope 的渲染结果就是喂给答题 LLM 的证据文本），
#    在 retrieve 内再压一次会让本臂的证据粒度与其余臂不可比（其他臂 top_k 条、
#    本臂将退化为 1 条整段指导）。故默认关，MEMBENCH_PLUGMEM_REASONING=1 可开，
#    开启时只影响 native_notes 里的 reasoning_text，不改 envelope 结构。
#
# 5. 检索预算 K 接到契约 top_k（差异 #9 的一部分，设计演进/中）
#    论文 txt:753-755：候选超过预算（e.g. top-K）就重排剪枝，K 是外部预算参数。
#    上游把它具体化成写死值：语义最终 k=10、程序 k=1、稠密候选池 5、情景池 30。
#    本臂只把**最终预算**统一接到 top_k（全 arm 一致=20，interface-spec §7），候选池保持上游原样。
#    ⚠️ 2026-09-13 按对抗审查 M1 回改：早前把稠密候选池也扩到 top_k，把标签路由通道完全抵消
#      ——最终排序是纯余弦，路由进来的节点要么已在稠密 top_k 里、要么排不进，
#      论文 B3「高层节点路由激活低层节点」在语义模式上变成了空操作。
#      现在直接用上游 retrieve_semantic_nodes（内部：稠密 5 ∪ 标签路由 → 纯余弦取 k），
#      只把 k 换成 top_k。
#    ⚠️ 保持上游默认不动的：标签路由 k=1/阈值 0.8、意图路由 k=1/阈值 0.1、稠密候选池 5、
#      程序最终阈值 0.1（审查 m1）、情景投票池 30、会话投票阈值 3。
#      它们是"路由信号"的选择而非预算，论文未给取值，改动无据。
#
# 6. 对话 → 轨迹的映射沿用上游 LongMemEval 复现脚本的做法
#    PlugMem 的 A1 吃的是 (observation, action) 对。上游 LME 脚本
#    （src/eval/longmemeval/eval_longmemeval_all.py:36-59）把 user 话语当 observation、
#    assistant 话语当 action。LoCoMo 是双人对话、harness 把两个 speaker 都标成 role=user
#    并把说话人名编进 content（loaders/locomo.py:96-99），故本臂按 content 前缀解析说话人：
#    第一位说话人 → observation 侧，第二位 → action 侧；连续同一说话人的多条 turn 合并进同一侧
#    （上游脚本遇到这种情况直接抛 ValueError，LoCoMo 里确实存在连续同人发言）。
#    ⚠️ 2026-09-13 对抗审查 C1（致命，已修）：上游 get_semantic 只读 observation 字段
#      （inference/structuring.py:73，GetSemanticPrompt 唯一文档槽位也只有 {observation}），
#      动作侧话语只进情景节点、永远不会变成命题。LongMemEval 里动作侧是助手话语、
#      不是提问对象，所以上游那样没问题；平移到 LoCoMo 就错了——实测落在动作侧的
#      turn 2871/5882=48.8%，其中 gold evidence 1355/2806=48.3%，且开场说话人逐段翻转，
#      “被抽到的是哪一半”还是随机的。现由 _extract_action_side_semantics 逐步对动作侧
#      再抽一次命题并并进同一批语义层，成本约 +25%，数量计在
#      stats().paper_restored.action_side_facts。
#    另在每段会话末尾补一个收尾步：上游的逐步结构会把最后一个 observation 留在轨迹外，
#    对话场景下等于每段会话的最后一句话不被抽成命题，单 turn 会话更是整个变成空图。
#    该收尾步直接合成写入轨迹（零 LLM 调用），不走 append（审查 M4：走 append 会多 3 次标注、
#    制造一个只含占位步的伪轨迹段，并产出一条关于“不回复”的处方污染程序图）。
#
# ⚠️ 2026-09-13 对抗审查的其余修复（逐条证据见 servers/plugmem/review-2026-09-13.md）：
#    M2 多跳控制器的节点 id 加类型前缀、情景模式也能匹配重点节点、程序模式第二跳用新意图；
#    M3 意图合并把原始新意图串传给上游合并函数（而不是让它看到两个相同串）并把合并文本写回节点；
#    M5 情景侧超出半预算被截掉的节点，把投中它的命题回填到命题侧参与排序。
#
# 7. embedding 用 embedding-3（偏离论文与上游的 NV-Embed-v2）
#    与 mem0 / graphiti / mandol / rag_baseline / atommem 同口径，排除"嵌入强度"这个跨臂变量。
#    代价：上游硬编码的相似度阈值（切段 0.75、标签 0.8、意图 0.1、意图判等 0.8）是在
#    NV-Embed-v2 尺度上定的，换嵌入后触发率会漂。由 stats().threshold_probes 逐次观测。
#
# 8. max_tokens 8192（上游默认 4096）
#    上游 4096 面向英文 WebArena/LME；LoCoMo 场景下 get_semantic 要一次产 ≤10 条带标签命题，
#    中文 token 密度更高，4096 有截断风险，而截断是**静默**的——正则匹配不到就返回空列表，
#    命题直接消失。finish_reason=="length" 的次数记在 stats().truncated_completions，
#    非零就说明这个口径需要再提。
#
# 依赖：主 venv（.venv，chromadb 1.5.9 / openai / numpy 已在）。上游包用 sys.path 引入，
#   不 pip 安装、不改上游仓库。上游 clone 默认 ~/Documents/repo/PlugMem，
#   可用 MEMBENCH_PLUGMEM_REPO 覆盖。
# 环境变量：MEMBENCH_LLM_API_KEY / MEMBENCH_LLM_BASE_URL / MEMBENCH_LLM_MODEL
#   可选：MEMBENCH_PLUGMEM_MAX_HOPS（默认 2）、MEMBENCH_PLUGMEM_REASONING（默认 0）、
#        MEMBENCH_THINKING（默认 low，三态同 mem0）、MEMBENCH_EMBED_*（同 rag_baseline）

import json
import logging
import os
import re
import sys
import time
from pathlib import Path

MEMBENCH_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(MEMBENCH_ROOT))

# 日志改道 stderr，防污染 stdio JSON-RPC
logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

import numpy as np
from fastmcp import FastMCP
from openai import OpenAI

from servers.common.base import BaseState
from servers.common.envelope import make_envelope
from servers.common.stats import StatsTracker

mcp = FastMCP("plugmem")

_state = BaseState("plugmem")
_stats = StatsTracker()

_CHROMA_DIR = (_state.state_dir / "chroma").resolve()
_META_PATH = (_state.state_dir / "session_meta.json").resolve()

PLUGMEM_REPO = Path(
    os.environ.get("MEMBENCH_PLUGMEM_REPO") or (Path.home() / "Documents" / "repo" / "PlugMem")
).resolve()
if not (PLUGMEM_REPO / "plugmem" / "core" / "memory_graph.py").exists():
    raise RuntimeError(f"上游 PlugMem 仓库不存在: {PLUGMEM_REPO}（用 MEMBENCH_PLUGMEM_REPO 指定）")
sys.path.insert(0, str(PLUGMEM_REPO))

from plugmem.clients.embedding import EmbeddingClient, get_similarity  # noqa: E402
from plugmem.clients.llm import LLMClient  # noqa: E402
from plugmem.core.memory import Memory  # noqa: E402
from plugmem.core.memory_graph import MemoryGraph, _normalize_mode  # noqa: E402
from plugmem.core.value_base import ValueBase  # noqa: E402
from plugmem.core.value_functions import (  # noqa: E402
    ProceduralEqual,
    SemanticEqual,
    SubgoalEqual,
    SubgoalRelevant,
    TagEqual,
    TagRelevant,
)
import plugmem.core.memory_graph as _pm_graph  # noqa: E402
from plugmem.inference.retrieving import get_mode, get_new_subgoal, get_plan  # noqa: E402
from plugmem.inference.structuring import get_return, get_semantic  # noqa: E402
from plugmem.storage.chroma import ChromaStorage  # noqa: E402

import chromadb  # noqa: E402

_REQUIRED = ["MEMBENCH_LLM_API_KEY", "MEMBENCH_LLM_BASE_URL", "MEMBENCH_LLM_MODEL"]
_THINKING = os.environ.get("MEMBENCH_THINKING", "low")        # low | enabled | disabled
_MAX_HOPS = int(os.environ.get("MEMBENCH_PLUGMEM_MAX_HOPS", "2"))   # 论文默认 T_max=2（口径 3）
_REASONING = os.environ.get("MEMBENCH_PLUGMEM_REASONING", "0") == "1"  # B6，默认关（口径 4）
_THETA_EQUAL = float(os.environ.get("MEMBENCH_PLUGMEM_THETA_EQUAL", "0.8"))  # 意图判等（口径 2）
_MAX_TOKENS = int(os.environ.get("MEMBENCH_PLUGMEM_MAX_TOKENS", "8192"))     # 口径 8

# 上游写死的、本臂刻意不动的路由/池参数（口径 5），集中在此便于核查
_SEGMENT_THRESHOLD = 0.75      # memory.py:81，轨迹切段
_EPISODIC_POOL = 30            # memory_graph.py:860，情景模式语义投票池
_SESSION_VOTE_MIN = 3          # memory_graph.py:874，满 3 票搬整段会话原文

_PROBES = {
    "segment_split": 0,        # 切段触发次数（阈值 0.75 在 embedding-3 尺度下的漂移观测）
    "segment_checks": 0,
    "intent_merged": 0,        # 口径 2 的语义判重命中次数
    "intent_new": 0,
    "merge_writeback_fail": 0,  # 合并后文本写回节点失败次数（应恒为 0）
    "hops_used": [],           # 每次 retrieve 实际跳数
    "stop_early": 0,           # MULTI HOP CTRL 判 enough 提前停的次数
}
_TRUNCATED = {"count": 0}      # finish_reason == length（口径 8）
_MODE_COUNT = {"semantic_memory": 0, "episodic_memory": 0, "procedural_memory": 0}
_RESTORED = {"return_scores": 0, "return_nonzero": 0, "action_side_facts": 0}   # 补齐计数


def _check_env() -> None:
    missing = [k for k in _REQUIRED if not os.environ.get(k)]
    if missing:
        raise RuntimeError(
            f"缺少环境变量 {missing}——MCP stdio 子进程不继承父进程环境（见 interface-spec §7）"
        )


# ═══ 内部 LLM / embedding 替身（interface-spec §7 统一配置）═══


class BenchLLM(LLMClient):
    """全 arm 统一 endpoint + temp=0 + thinking 三态（与 mem0 servers/mem0/server.py:167-181 对齐）。

    上游 OpenAICompatibleLLMClient 不带 extra_body 通道，故这里自己实现 LLMClient 接口，
    顺带在同一切点统计 calls / usage / 截断次数。
    """

    def __init__(self) -> None:
        _check_env()
        self.model = os.environ["MEMBENCH_LLM_MODEL"]
        self._client = OpenAI(
            api_key=os.environ["MEMBENCH_LLM_API_KEY"],
            base_url=os.environ["MEMBENCH_LLM_BASE_URL"],
            timeout=180.0,
            max_retries=5,
        )
        self.tokens = 0            # 累计用量，工具层算 delta 分桶（ingest / retrieve / internal_llm）

    def complete(self, messages, temperature: float = 0, top_p: float = 1.0,
                 max_tokens: int = 4096) -> str:
        extra = {"thinking": {"type": "disabled" if _THINKING == "disabled" else "enabled"}}
        if _THINKING == "low":
            extra["reasoning_effort"] = "low"
        r = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0,                      # spec §7：内部 LLM 一律 temp=0，忽略调用方传值
            top_p=top_p,
            max_tokens=max(max_tokens, _MAX_TOKENS),
            extra_body=extra,
        )
        _stats.llm_calls += 1
        if r.usage is not None:
            self.tokens += r.usage.total_tokens
        choice = r.choices[0]
        if getattr(choice, "finish_reason", None) == "length":
            _TRUNCATED["count"] += 1
        return choice.message.content or ""


class BenchEmbedder(EmbeddingClient):
    """embedding-3（口径 7）。带进程内缓存：标签/意图重复率高，缓存显著降成本且不改语义。"""

    def __init__(self) -> None:
        _check_env()
        base = (os.environ.get("MEMBENCH_EMBED_BASE_URL")
                or os.environ["MEMBENCH_LLM_BASE_URL"].replace("/coding", ""))
        key = os.environ.get("MEMBENCH_EMBED_API_KEY") or os.environ["MEMBENCH_LLM_API_KEY"]
        self.model = os.environ.get("MEMBENCH_EMBED_MODEL", "embedding-3")
        self._client = OpenAI(api_key=key, base_url=base, timeout=120.0, max_retries=5)
        self._cache: dict[str, list[float]] = {}
        self.calls = 0
        self.cache_hits = 0
        self.tokens = 0

    def embed(self, text: str) -> list[float]:
        key = (text or "")[:8192]
        if key in self._cache:
            self.cache_hits += 1
            return self._cache[key]
        r = self._client.embeddings.create(model=self.model, input=key or " ")
        self.calls += 1
        if r.usage is not None:
            self.tokens += r.usage.total_tokens
        vec = r.data[0].embedding
        self._cache[key] = vec
        return vec

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


_LLM: BenchLLM | None = None
_EMBED: BenchEmbedder | None = None


def _llm() -> BenchLLM:
    global _LLM
    if _LLM is None:
        _LLM = BenchLLM()
    return _LLM


def _embedder() -> BenchEmbedder:
    global _EMBED
    if _EMBED is None:
        _EMBED = BenchEmbedder()
    return _EMBED


# ═══ 价值函数：最终预算接 top_k（口径 5）═══


class BudgetRelevant(ValueBase):
    """纯相关度 + 预算 K。等价于上游 SemanticRelevant/ProceduralRelevant 的排序语义
    （它们的 importance/recency/return/credibility 分量同样恒 0），差别只在 k 由外部预算给定。
    论文 B4 的 optional importance/recency 未启用——原文是 optionally，属留白而非承诺。"""

    def __init__(self, k: int, value_threshold: float = 0.0):
        self.k = k
        self.value_threshold = value_threshold

    def compute_importance(self, Importance: float) -> float:
        return 0

    def compute_relevance(self, Relevance: float) -> float:
        return Relevance

    def compute_recency(self, Recency: float) -> float:
        return 0

    def compute_return(self, Return: float) -> float:
        return 0

    def compute_credibility(self, Credibility: float) -> float:
        return 0


# ═══ 图管理（每个 scope 一张图；chroma 句柄在 reset/restore 后必须重建）═══

_CLIENT: "chromadb.ClientAPI | None" = None
_STORAGE: ChromaStorage | None = None
_GRAPHS: dict[str, MemoryGraph] = {}
_META: dict | None = None      # session_id → {date, scope, turn_ranges}


def _storage() -> ChromaStorage:
    global _CLIENT, _STORAGE
    if _STORAGE is None:
        _CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _CLIENT = chromadb.PersistentClient(path=str(_CHROMA_DIR))
        # embedding_function 传 None：所有写入都显式带 embedding，检索侧上游全走暴力余弦
        # （paper-vs-code 差异 #18：向量库四个近邻查询方法零调用），chroma 不需要自己算向量。
        _STORAGE = ChromaStorage(client=_CLIENT, embedding_function=None)
    return _STORAGE


def _graph_id(scope_id: str) -> str:
    """chroma collection 名约束：[a-zA-Z0-9._-]，3–63 字符，首尾字母数字。"""
    gid = re.sub(r"[^a-zA-Z0-9_-]", "_", scope_id or "default")
    return f"g_{gid}"[:56]


def _get_graph(scope_id: str) -> MemoryGraph:
    gid = _graph_id(scope_id)
    g = _GRAPHS.get(gid)
    if g is not None:
        return g
    st = _storage()
    st.create_graph(gid)          # get_or_create，幂等
    g = MemoryGraph(
        graph_id=gid, storage=st, llm=_llm(), embedder=_embedder(),
        tag_equal=TagEqual(), tag_relevant=TagRelevant(),
        semantic_equal=SemanticEqual(), semantic_relevant=BudgetRelevant(k=20),
        subgoal_equal=SubgoalEqual(), subgoal_relevant=SubgoalRelevant(),
        procedural_equal=ProceduralEqual(), procedural_relevant=BudgetRelevant(k=20),
    )
    g.load()
    _GRAPHS[gid] = g
    return g


def _default_scope() -> str:
    """retrieve 不带 filter.scope_id 时的回退（smoke 步骤 2/5/7 就是这种调用）。
    优先用已建图，其次从 session 元数据推断——进程重启或 restore 后 _GRAPHS 是空的。"""
    for g in _GRAPHS.values():
        return g.graph_id.removeprefix("g_")
    scopes = [v.get("scope") for v in _meta()["sessions"].values() if v.get("scope")]
    return scopes[0] if scopes else "default"


def _drop_caches() -> None:
    """reset/restore 后必须调用：chroma 按 path 缓存 System 单例，只把变量置 None 不够，
    下次 PersistentClient(同 path) 会拿回指向已删目录的旧实例
    （memory-system-analysis §8.6「持有目录句柄的库必须重建实例」）。"""
    global _CLIENT, _STORAGE, _META
    _GRAPHS.clear()
    try:
        from chromadb.api.shared_system_client import SharedSystemClient
        SharedSystemClient.clear_system_cache()
    except Exception:
        pass
    _CLIENT = None
    _STORAGE = None
    _META = None


def _meta() -> dict:
    global _META
    if _META is None:
        if _META_PATH.exists():
            _META = json.loads(_META_PATH.read_text())
        else:
            _META = {"sessions": {}}
    return _META


def _save_meta() -> None:
    _META_PATH.parent.mkdir(parents=True, exist_ok=True)
    _META_PATH.write_text(json.dumps(_meta(), ensure_ascii=False))


# ═══ A1：对话 turns → PlugMem 轨迹（口径 6）═══

_SPEAKER_RE = re.compile(r"^(?:\[\d{4}-\d{2}-\d{2}\]\s*)?([^:：]{1,40})[:：]\s*")


def _speaker_of(content: str) -> str | None:
    m = _SPEAKER_RE.match(content or "")
    return m.group(1).strip() if m else None


def _sides(turns: list[dict]) -> list[str]:
    """每条 turn 归到 observation 侧还是 action 侧。

    优先用契约里的 role（§2）：user→obs、assistant→act，与上游 LME 脚本一致。
    LoCoMo 把两个 speaker 都标成 role=user（loaders/locomo.py:96），此时回落到
    content 前缀里的说话人名：第一位出现的 → obs 侧，其余 → act 侧（口径 6）。
    """
    roles = {(t.get("role") or "").lower() for t in turns}
    if "assistant" in roles and len(roles) > 1:
        return ["act" if (t.get("role") or "").lower() == "assistant" else "obs" for t in turns]
    speakers = [_speaker_of(t.get("content", "")) for t in turns]
    first = next((s for s in speakers if s), None)
    if first is None:                       # 解析不出说话人：整段按单侧独白处理
        return ["obs"] * len(turns)
    return ["obs" if s == first or s is None else "act" for s in speakers]


def _pair_turns(turns: list[dict]) -> tuple[list[tuple[str, str]], str, list[list[int]], bool]:
    """把对话 turns 折成 PlugMem 的 (action, observation) 序列。

    返回 (pairs, initial_observation, step_ranges, has_tail)：
      pairs[i] = (action_t0, observation_t1) → Memory.append 的第 i 次调用；
      step_ranges[i] = 轨迹第 i 步（observation_i + action_i）覆盖的原始 turn 下标区间。
    上游 Memory.append 在第 i 步记录的是 (observation_i, action_i)，observation_{i+1}
    留到下一步，所以 step_ranges 与 episodic 节点逐个对齐（envelope 的 turn_range 靠它）。
    连续同侧的 turn 合并成一块——上游 LME 脚本遇到这种情况直接抛 ValueError，
    而 LoCoMo 里确实存在同一人连说两条。
    """
    if not turns:
        return [], "", []

    sides = _sides(turns)
    blocks: list[tuple[str, list[int]]] = []
    for i, side in enumerate(sides):
        if blocks and blocks[-1][0] == side:
            blocks[-1][1].append(i)
        else:
            blocks.append((side, [i]))
    if blocks[0][0] == "act":                 # 以 action 开头：补一个空观察，保证交替
        blocks.insert(0, ("obs", []))

    def text_of(idxs: list[int]) -> str:
        return "\n".join((turns[i].get("content") or "").strip() for i in idxs)

    obs_blocks = [idxs for side, idxs in blocks if side == "obs"]
    act_blocks = [idxs for side, idxs in blocks if side == "act"]

    initial_obs = f"User Say: {text_of(obs_blocks[0])}"
    pairs: list[tuple[str, str]] = []
    step_ranges: list[list[int]] = []
    for i, act in enumerate(act_blocks):
        nxt = obs_blocks[i + 1] if i + 1 < len(obs_blocks) else []
        pairs.append((f"Agent Say: {text_of(act)}", f"User Say: {text_of(nxt)}"))
        span = (obs_blocks[i] if i < len(obs_blocks) else []) + act
        step_ranges.append([min(span), max(span)] if span else [0, 0])

    # 收尾步（适配层必要修正，不是论文偏离）：
    # Memory.append 第 i 步存的是 (observation_i, action_i)，传进去的 observation_{i+1}
    # 要等下一步才落到 trajectory——所以会话最后一个 observation 块永远不会被存进轨迹，
    # 也就不会被 get_semantic 抽成命题（上游 LME 脚本同样丢，对话场景下这意味着每段会话
    # 的最后一句话整段丢失；locomo 的 evidence 很可能就在那里，而单 turn 会话会整个变成空图）。
    # 旧做法是补一步占位动作走 append，已废弃（审查 M4）：占位步会多花 3 次标注调用，
    # 它的子目标是对「不回复」的解释、与前一步相似度大概率低于切段阈值，于是多出一个
    # 只含占位步的轨迹段，再产出一条关于「不回复」的处方进程序图（272 段里 140 段会触发）。
    # 现在改为由 _build_memory 直接合成一个 step 写进 trajectory，零 LLM 调用、不产伪段。
    has_tail = len(obs_blocks) > len(act_blocks)
    if has_tail:
        tail = obs_blocks[-1]
        step_ranges.append([min(tail), max(tail)] if tail else [0, 0])

    return pairs, initial_obs, step_ranges, has_tail


def _build_memory(turns: list[dict], session_id: str, date: str | None) -> tuple[Memory, list[list[int]]]:
    """A1+A2：逐步标注 → 切段 → 抽语义/程序。切段阈值观测写进探针（口径 7）。"""
    pairs, initial_obs, ranges, has_tail = _pair_turns(turns)
    time_str = f"Date: {date[:10]}" if date else ""
    mem = Memory(goal="Answer user's question", observation=initial_obs,
                 llm=_llm(), embedder=_embedder(), time=time_str, session_id=session_id)
    n_traj_before = 0
    for action, obs in pairs:
        mem.append(action_t0=action, observation_t1=obs)
        _PROBES["segment_checks"] += 1
        if len(mem.memory["episodic"]) > n_traj_before:     # append 内部触发了切段
            _PROBES["segment_split"] += 1
            n_traj_before = len(mem.memory["episodic"])

    if has_tail:                       # 收尾步：合成写入，不走 append（审查 M4）
        mem.trajectory.append({
            "subgoal": mem.trajectory[-1]["subgoal"] if mem.trajectory else "Wrap up the session",
            "state": mem.state_t0,
            "observation": mem.observation_t0,      # 最后一个 observation 块
            "action": "",
            "reward": "",
            "similarity_subgoal": 1.0,              # 显式标为不切段
            "time": mem.time,
        })

    mem.close()
    _extract_action_side_semantics(mem)
    return mem, ranges


def _extract_action_side_semantics(mem: Memory) -> None:
    """C1 修复：把动作侧话语也抽成命题。

    上游 get_semantic 只读 step["observation"]（inference/structuring.py:73，
    GetSemanticPrompt 的唯一文档槽位也只有 {observation}），动作侧只进情景节点和状态摘要。
    在 LongMemEval 里这没问题——动作侧是助手话语，不是提问对象；但 LoCoMo 是双人对话，
    两个说话人都是提问对象。直接平移上游映射的后果已由对抗审查全量核实
    （2026-09-13）：落在动作侧的 turn 2871/5882 = 48.8%，其中 gold evidence 1355/2806 = 48.3%，
    且开场说话人逐段翻转，所以“被抽到的是哪一半”还是随机的。
    这不是论文机制而是适配层产物，故在这里补齐：逐步对动作侧再抽一次命题，
    结果并进同一批语义层（trajectory_num / turn_num 对齐该步，turn_range 逻辑不变）。
    成本：每步 +1 次抽取调用（约 +25%）。
    """
    llm, embedder = _llm(), _embedder()
    for j, trajectory in enumerate(mem.memory["episodic"]):
        for i, step in enumerate(trajectory):
            action = (step or {}).get("action") or ""
            if not action.strip():
                continue
            for item in get_semantic(llm, {"observation": action}, j, i, mem.time):
                mem.memory["semantic"].append(item)
                mem.memory_embedding["semantic"].append({
                    "semantic_memory": embedder.embed(item["semantic_memory"]),
                    "tags": [embedder.embed(t) for t in item["tags"]],
                })
                _RESTORED["action_side_facts"] += 1


# ═══ A2 补齐：处方质量分（口径 1）═══


def _score_prescriptions(mem: Memory, graph_id: str) -> None:
    for item in mem.memory["procedural"]:
        text = item.get("procedural_memory") or ""
        if not text:
            continue
        score = get_return(_llm(), subgoal=item.get("subgoal", ""), procedural_memory=text,
                           graph_id=graph_id)
        item["return"] = float(score)
        _RESTORED["return_scores"] += 1
        if score:
            _RESTORED["return_nonzero"] += 1


# ═══ A3 补齐：意图语义判重（口径 2）═══


# 合并中转表（审查 M3）：把「被命中的已有意图串」→「原始新意图串」传给上游合并函数。
_PENDING_MERGE: dict[str, str] = {}
_MERGE_RESULT: dict[str, str] = {}
_orig_get_new_subgoal = _pm_graph.get_new_subgoal


def _patched_get_new_subgoal(llm, subgoal_a, subgoal_b, **kw):
    """上游 insert 命中字典分支后会调 get_new_subgoal(旧串, 新串) 做合并改写。
    本臂的语义判重在入图前就把新意图改写成了已有节点的原串，于是上游看到的两个串
    完全相同——论文的「合并改写」退化成「让模型复述一遍旧串」，还把这段复述的向量
    刷回节点（审查 M3：把上游已知的「向量刷了文本没写回」从偶发变成每次命中都发生）。
    这里把真正的新意图串换回去，并记下合并结果供 insert 后把文本写回节点。
    只在本进程的模块命名空间生效，不改上游仓库文件。
    """
    original_new = _PENDING_MERGE.pop(subgoal_a, None)
    merged = _orig_get_new_subgoal(llm, subgoal_a, original_new or subgoal_b, **kw)
    if original_new:
        _MERGE_RESULT[subgoal_a] = merged
    return merged


_pm_graph.get_new_subgoal = _patched_get_new_subgoal


def _writeback_merged_intents(graph: MemoryGraph) -> None:
    """insert 后把合并后的文本写回节点，保证文本与向量一致（修上游差异 #10）。"""
    for old, merged in list(_MERGE_RESULT.items()):
        _MERGE_RESULT.pop(old, None)
        node = graph.subgoal2node.get(old)
        if node is None or not merged or merged == old:
            continue
        node.subgoal = merged
        graph.subgoal2node.pop(old, None)
        graph.subgoal2node[merged] = node
        emb = node.embedding
        if hasattr(emb, "tolist"):
            emb = emb.tolist()
        try:
            graph.storage.update_subgoal(
                graph.graph_id, subgoal_id=node.subgoal_id, subgoal=merged, embedding=emb,
                metadata_updates={"procedural_ids": [p.procedural_id for p in node.procedural_nodes],
                                  "time": node.time},
            )
        except Exception as exc:                     # 持久化失败不该中断 ingest，但要留痕
            _PROBES["merge_writeback_fail"] += 1
            logging.warning("意图合并文本写回失败 %s: %s", node.subgoal_id, exc)


def _merge_intents_semantically(mem: Memory, graph: MemoryGraph) -> None:
    """新意图与图中已有意图算余弦，≥θ_equal 就把字符串改写成已有节点的串，
    从而命中上游 insert 的字典分支并触发它原有的 LLM 合并改写（get_new_subgoal）；
    真正的新意图串通过 _PENDING_MERGE 传给已 patch 的合并函数，不会在半路丢掉。"""
    # 候选池 = 图中已有意图 ∪ 本批已处理过的意图。
    # 本批内部也要两两判重：一次 insert 里的多段轨迹常常抽出近义意图，只比对库存会漏掉它们。
    # （2026-09-12 实测：两段会话入图后 15 个意图的两两相似度最高 0.892，已越过 0.8 阈值却未合并。）
    pool: list[tuple[str, object]] = []
    for node in graph.subgoal_nodes:
        if node.embedding is None:
            node.embedding = _embedder().embed(node.get_subgoal())
        pool.append((node.get_subgoal(), node.embedding))

    for item, emb_item in zip(mem.memory["procedural"], mem.memory_embedding["procedural"]):
        subgoal = item.get("subgoal") or ""
        if not subgoal:
            continue
        if subgoal in graph.subgoal2node:          # 字面完全相同：上游自己就会合并
            continue
        vec = emb_item.get("subgoal") or _embedder().embed(subgoal)
        best_str, best_sim = None, -1.0
        for cand_str, cand_vec in pool:
            sim = get_similarity(vec, cand_vec)
            if sim > best_sim:
                best_str, best_sim = cand_str, sim
        if best_str is not None and best_sim >= _THETA_EQUAL:
            _PENDING_MERGE[best_str] = subgoal      # 原始新意图串交给 patch 后的合并函数
            item["subgoal"] = best_str
            _PROBES["intent_merged"] += 1
        else:
            pool.append((subgoal, vec))            # 成为后续意图的候选
            _PROBES["intent_new"] += 1


# ═══ B2/B3：召回（预算接 top_k，口径 5）═══


def _dense_semantic(graph: MemoryGraph, query_vec, k: int) -> list:
    """全库稠密打分取前 k。返回 [(sim, node)] 降序。情景模式的投票池用它；
    语义模式不再用它充候选池（审查 M1）。"""
    scored = []
    for node in graph.semantic_nodes:
        if not getattr(node, "is_active", True):
            continue
        if node.embedding is None:
            node.embedding = _embedder().embed(node.get_semantic_memory())
        scored.append((float(get_similarity(query_vec, node.embedding)), node))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:k]


def _recall_semantic(graph: MemoryGraph, query: str, tags: list[str], top_k: int) -> list[tuple[float, object]]:
    """两通道候选并集（上游稠密 5 ∪ 标签路由激活）→ 按预算 top_k 重排剪枝。

    只把预算接到契约 top_k，候选池保持上游原样（审查 M1）。
    早前把稠密候选池也扩到 top_k 是错的：最终排序是纯余弦，任何路由进来的节点
    若余弦高于稠密第 k 名就已在稠密 top_k 里，否则排不进——除并列外结果恒等于纯稠密检索，
    论文 B3「高层节点路由激活低层节点」在这条路径上变成了空操作。
    """
    qvec = _embedder().embed(query)
    routed = graph.retrieve_semantic_nodes(
        semantic_memory={"semantic_memory": query, "tags": tags},
        semantic_memory_embedding={"semantic_memory": qvec,
                                   "tags": [_embedder().embed(t) for t in tags]},
        value_func_tag=graph.tag_relevant,
        value_func=BudgetRelevant(k=top_k),
    )
    out: list[tuple[float, object]] = []
    for node in routed:
        if node.embedding is None:
            node.embedding = _embedder().embed(node.get_semantic_memory())
        out.append((float(get_similarity(qvec, node.embedding)), node))
    out.sort(key=lambda x: x[0], reverse=True)
    return out[:top_k]


def _recall_procedural(graph: MemoryGraph, subgoal: str, top_k: int) -> list[tuple[float, object]]:
    nodes = graph.retrieve_procedural_nodes(
        subgoal=subgoal,
        value_func_subgoal=graph.subgoal_relevant,       # 上游默认 k=1/0.1，刻意不动（口径 5）
        # 阈值保留上游 ProceduralRelevant 的 0.1（value_functions.py:176），只改预算（审查 m1）
        value_func=BudgetRelevant(k=top_k, value_threshold=0.1),
    )
    if not nodes:
        return []
    qvec = _embedder().embed(subgoal)
    out = []
    for n in nodes:
        emb = n.embedding if n.embedding is not None else _embedder().embed(n.get_procedural_memory())
        out.append((float(get_similarity(qvec, emb)), n))
    out.sort(key=lambda x: x[0], reverse=True)
    return out


def _recall_episodic(graph: MemoryGraph, query: str, top_k: int) -> tuple[list[tuple[float, object]], list[str]]:
    """情景模式：语义命题投票定位会话，满 3 票的会话回情景原文、不足的回命题文本
    （上游 memory_graph.py:847-880 的二分）。两处适配，均因为上游返回的是一整段拼好的长字符串、
    根本没有「条数预算」这个概念，而契约的 envelope 是逐条的、共用全臂统一的 top_k：

    1) 粒度：满票会话展开成情景节点（一步的观察＋动作）逐条出 envelope，而不是一整段。
    2) 预算与排序：情景节点最多占 top_k 的一半，剩下留给命题；节点分数取「把它投出来的
       命题中的最高相关度」（沿溯源边，零额外 embedding 成本）。
       不这么做的后果已实测：满票会话的全部情景节点会按同一个投票分并列塞满 top_k，
       不同问题拿到几乎相同的证据集，跨题区分度归零，且把命题全部挤出预算。
    """
    qvec = _embedder().embed(query)
    pool = _dense_semantic(graph, qvec, _EPISODIC_POOL)
    votes: dict[str, int] = {}
    sess_best: dict[str, float] = {}
    for sim, node in pool:
        sid = getattr(node, "session_id", None)
        if sid:
            votes[sid] = votes.get(sid, 0) + 1
            sess_best[sid] = max(sess_best.get(sid, 0.0), sim)

    hit_sessions = [s for s, v in votes.items() if v >= _SESSION_VOTE_MIN]

    # 溯源边：命题 → 它所出自的情景节点，命题相关度向下传给情景节点
    ep_score: dict[int, float] = {}
    ep_source: dict[int, tuple[float, object]] = {}      # 情景节点 ← 投出它的最高分命题
    for sim, node in pool:
        if getattr(node, "session_id", None) not in hit_sessions:
            continue
        for ep in getattr(node, "episodic_nodes", []) or []:
            if float(sim) > ep_score.get(ep.episodic_id, -1.0):
                ep_score[ep.episodic_id] = float(sim)
                ep_source[ep.episodic_id] = (float(sim), node)

    ep_budget = max(1, (top_k + 1) // 2) if hit_sessions else 0
    episodic_items: list[tuple[float, object]] = []
    for sid in hit_sessions:
        for ep in graph.session_ids.get(sid, []):
            # 没被命题直接指到的节点仍保留（满票会话要的是上下文连续性），用会话最高分打折兑底，
            # 使它们排在有直接证据的节点之后、其他会话之前。
            episodic_items.append((ep_score.get(ep.episodic_id, sess_best.get(sid, 0.0) * 0.5), ep))
    episodic_items.sort(key=lambda x: x[0], reverse=True)

    # 不足 3 票的会话：退回命题本身（上游同样只回命题文本、不回原文）
    prop_items = [(sim, n) for sim, n in pool
                  if getattr(n, "session_id", None) not in hit_sessions]

    # 情景侧的一半预算是硬上限，命题侧不足时不回填。
    # 实测依据（2026-09-12，2 个 session / 18 个情景节点）：开回填后四道不同的题拿到的
    # 证据集完全相同（Jaccard 1.0，仅排序不同）——预算大于候选总量时，“填满”等于把
    # 整段历史倒给答题 LLM，本臂就退化成了 full_context。不回填时同一批题的
    # Jaccard 降到 0–0.25。top_k 是上限不是下限，宁可少给也不能丢掉跨题区分度；
    # 条数不足由 MODE_LIMITED 上报，不静默。
    ep_take = min(len(episodic_items), ep_budget)

    # 被半预算截掉的情景节点，把投中它的命题回填到命题侧参与排序（审查 M5）。
    # 不回填的后果：满票会话的直接命中节点总数超过半预算时（投票池集中在两三段会话时很常见），
    # 高分证据被丢，命题侧却在用其他会话里相关度更低的候选填满。
    seen_sem = {getattr(n, "semantic_id", None) for _, n in prop_items}
    for _, ep in episodic_items[ep_take:]:
        src = ep_source.get(getattr(ep, "episodic_id", -1))
        if src and getattr(src[1], "semantic_id", None) not in seen_sem:
            prop_items.append(src)
            seen_sem.add(getattr(src[1], "semantic_id", None))
    prop_items.sort(key=lambda x: x[0], reverse=True)

    prop_take = min(len(prop_items), max(0, top_k - ep_take))
    out = episodic_items[:ep_take] + prop_items[:prop_take]
    out.sort(key=lambda x: x[0], reverse=True)
    capped = len(episodic_items) > ep_take
    return out[:top_k], (hit_sessions, capped)


# ═══ B8：MULTI HOP CTRL（口径 3，论文 Listing 10）═══

_HOP_PROMPT = """You are the retrieval controller of a memory system.
Decide whether the retrieved facts are sufficient to answer the question.

Return strict JSON:
{"enough": true/false, "top_node_ids": ["id", ...]}

Constraints:
- top_node_ids length <= {budget}
- top_node_ids must be a subset of available ids, copied verbatim as strings
- if enough=true => top_node_ids=[]

**Question:**
{question}
**Available node ids:**
{available_ids}
**Retrieved facts:**
{facts}"""


def _node_key(node) -> str:
    """跨三类节点唯一的 id。必须带类型前缀（审查 M2）：命题/处方/情景 三类编号各自从 0 起，
    混用纯整数会让多跳控制器选中的情景节点误匹配到同号命题。"""
    for attr, prefix in (("semantic_id", "s"), ("procedural_id", "p"), ("episodic_id", "e")):
        val = getattr(node, attr, None)
        if val is not None:
            return f"{prefix}{val}"
    return "x"


def _hop_control(question: str, items: list[tuple[float, object]], budget: int) -> tuple[bool, list[str]]:
    """返回 (enough, 重点节点 key)。解析失败一律判 enough=True（停跳），不猜。"""
    ids, lines = [], []
    for _, node in items:
        key = _node_key(node)
        ids.append(key)
        lines.append(f"[{key}] {_node_text(node)}"[:400])
    prompt = (_HOP_PROMPT.replace("{budget}", str(budget))
              .replace("{question}", question)
              .replace("{available_ids}", json.dumps(ids))
              .replace("{facts}", "\n".join(lines)))
    raw = _llm().complete(messages=[{"role": "user", "content": prompt}])
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return True, []
    try:
        data = json.loads(m.group(0))
    except Exception:
        return True, []
    enough = bool(data.get("enough", True))
    picked = [str(x) for x in (data.get("top_node_ids") or []) if str(x) in ids]
    return enough, picked[:budget]


# 适配层给轨迹加的角色前缀，不应进 envelope（审查 m3）：LoCoMo 两个说话人都是用户，
# “Agent Say” 这个标签会误导答题模型；而且这是本臂独有的装饰，占用 600 字符预算。
_ROLE_PREFIX = re.compile(r"(?m)^\s*(?:User Say|Agent Say)\s*:\s*")


def _node_text(node) -> str:
    for attr in ("get_semantic_memory", "get_procedural_memory"):
        fn = getattr(node, attr, None)
        if callable(fn):
            return fn() or ""
    fn = getattr(node, "get_episodic_memory", None)
    if callable(fn):
        return _ROLE_PREFIX.sub("", fn(date=False) or "").strip()
    return str(node)


# ═══ envelope 渲染 ═══


def _session_meta(session_id: str | None) -> dict:
    if not session_id:
        return {}
    return _meta()["sessions"].get(session_id, {})


def _turn_range_for(node) -> list[int] | None:
    sid = getattr(node, "session_id", None)
    meta = _session_meta(sid)
    ranges = meta.get("turn_ranges") or []
    if not ranges:
        return None
    eps = getattr(node, "episodic_nodes", None)
    if eps is None and hasattr(node, "episodic_id"):
        eps = [node]
    if not eps:
        return None
    idxs = []
    for ep in eps:
        sid_ep = getattr(ep, "session_id", None)
        if sid_ep != sid:
            continue
        order = _meta()["sessions"].get(sid_ep, {}).get("episodic_ids") or []
        if ep.episodic_id in order:
            pos = order.index(ep.episodic_id)
            if pos < len(ranges):
                idxs += ranges[pos]
    return [min(idxs), max(idxs)] if idxs else None


def _to_envelope(score: float, node, mode: str) -> dict:
    sid = getattr(node, "session_id", None)
    meta = _session_meta(sid)
    ts = meta.get("date")
    text = _node_text(node)
    if mode == "procedural_memory":
        nid = f"proc_{node.procedural_id}"
        # 质量分放在格式标注里，不进证据正文（审查 m3）：它是本臂的可观测量（口径 1），
        # 不是要喂给答题模型的证据，也不应占用 600 字符预算。
        raw = f"plugmem_prescription(q={getattr(node, 'Return', 0.0):.0f})"
    elif mode == "episodic_memory" and hasattr(node, "episodic_id"):
        nid = f"epis_{node.episodic_id}"
        raw = "plugmem_episode"
    else:
        nid = f"sem_{getattr(node, 'semantic_id', 'x')}"
        raw = "plugmem_proposition"
    return make_envelope(
        memory_id=nid, text=text, session_id=sid, turn_range=_turn_range_for(node),
        timestamp=ts, score=round(float(score), 4), raw_format=raw,
    )


# ═══ 六工具 ═══


@mcp.tool
def add_conversation(session_id: str, turns: list[dict], scope: dict,
                     metadata: dict | None = None) -> dict:
    """灌入一段会话：对话折成轨迹 → 逐步标注切段 → 抽命题/处方 → 处方打分 → 意图语义归并 → 入图。"""
    t0 = time.perf_counter()
    scope_id = (scope or {}).get("id") or "default"
    graph = _get_graph(scope_id)
    date = next((t.get("timestamp") for t in turns if t.get("timestamp")), None)
    llm0, emb0 = _llm().tokens, _embedder().tokens

    n_ep_before = len(graph.episodic_nodes)
    mem, ranges = _build_memory(turns, session_id, date)
    _score_prescriptions(mem, graph.graph_id)                 # 口径 1
    _merge_intents_semantically(mem, graph)                   # 口径 2
    graph.insert(mem)
    _writeback_merged_intents(graph)                          # 合并后文本写回节点（审查 M3）

    new_ep_ids = [n.episodic_id for n in graph.episodic_nodes[n_ep_before:]]
    _meta()["sessions"][session_id] = {
        "date": date, "scope": scope_id, "turn_ranges": ranges,
        "episodic_ids": new_ep_ids, "n_turns": len(turns),
    }
    _save_meta()
    _stats.n_sessions += 1
    llm_d, emb_d = _llm().tokens - llm0, _embedder().tokens - emb0
    _stats.add_tokens("ingest", llm_d + emb_d)
    _stats.add_tokens("internal_llm", llm_d)

    n_sem = len(mem.memory["semantic"])
    n_proc = len([p for p in mem.memory["procedural"] if p.get("procedural_memory")])
    return {
        "accepted_turns": len(turns),
        "native_notes": (f"plugmem: {len(mem.memory['episodic'])} 段轨迹 / {n_sem} 命题 / "
                         f"{n_proc} 处方，{time.perf_counter() - t0:.1f}s"),
    }


@mcp.tool
def retrieve(query: str, query_mode: str = "fixed", top_k: int = 5,
             filter: dict | None = None) -> dict:
    """B1 选型+抽象 → B2/B3 两通道召回 → B4 按预算重排 → B8 多跳（默认 T_max=2）。"""
    t0 = time.perf_counter()
    notes: list[str] = []
    scope_id = (filter or {}).get("scope_id") or _default_scope()
    if filter and any(k in filter for k in ("before_timestamp", "session_ids")):
        notes.append("FILTER_IGNORED")
    graph = _get_graph(scope_id)
    llm0, emb0 = _llm().tokens, _embedder().tokens

    # B1：记忆类型三选一 + 抽象查询（只读 query，不读记忆内容）
    # 用上游 _normalize_mode：LLM 常回 "## episodic_memory" 这类带 markdown 标记的串，
    # 自己做等值判断会把它们全部误归到兵家的 semantic 兜底分支。
    mode = _normalize_mode(get_mode(_llm(), observation=query, task_type="assistant for user",
                                    graph_id=graph.graph_id))
    _MODE_COUNT[mode] += 1
    # 情景模式不用标签也不用下一步意图（_recall_episodic 只吃 query），跳过这次调用
    # 不改变行为，只省成本；上游无条件调是因为它把三个模式走同一个入口（审查 m10）。
    if mode == "episodic_memory":
        next_subgoal, query_tags = "", []
    else:
        next_subgoal, query_tags = get_plan(_llm(), goal="Answer user's question", subgoal=None,
                                            state=None, observation=query, graph_id=graph.graph_id)

    hop_query = query
    items: list[tuple[float, object]] = []
    hops = 0
    hit_sessions: list[str] = []
    episodic_capped = False
    for hop in range(max(1, _MAX_HOPS)):
        hops = hop + 1
        if mode == "procedural_memory":
            fresh = _recall_procedural(graph, next_subgoal or hop_query, top_k)
        elif mode == "episodic_memory":
            fresh, (hit_sessions, episodic_capped) = _recall_episodic(graph, hop_query, top_k)
        else:
            fresh = _recall_semantic(graph, hop_query, query_tags, top_k)

        seen = {id(n) for _, n in items}
        items += [(s, n) for s, n in fresh if id(n) not in seen]
        items.sort(key=lambda x: x[0], reverse=True)
        items = items[:top_k]

        if hops >= max(1, _MAX_HOPS) or not items:
            break
        enough, picked = _hop_control(query, items, top_k)   # 读记忆内容 → active retrieval
        if enough:
            _PROBES["stop_early"] += 1
            break
        # 用带类型前缀的 key 匹配（审查 M2）：旧实现用 semantic_id/procedural_id 取值，
        # 情景节点两个属性都没有，focus 恒为空——而情景模式正是 LoCoMo 上的主路径，
        # 于是第二跳变成重复查一遍，只花钱不出效。
        focus = [n for _, n in items if _node_key(n) in picked]
        hop_query = query + "\n" + "\n".join(_node_text(n)[:300] for n in focus)  # 论文默认纯拼接
        if mode != "episodic_memory":
            # 程序模式的第二跳必须用新意图，否则查询字面与第一跳相同（审查 M2）
            next_subgoal, query_tags = get_plan(
                _llm(), goal="Answer user's question", subgoal=next_subgoal,
                state=None, observation=hop_query, graph_id=graph.graph_id)

    _PROBES["hops_used"].append(hops)
    results = [_to_envelope(s, n, mode) for s, n in items]

    notes.append(f"mode={mode}")
    notes.append(f"hops={hops}/{_MAX_HOPS}")
    if query_tags:
        notes.append("tags=" + ",".join(query_tags[:5]))
    if mode == "episodic_memory" and hit_sessions:
        notes.append(f"session_vote_hits={len(hit_sessions)}")
    # 条数不足的三种原因分开上报（审查 m5），否则逐题截断统计不可解释。
    # 三者都不是分数阈值截断（本臂检索侧无分数阈值），故不用 TRUNCATED_BELOW_TOP_K。
    if len(results) < top_k:
        if episodic_capped:
            notes.append("EPISODIC_CAP")          # 情景侧撞上半预算硬上限
        elif mode == "procedural_memory":
            notes.append("PROC_SINGLE_INTENT")    # 单意图路由下处方本来就少
        else:
            notes.append("MODE_LIMITED")          # 该类型可用节点确实不足

    if _REASONING:                            # B6，默认关（口径 4）
        joined = "\n".join(e["text"] for e in results)
        compressed = _llm().complete(messages=[{"role": "user", "content":
            f"Compress the following memories into one compact, actionable guidance "
            f"for answering the question. Keep all facts needed.\n\nQuestion: {query}\n\n{joined}"}])
        notes.append("reasoning_text=" + compressed.replace("\n", " ")[:500])

    llm_d, emb_d = _llm().tokens - llm0, _embedder().tokens - emb0
    _stats.add_tokens("retrieve", llm_d + emb_d)
    _stats.add_tokens("internal_llm", llm_d)
    return {
        "results": results, "query_used": query, "query_mode": query_mode,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
        "native_notes": "; ".join(notes),
    }


def _count_memories() -> int:
    """从 chroma 直接数（审查 m6）：只数进程内已加载的图会让 restore 或重启后恒为 0。"""
    try:
        client = _storage()._client
        total = 0
        for coll in client.list_collections():
            name = getattr(coll, "name", None) or str(coll)
            if name.endswith(("_semantic", "_procedural", "_episodic")):
                total += client.get_collection(name).count()
        return total
    except Exception:                               # chroma 不可用时回退到进程内计数
        return sum(len(g.semantic_nodes) + len(g.procedural_nodes) + len(g.episodic_nodes)
                   for g in _GRAPHS.values())


@mcp.tool
def reset() -> dict:
    """清空全部状态（chroma 目录 + session 元数据 + 进程内图缓存）。幂等。"""
    n = _count_memories()
    _drop_caches()
    _state.hard_reset_dir()
    _CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    for k, v in list(_PROBES.items()):
        _PROBES[k] = [] if isinstance(v, list) else 0
    _TRUNCATED["count"] = 0
    for k in _MODE_COUNT:
        _MODE_COUNT[k] = 0
    for k in _RESTORED:
        _RESTORED[k] = 0
    _stats.mark_reset()
    _stats.n_sessions = 0
    return {"ok": True, "cleared": {"memories": n, "system": "plugmem"}}


@mcp.tool
def stats() -> dict:
    d = _stats.to_dict(n_memories=_count_memories())
    emb = _EMBED
    d["embedding"] = {
        "model": os.environ.get("MEMBENCH_EMBED_MODEL", "embedding-3"),
        "calls": emb.calls if emb else 0,
        "cache_hits": emb.cache_hits if emb else 0,
        "tokens": emb.tokens if emb else 0,
    }
    hops = _PROBES["hops_used"]
    d["threshold_probes"] = {                      # 口径 7：embedding-3 尺度漂移观测
        "segment_split": _PROBES["segment_split"],
        "segment_checks": _PROBES["segment_checks"],
        "intent_merged": _PROBES["intent_merged"],
        "intent_new": _PROBES["intent_new"],
        "stop_early": _PROBES["stop_early"],
        "hops_mean": round(sum(hops) / len(hops), 2) if hops else None,
    }
    d["paper_restored"] = {                        # 口径 1/2/3 的补齐是否真的在跑
        "return_scores": _RESTORED["return_scores"],
        "return_nonzero": _RESTORED["return_nonzero"],
        "action_side_facts": _RESTORED["action_side_facts"],   # 动作侧补抽出的命题数（C1）
        "max_hops": _MAX_HOPS,
        "reasoning_module": _REASONING,
        "theta_equal": _THETA_EQUAL,
    }
    d["mode_counts"] = dict(_MODE_COUNT)
    d["truncated_completions"] = _TRUNCATED["count"]   # 口径 8
    d["thinking"] = _THINKING
    d["retrieval_face"] = "active" if _MAX_HOPS > 1 else "query_understanding_only"
    return d


@mcp.tool
def snapshot(tag: str) -> dict:
    r = _state.snapshot(tag)
    _stats.snapshots = _state.tags()
    return r


@mcp.tool
def restore(tag: str) -> dict:
    r = _state.restore(tag)
    _drop_caches()          # 必须：chroma 句柄指向旧目录，不重建会读到脏状态
    _CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    _stats.snapshots = _state.tags()
    if not r.get("ok"):
        r["error"] = r.get("error", "SNAPSHOT_FAILED")
    return r


if __name__ == "__main__":
    mcp.run()  # stdio

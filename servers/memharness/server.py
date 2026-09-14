# memharness：MemHarness（Wu 2026, arXiv:2607.28272）的 LoCoMo 静态 forced-call 封装。
#
# 论文一号机制是「记忆是重构的，不是复现的」：检索命中之后、真正使用之前，插入一次独立的模型调用，
# 把历史经验改写成贴合当前情境的 guidance；判定不适用时输出 <EMPTY> 整条丢弃。本臂完整保留这一步，
# 因此 retrieve 路径会读记忆内容并调 LLM —— 属 active retrieval，与 intent Tier2 同类，
# 成本与延迟不可与零 LLM 检索面（mock/rag_baseline/mem0/graphiti/mandol/memos）并列（interface-spec §7）。
#
# 不复现的部分：GRPO 训练层与效用闭环。LoCoMo forced-call 下没有 episode success 信号，
# 「取用后任务是否成功」拿不到，效用分只能退化成常数，故剪枝默认关闭（与上游基础默认一致）。
# 详细口径决策与判据见同目录 REPRO-NOTES.md，论文↔上游↔本臂三列对照见 paper-vs-code.md。
#
# 存储：memories.jsonl（(situation, principle) 二元组 + 溯源 + 效用计数）+ vectors.npy（principle 向量）。
# 检索后端用 numpy 暴力余弦，与上游 Milvus-Lite 的 FLAT+COSINE 数学等价（FLAT 即穷举），
# 避免引入 Milvus 依赖和 code-architecture §5 记录的多进程写入竞态未验证问题。
#
# 环境变量：
#   必需 MEMBENCH_LLM_API_KEY / MEMBENCH_LLM_BASE_URL / MEMBENCH_LLM_MODEL
#   可选 MEMBENCH_EMBED_BASE_URL / _API_KEY / _MODEL（默认从 LLM 端点推导，去掉 /coding）
#   可选 MEMBENCH_THINKING（low|enabled|disabled，默认 low，映射与 mem0 对齐）
#   可选 MEMBENCH_MEMHARNESS_ADAPTOR（on|off，默认 on；off = 论文 Table 2「w/o reconstruction」消融）
#   可选 MEMBENCH_MEMHARNESS_RECON_TOP_K（默认 0=对全部命中重构；设 1 复现上游 retrieval_top_k 默认）
#   可选 MEMBENCH_MEMHARNESS_ADAPTOR_CONCURRENCY（默认 12，单次 retrieve 内的重构并发度）
#   可选 MEMBENCH_MEMHARNESS_DISTILL_STYLE（conversational|agentic，默认 conversational）
#   可选 MEMBENCH_MEMHARNESS_MAX_PAIRS（默认 8；注意这是偏离项，上游实际取 1，见下方 _max_pairs）
#   可选 MEMBENCH_MEMHARNESS_INSERT_DEDUPE / _RETRIEVAL_DEDUPE（默认 0.85，设 none 关闭）

import json
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 让 servers.common 可导入

from fastmcp import FastMCP
from openai import OpenAI

from servers.common.base import BaseState
from servers.common.envelope import make_envelope
from servers.common.stats import StatsTracker

# 臂名可覆盖：消融臂（server_noadapt.py）需要独立的状态目录与快照命名空间，
# 否则两臂共用 .state/memharness 会互相覆盖。
ARM = os.environ.get("MEMBENCH_MEMHARNESS_ARM", "memharness")

mcp = FastMCP(ARM)

_state = BaseState(ARM)
_stats = StatsTracker()
_MEM_FILE = _state.state_dir / "memories.jsonl"
_VEC_FILE = _state.state_dir / "vectors.npy"

_REQUIRED = ["MEMBENCH_LLM_API_KEY", "MEMBENCH_LLM_BASE_URL", "MEMBENCH_LLM_MODEL"]

# ---------------------------------------------------------------------------
# 上游 prompt（逐字照抄处已标注来源行；域迁移处见 REPRO-NOTES 决策 4）
# ---------------------------------------------------------------------------

# 重构 prompt 与上游逐字一致：verl/trainer/config/ppo_trainer.yaml:691-696（system_prompt）
# 与 :697-712（user_message_template + Output rules）。这两段本身与任务域无关，无需改写。
ADAPTOR_SYSTEM_PROMPT = (
    "You adapt a retrieved memory principle into a concise reusable guidance for the CURRENT "
    "situation and initial task, or output exactly <EMPTY> if the principle does not apply. "
    "Do not write chain-of-thought, first-person reasoning, or a step-by-step action plan."
)

ADAPTOR_USER_TEMPLATE = """Initial task:
{task}

Current situation (state):
{s_curr}

Retrieved historical state:
{s_old}

Historical principle (memory):
{p_old}

Output rules:
- Output exactly one short adapted principle, or exactly <EMPTY>.
- Write in imperative or neutral guidance style.
- Do NOT use first person ("I", "my", "we") or phrases like "therefore", "I need to", "since".
- Do NOT explain your reasoning or describe multiple next steps.
"""

# forced-call 下 {task} 的取值：上游是 ALFWorld/WebShop 的初始任务描述，本臂是 benchmark 的任务定义。
ADAPTOR_TASK_DESCRIPTION = (
    "Answer questions about a long-running multi-session conversation between two people, "
    "using evidence recalled from that conversation history."
)

# 蒸馏 prompt（对话域）：保留上游 compact schema 的 JSON 形状与 situation/memory 二元结构
# （experience_summarizer.py:96-128），只替换域描述——上游的 "advice / what to do or check" 和
# "<think>/<action>/<memory_retrieve>" 在对话语料里没有对应物。判据见 REPRO-NOTES 决策 4。
DISTILL_SYSTEM_CONVERSATIONAL = """You are a JSON-only memory extractor.

Read a completed conversation session and write reusable memories for answering future questions about it.

Critical rules:
- Return exactly one JSON object and nothing else.
- Do not continue the conversation.
- Do not write thoughts, markdown, XML tags, or explanations.
- Each memory must be grounded in the conversation and useful later."""

DISTILL_USER_CONVERSATIONAL = """Benchmark: "{task_name}".

Task: extract at most {num_memories} reusable memories from the completed conversation session below.

Return only this JSON shape:
{{
  "memories": [
    {{
      "situation": "one short sentence describing when this memory applies",
      "memory": "one short self-contained sentence stating what is true and worth recalling"
    }}
  ]
}}

Field rules:
- situation: generalized topic or precondition under which this memory becomes relevant, not a dialogue dump.
- memory: a self-contained statement a future reader must know to answer questions about this
  conversation — concrete facts, commitments, preferences, plans, events, relationships and their
  dates. Keep speaker names and dates that appear in the session. Not a recap of the dialogue flow.
- If no useful memory exists, return {{"memories": []}}.

Conversation session:
{trajectory_text}
"""

# 蒸馏 prompt（上游原版，逐字照抄 experience_summarizer.py:96-128）。
# 保留它是为了能跑「域迁移代价」的对照：MEMBENCH_MEMHARNESS_DISTILL_STYLE=agentic。
DISTILL_SYSTEM_AGENTIC = """You are a JSON-only memory extractor.

Read a completed agent trajectory and write reusable advice for future similar states.

Critical rules:
- Return exactly one JSON object and nothing else.
- Do not continue the trajectory.
- Do not write thoughts, actions, markdown, XML tags, or explanations.
- Do not copy raw <think>, <action>, or <memory_retrieve> text.
- Each memory must be grounded in the trajectory and useful later."""

DISTILL_USER_AGENTIC = """Benchmark: "{task_name}".

Task: extract at most {num_memories} reusable memories from the completed trajectory below.

Return only this JSON shape:
{{
  "memories": [
    {{
      "situation": "one short sentence describing when this advice applies",
      "memory": "one short sentence describing what to do or check"
    }}
  ]
}}

Field rules:
- situation: generalized state or precondition, not a full observation dump.
- memory: reusable advice, not a recap and not a next action command.
- If no useful memory exists, return {{"memories": []}}.

Trajectory:
{trajectory_text}
"""

# 上游 mem_adaptor.empty_output_markers（ppo_trainer.yaml:631-633）
EMPTY_MARKERS = ("<EMPTY>", "<empty>")
# 上游 _normalize_adaptor_output（mem_adaptor_rollout.py:88-92）：吐回 agent 协议标签同样判 reject
AGENT_PROTOCOL_RE = re.compile(r"<\s*(?:redacted_thinking|action|memory_retrieve|memory)\b", re.IGNORECASE)

MAX_TRAJECTORY_CHARS = 32000  # 蒸馏 prompt 软上限（上游未设；LoCoMo 单 session 远低于此，仅防御）
ADAPTOR_MAX_PROMPT_CHARS = 12000  # 上游 mem_adaptor.max_prompt_chars（ppo_trainer.yaml:669）
ADAPTOR_MAX_NEW_TOKENS = 256  # 上游 mem_adaptor.max_new_tokens（ppo_trainer.yaml:668）


def _adaptor_max_tokens() -> int:
    """默认低档思考时沿用上游的 256；调高思考档位时必须提额度。
    思考与正式回复共用额度，256 在高档下会被思考吃光，产生的空输出会被误判为「模型拒绝」
    （同 graphiti/amem 的 128k 防线先例，只是此处取更保守的值）。"""
    return ADAPTOR_MAX_NEW_TOKENS if os.environ.get("MEMBENCH_THINKING", "low").strip().lower() == "low" else 8192


def _log(msg: str) -> None:
    """stdio 是 MCP 的 JSONRPC 通道，任何日志必须走 stderr。"""
    print(f"[memharness] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# 配置读取
# ---------------------------------------------------------------------------


def _env_float_or_none(key: str, default: float) -> float | None:
    raw = os.environ.get(key)
    if raw is None:
        return default
    if raw.strip().lower() in ("none", "null", "off", ""):
        return None
    return float(raw)


def _adaptor_on() -> bool:
    return os.environ.get("MEMBENCH_MEMHARNESS_ADAPTOR", "on").strip().lower() not in ("off", "false", "0")


def _recon_top_k() -> int:
    """0 = 对全部命中重构（本臂默认，见 REPRO-NOTES 决策 3）；>0 = 只重构前 n 条（上游默认 1）。"""
    return int(os.environ.get("MEMBENCH_MEMHARNESS_RECON_TOP_K", "0"))


def _distill_style() -> str:
    s = os.environ.get("MEMBENCH_MEMHARNESS_DISTILL_STYLE", "conversational").strip().lower()
    return "agentic" if s == "agentic" else "conversational"


def _max_pairs() -> int:
    """每段会话蒸馏几条。这是已声明的偏离项，不是上游默认值。

    上游实际送进提示词的是 `max(1, min(num_memories_per_trajectory, max_pairs_per_episode))`
    = `min(1, 8)` = 1（experience_summarizer.py:1202-1203，ppo_trainer.yaml:416/423，两个训练脚本均未覆盖）；
    8 只是硬上限。本臂取 8 的理由：上游一条轨迹 = 一个单一任务，一条经验足够；
    LoCoMo 一个 session 是 15-35 轮多话题对话，取 1 会让全库只剩百条量级。
    详见 REPRO-NOTES 决策 11。要复现上游口径设 MEMBENCH_MEMHARNESS_MAX_PAIRS=1。
    """
    return int(os.environ.get("MEMBENCH_MEMHARNESS_MAX_PAIRS", "8"))


def _insert_dedupe_threshold() -> float | None:
    return _env_float_or_none("MEMBENCH_MEMHARNESS_INSERT_DEDUPE", 0.85)


def _retrieval_dedupe_threshold() -> float | None:
    return _env_float_or_none("MEMBENCH_MEMHARNESS_RETRIEVAL_DEDUPE", 0.85)


# 上游 memory_text_retrieval_dedupe_prefetch_limit（ppo_trainer.yaml:487）：去重前先多取一些候选
_DEDUPE_PREFETCH_MIN = 10


def _missing_env() -> list[str]:
    return [k for k in _REQUIRED if not os.environ.get(k)]


# 客户端单例：全量 run 的重构调用量在十万量级，每次新建 OpenAI 实例会反复创建连接池与 fd
_LLM_SINGLETON: OpenAI | None = None
_EMBED_SINGLETON: OpenAI | None = None


def _llm_client() -> OpenAI:
    global _LLM_SINGLETON
    if _LLM_SINGLETON is None:
        missing = _missing_env()
        if missing:
            raise RuntimeError(f"缺少环境变量 {missing}——MCP stdio 子进程不继承父进程环境（见 interface-spec §7）")
        _LLM_SINGLETON = OpenAI(
            api_key=os.environ["MEMBENCH_LLM_API_KEY"], base_url=os.environ["MEMBENCH_LLM_BASE_URL"]
        )
    return _LLM_SINGLETON


def _embed_client() -> OpenAI:
    global _EMBED_SINGLETON
    if _EMBED_SINGLETON is None:
        missing = [k for k in ("MEMBENCH_LLM_API_KEY", "MEMBENCH_LLM_BASE_URL") if not os.environ.get(k)]
        if missing:
            raise RuntimeError(f"缺少环境变量 {missing}——MCP stdio 子进程不继承父进程环境（见 interface-spec §7）")
        # embedding 走智谱普通通道：coding 通道无 embedding-3 权限（同 rag_baseline）
        base = os.environ.get("MEMBENCH_EMBED_BASE_URL") or os.environ["MEMBENCH_LLM_BASE_URL"].replace("/coding", "")
        key = os.environ.get("MEMBENCH_EMBED_API_KEY") or os.environ["MEMBENCH_LLM_API_KEY"]
        _EMBED_SINGLETON = OpenAI(api_key=key, base_url=base)
    return _EMBED_SINGLETON


def _thinking_extra_body() -> dict:
    """thinking 三态映射与 mem0 对齐（servers/mem0/server.py:167-181）：
    low（默认）= thinking enabled + reasoning_effort=low；enabled = 服务端默认深度；disabled = 关思考。
    """
    mode = os.environ.get("MEMBENCH_THINKING", "low").strip().lower()
    extra: dict[str, object] = {"thinking": {"type": "disabled" if mode == "disabled" else "enabled"}}
    if mode == "low":
        extra["reasoning_effort"] = "low"
    return extra


_RETRY_MAX = 4  # 首次 + 3 次重试
_retry_count = 0  # 退避重试累计，跑完看它判断并发是否偷高


def _is_retryable(exc: Exception) -> bool:
    """限流、服务端 5xx 与连接失败可重试；参数错误、鉴权失败这类不重试。"""
    name = type(exc).__name__
    if name in ("RateLimitError", "APIConnectionError", "APITimeoutError", "InternalServerError"):
        return True
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and (status == 429 or status >= 500)


def _chat(system: str, user: str, max_tokens: int) -> tuple[str, int, str]:
    """一次内部 LLM 调用，返回 (文本, 总 token, finish_reason)。temperature=0 是 interface-spec §7 硬要求。

    finish_reason 必须回传：重构的 max_tokens=256 是上游原值，一旦思考档位调高就可能被截断，
    而截断后的空输出会与「模型判定不适用」不可区分，使拒绝率失真。

    限流退避：本臂每题要发 top_k 次重构调用，是其他臂的十几到二十倍，不退避会在长跑里
    因一次瞬时 429 而中断整个 run（实测并发 12 时出现）。退避只处理可恢复的错误，
    耗尽后仍然上抛——不把失败静默地变成「模型判定不适用」。
    """
    last: Exception | None = None
    for attempt in range(_RETRY_MAX):
        try:
            r = _llm_client().chat.completions.create(
                model=os.environ["MEMBENCH_LLM_MODEL"],
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0,
                max_tokens=max_tokens,
                extra_body=_thinking_extra_body(),
            )
            text = (r.choices[0].message.content or "").strip()
            used = int(r.usage.total_tokens) if r.usage else 0
            return text, used, str(r.choices[0].finish_reason or "")
        except Exception as exc:
            last = exc
            if attempt == _RETRY_MAX - 1 or not _is_retryable(exc):
                raise
            delay = (2**attempt) * 2 + random.uniform(0, 1)  # 2/4/8 秒 + 抖动，避免整批同步重试
            global _retry_count
            _retry_count += 1
            _log(f"可恢复错误，{delay:.1f}s 后重试（{attempt + 1}/{_RETRY_MAX - 1}）：{type(exc).__name__}")
            time.sleep(delay)
    raise last if last else RuntimeError("unreachable")


def _embed(texts: list[str]) -> tuple[list[list[float]], int]:
    model = os.environ.get("MEMBENCH_EMBED_MODEL", "embedding-3")
    r = _embed_client().embeddings.create(model=model, input=texts)
    return [d.embedding for d in r.data], int(r.usage.total_tokens)


# ---------------------------------------------------------------------------
# 存储读写
# ---------------------------------------------------------------------------


def _load_records() -> list[dict]:
    if not _MEM_FILE.exists():
        return []
    return [json.loads(line) for line in _MEM_FILE.read_text().splitlines() if line.strip()]


def _save_records(records: list[dict]) -> None:
    """原子写：records 与 vectors 是两个文件，崩在中间会造成行序错位且难以发现。"""
    _MEM_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _MEM_FILE.with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records))
    os.replace(tmp, _MEM_FILE)


def _load_vecs() -> np.ndarray | None:
    if _VEC_FILE.exists():
        return np.load(_VEC_FILE)
    return None


def _save_vecs(arr: np.ndarray | None) -> None:
    if arr is None or len(arr) == 0:
        if _VEC_FILE.exists():
            _VEC_FILE.unlink()
        return
    _VEC_FILE.parent.mkdir(parents=True, exist_ok=True)
    # 临时名必须以 .npy 结尾：np.save 会给非 .npy 路径自动追加后缀，使 os.replace 找不到源文件
    tmp = _VEC_FILE.with_name(_VEC_FILE.stem + ".tmp.npy")
    np.save(tmp, arr)
    os.replace(tmp, _VEC_FILE)


def _commit(records: list[dict], vecs: np.ndarray) -> None:
    """记录与向量必须成对落盘。先把两份都写成临时文件，再连续替换，
    把失败窗口压到两次 rename 之间（不涉 IO）。否则写完一个文件就失败会留下行序错位的脏状态，
    而错位会让检索静默归因到错误记忆上。"""
    if len(records) != len(vecs):
        raise RuntimeError(f"拒绝写入不一致状态：records({len(records)}) != vectors({len(vecs)})")
    _MEM_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_r = _MEM_FILE.with_suffix(".jsonl.tmp")
    tmp_v = _VEC_FILE.with_name(_VEC_FILE.stem + ".tmp.npy")
    tmp_r.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records))
    np.save(tmp_v, vecs)
    os.replace(tmp_r, _MEM_FILE)
    os.replace(tmp_v, _VEC_FILE)


# 阈值探针：embedding 从上游 BGE-M3 换成 embedding-3 后，0.85 这两条线的尺度会漂，
# 逐次观测触发率（同 atommem 的 threshold_probes 做法）。纯观测，不改任何判定。
_probes: dict[str, dict[str, float | int]] = {
    "insert_dedupe_0.85": {"evaluated": 0, "fired": 0, "max_top1": 0.0, "sum_top1": 0.0},
    "retrieval_dedupe_0.85": {"evaluated": 0, "fired": 0, "max_top1": 0.0, "sum_top1": 0.0},
}
# 重构层观测：论文 Table 4(a) / Figure 3 的核心指标就是拒绝率
_adaptor_counters: dict[str, int] = {
    "evaluated": 0,
    "rejected": 0,
    "api_fail": 0,
    "accepted": 0,
    "identical": 0,
    "truncated": 0,  # finish_reason=length：截断输出会被当成正常 guidance 或误判为拒绝
}


def _reset_probes() -> None:
    global _retry_count
    for p in _probes.values():
        p.update({"evaluated": 0, "fired": 0, "max_top1": 0.0, "sum_top1": 0.0})
    for k in _adaptor_counters:
        _adaptor_counters[k] = 0
    _retry_count = 0


def _note_probe(name: str, top1: float, fired: bool) -> None:
    """只在真有候选可比时记录。候选池为空时 top1 恒为 0，计入会系统性拉低均值，
    让「阈值尺度漂移」这个观测目标失真。"""
    p = _probes[name]
    p["evaluated"] = int(p["evaluated"]) + 1
    p["sum_top1"] = float(p["sum_top1"]) + top1
    p["max_top1"] = max(float(p["max_top1"]), top1)
    if fired:
        p["fired"] = int(p["fired"]) + 1


def _cosine_matrix(vecs: np.ndarray, qv: np.ndarray) -> np.ndarray:
    a_n = vecs / np.clip(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-12, None)
    q_n = qv / max(float(np.linalg.norm(qv)), 1e-12)
    return a_n @ q_n


def _greedy_dedupe(vecs: np.ndarray, order: list[int], threshold: float) -> list[int]:
    """上游 dedupe_indices_by_embedding_similarity 的向量化等价：keep-first 贪心，>= 阈值即丢。"""
    kept: list[int] = []
    kept_vecs: list[np.ndarray] = []
    for i in order:
        v = vecs[i]
        n = max(float(np.linalg.norm(v)), 1e-12)
        vn = v / n
        if not kept_vecs:  # 首条无可比对象，不计入探针
            kept.append(i)
            kept_vecs.append(vn)
            continue
        sim = max(float(vn @ kv) for kv in kept_vecs)
        _note_probe("retrieval_dedupe_0.85", sim, sim >= threshold)
        if sim >= threshold:
            continue
        kept.append(i)
        kept_vecs.append(vn)
    return kept


# ---------------------------------------------------------------------------
# A2 DISTILL：会话 → (situation, principle) 二元组
# ---------------------------------------------------------------------------


def _render_trajectory(turns: list[dict]) -> tuple[str, bool]:
    """把一段会话渲染成蒸馏用的文本。[YYYY-MM-DD] 前缀由 harness loader 编进 content，此处不再加。"""
    lines = [f"{t.get('role', 'user')}: {t.get('content', '')}" for t in turns]
    text = "\n".join(lines)
    if len(text) > MAX_TRAJECTORY_CHARS:
        return text[:MAX_TRAJECTORY_CHARS], True
    return text, False


def _extract_json_object(text: str) -> dict:
    """上游 experience_summarizer.extract_json_object 的等价实现（含 ``` 围栏剥离 + 花括号兜底）。"""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not m:
            raise
        return json.loads(m.group(0))


def _distill(trajectory_text: str, task_name: str) -> tuple[list[dict], int, int]:
    """返回 (memories, token 用量, 解析重试次数)。上游 parse_max_attempts 默认 3。"""
    style = _distill_style()
    system = DISTILL_SYSTEM_AGENTIC if style == "agentic" else DISTILL_SYSTEM_CONVERSATIONAL
    template = DISTILL_USER_AGENTIC if style == "agentic" else DISTILL_USER_CONVERSATIONAL
    user = template.format(task_name=task_name, num_memories=_max_pairs(), trajectory_text=trajectory_text)

    total_tok = 0
    for attempt in range(3):
        text, used, _fr = _chat(system, user, max_tokens=4096)
        total_tok += used
        _stats.llm_calls += 1
        try:
            obj = _extract_json_object(text)
        except (json.JSONDecodeError, ValueError):
            _log(f"蒸馏 JSON 解析失败，第 {attempt + 1}/3 次重试")
            continue
        if not isinstance(obj, dict):  # 模型可能直接返回数组，不能让 .get 抛 AttributeError
            _log(f"蒸馏返回非对象（{type(obj).__name__}），第 {attempt + 1}/3 次重试")
            continue
        raw = obj.get("memories")
        if not isinstance(raw, list):
            _log(f"蒸馏返回缺少 memories 数组，第 {attempt + 1}/3 次重试")
            continue
        out: list[dict] = []
        for item in raw[: _max_pairs()]:
            if not isinstance(item, dict):
                continue
            principle = str(item.get("memory") or item.get("memory_text") or "").strip()
            if not principle:
                continue
            out.append({"situation": str(item.get("situation") or "").strip(), "principle": principle})
        return out, total_tok, attempt
    return [], total_tok, 3


# ---------------------------------------------------------------------------
# B4 APPRAISE：批判 + 重构（论文一号机制）
# ---------------------------------------------------------------------------


def _normalize_adaptor_output(text: str) -> tuple[str, bool]:
    """上游 _normalize_adaptor_output（mem_adaptor_rollout.py:68-100）的等价实现，返回 (文本, 是否拒绝)。"""
    t = (text or "").strip()
    if not t:
        return "", True
    blocks = re.findall(r"<action>\s*(.*?)\s*</action>", t, flags=re.DOTALL | re.IGNORECASE)
    if blocks and len(re.findall(r"<action>", t, flags=re.IGNORECASE)) == 1 and blocks[0].strip():
        t = blocks[0].strip()
    low = t.lower()
    for m in EMPTY_MARKERS:
        if t == m or low == m.lower():
            return "", True
    if AGENT_PROTOCOL_RE.search(t) or "\nassistant" in low or re.match(r"^assistant\b", low):
        return "", True
    t = re.split(r"\nassistant\b", t, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    if not t:
        return "", True
    return t, False


class AdaptorCallFailed(RuntimeError):
    """重构调用本身失败（网络/限流/服务端错误），与「模型判定这条记忆不适用」是两回事。

    上游的重构跑在本地 vLLM 的 generate_sequences 里，根本不存在远端调用失败这一类；
    _normalize_adaptor_output 处理的是输出格式非法，不是调用失败。把两者合并成 reject 会让
    一段限流窗口静默地变成「这批题没证据」，事后无法逐题定位。故此处抛出，
    与其他臂 retrieve 路径 API 失败的行为对齐（让 run 崩掉、靠 resume 续跑）。
    """


def _reconstruct_one(query: str, situation: str, principle: str) -> tuple[str, bool, int, str]:
    """对单条记忆做一次批判+重构，返回 (guidance, 是否被拒, token, finish_reason)。

    上游是一条命中一次独立 generate_sequences（ppo_trainer.yaml:634 注释「One adaptor forward per
    retrieved hit」），此处逐条调用、由调用方并发。非法输出按上游语义判 reject；
    调用失败则抛 AdaptorCallFailed，不降级成 reject。
    """
    s_old = situation.strip() or "(none)"  # 上游 placeholder_old_state
    user = ADAPTOR_USER_TEMPLATE.format(
        task=ADAPTOR_TASK_DESCRIPTION, s_curr=query, s_old=s_old, p_old=principle
    )
    if len(user) > ADAPTOR_MAX_PROMPT_CHARS:
        user = user[:ADAPTOR_MAX_PROMPT_CHARS]
    try:
        text, used, finish = _chat(ADAPTOR_SYSTEM_PROMPT, user, max_tokens=_adaptor_max_tokens())
    except Exception as exc:
        _adaptor_counters["api_fail"] += 1
        _log(f"重构调用失败（不降级为 reject，直接上抛）：{exc}")
        raise AdaptorCallFailed(str(exc)) from exc
    guidance, rejected = _normalize_adaptor_output(text)
    return guidance, rejected, used, finish


# ---------------------------------------------------------------------------
# MCP 工具
# ---------------------------------------------------------------------------


@mcp.tool
def add_conversation(session_id: str, turns: list[dict], scope: dict, metadata: dict | None = None) -> dict:
    """灌入一段会话：整段蒸馏成 ≤max_pairs 条 (situation, principle)，写入前做嵌入最近邻去重。"""
    t0 = time.perf_counter()
    notes: list[str] = []
    benchmark = (metadata or {}).get("benchmark") or "conversation"

    trajectory, truncated = _render_trajectory(turns)
    if truncated:
        notes.append("TRAJECTORY_TRUNCATED")
    if not trajectory.strip():
        return {"accepted_turns": 0, "native_notes": "EMPTY_SESSION"}

    pairs, distill_tok, retries = _distill(trajectory, benchmark)
    _stats.add_tokens("internal_llm", distill_tok)
    if retries >= 3:
        # 蒸馏是本臂唯一的入库路径，连试 3 次都解析失败 = 这整段会话一条记忆也没进库。
        # 必须按 spec §6 报 PARTIAL_INGEST 且 accepted_turns=0，让评测循环中止并报警，
        # 不能与「模型合法地判定无高价值内容」混为一谈（atommem 已踩过这个语义反转）。
        _log(f"蒸馏连续 3 次解析失败，session={session_id} 未入库")
        return {
            "accepted_turns": 0,
            "error": "PARTIAL_INGEST",
            "native_notes": "; ".join(notes + ["PARTIAL_INGEST=蒸馏解析连续 3 次失败，本 session 零条入库"]),
        }
    if not pairs:
        notes.append("NO_MEMORIES")  # 模型合法返回空数组，与解析失败不同
        return {
            "accepted_turns": len(turns),
            "native_notes": "; ".join(notes) + f"；蒸馏 {distill_tok} tok，{time.perf_counter() - t0:.2f}s",
        }

    # retrieve_key 上游默认 memory_text（ppo_trainer.yaml:478）：索引建在 principle 上
    vecs_new, embed_tok = _embed([p["principle"] for p in pairs])
    _stats.add_tokens("ingest", embed_tok)
    _stats.llm_calls += 1

    records = _load_records()
    existing = _load_vecs()
    scope_id = scope.get("id")
    session_ts = next((t.get("timestamp") for t in turns if t.get("timestamp")), None)
    insert_thr = _insert_dedupe_threshold()
    # 去重必须限定在同一 scope 内：上游的最近邻探测跑在单 task 存储上（milvus_store.py:193-197
    # 用 task_name 限定），本仓库的等价物是 scope。若跨 scope 比，则 conv-B 里一条与 conv-A 相似的
    # 记忆会在写入时被丢弃，而 retrieve 又按 scope 过滤，导致 conv-B 永远拿不到它——
    # 证据静默缺失且无告警，还破坏 spec §2/§3 的对话间隔离契约。
    same_scope_idx = [i for i, r in enumerate(records) if r.get("scope_id") == scope_id]

    kept_records: list[dict] = []
    kept_vecs: list[list[float]] = []
    skipped = 0
    for i, pair in enumerate(pairs):
        v = np.array(vecs_new[i], dtype=np.float32)
        if insert_thr is not None:
            # 本轮已接受的条目也要参与比较，否则同一 session 内的重复会漏网
            pool: list[np.ndarray] = []
            if existing is not None and len(existing) and same_scope_idx:
                pool.append(existing[same_scope_idx])
            if kept_vecs:
                pool.append(np.array(kept_vecs, dtype=np.float32))
            if pool:  # 候选池为空时不计入探针（否则 top1=0 会拉低均值、干扰尺度漂移观测）
                allv = np.vstack(pool)
                top1 = float(np.max(_cosine_matrix(allv, v)))
                fired = top1 >= insert_thr
                _note_probe("insert_dedupe_0.85", top1, fired)
                if fired:
                    skipped += 1
                    continue
        kept_records.append(
            {
                "memory_id": f"{scope_id or 'default'}::{session_id}#{len(records) + len(kept_records)}",
                "session_id": session_id,
                "scope_id": scope_id,
                "situation": pair["situation"],
                "principle": pair["principle"],
                "timestamp": session_ts,
                # 效用计数：use 在检索命中时可累加；succ 在 forced-call 下永远拿不到（REPRO-NOTES 决策 7）
                "utility_use_count": 0,
                "utility_succ_count": 0,
                "utility_score": 0.5,  # 上游 Laplace 先验 (0+1)/(0+2)
            }
        )
        kept_vecs.append(vecs_new[i])

    if kept_records:
        merged = (
            np.array(kept_vecs, dtype=np.float32)
            if existing is None or len(existing) == 0
            else np.vstack([existing, np.array(kept_vecs, dtype=np.float32)])
        )
        _commit(records + kept_records, merged)

    if skipped:
        notes.append(f"INSERT_DEDUPED={skipped}（同 scope 内相似度 ≥{insert_thr}）")
    _stats.n_sessions = len({r["session_id"] for r in _load_records()})
    return {
        "accepted_turns": len(turns),
        "native_notes": "; ".join(notes)
        + f"；蒸馏 {len(pairs)} 条保留 {len(kept_records)} 条，{distill_tok + embed_tok} tok，"
        + f"{time.perf_counter() - t0:.2f}s",
    }


@mcp.tool
def retrieve(query: str, query_mode: str = "fixed", top_k: int = 5, filter: dict | None = None) -> dict:
    """余弦召回 → 贪心去重 → 逐条批判+重构（判定不适用即丢弃）→ envelope。

    forced-call 下由评测循环给 query，上游的 agentic 触发（模型自己决定何时查、自己写 query）
    被 harness 接管，这是 A 档共有口径（interface-spec §9），逐次在 native_notes 声明。
    """
    t0 = time.perf_counter()
    notes: list[str] = ["AGENTIC_TRIGGER_BYPASSED"]
    records = _load_records()
    vecs = _load_vecs()
    if not records or vecs is None or len(vecs) == 0:
        return {
            "results": [], "query_used": query, "query_mode": query_mode,
            "latency_ms": int((time.perf_counter() - t0) * 1000), "native_notes": "EMPTY",
        }
    if len(records) != len(vecs):  # 两个文件一旦错位，检索结果会静默归因到错误记忆上
        raise RuntimeError(f"存储行序错位：records({len(records)}) != vectors({len(vecs)})")

    scope_id = (filter or {}).get("scope_id")
    keep = (
        [i for i, r in enumerate(records) if r.get("scope_id") == scope_id]
        if scope_id
        else list(range(len(records)))
    )
    if filter and any(k in filter for k in ("before_timestamp", "session_ids")):
        notes.append("FILTER_IGNORED")
    if not keep:
        return {
            "results": [], "query_used": query, "query_mode": query_mode,
            "latency_ms": int((time.perf_counter() - t0) * 1000), "native_notes": "; ".join(notes + ["EMPTY_SCOPE"]),
        }

    qv_list, embed_tok = _embed([query])
    _stats.add_tokens("retrieve", embed_tok)
    _stats.llm_calls += 1
    qv = np.array(qv_list[0], dtype=np.float32)

    sub = vecs[keep]
    sims = _cosine_matrix(sub, qv)
    # 上游：先取更大候选池（prefetch_limit），贪心去重后再截断到 top_k（milvus_store.retrieve）
    dedupe_thr = _retrieval_dedupe_threshold()
    prefetch = max(top_k, _DEDUPE_PREFETCH_MIN) if dedupe_thr is not None else top_k
    order = sorted(range(len(sims)), key=lambda i: (-sims[i], i))[:prefetch]
    order = [i for i in order if sims[i] >= 0.0]  # 上游 min_retrieval_score 默认 0.0
    if dedupe_thr is not None:
        before = len(order)
        order = _greedy_dedupe(sub, order, dedupe_thr)
        if before != len(order):
            notes.append(f"RETRIEVAL_DEDUPED={before - len(order)}")
    order = order[:top_k]

    hits = [(records[keep[i]], float(sims[i])) for i in order]

    # ---- B4 批判 + 重构 ----
    adaptor_on = _adaptor_on()
    recon_k = _recon_top_k()
    n_recon = len(hits) if recon_k <= 0 else min(recon_k, len(hits))
    results: list[dict] = []
    recon_tok = 0

    if not adaptor_on:
        notes.append("ADAPTOR_OFF")  # 论文 Table 2「w/o reconstruction」消融口径
        for rec, score in hits:
            results.append(_envelope_of(rec, score, rec["principle"], adapted=False))
    else:
        targets = hits[:n_recon]
        passthrough = hits[n_recon:]
        # 默认 8：评测循环的 Phase A（ingest + 逐题 retrieve）是串行的（bench/runner.py:8-11，
        # 逐题 `await acall(...)`），16 路并发只发生在不调 MCP 的 Phase B，两者不相乘。
        # 即本并发度就是服务端瞄时压力上限，也直接决定 Phase A 总时长
        #（全量约 5958 次 retrieve × top_k 条重构）。
        # 12 实测会撞账户限流（且当时有其他会话共享配额），回调到 8 并配合 _chat 的指数退避。
        workers = max(1, int(os.environ.get("MEMBENCH_MEMHARNESS_ADAPTOR_CONCURRENCY", "8")))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            outs = list(
                pool.map(
                    lambda h: _reconstruct_one(query, h[0].get("situation", ""), h[0]["principle"]),
                    targets,
                )
            )
        n_rejected = n_truncated = 0
        for (rec, score), (guidance, rejected, used, finish) in zip(targets, outs):
            recon_tok += used
            _stats.llm_calls += 1
            _adaptor_counters["evaluated"] += 1
            if finish == "length":
                _adaptor_counters["truncated"] += 1
                n_truncated += 1
            if rejected:
                _adaptor_counters["rejected"] += 1
                n_rejected += 1
                continue  # 上游：判定不适用 → 该条整块不进上下文
            _adaptor_counters["accepted"] += 1
            if guidance.strip() == rec["principle"].strip():
                _adaptor_counters["identical"] += 1  # 上游把「原样复读」当作要惩罚的退化行为
            results.append(_envelope_of(rec, score, guidance, adapted=True))
        for rec, score in passthrough:
            results.append(_envelope_of(rec, score, rec["principle"], adapted=False))
        _stats.add_tokens("internal_llm", recon_tok)
        # 逐题上报：本臂返回条数 = 召回条数 − 被拒条数，不这样报事后无法逐题归因证据为何变少
        notes.append(f"RECONSTRUCTED={len(targets)}; ACCEPTED={len(targets) - n_rejected}; REJECTED={n_rejected}")
        if n_truncated:
            notes.append(f"ADAPTOR_TRUNCATED={n_truncated}")
        if targets and n_rejected == len(targets):
            notes.append(f"ALL_REJECTED={len(targets)}")

    # 效用闭环只剩「被取用」这一半有信号（REPRO-NOTES 决策 7）
    hit_ids = {r["memory_id"] for r, _ in hits}
    if hit_ids:
        for r in records:
            if r["memory_id"] in hit_ids:
                r["utility_use_count"] = int(r.get("utility_use_count", 0)) + 1
        _save_records(records)

    return {
        "results": results,
        "query_used": query,
        "query_mode": query_mode,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
        "native_notes": "; ".join(notes),
    }


def _envelope_of(rec: dict, score: float, text: str, adapted: bool) -> dict:
    """turn_range 恒为 null：蒸馏是 session 级的，一条原则可能来自该 session 的任意若干轮，
    不做无证据的行号归因（interface-spec §4 允许 null，同 intent 的 session 级粒度先例）。
    """
    return make_envelope(
        memory_id=rec["memory_id"],
        text=text,
        session_id=rec["session_id"],
        turn_range=None,
        timestamp=rec.get("timestamp"),
        score=round(score, 4),
        raw_format="memharness_adapted_principle" if adapted else "memharness_principle",
    )


@mcp.tool
def reset() -> dict:
    """清空全部状态（memories.jsonl + vectors.npy + 探针计数）。幂等。"""
    _state.hard_reset_dir()
    _stats.mark_reset()
    _stats.n_sessions = 0
    _reset_probes()
    return {"ok": True, "cleared": {"system": "memharness"}}


@mcp.tool
def stats() -> dict:
    records = _load_records()
    # n_sessions 必须从磁盘重算：正式 run 走「全部已灌 → restore」路径时，
    # 进程内计数器是 0，会让 system_stats 失真（mem0 已踩过同一坑）
    _stats.n_sessions = len({r["session_id"] for r in records})
    d = _stats.to_dict(n_memories=len(records))
    d["adaptor"] = dict(_adaptor_counters)
    ev = _adaptor_counters["evaluated"]
    d["adaptor"]["reject_rate"] = round(_adaptor_counters["rejected"] / ev, 4) if ev else None
    d["threshold_probes"] = {
        name: {
            "evaluated": p["evaluated"],
            "fired": p["fired"],
            "max_top1": round(float(p["max_top1"]), 4),
            "mean_top1": round(float(p["sum_top1"]) / int(p["evaluated"]), 4) if p["evaluated"] else None,
        }
        for name, p in _probes.items()
    }
    d["retry_count"] = _retry_count  # 限流/5xx 退避重试次数
    d["config"] = {
        "adaptor": "on" if _adaptor_on() else "off",
        "recon_top_k": _recon_top_k() or "all",
        "distill_style": _distill_style(),
        "max_pairs_per_session": _max_pairs(),
        "insert_dedupe": _insert_dedupe_threshold(),
        "retrieval_dedupe": _retrieval_dedupe_threshold(),
        "thinking": os.environ.get("MEMBENCH_THINKING", "low"),
        "embed_model": os.environ.get("MEMBENCH_EMBED_MODEL", "embedding-3"),
        "prune": "disabled（forced-call 无 episode success 信号，见 REPRO-NOTES 决策 7）",
    }
    return d


@mcp.tool
def snapshot(tag: str) -> dict:
    r = _state.snapshot(tag)
    _stats.snapshots = _state.tags()
    return r


@mcp.tool
def restore(tag: str) -> dict:
    r = _state.restore(tag)
    _stats.snapshots = _state.tags()
    if not r.get("ok"):
        r["error"] = r.get("error", "SNAPSHOT_FAILED")
    return r


if __name__ == "__main__":
    mcp.run()  # stdio

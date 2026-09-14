# atommem：A档系统（arXiv:2606.19847，AtomMem: Building Simple and Effective Memory System
#   for LLM Agents via Atomic Facts；上游 MINE-USTC/AtomMem @ 776f880）
#
# 机制：把每条 turn 抽成原子事实（A1/A2）→ 元数据解析 + 去重/冲突覆盖 + 事件归属 + 画像批抽（A3/A5）
#   → 检索期三路召回（主召回 5 + 事件层展开 5 + 画像 5）后做多通道图游走重排（B2/B3/B4）。
#
# ═══ 复现口径（2026-09-10 用户逐项定，偏离上游处全部列在这里，不静默）═══
#
# 1. A1/A2 抽取按论文补齐（paper-vs-code 差异 1，能力损失/高）
#    上游跑分链路不抽事实，直接读磁盘上一份现成 JSON（preextracted_pipeline.py:49）。
#    harness 灌的是 LoCoMo 原始 turns，没有那份文件，这一步必须自己实现。
#    提示词逐条对齐论文 Figure A.1 五条规则（见 extractor.py），而不是仓库自带那份缺两条规则的。
#    模型不是论文的 LoRA Qwen3-14B（仓库无权重），而是全 arm 统一的内部 LLM。
#    ⚠️ 规则 4（多模态整合）在本口径下无输入：loaders/locomo.py:98 只交
#      {role, content, timestamp}，图像描述在 loader 层已丢弃。规则保留但未被测到。
#
# 2. B6 事件摘要进 envelope（paper-vs-code 差异 3，能力损失/高）
#    论文三处说事件摘要参与生成（Figure 8/A.3、Figure 9/A.4、正文 txt:436），
#    上游每次查询都算出 event_contexts 却在生成函数入口丢掉（query_response.py:195/198/234）。
#    本臂按论文把事件摘要拼进对应 fact 的 envelope text。
#
# 3. embedding 换 embedding-3（偏离论文与上游的 all-MiniLM-L6-v2）
#    与 mem0 / graphiti / mandol / rag_baseline 同口径，排除"嵌入强度"这个跨臂变量。
#    ⚠️ 代价已知：AtomMem 构建侧阈值（去重 0.95 / 冲突门 0.6 / 画像免 LLM 0.55）都是在
#      384d 尺度上调的硬编码值，2048d 下余弦分布平移会让触发率漂。
#      _wrap_threshold_probes 逐次统计，stats().threshold_probes 单列上报——这是本臂
#      开跑前必须先看的观测项，不是可选调试信息。
#
# 4. B7 不在本臂内执行，但 retrieve 并非零 LLM
#    上游把答案生成放在记忆系统内部并与全部内部调用共用同一模型实例（差异 18），
#    论文则把这一跳划在系统边界外（§3.5.3）。契约要求 retrieve 只回证据，
#    故 _generate_answer 被替换为空实现：本臂不产答案。
#    ⚠️ 但 retrieve 仍有 1 次 LLM 调用——B1 查询意图解析（§3.5.1，解析人物/关键词/时间/是否要画像）。
#    它与 mem0 / graphiti / mandol / rag_baseline 的纯检索零 LLM 不同口径，成本表与延迟表必须单列。
#    与 intent Tier2 的区别：B1 只读 query 本身，不读记忆内容，不构成 active retrieval；
#    但“零 LLM 检索面”的表里不能把它当纯检索臂直接并列。
#
# 5. envelope 条数：facts 与 profiles 共享 top_k 预算，不超额
#    画像是论文的独立一路证据（Table 2：去掉画像单跳 F1 56.66→50.91），不能砍；
#    但也不能额外追加——那会让本臂喂给答题 LLM 的证据体量系统性高于其他臂。
#    做法同 graphiti（edge/entity/community 三类混合塞在 top_k 之内）：
#    profiles 先占位（≤PROFILE_RECALL_TOP_K=5），facts 取剩余预算，top_k=20 时最多 15+5，
#    恰好保住论文 kf=10 : kp=5 的比例。占位数在 native_notes 以 PROFILE_SLOTS=n 声明。
#
# 6. 会话时间必须翻成上游认得的串（_to_native_session_time）
#    上游 parse_session_datetime 只认 "on 8 May, 2023"，传 ISO 会静默落到 datetime.now()，
#    把每条 fact 的 interaction_time 和每条 profile 的 valid_from 写成跑批当天，
#    连带破坏时间过滤与画像版本链。该缺陷由 2026-09-10 对抗审查 C1 实证并修复。
#
# 依赖：主 venv（.venv）即可，上游是脚本式仓库不需要 pip 安装，用 sys.path + chdir 引入。
# 环境变量：MEMBENCH_LLM_API_KEY / MEMBENCH_LLM_BASE_URL / MEMBENCH_LLM_MODEL
#   （可选 MEMBENCH_ATOMMEM_REPO 指向上游 clone，默认 ~/Documents/repo/AtomMem）

import contextlib
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

from fastmcp import FastMCP

from servers.common.base import BaseState
from servers.common.envelope import make_envelope
from servers.common.stats import StatsTracker

mcp = FastMCP("atommem")

_state = BaseState("atommem")
_stats = StatsTracker()

# MEMBENCH_STATE_DIR 可能是相对路径，chdir 之前先钉成绝对，否则 state 会漂到上游仓库下
_MEM_DIR = (_state.state_dir / "memory").resolve()
_MEM_DIR.mkdir(parents=True, exist_ok=True)
# session_id → 会话日期。AtomMem 的 fact 只存 [event_time, recorded_date]，不留会话日期，
# 而 recorded_date 是**跑批当天**（元数据提示词按 today 填）——直接拿它当 envelope.timestamp
# 会把所有事实标成运行日，误导答题 LLM。事实时间为空时回退到这张表。
_SESSION_DATES = _MEM_DIR / "session_dates.json"

ATOMMEM_REPO = Path(
    os.environ.get("MEMBENCH_ATOMMEM_REPO") or (Path.home() / "Documents" / "repo" / "AtomMem")
).resolve()
if not (ATOMMEM_REPO / "config.py").exists():
    raise RuntimeError(f"上游 AtomMem 仓库不存在: {ATOMMEM_REPO}（用 MEMBENCH_ATOMMEM_REPO 指定）")


# ═══ 上游引入（顺序敏感，勿调换）═══
# config.py 的每个常量都在 import 时求值，所以环境变量必须先设；
# src/embedding.py 的替身必须在任何上游模块 import 之前塞进 sys.modules，
# 因为 6 处都是 `from src.embedding import EmbeddingModel`——import 时就绑定了名字。

def _prepare_env() -> None:
    """把 MEMBENCH_* 翻译成上游 config.py 读的 ATOMMEM_*（interface-spec §7 统一配置）。"""
    missing = [k for k in ("MEMBENCH_LLM_API_KEY", "MEMBENCH_LLM_BASE_URL") if not os.environ.get(k)]
    if missing:
        raise RuntimeError(
            f"缺少环境变量 {missing}——MCP stdio 子进程不继承父进程环境（见 interface-spec §7）"
        )
    os.environ["ATOMMEM_API_KEY"] = os.environ["MEMBENCH_LLM_API_KEY"]
    os.environ["ATOMMEM_API_BASE"] = os.environ["MEMBENCH_LLM_BASE_URL"]
    os.environ["ATOMMEM_LLM_MODEL"] = os.environ.get("MEMBENCH_LLM_MODEL", "glm-5.3")
    os.environ["ATOMMEM_LLM_TEMPERATURE"] = "0"          # spec §7：内部 LLM 一律 temp=0
    os.environ["ATOMMEM_EMBEDDING_DIMENSION"] = os.environ.get("ATOMMEM_EMBEDDING_DIMENSION", "2048")
    os.environ["ATOMMEM_FACTS_DIR"] = str(_MEM_DIR)      # 三个 JSON 落 state_dir，snapshot 才有意义
    os.environ["ATOMMEM_PROMPTS_DIR"] = str(ATOMMEM_REPO / "prompts")


_prepare_env()

# 上游 preextracted_pipeline.py:43 用 os.path.join("prompts", ...) 读提示词——相对 cwd 硬编码，
# configure_runtime_paths 也覆盖不到它，只能 chdir。state 路径已在上面钉成绝对，不受影响。
os.chdir(ATOMMEM_REPO)
sys.path.insert(0, str(ATOMMEM_REPO))

import importlib
import types

from servers.atommem.embedding import CloudEmbeddingModel
from servers.atommem import embedding as _embed_mod
from servers.atommem.extractor import PaperFactExtractor

# src 是 namespace package（无 __init__.py），先让它进 sys.modules 再挂替身模块。
_src_pkg = importlib.import_module("src")
_fake_embedding = types.ModuleType("src.embedding")
_fake_embedding.EmbeddingModel = CloudEmbeddingModel
sys.modules["src.embedding"] = _fake_embedding
_src_pkg.embedding = _fake_embedding

import config as atom_config                                   # noqa: E402
from src import file_storage as atom_file_storage               # noqa: E402
from scripts.run_atommem_pipeline import AtomMemPipeline        # noqa: E402

atom_config.FACTS_DIR = str(_MEM_DIR)
atom_config.PROMPTS_DIR = str(ATOMMEM_REPO / "prompts")

_THINKING = os.environ.get("MEMBENCH_THINKING", "low")
_PIPELINES: dict[str, object] = {}
_EXTRACTORS: dict[str, PaperFactExtractor] = {}

# embedding-3 尺度漂移观测（口径 3）。三个硬编码阈值各一个探针：
#   duplicate_0.95  去重（fact_storage.py:162 / config.py:59）
#   conflict_0.6    冲突检测的 LLM 门（进入 _llm_detect_conflict = 门已触发）
#   profile_0.55    画像免 LLM 阈（temporal_profile_version_chain.py:189）
# 每个探针记：被评估次数 / 触发次数 / top-1 相似度的分布（累加和 + 分档计数）。
# 单个 max 看不出分布平移，所以同时留 sum 和分档。
def _new_probe() -> dict:
    return {"evaluated": 0, "fired": 0, "max_sim": 0.0, "sum_top1": 0.0, "n_top1": 0, "ge_090": 0, "ge_095": 0}


_PROBES: dict[str, dict] = {
    "duplicate_0.95": _new_probe(),
    "conflict_0.6": _new_probe(),
    "profile_0.55": _new_probe(),
    # 检索侧符号过滤归零率（纯观测，不改判定）。
    # evaluated = query 解析出具名人物的次数；fired = 其中主召回被过滤清空的次数。
    "people_filter_empty": _new_probe(),
}


def _record_top1(probe: dict, score: float) -> None:
    probe["sum_top1"] += score
    probe["n_top1"] += 1
    probe["max_sim"] = max(probe["max_sim"], score)
    if score >= 0.90:
        probe["ge_090"] += 1
    if score >= 0.95:
        probe["ge_095"] += 1


def _llm_instances(pipeline) -> dict[int, object]:
    """AtomMem 内部有 4 个独立的 LLMInterface 实例，口径与上游
    get_aggregate_llm_statistics（incremental_temporal_profile.py:334）完全一致：
      pipeline.llm                              抽取 / 元数据解析 / B1 意图（query_responder.llm 与它同对象）
      fact_storage.llm                          冲突检测
      fact_storage.event_manager.llm            事件归属 / 摘要重写
      fact_storage.profile_manager.llm          画像抽取（temporal_processor.llm 与它同对象）
    只钉其中一个 = 另三个跑在服务端默认推理深度，在 max_tokens 受限时会重现 amem
    2026-08-30 那种“思考吃光额度 → content 为空 → 调用方静默返回 None”的事故。
    """
    fs = getattr(pipeline, "fact_storage", None)
    cands = [
        pipeline.llm,
        getattr(pipeline.query_responder, "llm", None),
        getattr(fs, "llm", None),
        getattr(getattr(fs, "event_manager", None), "llm", None),
        getattr(getattr(fs, "profile_manager", None), "llm", None),
        getattr(getattr(getattr(fs, "profile_manager", None), "temporal_processor", None), "llm", None),
    ]
    return {id(x): x for x in cands if x is not None}


def _pin_llm(pipeline) -> None:
    """全部内部 LLM 实例钉 temperature=0 + thinking 档位（interface-spec §7）。

    thinking 三态映射与 mem0 对齐（servers/mem0/server.py:167-181）：
      low（默认）= thinking enabled + reasoning_effort=low；enabled = 服务端默认深度；disabled = 关思考。
    不能把非 low 一律钉成 high——那会在切 enabled 做对照时静默跑出第三种配置。

    max_tokens：上游 config.py:44 写死 2000，属于代码原生，低档下不覆盖（同 amem 处理 max_tokens=1000
    的理由）。但思考与正式回复共用额度，一旦调高档位 2000 必爆，所以非 low 档提到 128k
    并在 stats 里留痕，不静默。

    ⚠️ 失败不得静默：pin 走错属性路径被 except 吃掉、然后用默认温度跑完整轮，是 amem 已发生过的事故。
    这里把实际钉中数记在 pin_targets，stats() 以 n/N 形式上报。
    """
    targets = _llm_instances(pipeline)
    n_ok = 0
    for llm in targets.values():
        try:
            client = llm.client
            create = client.chat.completions.create

            def create_pinned(_create=create, **kwargs):
                kwargs["temperature"] = 0
                extra = kwargs.setdefault("extra_body", {})
                extra["thinking"] = {"type": "disabled" if _THINKING == "disabled" else "enabled"}
                if _THINKING == "low":
                    extra["reasoning_effort"] = "low"
                else:
                    kwargs["max_tokens"] = max(int(kwargs.get("max_tokens") or 0), 128000)
                return _create(**kwargs)

            client.chat.completions.create = create_pinned
            n_ok += 1
        except Exception as e:                       # noqa: BLE001
            print(f"[atommem-pin] 注入失败（公平性受损，未静默）: {e}", file=sys.stderr)
    pipeline.pin_targets = (n_ok, len(targets))
    pipeline.pin_ok = n_ok == len(targets) == 4


def _wrap_threshold_probes(pipeline) -> None:
    """统计 384d→2048d 换嵌入后，硬编码阈值的实际触发情况（口径 3 的观测项）。

    只观测不改判定：包住 _is_duplicate / _detect_conflict，原逻辑原样执行。
    """
    storage = pipeline.fact_storage
    orig_dup = storage._is_duplicate
    orig_llm_conf = storage._llm_detect_conflict

    from src.fact_storage import people_sets_compatible
    from src.utils import cosine_similarity

    def is_duplicate(new_fact, existing_facts):
        p = _PROBES["duplicate_0.95"]
        p["evaluated"] += 1
        fired = orig_dup(new_fact, existing_facts)
        # top-1 必须算在与上游同一个候选集上（fact_storage.py:150-157 先过人物兼容门），
        # 否则会出现 max_sim>0.95 但 fired=0 的误导读数。
        try:
            if new_fact.get("embedding"):
                np_ = set(new_fact.get("people", []))
                cands = [f for f in existing_facts if people_sets_compatible(np_, set(f.get("people", [])))]
                if cands:
                    _record_top1(p, float(max(
                        cosine_similarity(f["embedding"], new_fact["embedding"]) for f in cands
                    )))
        except Exception:                            # noqa: BLE001 —— 观测失败不影响主链路
            pass
        if fired:
            p["fired"] += 1
        return fired

    def llm_detect_conflict(new_fact, candidates):
        # 包 _llm_detect_conflict 而不是 _detect_conflict：前者被调用 = 0.6 相似度门已经过了（门触发），
        # 后者返回非 None 只代表 LLM 确认了冲突。两者不是同一件事。
        p = _PROBES["conflict_0.6"]
        p["evaluated"] += 1
        hit = orig_llm_conf(new_fact, candidates)
        if hit:
            p["fired"] += 1
        return hit

    storage._is_duplicate = is_duplicate
    storage._llm_detect_conflict = llm_detect_conflict

    # 画像 0.55 免 LLM 阈：temporal_profile_version_chain.py:188-191 拿 _retrieve_candidates 的
    # top-1 分与 min_llm_score 比。包住它就能看到 2048d 下这个阈的实际位置。
    try:
        proc = pipeline.fact_storage.profile_manager.temporal_processor
        orig_cand = proc._retrieve_candidates

        def retrieve_candidates(prepared, temporal_profiles):
            p = _PROBES["profile_0.55"]
            p["evaluated"] += 1
            out = orig_cand(prepared, temporal_profiles)
            if out:
                top = float(out[0].get("score", 0.0))
                _record_top1(p, top)
                if top >= proc.min_llm_score:
                    p["fired"] += 1                  # 过门 = 会去调 LLM 四选一
            return out

        proc._retrieve_candidates = retrieve_candidates
    except Exception as e:                           # noqa: BLE001
        print(f"[atommem-probe] 画像探针未装上（仅影响观测）: {e}", file=sys.stderr)


def _get_pipeline(scope_id: str):
    """per-scope pipeline。AtomMem 按 conversation_id 分文件（facts_/events_/profiles_<id>.json），
    scope.id 直接作 conversation_id，天然隔离。"""
    p = _PIPELINES.get(scope_id)
    if p is None:
        with _quiet():
            p = AtomMemPipeline(
                conversation_id=scope_id,
                output_dir=str(_MEM_DIR),
                profile_top_k=atom_config.PROFILE_TEMPORAL_TOP_K,
                min_profile_llm_score=atom_config.PROFILE_TEMPORAL_MIN_LLM_SCORE,
                enable_graph=True,
                final_top_k=atom_config.GRAPH_FINAL_TOP_K,
            )
        _pin_llm(p)
        _wrap_threshold_probes(p)
        # B7 交给评测循环：契约的 retrieve 只回证据，本臂不产答案（口径 4）
        p.query_responder._generate_answer = lambda *a, **k: ""
        _PIPELINES[scope_id] = p
        _EXTRACTORS[scope_id] = PaperFactExtractor(p.llm)
    return p


@contextlib.contextmanager
def _quiet():
    """上游把进度和重试信息 print 到 stdout（preextracted_pipeline._print_session_progress、
    LLMInterface.call_with_retry 等十余处），而 stdio 模式下 stdout 是 JSON-RPC 通道——
    一行进度条就会让 client 端 JSONRPCMessage 解析崩溃。所有进入上游代码的调用都要包这层。

    MCP server 是单线程 asyncio，工具执行期间不会并发写 JSON-RPC 响应，
    因此在工具函数体内临时改道 sys.stdout 是安全的。
    """
    with contextlib.redirect_stdout(sys.stderr):
        yield


def _safe_session(session_id: str) -> str:
    """dia_id 的 session 段不能含冒号（否则 parse_dia_id 正则对不上）。
    会话日期表必须用同一把 key，否则写入用原 id、读取用去冒号 id 就对不上。"""
    return session_id.replace(":", "-")


def _load_session_dates() -> dict:
    import json

    if _SESSION_DATES.exists():
        try:
            return json.loads(_SESSION_DATES.read_text())
        except Exception:                            # noqa: BLE001
            return {}
    return {}


def _save_session_date(session_id: str, date: str | None) -> None:
    import json

    if not date:
        return
    d = _load_session_dates()
    if d.get(session_id) == date:
        return
    d[session_id] = date
    _SESSION_DATES.parent.mkdir(parents=True, exist_ok=True)
    _SESSION_DATES.write_text(json.dumps(d, ensure_ascii=False))


def _fact_timestamp(fact: dict, session_dates: dict) -> str | None:
    """envelope.timestamp = 说话时间（会话日期），与 spec §4 示例及 mem0 / rag_baseline 同口径。

    fact['time'] = [event_time, interaction_time]。interaction_time 由上游
    parse_session_datetime(session_time) 得出，只要 _to_native_session_time 传对了格式，
    它就是会话日期（传错格式时上游会静默落到 datetime.now，见 src/utils.py:34）。
    事实涉及的绝对时间已由论文规则 2 写进事实正文（“Caroline attended … on 2023-05-07”），
    不需要再占时间戳槽位；而且 event_time 可能是 "2024-06" 这类残缺值。
    interaction_time 缺失时回退到会话日期表。
    """
    tf = fact.get("time") or []
    interaction = tf[1] if isinstance(tf, list) and len(tf) > 1 else None
    if isinstance(interaction, str) and interaction.strip():
        return interaction.strip()
    dia = str(fact.get("dia_id") or "")
    return session_dates.get(dia.rsplit(":", 1)[0]) if ":" in dia else None


def _default_scope() -> str:
    """retrieve 不带 filter.scope_id 时的回退（smoke 步骤 2/5/7 就是这种调用）。
    优先用已建实例，其次从磁盘 facts_*.json 推断——进程重启或 restore 后 _PIPELINES 是空的。"""
    if _PIPELINES:
        return next(iter(_PIPELINES))
    names = sorted(p.stem[len("facts_"):] for p in _MEM_DIR.glob("facts_*.json"))
    return names[0] if names else "default"


def _drop_caches() -> None:
    """reset / restore 后必须清：pipeline 实例持有 storage 句柄，file_storage 有模块级 mtime 缓存。
    不清就会读到脏状态（memory-system-analysis §7.6 的已知坑）。"""
    _PIPELINES.clear()
    _EXTRACTORS.clear()
    try:
        atom_file_storage._COLLECTION_CACHE.clear()
    except Exception:                                # noqa: BLE001
        pass


# ═══ turn → AtomMem dialogue 记录 ═══

# harness 渲染约定：content = "[YYYY-MM-DD] Speaker: text"（loaders/locomo.py:96，日期前缀由
# harness 层统一加，spec §7）。这里解析回 speaker/text 供 AtomMem 的 people 元数据用；
# 解析不出就退化为 role 作 speaker、content 全文作 text，不报错。
_SPEAKER_RE = re.compile(r"^(?:\[(\d{4}-\d{2}-\d{2})\]\s*)?([^:\n]{1,40}?):\s*(.*)$", re.DOTALL)

# 月名写死而不用 strftime('%B')：后者依赖 locale，非英文 locale 下会产出上游 month_map 查不到的名字。
_MONTHS_EN = ["January", "February", "March", "April", "May", "June",
              "July", "August", "September", "October", "November", "December"]


def _to_native_session_time(iso_date: str) -> str:
    r"""ISO 日期 → 上游认得的会话时间串。

    上游 src/utils.py:12-34 的 parse_session_datetime 只认 LoCoMo 原生格式
    "1:56 pm on 8 May, 2023"（正则 `on (\d+) (\w+), (\d{4})`，月名要完整英文）。
    直接传 ISO "2023-05-08" 会匹配失败并**静默落到 datetime.now()**，
    后果是每条 fact 的 interaction_time 和每条 profile 的 valid_from 都变成跑批当天：
      · 检索侧时间过滤（retrieval.py:290-300）和图过滤（multichannel_graph.py:619-631）
        对两个时间槽位做前缀匹配，event_time 为空的 fact 在带时间 query 下会被错拒；
      · 画像版本链的 valid_from 变成未来日期，_apply_profile_time_filter 会把町像全部判成
        “该时刻还不存在”而丢掉。
    这是 2026-09-10 对抗审查 C1 实证出来的，不是上游行为。
    """
    if not iso_date:
        return ""
    try:
        y, m, d = (int(x) for x in iso_date.split("-")[:3])
        return f"on {d} {_MONTHS_EN[m - 1]}, {y}"
    except (ValueError, IndexError):
        return ""


def _parse_turn(turn: dict, session_id: str, idx: int) -> dict:
    content = turn.get("content", "") or ""
    m = _SPEAKER_RE.match(content)
    date_in_text, speaker, text = (m.group(1), m.group(2).strip(), m.group(3)) if m else (None, None, None)
    if not speaker:
        speaker = turn.get("role", "user")
        text = content

    ts = turn.get("timestamp")
    session_date = (ts[:10] if isinstance(ts, str) and len(ts) >= 10 else None) or date_in_text or ""

    # dia_id 必须匹配 multichannel_graph.parse_dia_id 的 ^([^:]+):(\d+)$，否则 B3 的轮次通道
    # 会把所有事实塞进 __global__ 并按 fallback_order 排序——相邻轮次边就废了。
    # LoCoMo 原生 dia_id（"D1:1"）在 loader 层已丢弃，这里按 session 重建，序号从 1 起。
    return {
        "session": session_id,
        "session_time": _to_native_session_time(session_date),   # 给上游 parse_session_datetime
        "session_date": session_date,                            # ISO，给抽取器与会话日期表
        "dia_id": f"{_safe_session(session_id)}:{idx}",
        "speaker": speaker,
        "text": text,
    }


# ═══ 六工具 ═══


@mcp.tool
def add_conversation(session_id: str, turns: list[dict], scope: dict, metadata: dict | None = None) -> dict:
    """灌入一段会话：逐 turn 按论文 Figure A.1 抽原子事实，再走 AtomMem 的构建链。"""
    t0 = time.perf_counter()
    scope_id = (scope or {}).get("id") or "default"
    pipeline = _get_pipeline(scope_id)
    extractor = _EXTRACTORS[scope_id]

    # 只读 pipeline.llm 会漏掉冲突检测 / 事件归属 / 事件摘要 / 画像抽取四类调用（C3）——
    # 而构建期成本的大头正在那里。用上游的聚合口径（覆盖 4 个 LLMInterface 实例）。
    agg0 = pipeline.get_aggregate_llm_statistics()
    emb0 = _embed_mod.USAGE["tokens"]

    parsed = [_parse_turn(t, session_id, i + 1) for i, t in enumerate(turns)]
    _save_session_date(_safe_session(session_id),
                       next((x["session_date"] for x in parsed if x["session_date"]), None))

    # A1/A2：逐 turn 抽事实，上下文窗口取前一条（config.CONTEXT_WINDOW_K=1）
    dialogue_results = []
    n_fail_before = extractor.n_parse_fail
    n_api_before = extractor.n_api_fail
    with _quiet():
        for i, cur in enumerate(parsed):
            # 抽取器的 Time: 行给 LLM 看，用 ISO 更清晰；上游那一侧用 native 串
            facts = extractor.extract_turn(cur, parsed[i - 1] if i > 0 else None, cur["session_date"])
            dialogue_results.append({**cur, "facts": facts})
    n_fail = (extractor.n_parse_fail - n_fail_before) + (extractor.n_api_fail - n_api_before)

    # A3/A5：元数据解析 → 去重/冲突 → 事件归属 → 画像批抽 → 落盘
    # process_all_facts 覆写版内部已调 _finalize_temporal_profiles + save_memory_snapshot
    # （incremental_temporal_profile.py:313-317），这里不再重复落盘。
    # 画像触发：上游的"攒够 10 条即触发"（profile_manager.py:41）仍在 session 内生效，
    # 本封装只是在它之上**追加**了一次 session 末 flush（一次 add_conversation = 一个 session），
    # 因此比上游更接近论文的"每个 session 结束触发"（差异 8），但不是替代关系。
    with _quiet():
        pipeline.process_all_facts(dialogue_results)

    n_facts = sum(len(d["facts"]) for d in dialogue_results)
    agg1 = pipeline.get_aggregate_llm_statistics()
    _stats.add_tokens("internal_llm", agg1["total_tokens"] - agg0["total_tokens"])
    _stats.add_tokens("ingest", _embed_mod.USAGE["tokens"] - emb0)
    _stats.llm_calls += agg1["calls"] - agg0["calls"]     # 累加：一个进程会灌多个 conversation
    _stats.n_sessions += 1

    notes = [f"atommem: {n_facts} facts from {len(turns)} turns", f"{time.perf_counter() - t0:.1f}s"]
    n_ok, n_all = getattr(pipeline, "pin_targets", (0, 0))
    if not pipeline.pin_ok:
        notes.append(f"PIN_FAILED={n_ok}/{n_all}")
    # §6 的 PARTIAL_INGEST = "部分 turn 灌入失败"。抽取调用失败才是它；
    # "LLM 判定整段无高价值事实"是规则 1 的合法结果，不能报成灌入失败（另报 NO_FACTS）。
    if n_fail:
        notes.append(f"PARTIAL_INGEST={n_fail}/{len(turns)}")
    if turns and n_facts == 0:
        notes.append("NO_FACTS")

    return {"accepted_turns": len(turns), "native_notes": "; ".join(notes)}


@mcp.tool
def retrieve(query: str, query_mode: str = "fixed", top_k: int = 5, filter: dict | None = None) -> dict:
    """三路召回 + 多通道图游走重排。返回 facts（含事件摘要）+ profiles 两类 envelope。"""
    t0 = time.perf_counter()
    notes: list[str] = []
    scope_id = (filter or {}).get("scope_id") or _default_scope()
    if filter and any(k in filter for k in ("before_timestamp", "session_ids")):
        notes.append("FILTER_IGNORED")

    pipeline = _get_pipeline(scope_id)
    emb0 = _embed_mod.USAGE["tokens"]
    agg0 = pipeline.get_aggregate_llm_statistics()

    # 契约的 top_k 驱动 B4 的最终事实数（论文 kf=10 是它的默认值）
    qr = pipeline.query_responder
    qr.final_top_k = top_k
    with _quiet():
        query_info, lat = qr.prepare_query_info(query)
        resp = qr.answer_query_with_query_info(query, query_info, shared_latency=lat, category=None)

    facts = resp.get("retrieved_facts", []) or []
    profiles = resp.get("retrieved_profiles", []) or []
    event_contexts = resp.get("event_contexts", {}) or {}

    # 上游 src/retrieval.py:284-288 的主召回符号过滤：query 解析出具名人物时，
    # people 不与之相交的 fact（含 people 为空的）一律被拒且无回退，召回直接归零。
    # 论文 txt:233-235 明写主召回按人物过滤，故**不加兑底**（尊重论文复现原则，
    # 不擅自改进）；但归零不得静默——逐题上报，出分时可单独统计它吃掉了多少题。
    # 2026-09-10 量化：LoCoMo 200 题分层采样，query 人名落在说话人名单外的占 1.0%。
    if query_info.get("people"):
        _PROBES["people_filter_empty"]["evaluated"] += 1
        if not facts:
            _PROBES["people_filter_empty"]["fired"] += 1
            notes.append("PEOPLE_FILTER_EMPTY")

    # 口径 5：facts + profiles 共用 top_k 预算，不超额。图重排结果已按分排序，截尾等价于少要几条。
    # top_k=20 时最多 15 facts + 5 profiles，恰好保住论文 kf=10 : kp=5 的比例。
    # （graphiti 的先例：edge/entity/community 三类混合同样塞在 top_k 之内，不额外追加。）
    profiles = profiles[: max(0, top_k - 1)]
    facts = facts[: max(1, top_k - len(profiles))]

    session_dates = _load_session_dates()
    results = []
    for rank, f in enumerate(facts):
        # 口径 2：事件摘要拼进 text（论文说它参与生成，上游算了却丢弃）
        text = f.get("fact", "")
        ev = event_contexts.get(f.get("fact_id"))
        if ev:
            text = f"{text} ｜ 事件: {ev}"
        recorded = _fact_timestamp(f, session_dates)
        dia = str(f.get("dia_id") or "")
        turn_no = int(dia.rsplit(":", 1)[1]) if ":" in dia and dia.rsplit(":", 1)[1].isdigit() else None
        results.append(
            make_envelope(
                memory_id=f"{scope_id}:{f.get('fact_id') or f'F{rank}'}",
                text=text,
                session_id=dia.rsplit(":", 1)[0] if ":" in dia else None,
                turn_range=[turn_no, turn_no] if turn_no is not None else None,
                timestamp=recorded,
                score=round(float(f["score"]), 4) if isinstance(f.get("score"), (int, float)) else None,
                raw_format="atommem_fact",
            )
        )

    # 口径 5：画像是论文的独立一路证据，额外附加并显式声明条数
    for p in profiles:
        results.append(
            make_envelope(
                memory_id=f"{scope_id}:{p.get('profile_id') or 'P?'}",
                text=p.get("content", ""),
                session_id=None,
                turn_range=None,
                timestamp=p.get("valid_from") or None,
                # profile 的 score 是混合余弦/Jaccard（0-1），fact 开图时是 PPR 稳态概率（~0.01-0.2），
                # 两者不同尺度、不可全局排序，故画像侧置 None，避免被当成同一标尺读。
                score=None,
                raw_format="atommem_profile",
            )
        )
    if profiles:
        notes.append(f"PROFILE_SLOTS={len(profiles)}")

    gd = resp.get("graph_debug") or {}
    graph_on = bool(gd.get("enabled"))
    notes.append(f"graph={'on' if graph_on else 'off'}")
    notes.append(f"score_kind={'ppr' if graph_on else 'hybrid'}")
    if not graph_on and gd.get("reason"):
        notes.append(f"graph_reason={gd['reason']}")
    if len(facts) + len(profiles) < top_k:
        # 结构性不足（图关闭/失败时种子上限 GRAPH_MAX_SEED_FACTS=10），不是阈值截断。
        # §7 的 TRUNCATED_BELOW_TOP_K 留给阈值截断，不能混用。
        notes.append(f"SEED_LIMITED={len(facts) + len(profiles)}/{top_k}")

    agg1 = pipeline.get_aggregate_llm_statistics()
    _stats.add_tokens("retrieve", _embed_mod.USAGE["tokens"] - emb0)
    _stats.add_tokens("internal_llm", agg1["total_tokens"] - agg0["total_tokens"])   # B1 查询意图解析
    _stats.llm_calls += agg1["calls"] - agg0["calls"]

    return {
        "results": results,
        "query_used": query,
        "query_mode": query_mode,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
        "native_notes": "; ".join(notes),
    }


@mcp.tool
def reset() -> dict:
    """清空全部状态（三个 JSON + pipeline 实例 + 模块级缓存）。幂等。"""
    n = _count_facts()
    _state.hard_reset_dir()
    _MEM_DIR.mkdir(parents=True, exist_ok=True)
    _drop_caches()
    for k in _PROBES:
        _PROBES[k] = _new_probe()                    # 探针跟着状态走，不跨 run 累积
    _stats.mark_reset()
    _stats.n_sessions = 0
    return {"ok": True, "cleared": {"memories": n, "system": "atommem"}}


def _count_facts() -> int:
    import json

    total = 0
    for p in _MEM_DIR.glob("facts_*.json"):
        try:
            data = json.loads(p.read_text())
            total += len(data.get("facts", []) if isinstance(data, dict) else data)
        except Exception:                            # noqa: BLE001
            continue
    return total


@mcp.tool
def stats() -> dict:
    d = _stats.to_dict(n_memories=_count_facts())
    d["threshold_probes"] = _PROBES          # embedding-3 尺度漂移观测（口径 3）
    d["embedding"] = {
        "model": os.environ.get("MEMBENCH_EMBED_MODEL", "embedding-3"),
        "calls": _embed_mod.USAGE["calls"],
        "cache_hits": _embed_mod.USAGE["cache_hits"],
    }
    d["extraction"] = {
        sid: {"calls": e.n_calls, "facts": e.n_facts,
              "parse_fail": e.n_parse_fail, "api_fail": e.n_api_fail}
        for sid, e in _EXTRACTORS.items()
    }
    d["pin_ok"] = all(getattr(p, "pin_ok", False) for p in _PIPELINES.values()) if _PIPELINES else None
    d["pin_targets"] = {sid: getattr(p, "pin_targets", None) for sid, p in _PIPELINES.items()}
    d["thinking"] = _THINKING
    return d


@mcp.tool
def snapshot(tag: str) -> dict:
    r = _state.snapshot(tag)
    _stats.snapshots = _state.tags()
    return r


@mcp.tool
def restore(tag: str) -> dict:
    r = _state.restore(tag)
    _MEM_DIR.mkdir(parents=True, exist_ok=True)
    _drop_caches()                                   # 必须：否则 pipeline 句柄与 mtime 缓存读到脏状态
    _stats.snapshots = _state.tags()
    if not r.get("ok"):
        r["error"] = r.get("error", "SNAPSHOT_FAILED")
    return r


if __name__ == "__main__":
    mcp.run()  # stdio

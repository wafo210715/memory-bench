# mem0：A档首个真实系统封装（interface-spec 契约）
# 公平性配置（spec §7）：LLM 全部走 MEMBENCH_* 环境变量，temperature=0。
# 存储落 MEMBENCH_STATE_DIR（chroma 本地目录），snapshot/restore = 目录拷贝 + 重建实例。
# env_required: MEMBENCH_LLM_API_KEY / MEMBENCH_LLM_BASE_URL / MEMBENCH_LLM_MODEL
# 可选: MEMBENCH_EMBED_MODEL（默认 text-embedding-3-small）、MEMBENCH_EMBED_BASE_URL / MEMBENCH_EMBED_API_KEY

import json
import os
import sys
import time
from pathlib import Path

# MCP stdio 要求 stdout 纯净：chromadb 的 warning（"The 'chroma' vector store does not support
# keyword search..."）用裸 print/root handler 漏到 stdout，污染 JSON-RPC（2026-08-22 S4 第一批实测）
import builtins
import logging

# 根治：任何显式传 sys.stdout 的 StreamHandler 一律改道 stderr（logging 自身 lastResort 用无参构造不受影响）
_orig_sh_init = logging.StreamHandler.__init__


def _safe_sh_init(self, stream=None):
    if stream is sys.stdout:
        stream = sys.stderr
    _orig_sh_init(self, stream)


logging.StreamHandler.__init__ = _safe_sh_init

logging.basicConfig(stream=sys.stderr, level=logging.WARNING, force=True)
_orig_print = builtins.print


def _print_stderr(*args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    _orig_print(*args, **kwargs)


builtins.print = _print_stderr

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# 关闭遥测：PostHog 配额限流会造成假死，评测机也不应外发数据
os.environ.setdefault("MEM0_TELEMETRY", "False")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "FALSE")

from fastmcp import FastMCP

from servers.common.base import BaseState
from servers.common.envelope import make_envelope
from servers.common.stats import StatsTracker

mcp = FastMCP("mem0")

_state = BaseState("mem0")
_stats = StatsTracker()
_SCOPE_FILE = _state.state_dir / "scopes.json"
_MEMORY = None  # 惰性单例：restore 后必须重建


def _die_if_env_missing() -> None:
    missing = [k for k in ("MEMBENCH_LLM_API_KEY", "MEMBENCH_LLM_BASE_URL", "MEMBENCH_LLM_MODEL") if not os.environ.get(k)]
    if missing:
        # 用 RuntimeError 而非 SystemExit：让错误作为工具结果返回给客户端，不能无声杀死 server
        raise RuntimeError(f"缺少环境变量 {missing}——MCP stdio 子进程不继承父进程环境，须在 servers.yaml/客户端配置里显式传入（见 interface-spec §7）")


def _config() -> dict:
    chroma_path = _state.state_dir / "chroma"
    embed_base = os.environ.get("MEMBENCH_EMBED_BASE_URL") or os.environ["MEMBENCH_LLM_BASE_URL"]
    embed_key = os.environ.get("MEMBENCH_EMBED_API_KEY") or os.environ["MEMBENCH_LLM_API_KEY"]
    return {
        "llm": {
            "provider": "openai",
            "config": {
                "model": os.environ["MEMBENCH_LLM_MODEL"],
                "api_key": os.environ["MEMBENCH_LLM_API_KEY"],
                "openai_base_url": os.environ["MEMBENCH_LLM_BASE_URL"],
                "temperature": 0,
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": os.environ.get("MEMBENCH_EMBED_MODEL", "text-embedding-3-small"),
                "api_key": embed_key,
                "openai_base_url": embed_base,
            },
        },
        "vector_store": {
            "provider": "chroma",
            "config": {"path": str(chroma_path), "collection_name": "membench"},
        },
    }


def _mem():
    global _MEMORY
    if _MEMORY is None:
        _die_if_env_missing()
        from mem0 import Memory  # 惰性导入：环境就绪才加载

        _MEMORY = Memory.from_config(_config())
        _pin_thinking(_MEMORY)
    return _MEMORY


def _pin_thinking(memory) -> None:
    """钉住推理深度，防止服务端默认漂移。MEMBENCH_THINKING ∈ low | enabled | disabled：
    - low: thinking enabled + reasoning_effort=low（实测 reasoning 压到 0，总 token -63%——快速出粗结论用）
    - enabled(默认): 服务端默认深度（glm-5.3 metadata: default_reasoning_level=max）
    - disabled: 关思考
    经 OpenAI SDK extra_body 注入，不侵入 mem0 内部。"""
    mode = os.environ.get("MEMBENCH_THINKING", "enabled")
    try:
        create = memory.llm.client.chat.completions.create

        def create_with_thinking(**kwargs):
            extra = kwargs.setdefault("extra_body", {})
            extra["thinking"] = {"type": "disabled" if mode == "disabled" else "enabled"}
            if mode == "low":
                extra["reasoning_effort"] = "low"
            return create(**kwargs)

        memory.llm.client.chat.completions.create = create_with_thinking
    except Exception:
        pass  # 注入失败则退回服务端默认，不阻断启动


def _drop_memory() -> None:
    """弃实例 + 清 chroma 进程级缓存（2026-08-18 假数据事故根因：
    PersistentClient 按路径缓存 system，文件换了但缓存句柄读旧状态，
    reset 后 restore 会得到空 collection）。"""
    global _MEMORY
    if _MEMORY is not None:
        try:
            client = getattr(getattr(_MEMORY, "vector_store", None), "client", None)
            if client is not None and hasattr(type(client), "clear_system_cache"):
                type(client).clear_system_cache()
        except Exception:
            pass  # 清理失败不阻塞，最坏情况重建后读到旧状态
    _MEMORY = None


def _scopes() -> dict:
    if _SCOPE_FILE.exists():
        return json.loads(_SCOPE_FILE.read_text())
    return {"scope_ids": [], "sessions": []}


def _save_scopes(scope_id: str | None, session_id: str | None) -> None:
    s = _scopes()
    if scope_id and scope_id not in s["scope_ids"]:
        s["scope_ids"].append(scope_id)
    if session_id and session_id not in s["sessions"]:
        s["sessions"].append(session_id)
    _SCOPE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SCOPE_FILE.write_text(json.dumps(s, ensure_ascii=False))


def _n_memories() -> int:
    total = 0
    for uid in _scopes()["scope_ids"]:
        try:
            total += len(_extract(_mem().get_all(filters={"user_id": uid})))
        except Exception:
            pass  # get_all 失败不阻塞 stats，按 0 计
    return total


def _extract(res) -> list:
    """mem0 v2 返回兼容：{'results': [...]} 或直接 list。"""
    if isinstance(res, dict):
        return res.get("results", [])
    return res or []


@mcp.tool
def add_conversation(session_id: str, turns: list[dict], scope: dict, metadata: dict | None = None) -> dict:
    """灌入：整段会话一次 add（mem0 内部抽事实），metadata 记 session 溯源。"""
    t0 = time.perf_counter()
    messages = [{"role": t.get("role", "user"), "content": t.get("content", "")} for t in turns]
    first_ts = next((t.get("timestamp") for t in turns if t.get("timestamp")), None)
    # timestamp 是 mem0 Pro 功能，OSS SDK 不支持——塞进 metadata，envelope 从这里读回
    meta = {"session_id": session_id, **(metadata or {})}
    if first_ts:
        meta["timestamp"] = first_ts
    _mem().add(messages, user_id=scope.get("id"), metadata=meta)
    _save_scopes(scope.get("id"), session_id)
    _stats.n_sessions = len(_scopes()["sessions"])
    # mem0 未暴露内部 LLM token——按 spec 记 None（不可计量），诚实优先
    _stats.add_tokens("ingest", None)
    _stats.add_tokens("internal_llm", None)
    _stats.llm_calls = None  # type: ignore[assignment]  # 同上，未暴露
    return {
        "accepted_turns": len(turns),
        "native_notes": f"mem0 抽取完成，耗时 {int((time.perf_counter() - t0) * 1000)}ms（内部 token 未暴露）",
    }


@mcp.tool
def retrieve(query: str, query_mode: str = "fixed", top_k: int = 5, filter: dict | None = None) -> dict:
    """检索：mem0.search；turn_range 为 null（事实粒度，无轮次定位），粒度差异论文显式声明。"""
    t0 = time.perf_counter()
    notes = []
    scope_ids = _scopes()["scope_ids"]
    # scope_id 显式过滤（对话间隔离）：LoCoMo 200 条 conversation = 200 个独立 user，互不可见
    if filter and filter.get("scope_id"):
        uid = filter["scope_id"]
    else:
        if len(scope_ids) > 1:
            notes.append("MULTI_SCOPE: 未指定 filter.scope_id，仅检索首个 scope")
        uid = scope_ids[0] if scope_ids else "default"
    if filter and any(k for k in filter if k != "scope_id"):
        notes.append("FILTER_IGNORED: 仅支持 scope_id，其余过滤键忽略")
    res = _extract(_mem().search(query, top_k=top_k, filters={"user_id": uid}))
    results = [
        make_envelope(
            memory_id=r.get("id"),
            text=r.get("memory") or r.get("text", ""),
            session_id=(r.get("metadata") or {}).get("session_id"),
            turn_range=None,
            timestamp=(r.get("metadata") or {}).get("timestamp"),
            score=r.get("score"),
            raw_format="mem0_fact",
        )
        for r in res
    ]
    return {
        "results": results,
        "query_used": query,
        "query_mode": query_mode,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
        "native_notes": "; ".join(notes),
    }


@mcp.tool
def reset() -> dict:
    """mem0 官方 reset 清存储 + 重建实例。幂等。
    ⚠️ P1 修复（2026-08-19 核查）：必须以 _drop_memory() 收尾——否则 _MEMORY 持有指向
    已删目录的悬挂句柄，后续 add 全部静默失败（readonly database，accepted_turns 假成功）。"""
    _drop_memory()
    try:
        _mem().reset()
    except Exception as e:
        print(f"[mem0-reset] reset 异常（降级为目录清理）: {e}", file=sys.stderr)
        _drop_memory()
        _state.hard_reset_dir()
    _state.hard_reset_dir()  # scopes.json 一并清掉
    _drop_memory()  # 关键：不留悬挂实例
    _stats.mark_reset()
    _stats.n_sessions = 0
    return {"ok": True, "cleared": {"system": "mem0"}}


@mcp.tool
def stats() -> dict:
    return _stats.to_dict(n_memories=_n_memories())


@mcp.tool
def snapshot(tag: str) -> dict:
    _drop_memory()  # 确保目录无句柄占用
    time.sleep(0.1)
    r = _state.snapshot(tag)
    _stats.snapshots = _state.tags()
    return r


@mcp.tool
def restore(tag: str) -> dict:
    _drop_memory()
    r = _state.restore(tag)
    if not r.get("ok") and r.get("error") == "SNAPSHOT_NOT_FOUND":
        return r
    _stats.snapshots = _state.tags()
    _mem()  # 触发重建，校验快照可加载
    return r


if __name__ == "__main__":
    mcp.run()  # stdio

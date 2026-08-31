# llm.py：Anthropic 兼容答题/判分客户端（bench-design §2.1/§5）
# endpoint 走 .env 的 MEMBENCH_ANSWER_*；判分可用 MEMBENCH_JUDGE_* 覆盖。
# 当前用智谱 Anthropic 面（glm-5.3，thinking on）。vLLM/ngrok 那条路径 2026-08-30 已停用，
# .env 里已注释（`# [vLLM]` 前缀）；如需恢复见下方 thinking 语义注释的第二段。
# 依赖 httpx（已有），不引 anthropic SDK——网关只开 Anthropic 兼容面。

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]

_ANTHROPIC_HEADERS = {"anthropic-version": "2023-06-01", "ngrok-skip-browser-warning": "1"}


def load_dotenv(path: Path | None = None) -> None:
    """极简 .env 加载（与 scripts/smoke_test.py 同约定），不引入 python-dotenv。"""
    p = path or REPO / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


_RL_BACKOFF = [5, 10, 20, 30, 45, 60, 60, 60]  # 429 限流退避序列（网关分钟级 RPM 窗口）


class LLMError(Exception):
    """单次调用最终失败（重试耗尽）。"""


class Suspended(Exception):
    """连续失败达到挂起阈值（bench-design §7），run 落盘退出。"""


class AnthropicCompat:
    """最小 Anthropic /v1/messages 客户端：temp=0、thinking 显式可控、指数退避重试。

    thinking 语义（2026-08-29 实测，两个后端行为不同，勿混用）：
      · 智谱 Anthropic 面（open.bigmodel.cn/api/anthropic）
          thinking={"type":"disabled"} → thinking block 实测 0 字符，out 45 tok（真关掉）
          不传该参数           → 默认开，thinking 679 字符，out 185 tok
      · vLLM 网关（Anthropic 兼容面）——**已停用，未实现**
          thinking={"type":"disabled"} ❌ 无效，需 chat_template_kwargs={"enable_thinking":false}
          2026-08-30 决策：不接这条路径，统一用智谱并保持 thinking on。
          将来若恢复 vLLM，需在下方 body 构造处按端点分支加 chat_template_kwargs。

    thinking 是**实验变量**（考试是否贴近真实用户场景），不是固定配置：
    开关状态由 MEMBENCH_*_THINKING 控制，并由 runner 写入 run manifest 留痕。
    """

    def __init__(self, base: str, key: str, model: str, timeout: float = 300.0,
                 max_retries: int = 3, thinking: bool = False,
                 max_tokens: int = 600) -> None:
        self.base = base.rstrip("/")
        self.key = key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.thinking = thinking
        # thinking 开时 reasoning 与正文共用 max_tokens，额度不足会 stop_reason=max_tokens
        # 且 content 为空 → PARSE_ERROR。默认值按开关分档，可用 MEMBENCH_*_MAX_TOKENS 覆盖。
        self.max_tokens = max_tokens

    async def chat(self, client: httpx.AsyncClient, system: str, user: str,
                   max_tokens: int | None = None, temperature: float = 0.0) -> tuple[str, dict]:
        """返回 (拼接文本, usage)。429 限流长退避（网关 RPM 限制，2026-08-21 实测）；5xx/网络短退避；其余 4xx 直接 LLMError。"""
        body = {
            "model": self.model,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if not self.thinking:
            # 显式关闭；开启时不传参数，走 provider 默认态（实测即为开），manifest 记 on(provider-default)
            body["thinking"] = {"type": "disabled"}
        headers = {"x-api-key": self.key, "content-type": "application/json", **_ANTHROPIC_HEADERS}
        last_err: Exception | None = None
        attempt = 0
        while True:
            try:
                r = await client.post(f"{self.base}/v1/messages", json=body, headers=headers,
                                      timeout=self.timeout)
                if r.status_code == 200:
                    d = r.json()
                    text = "".join(b.get("text", "") for b in d.get("content", []))
                    if "<think>" in text.lower():
                        # thinking 未关干净：剥掉再返回（防御，2026-08-21 smoke 已确认无污染）
                        text = _strip_think(text)
                    return text, d.get("usage", {})
                if r.status_code == 429:
                    # 限流：分钟级窗口，长退避，重试额度宽（挂起交给上层阈值，这里别轻易放弃）
                    wait = _RL_BACKOFF[min(attempt, len(_RL_BACKOFF) - 1)]
                    last_err = LLMError(f"HTTP 429: {r.text[:80]}")
                    if attempt >= 8:
                        raise LLMError(f"429 退避耗尽（{attempt + 1} 次）: {last_err}")
                    await asyncio.sleep(wait)
                    attempt += 1
                    continue
                if r.status_code in (500, 502, 503, 504):
                    last_err = LLMError(f"HTTP {r.status_code}: {r.text[:120]}")
                else:
                    raise LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_err = LLMError(f"{type(e).__name__}: {e}")
            if attempt >= self.max_retries:
                raise LLMError(f"重试耗尽（{self.max_retries + 1} 次）: {last_err}")
            await asyncio.sleep(min(2**attempt, 30))
            attempt += 1


def _strip_think(text: str) -> str:
    """剥掉 <think>...</think> 段（qwen 系 thinking 泄漏防御）。"""
    import re
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()


def _env_thinking(name: str, default: bool = False) -> bool:
    """解析 on/off 型开关；未设时用 default。"""
    v = os.environ.get(name)
    if v is None or not v.strip():
        return default
    return v.strip().lower() in {"1", "on", "true", "yes", "enabled"}


# thinking 开时正文与 reasoning 共用额度：实测简单题 out=185 tok，复杂题（full_context ~15.8k
# evidence）更长，600 会截断成空 content。故按开关分档，可被 MEMBENCH_*_MAX_TOKENS 覆盖。
_MAX_TOKENS_THINK_ON = 2048
_MAX_TOKENS_THINK_OFF = 600


def _env_max_tokens(name: str, thinking: bool) -> int:
    v = os.environ.get(name)
    if v and v.strip():
        return int(v.strip())
    return _MAX_TOKENS_THINK_ON if thinking else _MAX_TOKENS_THINK_OFF


def answer_llm_from_env() -> AnthropicCompat:
    thinking = _env_thinking("MEMBENCH_ANSWER_THINKING", default=False)
    return AnthropicCompat(
        base=os.environ["MEMBENCH_ANSWER_BASE_URL"],
        key=os.environ["MEMBENCH_ANSWER_API_KEY"],
        model=os.environ["MEMBENCH_ANSWER_MODEL"],
        thinking=thinking,
        max_tokens=_env_max_tokens("MEMBENCH_ANSWER_MAX_TOKENS", thinking),
    )


def judge_llm_from_env() -> AnthropicCompat:
    """判分模型（bench-design §6.3）：默认同答题模型，MEMBENCH_JUDGE_* 可整组覆盖。

    judge 与答题同模型存在自我偏好（same-model bias），拆开是 D5；judge 单轮仅约 13M token，
    是换独立模型性价比最高的一处。
    """
    thinking = _env_thinking(
        "MEMBENCH_JUDGE_THINKING",
        default=_env_thinking("MEMBENCH_ANSWER_THINKING", default=False),
    )
    return AnthropicCompat(
        base=os.environ.get("MEMBENCH_JUDGE_BASE_URL", os.environ["MEMBENCH_ANSWER_BASE_URL"]),
        key=os.environ.get("MEMBENCH_JUDGE_API_KEY", os.environ["MEMBENCH_ANSWER_API_KEY"]),
        model=os.environ.get("MEMBENCH_JUDGE_MODEL", os.environ["MEMBENCH_ANSWER_MODEL"]),
        thinking=thinking,
        max_tokens=_env_max_tokens("MEMBENCH_JUDGE_MAX_TOKENS", thinking),
    )

# llm.py：Anthropic 兼容答题/判分客户端（bench-design §2.1/§5）
# endpoint 走 .env 的 MEMBENCH_ANSWER_*（ngrok → Linux vLLM）；判分可用 MEMBENCH_JUDGE_* 覆盖（模型待定决策）。
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
    """最小 Anthropic /v1/messages 客户端：temp=0、无 thinking、指数退避重试。"""

    def __init__(self, base: str, key: str, model: str, timeout: float = 300.0,
                 max_retries: int = 3) -> None:
        self.base = base.rstrip("/")
        self.key = key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    async def chat(self, client: httpx.AsyncClient, system: str, user: str,
                   max_tokens: int = 512, temperature: float = 0.0) -> tuple[str, dict]:
        """返回 (拼接文本, usage)。429 限流长退避（网关 RPM 限制，2026-08-21 实测）；5xx/网络短退避；其余 4xx 直接 LLMError。"""
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
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


def answer_llm_from_env() -> AnthropicCompat:
    return AnthropicCompat(
        base=os.environ["MEMBENCH_ANSWER_BASE_URL"],
        key=os.environ["MEMBENCH_ANSWER_API_KEY"],
        model=os.environ["MEMBENCH_ANSWER_MODEL"],
    )


def judge_llm_from_env() -> AnthropicCompat:
    """判分模型待定（bench-design §6.3）：默认同答题模型，MEMBENCH_JUDGE_* 可覆盖。"""
    return AnthropicCompat(
        base=os.environ.get("MEMBENCH_JUDGE_BASE_URL", os.environ["MEMBENCH_ANSWER_BASE_URL"]),
        key=os.environ.get("MEMBENCH_JUDGE_API_KEY", os.environ["MEMBENCH_ANSWER_API_KEY"]),
        model=os.environ.get("MEMBENCH_JUDGE_MODEL", os.environ["MEMBENCH_ANSWER_MODEL"]),
    )

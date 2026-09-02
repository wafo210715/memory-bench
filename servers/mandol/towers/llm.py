"""构建层 LLM 客户端（Phase 2）。

契约对齐（interface-spec §7 公平性配置）：
  · endpoint/模型  MEMBENCH_LLM_BASE_URL / MEMBENCH_LLM_MODEL（与 mem0/graphiti/amem 同一套）
  · temperature    强制 0

    ⚠️ 官方 dataset_maker 用 temperature=0.1（实体去重 0.05），本实现覆盖为 0。
    依据：§7「所有系统内部调 LLM 必须同一 endpoint、同一模型、temperature=0」，
    且项目已有先例——amem server 同样把官方默认 0.7 强制改为 0 并声明违约。
    这是**有意的、需在论文中声明的偏离**，不是疏漏。

  · reasoning_effort  low（extra_body 注入，与 mem0/amem 同款手法）

保持官方的部分：max_tokens 逐步不同（L0=250 / L1=4000 / L2=8000 等）、
max_retries=3、JSON 解析的 markdown 围栏剥离与花括号兜底——均逐条对齐 dataset_maker。
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

# 429 退避序列与 bench/llm.py 保持一致（网关分钟级 RPM 窗口）
_RL_BACKOFF = [5, 10, 20, 30, 45, 60, 60, 60]


class TowerLLMError(Exception):
    pass


class TowerLLM:
    """线程安全的构建层 LLM 客户端，供 ThreadPoolExecutor 并发调用。"""

    def __init__(self, model: str | None = None, temperature: float = 0.0,
                 reasoning_effort: str = "low", max_retries: int = 3,
                 retry_delay: float = 2.0) -> None:
        from openai import OpenAI

        base = os.environ.get("MEMBENCH_LLM_BASE_URL")
        key = os.environ.get("MEMBENCH_LLM_API_KEY")
        self.model = model or os.environ.get("MEMBENCH_LLM_MODEL")
        missing = [k for k, v in (("MEMBENCH_LLM_BASE_URL", base),
                                  ("MEMBENCH_LLM_API_KEY", key),
                                  ("MEMBENCH_LLM_MODEL", self.model)) if not v]
        if missing:
            raise TowerLLMError(f"缺少环境变量: {missing}（interface-spec §7）")

        self._client = OpenAI(base_url=base, api_key=key, timeout=180.0, max_retries=0)
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        self._lock = threading.Lock()
        self.calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.failures: list[str] = []

    # ---------- 统计 ----------

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"calls": self.calls, "tokens_in": self.tokens_in,
                    "tokens_out": self.tokens_out, "failures": len(self.failures)}

    def _account(self, usage: Any) -> None:
        if usage is None:
            return
        with self._lock:
            self.tokens_in += int(getattr(usage, "prompt_tokens", 0) or 0)
            self.tokens_out += int(getattr(usage, "completion_tokens", 0) or 0)

    # ---------- 原始调用 ----------

    def complete(self, prompt: str, max_tokens: int = 4000,
                 context_id: str = "-") -> str | None:
        """单次补全，带 429 长退避 + 5xx 短退避。失败返回 None。"""
        last_err: Exception | None = None
        for attempt in range(len(_RL_BACKOFF)):
            try:
                resp = self._client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.temperature,
                    max_tokens=max_tokens,
                    extra_body={"reasoning_effort": self.reasoning_effort},
                )
                with self._lock:
                    self.calls += 1
                self._account(getattr(resp, "usage", None))
                return (resp.choices[0].message.content or "").strip()
            except Exception as e:  # noqa: BLE001
                last_err = e
                msg = str(e)
                if "429" in msg or "rate" in msg.lower():
                    time.sleep(_RL_BACKOFF[min(attempt, len(_RL_BACKOFF) - 1)])
                elif any(c in msg for c in ("500", "502", "503", "504")) or "timeout" in msg.lower():
                    time.sleep(min(2 ** attempt, 20))
                else:
                    break  # 其余 4xx 直接放弃，不空转
        with self._lock:
            self.failures.append(f"{context_id}: {last_err}")
        return None

    # ---------- JSON 调用（对齐官方 _call_llm_with_retry + _parse_json_response）----------

    @staticmethod
    def parse_json(response: str | None) -> dict[str, Any] | None:
        """逐条对齐 dataset_maker 的 _parse_json_response（step2_extract_l1.py:638）。"""
        if not response:
            return None
        text = response.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        try:
            start, end = text.find("{"), text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass
        return None

    def complete_json(self, prompt: str, max_tokens: int = 4000,
                      context_id: str = "-") -> dict[str, Any] | None:
        """带 JSON 解析重试。max_retries 默认 3，与官方一致。"""
        for attempt in range(self.max_retries):
            parsed = self.parse_json(self.complete(prompt, max_tokens, context_id))
            if parsed is not None:
                return parsed
            if attempt < self.max_retries - 1:
                time.sleep(self.retry_delay)
        with self._lock:
            self.failures.append(f"{context_id}: JSON 解析连续 {self.max_retries} 次失败")
        return None

# atommem/extractor：按论文理念复现的 Fact Executor（A1 intake + A2 distill）
#
# 为什么要自己写这一层（paper-vs-code 差异 1，能力损失/高）：
#   论文的一号贡献是把 Qwen3-14B 用 LoRA 微调成事实抽取器（Eq.1；§4.1），但上游仓库
#   既无权重也无训练/推理依赖，跑分链路 evaluate_locomo.py:744 → preextracted_pipeline.py:49
#   直接从磁盘读一份现成事实 JSON。memory-bench 灌进来的是 LoCoMo 原始 turns，
#   没有那份文件，这一步必须补。
#
# 补法（用户 2026-09-10 定：论文理念优先于照抄代码，见 memory-system-analysis §4）：
#   提示词逐条对齐论文 Figure A.1（txt:1189-1207）的五条规则，而不是上游
#   run_atommem_pipeline.py:142 FactExtractor.extract_turn 里那份仓库自带提示词——
#   后者丢了"改写第三人称"和"视觉信息作主要来源"两条（差异 13）。
#   模型不是论文的微调 Qwen3-14B，而是全 arm 统一的内部 LLM（glm-5.3, temperature=0，
#   interface-spec §7）——抽取器本身无法复现，统一 backbone 是可比性的下限要求。
#
# 已知口径缺口（必须显式声明，不藏）：
#   Figure A.1 第 4 条多模态整合在本口径下无输入。LoCoMo 原始数据有 blip_caption / img_url，
#   但 harness 的 loaders/locomo.py:98 只把 {role, content, timestamp} 交给 add_conversation，
#   图像描述在 loader 层就已丢弃。规则仍写进提示词（无图时自然不触发），
#   但"AtomMem 的多模态能力"在本次评测中未被测到。

import json
from typing import Any

# 逐条对应 Figure A.1 的 Extraction Guidelines & Rules。规则文本贴论文原文，
# 只把"Output strictly in JSON format"具体化为 {"facts": [...]}——上游 LLMInterface
# 对 json 调用会传 response_format={"type":"json_object"}，裸 JSON array 不被该模式接受；
# 这是承载格式的工程适配，不改五条规则的语义。
SYSTEM_PROMPT = """Task: Extract useful, standalone and high-value facts from the current message, using recent conversation context when necessary. Each fact must be complete without additional context.

Extraction Guidelines & Rules:
1. Filter low-value content
- Ignore "noise" (greetings, fillers, acknowledgments, or conversational "fluff").
- Only extract facts with objective value, specific opinions, or significant emotional states.
- If no high-value facts exist, output an empty fact list.
2. Resolve references
- Replace all pronouns (it, they, this, that) and temporal markers (yesterday, now, last week) with explicit entities and absolute dates based on the metadata or context.
3. Rewrite in third person
- Convert all first-person statements into third-person facts. Attributes must be linked to a specific name, e.g., "The user", "Alice" or "Bob".
- Include explicit attribution for subjective content, e.g., "The user believes..." or "Alice expressed frustration regarding...".
4. Multimodal Integration
- If [Image Description] or [Image Keywords] are present, treat the visual data as a primary source. Synthesize the visual information naturally into the text facts.
5. Output
- If multiple distinct facts exist, extract them separately.
- Write each fact in the same language as the source message.
- Output strictly in JSON format: {"facts": ["fact 1", "fact 2", ...]}. Use {"facts": []} when nothing is worth keeping."""

# 「same language as the source message」是论文没有的一句工程补充：论文只在全英文语料
# （LoCoMo / LongMemEval）上跑，没有跨语言规定，而规则 3 的第三人称改写在中文输入上
# 会诱导模型改用英文输出，导致事实与原文不同语言、检索侧关键词对不上。
# 对 LoCoMo 无影响（本来就是英文），只保证中文样本（smoke test）不被静默翻译。


class PaperFactExtractor:
    """论文理念抽取器。共用 pipeline 的 LLMInterface 实例，token 自动汇入 internal_llm 统计。"""

    def __init__(self, llm: Any) -> None:
        self.llm = llm
        self.n_calls = 0
        self.n_parse_fail = 0     # 模型返回了但结构不可用
        self.n_api_fail = 0       # 调用本身失败（重试耗尽）
        self.n_facts = 0

    def extract_turn(
        self,
        current: dict,
        previous: dict | None,
        session_time: str,
    ) -> list[str]:
        """抽一条 turn。current/previous: {dia_id, speaker, text}；session_time: YYYY-MM-DD。

        上下文窗口取前一条（config.CONTEXT_WINDOW_K 默认 1，与上游一致；
        论文只说 "using recent conversation context when necessary"，未给具体 K）。
        """
        context = ""
        if previous:
            context = (
                "\nPrevious dialogue:\n"
                f"[{previous.get('dia_id')}] {previous.get('speaker')}: {previous.get('text')}"
            )

        user_prompt = (
            f"{context}\n\nCurrent dialogue:\n"
            f"[{current.get('dia_id')}] {current.get('speaker')}\n"
            f"Time: {session_time}\n"
            f"Text: \"{current.get('text', '')}\""
        )

        result = self.llm.call_with_retry(
            SYSTEM_PROMPT, user_prompt, response_format="json", call_type="fact_extraction"
        )
        self.n_calls += 1

        facts, kind = self._parse(result)
        if kind == "api_fail":
            self.n_api_fail += 1
            return []
        if kind == "parse_fail":
            self.n_parse_fail += 1
            return []
        self.n_facts += len(facts)
        return facts

    def _parse(self, result: Any) -> tuple[list[str], str]:
        """返回 (facts, kind)，kind ∈ ok | api_fail | parse_fail。

        三者必须分开："模型判定无高价值事实"（规则 1 的合法空结果）、
        "调用没成功"（要报 PARTIAL_INGEST）、"返回了但结构不对"（提示词或模型问题）。
        合并统计会让 native_notes 里的失败数无法归因。
        """
        if isinstance(result, list):                    # 模型直接回了 JSON array
            return [str(f).strip() for f in result if str(f).strip()], "ok"
        if not isinstance(result, dict):
            return [], "parse_fail"
        if "error" in result:                           # LLMInterface 的调用失败标记
            return [], "api_fail"
        if "raw_content" in result:                     # 上游的 JSON 解析失败标记，再试一次
            try:
                reparsed = json.loads(result["raw_content"])
            except (json.JSONDecodeError, TypeError):
                return [], "parse_fail"
            return self._parse(reparsed)

        raw = result.get("facts")
        if raw is None:                                 # 容忍 {"atomic_facts": [...]} 之类的别名
            raw = next((v for v in result.values() if isinstance(v, list)), None)
        if not isinstance(raw, list):
            return [], "parse_fail"
        return [str(f).strip() for f in raw if str(f).strip()], "ok"

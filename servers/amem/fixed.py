# amem-fixed：A-MEM 的「按论文理念修复」臂（对照原生臂 amem）
#
# 不改上游 repo（agiresearch/A-mem），全部修复以子类 + override 实现，原生臂一行不动。
# 每处修复对应论文的一条明确主张，编号与 2026-08-30 讨论的对照表一致：
#
#   F1  论文 Eq.2  Ki, Gi, Xi ← LLM(ci ∥ ti ∥ Ps1)（note construction）
#       上游实现：`analyze_content()` 写完整了（含论文 Ps1 原文 prompt），但**全仓库无任何调用点**。
#       add_note 直接 MemoryNote(content=...)，keywords/context/tags 全走默认值
#       （[] / "General" / []）——而这恰好等于 analyze_content 失败时的 fallback，行为上看不出破绽。
#       后果：论文 §3.1 的 note construction 从未发生；唯一真实的 LLM 调用是 evolution，
#       而它的 prompt 里 `keywords: []`、`context: General` 也都是空的。
#       修复：add_note 时调 analyze_content 填充三个语义字段。
#       ⚠️ F3 依赖本项——不补 F1，F3 拼进向量的就是空列表和 "General"。
#       ⚠️ 成本：每条 note 额外一次 LLM 调用（与 evolution 共计两次/note）。
#
#   F3  论文 Eq.3  ei = fenc[concat(ci, Ki, Gi, Xi)]
#       上游实现：add_document(note.content, ...) —— ChromaDB 只对 documents 编码，
#       metadata 不参与向量化，实测两条 context 迥异的 note embedding L2 距离 = 0.0。
#       修复：把 content + keywords + tags + context 拼成 embed 文本作为 document，
#       原文仍存在 metadata.content 里，检索返回不受影响。
#
#   F4  论文 Eq.6  Li ← LLM(mn ∥ Mnear ∥ Ps2)
#       上游实现：喂给 LLM 的 memory_str 只有 `memory index:0..4`，真实 UUID 从未出现，
#       LLM 无从返回有效 id，links 里存的是 "0"/"1" 之类无效值。
#       修复：memory_str 携带真实 memory id，并在 prompt 中要求按 id 返回。
#       ⚠️ F8 依赖本项——不修 F4 只修 F8，沿链扩展仍然取不到任何邻居。
#
#   F5  论文 Eq.7  对 Mnear 中每个 mj 更新其 context/keywords/tags
#       上游实现：find_related_memories 返回的 indices 是检索排名序号 [0..k-1]，
#       process_memory 却拿它当 list(self.memories.values()) 的下标，
#       实际改写的是「最早插入的前 k 条」。实测两个集合完全不同。
#       修复：改用真实 doc_id 定位邻居。
#
#   F8  论文 Fig.2  "similar memories that are linked within the same box are also automatically accessed"
#       上游实现：邻居追加在直接命中之后，末尾 `return memories[:k]` 全部截掉，实测恒为 0 条。
#       修复：总预算仍为 k（与其他 arm 同口径），按 ratio 为邻居预留配额。
#
#   F-emb  换 embedding-3（2048d 云端），与 mem0/graphiti/mandol/rag_baseline 同口径。
#          原生臂的 all-MiniLM-L6-v2（384d）是已知偏离（interface-spec §7）。
#
#   F-dirty 修了 F3 之后，evolution 改写 context/tags 就必须让向量跟着变，否则改了白改
#          （这正是上游那个「metadata 改了 embedding 不重算」问题的真身）。
#          即时重算每条邻居一次 embed 调用太贵（LoCoMo ~6k turns × 5 邻居 = 3w 次），
#          改为 dirty 标记 + 批量 flush，由 server 层在 add_conversation 末尾统一触发。

import json
import logging
import os
import re
import time

from agentic_memory.memory_system import AgenticMemorySystem, MemoryNote

from servers.amem.embedding import CloudChromaRetriever, CloudEmbeddingFunction

logger = logging.getLogger(__name__)

# ── 可调参数（全部走 env，便于敏感性分析）─────────────────────────────
# 写入侧邻居数：保持上游默认 5（2026-08-30 决策：这是 A-MEM 构图的固有设定，不动）
WRITE_K = int(os.environ.get("MEMBENCH_AMEM_WRITE_K", "5"))
# 429 退避：智谱端点在密集 ingest 时会限流（code 1302）
RETRY_MAX = int(os.environ.get("MEMBENCH_AMEM_RETRY", "4"))
# 上游 llm_controller.py:34 把 max_tokens=1000 写死。那是 2025 年初为 gpt-4o-mini（不思考）
# 定的预算；换成推理模型后，思考与正式回复共用同一额度，1000 会被思考吃光 → content 为空
# → json.loads 报 'Expecting value: line 1 column 1' → evolution 静默丢弃。
# 2026-08-30 决策：取 128k（智谱端点实测接受）——不人为限制输出，对齐真实应用场景。
# 写死的 token 预算本质上是对某一代模型的隐含假设，不应留在评测链路上。
MAX_TOKENS = int(os.environ.get("MEMBENCH_AMEM_MAX_TOKENS", "128000"))
# D1(B)：JSON 畅形时重试次数。glm-5.3 对 json_schema 的遵守不稳定（fence / Extra data /
# Unterminated string 都实测到过），不重试的话机制价值会被格式问题吃掉三分之二。
JSON_RETRY = int(os.environ.get("MEMBENCH_AMEM_JSON_RETRY", "2"))
# 推理深度：与其他 arm 同口径（interface-spec §7），默认 low
THINKING = os.environ.get("MEMBENCH_THINKING", "low")
# 重试时追加的硬格式约束（首次不加，保持与论文 prompt 一致）
_JSON_NUDGE = (
    "\n\nIMPORTANT: Respond with ONLY the raw JSON object. "
    "No markdown code fences, no explanation before or after, no trailing text. "
    "Ensure every string is properly closed and the JSON is complete."
)
# 检索侧邻居配额比例：k=20 且 ratio=0.25 → 15 条直接命中 + 5 条沿链邻居
NEIGHBOR_RATIO = float(os.environ.get("MEMBENCH_AMEM_NEIGHBOR_RATIO", "0.25"))


def loads_lenient(s: str) -> dict:
    """宽容 JSON 解析——工程容错，**不是论文机制**。

    glm-5.3 对 response_format=json_schema 的遵守不稳定：同一 prompt 有时返回裸 JSON，
    有时包在 ```json fence 里（2026-08-30 实测两种都出现过）。上游是裸 json.loads，
    遇到 fence 就抛 'Expecting value: line 1 column 1' 并被 except 吃掉 → evolution 静默失败。
    原生臂保留这个行为（它就是上游真实形态），fixed 臂容错，否则测不出机制价值。
    """
    s = (s or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return json.loads(s)


class FixedAgenticMemorySystem(AgenticMemorySystem):
    """按论文理念修复的 A-MEM。父类的 add_note / consolidate_memories 等入口保持同名同签名。"""

    def __init__(self, collection_name: str, llm_model: str):
        # 父类 __init__ 建的是写死的 "memories" collection（本地 MiniLM），与下面的 per-scope
        # collection 名不冲突；走完它只为拿到 llm_controller / _evolution_system_prompt 等字段。
        super().__init__(
            model_name="all-MiniLM-L6-v2",
            llm_backend="openai",
            llm_model=llm_model,
        )
        self.collection_name = collection_name
        self.embed_fn = CloudEmbeddingFunction()
        self.retriever = CloudChromaRetriever(collection_name, self.embed_fn)
        self._dirty: set[str] = set()   # F-dirty：待重算向量的 note id
        # 诊断计数：上报到 stats，用于判断机制是否真的跑起来了（而非静默失败）
        self.n_construct_ok = 0      # F1 note construction 成功次数
        self.n_evo_ok = 0            # evolution 解析成功
        self.n_evo_fail = 0          # evolution 失败（重试耗尽后仍失败）
        self.n_links = 0             # 累计建立的有效链接数
        self.n_llm_calls = 0         # 实际 LLM 请求数（含重试）
        self.n_json_retry = 0        # D1(B)：因 JSON 畅形触发的重试次数

    def _llm_json(self, prompt: str, schema: dict) -> dict:
        """带 429 退避 + JSON 重试 + 解除 max_tokens 限制的 LLM 调用。

        不走 llm_controller.get_completion（它写死 max_tokens=1000），直接调 client。

        ⚠️ 公平性配置在这里自己保证，**不能指望 server 层的 _pin_reasoning**：
        它写的是 `system.llm.client`，而 AgenticMemorySystem 上没有 .llm（真实路径是
        .llm_controller.llm），2026-08-30 实测确认其一直落在 AttributeError 的 except 分支里。
        故此处显式传 temperature=0 + reasoning_effort，对齐 interface-spec §7。
        """
        llm = self.llm_controller.llm
        cur = prompt
        json_tries = 0
        rate_tries = 0
        while True:
            try:
                r = llm.client.chat.completions.create(
                    model=llm.model,
                    messages=[
                        {"role": "system", "content": "You must respond with a JSON object."},
                        {"role": "user", "content": cur},
                    ],
                    response_format=schema,
                    temperature=0,
                    max_tokens=MAX_TOKENS,
                    extra_body={"reasoning_effort": THINKING},
                )
                self.n_llm_calls += 1
                return loads_lenient(r.choices[0].message.content)
            except ValueError as e:      # json.JSONDecodeError 是 ValueError 子类
                json_tries += 1
                self.n_json_retry += 1
                if json_tries > JSON_RETRY:
                    raise
                cur = prompt + _JSON_NUDGE   # D1(B)：重试时才加硬约束
                continue
            except Exception as e:
                msg = str(e)
                if "429" in msg or "1302" in msg or "rate" in msg.lower():
                    rate_tries += 1
                    if rate_tries > RETRY_MAX:
                        raise
                    time.sleep(2 ** rate_tries * 2)   # 4/8/16/32s
                    continue
                raise

    def analyze_content(self, content: str) -> dict:
        """F1：沿用上游 Ps1 prompt（论文原文），但走宽容解析 + 429 退避。"""
        prompt = (
            "Generate a structured analysis of the following content by:\n"
            "1. Identifying the most salient keywords (focus on nouns, verbs, and key concepts)\n"
            "2. Extracting core themes and contextual elements\n"
            "3. Creating relevant categorical tags\n\n"
            'Format the response as a JSON object with keys "keywords" (array of >=3 strings, '
            "excluding speaker names and times), \"context\" (ONE sentence summarizing main "
            'topic/domain, key points, intended purpose), "tags" (array of >=3 broad category strings).\n\n'
            "Content for analysis:\n" + content
        )
        schema = {"type": "json_schema", "json_schema": {"name": "response", "schema": {
            "type": "object",
            "properties": {
                "keywords": {"type": "array", "items": {"type": "string"}},
                "context": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["keywords", "context", "tags"],
        }}}
        try:
            out = self._llm_json(prompt, schema)
            self.n_construct_ok += 1
            return out
        except Exception as e:
            logger.error(f"[amem-fixed] analyze_content 失败: {e}")
            return {"keywords": [], "context": "General", "tags": []}

    # ── F3：进入向量的文本 ────────────────────────────────────────────
    @staticmethod
    def embed_text(note: MemoryNote) -> str:
        """论文 Eq.3 的 concat(ci, Ki, Gi, Xi)。

        带字段名的结构化拼接（而非裸空格连接）——embedding-3 对 `key: value` 结构更稳，
        且避免关键词串把原文语义冲淡。context 为默认值 "General" 时不拼（无信息量）。
        """
        parts = [note.content]
        kw = getattr(note, "keywords", None)
        tg = getattr(note, "tags", None)
        ctx = getattr(note, "context", None)
        if kw:
            parts.append(f"keywords: {', '.join(map(str, kw))}")
        if tg:
            parts.append(f"tags: {', '.join(map(str, tg))}")
        if ctx and str(ctx) != "General":
            parts.append(f"context: {ctx}")
        return "\n".join(parts)

    @staticmethod
    def _metadata(note: MemoryNote) -> dict:
        """metadata.content 始终保留原文——检索返回与 envelope 渲染都取这里，不受 F3 影响。"""
        return {
            "id": note.id,
            "content": note.content,
            "keywords": note.keywords,
            "links": note.links,
            "retrieval_count": note.retrieval_count,
            "timestamp": note.timestamp,
            "last_accessed": note.last_accessed,
            "context": note.context,
            "evolution_history": note.evolution_history,
            "category": note.category,
            "tags": note.tags,
        }

    def _index(self, note: MemoryNote) -> None:
        """(重)写入向量库：document 用 F3 富文本，metadata 用原文。"""
        try:
            self.retriever.delete_document(note.id)
        except Exception:
            pass
        self.retriever.add_document(self.embed_text(note), self._metadata(note), note.id)

    # ── F-dirty：批量重算 ────────────────────────────────────────────
    def flush_dirty(self) -> int:
        """把 evolution 改过 context/tags 的 note 重新编码。由 server 在 ingest 末尾调用。"""
        n = 0
        for nid in list(self._dirty):
            note = self.memories.get(nid)
            if note is not None:
                self._index(note)
                n += 1
        self._dirty.clear()
        return n

    # ── F4 + F5：邻居检索返回真实 id ──────────────────────────────────
    def find_related_with_ids(self, query: str, k: int) -> tuple[str, list[str]]:
        """上游 find_related_memories 丢弃了 doc_id 只回枚举序号；这里保留真实 id。"""
        if not self.memories:
            return "", []
        try:
            results = self.retriever.search(query, k)
            ids = results.get("ids") or []
            if not ids or not ids[0]:
                return "", []
            memory_str, doc_ids = "", []
            metas = results["metadatas"][0]
            for i, doc_id in enumerate(ids[0]):
                if i >= len(metas):
                    break
                m = metas[i]
                # F4：把真实 id 摆进 prompt，LLM 才可能返回有效 suggested_connections
                memory_str += (
                    f"memory id:{doc_id}\ttalk start time:{m.get('timestamp', '')}\t"
                    f"memory content: {m.get('content', '')}\t"
                    f"memory context: {m.get('context', '')}\t"
                    f"memory keywords: {m.get('keywords', [])}\t"
                    f"memory tags: {m.get('tags', [])}\n"
                )
                doc_ids.append(doc_id)
            return memory_str, doc_ids
        except Exception as e:
            logger.error(f"[amem-fixed] find_related_with_ids 失败: {e}")
            return "", []

    def process_memory(self, note: MemoryNote) -> tuple[bool, MemoryNote]:
        """重写 evolution：邻居用真实 id 定位（F5），links 用真实 id 落库（F4）。"""
        if not self.memories:
            return False, note

        neighbors_text, neighbor_ids = self.find_related_with_ids(note.content, k=WRITE_K)
        if not neighbors_text or not neighbor_ids:
            return False, note

        prompt = self._evolution_system_prompt.format(
            content=note.content,
            context=note.context,
            keywords=note.keywords,
            nearest_neighbors_memories=neighbors_text,
            neighbor_number=len(neighbor_ids),
        )
        schema = {
            "type": "json_schema",
            "json_schema": {
                "name": "response",
                "schema": {
                    "type": "object",
                    "properties": {
                        "should_evolve": {"type": "boolean"},
                        "actions": {"type": "array", "items": {"type": "string"}},
                        "suggested_connections": {"type": "array", "items": {"type": "string"}},
                        "new_context_neighborhood": {"type": "array", "items": {"type": "string"}},
                        "tags_to_update": {"type": "array", "items": {"type": "string"}},
                        "new_tags_neighborhood": {
                            "type": "array",
                            "items": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                    "required": [
                        "should_evolve", "actions", "suggested_connections",
                        "tags_to_update", "new_context_neighborhood", "new_tags_neighborhood",
                    ],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        }
        try:
            rj = self._llm_json(prompt, schema)
            self.n_evo_ok += 1
            if not rj.get("should_evolve"):
                return False, note

            for action in rj.get("actions", []):
                if action == "strengthen":
                    # F4：只接受真实存在的 id，过滤掉 LLM 编造/序号残留
                    sug = [s for s in rj.get("suggested_connections", [])
                           if s in self.memories or s in neighbor_ids]
                    note.links.extend(sug)
                    self.n_links += len(sug)
                    if rj.get("tags_to_update"):
                        note.tags = rj["tags_to_update"]
                elif action == "update_neighbor":
                    ctxs = rj.get("new_context_neighborhood", []) or []
                    tags = rj.get("new_tags_neighborhood", []) or []
                    # F5：按真实 id 定位，长度对不上时只处理能对上的前缀
                    for i, nid in enumerate(neighbor_ids):
                        tgt = self.memories.get(nid)
                        if tgt is None:
                            continue
                        changed = False
                        if i < len(ctxs) and ctxs[i]:
                            tgt.context = ctxs[i]
                            changed = True
                        if i < len(tags) and tags[i]:
                            tgt.tags = tags[i]
                            changed = True
                        if changed:
                            self.memories[nid] = tgt
                            self._dirty.add(nid)   # F-dirty：向量待重算
            return True, note
        except Exception as e:
            self.n_evo_fail += 1
            logger.error(f"[amem-fixed] process_memory 失败: {e}")
            return False, note

    # ── F3：add_note 走富文本索引 ─────────────────────────────────────
    def add_note(self, content: str, time: str | None = None, **kwargs) -> str:
        if time is not None:
            kwargs["timestamp"] = time
        # F1：上游从不调 analyze_content，这里补上（调用方已显式传入时不覆盖）
        if not any(k in kwargs for k in ("keywords", "context", "tags")):
            try:
                meta = self.analyze_content(content) or {}
                if meta.get("keywords"):
                    kwargs["keywords"] = meta["keywords"]
                if meta.get("context"):
                    kwargs["context"] = meta["context"]
                if meta.get("tags"):
                    kwargs["tags"] = meta["tags"]
            except Exception as e:
                logger.error(f"[amem-fixed] analyze_content 失败，退回默认值: {e}")
        note = MemoryNote(content=content, **kwargs)
        evo, note = self.process_memory(note)
        self.memories[note.id] = note
        self._index(note)
        if evo:
            self.evo_cnt += 1
        return note.id

    def consolidate_memories(self) -> None:
        # 重建 collection（同样不能用 get_or_create + 新 embedding_function，会触发冲突校验）
        self.retriever = CloudChromaRetriever(self.collection_name, self.embed_fn)
        for note in self.memories.values():
            self._index(note)
        self._dirty.clear()

    # ── F8：沿链扩展进入结果，总预算仍为 k ─────────────────────────────
    def search_agentic(self, query: str, k: int = 5) -> list[dict]:
        """直接命中占 k-reserve，沿链邻居占 reserve；总数恒为 k，与其他 arm 同口径。

        上游把邻居追加在 k 个直接命中之后再 [:k]，等于永远截掉。这里改为**先分配配额**：
        邻居不够时由直接命中回填，保证总条数不因链接稀疏而缩水。
        """
        if not self.memories:
            return []
        reserve = min(k - 1, max(1, int(round(k * NEIGHBOR_RATIO)))) if k > 1 else 0
        direct_quota = k - reserve
        try:
            # 多取一些直接命中，供邻居配额用不满时回填
            results = self.retriever.search(query, k)
            ids = results.get("ids") or []
            if not ids or not ids[0]:
                return []
            metas = results["metadatas"][0]
            dists = (results.get("distances") or [[]])[0]

            ranked: list[dict] = []
            for i, doc_id in enumerate(ids[0]):
                if i >= len(metas):
                    break
                m = metas[i]
                ranked.append({
                    "id": doc_id,
                    "content": m.get("content", ""),
                    "context": m.get("context", ""),
                    "keywords": m.get("keywords", []),
                    "tags": m.get("tags", []),
                    "timestamp": m.get("timestamp", ""),
                    "category": m.get("category", "Uncategorized"),
                    "is_neighbor": False,
                    "score": dists[i] if i < len(dists) else None,
                })

            out, seen = [], set()
            for item in ranked[:direct_quota]:
                out.append(item)
                seen.add(item["id"])

            # 沿 links 扩展（F4 保证了 links 里是真实 id）
            n_added = 0
            for item in list(out):
                if n_added >= reserve:
                    break
                mem = self.memories.get(item["id"])
                for link_id in (getattr(mem, "links", []) or []):
                    if n_added >= reserve or link_id in seen:
                        continue
                    nb = self.memories.get(link_id)
                    if nb is None:
                        continue
                    out.append({
                        "id": link_id,
                        "content": nb.content,
                        "context": nb.context,
                        "keywords": nb.keywords,
                        "tags": nb.tags,
                        "timestamp": nb.timestamp,
                        "category": nb.category,
                        "is_neighbor": True,
                        "score": None,
                    })
                    seen.add(link_id)
                    n_added += 1

            # 邻居没占满 → 用剩余直接命中回填，保证返回 k 条
            for item in ranked[direct_quota:]:
                if len(out) >= k:
                    break
                if item["id"] not in seen:
                    out.append(item)
                    seen.add(item["id"])
            return out[:k]
        except Exception as e:
            logger.error(f"[amem-fixed] search_agentic 失败: {e}")
            return []

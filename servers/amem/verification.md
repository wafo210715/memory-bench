# amem 架构文档复核报告

> 复核日期 2026-09-05
> 论文源：`literature/papers/Xu-2025-A-MEM-Agentic-Memory-for-LLM-Agents.txt`（3600 行，arXiv:2502.12110v11）
> 上游代码源：`repo/A-mem` @ `ceffb86`（2025-12-12，agiresearch/A-mem）
> 封装/修复臂代码源：`memory-bench` @ `947c136`，`servers/amem/{fixed,server,server_fixed,embedding}.py`
> 复核对象：`servers/amem/ARCHITECTURE.md`（主）+ `servers/amem/methodology-flow.md`（附）
>
> **三源结构说明**：本目录的 ARCHITECTURE.md 不是「论文 vs 代码」对照文档，而是 memory-bench
> 自建 **fixed 臂**（上游 A-Mem + 七处修复）的操作流程说明。因此本报告核对三条线：
> (a) 论文 → txt 行号；(b) 上游仓库 → `agentic_memory/*.py:NNN`；(c) fixed 臂 → `servers/amem/*.py:NNN`。

---

## 1. 总评

ARCHITECTURE.md 的**核心论断完全成立**，且是本次复核中证据最硬的一条：论文 §3.1 / Eq.2 要求的
note construction 在上游仓库中**确实从未执行**——`analyze_content()` 在全仓库（含 tests/、examples/、
README）只出现**一次**，就是它自己的 `def`（`memory_system.py:159`），零调用点；`add_note()` 直接
`MemoryNote(content=...)`（`memory_system.py:238`），keywords/context/tags 全落在默认值
`[] / "General" / []` 上，而这恰好等于 `analyze_content` 失败时的 fallback（`memory_system.py:231`），
从外部完全看不出破绽。文档对 F3/F4/F5/F8 四项上游失效的描述同样逐条属实（见 §2 与 §5.1）。

**最严重的问题只有一条，但是硬伤**：⑤「每 100 次成功演化 → consolidate」在 fixed 臂上**根本不存在**。
`FixedAgenticMemorySystem.add_note()` 覆盖了父类入口后只写了 `self.evo_cnt += 1`（`fixed.py:385-386`），
**没有阈值判断、没有调用点**；`fixed.py:389` 定义的 `consolidate_memories()` 全仓库无 caller；
server 层的 `_patch_consolidate()` 只挂在 native 分支（`server.py:230` 在 `else:` 里）。
文档括注的「（P9 修的，行为保留）」把一个只属于 native 臂的行为写进了 fixed 臂的主流程图。

其余问题都是精度而非事实层面的：多处措辞把「查询侧」和「文档侧」混为一谈（②）、把「逐条」说成
「批量」（flush_dirty）、把「每条 envelope 各自 600 字符」说成「共享 600 字符预算」（设计取舍③）。
数值与引用锚点方面，四个 commit hash 全部对得上，论文 Eq.2/Eq.3/Eq.6/§3.3 的编号引用全部命中，
`k=5 / k=20 / 25% / 1297 条` 全部可复现；只有 `0.563` 这个分数在所引 run 里复现不出来（实测 0.5392）。

同目录的 `methodology-flow.md`（2026-09-05）质量更高：抽检 20 处 `file.py:NNN` 锚点仅 2 处轻微漂移，
且它的三条「不确定处」经本轮核实**全部成立**，正好对应本报告的 A10 / A21 / A23。

---

## 2. 逐条核对表

判定：`✓` 属实 / `✗` 不实 / `◐` 部分属实或需加限定 / `?` 无法核实

### 2.1 `ARCHITECTURE.md` — 页首元信息（L1-6）

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| A1 | 页首 L3 | 「对应 commit `b3acfb2`（fixed 臂）+ `b5b43f1`（数据修正）」 | ✓ | `git log b3acfb2` = "A-MEM 第 4 层：新增 amem_fixed —— 论文机制对照臂"；`b5b43f1` = "A-MEM 数据修正：conv-26 的 fixed 臂补齐后重跑" | 两个 hash 与描述一一对应 |
| A2 | 页首 L4-5 | 「见 `docs/../research-vault` 的 `[[amem-paper-vs-code-benchmark]]`」 | ? | `memory-bench` 根目录无 `research-vault/`（`ls -a` 已确认），本会话挂载树只有 `literature / memory-bench / repo` | 跨库引用，本轮无法核实 |

### 2.2 `ARCHITECTURE.md` — 写入侧 ①-⑤（L8-36）

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| A3 | 写入侧标题 | 「ingest，每个 turn 一次」 | ✓ | `server.py:263-264` `for i, t in enumerate(turns): sysm.add_note(...)` | |
| A4 | L11 | turn 形如 `"user: [2023-05-08] Caroline: ..."` | ✓ | `loaders/locomo.py:93,97`（`prefix = f"[{dt[:10]}] "`、`content = f"{prefix}{t['speaker']}: {t['text']}"`，role 固定 user）；实测 envelope：`user: [2023-03-16] Gina: Thanks, Jon! ...` | 日期前缀由 harness 层加（`docs/interface-spec.md:169`） |
| A5 | ① L13 | 「note construction [LLM 调用 1/2]」 | ✓ | `fixed.py:370-378` 调 `analyze_content`；`fixed.py:327` 调 evolution。实测 `runs/amem-ab-3conv/system_stats.jsonl`：`n_construct_ok=852, n_evo_ok=850, n_llm_calls=1703` ≈ 2×note | 每 note 恰 2 次（无邻居的首条只 1 次，见 M12） |
| A6 | ① L14 | 「原文 → 一句话摘要 + ≥3 关键词 + ≥3 标签」 | ✓ | `fixed.py:175-177`（`"keywords" (array of >=3 strings ... "context" (ONE sentence ... "tags" (array of >=3`）；论文 Ps1 原文 txt:3147-3148「At least three keywords」、3151-3152「At least three tags」、3149「one sentence summarizing」 | prompt 的**要求**，非返回保证 |
| A7 | ① L15 | 「论文 Eq.2」 | ✓ | txt:351-353 `Ki, Gi, Xi ← LLM(ci ∥ti ∥Ps1)` 编号为 (2)，位于 §3.1 Note Construction（txt:334-336） | 编号与内容完全对应 |
| A8 | ① L15 | **「官方代码里这步从未执行」** | ✓ | `grep -rn analyze_content repo/A-mem --exclude-dir=.git` → **唯一命中 `memory_system.py:159`（其自身 def）**；`add_note` 在 `memory_system.py:238` 直接 `MemoryNote(content=content, **kwargs)`，无 kwargs 注入语义字段；默认值见 `memory_system.py:68-72` | 文档核心论断，**成立**。且上游 README:44,161 仍宣称"Creates contextual descriptions and tags"/"Let the system handle context and keyword generation" |
| A9 | ① L15 | 「我们补的 F1」 | ✓ | `fixed.py:369-378`（`if not any(k in kwargs for k in ("keywords","context","tags")): meta = self.analyze_content(content)`） | |
| A10 | ② L18 | 「用「原文+语义字段」拼成的**富文本做向量**（Eq.3，F3），在库里找 top-5 相似的老记忆」 | ◐ | `fixed.py:289` `self.find_related_with_ids(note.content, k=WRITE_K)` —— **查询侧传的是纯原文 `note.content`**；富文本只出现在**被检索的库内文档**一侧（`fixed.py:240` `add_document(self.embed_text(note), ...)`，`embed_text` 定义 `fixed.py:198-215`） | 查询/文档两侧口径不同，文档句子未区分。论文 Eq.3（txt:358-360）要求 en 也用 concat 编码 → 见 §5.2-D3 |
| A11 | ② L19 | 「k=5 **硬编码**，与官方一致」 | ◐ | 「与官方一致」✓：上游 `memory_system.py:605` `find_related_memories(note.content, k=5)` 字面量。「硬编码」✗ on fixed：`fixed.py:60` `WRITE_K = int(os.environ.get("MEMBENCH_AMEM_WRITE_K", "5"))` 是 env 可调默认值 | 同页 L116 自称"官方默认"更准确 |
| A12 | ③ L21 | 「evolution [LLM 调用 2/2]」 | ✓ | `fixed.py:326-327`；实测 stats 见 A5 | |
| A13 | ③ L22 | 「把新 note + 5 个邻居（**带真实 UUID**，F4）喂给 LLM」 | ✓ | `fixed.py:271-277` `memory_str += f"memory id:{doc_id}\t..."`；`fixed.py:293-299` 拼进 `_evolution_system_prompt`。对照上游 `memory_system.py:307` 只写 `memory index:{i}` | F4 描述属实 |
| A14 | ③ L23 | 返回 `should_evolve` | ✓ | `fixed.py:307,329` | |
| A15 | ③ L24 | 「suggested_connections（**只接受真实存在的 ID**）」 | ✓ | `fixed.py:335-336` `sug = [s for s in rj.get("suggested_connections", []) if s in self.memories or s in neighbor_ids]` | |
| A16 | ③ L25 | 「new_context / new_tags：每个邻居的新摘要和标签」 | ✓ | `fixed.py:342-343`（取 `new_context_neighborhood` / `new_tags_neighborhood`）、`fixed.py:350-354`（按位赋给 `tgt.context` / `tgt.tags`） | 位置对齐依赖上游 prompt 的"sequential order"约束（`memory_system.py:144`） |
| A17 | ③ L26 | 「"strengthen" → 新 note 的 links 加上选中邻居」 | ◐ | `fixed.py:337` ✓；但同一分支 `fixed.py:339-340` 还有 `if rj.get("tags_to_update"): note.tags = rj["tags_to_update"]` ——**新 note 自己的 tags 会被 evolution 覆盖**，文档未提 | 影响 F3 富文本内容；上游 `memory_system.py:683` 同样有此赋值 |
| A18 | ③ L27-28 | 「"update_neighbor" → 改写邻居的摘要/标签（**按真实 ID 定位**，F5），被改的邻居标记进 `_dirty`」 | ✓ | `fixed.py:345-358`（`for i, nid in enumerate(neighbor_ids): tgt = self.memories.get(nid)` … `self._dirty.add(nid)`）。对照上游错误实现 `memory_system.py:687-716`（`noteslist[indices[i]]`，`indices[i]==i`，改的是**最早插入的前 k 条**） | F5 描述属实 |
| A19 | ③ L29 | 「（原文 content 任何情况下不动）」 | ✓ | `grep "\.content = "` 全仓库仅命中 `memory_system.py:64`（构造函数）；fixed.py 无任何 `.content` 赋值 | |
| A20 | ④ L31-32 | 「新 note 写进内存 dict + chroma（document=富文本，metadata 存原文）」 | ✓ | `fixed.py:383-384`（`self.memories[note.id] = note` → `self._index(note)`）；`fixed.py:234-240`（delete+add，document=`embed_text`）；`fixed.py:218-232` `_metadata` 的 `"content": note.content` | 顺序也对：process_memory → 入 dict → 入库 |
| A21 | ⑤ L34-35 | **「每 100 次成功演化 → consolidate 用统一的向量模型和库名重建索引（P9 修的，行为保留）」** | **✗** | `fixed.py:385-387` 全文为 `if evo: self.evo_cnt += 1` / `return note.id` —— **无 `% evo_threshold` 判断、无 `consolidate_memories()` 调用**。`fixed.py:389` 的 `consolidate_memories()` 定义全仓库无 caller。`_patch_consolidate` 唯一调用点 `server.py:230` 位于 `else:`（native）分支内（`server.py:210` `if IS_FIXED:` / `217` `else:`）。上游该行为在 `memory_system.py:260-263` | **fixed 臂无 consolidate**。该行为只存在于 native 臂 |

### 2.3 `ARCHITECTURE.md` — session 末（L38-47）

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| A22 | 标题 L38 | 「每个 session 灌完时（`add_conversation` 末尾）」 | ✓ | `server.py:266-269`（turn 循环之后）；`bench/runner.py:176-181` 逐 session 调一次 `add_conversation` | |
| A23 | L41 | 「flush_dirty **[embedding 批量调用]**」 | ◐ | `fixed.py:243-252` `for nid in list(self._dirty): ... self._index(note)`，每条走 `delete_document` + 单条 `add_document`（`fixed.py:237-240`）→ `CloudEmbeddingFunction.__call__` 收到长度为 1 的 list（`embedding.py:67-77`，chunk=64 对单条无意义）→ **每条一次 embedding API 调用**。实测 `embed_calls=4986` vs 852 notes ≈ 5.85 次/note，与"逐条"吻合 | 真正的批量只在 restore（`server.py:440-444`）。同段下一行"逐条重算向量"自相矛盾 |
| A24 | L42 | 「逐条重算向量（delete+re-add）」 | ✓ | `fixed.py:237-240` | 与 A23 的"批量"标注冲突，此句为准 |
| A25 | L43 | 「**论文没写这步怎么落**」 | ✓ | 论文 §3.3（txt:403-405）仅 txt:422-423「The evolved memory mj* then replaces the original memory mj in the memory set M」；全文 grep `re-encode / recomput / re-embed / update the embedding` 零命中 | 否定式断言，成立 |
| A26 | L44 | 「没有它，③ 的改写对检索永远不生效（Eq.3 的必然推论）」 | ✓ | 论文 Eq.3 txt:358-360 `ei = fenc[concat(ci,Ki,Gi,Xi)]`；fixed 臂 document = `embed_text` 含 tags/context（`fixed.py:205-215`）→ 不重算则向量停留在旧语义。逻辑成立 | |
| A27 | L46 | 「就绪屏障（`count()` 一次，P10）」 | ✓ | `server.py:274-278` `_ready = sysm.retriever.collection.count()`，try/except 包裹 | |

### 2.4 `ARCHITECTURE.md` — 读取侧 ⑥-⑧（L49-66）

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| A28 | ⑥ L55-56 | 「query 编码 → **与全库比** → 按距离排序」 | ◐ | `fixed.py:409` `self.retriever.search(query, k)` → `retrievers.py:103` `self.collection.query(query_texts=[query], n_results=k)`。Chroma 默认 HNSW **近似**检索且只返回 k 条，不是"与全库比"的精确全排序 | 论文 Eq.9（txt:444-448）确实写的是对 ∀mi∈M 的精确 cosine；代码是 ANN |
| A29 | ⑦ L58 | 「k=20 → 直接命中 15 条 + 邻居预留 5 条（25%）」 | ✓ | `fixed.py:405-406` `reserve = min(k-1, max(1, round(k*0.25)))` → k=20 时 reserve=5, direct_quota=15；`runs/amem-ab-3conv/manifest.json` `top_k=20`；实测 `native_notes` "F8: 沿链邻居 5/20 条" 出现 1182/1185 次 | |
| A30 | ⑦ L59 | 「先取 top-15 直接命中」 | ✓ | `fixed.py:434-436` `for item in ranked[:direct_quota]` | |
| A31 | ⑦ L60 | 「沿这 15 条的 links 找邻居（跳过已见/已删）」 | ✓ | `fixed.py:440-449`（`for item in list(out)` → `mem.links` → `if n_added >= reserve or link_id in seen: continue` → `nb = self.memories.get(link_id); if nb is None: continue`） | |
| A32 | ⑦ L61 | 「填进预留槽（`is_neighbor=true` 标记）」 | ✓ | `fixed.py:458` `"is_neighbor": True` | |
| A33 | ⑦ L62 | 「邻居不够 5 条 → 用第 16-20 名直接命中回填，**总数恒为 20**」 | ◐ | 回填逻辑属实（`fixed.py:465-471` `for item in ranked[direct_quota:]`）。但候选池 `ranked` 只有 k=20 条（`fixed.py:409` 传 `k` 而非 `k+reserve`），而 `fixed.py:408` 的注释写着"多取一些直接命中"——**注释与代码不符**；库内 note < 20 时总数达不到 20 | 实测 envelope 数恒为 20（1185/1185），因每 scope note 数 ≥369 |
| A34 | ⑧ L64-65 | 「envelope 渲染（F9）每条 = 原文 + 〔一句话摘要〕+ 时间戳」 | ◐ | 成分属实：`server.py:312-315` `content = f"{content}〔{ctx}〕"`（且 `ctx != "General"` 才拼）、`server.py:318` 取 timestamp。但**渲染顺序**是 `- {时间戳} · {原文}〔{摘要}〕`（`envelope.py:9-17`），且整条 >600 字符会被截断为 `…`（`envelope.py:15-16`） | 实测：`- 2023-05-18T13:47:00 · user: [2023-05-18] Evan: ...〔Evan greets Sam ...〕` |

### 2.5 `ARCHITECTURE.md` — 跨进程 / 「检索路径上没有任何东西」（L68-80）

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| A35 | L71 | 「snapshot: 内存 notes 序列化成 `notes.json`（真正载体）」 | ✓ | `server.py:389-401` `_dump_notes` = `dict(vars(note))`；`server.py:472` 写 `notes.json`；`server.py:479` 注释"快照真正的载体是上面那份 notes.json" | |
| A36 | L72 | 「restore: 批量重灌 + 重算向量（P12 修成批量…）」 | ✓ | `server.py:440-444` `B = 512` 分批 `collection.add`；`embedding.py:71` 内部再按 64 分批调 API | |
| A37 | L72 | 「24s/1297 条」 | ◐ | **1297 ✓**：`logs/amem-ab-3conv.log:627-629` 三 scope 注入 419+369+509 = 1297；`system_stats.jsonl` 亦有 `n_memories: 1297`。**24s ?**：日志无该步计时，`server.py:410` 注释只写"几十秒完成" | 数量可复现，秒数不可 |
| A38 | L77 | 「时间：不排序、不衰减、不过滤」 | ✓ | `fixed.py:397-471` 与 `server.py:305-328` 全路径无任何时间比较/排序/过滤；排序键只有 Chroma distance | 否定式断言，成立 |
| A39 | L77 | 「原文 `[日期]` 前缀进向量是**唯一**的时序信号」 | ◐ | 前缀确实进向量（`fixed.py:205` `parts = [note.content]`）。但 F3 富文本还拼了 LLM 生成的 context/keywords（`fixed.py:209-214`），实测 context 里含明确日期（envelope: "a December 2023 mountain drive"）→ "唯一"过强 | |
| A40 | L78 | 「`retrieval_count` 永远不涨（官方就没写更新点，我们没补）」 | ✓ | 上游 grep：仅 `memory_system.py:41,55,80`（声明/初始化）与 `250,278,383`（写进 metadata），**无任何自增**。fixed 侧仅 `fixed.py:225` / `server.py:77` 读出 | 否定式断言，两侧均成立 |
| A41 | L79 | 「演化是单向的：邻居被改写，但不会反向补 links（照论文）」 | ✓ | `fixed.py:337` 只对新 note `note.links.extend(sug)`，无对 `tgt` 的 links 写入。论文 Eq.6（txt:388-392）亦只更新 mn 的 link set | |
| A42 | L80 | 「记忆永不删除：没有遗忘机制，links 只增不减」 | ◐ | fixed 臂机制层属实：无删除路径，links 只 `extend`。但 (a) 上游定义了从未被 server 调用的 `delete()`（`memory_system.py:398-413`）；(b) 论文 Ps3 的 JSON 示例列了 `"actions": ["strengthen", "merge", "prune"]`（txt:3203）——"照论文"并非无遗忘 | `_index` 里的 `delete_document` 是"删完立即重加"，不构成遗忘 |

### 2.6 `ARCHITECTURE.md` — 设计取舍 + 相关（L82-133）

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| A43 | ①L86-88 | 「评测无影响（runner 每 session 都会 flush）」 | ✓ | `bench/runner.py:176-184` 逐 session 一次 `add_conversation` → `server.py:268-269` 每次 flush | |
| A44 | ②L92-93 | 「`update_neighbor` 是原地覆盖（硬改）……论文 §3.3 就是 `mj* 替换 mj`」 | ✓ | 论文 txt:403-405 §3.3 标题；txt:415-420 Eq.7；txt:422-423「The evolved memory mj* then replaces the original memory mj in the memory set M」。代码 `fixed.py:351,354` 直接赋值覆盖 | 引用锚点精确 |
| A45 | ②L95-97 | 「graphiti/Zep 边失效是软改——旧关系标 `tinvalid` 而非物理删除，双时间轴可追溯」 | ✓ | `Rasmussen-2025-Zep-...txt:163-164`（t'created/t'expired + tvalid/tinvalid 四时间戳）、`:166-170`（"invalidates the affected edges by setting their tinvalid to the tvalid of the invalidating edge"） | 跨论文引用属实 |
| A46 | ②L99 | 「语义漂移未测，论文没讨论」 | ✓ | 论文 §3.3（txt:403-430）只到"progressively richer"，无漂移/退化讨论；全文无相关实验 | 否定式断言，成立 |
| A47 | ③L106 | 「环境变量 `MEMBENCH_AMEM_NEIGHBOR_RATIO` 可调」 | ✓ | `fixed.py:81` | |
| A48 | ③L106 | 「未做敏感性分析」 | ✓ | `grep -rn NEIGHBOR_RATIO memory-bench` 仅命中 `fixed.py:81,405` 与本文档 L104,106；无扫参脚本、无对应 run | 否定式断言，成立 |
| A49 | ③L111-112 | 「envelope 的 **600 字符上限内**，噪声邻居挤占的是直接命中的槽位」 | ◐ | 600 上限确实存在（`envelope.py:4` `MAX_CHARS = 600`），但它是**每条 envelope 各自**截断（`envelope.py:15-16`），**不是共享预算**。挤占来自 `fixed.py:405-406` 的 k=20 配额切分，与 600 无关 | 结论（存在 trade-off）对，给出的机制错 |
| A50 | ④L116 | 「写入侧 k=5（官方默认，构图密度参数）」 | ✓ | `memory_system.py:605`（上游字面量 5）；`fixed.py:60`（默认 "5"） | |
| A51 | ④L117 | 「读取侧 top_k=20（spec §7 全臂统一）」 | ✓ | `docs/interface-spec.md:154`「top_k **默认 20，全 arm 一致**（2026-08-30 由 5 改为 20）」；`runs/amem-ab-3conv/manifest.json` `"top_k": 20` | |
| A52 | ⑤L124 | 「fixed 的总分里混着 F9（摘要进上下文）的贡献」 | ✓ | `server.py:312-315` 仅 `IS_FIXED` 时把 context 拼进 envelope，native 不拼 → 两臂上下文内容不同源 | 归因风险描述属实 |
| A53 | ⑤L125-126 | 「引用 **0.563** 时需带此注脚」 | ? | 在 `runs/amem-ab-3conv/answers.jsonl` 中，`amem_fixed` judge 准确率 = **0.5392**（1185 题）；分 conv：conv-26 = 0.5477、conv-49 = 0.5306；`amem` = 0.4265（全 5 conv）/ 0.3958（配对 2 conv）。**任何切片都不等于 0.563** | 0.563 的来源在未挂载的 research-vault（见 A2），本轮无法核实；若引用需先对齐口径 |
| A54 | 相关L130-131 | 「实现代码：`fixed.py`（机制）、`embedding.py`（向量层）、`server.py`（双模式 MCP 层）」 | ✓ | 三文件均存在，职责与描述相符（`fixed.py` 全为 F1-F8 override；`embedding.py` 只有 CloudEmbeddingFunction/CloudChromaRetriever/no_chroma_reset；`server.py:39-41` 双模式开关） | |
| A55 | 相关L132 | 「上游缺陷修复：commit `8d986e4` → `af56715`（**四层**，按发现次序）」 | ◐ | 该区间只含**三层**：`8d986e4` 第1层(pin) / `1766bdd` 第2层(chroma 生命周期) / `af56715` 第3层(consolidate)。第 4 层是 `b3acfb2`（新增 amem_fixed），已在页首单列 | 区间端点与"四层"不自洽 |
| A56 | 相关L133 | 「实测结果：run `runs/amem-ab-3conv`（3 conv），commit `b5b43f1`」 | ◐ | run 配置确为 3 conv（`logs/amem-ab-3conv.log` "arms=['amem','amem_fixed'] convs=3 n=3"，即 conv-26/30/49）。但 `evidence/amem_fixed.jsonl` **只覆盖 2 个 conv**（conv-26 597 题 + conv-49 588 题，conv-30 缺失）；`evidence/amem.jsonl` 反而覆盖 5 个 conv（26/30/48/49/50） | 直接影响 A53 的分数口径 |

### 2.7 `methodology-flow.md`（附核，抽检 20 项）

| # | 文档小节 | 断言摘录 | 判定 | 证据 | 备注 |
|---|---|---|---|---|---|
| M1 | 来源与口径 L13 | 「本目录没有 `verification.md`」 | ✓ | 复核开始时 `servers/amem/` 只有 ARCHITECTURE.md + methodology-flow.md | 本报告即补上 |
| M2 | 来源与口径 L13 | 「节点与边已逐项回查 `fixed.py`、`embedding.py` 和 `server.py`」 | ✓ | 抽检 20 处行号锚点，18 处精确命中，2 处轻微漂移（M16/M19） | 锚点质量显著高于 ARCHITECTURE.md |
| M3 | L17 | 「fixed 臂实现源自 commit `b3acfb2`」 | ✓ | 同 A1 | |
| M4 | INGEST S | `server.py:256-265` 逐 turn 循环 | ✓ | 256 `@mcp.tool` / 257 def / 263-264 循环 | |
| M5 | INGEST EXT | `fixed.py:168-195,366-381`；失败回退 `[], General, []` | ✓ | `fixed.py:195` `return {"keywords": [], "context": "General", "tags": []}` | |
| M6 | INGEST NEAR | 「**新 note 原文作 query** → top-5 老 note；老 note document 是富文本」`fixed.py:255-279,284-299` | ✓ | `fixed.py:289` 传 `note.content` | 这是对 ARCHITECTURE A10 措辞的正确修订 |
| M7 | INGEST EVO | `fixed.py:293-363`；真实 UUID；失败则跳过演化 | ✓ | `fixed.py:360-363` except → `return False, note` | |
| M8 | INGEST GS | `fixed.py:332-358,381-384`；单向 UUID links；原文不改；neighbor context/tags 硬覆盖 | ✓ | 同 A18/A19/A41 | |
| M9 | INGEST RICH | `fixed.py:199-240`；content + keywords + tags + context | ✓ | `fixed.py:205-215` | |
| M10 | INGEST VS | `embedding.py:42-98; server.py:209-216,270-278` | ✓ | `embedding.py:42` CloudEmbeddingFunction / `:80-98` CloudChromaRetriever；`server.py:209-216` fixed 分支建 per-scope collection；`:274-278` count() 屏障 | |
| M11 | INGEST BATCH/REIDX | `server.py:266-269` / `fixed.py:234-252` | ✓ | 同 A22/A24 | 图中 `Sched:Batch` 命名与 A23 同源，实际逐条 |
| M12 | INGEST 边 | 「无邻居：**0 次 evolution LLM**」 | ✓ | `fixed.py:286-287`（`if not self.memories: return`）、`fixed.py:290-291`（无 neighbors 即 return），均在 `_llm_json` 之前 | 但 `analyze_content` 那次仍会发生 |
| M13 | RETRIEVE 标题 | 「benchmark 传 `top_k=20`，函数默认值为 5」 | ✓ | `server.py:287` `top_k: int = 5`；manifest `top_k=20` | |
| M14 | RETRIEVE FUSE | 「reserve=round(k×0.25)，**至少 1、至多 k-1**」`fixed.py:403-406,464-471` | ✓ | `fixed.py:405` `min(k-1, max(1, ...))` | |
| M15 | 环境退化 L90 | 「`MEMBENCH_AMEM_MODE` **默认是 native**」`server.py:38-41,209-230` | ✓ | `server.py:39` `os.environ.get("MEMBENCH_AMEM_MODE", "native")` | |
| M16 | 环境退化 L92 | 「embedding 端点或密钥缺失会在**初始化**/首次编码时报错」`embedding.py:26-39` | ◐ | `CloudEmbeddingFunction.__init__`（`embedding.py:48-52`）不读端点/密钥，只设 `self._client = None`；`_embed_client()` 惰性调用于 `__call__`（`embedding.py:68-69`）→ **只在首次编码时报错**，初始化阶段不会 | "不是静默降级"的结论 ✓ |
| M17 | 环境退化 L93 | 「多 scope 且未传 `filter.scope_id` 时只查 sidecar 中第一个 scope；除 `scope_id` 外的 filter 全部忽略并写进 `native_notes`」`server.py:291-295,332-335` | ✓ | `server.py:295` `sid = scope_ids[0]`；`server.py:332-335` 两条 native_notes 提示 | |
| M18 | 不确定处 1-3 | 三条存疑项 | ✓ | 三条**全部成立**：①=A10（query 用原文）②=A21（fixed 臂无 consolidate 调用点）③=A23（flush 逐条非批量） | 该文档的自我标注准确 |
| M19 | RETRIEVE GRAPH | `fixed.py:433-462` 沿 links 扩展 | ◐ | 图扩展实际在 `fixed.py:438-462`；`433-437` 是直达命中填充（`out, seen = [], set()` + `for item in ranked[:direct_quota]`） | 轻微漂移 |
| M20 | STATE RESTORE | 「Chroma batch=512，embedding chunk=64」`server.py:404-444,488-516` | ✓ | `server.py:440` `B = 512`；`embedding.py:71` `range(0, len(input), 64)` | |

---

## 3. 步骤清单 — 论文侧

来源：Xu et al. 2025 §3.1-§3.4 + Figure 2 caption + Appendix B。
**系统边界**：论文把 note construction / link generation / memory evolution / retrieval 全部划归记忆系统；
agent 的最终作答（用检索到的 context 构造 prompt 之后的生成）在系统之外。

### 写入侧（每次 agent-环境交互 → 一条 note）

| # | name（原文叫法） | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| P1 | Note Construction (§3.1, Eq.1-2) | 每次交互（每 turn） | `ci, ti` → `Ki`(keywords) `Gi`(tags) `Xi`(one-sentence context) | **1 次**，Ps1，抽取/标注角色（txt:3137-3154） | – | `P-EXTRACT` + `P-META`（同一次调用同时产出一句话笔记与关键词/标签） |
| P2 | dense representation (§3.1, Eq.3) | 每 note | `concat(ci,Ki,Gi,Xi)` → `ei` | no | 向量库 | `P-EMBED` |
| P3 | similarity retrieval (§3.2, Eq.4-5) | 每 note（入库前） | `en` → `Mnear`（top-k） | no | 向量库（读） | `P-DENSE` |
| P4 | Link Generation (§3.2, Eq.6) | 每 note | `mn ∥ Mnear ∥ Ps2` → `Li`（新 note 的 link set） | **1 次**，Ps2，连边角色（txt:3159-3170） | 图（新 note 的 links） | `P-LINK` |
| P5 | Memory Evolution (§3.3, Eq.7) | 每 note，对 `Mnear` 中每个 `mj` | `mn ∥ Mnear\mj ∥ mj ∥ Ps3` → `mj*`（新 context/keywords/tags），`mj* 替换 mj` | **1 次/邻居**（Eq.7 按 mj 写，txt:415-423） | 覆盖既有 note | `P-REVISE` [NEW] |
| P6 | （未命名，Eq.3 的必然推论） | — | 被改写的 `mj*` 的 `ej` 应重算 | no | 向量库 | `~P-EMBED`（**论文未写**，见 §5.1-D6） |

论文未描述任何持久化、去重、冲突消解、驱逐/遗忘步骤（Ps3 的 JSON 示例里出现过 `merge`/`prune`
两个动作名（txt:3203），但正文 1.1/1.2 只定义了 `strengthen` / `update_neighbor`，无对应机制描述）。

### 检索侧（每次 interaction 的 query）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| P7 | query encoding + cosine top-k (§3.4, Eq.8-10) | 每 query | `q` → `Mretrieved`（k=10，txt:907） | no | 向量库 | `P-DENSE` |
| P8 | linked memories auto-access（**仅 Figure 2 caption**，txt:296-297） | 每 query | 命中 note → 同 box 内 linked memories | no | 图 | `~P-GRAPHEXPAND`（§3.4 的公式里**没有**这一步） |
| P9 | prompt construction（txt:449-450） | 每 query | `Mretrieved` → agent prompt | no | – | `P-ASSEMBLE` |
| P10 | agent 作答 | 每 query | prompt → answer | 1（backbone） | – | `P-GENERATE`（**边界外**） |

---

## 4. 步骤清单 — 代码侧

### 4.1 上游仓库 `agiresearch/A-mem` @ `ceffb86`

**系统边界**：`AgenticMemorySystem` 类本体即记忆系统；没有 agent 循环，也没有作答代码。

#### 写入侧 `add_note()`（`memory_system.py:233-264`）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| C1 | `MemoryNote(content=...)` (`:238`) | 每次 add_note 调用 | 原文 → note（keywords=`[]`, context=`"General"`, tags=`[]`, links=`[]`） | **no** —— `analyze_content()` 从未被调用 | 内存 dict | `P-INTAKE` |
| C2 | `find_related_memories(note.content, k=5)` (`:288-313`, 由 `:605` 调) | 每 note | 原文 → top-5 的 `memory_str` + **枚举序号** `indices=[0..k-1]`（`:308`） | no | Chroma（读） | `P-DENSE` |
| C3 | evolution LLM (`:612-671`) | 每 note（`self.memories` 非空且有邻居） | prompt（Ps2+Ps3 **合并成一个** `_evolution_system_prompt`，`:127-157`） → JSON | **1 次** | – | `P-LINK` + `P-REVISE`（一次调用两件事） |
| C3a | `strengthen` (`:679-683`) | should_evolve 时 | `note.links.extend(suggested_connections)`；`note.tags = tags_to_update` | – | 内存 | `P-LINK`（**失效**：prompt 里只有 `memory index:i`（`:307`），LLM 拿不到真实 id） |
| C3b | `update_neighbor` (`:684-716`) | should_evolve 时 | `noteslist[indices[i]].context/.tags` 被覆盖 | – | 内存 dict | `P-REVISE`（**错标的**：`indices[i]==i`，改的是**最早插入的前 k 条**，不是检索到的邻居） |
| C4 | `self.memories[note.id] = note` (`:242`) | 每 note | – | no | 内存 dict（**不落盘**） | `P-PERSIST` |
| C5 | `retriever.add_document(note.content, metadata, id)` (`:258`) | 每 note | **只有原文**进 document；keywords/tags/context 只进 metadata（`retrievers.py:81-83`，metadata 不参与向量化） | no | Chroma | `P-EMBED`（**Eq.3 未实现**） |
| C6 | `consolidate_memories()` (`:260-263, 266-286`) | 每 **100** 次 `evo_label==True`（`evo_threshold=100`, `:97,124`） | 重建 collection + 全量 re-add | no | Chroma | `~P-EMBED`（全量重建） |

**注**：C3b 改写的 note **从不重新索引**（`add_document` 只对新 note 调），但因为 C5 只编码原文，
这个缺失在上游是"无害"的——它只在补了 F3 之后才变成必须（见 §5.2-E6）。

#### 检索侧 `search_agentic(query, k=5)`（`memory_system.py:509-588`）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| C7 | `retriever.search(query, k)` (`:516`) | 每 query | query → top-k（`is_neighbor=False`） | no | Chroma | `P-DENSE` |
| C8 | 组装 memory_dict (`:528-552`) | 每 query | metadata → result dict | no | – | `P-ASSEMBLE` |
| C9 | linked memories 追加 (`:554-583`) | 每 query | 沿 `links` 1 跳，追加在 k 个直达命中**之后** | no | 内存 dict | `P-GRAPHEXPAND` |
| C10 | `return memories[:k]` (`:585`) | 每 query | 截断 | no | – | `P-SELECT` —— **把 C9 全部截掉，实测 `is_neighbor` 恒为 0** |

上游另有 `search` / `_search` / `find_related_memories_raw` 等未被 memory-bench 使用的入口。

### 4.2 memory-bench fixed 臂（`MEMBENCH_AMEM_MODE=fixed`）

**系统边界**：
- **记忆系统本体**：`FixedAgenticMemorySystem`（fixed.py）的 add_note / process_memory / search_agentic / flush_dirty；`CloudChromaRetriever` 向量层。
- **MCP 封装层（bench 侧，但会改变机制可见行为）**：`server.py` 的 per-scope 实例化 + HOME 切换、`_pin_reasoning`、就绪屏障、F9 envelope 拼接、snapshot/restore。
- **评测脚本侧（边界外）**：`loaders/locomo.py` 的 `[日期]` 前缀与 `role: ` 拼接、`bench/runner.py` 的 session 切分与 top_k=20、答题/裁判 LLM。

#### 写入侧（`add_conversation` → 每 turn 一次 `add_note`）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| X0 | harness 拼装（`loaders/locomo.py:93,97`） | 每 turn | `speaker/text/date` → `"user: [YYYY-MM-DD] Speaker: text"` | no | – | `P-INTAKE`（**边界外**） |
| X1 | F1 note construction（`fixed.py:369-378` → `:168-195`） | 每 turn | 原文 → keywords / context(1 句) / tags | **1 次**（Ps1；失败回退 `[], "General", []`） | – | `P-EXTRACT` + `P-META` |
| X2 | F4 邻居检索（`fixed.py:289` → `:255-279`） | 每 turn | **原文** query → top-`WRITE_K`(=5) 的 memory_str（**带真实 UUID**）+ `doc_ids` | no | Chroma（读，库内文档是富文本） | `P-DENSE` |
| X3 | evolution（`fixed.py:326-359`） | 每 turn（有邻居时） | 新 note + 5 邻居 → `should_evolve/actions/...` | **1 次**（`_llm_json`，temp=0, reasoning=low, max_tokens=128000, JSON 重试 ≤2, 429 退避 ≤4） | – | `P-LINK` + `P-REVISE` |
| X3a | `strengthen`（`:333-340`） | – | 过滤后的真实 id → `note.links`；`tags_to_update` → **新 note 的 tags** | – | 内存 | `P-LINK` |
| X3b | `update_neighbor`（`:341-358`） | – | 按真实 UUID 覆盖邻居 `context`/`tags`；加入 `_dirty` | – | 内存 dict | `P-REVISE`（硬覆盖，无版本） |
| X4 | `self.memories[note.id] = note`（`:383`） | 每 turn | – | no | 内存 dict | `P-PERSIST` |
| X5 | F3 索引（`:384` → `:234-240` → `:198-215`） | 每 turn | `content + keywords + tags + context` → document；原文进 metadata | no | Chroma（delete+add） | `P-EMBED` |
| X6 | F-dirty flush（`server.py:266-269` → `fixed.py:243-252`） | **每 session 末** | `_dirty` 中每个 UUID **逐条** delete+re-add | no | Chroma | `~P-EMBED`（逐条重编码） |
| X7 | 就绪屏障（`server.py:274-278`） | 每 session 末 | `collection.count()` | no | Chroma | （工程屏障，无 prim） |

**fixed 臂没有的步骤**：consolidate（A21）、去重、冲突消解、驱逐/遗忘、`retrieval_count` 更新。

#### 检索侧（`retrieve` → `search_agentic(query, k=20)`）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| Y1 | scope 选取（`server.py:291-296`） | 每 query | `filter.scope_id` 或 sidecar 首个 scope | no | sidecar JSON | `P-SYMFILTER`（退化：只支持 scope_id，其余 filter 忽略并在 `native_notes` 声明） |
| Y2 | 向量检索（`fixed.py:409-431`） | 每 query | query → Chroma top-20（按 distance 排序） | no | Chroma | `P-DENSE` |
| Y3 | 配额切分（`fixed.py:405-406,433-436`） | 每 query | reserve=5 / direct_quota=15；先填 top-15 | no | – | `P-SELECT` |
| Y4 | 沿链扩展（`fixed.py:438-462`） | 每 query | 15 条种子的 `links` 1 跳，跳过已见/失效，最多 5 条，`is_neighbor=True` | no | 内存 dict | `P-GRAPHEXPAND` |
| Y5 | 回填（`fixed.py:464-471`） | 每 query | 邻居不足时用 ranked[15:20] 补齐到 20 | no | – | `P-FUSE`（**配额式**合并，非分数融合） |
| Y6 | F9 envelope（`server.py:307-328` + `envelope.py:7-17`） | 每 query | `- {ts} · {原文}〔{context}〕`，≤600 字符截断 | no | – | `P-ASSEMBLE` |
| Y7 | 答题 | 每 query | envelope → answer | 1（backbone glm-5.3） | – | `P-GENERATE`（**边界外**） |

#### 跨进程旁路（bench 侧）

| # | name | trigger | in → out | llm | store | prim |
|---|---|---|---|---|---|---|
| Z1 | snapshot（`server.py:389-401,447-485`） | 逐 conv + run 末（`bench/runner.py:190,194`） | `vars(note)` → `notes.json`（+ homes/ + scopes.json）；`actual==0 && expected>0` 时拒绝写空 | no | 磁盘 JSON | `P-PERSIST` |
| Z2 | restore（`server.py:404-444,488-516`） | run 启动/续跑 | `notes.json` → 内存 dict + Chroma（batch 512，embedding chunk 64） | no | Chroma | `P-EMBED`（批量重建） |

---

## 5. 分歧清单

### 5.1 论文 ↔ 上游代码（paper ↔ `agiresearch/A-mem` @ ceffb86）

| # | 分类 | 分歧 | 论文证据 | 代码证据 |
|---|---|---|---|---|
| D1 | **paper-only** | **Note Construction 完全缺失**。论文 Eq.2 要求每条 note 由 LLM 生成 Ki/Gi/Xi；上游 `analyze_content()` 写完整了（含 Ps1 原文）却**零调用点**，note 的三个语义字段永远是默认值 | txt:334-336 §3.1；txt:351-353 Eq.2；txt:3137-3154 Ps1 | `memory_system.py:159`（唯一出现处 = def）；`memory_system.py:238` `MemoryNote(content=content, **kwargs)`；默认值 `:68-72` |
| D2 | **两边都有但行为不同** | **Eq.3 未实现**。论文 `ei = fenc[concat(ci,Ki,Gi,Xi)]`；代码 `add_document(note.content, ...)`，Chroma 只对 documents 编码，metadata 不参与向量化 | txt:358-360 Eq.3 | `memory_system.py:258`；`retrievers.py:81-83`（metadata 全部 `json.dumps`/`str` 后作为 metadatas 传入） |
| D3 | **两边都有但行为不同** | **邻居检索的 query 侧口径**。论文 Eq.4 用 `en`（Eq.3 的富文本向量）算相似度；代码用 `note.content` 原文串做 query | txt:372-379 Eq.4 | `memory_system.py:605` `find_related_memories(note.content, k=5)` |
| D4 | **两边都有但行为不同** | **Eq.6 的 link set 无效**。论文让 LLM 基于 Mnear 返回连边；代码喂给 LLM 的 memory_str 只有 `memory index:0..4`，真实 UUID 从未出现，`suggested_connections` 落进 `note.links` 的是 `"0"/"1"` 之类无效值 | txt:388-392 Eq.6；Ps2 txt:3159-3170 | `memory_system.py:307`（`memory index:{i}`）；`:308` `indices.append(i)`；`:682` `note.links.extend(suggest_connections)` |
| D5 | **两边都有但行为不同** | **Eq.7 改错对象**。论文对 `Mnear` 中每个 `mj` 更新；代码把检索排名序号当 `list(self.memories.values())` 的下标，实际改写的是**最早插入的前 k 条** | txt:407-423 §3.3 / Eq.7 | `memory_system.py:687-716`（`noteslist = list(self.memories.values())`；`memorytmp_idx = indices[i]`，而 `indices[i]==i`） |
| D6 | **paper-only（隐含）** | 演化后 `ej` 的重算。Eq.3 把 Gi/Xi 编进 ei，Eq.7 又改 Gi/Xi，逻辑上必须重算；论文全文未提，代码也未做 | txt:358-360 + txt:422-423；无重编码描述 | `memory_system.py:684-716` 改完内存对象后无任何 `add_document`/`update` 调用 |
| D7 | **两边都有但行为不同** | **Ps2 与 Ps3 被合并成一次调用**。论文是两个独立 prompt（§3.2 连边、§3.3 演化），推论上每 note ≥1+1+1=3 次 LLM；代码只有一个 `_evolution_system_prompt` 同时产出 links 与邻居改写，每 note 仅 **1 次** LLM | txt:3159-3170 Ps2；txt:3177-3208 Ps3（两个独立模板） | `memory_system.py:127-157`（单一合并 prompt）；`:621` 单次 `get_completion` |
| D8 | **code-only** | `consolidate_memories()`：每 100 次成功演化重建整个 collection。论文无任何"整理/重建"步骤 | 论文无对应描述（grep `consolidat/threshold` 无命中） | `memory_system.py:97,124,260-263,266-286` |
| D9 | **code-only** | 检索侧沿链扩展被 `return memories[:k]` 截断成死代码。Figure 2 caption 明确要求"linked memories also automatically accessed" | txt:296-297（Fig.2 caption） | `memory_system.py:554-583`（追加）+ `:585`（截断） |
| D10 | **paper-only** | Ps3 的 JSON 示例列了 `"actions": ["strengthen", "merge", "prune"]`；代码 prompt 只列 `["strengthen","update_neighbor"]`，且只实现这两个 | txt:3203 | `memory_system.py:151, 679, 684` |
| D11 | **code-only** | 上游 prompt 额外加了 `neighbor_number` 与"长度必须等于邻居数"的硬约束；论文 Ps3 无此约束 | txt:3177-3208 | `memory_system.py:146-147` |
| D12 | **两边都有但参数不同** | 检索 k：论文主设 k=10（部分类别调参，Appendix A.5）；代码 `search_agentic` 默认 k=5 | txt:907；txt:2844 | `memory_system.py:509` `k: int = 5` |
| D13 | **paper-only** | `retrieval_count` / `last_accessed` / `evolution_history` 三个字段在论文 Eq.1 的 note 定义里没有对应项，代码里有字段但**永不更新** | txt:342-343 Eq.1 = `{ci,ti,Ki,Gi,Xi,ei,Li}` | `memory_system.py:80-81`（初始化）；全仓库无自增/更新点 |

### 5.2 上游代码 ↔ memory-bench fixed 臂（`agiresearch/A-mem` ↔ `servers/amem/`）

| # | 分类 | 分歧 | 上游证据 | fixed 臂证据 |
|---|---|---|---|---|
| E1 | **fixed-only（F1）** | add_note 调 `analyze_content` 填 keywords/context/tags；每 note 多一次 LLM | `memory_system.py:238`（不调） | `fixed.py:369-378`；`:168-195`（宽容解析 + 429 退避 + 解除 max_tokens=1000） |
| E2 | **两边都有但行为不同（F3）** | 索引 document 从"仅原文"改为"content + keywords + tags + context"结构化拼接；原文保留在 `metadata.content` | `memory_system.py:258` | `fixed.py:234-240`；`:198-215`（`context == "General"` 时不拼） |
| E3 | **两边都有但行为不同（F4）** | 邻居 memory_str 改为携带真实 `doc_id`；`suggested_connections` 过滤到"真实存在的 id" | `memory_system.py:307-308`（`memory index:{i}`，返回枚举序号） | `fixed.py:271-278`（`memory id:{doc_id}`）；`:335-336`（过滤） |
| E4 | **两边都有但行为不同（F5）** | `update_neighbor` 改为按真实 UUID 定位 | `memory_system.py:687-716`（下标错位） | `fixed.py:345-357` |
| E5 | **两边都有但行为不同（F8）** | 检索改为**先分配配额**（direct 15 / neighbor 5），邻居不足时用直达命中回填，总数恒为 k | `memory_system.py:554-585`（追加后 `[:k]` 全截） | `fixed.py:405-406,433-471`；实测 `F8: 沿链邻居 5/20` |
| E6 | **fixed-only（F-dirty）** | 被演化改写的邻居加入 `_dirty`，session 末 flush 重算向量 | 上游无（改完不重新索引） | `fixed.py:113,358,243-252`；`server.py:266-269` |
| E7 | **fixed-only（F9，在 server 层）** | envelope 把 LLM 生成的 context 拼进作答上下文 | 上游无 envelope 概念 | `server.py:309-315` |
| E8 | **两边都有但参数不同（F-emb）** | 向量模型 `all-MiniLM-L6-v2`(384d, 本地) → `embedding-3`(云端)。**两臂均已换**（native 也换，见 `server.py:227-228`），故这不是两臂差异，而是与上游/论文的共同偏离 | `memory_system.py:94` / `retrievers.py:48`；论文 txt:910 `all-minilm-l6-v2` | `embedding.py:42-77`；`server.py:227-228`（native）/`fixed.py:111-112`（fixed） |
| E9 | **两边都有但行为不同** | LLM 调用参数：上游 `llm_controller` 写死 `max_tokens=1000`、`temperature=0.7`；fixed 臂绕开 controller 直接调 client，`temperature=0` + `reasoning_effort` + `max_tokens=128000` + JSON 重试 ≤2 + 429 指数退避 | 上游 `llm_controller.py:34`（据 `fixed.py:63` 注释） | `fixed.py:122-166`；native 侧 `server.py:156-184` 只钉 temperature/reasoning，**不覆盖 max_tokens** |
| E10 | **上游有 fixed 没有（回归）** | **`consolidate_memories` 在 fixed 臂无调用点**。上游 `add_note` 末尾有 `evo_cnt % evo_threshold` 判断；fixed 覆盖 `add_note` 后只留计数器 | `memory_system.py:260-263` | `fixed.py:385-387`（无判断）；`fixed.py:389`（定义无 caller）；`server.py:230`（`_patch_consolidate` 只在 native 分支） |
| E11 | **fixed-only（bench 层，两臂共享）** | P8 `no_chroma_reset()`（上游 `__init__` 的全局 `client.reset()` 会清空所有 scope）、P2 per-scope collection、P10 就绪屏障、P11/P13 snapshot 判据、P12 restore 批量 | `memory_system.py:111-116`（全局 reset）；`retrievers.py:55` | `embedding.py:101-116`；`server.py:209,223-228,274-278,458-471,440-444` |
| E12 | **两边都有但参数不同** | 检索 top_k：上游默认 5 → bench 统一 20（MCP 函数签名默认仍是 5） | `memory_system.py:509` | `server.py:287`（签名 5）；`docs/interface-spec.md:154` + `manifest.json`（实跑 20） |

---

## 6. 新造的 primitive 标签

| 标签 | 定义 | 为什么种子词表不够 |
|---|---|---|
| **`P-REVISE`** [NEW] | **回溯改写已存记忆单元的语义字段**（context/keywords/tags/摘要），原地硬覆盖、非新增、非删除、无版本历史，且**不由冲突触发** | 种子表里最接近的两个都不合适：`P-META` 是给**当前正在写入的**单元打标注，无法表达"回过头去改老记忆"这一 A-Mem 的定义性动作（若用 P-META，序列 `...>P-LINK>P-META` 会被读成"再标注一次新 note"，论文全部要点丢失）；`P-CONFLICT` 要求存在冲突/失效语义（覆盖/失效标记/版本化），而 A-Mem 的演化是**增益型**的——新记忆让旧记忆的描述"更丰富"，不是判定旧记忆错了。跨系统对照时这条区分是刚需：Zep 的 `tinvalid` 软失效、mem0 的 UPDATE/DELETE 都是 `P-CONFLICT`，A-Mem 的 evolution 不是 |

其余步骤全部复用种子词表。两处复用需要额外说明：
- `P-FUSE` 用于 fixed 臂的配额合并（Y5）。种子定义是"多路融合(RRF/加权和/MMR)"，而这里是**固定预算配额 + 回填**，不涉及分数运算——归入 P-FUSE 是因为其功能位（合并两条召回通道的结果）一致；`methodology-flow.md` 为此单独登记了 `Fusion:Quota` module，可视为 `P-FUSE` 的一个子型。
- `P-SELECT` 用于上游的 `return memories[:k]`（C10）和 fixed 的 direct_quota 截断（Y3），对应种子定义里的"阈值截断"。

---

## 7. 复核统计

| 文档 | ✓ | ✗ | ◐ | ? | 小计 |
|---|---|---|---|---|---|
| `ARCHITECTURE.md` | 40 | 1 | 13 | 2 | 56 |
| `methodology-flow.md`（抽检） | 18 | 0 | 2 | 0 | 20 |
| **合计** | **58** | **1** | **15** | **2** | **76** |

**✗ 明细（1 条）**：A21 —— fixed 臂无 consolidate 调用点。

**◐ 明细（15 条）**：
A10（富文本只在文档侧，query 侧是原文）、A11（k=5 在 fixed 臂是 env 默认非硬编码）、
A17（strengthen 还会覆盖新 note 自己的 tags，未提）、A23（flush 是逐条不是批量）、
A28（Chroma 是 ANN top-k，非"与全库比"）、A33（候选池只有 k 条，注释与代码不符）、
A34（envelope 实际顺序是"时间戳·原文〔摘要〕"且有 600 截断）、A37（1297 ✓ / 24s 无据）、
A39（"唯一时序信号"忽略了 LLM context 里的日期）、A42（上游有未调用的 delete()，论文 Ps3 列了 prune）、
A49（600 是每条各自的上限，不是共享预算）、A55（8d986e4→af56715 只含三层）、
A56（fixed 臂 evidence 只覆盖 2 个 conv）、M16（端点/密钥缺失只在首次编码报错）、M19（图扩展行号 438-462）。

**? 明细（2 条）**：A2（research-vault 未挂载）、A53（0.563 在所引 run 中复现不出，实测 0.5392）。

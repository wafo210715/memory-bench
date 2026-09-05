---
title: MRAgent methodology 流程图
date: 2026-09-05
tags:
  - memory-bench
  - methodology-flow
  - mragent
---

# MRAgent methodology 流程图

> [!note] 来源与口径
> 基于同目录 [[paper-architecture]] 与 [[code-architecture]]，勘误已按 [[verification]] 复核结论修正：「两路 LLM 精排取并集」实为一路（第二路主路径不可达）、「论文完全没写 2-prompt 结构」被 Appendix E 证伪而撤回、Alg.1 line20 为 `AnswerLLM(x, H^(t+1))` 而非 `H^(T)`、7 个工具映射算子仅 2 个真正出自 §3.1（其余只在 Table 4 出现）。词汇表与图例见全项目规范 `METHODOLOGY-FLOW-SPEC`。

## Paper 视角

Ji, Li, Hooi 2026, *Memory is Reconstructed, Not Retrieved: Graph Memory for LLM Agents*, arXiv:2606.06036（ICML 2026 / PMLR 306）。

![[assets/mragent-paper-flow.png]]

### 核验真源

```mermaid
flowchart TB
    classDef llm fill:#dbeafe,stroke:#2563eb,stroke-width:2px
    classDef alg fill:#ffedd5,stroke:#ea580c,stroke-width:2px
    classDef store fill:#e5e7eb,stroke:#6b7280
    classDef io fill:#f3e8ff,stroke:#9333ea

    subgraph INGEST["写入路径（离线一次性构建）：对话流 T 进，图 M 出（§3.3 / Appendix B.1 / Figure 4(a)）"]
        direction LR
        T["IO:Stream<br/>输入对话流 T"]
        RW["LLM:Rewrite（R_LLM）<br/>代词消解+时间归一化+episode 切分<br/>{e_i} ← R_LLM(T)，Eq.18"]
        TG["LLM:Tag（T_LLM）<br/>每个 e_i 生成关联 tag g_i<br/>Eq.19"]
        KE["LLM:Extract（K_LLM）<br/>每个 e_i 抽细粒度 cue 集 C_i<br/>Eq.19"]
        SE["LLM:Extract（S_LLM）<br/>直接作用于 T 抽语义事实<br/>(c^s, g^s, s)，Eq.20"]
        AB["LLM:Summarize（A_LLM）<br/>对已切好的 e_i 集合摘要抽象<br/>→ topic τ_j，Eq.21"]
        G[("Store:Graph<br/>异构图 M=(C,V,R)，§3.1<br/>Cue–Tag–Episode（沿统一时间线 §3.2）<br/>Cue–Tag–Semantic<br/>Topic–Episode 链接")]

        T --> RW
        RW -->|"e_i"| TG
        RW -->|"e_i"| KE
        T --> SE
        RW -->|"e_i 集合"| AB
        TG --> G
        KE --> G
        SE --> G
        AB --> G
    end

    subgraph RETRIEVE["检索路径：主动记忆重构，每查询一次，≤T 步迭代（§4.1-4.2 / Algorithm 1；Navigate/Answer 双模式 §B.2）"]
        direction LR
        Q["IO:Query x"]
        QC["LLM:Extract<br/>ExtractCues(x)，Alg.1 line1<br/>（论文写成函数，未明示是否 LLM 调用）"]
        INIT["Retrieval:CueMatch<br/>ActiveSetInit(C,G)，Alg.1 line2<br/>查询 cue 匹配图 cue 集 → Z(0)<br/>（匹配机制论文未说明）"]
        SEL["LLM:Select（f_select）<br/>基于 x+H(t)+Z(t)<br/>选遍历动作 A(t)，Eq.10"]
        TRV["Retrieval:Graph<br/>Controlled Traversal 算子 Π_a，Eq.8/9/11<br/>Forward: Cue→Tag / (Cue,Tag)→Content<br/>Reverse: Content→(Cue,Tag)<br/>7 个工具（Table 4）"]
        RT["LLM:Route（f_route）<br/>评估语义关联、剪枝候选<br/>Z(t+1)=f_route(x,H(t),Z~(t+1))，Eq.12<br/>H(t+1)=H(t)∪Z(t+1)"]
        ST{"LLM:Judge（C_LLM 判停）<br/>STOP(x,H(t+1))<br/>Alg.1 line16-18"}
        ANS["LLM:Answer<br/>AnswerLLM(x, H(t+1))<br/>Alg.1 line20"]
        A["IO:Answer ŷ"]

        Q --> QC --> INIT --> SEL --> TRV --> RT --> ST
        ST -->|"否，回 f_select（最多 T 步）"| SEL
        ST -->|"是：证据足够"| ANS --> A
    end

    G -.->|"算子执行后返回候选"| TRV
```

> [!info] Paper 侧边界（论文自己的划分）
> 图 `M=(C,V,R)` + 7 个映射算子 `ϕ`（Table 4）归**记忆系统本体**——只按结构化条件存取，不做语义判断（txt:461-462）；`f_select` / `f_route` / `C_LLM` / `AnswerLLM` 全部归 **LLM 推理侧**——所有决策（选动作、剪枝、判停、组织答案）都发生在 LLM 一侧。

## Code 视角

repo `~/Documents/repo/MRAgent` @ `7441506`（单提交仓库，无 tag；静态读码未运行）。

![[assets/mragent-code-flow.png]]

### 核验真源

```mermaid
flowchart TB
    classDef llm fill:#dbeafe,stroke:#2563eb,stroke-width:2px
    classDef alg fill:#ffedd5,stroke:#ea580c,stroke-width:2px
    classDef nlp fill:#ecfccb,stroke:#65a30d
    classDef store fill:#e5e7eb,stroke:#6b7280
    classDef io fill:#f3e8ff,stroke:#9333ea
    classDef dead fill:#fee2e2,stroke:#dc2626,stroke-dasharray:5 5

    subgraph INGEST["写入路径（离线构建）：run.py 每 sample 一次，①② 内部逐 session 各 1 次调用"]
        direction LR
        T["IO:Stream<br/>raw_text 原始对话<br/>get_data.py:9（LM 分支只留 user 轮）"]
        RW["LLM:Rewrite ①<br/>agent.py:592 / prompts.py:18-55<br/>每 session 1 次调用四合一：<br/>改写句 + 每句 tag + ≥10 topics + personal_sentences<br/>（覆盖论文 R/T/A/S 四函数）"]
        KW["LLM:Extract ②（K_LLM）<br/>agent.py:669/712 / prompts.py:69-87<br/>每 session 1 次，抽每句 cue<br/>输入=①的改写句 {id,text}（:737-743）"]
        EMB["Retrieval:Emb ③<br/>embed_rewrite.py:20（纯计算，非 LLM）<br/>text-embedding-3-large 3072 维 L2<br/>改写句+topic+全部问题向量，落盘 pkl"]
        G[("Store:Graph<br/>MemorySystem 进程内 Python 对象图，不持久化<br/>EpisodeEvent：text=原始对话行（:798-811，<br/>改写句只活在向量空间）<br/>PersonalEvent 挂 Persona 桶（LLM 生成文本）<br/>Topic（session 级）+ timeline 日期索引<br/>组图纯 Python agent.py:772-862（store_raw_text :864）<br/>说话人强制入 cue :847-848；中间产物落盘、存在即跳过")]

        T --> RW
        RW -->|"改写句"| KW
        RW -->|"改写句+topics 文本"| EMB
        T -->|"raw_text 直灌"| G
        KW -->|"每句 cue"| G
        EMB -->|"句/主题/问题向量"| G
    end

    subgraph RETRIEVE["检索路径：answer_question agent.py:450，每问题一次（10 线程并发，图只读共享）"]
        direction LR
        Q["IO:Query"]
        QK["LLM:Extract<br/>问题 cue + 时间范围<br/>agent.py:566 / prompts.py:206-219"]
        CM["Retrieval:CueMatch<br/>图文本匹配（无向量）<br/>controller.py:214/263<br/>归一化/子集/Jaccard≥0.6<br/>→ full/partial 候选池"]
        TL["Retrieval:Timeline<br/>时间快通道（条件：question_time 非空）<br/>system.py:137-147 日期索引<br/>阈值 50（locomo）/ 20（LM）<br/>命中少直接短路；多则退回图匹配结果按时间过滤"]
        CE["Retrieval:Emb<br/>K1=80 向量粗排<br/>（条件：候选>80，点积）<br/>agent.py:495-498"]
        DD["NLP:PrefixDedup<br/>同 origin 前缀只留一条<br/>agent.py:505-518"]
        TP["Retrieval:Emb<br/>topic 独立通道 top-8（TOPIC_K=8）<br/>agent.py:236/520<br/>不与主证据合并，并列入 ans_input"]
        RR["LLM:Rerank<br/>listwise 精排 ≤K2=20<br/>（条件：去重后>20）<br/>agent.py:244/523<br/>ANSWER_SORT_PROMPT2（唯一生效路）"]
        KT["LLM:Rerank<br/>高扇出 cue 的 tag 打分（条件：tag>15，<br/>每 cue 1 次 LLM）agent.py:392/536<br/>分≥0.7 的 tag 预取原文<br/>= 循环前预执行一次 edges_by_tag"]
        ASM["初始证据包组装 ans_input<br/>{question, key_sentences, keys_candidates,<br/>key_tag_sentences, similar_topic}<br/>agent.py:539-548"]
        LOOP{{"LLM:Select 工具循环<br/>chat_with_tools_once llm/controller.py:92<br/>≤8 轮 / 全局 ≤50 次工具调用（无单轮上限）<br/>每轮 1 次 LLM 同给 mode+tool_calls<br/>第 8 轮强制换收尾 prompt :140-143"}}
        TB["Retrieval:Graph<br/>ToolBridge 7 工具 tools.py:162-192（纯 Python）<br/>edges_by_tag(必填note) / query_conversation_time /<br/>query_event_keywords / query_event_context /<br/>query_personal_information / query_personal_aspect / query_topic_events<br/>工具内条件触发：event_by_tag>20 → embedding 重排<br/>（controller.py:29-48）；tag>15 → LLM 打分（:54-95）"]
        FA["LLM:Answer<br/>mode=answer JSON<br/>answer+supports+confidence<br/>controller.py:178-181"]
        A["IO:Answer"]

        Q --> QK
        Q -->|"问题向量（构建期预计算）"| TP
        QK --> CM
        CM -->|"时间命中少：短路跳过粗排/精排"| TL --> ASM
        CM -->|"候选>80"| CE --> DD -->|"去重后>20"| RR
        CM -->|"某 cue 的 tag 数>15"| KT
        RR --> ASM
        KT --> ASM
        TP --> ASM
        ASM --> LOOP
        LOOP -->|"navigate: 发起 tool_calls"| TB
        TB -->|"原始返回原样回灌，只增不删（:206-223）"| LOOP
        LOOP -->|"mode=answer / 第 8 轮强制"| FA --> A
    end

    subgraph DEAD["论文宣称但代码不成立 / 运行时死路（verification 修正口径）"]
        D1["LLM:Route（f_route 独立剪枝）<br/>论文 Eq.12 的显式候选筛选步骤<br/>= 无对应函数：工具输出原样累积<br/>controller.py:206-223 只增不删"]
        D2["LLM:Judge（C_LLM 独立判停调用）<br/>= 无独立调用：判停隐式并入<br/>每轮 mode=answer 决策 controller.py:178-181"]
        D3["LLM:Rerank 第二路（0-1 打分精排）<br/>select_finegrained_sentence_sort agent.py:309<br/>主路径不可达（:315 入口条件恒假）<br/>仅 LM 时间分支 :178 作首选，且被 gemini 门控 :180"]
    end

    G -.->|"图查询返回结果"| TB
    G -.->|"候选池来源"| CM
```

> [!warning] 与论文的核心分歧（verification 逐条确认）
> 1. **图里存的 episode 文本是原始对话行，不是论文宣称的 R_LLM 改写句**（agent.py:798-811 三处交叉验证）——改写句只活在向量空间，「代词消解让 cue 显式」仅体现于向量层面。
> 2. 论文 5 个抽取函数（R/T/K/S/A）→ 代码每 session **2 次调用**（rewrite 四合一 + keyword）；论文 Appendix E 的 2-prompt 结构事实上已给出同样合并（txt:1919-1990）。
> 3. 论文对 MRAgent **无任何 embedding 成分**（embedding 只出现在 baseline 描述）；代码有 3 处向量检索（K1 粗排 / topic top-8 / event_by_tag 内部重排）。
> 4. timeline 未作为工具暴露给 LLM，只在循环前的时间快通道用一次（论文 §3.2 宣称支撑检索期时间约束）。
> 5. 论文 `ActiveSetInit` 一行伪代码 → 代码在进循环前实际跑了 5 种机制（图文本匹配→K1 粗排→前缀去重→一路 LLM 精排→topic 向量 top-8+条件 tag 打分）。

> [!bug] 复核顺带发现的代码问题（verification 附录，文档未记）
> - `agent.py:698` 调 `check_key_json(keys_out, text, replace=True)`，而 `schema.py:144` 签名为 `(text, ref_obj=None)`——关键词抽取第 3 次重试失败会抛 TypeError。
> - LM 时间分支 `agent.py:192-193` 算出的 `key_candidates`/`key_tag_sentences` 未装入 `ans_input`（:195-199）即被丢弃，纯浪费 LLM 调用。
> - 工具循环空转轮：既无 answer 也无 tool_calls 时 `controller.py:229-232` 走 `continue`，白烧 MAX_ROUNDS 预算。

## 新登记 module

- `IO:Stream`：跨 session 的完整输入对话流（论文 `T` / 代码 `raw_text`）；`IO:Session` 语义偏单会话、`IO:TurnPair` 偏单轮，均不匹配 MRAgent 的整段批处理粒度。
- `Retrieval:CueMatch`：cue 集合对图 cue 节点的纯文本匹配（归一化/子集/Jaccard）；论文 `ActiveSetInit` 的对应，非向量非 BM25 的第三种检索入口。
- `Retrieval:Timeline`：时间线日期索引快速通道（代码独有，`system.py:137-147`）；论文侧的时间线只是 episodic 层组织方式，检索算子里无时间查询工具。
- `LLM:Select`：多步循环中选择遍历动作/工具调用决策（论文 `f_select`，Eq.10）。
- `LLM:Route`：候选语义路由与剪枝（论文 `f_route`，Eq.12）；代码无实现，code 图以 dead 展示。
- `LLM:Rerank`：LLM listwise 精排/相关性打分（代码 r8/r9/r14 三处；论文无对应）。跨系统高频组件，建议统一登记。
- `NLP:PrefixDedup`：同源前缀规则去重（`agent.py:505-518`），区别于 mem0 的 `NLP:HashDedup`（md5）。

## 不确定处

1. **f_select 与 f_route 是否两次独立 LLM 调用**：论文正文未显式说明；Appendix E 只有一份 QA and Tool-Use Prompt（answer/navigate 二选一）+ B.2「选工具→调用→评估」的描述，强烈指向每轮一次调用同时完成两个决策（verification P48/P58）。paper 图按论文形式化分画两个节点，此张力保留。
2. `C_LLM`（§4.2）与 `STOP(x,H(t+1))`（Alg.1 line16）两处表述论文无桥接说明（P49）；代码侧判停隐式并入 mode=answer，无独立调用。
3. `ActiveSetInit` 的匹配机制（精确/模糊/向量）论文未写（P56）；代码用文本归一化/子集/Jaccard（D7）。
4. `A_LLM({e_i})` 的输入粒度（单 session vs 跨 session）论文未写（P50）；代码 topic 为 session 级直接从原文生成（D3）。
5. Table 6 只报告 5/7 工具的证据覆盖率，缺 `query event keywords` / `query personal information`，论文未解释（P47/D15）；代码中两工具均启用。
6. Table 3 的 token/runtime 只给汇总（caption 写明含构建+检索），未拆分项——循环前初始证据包的多次 LLM 调用（r1/r8/r9）是否计入「retrieval」口径不明（P55）。

## 生图 prompt 素材

### Paper flow prompt

```text
Create a wide academic systems flowchart for MRAgent paper view in the approved Mem0 visual style. White background; two horizontal lanes; canonical colors and shapes. INGEST lane: IO:Stream -> LLM:Rewrite, then branches to LLM:Tag, LLM:Extract (cues), LLM:Extract (semantic facts), LLM:Summarize (topics); all write one gray cylinder Store:Graph labeled heterogeneous cue-tag-content graph. RETRIEVE lane: IO:Query -> LLM:Extract (query cues) -> Retrieval:CueMatch -> LLM:Select -> Retrieval:Graph -> LLM:Route -> LLM:Judge. Judge loops back to Select when evidence is insufficient and flows to LLM:Answer -> IO:Answer when sufficient. Draw Store:Graph into Retrieval:Graph. LLM blue, Retrieval orange, stores gray cylinders, IO purple pills. Short English labels only; canonical legend; no citations, equations, icons, or decoration.
```

### Code flow prompt

```text
Create a wide academic systems flowchart for MRAgent code view in the approved Mem0 visual style. INGEST lane: IO:Stream -> LLM:Rewrite (one four-in-one call) -> LLM:Extract (cues) -> Retrieval:Emb -> Store:Graph; also connect raw stream directly to Store:Graph. RETRIEVE lane: IO:Query -> LLM:Extract (cues + time) -> Retrieval:CueMatch, then conditional Retrieval:Timeline, Retrieval:Emb coarse rank, NLP:PrefixDedup, LLM:Rerank, and a parallel Retrieval:Emb topic top-8; converge into initial evidence -> LLM:Select tool loop <-> Retrieval:Graph seven tools -> LLM:Answer -> IO:Answer. Add a red dashed PAPER-ONLY / DEAD panel: LLM:Route independent pruning, LLM:Judge independent stop call, second LLM:Rerank path. LLM blue, Retrieval orange, NLP green, store gray cylinder, IO purple pills, dead red dashed. Short English labels only; canonical legend; no citations or decoration.
```

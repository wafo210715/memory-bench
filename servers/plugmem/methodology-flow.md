---
title: PlugMem methodology 流程图
date: 2026-09-05
tags:
  - memory-bench
  - methodology-flow
  - plugmem
---

# PlugMem methodology 流程图

> [!note] 来源与采信顺序
> 基于同目录 [[paper-architecture]] 与 [[code-architecture]]，并已吸收 [[verification]]（2026-09-05，论文 83 条 + 代码 71 条逐项核对）的勘误。凡 architecture 与 verification 冲突，一律以 verification 为准。关键修正包括：当前 LongMemEval / WebArena 脚本通过 `PlugMemClient` 访问 `plugmem/` 服务；`plugmem/` 首次提交早于 ICML 接收；默认三基准均不启用多跳；return scorer 是死代码；intent 写入去重是精确字符串匹配；semantic rerank 实际退化为纯 cosine。统一词汇表见 `METHODOLOGY-FLOW-SPEC`。

## Paper 视角

Yang et al. 2026, *PlugMem: A Task-Agnostic Plugin Memory Module for LLM Agents*, arXiv:2603.03296（ICML 2026）。

![[assets/plugmem-paper-flow.png]]

### 核验真源

```mermaid
flowchart TB
    classDef llm fill:#dbeafe,stroke:#2563eb,stroke-width:2px
    classDef alg fill:#ffedd5,stroke:#ea580c,stroke-width:2px
    classDef nlp fill:#ecfccb,stroke:#65a30d
    classDef fusion fill:#fef9c3,stroke:#ca8a04,stroke-width:2px
    classDef store fill:#e5e7eb,stroke:#6b7280
    classDef io fill:#f3e8ff,stroke:#9333ea
    classDef dead fill:#fee2e2,stroke:#dc2626,stroke-dasharray:5 5
    classDef async fill:#f0fdf4,stroke:#16a34a,stroke-dasharray:4 3
    classDef learn fill:#fae8ff,stroke:#a21caf
    classDef sched fill:#fef9c3,stroke:#ca8a04

    subgraph INGEST["INGEST：Structuring / create；每条完整轨迹处理一次（§3.1）"]
        direction LR
        TRAJ(["IO:Trajectory<br/>τ=[(o_t,a_t)]₁ᵀ"]):::io
        STD["LLM:Extract<br/>Standardize：每步 3 次 LLM<br/>state / subgoal / reward<br/>→ e_t=(o,s,a,r,g)<br/>§3.1.1 / Appx.C.1"]:::llm
        GE[("Store:Graph G_E<br/>episodic source traces<br/>verifiable evidence<br/>§3.1 / Table 2")]:::store
        SEM["LLM:Extract<br/>≤10 propositions + concepts<br/>指代消解 / 去重 / 长度控制<br/>§3.1.2 / Appx.C.2"]:::llm
        SEMEMB["Retrieval:Emb<br/>cache proposition / concept vectors<br/>Appx.C.2"]:::alg
        GS[("Store:Graph G_S<br/>concept ↔ proposition<br/>membership + sibling + provenance<br/>§3.1.2 / Appx.C.2")]:::store
        SEG["Retrieval:Emb<br/>adjacent subgoal cosine<br/>below threshold → segment<br/>§3.1.2 / Appx.C.2"]:::alg
        PROC["LLM:Extract<br/>segment → intent + prescription<br/>§3.1.2 / Appx.C.2"]:::llm
        SCORE["LLM:Judge<br/>independent return scorer<br/>ρ ∈ [1,10]<br/>§3.1.2 / Appx.C.2"]:::llm
        IDEMB["Retrieval:Emb<br/>intent cosine vs existing intents<br/>threshold θ_equal<br/>Appx.C.2"]:::alg
        IMERGE["LLM:Rewrite<br/>merge matching intent<br/>refresh embedding<br/>Appx.C.2"]:::llm
        GP[("Store:Graph G_P<br/>intent → prescription<br/>hierarchical + provenance<br/>§3.1.2 / Appx.C.2")]:::store

        TRAJ --> STD --> GE
        STD --> SEM --> SEMEMB --> GS
        STD --> SEG --> PROC --> SCORE --> IDEMB
        IDEMB -->|"new intent"| GP
        IDEMB -->|"cosine > θ_equal"| IMERGE --> GP
        GS -.->|"provenance"| GE
        GP -.->|"provenance"| GE
    end

    subgraph RETRIEVE["RETRIEVE：Retrieval + Reasoning；迭代至证据足够或 T_max（§3.2-§3.3）"]
        direction LR
        Q(["IO:Query Q"]):::io
        MODE["LLM:Route<br/>GET MODE：E / S / P<br/>§3.2 / Listing 8"]:::llm
        INIT["Retrieval:Emb<br/>Q vs all low-level nodes<br/>initialize C₀<br/>§3.2 / Table 14"]:::alg
        CTRL["LLM:Judge<br/>MULTI HOP CTRL<br/>enough + focus node IDs<br/>Appx.C.3 / Listing 10"]:::llm
        PLAN["LLM:Tag<br/>GET PLAN：concepts / intents<br/>Appx.C.3 / Listing 9"]:::llm
        DENSE["Retrieval:Emb<br/>embedding channel<br/>low-level similarity<br/>Appx.C.3"]:::alg
        LINK["Retrieval:Graph<br/>linking channel<br/>high-level route → low-level neighbors<br/>Appx.C.3"]:::alg
        UNION["Fusion:Union<br/>merge two candidate sets<br/>Appx.C.3"]:::fusion
        RERANK["Retrieval:Rerank<br/>relevance + optional importance/recency<br/>prune to budget K<br/>§3.2 / Appx.C.3"]:::alg
        TOEP["Retrieval:Graph<br/>ToEpisodic via provenance<br/>only when E is requested<br/>§3.2 / Table 14"]:::alg
        REASON["LLM:Summarize<br/>type-specific Reasoning Module<br/>compact actionable guidance<br/>§3.3 / Appx.C.4"]:::llm
        MEM(["IO:RetrievedMemory<br/>refined memory tokens"]):::io

        Q --> MODE --> INIT --> CTRL
        CTRL -->|"not enough"| PLAN
        PLAN --> DENSE & LINK
        DENSE & LINK --> UNION --> RERANK --> CTRL
        CTRL -->|"enough: S / P"| REASON
        CTRL -->|"enough: E"| TOEP --> REASON
        REASON --> MEM
    end

    GS -.-> DENSE
    GS -.-> LINK
    GP -.-> DENSE
    GP -.-> LINK
    GE -.-> TOEP

    subgraph MAINTAIN["MAINTAIN：独立操作；主论文基准主要评测 create / retrieve（§3.4）"]
        direction LR
        UPDATE["LLM:Resolve<br/>update：合并语义节点、缓解矛盾<br/>§3.4 / Appx.C.5"]:::llm
        DELETE["Sched:Evict<br/>delete：衰减低效用节点<br/>+ 压缩旧 episodic<br/>§3.4 / Table 13<br/>算法与独立实验未给"]:::sched
        UPDATE -.-> GS
        DELETE -.-> GE
        DELETE -.-> GS
        DELETE -.-> GP
    end

    subgraph OUTSIDE["Base Agent（PlugMem 边界外）"]
        direction LR
        ANSWER["LLM:Answer<br/>consume refined memory tokens"]:::llm
        A(["IO:Answer / next action"]):::io
        ANSWER --> A
    end

    MEM --> ANSWER
```

> [!warning] 论文自身未消解的张力
> - Memory type：Table 14 的 `F ⊆ {E,S,P}` 允许多类型子集，Listing 8 却要求 “only one”；图按可比较主链画 E/S/P 路由，不把“可多选”当成已确认能力。
> - `RerankPrune` 只说 relevance 为主、可叠加 importance/recency，没有闭式公式、权重或 importance 定义；图保留论文宣称，不补造打分细节。
> - `ToEpisodic(C,G_E)` 只有伪代码一行，provenance 映射的一对一/聚合规则未披露。
> - Table 2 渲染出的 solves 箭头方向与正文语义描述不一致；图采用正文与 Appendix C.2 支持的 intent → prescription 方向。

## Code 视角

repo `~/Documents/repo/PlugMem` @ `3b2ce75`。主图以 `plugmem/core` + `plugmem/inference` + `plugmem/storage` 的当前服务实现为主，并单独标出 `src/eval/hotpotqa` 的外挂多跳；当前 LongMemEval / WebArena 评测入口通过 `PlugMemClient` 访问该服务，但仍复用部分 `src/` structuring / value 代码。

![[assets/plugmem-code-flow.png]]

### 核验真源

```mermaid
flowchart TB
    classDef llm fill:#dbeafe,stroke:#2563eb,stroke-width:2px
    classDef alg fill:#ffedd5,stroke:#ea580c,stroke-width:2px
    classDef nlp fill:#ecfccb,stroke:#65a30d
    classDef fusion fill:#fef9c3,stroke:#ca8a04,stroke-width:2px
    classDef store fill:#e5e7eb,stroke:#6b7280
    classDef io fill:#f3e8ff,stroke:#9333ea
    classDef dead fill:#fee2e2,stroke:#dc2626,stroke-dasharray:5 5
    classDef async fill:#f0fdf4,stroke:#16a34a,stroke-dasharray:4 3
    classDef learn fill:#fae8ff,stroke:#a21caf
    classDef sched fill:#fef9c3,stroke:#ca8a04

    subgraph INGEST["INGEST：append per turn → close / insert per trajectory"]
        direction LR
        TURN(["IO:TurnPair<br/>(action, observation)<br/>core/memory.py:59"]):::io
        META["LLM:Extract<br/>get_subgoal + get_reward + get_state<br/>3 calls / turn<br/>core/memory.py:60/68/95"]:::llm
        SEG["Retrieval:Emb<br/>adjacent subgoal cosine < 0.75<br/>segment trajectory<br/>core/memory.py:76-83"]:::alg
        TRAJ(["IO:Trajectory<br/>Memory.close() after full run<br/>core/memory.py:104"]):::io
        SEM["LLM:Extract<br/>get_semantic, 1 call / step<br/>core/memory.py:115"]:::llm
        SEMEMB["Retrieval:Emb<br/>proposition + tag vectors<br/>core/memory.py:118-121"]:::alg
        PROC["LLM:Extract<br/>get_procedural, 1 call / segment<br/>core/memory.py:123<br/>return hard-coded 0.0"]:::llm
        EXACT["NLP:TextDedup<br/>tag / subgoal exact-string dict lookup<br/>memory_graph.py:442/515"]:::nlp
        PMERGE["LLM:Rewrite<br/>get_new_subgoal only on exact repeat<br/>memory_graph.py:519"]:::llm
        GRAPH[("Store:Graph<br/>5 logical node types + ID links<br/>MemoryGraph.insert :363-593<br/>Episodic / Semantic / Tag /<br/>Procedural / Subgoal")]:::store
        CHROMA[("Store:Vector<br/>ChromaDB, 5 collections<br/>persistence only<br/>storage/chroma.py:17/72-81")]:::store

        TURN --> META --> SEG --> TRAJ
        TRAJ --> SEM --> SEMEMB --> GRAPH
        TRAJ --> PROC -->|"return = 0.0"| EXACT
        EXACT -->|"new string"| GRAPH
        EXACT -.->|"exact repeat only"| PMERGE --> GRAPH
        GRAPH --> CHROMA
    end

    subgraph RETRIEVE["RETRIEVE：retrieve_memory；核心库单轮、三选一（memory_graph.py:988-1108）"]
        direction LR
        Q(["IO:Query"]):::io
        MODE["LLM:Route<br/>get_mode：E / S / P 三选一<br/>1 call / query<br/>memory_graph.py:1011-1015"]:::llm
        PLAN["LLM:Tag<br/>get_plan：next_subgoal + query_tags<br/>1 call / query<br/>memory_graph.py:1019-1022"]:::llm

        S1["Retrieval:Emb<br/>Semantic Phase 1<br/>full scan active nodes → top-5<br/>memory_graph.py:663/686-699"]:::alg
        S2["Retrieval:Graph<br/>Semantic Phase 2<br/>each query tag → 1 TagNode<br/>threshold 0.8<br/>memory_graph.py:599/714-740"]:::alg
        SU["Fusion:Union<br/>semantic candidate union<br/>memory_graph.py:745-749"]:::fusion
        SR["Retrieval:Rerank<br/>pure text cosine → top-10<br/>importance / recency / credibility = 0<br/>memory_graph.py:762-797<br/>value_functions.py:75-88"]:::alg

        P1["Retrieval:Emb<br/>Procedural: best 1 SubgoalNode<br/>threshold 0.1<br/>memory_graph.py:892-915"]:::alg
        P2["Retrieval:Graph<br/>only that subgoal's prescriptions<br/>memory_graph.py:939"]:::alg
        PR["Retrieval:Rerank<br/>prescription cosine → top-1 default<br/>value_functions.py:176"]:::alg

        E1["Retrieval:Emb<br/>Episodic: semantic full scan<br/>no tag route, top-30<br/>memory_graph.py:809/847/860"]:::alg
        E2["Retrieval:Graph<br/>session vote ≥3 → full episode<br/><3 → semantic proposition text<br/>memory_graph.py:862-878"]:::alg

        MSG(["IO:RetrievedMemory<br/>type-specific prompt messages<br/>memory_graph.py:1079-1108<br/>core system ends here"]):::io

        Q --> MODE --> PLAN
        PLAN -->|"semantic"| S1 & S2
        S1 & S2 --> SU --> SR --> MSG
        PLAN -->|"procedural"| P1 --> P2 --> PR --> MSG
        PLAN -->|"episodic"| E1 --> E2 --> MSG
        PLAN -.->|"episodic audit only; discarded"| S1
        PLAN -.->|"episodic audit only; discarded"| P1
    end

    GRAPH -.-> S1
    GRAPH -.-> S2
    GRAPH -.-> P1
    GRAPH -.-> P2
    GRAPH -.-> E1
    CHROMA -.->|"load all nodes into Python"| GRAPH

    subgraph CALLER["调用方 / Base Agent（默认评测路径，PlugMem core 边界外）"]
        direction LR
        REASON["LLM:Summarize<br/>caller-owned reasoning call<br/>eval_longmemeval_all.py:102<br/>plugmem_agent.py:234"]:::llm
        ANSWER["LLM:Answer / Act<br/>final answer or action<br/>eval_longmemeval_all.py:116"]:::llm
        OUT(["IO:Answer / next action"]):::io
        REASON --> ANSWER --> OUT
    end

    MSG --> REASON

    subgraph EVAL["评测脚本旁路：不是 MemoryGraph 通用能力"]
        direction LR
        MH["LLM:Judge<br/>HotpotQA semantic-only loop<br/>enough + top_node_ids<br/>eval_qa_all.py:63/122-221"]:::llm
        CONCAT["Fusion:Concat<br/>selected facts appended to query<br/>max 3 rounds; union across rounds<br/>eval_qa_all.py:138/213/216-219"]:::fusion
        MH --> CONCAT --> MH
    end

    SR -.->|"only if --n_round_retrieval ≥2<br/>default = 1"| MH

    subgraph MAINTAIN["MAINTAIN：显式调用，不在 insert 主链自动触发"]
        direction LR
        UCAND["Retrieval:Graph<br/>shared-tag candidates<br/>memory_graph.py:1348+"]:::alg
        USIM["Retrieval:Emb<br/>cosine ≥ merge_threshold 0.5"]:::alg
        URES["LLM:Resolve<br/>merge_semantic + deactivate old node<br/>memory_graph.py:1298/1348"]:::llm
        UCAND --> USIM --> URES --> GRAPH
    end

    GRAPH -.-> UCAND

    subgraph CODING["论文外旁路：coding-memory promotion（2026-05 新增）"]
        direction LR
        CAND(["IO:TurnPair<br/>failure_delta / explicit correction<br/>promotion.py:24/31-32"]):::io
        CEXT["LLM:Extract<br/>extract_coding_memories<br/>promotion.py:63"]:::llm
        CAND --> CEXT -->|"_insert_structured, bypass Memory.close"| GRAPH
    end

    subgraph DEAD["论文宣称但核心代码缺失 / 死路径"]
        direction LR
        DRETURN["LLM:Judge<br/>Get_Return ρ∈[1,10]<br/>function exists but zero calls;<br/>src call commented out<br/>inference/structuring.py:96-124"]:::dead
        DINTENT["Retrieval:Emb<br/>intent cosine dedup + θ_equal<br/>insert() has no cosine call<br/>memory_graph.py:363-593"]:::dead
        DMH["LLM:Judge<br/>generic MULTI HOP CTRL<br/>absent from plugmem core;<br/>paper says G_S / G_P generic"]:::dead
        DEXP["Retrieval:Graph<br/>generic iterative graph expansion<br/>absent from plugmem core"]:::dead
        DIMP["Fusion:Add<br/>importance / recency / credibility<br/>into semantic score<br/>computed inputs are discarded"]:::dead
        DDEL["Sched:Evict<br/>delete low-utility nodes +<br/>compress old episodic<br/>no implementation; credibility decay default 0"]:::dead
        DRETURN -.-> DINTENT
        DMH -.-> DEXP
    end
```

> [!warning] 代码与运行配置退化
> 1. **多跳默认全关**：LongMemEval / WebArena 各只调用一次 `retrieve_memory()`；HotpotQA 的外挂循环仅支持 semantic，且 `--n_round_retrieval` 默认 1。论文的 G_S / G_P 通用多跳不是核心库能力。
> 2. **quality-aware reuse 缺失**：`get_return()` 存在但零调用，`get_procedural()` 将 `_return` 写死为 `0.0`；`src` 对应调用甚至被注释掉。
> 3. **intent 去重退化**：写入时只做 `subgoal2node.get(subgoal_str)` 精确字符串匹配，不做论文的 embedding cosine + `θ_equal`。即使命中，合并分支只刷新 embedding/time，未把 merged string 写回节点文本。
> 4. **semantic 路由与重排退化**：tag route 只扩大候选池；`compute_importance` / `compute_recency` / `compute_credibility` 恒为 0，最终排序 100% 是文本 cosine。`ValueBase.evaluate()` 还漏加 `v_credibility`。
> 5. **Chroma 退化为持久化层**：四个 `query_*` ANN 方法全仓零调用；查询先把节点载入 Python，再全量 `for` 循环算 cosine，未使用 Chroma HNSW。
> 6. **episodic 模式额外浪费**：先跑 semantic + procedural 两路写入 audit 后丢弃，再单独跑 episodic；其 `_wo_tag` semantic 路径不检查 `is_active`，软删除节点仍可能重新命中。
> 7. **Reasoning 边界外移**：`retrieve_memory()` 只返回 prompt messages；`retrieve_and_reason()` 虽存在，但三个 eval 目录没有调用点。论文系统内的 Reasoning Module 在默认代码路径由调用方 LLM 完成。

> [!info] 代码来源口径修正
> `plugmem/` 并非论文接收后才出现：其首个提交为 2026-03-19，早于 2026-04 ICML 接收；只有 coding plugin / promotion 旁路是 2026-05 新增。当前 LongMemEval / WebArena 入口无条件使用 HTTP `PlugMemClient`，不能再把三个基准概括成“全部 import `src/memory_retrieving`”。

## 新登记 module

以下均以当前中央规范 `METHODOLOGY-FLOW-SPEC` 为判定基准；其中部分名称已在其他系统的 methodology 文件出现，但尚未回填中央词汇表。

| module | 类别 | 理由 |
|---|---|---|
| `IO:Trajectory` | IO | PlugMem create 的输入与 close/insert 的提交粒度是完整 trajectory；区别于逐步进入 `Memory.append()` 的 `IO:TurnPair`。 |
| `IO:RetrievedMemory` | IO | 检索末端输出的是 refined memory tokens（论文）或渲染好的 prompt messages（代码），不是最终 answer。 |
| `LLM:Route` | LLM | GET MODE / get_mode 负责在 episodic / semantic / procedural 之间路由；与生成 concept/intent 查询标签的 `LLM:Tag` 分开。 |
| `NLP:TextDedup` | NLP | 代码插入使用 tag/subgoal 文本的精确字符串 dict lookup；区别于 embedding 阈值去重与 hash 去重。 |
| `Fusion:Union` | Fusion | 论文和代码 semantic 检索都把 dense 与 graph-route 两个候选集合做集合并；不应误写成加权求和或纯 concat。 |
| `Fusion:Concat` | Fusion | HotpotQA 外挂多跳把 focus facts 直接拼接进下一轮 query 字符串，不做 embedding 融合。 |
| `Retrieval:Rerank` | Retrieval | 候选召回后的确定性打分、排序与 top-k pruning；区别于 LLM listwise reranker。 |

已直接复用中央词汇表既有项：`LLM:Extract`、`LLM:Judge`、`LLM:Rewrite`、`LLM:Tag`、`LLM:Summarize`、`LLM:Resolve`、`LLM:Answer`、`Retrieval:Emb`、`Retrieval:Graph`、`Fusion:Add`、`Sched:Evict`、`Store:Graph`、`Store:Vector`、`IO:Query`、`IO:Answer`、`IO:TurnPair`。

## 不确定处

1. **论文 memory type 是单选还是多选**：Listing 8 的 “only one” 与 Table 14 的集合 `F ⊆ {E,S,P}` 冲突，论文无勘误。
2. **论文 rerank 公式**：importance 的定义、relevance/importance/recency 权重及是否在主实验启用均未披露。
3. **论文 episodic 回映射**：`ToEpisodic(C,G_E)` 的粒度与聚合规则未写；代码的“session 命中 ≥3 才回整段，否则返回 proposition”只能视为实现选择，不能反推论文。
4. **intent 精确字符串去重的实际命中率**：静态控制流已确认，但仓库没有统计或运行日志，不能量化“几乎不命中”。
5. **旧 `src` 纯 procedural 分支的 `max_w` NameError 是否在历史跑分触发**：静态作用域风险成立，但未运行该路径或取得历史日志。
6. **Figure 2/3/4 的视觉细节**：本轮核验依据 txt 正文、图注与代码，没有读取论文图片像素；图中若有正文未提字段，仍未核实。
7. **LongMemEval 主结果的精确历史代码版本**：当前 `eval_longmemeval_all.py` 将 reasoning / answer 硬编码为 `gpt-4o`，与论文 Qwen2.5-72B 配置确定冲突；当前 HEAD 是否等于产出 Table 3 的历史 commit，缺运行记录和版本锚点。

## 生图 prompt 素材

### Paper flow prompt

```text
Create a clean horizontal academic systems diagram titled “PlugMem — Paper Methodology”. White background, compact sans-serif labels, thin charcoal arrows, no gradients or decoration. Use four swimlanes: INGEST, RETRIEVE, MAINTAIN, BASE AGENT. Use canonical short labels exactly: blue rectangles for LLM, orange rectangles for retrieval, yellow rectangles for fusion or scheduling, gray cylinders for stores, pale-purple rounded rectangles for IO. INGEST: IO:Trajectory → LLM:Extract “Standardize” → Store:Graph G_E; branch to LLM:Extract “Semantic” → Retrieval:Emb → Store:Graph G_S, and Retrieval:Emb “Segment” → LLM:Extract “Procedural” → LLM:Judge “Return 1–10” → Retrieval:Emb “Intent Dedup” → optional LLM:Rewrite → Store:Graph G_P. Show provenance links from G_S and G_P to G_E. RETRIEVE: IO:Query → LLM:Route → Retrieval:Emb “Init” → LLM:Judge “Enough?”; if no, LLM:Tag → parallel Retrieval:Emb and Retrieval:Graph → Fusion:Union → Retrieval:Rerank → back to “Enough?”; if yes, optional Retrieval:Graph “To Episodic” → LLM:Summarize → IO:RetrievedMemory → external LLM:Answer → IO:Answer. MAINTAIN: LLM:Resolve “Update” and Sched:Evict “Delete”. Keep all image labels short; omit file paths and long citations.
```

### Code flow prompt

```text
Create a matching horizontal academic systems diagram titled “PlugMem — Code Methodology”, using the same white academic visual system and canonical color legend. Use five main swimlanes: INGEST, RETRIEVE, CALLER, EVAL-ONLY, PAPER-ONLY DEAD; add compact MAINTAIN and CODE-ONLY sidebands. INGEST: IO:TurnPair → LLM:Extract “State / Subgoal / Reward” → Retrieval:Emb “Segment <0.75” → IO:Trajectory; branch to LLM:Extract “Semantic” → Retrieval:Emb, and LLM:Extract “Procedural, return=0” → NLP:TextDedup “Exact String”; merge into Store:Graph → Store:Vector “Chroma Persistence”. RETRIEVE starts IO:Query → LLM:Route “Memory Type” → LLM:Tag “Query Plan”, then three single-pass branches: Semantic = parallel Retrieval:Emb “Global Top-5” plus Retrieval:Graph “Tag Route” → Fusion:Union → Retrieval:Rerank “Cosine Top-10”; Procedural = Retrieval:Emb “One Intent” → Retrieval:Graph “Child Prescriptions” → Retrieval:Rerank “Top-1”; Episodic = Retrieval:Emb “Semantic Top-30” → Retrieval:Graph “Session Vote ≥3”. All end at IO:RetrievedMemory, then cross the system boundary to caller-owned LLM:Summarize → LLM:Answer → IO:Answer. EVAL-ONLY: optional semantic-only LLM:Judge loop, default off. MAINTAIN: Retrieval:Graph → Retrieval:Emb → LLM:Resolve → Store:Graph. CODE-ONLY: IO:TurnPair “Failure / Correction” → LLM:Extract → Store:Graph. PAPER-ONLY DEAD: red dashed LLM:Judge “Return Scorer”, Retrieval:Emb “Intent Cosine Dedup”, LLM:Judge “Generic Multi-Hop”, Fusion:Add “Importance”, and Sched:Evict “Episodic Compression”. Add a small warning strip: default benchmarks are single-pass; Chroma ANN unused; semantic rerank is pure cosine; reasoning is caller-owned. Keep labels short and omit code citations.
```

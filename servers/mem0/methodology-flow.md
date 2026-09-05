---
title: Mem0 methodology 流程图
date: 2026-09-05
tags:
  - memory-bench
  - methodology-flow
  - mem0
---

# Mem0 methodology 流程图

> [!note] 来源与口径
> 基于同目录 [[paper-architecture]] 与 [[code-architecture]]（勘误已按 [[verification]] 复核结论修正：Phase 8 补齐、linked_memory_ids 真实来源、paper 页码偏移）。词汇表与图例见全项目规范 `METHODOLOGY-FLOW-SPEC`。

## Paper 视角

Chhikara et al. 2025, *Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory*, arXiv:2504.19413（ECAI 2025）。

![[assets/mem0-paper-flow.png]]

### 核验真源

```mermaid
flowchart TB
    classDef llm fill:#dbeafe,stroke:#2563eb,stroke-width:2px
    classDef alg fill:#ffedd5,stroke:#ea580c,stroke-width:2px
    classDef store fill:#e5e7eb,stroke:#6b7280
    classDef io fill:#f3e8ff,stroke:#9333ea
    classDef async fill:#f0fdf4,stroke:#16a34a,stroke-dasharray:4 3

    subgraph INGEST["写入路径：每个 turn-pair 触发一次（§2.1）"]
        direction LR
        M["IO:TurnPair (m_t-1, m_t)"]
        CTX["上下文拼装 P=(S, 近m条, m_t-1, m_t)<br/>m=10（§2.1）"]
        EXT["LLM:Extract φ<br/>候选事实集 Ω（§2.1）"]
        RET["Retrieval:Emb<br/>top-s 相似老记忆<br/>s=10（§2.1）"]
        RSV["LLM:Resolve（tool-call）<br/>ADD / UPDATE / DELETE / NOOP<br/>判定顺序见 Alg.1（Appx.B）"]
        VS[("Store:Vector<br/>自然语言事实<br/>+ dense embedding")]

        M --> CTX --> EXT
        RET --> RSV
        EXT -->|"每个候选 ω_i"| RET
        RSV -->|"ADD / UPDATE / DELETE"| VS
    end

    subgraph ASYNC["异步旁路"]
        SUM["LLM:Summarize<br/>会话摘要 S 周期刷新<br/>（§2.1，独立于主流程）"]
        SUM -.->|"S"| CTX
    end

    subgraph RETRIEVE["检索路径"]
        direction LR
        Q["IO:Query"]
        QEMB["Retrieval:Emb<br/>query 向量化→top-k<br/>（论文未给 k 值与算法细节）"]
        ANS["LLM:Answer<br/>{Memories} 拼进 prompt<br/>（Appx.A 模板，p.20）"]
        A["IO:Answer"]
        Q --> QEMB --> ANS --> A
        VS --> QEMB
    end
```

Mem0g 变体（论文 §2.2，图略差异见下）：写入侧 `LLM:NER`（实体抽取）+ `LLM:RelGen`（关系生成）→ 三元组落 `Store:Graph`（Neo4j，实现细节 p.6）；节点匹配走 `Retrieval:Emb`（阈值 t）；冲突由 `LLM:Resolve` 判定后**标 invalid 而非物理删除**（p.6）。检索为双路：entity-centric + semantic triplet（p.6）。

## Code 视角

repo `~/Documents/repo/mem0` @ `dae67f74`（mem0ai==2.0.20）。

![[assets/mem0-code-flow.png]]

### 核验真源

```mermaid
flowchart TB
    classDef llm fill:#dbeafe,stroke:#2563eb,stroke-width:2px
    classDef alg fill:#ffedd5,stroke:#ea580c,stroke-width:2px
    classDef nlp fill:#ecfccb,stroke:#65a30d
    classDef store fill:#e5e7eb,stroke:#6b7280
    classDef io fill:#f3e8ff,stroke:#9333ea
    classDef dead fill:#fee2e2,stroke:#dc2626,stroke-dasharray:5 5

    subgraph INGEST["写入路径：每 session 一次（add_conversation 整段传入，Phase 0-8）"]
        direction LR
        M["IO:Session messages"]
        P0["IO:近10条历史消息<br/>main.py:918-920（Phase 0，读 messages 表）"]
        P1["Retrieval:Emb<br/>top-10 老记忆（去重参考）<br/>main.py:923-929（Phase 1）"]
        P2["LLM:Extract（ADD-only，单次调用）<br/>prompts.py:468 'Your sole operation is ADD'<br/>main.py:940（Phase 2）"]
        P3["Retrieval:Emb<br/>批量向量化 main.py:991（Phase 3）"]
        P4["NLP:HashDedup<br/>md5 去重 main.py:1005-1043（Phase 4-5）"]
        VS[("Store:Vector<br/>chroma 等<br/>main.py:1045-1075（Phase 6）")]
        AUD[("Store:SQLite history<br/>审计日志，event='ADD' 硬编码<br/>main.py:1070")]
        P6["NLP:NER（spaCy）<br/>实体共现生成 linked_memory_ids<br/>main.py:1086 起（Phase 7）"]
        ES[("Store:Entity<br/>独立 collection")]
        MSG[("Store:SQLite messages<br/>原始对话逐条落盘<br/>storage.py:134-141（Phase 8）<br/>Phase 0 会读回喂抽取 prompt")]

        M --> P0 --> P1 --> P2 --> P3 --> P4 --> VS
        VS --> AUD
        P4 --> P6 --> ES
        M --> MSG
        MSG -.->|"读回"| P0
    end

    subgraph DEAD["论文宣称但代码不成立（verification 修正口径）"]
        D1["LLM:Resolve 四操作自动判定<br/>自动路径=零调用点死代码<br/>（手动 CRUD 路径存在 UPDATE/DELETE<br/>写入 history：main.py:2084/2116，非 LLM 判定）"]
        D2["Mem0g 图记忆<br/>= 模块整体不存在"]
        D3["LLM:Summarize 异步摘要<br/>= prompt 留坑、参数从未传<br/>（main.py:948-953/2610-2615）"]
        D4["LLM 输出的 linked_memory_ids<br/>= 同步/异步路径均被丢弃<br/>（main.py:1015-1039/2673-2697）"]
    end

    subgraph RETRIEVE["检索路径：search() 一步到位，无迭代循环"]
        direction LR
        Q["IO:Query"]
        QE["Retrieval:Emb<br/>over-fetch 4×top_k<br/>main.py:1641"]
        BM["Retrieval:BM25<br/>chroma 后端下恒为空<br/>main.py:1646"]
        EB["Retrieval:EntityBoost<br/>spaCy 缺失时恒为空<br/>main.py:1661-1663"]
        FUS["Fusion:Add<br/>score_and_rank 加法融合<br/>threshold 只卡语义分<br/>scoring.py"]
        OUT["IO:结构化 top-k 列表<br/>（不生成答案，调用方自拼 prompt）"]

        Q --> QE & BM & EB --> FUS --> OUT
    end

    VS -.-> QE
    ES -.-> EB
```

> [!warning] 环境退化事实（memory-bench 实测）
> chroma 后端（无 BM25 通道）+ venv 未装 spaCy（无实体通道）→ 三通道设计实际退化为**纯语义单通道**，检索侧等价于裸向量 RAG。

## 新登记 module

- `Retrieval:EntityBoost`：query 实体命中加分通道（mem0 特有的第三检索通道，非独立检索器，归 Retrieval 类）
- `IO:TurnPair` / `IO:Session`：写入触发粒度的输入节点（区分论文 turn-pair 触发 vs 代码 session 触发）

## 不确定处

无（mem0 为样例系统，verification.md 已全量核对 46+61 条断言）。

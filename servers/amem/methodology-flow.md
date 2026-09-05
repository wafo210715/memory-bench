---
title: A-Mem methodology 流程图
date: 2026-09-05
tags:
  - memory-bench
  - methodology-flow
  - amem
---

# A-Mem methodology 流程图

> [!note] 来源与口径
> 本系统按 [[METHODOLOGY-FLOW-SPEC]] 的特例只画 **Code 视角**，不补 Paper 视角。主真源是同目录 [[ARCHITECTURE]]，节点与边已逐项回查 `fixed.py`、`embedding.py` 和 `server.py`；本目录没有 `verification.md`，因此代码与架构文档冲突时以当前封装臂代码为准。图的主对象是 `MEMBENCH_AMEM_MODE=fixed` 下 memory-bench 的实测封装行为，不代表上游 A-MEM 原生臂。

## Code 视角

repo `~/Documents/repo/memory-bench`，fixed 臂实现源自 commit `b3acfb2`；数据修正 commit `b5b43f1` 不改变下图方法链。

![[assets/amem-code-flow.png]]

### 核验真源

```mermaid
flowchart TB
    classDef llm fill:#dbeafe,stroke:#2563eb,stroke-width:2px
    classDef alg fill:#ffedd5,stroke:#ea580c,stroke-width:2px
    classDef nlp fill:#ecfccb,stroke:#65a30d
    classDef store fill:#e5e7eb,stroke:#6b7280
    classDef io fill:#f3e8ff,stroke:#9333ea
    classDef dead fill:#fee2e2,stroke:#dc2626,stroke-dasharray:5 5
    classDef async fill:#f0fdf4,stroke:#16a34a,stroke-dasharray:4 3
    classDef learn fill:#fae8ff,stroke:#a21caf
    classDef sched fill:#fef9c3,stroke:#ca8a04

    subgraph INGEST["写入路径：add_conversation 接收 session，逐 turn 建一条 note"]
        direction LR
        S(["IO:Session<br/>结构化 turns；逐 turn 循环<br/>server.py:256-265"])
        EXT["LLM:Extract<br/>一句 context + ≥3 keywords + ≥3 tags<br/>失败回退 [], General, []<br/>fixed.py:168-195,366-381"]
        NEAR["Retrieval:Emb<br/>新 note 原文作 query → top-5 老 note<br/>老 note document 是富文本<br/>fixed.py:255-279,284-299"]
        EVO["LLM:Evolve<br/>should_evolve + strengthen / update_neighbor<br/>真实 UUID；失败则跳过演化<br/>fixed.py:293-363"]
        GS[("Store:Graph<br/>内存 MemoryNote dict + 单向 UUID links<br/>原文不改；neighbor context/tags 硬覆盖<br/>fixed.py:332-358,381-384")]
        RICH["Retrieval:Emb<br/>新 note 富文本编码<br/>content + keywords + tags + context<br/>fixed.py:199-240"]
        VS[("Store:Vector<br/>per-scope Chroma + embedding-3<br/>session 末 count() 就绪屏障<br/>embedding.py:42-98; server.py:209-216,270-278")]
        BATCH["Sched:Batch<br/>session 末 flush dirty UUIDs<br/>server.py:266-269"]
        REIDX["Retrieval:Emb<br/>被改写 neighbor 逐条 delete + re-add<br/>fixed.py:234-252"]

        S -->|"每个 turn"| EXT --> NEAR
        VS -.->|"检索已存富文本向量"| NEAR
        NEAR -->|"有邻居"| EVO
        NEAR -->|"无邻居：0 次 evolution LLM"| GS
        EVO -->|"存新 note / links；覆盖老 note 语义字段"| GS
        GS -->|"每条新 note"| RICH --> VS
        GS -.->|"dirty UUID 集合"| BATCH --> REIDX --> VS
    end

    subgraph RETRIEVE["检索路径：每次 retrieve；benchmark 传 top_k=20，函数默认值为 5"]
        direction LR
        Q(["IO:Query<br/>可选 filter.scope_id<br/>server.py:286-305"])
        DIRECT["Retrieval:Emb<br/>query 编码 → Chroma 距离排序 top-k<br/>fixed.py:397-430"]
        GRAPH["Retrieval:Graph<br/>从前 k-reserve 条直达命中沿 links 扩展<br/>去重、跳过失效 UUID<br/>fixed.py:433-462"]
        FUSE["Fusion:Quota<br/>reserve=round(k×0.25)，至少 1、至多 k-1<br/>邻居不足由后续直达命中回填<br/>fixed.py:403-406,464-471"]
        OUT(["IO:Evidence<br/>原文 +〔一句 context〕+ timestamp<br/>不在记忆系统内生成答案<br/>server.py:307-341"])

        Q --> DIRECT
        DIRECT -->|"ranked direct hits"| FUSE
        DIRECT -->|"前 k-reserve 条作种子"| GRAPH -->|"最多 reserve 条 linked neighbors"| FUSE
        FUSE --> OUT
        VS -.-> DIRECT
        GS -.-> GRAPH
    end

    subgraph STATE["跨进程旁路：snapshot / restore"]
        direction LR
        SNAP[("Store:JSON<br/>notes.json 是真实 note 载体<br/>另存 homes/ + scopes.json<br/>server.py:389-400,447-485")]
        RESTORE["Retrieval:Emb<br/>restore 后批量重灌 + 重建索引<br/>Chroma batch=512，embedding chunk=64<br/>server.py:404-444,488-516"]

        GS -.->|"snapshot 序列化"| SNAP
        SNAP -.->|"restore notes"| GS
        SNAP --> RESTORE --> VS
    end

    class EXT,EVO llm
    class NEAR,RICH,REIDX,DIRECT,GRAPH,RESTORE alg
    class VS,GS,SNAP store
    class S,Q,OUT io
    class BATCH,FUSE sched
```

> [!warning] 环境退化与运行边界
> - `MEMBENCH_AMEM_MODE` 默认是 `native`；未显式设为 `fixed` 时，上图的 note construction、真实 UUID 演化、dirty reindex、邻居配额和 context envelope 都不会按 fixed 路径执行（`server.py:38-41,209-230`）。
> - `LLM:Extract` 重试耗尽后回退为空 keywords/tags 与 `General` context，富文本索引随即退化为仅原文；`LLM:Evolve` 失败则该 note 仍会入库，但不建链、不改邻居（`fixed.py:189-195,326-363`）。
> - embedding 端点或密钥缺失会在初始化/首次编码时报错，不是静默降级（`embedding.py:26-39`）。
> - 多 scope 且未传 `filter.scope_id` 时只查 sidecar 中第一个 scope；除 `scope_id` 外的 filter 全部忽略并写进 `native_notes`（`server.py:291-295,332-335`）。

> [!note] 设计取舍
> - 写入构图固定 `WRITE_K=5`；检索 `top_k` 由调用方传入，统一 benchmark 口径是 20，但 MCP 函数签名默认仍是 5（`fixed.py:58-60`; `server.py:286-287`; `docs/interface-spec.md:154`）。
> - `update_neighbor` 原地硬覆盖 context/tags，不保留版本；content 永不改。links 只写在新 note 上，不反向补边，也没有删除或遗忘机制。
> - 邻居预留比例默认 25%，未做敏感性分析。它用直接命中精度换取沿链线索，邻居不足时才用第 `direct_quota+1` 名以后的直达结果回填。
> - dirty note 延迟到 session 末重算，进程在 flush 前崩溃会留下“内存语义字段已变、向量仍旧”的窗口。
> - 检索不做时间排序、衰减或过滤，`retrieval_count` 也不递增；日期前缀若存在，只作为普通原文参与 embedding。

## 新登记 module

| module | 类别 | 理由 |
|---|---|---|
| `LLM:Evolve` | LLM 调用·蓝 | 单次调用同时决定 `should_evolve`、新 note 的链接强化和邻居语义字段改写。它不是事实抽取，也不是冲突消解；用独立动词保留 A-Mem 的核心自演化语义 |
| `Fusion:Quota` | 融合/门控·黄 | 按固定预算合并 direct hits 与 linked neighbors，并在邻居不足时用 direct hits 回填。与分数相加、RRF、插值或学习门控均不同 |
| `IO:Evidence` | 输入/输出·淡紫 | 记忆封装臂返回给外部答题模型的 evidence envelope 列表；A-Mem 自身不执行 `LLM:Answer` |
| `Store:JSON` | 存储层·灰 | `notes.json` 是 A-Mem 跨进程快照的真实结构化载体；与作为在线记忆形态的 `Store:Plaintext` 不同 |
| `Sched:Batch` | 调度·黄 | session 末集中处理 dirty note 的触发点；与 AtomMem methodology-flow 中画像攒批使用同一 canonical module，建议统一登记进总词表 |

## 不确定处

1. [[ARCHITECTURE]] 写“用原文+语义字段拼成的富文本”检索 top-5 邻居，但 `process_memory()` 明确把 `note.content` 传给 `find_related_with_ids()`（`fixed.py:289`）。因此当前图按“新 note 原文 query，对已存富文本 document 检索”绘制；文档原句是否只是省略了 query/document 两侧差异，未确认。
2. [[ARCHITECTURE]] 写“每 100 次成功演化 consolidate”，但 fixed 臂覆盖的 `add_note()` 只递增 `evo_cnt`，没有阈值检查或 `consolidate_memories()` 调用；仓库内该方法只有定义、没有 fixed 臂调用点（`fixed.py:365-394`）。这是有意取消还是漏迁移，未确认，故不进入主流程图。
3. [[ARCHITECTURE]] 与 `fixed.py:41-44` 注释称 dirty reindex 是“批量 flush / embedding 批量调用”，但 `flush_dirty()` 实际逐 UUID 调 `_index()`，每次 `delete_document()` 后单条 `add_document()`（`fixed.py:234-252`）。只有 restore 明确按 512 条批量写入；session-end flush 是否计划后续批量化，未确认。
4. 本目录没有 `verification.md`，本轮只做静态代码核验，没有重跑 fixed 臂或检查 MCP trace；LLM 失败率、实际邻居占比、dirty reindex 调用数仍依赖既有实测记录。

## 生图 prompt 素材

```text
Create one clean horizontal academic systems diagram titled "A-Mem Fixed — Verified Code Path". White background, compact sans-serif typography, thin charcoal connectors, no gradients, no decorative artwork. Use three aligned swimlanes: INGEST, RETRIEVE, and SNAPSHOT / RESTORE. Use canonical labels exactly and short English captions only. Color and shape system: blue rectangles for LLM modules, orange rectangles for Retrieval modules, yellow rectangles for Fusion and Scheduler modules, gray cylinders for Store modules, and pale-purple rounded rectangles for IO modules. INGEST: IO:Session (structured turns, one note per turn) -> LLM:Extract (one-sentence context, keywords, tags) -> Retrieval:Emb (raw new content queries top-5 stored rich-text notes) -> LLM:Evolve (should_evolve; strengthen UUID links; hard-overwrite neighbor context/tags). Store every new note in Store:Graph (in-memory notes plus one-way UUID links), encode content + keywords + tags + context with embedding-3, then write Store:Vector (per-scope Chroma). Branch dirty neighbor UUIDs to Sched:Batch (session-end flush) -> Retrieval:Emb reindex -> Store:Vector. Show a bypass from neighbor search to storage when no neighbor exists, with no evolution LLM call. RETRIEVE: IO:Query -> Retrieval:Emb top-k direct hits; use the first k-reserve hits as seeds for Retrieval:Graph one-hop link expansion; combine direct and neighbor results in Fusion:Quota with 25% neighbor reserve and direct-hit backfill -> IO:Evidence (original text, one-sentence context, timestamp; no answer generation). Feed Store:Vector into direct retrieval and Store:Graph into link expansion. SNAPSHOT / RESTORE: Store:Graph -> Store:JSON notes.json -> Retrieval:Emb batch rebuild -> Store:Vector, with a restore arrow back to Store:Graph. Add tiny factual captions: write k=5; benchmark retrieval k=20; source text immutable; no time decay; no forgetting; default server mode is native, fixed must be explicitly enabled. Keep labels readable and the data flow strictly left-to-right within each lane.
```

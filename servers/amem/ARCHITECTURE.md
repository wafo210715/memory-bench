# A-Mem fixed 臂：完整操作流程与设计取舍

> 写于 2026-09-04，对应 commit `b3acfb2`（fixed 臂）+ `b5b43f1`（数据修正）。
> 双臂对照的动机、七个静默失效的修复、以及实测结果见
> `docs/../research-vault` 的 `[[amem-paper-vs-code-benchmark]]` 与论文笔记保真度核对表
> （本条 2026-09-05 复核时本机挂载树内无 research-vault 目录，未能核实该引用是否仍有效）。
> 本文档只回答一个问题：**fixed 臂跑起来之后，每一步到底发生了什么。**
>
> **2026-09-05 勘误**：本文已按同目录 `verification.md` 的逐条复核结论修正（共 14 处：6 处事实、0 处行号/锚点、8 处表述限定）。原始未修正版本见 git 历史。

## 写入侧（ingest，每个 turn 一次）

```text
turn 进入（"user: [2023-05-08] Caroline: ..."）
  │
  ├─ ① note construction                    [LLM 调用 1/2]
  │    原文 → 一句话摘要 + ≥3 关键词 + ≥3 标签
  │    （论文 Eq.2，官方代码里这步从未执行——我们补的 F1）
  │
  ├─ ② 邻居检索
  │    查询侧只用原文做向量（find_related_with_ids 传 note.content）；
  │    「原文+语义字段」拼成的富文本（Eq.3，F3）只用于库内被检索的老记忆那一侧
  │    在库里找 top-5 相似的老记忆（k=5 是官方默认值，fixed 臂里是可调环境变量，非硬编码）
  │
  ├─ ③ evolution                            [LLM 调用 2/2]
  │    把新 note + 5 个邻居（带真实 UUID，F4）喂给 LLM，它返回：
  │      · should_evolve: 要不要演化
  │      · suggested_connections: 该连谁（只接受真实存在的 ID）
  │      · new_context / new_tags: 每个邻居的新摘要和标签
  │    ├─ "strengthen"      → 新 note 的 links 加上选中邻居（同一响应里的 tags_to_update
  │    │                      还会顺带覆盖新 note 自己的 tags，非只影响邻居）
  │    └─ "update_neighbor" → 改写邻居的摘要/标签（按真实 ID 定位，F5），
  │                           被改的邻居标记进 _dirty 集合
  │    （原文 content 任何情况下不动）
  │
  ├─ ④ 入库
  │    新 note 写进内存 dict + chroma（document=富文本，metadata 存原文）
  │
  └─ ⑤ 「每 100 次成功演化 → consolidate」只存在于 native 臂，fixed 臂没有这一步
       fixed 的 add_note() 覆盖父类入口后只做 self.evo_cnt += 1，没有阈值判断、
       也没有调用点；consolidate_memories() 在 fixed.py 里全仓库无 caller。
       P9 打的补丁（_patch_consolidate）只挂在 server.py 的 native 分支上。
```

## 每个 session 灌完时（add_conversation 末尾）

```text
flush_dirty                                    [逐条 embedding 调用，非批量]
  把 ③ 里被改过摘要/标签的邻居逐条重算向量（delete+re-add），每条各发一次 embedding API
  ← 论文没写这步怎么落，我们补的 F-dirty；
    没有它，③ 的改写对检索永远不生效（Eq.3 的必然推论）

就绪屏障（count() 一次，P10）
```

## 读取侧（retrieve，每次查询）

```text
query 进入
  │
  ├─ ⑥ 向量检索
  │    query 编码 → Chroma 近似最近邻（ANN，非全库精确比对）→ 按距离排序，直接取回 k 条
  │
  ├─ ⑦ 配额切分（F8）
  │    k=20 → 直接命中 15 条 + 邻居预留 5 条（25%）
  │    ├─ 先取 top-15 直接命中
  │    ├─ 沿这 15 条的 links 找邻居（跳过已见/已删），
  │    │   填进预留槽（is_neighbor=true 标记）
  │    └─ 邻居不够 5 条 → 用第 16-20 名直接命中回填，总数恒为 20
  │       （候选池本身只取 k=20 条，代码注释写「多取一些」但实际没多取；
  │        库内 note 总数 < 20 时无法回填满 20 条）
  │
  └─ ⑧ envelope 渲染（F9）
       每条 = 「- 时间戳 · 原文〔一句话摘要〕」，整条 >600 字符会截断（每条各自限额，非共享预算）
```

## 跨进程（快照/恢复）

```text
snapshot: 内存 notes 序列化成 notes.json（真正载体）
restore : 批量重灌 + 重算向量（P12 修成批量；1297 条数量可复现，24s 耗时日志未记录，未能核实）
```

## 检索路径上没有任何东西

- **时间**：不排序、不衰减、不过滤。原文 `[日期]` 前缀是最直接的时序信号，
  但不是唯一的——F3 富文本里 LLM 生成的 context 也常带日期表述
- **检索计数**：`retrieval_count` 永远不涨（官方就没写更新点，我们没补）
- **演化是单向的**：邻居被改写，但不会反向补 links（照论文）
- **记忆永不删除**：fixed 臂机制层没有删除路径，links 只增不减
  （上游定义了从未被调用的 delete()；论文 Ps3 的 JSON 示例里列过「prune」，
  但正文只讲了 strengthen/update_neighbor 两种，「照论文无遗忘」这个说法不完全准确）

## 设计取舍记录（2026-09-04 与 wafo 对齐）

### ① F-dirty 的崩溃窗口

向量化重算攒到 session 末尾批量做（省 API 调用）。session 中途崩溃时，
已改写的摘要/标签还没重算向量，这部分改动丢失。评测无影响（runner 每
session 都会 flush），离线批处理场景需要知道这个窗口。

### ② 演化语义：硬改 vs 软改

`update_neighbor` 是**原地覆盖**（硬改）——这是照论文复现的选择，论文 §3.3
就是 `mj* 替换 mj`。

对比 [[Rasmussen-2025-Zep-Temporal-Knowledge-Graph-Architecture-for-Agent-Memory]]
（graphiti/Zep）的做法：边失效是**软改**——旧关系标 `tinvalid` 而非物理删除，
双时间轴可追溯。TEPA 类 reversal 场景下软改可回滚，硬改不可。

**语义漂移未测**：摘要被反复改写会不会逐渐失去原意，论文没讨论，我们没测。
可行的测法（未执行）：灌完后 dump 全部 note 的 context 版本历史——但硬改没有
历史可 dump，这本身就是硬改的定义性缺陷。要测得先改成软改（追加式 context
列表 + 检索时取最新），那已经是新机制而非复现了。

### ③ 25% 邻居配额（NEIGHBOR_RATIO=0.25）

拍脑袋定的初始值，环境变量 `MEMBENCH_AMEM_NEIGHBOR_RATIO` 可调，未做敏感性分析。

**wafo 的判断（2026-09-04）**：邻居如果是噪声也无妨——它只是注入上下文，
与问题相关与否由答题模型的智力判断。即：把邻居视为「廉价的额外线索」而非
「必须精确的检索结果」，配额比例的精度不重要，重要的是有这个通道。
（此判断隐含一个前提：噪声邻居挤占的是 k=20 配额里直接命中的槽位（由 NEIGHBOR_RATIO
决定，与 600 字符无关，600 是每条 envelope 各自的截断上限，不是共享预算）——
比例越大，直接命中的精度损失越大，这个 trade-off 依然存在。）

### ④ 写入 k=5 / 检索 k=20

写入侧 k=5（官方默认，构图密度参数）保持不动——2026-08-30 决策。
读取侧 top_k=20（spec §7 全臂统一）。

**wafo 的倾向（2026-09-04）**：写入侧是规则、取回侧倾向多取。当前 20 与此
一致，不需要动。

### ⑤ 归因未拆

fixed 的总分里混着 F9（摘要进上下文）的贡献。呈现层增益 vs 机制增益，
拆分需要第三臂（fixed 但关掉 F9），2026-08-30 决策不做。引用 0.563 时
需带此注脚——`runs/amem-ab-3conv` 实测复现值是 0.5392（非 0.563），
且该 run 的 amem_fixed evidence 只覆盖 conv-26/conv-49 两个 conv，
第三个 conv-30 缺失，与「3 conv」的口径不一致。

## 相关

- 实现代码：`servers/amem/fixed.py`（机制）、`servers/amem/embedding.py`（向量层）、
  `servers/amem/server.py`（双模式 MCP 层）
- 上游缺陷修复：commit `8d986e4` → `af56715`（三层，按发现次序；第四层是页首的 `b3acfb2`，新增 amem_fixed）
- 实测结果：run `runs/amem-ab-3conv`（3 conv），commit `b5b43f1`

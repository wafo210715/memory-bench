# 接力提示词 — memory-bench methodology 流程图项目

> 把下面 `====` 之间的全部内容，原样粘贴给新会话。

====

我在 `memory-bench` 项目上有一件跨会话的长任务，上一个会话做到一半撞上速率限制。下面是完整交接。**先读完再动手，不要重做已完成的部分。**

## 0. 环境与路径

- 已连接文件夹：`/Users/guanhongli/Documents/repo/memory-bench`
- **还需要你主动申请两个文件夹的访问权限**（用 `device_request_folder_access`）：
  - `/Users/guanhongli/Documents/wafo-base/literature` —— 论文原文库（442 篇，pdf + pdftotext 出的 txt）
  - `/Users/guanhongli/Documents/repo` —— 14 个上游代码仓库
- 所有文件都在**我本机**上。用 `mcp__remote-devices__device_bash` 干活（`$HOME/mnt/<folder>/…`），
  **不要**用云容器的 Bash/Read/Grep 去找这些文件，那台机器上没有。
- 例外：需要**渲染 SVG / 看图 / 装 python 包**时，在云容器里做，做完 `device_commit_files` 写回。

## 1. 任务是什么

`servers/` 下有 14 个记忆系统，每个系统有两份架构文档（`paper-architecture.md` 描述论文机制、
`code-architecture.md` 描述代码实际行为）。我要做两件事：

1. **验证**这些文档 —— 对着论文原文和源码逐句复核。
2. 把两份文档的流程**转化成 methodology 流程图**。硬要求：**跨论文之间，同一个 module
   （比如很多论文都用了 BM25）必须用一样或类似的形式表示。**

## 2. 我已经拍板的 8 条决策（不要再问我一遍）

| # | 事项 | 决定 |
|---|---|---|
| 1 | 验证深度 | **全文逐句复核**全部 26 份文档（不是抽查）。已完成。 |
| 2 | 图怎么摆 | 每系统 **3 张**：paper 一张、code 一张、**paper↔code 分歧图**一张 |
| 3 | 跨系统统一 | 我的猜想是 14 个能进**同一套骨架**，具体骨架落在哪要**遍历全文实证推导**，不许预设。若推不出来才退回"只统一共享模块、结构各系统自由"。→ 已推导出来，见 §3.2 |
| 4 | 产出形态 | Mermaid 源码回写各 md 文档 **+** 一个 HTML gallery **+** 矢量图 SVG/PDF |
| 5 | 51 条硬错 | **直接改源档，错的就修**（不是只在图里绕开） |
| 6 | 图上语言 | **英文节点 + 中文说明**，中文要通俗自然，别翻译腔 |
| 7 | amem / mandol | 出**三张图**，并且**补写**成和其他 12 个一样的 paper/code 双份文档 |
| 8 | 生图 | 上个会话没有生图模型工具，改用**手写矢量图 + 渲染器**。见 §5 的重要背景。 |

## 3. 已经完成的部分

### 3.1 全量复核 → `servers/<sys>/verification.md`（14 份，全部完成）

14 个 agent 各自读完一篇论文全文 + 一个源码仓库 + 两份架构文档，逐条核对。
共约 **1,530 条断言**，判定 `✓ 属实 / ✗ 不实 / ◐ 部分属实需限定 / ? 无法核实`，
每条都带**亲眼看到的**证据（论文 txt 行号 或 `file.py:NNN`）。合计 **51 条 ✗ + 253 条 ◐**。

每份报告结构：总评 → 逐条核对表 → 步骤清单（论文侧/代码侧）→ 论文↔代码分歧 → 新造标签 → 统计。

**注意 `letta/verification.md` 是两份报告的合并版**（162 行核对、✓128/✗6/◐28/?0），
因为当时有另一个会话在并行做同一件事，两边都验了 letta。合并时逐条破了 15 处判定冲突。

### 3.2 实证推导的统一骨架 → `servers/METHODOLOGY-SKELETON.md`

**这是整个项目的核心产出，务必先读完这份文件。** 要点：

- 推导方法是**自下而上**的：14 个 agent 互不通信，各自产出"论文侧/代码侧操作步骤序列"共 30 条；
  primitive 标签取自一份 32 条种子词表，允许新造但须说明理由 —— 最后新登记了 10 个。
- **顶层二分不是"写入/检索"**。30 条序列全部自发在同一处断开（包括 3 个 forward-pass 内部的
  系统，它们既没写入也没检索）。正确的名字是 **A 形成期 query-independent / B 动员期 query-conditioned**。
  逼出这个命名的是 Memory Decoder：它的稠密检索**真实存在但发生在建 datastore 的时候**，
  推理时 Faiss 索引根本不加载 —— 用"检索"当阶段名，这个系统无法归类。
- 十四个阶段：`A1 INTAKE / A2 DISTILL / A3 ADMIT / A4 INDEX / A5 COMMIT / A6 INTERNALIZE`
  ‖ `B1 CUE / B2 RECALL / B3 EXPAND / B4 APPRAISE / B5 SELECT / B6 DELIVER / B7 GENERATE / B8 LOOP`
- 文件里有 **14×14 的覆盖矩阵**（格式 `论文侧|代码侧`），以及从矩阵读出的四条结论。
  最重要的两条：**B6 DELIVER 是唯一 14/14 全有的阶段**，且"交付方式"只有三种
  （拼进 prompt / 改隐状态 / 改输出分布）—— 这三种恰好就是三个家族的定义；
  **A3 ADMIT 是论文↔代码退化最集中的一列**。

### 3.3 源档修正（7/14 完成）

按各自 `verification.md` 的结论，把 ✗ 和 ◐ 改回了源文档，文档头加了一行
`> **2026-09-05 勘误**：本文已按同目录 verification.md … 修正（共 N 处：…）`。

**已完成**：`mem0` `graphiti` `atommem` `memos` `mragent` `graphmemix` `plugmem`
**未做**：`transmem` `livemem` `memorydecoder` `memharness` `letta` `amem` `mandol`

### 3.4 渲染器 + mem0 样图 → `servers/flowgen/`

`servers/flowgen/README.md` 有完整用法和 spec 字段说明，**动手前读它**。核心思想：

> 每个系统只写一份结构化 JSON，图由同一套代码渲染。
> **跨系统一致性靠代码保证，不靠画图的人自律** —— 泳道 x 坐标、配色、形状、图例全部由
> `render.py` 统一计算，所以"同一个 BM25 在 14 张图里长在同一格、长得一模一样"是机械结果。
> 42 张图靠人手对齐是不可能对齐的。

三个设计要点：
1. **泳道 = 阶段，不是顺序**；真实执行顺序看节点左上角黑圈里的数字（`seq` 字段）。
   mem0 是最好的例子：它 ③先检索 ④再抽取 ⑤再编码 ⑥再去重，阶段上来回跳。
2. **灰掉的泳道 = 这个系统没有这一步**，不是"没画"。空格子是分类学结果。
3. **行号直接印进节点**（`main.py:1005-1043 Phase 4-5`），因为这是手写矢量图，不怕文字失真。

已产出：`servers/mem0/assets/mem0-{paper,code,diff}-flow.svg`，spec 在 `servers/flowgen/specs/`。
**mem0 那三张是已批准的样板，后面 13 个照它的规格做。**

## 4. 接下来要做什么（按这个顺序）

1. **补完 7 个系统的源档修正**（§3.3 未做的那 7 个）。做法：每个系统一个 subagent，
   让它 `cat $HOME/mmscratch/FIX_TASK.md` 读任务规格再执行。
   ⚠️ 如果 `$HOME/mmscratch/` 已经随会话销毁了，就照 §3.3 的描述重写一份规格。
2. **给 amem / mandol 补写 paper-architecture.md + code-architecture.md 双份文档**
   （现有的 `ARCHITECTURE.md` 是 memory-bench 自己 fixed 臂/adapter 的实测版，保留为第三份）。
   两个系统的 verification.md 里已经有论文侧、上游代码侧、adapter 侧三条步骤清单，直接用。
3. **写 13 个系统 × 3 张图的 spec JSON 并渲染**。事实依据一律以 `verification.md` 的复核结论为准，
   不是架构文档原文。可以派 subagent 写 spec（它们读得到 verification.md 和架构文档），
   但**渲染和目检必须你自己来**，保证风格不漂。
4. ~~**更新各 `methodology-flow.md`**，把图从旧 PNG 换成新 SVG。~~
   **已作废（2026-09-06 用户拍板）**：旧 PNG 是 GPT Image 生图线的成果，用户双线推进
   （GPT Image 线 / SVG 线）最后两边对比。**PNG 嵌图与文件一律保留不动，不移不删**；
   SVG 另行展示，不替换 PNG。
5. **HTML gallery**：14 个系统的图并排 + 共享模块图例 + 跨系统模块对照矩阵（哪个系统用了
   BM25/PPR/cross-encoder…），可点击跳转。发布成 Artifact。
6. **PDF 导出**（云容器里 `cairosvg` 装超时了，换 `rsvg-convert` 或浏览器打印）。

## 5. 三个必须知道的坑

1. **仓库里有另一个会话留下的东西，别当成自己的。** 那个会话已经停了，但它留下了：
   - `servers/METHODOLOGY-FLOW-SPEC.md` —— canonical module 词汇表 + classDef + 布局约定。
     **这份仍然有效**，节点命名和配色照它来；它管"节点长什么样"，
     `METHODOLOGY-SKELETON.md` 管"节点摆在哪"，两份配合使用。
   - `servers/<sys>/methodology-flow.md`（14 份）+ `servers/<sys>/assets/*.png`（26 张 GPT-Image 图）。
     ~~这些 PNG 没有按阶段泳道对齐，也没经过复核勘误，属于 v1。新 SVG 出来后把 PNG
     移到 `assets/v1-legacy/` 保留，不要直接删。~~
     **已作废（2026-09-06 用户拍板）**：PNG 不是待淘汰的 v1，是用户双线推进中
     GPT Image 生图线的参考成果，最后要和 SVG 线对比。**保留原位，不移不删不替换。**
   - 它那份 spec 的 §6 记着"amem/mandol 只画 code 单图"—— **这条已被我推翻**，见 §2 第 7 条。
2. **Letta/MemGPT 那篇论文本地没有。** 我查了三遍确认：`find` 零结果；全库 grep "memgpt"
   只命中 20 篇引用它的论文；我自己的 `literature/_index.md:382` 白纸黑字写着
   "同批的 #2 MemGPT/Letta 仍未补"。已有的 letta 复核是靠联网抓 arXiv:2310.08560 做的。
   **别凭记忆当论文原文用**，抓不到的断言判 `?`。
   letta 仓库的 `main` 分支源码已被清空，文档基于 `origin/archive`，用
   `git show origin/archive:<path>` 读，**不要 checkout、不要改我的仓库**。
3. **subagent 是必须的**，这个量级单会话做不完。有效模式是：把任务规格写成一个文件放在
   `$HOME/mmscratch/`，每个 subagent 只收到"读这个文件 + 你负责哪个系统 + 该系统的特殊情况"。
   一次发 7 个左右。让它们把产出写进文件、回复只给摘要，别让它们把表格贴回来。

## 6. 风格要求

- 中文说明要**通俗自然**，别翻译腔，别堆术语。
- 复核要有**对抗性**：没亲眼找到证据不许判 ✓，否定式断言（"代码里没有 X"）必须主动证伪。
- 发现我给的信息有错，**直接说**，别顺着我编。上个会话我坚持说论文在本地库里，
  它查完证据告诉我不在 —— 这是对的做法。

====

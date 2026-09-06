# flowgen — methodology 流程图渲染器

把每个记忆系统的流程写成一份结构化 JSON，由同一套代码渲染成 SVG。
**跨系统一致性靠代码保证，不靠画图的人自律** —— 泳道 x 坐标、节点配色、形状、图例全部由
`render.py` 统一计算，所以"同一个 BM25 在 14 张图里长在同一格、长得一模一样"是机械结果。

## 用法

```bash
python3 render.py specs/mem0-code.json out/mem0-code.svg      # 出矢量图
python3 topng.py out/mem0-code.svg                            # 转 PNG 预览（需要 playwright + chromium）
```

批量：

```bash
for f in specs/*.json; do
  python3 render.py "$f" "out/$(basename "${f%.json}").svg"
done
```

## 布局模型

两条泳道带，对应 `../METHODOLOGY-SKELETON.md` §2.2：

```
A 带（上）：A1 INTAKE  A2 DISTILL  A3 ADMIT  A4 INDEX  A5 COMMIT  A6 INTERNALIZE
B 带（下）：B1 CUE  B2 RECALL  B3 EXPAND  B4 APPRAISE  B5 SELECT  B6 DELIVER  B7 GENERATE  B8 LOOP
```

- **泳道 = 阶段，不是顺序。** 节点的 x 由 `stage` 决定、y 由 `row` 决定。
- **真实执行顺序看节点左上角黑圈里的数字**（`seq` 字段）。两者分开表达是刻意的：
  mem0 就是"③先检索 ④再抽取 ⑤再编码 ⑥再去重"，阶段上来回跳，按执行顺序排版反而看不出
  "它的去重发生在 ADMIT 阶段"。
- **灰掉的泳道 = 这个系统没有这一步**，不是"没画"。空格子是分类学结果，见
  `../METHODOLOGY-SKELETON.md` §4。

## spec 字段

```jsonc
{
  "title":    "Mem0 — code view",
  "subtitle": "一句话说明图怎么读",
  "source":   "小字溯源：论文 arXiv 号 / repo @ commit / 复核报告",
  "footer":   "页脚",
  "legend_notes": ["图例区的要点，2-4 条"],

  "nodes": [{
    "id":    "ext",              // 边引用它
    "stage": "A2",               // 决定 x —— 只能用上面 14 个之一
    "row":   3,                  // 决定 y；同一 stage 同一 row 会重叠，注意错开
    "type":  "llm",              // 决定配色，见下
    "seq":   4,                  // 真实执行顺序；不参与排版的节点写 null
    "state": "paper_only",       // 缺省 "both"
    "label": "LLM:Extract — one call, ADD-only",   // 英文，用 SPEC 的 canonical 前缀
    "cite":  "main.py:940  Phase 2\nprompts.py:468 \"sole operation is ADD\""  // \n 换行，多行自动左对齐
  }],

  "edges": [
    {"from": "ext", "to": "emb"},
    {"from": "ext", "to": "resolve", "state": "paper_only", "label": "never reached"}
  ]
}
```

### `type` —— 节点性质决定配色

| type | 含义 | 色 |
|---|---|---|
| `llm` | LLM 调用 | 蓝 |
| `alg` | 检索 / 排序 | 橙 |
| `nlp` | 确定性 NLP（无 LLM） | 绿 |
| `fusion` | 融合 / 门控 | 黄 |
| `sched` | 调度 | 琥珀 |
| `store` | 存储（自动画成圆柱） | 灰 |
| `learn` | 可学习参数 | 紫红 |
| `io` | 输入 / 输出（自动画成胶囊） | 淡紫 |

节点命名前缀沿用 `../METHODOLOGY-FLOW-SPEC.md` §1 的 canonical 词汇表
（`LLM:Extract` / `Retrieval:BM25` / `NLP:HashDedup` / `Store:Vector` …）。
**同义异名是最严重的错误** —— 词汇表里有的一律照抄，没有的按同样格式自拟并回填词汇表。

### `state` —— 论文 vs 代码

| state | 含义 | 表现 |
|---|---|---|
| `both` | 两边一致（缺省） | 常规配色 |
| `paper_only` | 论文写了、代码没实现 | 红虚线 + `P` 角标 |
| `code_only` | 代码有、论文没写 | 青实线 + `C` 角标 |
| `differs` | 两边都有但行为不同 | 琥珀 + `!` 角标 |
| `degraded` | 有但退化 / 默认关 / 环境不满足 | 灰点线 + `~` 角标 |

图例只列**这张图实际用到的** type 和 state，不会堆一堆没用的条目。

## 每个系统出三张

| 文件 | 内容 |
|---|---|
| `<sys>-paper.svg` | 论文描述的机制，节点标 `§x.y / Eq.n / Table n` |
| `<sys>-code.svg` | 代码实际执行的路径，节点标 `file.py:NNN`；论文有代码没有的用 `paper_only` 画成红虚线 |
| `<sys>-diff.svg` | **只画分歧**，每个节点同时写 `paper: … / code: …`，`edges` 一般为空 |

三张图的事实依据一律是 `../<sys>/verification.md` 的复核结论，不是架构文档原文。

## 边怎么走（2026-09-06 起）

布线和排版一样是机械的，不是逐图手调的：

| 边的类型 | 走法 |
|---|---|
| 跨带（A → B） | 每条边在带间空隙里分到**一条自己的横向通道**；带间距按跨带边数量自动撑开（`46 + 20n`） |
| 同带前向 | 同一行直连；直线若会穿过中间节点，自动下沉到行间槽绕开 |
| 同带回跳（如 `A4 → A3`） | 走**两行之间的水平槽**：源节点底部出、平移、目标节点顶部进，直角折线 |
| 同泳道上下相邻 | 竖直折线，入口按需偏移 |
| 多条边进同一节点 | 入口沿节点上边缘散开，不叠成一个箭头 |

这套布线是 2026-09-06 用 graphiti code 视图（8 条跨带边、6 条回跳边）做 A/B 对比后
选定的。此前所有跨带边共用一条 channel，八条边在图上看起来是一根线；回跳边则被画成
横穿整个 A 带底部的长弧。mem0 三张图在新旧两版下节点位置完全一致，只有两处回跳边
由弧线变直角。

## 已知可以再改进的地方

- 还没有 PDF 导出（容器里装 cairosvg 超时了）。`rsvg-convert` 或浏览器打印都能补上；
  本机没有 playwright 时，`Google Chrome --headless --screenshot` 可以直接出 PNG。
- 行间槽的绕行只检测同带节点，暂不检测已有边，极密的图仍可能出现两条边贴着走。

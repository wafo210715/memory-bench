#!/usr/bin/env python3
"""
check.py — flowgen spec 的跨系统一致性校验器

背景
----
2026-09-06：14 个系统的 spec 出现 28 处跨泳道命名漂移。根因不是渲染器画错，
也不是子会话写错，而是**数据模型缺了一个字段**：

    verification.md 的步骤清单有 `prim` 列（这一步做成了什么）
    spec 只有 `label`（用什么算法做的）和 `stage`
    → primitive → 阶段 的绑定无处可查，只能靠写 spec 的人在脑子里走一遍

于是「跨系统一致性靠代码保证」这句话只兑现了一半：
    ✅ 同一 stage → 同一 x 坐标      （render.py 保证）
    ✅ 同一 type  → 同一配色         （render.py 保证）
    ❌ 同一 module → 同一 stage      （没有任何东西保证）

本文件补上后半截。三条规则见 METHODOLOGY-SKELETON.md §2.3。

三层结构
--------
    mechanism  →  label      用什么算法做的
    primitive  →  stage      在记忆生命周期里做成了什么
两者**多对多**：同一机制可服务不同 primitive（Retrieval:Emb 在 B2 是召回、
在 A3 是去重参照）；同一 primitive 可由不同机制实现（去重可以 md5/向量/LLM）。

所以「同一 label 必须落在同一 stage」是错的规则，不要再用。

噪声政策
--------
`prim` 允许写成两可：`"P-FUSE|P-SELECT"`，附 `prim_note` 说明。
两可项不报错，收进 AMBIGUITY.md。**合格标准不是零模糊，是零未标注的模糊。**

用法
----
    python3 check.py                    # 校验 specs/ 全部，打印报告
    python3 check.py --ambiguity        # 同时生成 AMBIGUITY.md
    python3 check.py specs/mem0-code.json   # 只校验指定文件
退出码：0 = 无违规（模糊项不算违规）；1 = 有违规
"""
import json
import sys
import collections
from pathlib import Path

HERE = Path(__file__).parent

# --------------------------------------------------------------- prim → stage
# 真源是 METHODOLOGY-SKELETON.md §2.3。改这里时必须同步改那份文档。
# 2026-09-06 两处补充：A3 增 P-SYMFILTER（写入期准入门控）、B6 增 P-ACTSELECT
# （§1 已登记为新 primitive，但 §2.3 原表漏了它）。
PRIM_STAGE = {
    "A1": {"P-INTAKE"},
    # P-SELFCHECK 2026-09-06 从 A3 移到 A2：按 A2/A3 判据「A2 不看库存，A3 必须看库存」，
    # 自检的输入是上一步 LLM 自己的输出（§1 原话），不查库存 → 属 A2。
    "A2": {"P-REWRITE", "P-EXTRACT", "P-NLPEXTRACT", "P-META", "P-CAPTION", "P-AGGREGATE",
           "P-SELFCHECK"},
    "A3": {"P-DEDUP", "P-CONFLICT", "P-REVISE", "P-UTILITY", "P-EVICT", "P-SYMFILTER"},
    "A4": {"P-EMBED", "P-SPARSE", "P-ANNINDEX", "P-LINK", "P-DATASTORE", "P-KNNDIST"},
    "A5": {"P-PERSIST"},
    "A6": {"P-TRAIN", "P-SIDEINIT", "P-TRANSMUTE"},
    "B1": {"P-QUERYPARSE", "P-EMBED", "P-CAPTION"},
    "B2": {"P-DENSE", "P-SPARSE", "P-SYMFILTER", "P-SUBSTR"},
    "B3": {"P-GRAPHEXPAND", "P-DIFFUSE", "P-LINK"},
    "B4": {"P-RERANK", "P-FUSE", "P-EDGEVERIFY", "P-UTILITY"},
    "B5": {"P-SELECT"},
    "B6": {"P-ASSEMBLE", "P-INJECT", "P-INTERP", "P-KVWINDOW", "P-ACTSELECT"},
    "B7": {"P-GENERATE", "P-FROZENFWD"},
    "B8": {"P-TOOLLOOP"},
}
# P-ORCHESTRATE：编排类，不是记忆原语本身，而是围绕原语的调度（触发条件/分批/切块/
# 标定/请求拆解）。原始 42 条 primitive 没有给它留位置——§1 的种子词表从「操作步骤」
# 抽出，编排步骤只能被贴上最接近的标签。2026-09-06 登记，允许出现在任何阶段。
for _s in PRIM_STAGE:
    PRIM_STAGE[_s] = PRIM_STAGE[_s] | {"P-ORCHESTRATE"}

ALL_PRIMS = set().union(*PRIM_STAGE.values())
STAGES = list(PRIM_STAGE)

# 母节点层（SKELETON §2.4）——用于报告时的粗粒度汇总
PARENT = {
    "A1": "A-I 边界", "A2": "A-II 内容", "A3": "A-II 内容",
    "A4": "A-III 形态", "A5": "A-III 形态", "A6": "A-III 形态",
    "B1": "B-I 线索", "B2": "B-II 候选", "B3": "B-II 候选",
    "B4": "B-III 收敛", "B5": "B-III 收敛",
    "B6": "B-IV 交付", "B7": "B-IV 交付", "B8": "B-V 回环",
}

TYPES = {"llm", "alg", "nlp", "fusion", "sched", "store", "learn", "io"}
STATES = {"both", "paper_only", "code_only", "differs", "degraded"}


class Report:
    def __init__(self):
        self.errors = []      # 硬违规
        self.ambig = []       # 已标注的模糊项
        self.review = []      # 需人看一眼，不算违规
        self.missing_prim = collections.Counter()

    def err(self, where, msg):
        self.errors.append(f"{where}: {msg}")

    def amb(self, rec):
        self.ambig.append(rec)

    def rev(self, msg):
        self.review.append(msg)


def load(paths):
    specs = []
    for p in paths:
        d = json.loads(Path(p).read_text())
        d["_file"] = Path(p).name
        specs.append(d)
    return specs


def parse_prim(node):
    """返回 (候选 prim 列表, 是否两可)。缺字段返回 (None, False)。"""
    raw = node.get("prim")
    if not raw:
        return None, False
    parts = [x.strip() for x in raw.split("|") if x.strip()]
    return parts, len(parts) > 1


def check(specs, rep):
    # ---- 每份 spec 的结构自检 -------------------------------------------
    for d in specs:
        f, view = d["_file"], d.get("view", "?")
        ids, seen_cell = set(), {}
        for n in d["nodes"]:
            nid = n.get("id", "?")
            where = f"{f}:{nid}"
            if nid in ids:
                rep.err(where, "重复的节点 id")
            ids.add(nid)
            if n["stage"] not in PRIM_STAGE:
                rep.err(where, f"非法 stage {n['stage']!r}")
                continue
            if n.get("type", "alg") not in TYPES:
                rep.err(where, f"非法 type {n.get('type')!r}")
            if n.get("state", "both") not in STATES:
                rep.err(where, f"非法 state {n.get('state')!r}")
            cell = (n["stage"], n.get("row", 0))
            if cell in seen_cell:
                rep.err(where, f"(stage,row)={cell} 与 {seen_cell[cell]} 重叠")
            seen_cell[cell] = nid

            # ---- R1：prim → stage --------------------------------------
            prims, is_amb = parse_prim(n)
            if prims is None:
                # diff 视图豁免：它的节点描述的是「分歧」而不是「步骤」，不对应任何
                # primitive；只校验它落在合法阶段（mem0-diff 已批准样板先例）。
                if view != "diff":
                    rep.missing_prim[f"{d['system']}-{view}"] += 1
                continue
            allowed = PRIM_STAGE[n["stage"]]
            for p in prims:
                if p not in ALL_PRIMS:
                    rep.err(where, f"未登记的 primitive {p!r}")
            # 单一 prim：必须落在本阶段。
            # 两可 prim：只要**有一个**候选合法即通过（噪声政策 MODEL.md §4）——
            # 候选跨阶段恰恰是「这个步骤同时具备两个阶段的性质」，是要记录的信号，
            # 不是要消灭的错误。
            legal = [p for p in prims if p in allowed]
            if not legal:
                p0 = prims[0]
                ok = [s for s in STAGES if p0 in PRIM_STAGE[s]]
                rep.err(where,
                        f"R1 违规：{'/'.join(prims)} 都不允许出现在 {n['stage']}"
                        f"，{p0} 应在 {'/'.join(ok)}（label: {n['label'][:44]}）")
            if is_amb:
                rep.amb({
                    "system": d["system"], "view": view, "id": nid,
                    "stage": n["stage"], "parent": PARENT[n["stage"]],
                    "label": n["label"], "prims": prims,
                    "note": n.get("prim_note", ""),
                    "cross_stage": len({s for p in prims for s in STAGES
                                        if p in PRIM_STAGE[s]}) > 1,
                })

        for e in d.get("edges", []):
            if e["from"] not in ids or e["to"] not in ids:
                rep.err(f, f"悬空边 {e['from']} → {e['to']}")

    # ---- R3：(label, stage) 必须推出唯一 prim ---------------------------
    # diff 视图豁免（mem0-diff 已批准样板用纯描述性标签，是既定先例）
    cell_prims = collections.defaultdict(lambda: collections.defaultdict(set))
    label_prims = collections.defaultdict(set)
    label_stages = collections.defaultdict(set)
    for d in specs:
        if d.get("view") == "diff":
            continue
        for n in d["nodes"]:
            prims, _ = parse_prim(n)
            if prims is None or n["stage"] not in PRIM_STAGE:
                continue
            key = n["label"].split("—")[0].split("--")[0].strip()
            cell_prims[key][n["stage"]].add("|".join(sorted(prims)))
            label_prims[key] |= set(prims)
            label_stages[key].add(n["stage"])

    for lab, per_stage in sorted(cell_prims.items()):
        for st, pset in sorted(per_stage.items()):
            if len(pset) > 1:
                rep.err(f"{lab} @{st}",
                        f"R3 违规：同一 (label, stage) 出现多个 prim {sorted(pset)}")

    # ---- R2：label → mechanism 一对一（软报告，供人裁决）----------------
    for lab in sorted(label_stages):
        if len(label_stages[lab]) > 1:
            parents = {PARENT[s] for s in label_stages[lab]}
            tag = "同一母节点内" if len(parents) == 1 else "跨母节点"
            rep.rev(f"{lab:30s} 落在 {sorted(label_stages[lab])} "
                    f"（{tag}）prim={sorted(label_prims[lab])}")


def emit(rep, specs, write_ambiguity=False):
    n_nodes = sum(len(d["nodes"]) for d in specs)
    print(f"校验 {len(specs)} 份 spec / {n_nodes} 个节点\n")

    if rep.missing_prim:
        tot = sum(rep.missing_prim.values())
        print(f"⚠ 尚未回填 prim 的节点：{tot} 个")
        for k, v in sorted(rep.missing_prim.items()):
            print(f"    {k:24s} {v}")
        print()

    if rep.errors:
        print(f"✗ 违规 {len(rep.errors)} 条")
        for e in rep.errors:
            print(f"    {e}")
        print()
    else:
        print("✓ 无违规\n")

    if rep.review:
        print(f"· 同一 label 跨泳道 {len(rep.review)} 条（需人裁决是否为合法多义）")
        for r in rep.review:
            print(f"    {r}")
        print()

    if rep.ambig:
        cross = sum(1 for a in rep.ambig if a["cross_stage"])
        print(f"· 已标注的模糊项 {len(rep.ambig)} 个（其中跨阶段 {cross} 个）")

    if write_ambiguity and rep.ambig:
        out = HERE / "AMBIGUITY.md"
        lines = [
            "# 已标注的模糊项",
            "",
            "> 由 `flowgen/check.py --ambiguity` 生成。",
            "",
            "**这不是免责声明，是发现清单。** 分类学上卡住的地方，往往正是这篇论文",
            "做了不常规的事、或实现与论文意图分岔的地方。默认把每一条当作线索来读。",
            "",
            "两个现成例子：GraphMemix 的节点效用打分卡在 B4/B5 之间，是因为 PCSF 把",
            "「打分」和「选集合」融进了同一个优化目标 —— 而那就是它论文的贡献；",
            "Memory Decoder 的 `P-DENSE` 落在 A4 而非 B2，当时像归类异常，结果它直接",
            "逼出了整个顶层二分的命名（SKELETON §2.1）。",
            "",
            "| 系统 | 视图 | 阶段 | 母节点 | 节点 | 候选 prim | 跨阶段 | 说明 |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for a in sorted(rep.ambig, key=lambda x: (x["system"], x["view"], x["stage"])):
            lines.append(
                f"| {a['system']} | {a['view']} | {a['stage']} | {a['parent']} | "
                f"{a['label'][:44]} | {' \\| '.join(a['prims'])} | "
                f"{'是' if a['cross_stage'] else '否'} | {a['note']} |")
        out.write_text("\n".join(lines) + "\n")
        print(f"\n→ 已写出 {out}")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    paths = args or sorted((HERE / "specs").glob("*.json"))
    if not paths:
        sys.exit("找不到 spec 文件")
    specs = load(paths)
    rep = Report()
    check(specs, rep)
    emit(rep, specs, write_ambiguity="--ambiguity" in sys.argv)
    sys.exit(1 if rep.errors else 0)


if __name__ == "__main__":
    main()

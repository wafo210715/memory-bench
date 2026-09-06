#!/usr/bin/env python3
"""
matrix.py — 交叉检验：spec 实际填的泳道 vs METHODOLOGY-SKELETON.md §3 覆盖矩阵

矩阵是 2026-09-05 复核阶段由 14 个 agent 独立产出的步骤序列汇总而来；
spec 是 2026-09-06 另一批 agent 从同一批 verification.md 画出来的。
两者独立，因此对账不一致就说明其中一边错了。

两条已知约定（不算不一致）：
  1. code 视图里 state=paper_only 的节点：图故意画出「论文有、代码没有」的缺口，
     矩阵那一格记 ✗ 是对的，图里有节点也是对的。
  2. paper 视图 B1 的 IO:Query 锚点：论文侧常常没有查询处理，但查询得有入口。
     mem0 已批准样板立的先例。
"""
import json, pathlib, re, sys

HERE = pathlib.Path(__file__).parent
SKEL = HERE.parent / "METHODOLOGY-SKELETON.md"
STAGES = ["A1","A2","A3","A4","A5","A6","B1","B2","B3","B4","B5","B6","B7","B8"]
HAS = {"✓", "◐", "~"}
NAME = {"AtomMem":"atommem","Mem0":"mem0","Zep/Graphiti":"graphiti","MemOS":"memos",
        "A-MEM":"amem","Mandol":"mandol","MRAgent":"mragent","GraphMemix":"graphmemix",
        "PlugMem":"plugmem","MemHarness":"memharness","Letta/MemGPT":"letta",
        "TransMem":"transmem","LiveMem":"livemem","Memory Decoder":"memorydecoder"}


def parse_matrix():
    sec = SKEL.read_text().split("## 3. 覆盖矩阵")[1].split("## 4.")[0]
    out = {}
    for line in sec.splitlines():
        if not line.startswith("| **"):
            continue
        parts = [c.strip() for c in line.replace(r"\|", "\x00").strip("|").split("|")]
        sysn = NAME.get(parts[0].strip("* "))
        if not sysn:
            continue
        cells = []
        for c in parts[1:15]:
            c = re.sub(r"[\*` ]", "", c)
            a, _, b = c.partition("\x00")
            cells.append((a, b or a))
        out[sysn] = cells
    return out


def main():
    matrix, mism, waived = parse_matrix(), [], 0
    for sysn, cells in sorted(matrix.items()):
        for view, idx in (("paper", 0), ("code", 1)):
            d = json.loads((HERE / "specs" / f"{sysn}-{view}.json").read_text())
            occ = {n["stage"] for n in d["nodes"]}
            # 约定 1：code 视图里 paper_only 的节点不代表「代码有这一步」
            real = {n["stage"] for n in d["nodes"]
                    if not (view == "code" and n.get("state") == "paper_only")}
            for st, cell in zip(STAGES, cells):
                claim, here = cell[idx] in HAS, st in real
                if claim == here:
                    continue
                # 约定 2：paper 视图 B1 的 IO:Query 锚点
                if (view == "paper" and st == "B1" and here
                        and all(n["label"].startswith("IO:Query")
                                or n.get("state") == "degraded"
                                for n in d["nodes"] if n["stage"] == "B1")):
                    waived += 1
                    continue
                if st in occ and not here:
                    waived += 1
                    continue
                mism.append(f"{sysn:14s} {view:5s} {st}  矩阵={cell[idx] or '?'} "
                            f" 图里={'有' if here else '空'}")
    n = len(matrix) * 28
    print(f"{len(matrix)} 系统 × 14 阶段 × 2 侧 = {n} 格")
    print(f"吻合 {n - len(mism) - waived} · 按约定豁免 {waived} · 不一致 {len(mism)}\n")
    for x in mism:
        print("  " + x)
    sys.exit(1 if mism else 0)


if __name__ == "__main__":
    main()

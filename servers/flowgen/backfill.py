#!/usr/bin/env python3
"""
backfill.py — 给 spec 回填 `prim` 字段，并应用 2026-09-06 的归一改名/移位

一次性脚本，跑完即完成使命，保留在仓库里作为归一过程的可复核记录。

做三件事：
  1. 应用 MODEL.md §7 Type II（改 label）与 Type III（移 stage）
  2. 按 (module, stage) 推导 `prim`，推不出来的留空由人补
  3. 打印残留清单

用法：
    python3 backfill.py --dry     # 只报告，不写
    python3 backfill.py           # 写回 specs/
"""
import json
import re
import sys
import collections
from pathlib import Path

SPECS = Path(__file__).parent / "specs"

# ---------------------------------------------------- Type II：同名异物，改 label
# (系统, 视图, 旧 module, 所在 stage) → 新 module；系统/视图为 None 表示不限
RENAME = [
    (None, None, "Fusion:Add",       "B6", "Fusion:Inject"),
    ("letta", None, "Store:Plaintext", "B6", "IO:Context"),
    ("letta", None, "Store:Database",  "B6", "IO:Context"),
    ("livemem", None, "Sched:Evict",   "B6", "Sched:KVWindow"),
    ("memos", None, "Store:KVCache",   "B6", "IO:Activation"),
    ("plugmem", None, "IO:RetrievedMemory", "B6", "IO:Structured"),
    (None, None, "IO:Context",       "A1", "IO:Prompt"),
    (None, None, "IO:Assemble",      "B6", "IO:Context"),
    ("memorydecoder", None, "Learn:Decoder", "B6", "Learn:Backbone"),
    # P-EMBED 与 P-DENSE 彻底分开：A4/B1 上的 Retrieval:Emb 其实是「算向量」
    (None, None, "Retrieval:Emb",    "A4", "NLP:Embed"),
    (None, None, "Retrieval:Emb",    "B1", "NLP:Embed"),
    ("plugmem", None, "Retrieval:Emb", "A2", "NLP:Segment"),
    ("mem0", None, "NLP:EmbDedup",   "A4", "NLP:CooccurLink"),
    ("graphiti", None, "Sched:Lifecycle", "A5", "Sched:Rebuild"),
    ("graphiti", None, "LLM:Judge",  "A3", "LLM:Resolve"),
    ("mragent", None, "LLM:Extract", "B1", "LLM:Query"),
    ("atommem", None, "LLM:Route",   "A2", "LLM:Tag"),
    ("mragent", None, "LLM:Route",   "B8", "LLM:Select"),
    ("memos", None, "NLP:TextDedup", "B5", "Fusion:Dedup"),
]

# ---------------------------------------------------- Type III：阶段放错，移 stage
MOVE = [
    ("memos", "Store:Vector",     "A4", "A5"),
    ("memos", "Retrieval:Rerank", "B5", "B4"),
    ("memos", "NLP:SchemaLink",   "A2", "A4"),
    ("amem",  "Sched:Lifecycle",  "A4", "A3"),
    ("graphmemix", "Fusion:Add",  "B5", "B4"),   # 用户 2026-09-06 判定
]

# ---------------------------------------------------- prim 推导
# 只有一个候选 prim 的 stage，直接确定
SOLE = {"A1": "P-INTAKE", "A5": "P-PERSIST", "B5": "P-SELECT", "B8": "P-TOOLLOOP"}

# (stage, module) 精确匹配优先
EXACT = {
    ("A2", "LLM:Reflect"): "P-SELFCHECK",
    ("A2", "LLM:Caption"): "P-CAPTION",
    ("A2", "LLM:Rewrite"): "P-REWRITE",
    ("A2", "NLP:Segment"): "P-NLPEXTRACT",
    ("A3", "Retrieval:SymFilter"): "P-SYMFILTER",
    ("A3", "NLP:UtilityScore"): "P-UTILITY",
    ("A3", "Sched:Evict"): "P-EVICT",
    ("A3", "LLM:Evolve"): "P-REVISE",
    ("A3", "NLP:Revise"): "P-REVISE",
    ("A3", "Sched:Lifecycle"): "P-REVISE",
    ("A4", "NLP:Embed"): "P-EMBED",
    ("A4", "Store:ANNIndex"): "P-ANNINDEX",
    ("A4", "Store:Datastore"): "P-DATASTORE",
    ("A4", "Retrieval:kNN"): "P-KNNDIST",
    ("A4", "Retrieval:kNNDist"): "P-KNNDIST",
    ("A6", "Learn:SideInit"): "P-SIDEINIT",
    ("B1", "NLP:Embed"): "P-EMBED",
    ("B1", "LLM:Caption"): "P-CAPTION",
    ("B2", "Retrieval:Substring"): "P-SUBSTR",
    ("B4", "LLM:VerifyEdge"): "P-EDGEVERIFY",
    ("B4", "NLP:UtilityScore"): "P-UTILITY",
    ("B6", "Fusion:Interp"): "P-INTERP",
    ("B6", "IO:Activation"): "P-KVWINDOW",
    ("B6", "Sched:KVWindow"): "P-KVWINDOW",
    ("B6", "Sched:MemSelect"): "P-ACTSELECT",
    ("A3", "LLM:SelfEdit"): "P-REVISE",
    ("A3", "Sched:QueueManager"): "P-EVICT",
    ("B6", "Learn:Backbone"): "P-INTERP",
    ("A2", "IO:MemCube"): "P-AGGREGATE",
    ("A4", "Link"): "P-LINK",
    ("B7", "LLM"): "P-GENERATE",
    ("A2", "LLM:NER"): "P-EXTRACT",
    ("A2", "LLM:RelGen"): "P-EXTRACT",
    ("B3", "Diffusion:EdgeWeight"): "P-DIFFUSE",
}

# 两可项（噪声政策：标注而不强判）→ (prim 候选, 说明)
AMBIG = {
    ("B2", "Retrieval:Unspecified"):
        ("P-DENSE|P-SPARSE", "论文只写 recall_storage.search()，未说明检索机制"),
    ("A3", "Retrieval:Recent"):
        ("P-DEDUP|P-ORCHESTRATE", "读近期历史为抽取提供上下文：它确实查了库存（故在 A3），"
                                  "但服务的是 A2 抽取而非准入判定"),
    ("B2", "Retrieval:EntityBoost"):
        ("P-SYMFILTER|P-FUSE", "实质是对召回得分的加成，既像召回通道又像融合"),
}

# 编排类：不是记忆原语本身，而是围绕原语的调度（触发条件、分批、切块、
# 标定、请求拆解）。原始 42 条 primitive 没有给它们留位置 —— 这本身是一条发现：
# §1 的种子词表从「操作步骤」抽出，编排步骤只能被贴上最接近的标签。
ORCHESTRATION = {"Sched:Batch", "Sched:Chunk", "Sched:Calibrate", "Sched:RequestEnd",
                 "Sched:Incremental", "Sched:TaskQueue", "Sched:PathResolver"}

# 无 canonical 前缀的节点补前缀（paper/code 视图必须有前缀；diff 视图豁免）。
# mem0 作为最早的样板，当时词表还没定死，留下一批纯描述性标签。
# 格式：(系统或 None, stage, 匹配正则, 新 label 前缀)
LABEL_FIX = [
    (None, "A3", r"^Recall last",              "Retrieval:Recent"),
    (None, "A3", r"^Dense probe",              "Retrieval:Emb"),
    ("graphiti", "A3", r"^Resolve contradictions", "NLP:Conflict"),
    ("graphiti", "A2", r"^extract_summary prompt",  "LLM:Summarize"),
    (None, "B1", r"^Query$",                   "IO:Query"),
    (None, "B6", r"^Structured top-k list",     "IO:Structured"),
    (None, "B6", r"^Retrieved text blocks",     "IO:Context"),
    (None, "B6", r"^χ constructor",              "IO:Context"),
    (None, "B6", r"^search_results_to_context",  "IO:Context"),
    ("memos", "B6", r'^"Prefer chat_time"',      "IO:Structured"),
    ("memos", "A4", r"^Contextual fingerprint",  "NLP:Embed"),
    ("atommem", "B3", r"^Multichannel edge weights", "Diffusion:EdgeWeight"),
    ("plugmem", "A4", r"^Link —",                "NLP:SchemaLink"),
    ("plugmem", "B7", r"^LLM —",                 "LLM:Answer"),
    ("mem0", "A3", r"node match by embedding",   "Retrieval:Emb"),
    ("mem0", "A4", r"build labelled directed graph", "NLP:SchemaLink"),
    ("mem0", "B2", r"^Semantic retrieval",       "Retrieval:Emb"),
    ("mem0", "B1", r"encode query entities",     "NLP:Embed"),
    ("mem0", "B2", r"semantic triplet search",   "Retrieval:Emb"),
    ("mem0", "B3", r"entity-centric subgraph",   "Retrieval:Graph"),
]

# (stage, 前缀或正则) 兜底
BY_STAGE = {
    "A2": [(r"^NLP:(NER|SpeakerTag|Extract)", "P-NLPEXTRACT"),
           (r"^LLM:Extract", "P-EXTRACT"),
           (r"^(LLM:Summarize|NLP:Cluster|LLM:Aggregate)", "P-AGGREGATE"),
           (r"^(LLM:Tag|NLP:Tag|LLM:TimeExtract|LLM:Judge|NLP:UsageUpdate)", "P-META")],
    "A3": [(r"Dedup", "P-DEDUP"),
           (r"^(LLM:Resolve|NLP:Conflict)", "P-CONFLICT"),
           (r"^Retrieval:", "P-DEDUP")],          # 写入期查库存的检索，服务于去重
    "A4": [(r"^(Retrieval:BM25|Retrieval:SPLADE)", "P-SPARSE"),
           (r"^(NLP:SchemaLink|NLP:MutualKNN|LLM:Link|NLP:LinkWrite|NLP:CooccurLink|Fusion:Union)",
            "P-LINK"),
           (r"^LLM:Extract", "P-EXTRACT")],
    "A6": [(r"^Convert:", "P-TRANSMUTE"), (r"^Learn:", "P-TRAIN")],
    "B1": [(r"^(LLM:Query|LLM:Route|LLM:SelfEdit|Retrieval:CueMatch|IO:)", "P-QUERYPARSE")],
    "B2": [(r"^(Retrieval:Emb|Retrieval:Hybrid|Retrieval:kNN)", "P-DENSE"),
           (r"^(Retrieval:BM25|Retrieval:FTS|Retrieval:SPLADE)", "P-SPARSE"),
           (r"^(Retrieval:SymFilter|Retrieval:CueMatch|Retrieval:Timeline|Retrieval:RuleFilter)",
            "P-SYMFILTER")],
    "B3": [(r"^Retrieval:Graph", "P-GRAPHEXPAND"),
           (r"^Diffusion:", "P-DIFFUSE"),
           (r"^LLM:Link", "P-LINK")],
    "B4": [(r"^(Retrieval:Rerank|LLM:Rerank|Fusion:CrossEncoder)", "P-RERANK"),
           (r"^Fusion:", "P-FUSE")],
    "B6": [(r"^(IO:Context|IO:Structured|LLM:MemReader|LLM:Reconstruct)", "P-ASSEMBLE"),
           (r"^(Fusion:Inject|Fusion:Gate|Learn:Recurrent|Learn:TransMem)", "P-INJECT")],
    "B7": [(r"^(LLM:Answer|LLM:Act|LLM:Generate)", "P-GENERATE"),
           (r"^(Learn:|IO:TokenStream)", "P-FROZENFWD")],
}


def module_of(label):
    # 先剥掉系统自己的前缀，如 "Mem0g · LLM:NER"
    label = re.sub(r"^[A-Za-z0-9]+ · ", "", label)
    m = re.match(r"^([A-Za-z]+:[A-Za-z0-9→_\-]+)", label)
    return m.group(1) if m else None


def derive(stage, label):
    if stage in SOLE:
        return SOLE[stage]
    mod = module_of(label)
    if mod is None:
        return None
    if mod == "NLP:Embed":
        return "P-EMBED"
    if mod in ORCHESTRATION:
        return "P-ORCHESTRATE"
    if (stage, mod) in AMBIG:
        return AMBIG[(stage, mod)][0]
    if (stage, mod) in EXACT:
        return EXACT[(stage, mod)]
    for pat, prim in BY_STAGE.get(stage, []):
        if re.search(pat, mod):
            return prim
    return None


def main():
    dry = "--dry" in sys.argv
    renamed = moved = filled = 0
    residual = collections.defaultdict(list)

    for f in sorted(SPECS.glob("*.json")):
        d = json.loads(f.read_text())
        sysname, view = d["system"], d.get("view", "?")
        for n in d["nodes"]:
            # 无 canonical 前缀的节点补前缀
            if view != "diff" and module_of(n["label"]) is None:
                for s, st, pat, pre in LABEL_FIX:
                    if s in (None, sysname) and n["stage"] == st and re.search(pat, n["label"]):
                        n["label"] = f"{pre} — {n['label']}"
                        renamed += 1
                        break
            # 无前缀的 "Embed ..." 补成 canonical（P-EMBED 与 P-DENSE 必须分开）
            if view != "diff" and re.match(r"^(Batch e|E)mbed\b", n["label"]):
                n["label"] = re.sub(r"^(Batch embed|Embed)", "NLP:Embed —", n["label"], count=1)
                n["label"] = n["label"].replace("NLP:Embed — —", "NLP:Embed —").rstrip(" —")
                renamed += 1
            mod = module_of(n["label"])
            # Type II 改名
            for s, v, old, st, new in RENAME:
                if (s in (None, sysname) and v in (None, view)
                        and mod == old and n["stage"] == st):
                    n["label"] = n["label"].replace(old, new, 1)
                    mod = new
                    renamed += 1
                    break
            # Type III 移位
            for s, m, frm, to in MOVE:
                if s == sysname and mod == m and n["stage"] == frm:
                    n["stage"] = to
                    moved += 1
                    break
            # prim 推导。diff 视图豁免：它的节点描述的是「分歧」而不是「步骤」，
            # 不对应任何 primitive；只校验它落在合法阶段（mem0-diff 已批准样板先例）。
            if view == "diff":
                continue
            p = derive(n["stage"], n["label"])
            if p:
                n["prim"] = p
                key = (n["stage"], module_of(n["label"]))
                if key in AMBIG:
                    n["prim_note"] = AMBIG[key][1]
                filled += 1
            else:
                residual[f"{sysname}-{view}"].append(f"{n['stage']} {n['label'][:56]}")
        if not dry:
            f.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n")

    total = sum(len(v) for v in residual.values())
    print(f"改名 {renamed} 处 · 移位 {moved} 处 · 回填 prim {filled} 个 · 残留 {total} 个"
          + ("   [dry-run，未写盘]" if dry else ""))
    if residual:
        print("\n=== 推不出 prim 的节点（按系统-视图）===")
        for k in sorted(residual):
            print(f"\n{k}  ({len(residual[k])})")
            for line in residual[k]:
                print(f"    {line}")


if __name__ == "__main__":
    main()

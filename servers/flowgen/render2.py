#!/usr/bin/env python3
"""
flowgen — renders memory-system methodology flowcharts as SVG.

One visual language, applied mechanically to every system, so that the same
canonical module always looks the same across all diagrams.

Layout model
------------
Two bands, matching servers/METHODOLOGY-SKELETON.md:
  A band (top)    : A1 INTAKE  A2 DISTILL  A3 ADMIT  A4 INDEX  A5 COMMIT  A6 INTERNALIZE
  B band (bottom) : B1 CUE  B2 RECALL  B3 EXPAND  B4 APPRAISE  B5 SELECT  B6 DELIVER
                    B7 GENERATE  B8 LOOP

Each stage is a fixed-width vertical lane.  A node declares (stage, row); x comes
from the lane, y from the row.  Because lane x is identical in every diagram, the
same module lands in the same horizontal position in all 42 figures.

Spec format: see specs/*.json
"""
import json
import math
import sys
from pathlib import Path

# ---------------------------------------------------------------- geometry ---
LANE_W = 196
LANE_GAP = 16
NODE_W = 172
ROW_GAP = 22
BAND_GAP = 74
PAD_X = 24
BAND_HEAD = 34          # height of the stage-name header strip
TITLE_H = 100
LEGEND_W = 232
CHAR_W_LABEL = 6.55     # px per char at 11.5px semibold
CHAR_W_CITE = 5.05      # px per char at 9px mono
LINE_H_LABEL = 15
LINE_H_CITE = 12
NODE_PAD_Y = 11

A_STAGES = [
    ("A1", "INTAKE"), ("A2", "DISTILL"), ("A3", "ADMIT"),
    ("A4", "INDEX"), ("A5", "COMMIT"), ("A6", "INTERNALIZE"),
]
B_STAGES = [
    ("B1", "CUE"), ("B2", "RECALL"), ("B3", "EXPAND"), ("B4", "APPRAISE"),
    ("B5", "SELECT"), ("B6", "DELIVER"), ("B7", "GENERATE"), ("B8", "LOOP"),
]
STAGE_ORDER = {s: i for i, (s, _) in enumerate(A_STAGES + B_STAGES)}
BAND_OF = {s: ("A" if s.startswith("A") else "B") for s, _ in A_STAGES + B_STAGES}

# ------------------------------------------------------------------ palette ---
# Node types.  Prefix in the label decides the type, so the type is never a
# per-diagram judgement call.
TYPES = {
    "llm":     dict(fill="#dbeafe", stroke="#2563eb", name="LLM call"),
    "alg":     dict(fill="#ffedd5", stroke="#ea580c", name="Retrieval / ranking"),
    "nlp":     dict(fill="#ecfccb", stroke="#4d7c0f", name="Deterministic NLP"),
    "fusion":  dict(fill="#fef9c3", stroke="#ca8a04", name="Fusion / gating"),
    "sched":   dict(fill="#fef3c7", stroke="#b45309", name="Scheduling"),
    "store":   dict(fill="#e5e7eb", stroke="#6b7280", name="Storage"),
    "learn":   dict(fill="#f5d0fe", stroke="#a21caf", name="Learned parameters"),
    "io":      dict(fill="#f3e8ff", stroke="#9333ea", name="Input / output"),
}
# Divergence states — used by the diff view, and by the code view for dead paths.
STATES = {
    "both":       dict(dash="",      opacity="1",   mark=""),
    "paper_only": dict(dash="6 4",   opacity="1",   mark="P"),   # claimed, not implemented
    "code_only":  dict(dash="",      opacity="1",   mark="C"),   # implemented, not written up
    "differs":    dict(dash="",      opacity="1",   mark="!"),   # both, but behave differently
    "degraded":   dict(dash="3 3",   opacity="1",   mark="~"),   # present but weakened
}
STATE_ACCENT = {
    "paper_only": "#dc2626",
    "code_only":  "#0f766e",
    "differs":    "#b45309",
    "degraded":   "#78716c",
    "both":       None,
}
STATE_LABEL = {
    "paper_only": "Paper only — not in code",
    "code_only":  "Code only — not in paper",
    "differs":    "Both, but behave differently",
    "degraded":   "Present but degraded",
    "both":       "Agrees on both sides",
}


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def wrap(text, max_px, char_w):
    """Greedy wrap that keeps CJK-safe by measuring wide chars as 2 units."""
    def w(ch):
        return char_w * (1.85 if ord(ch) > 0x2E80 else 1.0)
    words, cur, lines, cur_w = text.split(" "), [], [], 0.0
    for word in words:
        ww = sum(w(c) for c in word) + (char_w if cur else 0)
        if cur and cur_w + ww > max_px:
            lines.append(" ".join(cur))
            cur, cur_w = [word], sum(w(c) for c in word)
        else:
            cur.append(word)
            cur_w += ww
    if cur:
        lines.append(" ".join(cur))
    # hard-split any line still too wide (long CJK runs have no spaces)
    out = []
    for ln in lines:
        while True:
            acc, cut = 0.0, len(ln)
            for i, ch in enumerate(ln):
                acc += w(ch)
                if acc > max_px:
                    cut = max(1, i)
                    break
            if cut >= len(ln):
                out.append(ln)
                break
            out.append(ln[:cut])
            ln = ln[cut:]
    return out or [""]


class Node:
    def __init__(self, d):
        self.id = d["id"]
        self.stage = d["stage"]
        self.row = d.get("row", 0)
        self.type = d.get("type", "alg")
        self.label = d["label"]
        self.cite = d.get("cite", "")
        self.state = d.get("state", "both")
        self.seq = d.get("seq")          # true execution order, independent of lane order
        self.shape = d.get("shape", "cyl" if self.type == "store" else
                           ("pill" if self.type == "io" else "rect"))
        self.note = d.get("note", "")
        self.label_lines = wrap(self.label, NODE_W - 20, CHAR_W_LABEL)
        self.cite_lines = []
        for seg in (self.cite.split("\n") if self.cite else []):
            self.cite_lines.extend(wrap(seg, NODE_W - 20, CHAR_W_CITE))
        self.h = (NODE_PAD_Y * 2
                  + len(self.label_lines) * LINE_H_LABEL
                  + (len(self.cite_lines) * LINE_H_CITE + 4 if self.cite_lines else 0))
        if self.shape == "cyl":
            self.h += 12
        self.x = self.y = 0.0

    @property
    def cx(self): return self.x + NODE_W / 2
    @property
    def cy(self): return self.y + self.h / 2


def lane_x(stage):
    band = BAND_OF[stage]
    idx = [s for s, _ in (A_STAGES if band == "A" else B_STAGES)].index(stage)
    return PAD_X + idx * (LANE_W + LANE_GAP)


def build(spec):
    nodes = [Node(n) for n in spec["nodes"]]
    by_id = {n.id: n for n in nodes}

    # ---- vertical placement, per band, per row -----------------------------
    layout = {}
    for band in ("A", "B"):
        bn = [n for n in nodes if BAND_OF[n.stage] == band]
        if not bn:
            layout[band] = (0.0, [])
            continue
        rows = sorted({n.row for n in bn})
        heights = {r: max(n.h for n in bn if n.row == r) for r in rows}
        y, ys = 0.0, {}
        for r in rows:
            ys[r] = y
            y += heights[r] + ROW_GAP
        layout[band] = (y - ROW_GAP, ys)

    a_h = layout["A"][0]
    b_h = layout["B"][0]
    a_top = TITLE_H + BAND_HEAD
    b_top = a_top + a_h + BAND_GAP + BAND_HEAD

    for n in nodes:
        band = BAND_OF[n.stage]
        top = a_top if band == "A" else b_top
        n.x = lane_x(n.stage) + (LANE_W - NODE_W) / 2
        n.y = top + layout[band][1][n.row]

    n_a_lanes, n_b_lanes = len(A_STAGES), len(B_STAGES)
    width = PAD_X * 2 + max(n_a_lanes, n_b_lanes) * (LANE_W + LANE_GAP) - LANE_GAP + LEGEND_W + 20
    height = b_top + b_h + 46
    return nodes, by_id, width, height, a_top, b_top, a_h, b_h


# -------------------------------------------------------------------- edges ---
# render2 routing.  Same visual language as render.py; the only difference is
# that every edge gets its own lane so that dense diagrams stay readable:
#   * cross-band edges each get a private horizontal channel in the band gap
#   * backward edges travel in the gutter between two rows instead of one
#     shared arc under the whole band
#   * forward edges detour into a gutter when a node sits in the way
#   * several edges entering the same node fan out across its top edge
CHANNEL = [0.0]
ROUTER = [None]


class Router:
    def __init__(self, spec, nodes, a_top, b_top, a_h, b_h):
        self.geo = {n.id: n for n in nodes}
        self.nodes = nodes
        self.a_bottom = a_top + a_h
        self.b_top = b_top
        edges = spec.get("edges", [])

        def band(nid):
            return BAND_OF[self.geo[nid].stage]

        cross, back = [], []
        for e in edges:
            if e["from"] not in self.geo or e["to"] not in self.geo:
                continue
            if band(e["from"]) != band(e["to"]):
                cross.append((e["from"], e["to"]))
            elif STAGE_ORDER[self.geo[e["to"]].stage] < STAGE_ORDER[self.geo[e["from"]].stage]:
                back.append((e["from"], e["to"]))

        # one private channel per cross-band edge, spread across the band gap
        gap_lo = self.a_bottom + 22
        gap_hi = self.b_top - BAND_HEAD - 12
        n = max(1, len(cross))
        step = (gap_hi - gap_lo) / n if n > 1 else 0
        self.chan = {k: gap_lo + i * step for i, k in enumerate(cross)}
        self.back_idx = {k: i for i, k in enumerate(back)}

        # fan-out: how many edges arrive at each node from above/below
        self.in_top, self.in_left = {}, {}
        for e in edges:
            if e["from"] not in self.geo or e["to"] not in self.geo:
                continue
            t = e["to"]
            if band(e["from"]) != band(t) or \
               STAGE_ORDER[self.geo[t].stage] <= STAGE_ORDER[self.geo[e["from"]].stage]:
                self.in_top.setdefault(t, []).append(e["from"])
            else:
                self.in_left.setdefault(t, []).append(e["from"])
        # gutter jitter so two edges never share the same horizontal run
        self.gut = {}
        for i, e in enumerate(edges):
            self.gut[(e["from"], e["to"])] = i

    def entry_top(self, a, b):
        """Spread arrivals across b's top edge instead of stacking them at cx."""
        peers = self.in_top.get(b.id, [])
        if len(peers) <= 1:
            return b.cx
        i = peers.index(a.id) if a.id in peers else 0
        span = min(NODE_W - 40, 26 * (len(peers) - 1))
        return b.x + NODE_W / 2 - span / 2 + (span / (len(peers) - 1)) * i

    def blocked(self, a, b, y):
        """Is there a node sitting on the straight run from a to b at height y?"""
        x0, x1 = a.x + NODE_W, b.x
        for n in self.nodes:
            if n is a or n is b:
                continue
            if BAND_OF[n.stage] != BAND_OF[a.stage]:
                continue
            if n.x + NODE_W < x0 + 2 or n.x > x1 - 2:
                continue
            if n.y - 6 < y < n.y + n.h + 6:
                return True
        return False

    def path(self, a, b):
        key = (a.id, b.id)
        same_band = BAND_OF[a.stage] == BAND_OF[b.stage]
        ax, ay = a.x + NODE_W, a.cy
        bx, by = b.x, b.cy

        if not same_band:
            chan = self.chan.get(key, CHANNEL[0])
            ex = self.entry_top(a, b)
            d = (f"M {a.cx} {a.y + a.h} L {a.cx} {chan} L {ex} {chan} L {ex} {b.y}")
            return d, (ex, b.y, 90), ((a.cx + ex) / 2, chan - 6)

        if a.stage == b.stage:                        # same lane, stacked
            ex = self.entry_top(a, b)
            return (f"M {a.cx} {a.y + a.h} L {a.cx} {(a.y + a.h + b.y)/2} "
                    f"L {ex} {(a.y + a.h + b.y)/2} L {ex} {b.y}"), \
                   (ex, b.y, 90), (a.cx, (a.y + a.h + b.y) / 2 - 4)

        if STAGE_ORDER[b.stage] > STAGE_ORDER[a.stage]:      # forward
            if abs(ay - by) < 3 and not self.blocked(a, b, ay):
                return f"M {ax} {ay} L {bx} {by}", (bx, by, 0), ((ax + bx) / 2, ay - 6)
            if abs(ay - by) < 3:
                # a node is in the way: dip into the gutter under this row
                g = max(a.y + a.h, b.y + b.h) + 11 + 7 * (self.gut[key] % 3)
                d = (f"M {ax} {ay} L {ax + 12} {ay} L {ax + 12} {g} "
                     f"L {bx - 12} {g} L {bx - 12} {by} L {bx} {by}")
                return d, (bx, by, 0), ((ax + bx) / 2, g - 5)
            mid = ax + (bx - ax) / 2 + 6 * (self.gut[key] % 3 - 1)
            d = (f"M {ax} {ay} L {mid} {ay} Q {mid+8} {ay} {mid+8} "
                 f"{ay + (8 if by > ay else -8)} L {mid+8} {by - (8 if by > ay else -8)} "
                 f"Q {mid+8} {by} {mid+16} {by} L {bx} {by}")
            return d, (bx, by, 0), (mid + 8, (ay + by) / 2)

        # backward — travel in the gutter between the two rows, not under the band
        i = self.back_idx.get(key, 0)
        ex = self.entry_top(a, b)
        if b.y > a.y + a.h - 2:                        # target sits lower: go down
            g = (a.y + a.h + b.y) / 2 + 4 * (i % 3 - 1)
            d = f"M {a.cx} {a.y + a.h} L {a.cx} {g} L {ex} {g} L {ex} {b.y}"
            return d, (ex, b.y, 90), ((a.cx + ex) / 2, g - 5)
        if b.y + b.h < a.y + 2:                        # target sits higher: go up
            g = (a.y + b.y + b.h) / 2 - 4 * (i % 3 - 1)
            d = f"M {a.cx} {a.y} L {a.cx} {g} L {b.cx} {g} L {b.cx} {b.y + b.h}"
            return d, (b.cx, b.y + b.h, 270), ((a.cx + b.cx) / 2, g - 5)
        lift = max(a.y + a.h, b.y + b.h) + 16 + 9 * i   # overlapping rows: arc under
        return (f"M {a.cx} {a.y + a.h} C {a.cx} {lift} {b.cx} {lift} {b.cx} {b.y + b.h}"), \
               (b.cx, b.y + b.h, 270), ((a.cx + b.cx) / 2, lift - 4)


def edge_path(a, b, kind):
    d, head, _lab = ROUTER[0].path(a, b)
    return d, head


def arrow(px, py, rot, color):
    return (f'<g transform="translate({px:.1f},{py:.1f}) rotate({rot})">'
            f'<path d="M 0 0 L -8 -3.6 L -8 3.6 Z" fill="{color}"/></g>')


# ------------------------------------------------------------------- render ---
def render(spec):
    # widen the band gap so every cross-band edge gets its own channel
    global BAND_GAP
    _stage = {n["id"]: n["stage"] for n in spec["nodes"]}
    _cross = sum(1 for e in spec.get("edges", [])
                 if e["from"] in _stage and e["to"] in _stage
                 and BAND_OF[_stage[e["from"]]] != BAND_OF[_stage[e["to"]]])
    BAND_GAP = max(74, 46 + 20 * _cross)
    nodes, by_id, W, H, a_top, b_top, a_h, b_h = build(spec)
    used_states = {n.state for n in nodes} | {e.get("state", "both") for e in spec.get("edges", [])}
    used_types = {n.type for n in nodes}
    out = []
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
        f'viewBox="0 0 {W:.0f} {H:.0f}" font-family="Inter, -apple-system, '
        f'&quot;Helvetica Neue&quot;, &quot;PingFang SC&quot;, &quot;Noto Sans SC&quot;, sans-serif">')
    out.append('<rect width="100%" height="100%" fill="#ffffff"/>')

    # ---- title -------------------------------------------------------------
    out.append(f'<text x="{PAD_X}" y="30" font-size="19" font-weight="700" '
               f'fill="#111827">{esc(spec["title"])}</text>')
    if spec.get("subtitle"):
        out.append(f'<text x="{PAD_X}" y="50" font-size="11.5" fill="#4b5563">'
                   f'{esc(spec["subtitle"])}</text>')
    if spec.get("source"):
        out.append(f'<text x="{PAD_X}" y="66" font-size="9.5" fill="#9ca3af" '
                   f'font-family="ui-monospace, SFMono-Regular, Menlo, monospace">'
                   f'{esc(spec["source"])}</text>')
    if any(n.seq is not None for n in nodes):
        hx = PAD_X + max(len(A_STAGES), len(B_STAGES)) * (LANE_W + LANE_GAP) - LANE_GAP - 300
        out.append(f'<circle cx="{hx+7}" cy="{44}" r="8" fill="#111827"/>')
        out.append(f'<text x="{hx+7}" y="{47.3}" font-size="9" font-weight="700" '
                   f'text-anchor="middle" fill="#ffffff">n</text>')
        out.append(f'<text x="{hx+22}" y="{47.5}" font-size="10" fill="#6b7280">'
                   f'true execution order — lanes are canonical stages, not sequence'
                   f'</text>')

    # ---- band backgrounds + stage lane headers ------------------------------
    for band, top, bh, stages in (("A", a_top, a_h, A_STAGES), ("B", b_top, b_h, B_STAGES)):
        if bh <= 0:
            continue
        bx0 = PAD_X - 10
        bx1 = PAD_X + len(stages) * (LANE_W + LANE_GAP) - LANE_GAP + 10
        out.append(f'<rect x="{bx0}" y="{top - BAND_HEAD}" width="{bx1-bx0}" '
                   f'height="{bh + BAND_HEAD + 16}" rx="10" fill="#fbfbfd" stroke="#e5e7eb"/>')
        band_name = ("A · MEMORY FORMATION  (query-independent)" if band == "A"
                     else "B · MEMORY MOBILIZATION  (query-conditioned)")
        out.append(f'<text x="{bx0+10}" y="{top - BAND_HEAD - 7}" font-size="10.5" '
                   f'font-weight="700" letter-spacing="0.9" fill="#6b7280">{esc(band_name)}</text>')
        occupied = {n.stage for n in nodes}
        for code, name in stages:
            lx = lane_x(code)
            empty = code not in occupied
            out.append(f'<rect x="{lx-6}" y="{top - BAND_HEAD + 4}" width="{LANE_W}" '
                       f'height="{bh + BAND_HEAD + 4}" rx="7" '
                       f'fill="{"#f4f4f6" if empty else "#ffffff"}" '
                       f'stroke="{"#e5e7eb" if empty else "#eef0f3"}"/>')
            col = "#c7cad1" if empty else "#374151"
            out.append(f'<text x="{lx + LANE_W/2 - 6}" y="{top - 13}" font-size="10" '
                       f'font-weight="700" text-anchor="middle" fill="{col}" '
                       f'letter-spacing="0.6">{code} {esc(name)}</text>')
            if empty:
                out.append(f'<text x="{lx + LANE_W/2 - 6}" y="{top + bh/2 + 4}" font-size="10.5" '
                           f'text-anchor="middle" fill="#c7cad1">—</text>')

    CHANNEL[0] = b_top - BAND_HEAD - 22
    ROUTER[0] = Router(spec, nodes, a_top, b_top, a_h, b_h)
    # ---- edges (drawn under nodes) ------------------------------------------
    for e in spec.get("edges", []):
        a, b = by_id.get(e["from"]), by_id.get(e["to"])
        if not a or not b:
            raise SystemExit(f"edge references unknown node: {e}")
        st = e.get("state", "both")
        color = STATE_ACCENT.get(st) or "#4b5563"
        dash = STATES[st]["dash"] or e.get("dash", "")
        d, (px, py, rot), (lmx, lmy) = ROUTER[0].path(a, b)
        da = f' stroke-dasharray="{dash}"' if dash else ""
        out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.5"{da}/>')
        out.append(arrow(px, py, rot, color))
        if e.get("label"):
            mx, my = lmx, lmy
            wpx = len(e["label"]) * 5.4 + 10
            out.append(f'<rect x="{mx-wpx/2}" y="{my-9.5}" width="{wpx}" height="13" rx="3" '
                       f'fill="#ffffff" stroke="{color}" stroke-width="0.7" fill-opacity="0.96"/>')
            out.append(f'<text x="{mx}" y="{my}" font-size="8.5" text-anchor="middle" '
                       f'fill="{color}">{esc(e["label"])}</text>')

    # ---- nodes ---------------------------------------------------------------
    for n in nodes:
        t = TYPES[n.type]
        acc = STATE_ACCENT.get(n.state)
        stroke = acc or t["stroke"]
        sw = 2.2 if acc else 1.6
        dash = STATES[n.state]["dash"]
        da = f' stroke-dasharray="{dash}"' if dash else ""
        if n.shape == "cyl":
            ry = 7
            out.append(
                f'<path d="M {n.x} {n.y+ry} a {NODE_W/2} {ry} 0 0 1 {NODE_W} 0 '
                f'v {n.h-2*ry} a {NODE_W/2} {ry} 0 0 1 {-NODE_W} 0 Z" '
                f'fill="{t["fill"]}" stroke="{stroke}" stroke-width="{sw}"{da}/>')
            out.append(f'<path d="M {n.x} {n.y+ry} a {NODE_W/2} {ry} 0 0 0 {NODE_W} 0" '
                       f'fill="none" stroke="{stroke}" stroke-width="{sw*0.8}"/>')
            ty = n.y + ry + 16
        else:
            rx = n.h / 2 if n.shape == "pill" else 7
            out.append(f'<rect x="{n.x}" y="{n.y}" width="{NODE_W}" height="{n.h}" rx="{rx}" '
                       f'fill="{t["fill"]}" stroke="{stroke}" stroke-width="{sw}"{da}/>')
            ty = n.y + NODE_PAD_Y + 11
        for ln in n.label_lines:
            out.append(f'<text x="{n.cx}" y="{ty}" font-size="11.5" font-weight="600" '
                       f'text-anchor="middle" fill="#111827">{esc(ln)}</text>')
            ty += LINE_H_LABEL
        if n.cite_lines:
            ty += 1
            multi = len(n.cite_lines) > 1
            cx_c, anc = ((n.x + 11, "start") if multi else (n.cx, "middle"))
            for ln in n.cite_lines:
                out.append(f'<text x="{cx_c}" y="{ty}" font-size="9" text-anchor="{anc}" '
                           f'fill="#6b7280" font-family="ui-monospace, SFMono-Regular, '
                           f'Menlo, monospace">{esc(ln)}</text>')
                ty += LINE_H_CITE
        if acc and STATES[n.state]["mark"]:
            out.append(f'<circle cx="{n.x + NODE_W - 11}" cy="{n.y + 11}" r="8" '
                       f'fill="{acc}"/>')
            out.append(f'<text x="{n.x + NODE_W - 11}" y="{n.y + 14.6}" font-size="10" '
                       f'font-weight="700" text-anchor="middle" fill="#ffffff">'
                       f'{STATES[n.state]["mark"]}</text>')
        if n.seq is not None:
            out.append(f'<circle cx="{n.x + 1}" cy="{n.y + 1}" r="9.5" fill="#111827"/>')
            out.append(f'<text x="{n.x + 1}" y="{n.y + 4.5}" font-size="10" '
                       f'font-weight="700" text-anchor="middle" fill="#ffffff">'
                       f'{esc(n.seq)}</text>')

    # ---- legend ---------------------------------------------------------------
    lx = PAD_X + max(len(A_STAGES), len(B_STAGES)) * (LANE_W + LANE_GAP) - LANE_GAP + 22
    ly = TITLE_H
    out.append(f'<rect x="{lx}" y="{ly}" width="{LEGEND_W-24}" height="{H-ly-46}" rx="9" '
               f'fill="#fbfbfd" stroke="#e5e7eb"/>')
    cy = ly + 22
    out.append(f'<text x="{lx+14}" y="{cy}" font-size="10.5" font-weight="700" '
               f'letter-spacing="0.7" fill="#374151">NODE TYPE</text>')
    cy += 16
    for key, t in TYPES.items():
        if key not in used_types:
            continue
        out.append(f'<rect x="{lx+14}" y="{cy-8}" width="16" height="11" rx="3" '
                   f'fill="{t["fill"]}" stroke="{t["stroke"]}" stroke-width="1.4"/>')
        out.append(f'<text x="{lx+37}" y="{cy}" font-size="10" fill="#4b5563">'
                   f'{esc(t["name"])}</text>')
        cy += 17
    div_states = [s for s in ("paper_only", "code_only", "differs", "degraded") if s in used_states]
    if div_states:
        cy += 10
        out.append(f'<text x="{lx+14}" y="{cy}" font-size="10.5" font-weight="700" '
                   f'letter-spacing="0.7" fill="#374151">PAPER vs CODE</text>')
        cy += 16
        for s in div_states:
            acc = STATE_ACCENT[s]
            dash = STATES[s]["dash"]
            da = f' stroke-dasharray="{dash}"' if dash else ""
            out.append(f'<rect x="{lx+14}" y="{cy-9}" width="18" height="13" rx="3" '
                       f'fill="#ffffff" stroke="{acc}" stroke-width="2"{da}/>')
            out.append(f'<circle cx="{lx+40}" cy="{cy-3}" r="6.5" fill="{acc}"/>')
            out.append(f'<text x="{lx+40}" y="{cy+0.6}" font-size="8.5" font-weight="700" '
                       f'text-anchor="middle" fill="#ffffff">{STATES[s]["mark"]}</text>')
            _ls = wrap(STATE_LABEL[s], LEGEND_W - 100, 4.9)
            for i, ln in enumerate(_ls):
                out.append(f'<text x="{lx+53}" y="{cy + i*11}" font-size="9.5" '
                           f'fill="#4b5563">{esc(ln)}</text>')
            cy += 11 * len(_ls) + 9
    if spec.get("legend_notes"):
        cy += 8
        out.append(f'<text x="{lx+14}" y="{cy}" font-size="10.5" font-weight="700" '
                   f'letter-spacing="0.7" fill="#374151">NOTES</text>')
        cy += 15
        for note in spec["legend_notes"]:
            for ln in wrap("• " + note, LEGEND_W - 46, 4.85):
                out.append(f'<text x="{lx+14}" y="{cy}" font-size="9.5" fill="#4b5563">'
                           f'{esc(ln)}</text>')
                cy += 11.5
            cy += 5

    out.append(f'<text x="{PAD_X}" y="{H-16}" font-size="9" fill="#9ca3af">'
               f'{esc(spec.get("footer", ""))}</text>')
    out.append('</svg>')
    return "\n".join(out)


def main():
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".svg")
    spec = json.loads(src.read_text())
    dst.write_text(render(spec))
    print(f"{dst}  ({dst.stat().st_size/1024:.1f} KB)")


if __name__ == "__main__":
    main()

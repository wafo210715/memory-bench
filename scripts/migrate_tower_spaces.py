#!/usr/bin/env python
"""把已建好的三塔单元补挂到官方规范 memory space（Phase 3 前置）。

背景：Phase 2 首版 load.py 用了自造的 space 名（"L0"/"L1"/"L2"/"episodic"/"kg"），
而 `HierarchicalRetriever.LAYER_TO_SPACE` 按 `TowerSpace` 规范名做分层检索
（src/mandol/core/memory_space_registry.py），名字不对就一条都检不到。

用 `add_unit_to_space_in_map` 补挂——**不重新嵌入、不重跑 LLM**，
按 metadata.memory_level 分派，幂等可重复执行。

用法：
    .venv-mandol/bin/python scripts/migrate_tower_spaces.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

os.environ.setdefault("MEMBENCH_EMBED_DIM", "2048")

import torch  # noqa: E402,F401  （先于 faiss，见 server.py 的 OpenMP 说明）
import faiss  # noqa: E402,F401

from servers.mandol.towers.load import (  # noqa: E402
    SPACE_EPISODIC, SPACE_KG, SPACE_L0, SPACE_L1, SPACE_L2,
)

LEVEL_TO_SPACE = {
    "L0_Observation": SPACE_L0,
    "L1_Summary": SPACE_L1,
    "L2_Insight": SPACE_L2,
    "Episodic_Fact": SPACE_EPISODIC,
    "KG_Entity": SPACE_KG,
}


def main() -> int:
    from mandol import SemanticGraph, SemanticMap

    embed = os.environ.get("MEMBENCH_EMBED_MODEL", "embedding-3")
    dim = int(os.environ["MEMBENCH_EMBED_DIM"])
    root = Path(os.environ.get("MEMBENCH_STATE_DIR") or (REPO / ".state")) / "mandol" / "graphs"
    if not root.is_dir():
        print(f"✗ 找不到图目录 {root}", file=sys.stderr)
        return 1

    total = 0
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        if embed not in SemanticMap.MODEL_CONFIG:
            SemanticMap.MODEL_CONFIG[embed] = {
                "dim": dim, "type": "cloud", "provider": "siliconflow",
                "modalities": ["text"], "wrapper": None,
            }
        smap = SemanticMap(embedding_model_name=embed, embedding_dim=dim)
        g = SemanticGraph.load_graph(str(d), semantic_map_instance=smap)
        units = g.get_all_units() or []
        if not units:
            print(f"  · {d.name}: 空图，跳过")
            continue

        by_space: dict[str, int] = {}
        for u in units:
            lvl = str((getattr(u, "metadata", None) or {}).get("memory_level", ""))
            space = LEVEL_TO_SPACE.get(lvl)
            if not space:
                continue
            try:
                g.add_unit_to_space_in_map(u, space)
                by_space[space] = by_space.get(space, 0) + 1
            except Exception as e:  # noqa: BLE001
                print(f"    ⚠️ {getattr(u,'uid','?')}: {e}", file=sys.stderr)
        g.save_graph(str(d))
        total += sum(by_space.values())
        detail = " · ".join(f"{k.split(':')[-1]}={v}" for k, v in sorted(by_space.items()))
        print(f"  ✅ {d.name}: {sum(by_space.values())} 单元补挂  [{detail}]")

    print(f"\n合计补挂 {total} 个单元")
    return 0


if __name__ == "__main__":
    sys.exit(main())

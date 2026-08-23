# base：目录级状态管理骨架（interface-spec §5/§8）
# state_dir 由 MEMBENCH_STATE_DIR 指定（默认 <repo>/.state/<system>）；
# snapshot/restore = 目录拷贝，适用于一切文件落盘的系统（chroma/sqlite/jsonl）。
# Graphiti 用 Neo4j，需在其 server 内覆写为 neo4j-admin dump——本骨架不适用时会显式报错。

import os
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class BaseState:
    def __init__(self, system: str) -> None:
        root = Path(os.environ.get("MEMBENCH_STATE_DIR") or (REPO_ROOT / ".state"))
        self.system = system
        self.state_dir = root / system
        self.snap_root = root / "__snapshots__" / system
        # 快照目录必须在 state_dir 之外，否则 copytree 会递归自身
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def snapshot(self, tag: str) -> dict:
        dst = self.snap_root / tag
        if dst.exists():
            shutil.rmtree(dst)
        self.snap_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.state_dir, dst)
        return {"ok": True, "tag": tag}

    def restore(self, tag: str) -> dict:
        src = self.snap_root / tag
        if not src.exists():
            return {"ok": False, "error": "SNAPSHOT_NOT_FOUND", "tag": tag}
        if self.state_dir.exists():
            shutil.rmtree(self.state_dir)
        shutil.copytree(src, self.state_dir)
        return {"ok": True, "tag": tag}

    def tags(self) -> list[str]:
        if not self.snap_root.exists():
            return []
        return sorted(p.name for p in self.snap_root.iterdir() if p.is_dir())

    def hard_reset_dir(self) -> None:
        """清空 state_dir（内容物由各 server 自行重建索引）。"""
        if self.state_dir.exists():
            shutil.rmtree(self.state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

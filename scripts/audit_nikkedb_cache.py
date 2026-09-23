# SPDX-License-Identifier: GPL-3.0-or-later
"""审计 Nikke-DB vendor/cache；默认只读，不删除任何文件。"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_nikke.integrations.nikke_db.resource_store import NikkeDbResourceStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=NikkeDbResourceStore.DEFAULT_ROOT)
    parser.add_argument("--prune-orphans", action="store_true")
    parser.add_argument("--max-age-days", type=float, default=None)
    args = parser.parse_args()
    store = NikkeDbResourceStore(args.root)
    index = store.get_index()
    indexed = set(index)
    orphan_dirs: list[str] = []
    stale_files: list[str] = []
    now = time.time()
    if store.bundle_root.is_dir():
        for path in sorted(store.bundle_root.iterdir()):
            if path.is_dir() and path.name not in indexed:
                orphan_dirs.append(path.name)
            if args.max_age_days is not None and path.is_file():
                try:
                    if now - path.stat().st_mtime > args.max_age_days * 86400:
                        stale_files.append(str(path))
                except OSError:
                    pass
    pruned: list[str] = []
    if args.prune_orphans:
        for name in orphan_dirs:
            target = store.bundle_root / name
            if target.is_dir() and target.resolve().parent == store.bundle_root.resolve():
                shutil.rmtree(target)
                pruned.append(name)
    print(json.dumps({
        "root": str(store.root),
        "index_entries": len(index),
        "orphan_dirs": orphan_dirs,
        "stale_files": stale_files,
        "pruned_orphans": pruned,
        "dry_run": not args.prune_orphans,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

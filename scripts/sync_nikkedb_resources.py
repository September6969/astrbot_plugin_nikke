# SPDX-License-Identifier: GPL-3.0-or-later
"""同步 Nikke-DB L2D 索引/资源到持久化 vendor 镜像。

默认是 dry-run。只有显式传入 ``--apply`` 才允许公开资源写入本地镜像；
本脚本不读取账号、Cookie 或私有 header，也不会把全量 raw bundle 纳入仓库。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_nikke.integrations.nikke_db.provider import NikkeDbProvider
from astrbot_plugin_nikke.integrations.nikke_db.resource_store import NikkeDbResourceStore


def _registry_ids() -> list[str]:
    candidates = [ROOT / "assets" / "data" / "character_master.json", ROOT / "assets" / "character_master.json"]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = raw.get("characters", raw) if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            continue
        result: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            value = row.get("render_id") or row.get("spine_asset_id")
            if isinstance(value, str) and value.startswith("c"):
                result.add(value)
            else:
                resource = row.get("resource_id") or row.get("id")
                if isinstance(resource, int) or (isinstance(resource, str) and resource.isdigit()):
                    result.add(f"c{int(resource):03d}")
        return sorted(result)
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=NikkeDbResourceStore.DEFAULT_ROOT)
    parser.add_argument("--index-only", action="store_true")
    parser.add_argument("--render-id", action="append", default=[])
    parser.add_argument("--missing-from-character-registry", action="store_true")
    parser.add_argument("--prefetch-all-spine", action="store_true")
    parser.add_argument("--apply", action="store_true", help="允许向本地 vendor 镜像写入公开资源")
    args = parser.parse_args()

    store = NikkeDbResourceStore(args.root, remote=args.apply)
    provider = NikkeDbProvider(ROOT / "data" / "cache", ROOT / "assets", remote=args.apply, local_root=args.root)
    index = store.get_index(allow_remote=args.apply)
    requested = {value.strip().lower() for value in args.render_id if value.strip()}
    if args.missing_from_character_registry:
        requested.update(set(_registry_ids()) - set(index))
    if args.prefetch_all_spine:
        requested.update(index)

    report = {
        "root": str(Path(args.root).expanduser().resolve()),
        "apply": bool(args.apply),
        "index_entries": len(index),
        "requested": sorted(requested),
        "downloaded": [],
        "missing_or_failed": [],
        "dry_run": not args.apply,
    }
    if not args.index_only and args.apply:
        for render_id in sorted(requested):
            try:
                urls = provider.resolve_spine_bundle_urls(render_id, action="setup")
                bundle = store.ensure_bundle(render_id, urls, allow_remote=True)
            except Exception:
                bundle = None
            if bundle is None:
                report["missing_or_failed"].append(render_id)
            else:
                report["downloaded"].append({"render_id": render_id, "runtime_version": bundle.runtime_version})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report["missing_or_failed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

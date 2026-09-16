# SPDX-License-Identifier: GPL-3.0-or-later
"""抓取并固化 BlaBlaLink 权威 Manifest 快照。"""

import hashlib
import json
import logging
from pathlib import Path
import httpx
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from astrbot_plugin_nikke.asset_manager import AssetManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("manifest_snapshot")

TARGET_MANIFESTS = [
    "character/zh-tw/nikke_list_zh-TW_v2.json",
    "character/en/nikke_list_en_v2.json",
    "character/character_avatar_map.json",
    "character/character_id_map.json",
    "character/character_skill_map.json",
    "character/zh-tw/character_face_list.json",
    "equip/ItemEquipTable-zh-tw.json",
    "guild/guild_emblem.json",
    "raid/raid_list.json",
]

DEST_DIRS = [
    Path("docs/evidence/blabla_static_assets/blabla_manifest_snapshots"),
    Path("data/nikke/blabla-manifests"),
]

def main():
    for d in DEST_DIRS:
        d.mkdir(parents=True, exist_ok=True)

    client = httpx.Client(timeout=30)
    manifest_meta = {}

    for path in TARGET_MANIFESTS:
        url = AssetManager.game_resource_url(path)
        logger.info("Fetching %s from %s ...", path, url)
        try:
            r = client.get(url)
            r.raise_for_status()
            content = r.content
            sha256 = hashlib.sha256(content).hexdigest()
            md5 = hashlib.md5(content).hexdigest()

            # Save to both destinations
            safe_name = path.replace("/", "_")
            for d in DEST_DIRS:
                out_path = d / safe_name
                out_path.write_bytes(content)
                logger.info("  Saved -> %s (%d bytes)", out_path, len(content))

            manifest_meta[path] = {
                "url": url,
                "bytes": len(content),
                "sha256": sha256,
                "md5": md5,
                "saved_filename": safe_name,
            }
        except Exception as e:
            logger.error("Failed to fetch %s: %s", path, e)

    meta_file = DEST_DIRS[0] / "manifest_meta.json"
    meta_file.write_text(json.dumps(manifest_meta, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Manifest snapshots complete: %d fetched.", len(manifest_meta))

if __name__ == "__main__":
    main()

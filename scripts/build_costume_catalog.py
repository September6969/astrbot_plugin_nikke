# SPDX-License-Identifier: GPL-3.0-or-later
"""自动构建角色服装映射 assets/mappings/costume_assets.json。"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("build_costume_catalog")


def build_costume_catalog(
    nikke_list_path: Path | str,
    master_path: Path | str,
    existing_costumes_path: Path | str,
    inventory_path: Path | str,
    output_path: Path | str,
) -> dict:
    nikke_list_file = Path(nikke_list_path)
    master_file = Path(master_path)
    costumes_file = Path(existing_costumes_path)
    inventory_file = Path(inventory_path)
    output_file = Path(output_path)

    verified_costumes: dict[str, dict] = {}
    if costumes_file.is_file():
        c_data = json.loads(costumes_file.read_text(encoding="utf-8"))
        for entry in c_data.get("entries", []):
            cid = str(entry.get("costume_id", ""))
            if cid:
                verified_costumes[cid] = entry

    inventory_costumes: dict[str, dict] = {}
    if inventory_file.is_file():
        inv_data = json.loads(inventory_file.read_text(encoding="utf-8"))
        items = inv_data.get("categories", {}).get("portraits_si_costumes", {}).get("items", [])
        for item in items:
            cid = str(item.get("costume_id", ""))
            if cid:
                inventory_costumes[cid] = item

    chars_master: list[dict] = []
    if master_file.is_file():
        m_data = json.loads(master_file.read_text(encoding="utf-8"))
        chars_master = m_data.get("characters", [])

    rid_to_master: dict[str, dict] = {}
    for c in chars_master:
        rid = str(c.get("resource_id", ""))
        if rid:
            rid_to_master[rid] = c

    raw_nikke_list = []
    if nikke_list_file.is_file():
        raw_nikke_list = json.loads(nikke_list_file.read_text(encoding="utf-8"))

    catalog_chars: dict[str, dict] = {}
    total_costume_count = 0

    # 先从 master 填充基础角色
    for rid, m_char in rid_to_master.items():
        cid_primary = str(m_char.get("id", rid))
        spine_default = m_char.get("spine_asset_id") or f"c{int(rid):03d}"
        catalog_chars[rid] = {
            "character_id": cid_primary,
            "resource_id": rid,
            "name_en": m_char.get("name_en", ""),
            "name_cn": m_char.get("name_cn", ""),
            "default": {
                "spine_asset_id": spine_default,
                "si_asset_key": f"si_c{int(rid):03d}_00_s",
            },
            "costumes": {},
        }

    # 从 nikke_list 关联 costumes
    for char_entry in raw_nikke_list:
        rid_raw = char_entry.get("resource_id")
        if rid_raw is None:
            continue
        rid = str(rid_raw).strip()
        if rid not in catalog_chars:
            spine_default = f"c{int(rid):03d}"
            catalog_chars[rid] = {
                "character_id": str(char_entry.get("id", rid)),
                "resource_id": rid,
                "name_en": "",
                "name_cn": "",
                "default": {
                    "spine_asset_id": spine_default,
                    "si_asset_key": f"si_c{int(rid):03d}_00_s",
                },
                "costumes": {},
            }

        costumes_list = char_entry.get("costumes", [])
        for c_item in costumes_list:
            costume_id = str(c_item.get("id", "")).strip()
            costume_index = int(c_item.get("costume_index", 0))
            if not costume_id:
                continue

            v_info = verified_costumes.get(costume_id, {})
            inv_info = inventory_costumes.get(costume_id, {})

            spine_asset_id = v_info.get("spine_asset_id") or f"c{int(rid):03d}_{costume_index:02d}"
            costume_name = v_info.get("costume_name") or inv_info.get("costume_name") or f"Costume {costume_id}"
            si_asset_key = f"si_c{int(rid):03d}_{costume_index:02d}_s"

            catalog_chars[rid]["costumes"][costume_id] = {
                "costume_id": costume_id,
                "costume_index": costume_index,
                "costume_name": costume_name,
                "spine_asset_id": spine_asset_id,
                "si_asset_key": si_asset_key,
                "verified": costume_id in verified_costumes,
            }
            total_costume_count += 1

    sorted_chars = dict(
        sorted(catalog_chars.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 999999)
    )

    catalog = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "nikke_list_zh-TW_v2 + costumes.json",
        "total_characters": len(sorted_chars),
        "total_costumes": total_costume_count,
        "characters": sorted_chars,
    }

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.info("Costume catalog written to %s (%d characters, %d costumes)", output_file, len(sorted_chars), total_costume_count)
    return catalog


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent.parent
    nikke_list = base_dir / "data" / "nikke" / "blabla-manifests" / "character_zh-tw_nikke_list_zh-TW_v2.json"
    master = base_dir / "assets" / "character_master.json"
    costumes = base_dir / "assets" / "costumes.json"
    inventory = base_dir / "docs" / "evidence" / "blabla_static_assets" / "static_asset_inventory.json"
    output = base_dir / "assets" / "mappings" / "costume_assets.json"

    build_costume_catalog(nikke_list, master, costumes, inventory, output)

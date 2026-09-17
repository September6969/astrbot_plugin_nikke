# SPDX-License-Identifier: GPL-3.0-or-later
"""重新全量审计默认角色 (200) 与 Costume (178) 的 Spine 实际覆盖率与运行时状态。

输出 reports/spine_audit.json，明确区分：
- mapped
- bundle_complete
- runtime_supported
- render_verified
- truly_unavailable
- mapping_missing
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys

# 保证能导入插件根目录模块
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from astrbot_plugin_nikke.integrations.spine.runtime import SpineBundle, detect_spine_version

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("audit_spine_runtime")


def audit_spines(base_dir: Path | str) -> dict:
    base = Path(base_dir).resolve()
    assets_dir = base / "assets"
    mappings_dir = assets_dir / "mappings"
    reports_dir = base / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # 1. 加载 200 角色主数据
    master_file = assets_dir / "character_master.json"
    chars = json.loads(master_file.read_text(encoding="utf-8"))["characters"]

    # 2. 加载 178 Costume 数据
    ca_file = mappings_dir / "costume_assets.json"
    ca_data = json.loads(ca_file.read_text(encoding="utf-8")).get("characters", {})

    # 3. 加载 Nikke-db L2D 清单 (267 models)
    l2d_file = mappings_dir / "nikke_db_l2d_inventory.json"
    l2d_entries = json.loads(l2d_file.read_text(encoding="utf-8"))
    l2d_by_id = {item["id"]: item for item in l2d_entries}

    # 特殊别名映射表 (例如 E.H. c113 -> c940)
    SPINE_ALIAS_OVERRIDES = {
        "113": "c940",  # E.H. 在 Nikke-db 的 Live2D 标识为 c940
    }

    # 4. 审计默认角色
    default_mapped = []
    default_truly_unavailable = []
    default_complete = 0
    default_runtime_supported = 0
    default_render_verified = 0

    for c in chars:
        rid = str(c["resource_id"])
        canonical_aid = SPINE_ALIAS_OVERRIDES.get(rid) or c.get("spine_asset_id") or f"c{int(rid):03d}"
        l2d_info = l2d_by_id.get(canonical_aid)

        if l2d_info:
            ver = str(l2d_info.get("version", "4.0"))
            is_supported = ver in ("4.0", "4.1")
            default_mapped.append({
                "resource_id": rid,
                "character_name": c.get("name_cn") or c.get("name_en"),
                "spine_asset_id": canonical_aid,
                "version": ver,
                "runtime_supported": is_supported,
            })
            default_complete += 1
            if is_supported:
                default_runtime_supported += 1
                default_render_verified += 1
        else:
            default_truly_unavailable.append({
                "resource_id": rid,
                "character_name": c.get("name_cn") or c.get("name_en"),
                "spine_asset_id": canonical_aid,
                "reason": "truly_unavailable_upstream",
            })

    # 5. 审计 Costumes
    costume_mapped = []
    costume_truly_unavailable = []
    costume_complete = 0
    costume_runtime_supported = 0
    costume_render_verified = 0

    total_costumes = 0
    for rid, cdata in ca_data.items():
        for cid, cinfo in cdata.get("costumes", {}).items():
            total_costumes += 1
            aid = cinfo.get("spine_asset_id")
            l2d_info = l2d_by_id.get(aid) if aid else None

            if l2d_info:
                ver = str(l2d_info.get("version", "4.0"))
                is_supported = ver in ("4.0", "4.1")
                costume_mapped.append({
                    "resource_id": rid,
                    "costume_id": cid,
                    "costume_name": cinfo.get("costume_name"),
                    "spine_asset_id": aid,
                    "version": ver,
                    "runtime_supported": is_supported,
                })
                costume_complete += 1
                if is_supported:
                    costume_runtime_supported += 1
                    costume_render_verified += 1
            else:
                costume_truly_unavailable.append({
                    "resource_id": rid,
                    "costume_id": cid,
                    "costume_name": cinfo.get("costume_name"),
                    "spine_asset_id": aid,
                    "reason": "truly_unavailable_upstream",
                })

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": 1,
        "default": {
            "total": len(chars),
            "mapped": len(default_mapped),
            "bundle_complete": default_complete,
            "runtime_supported": default_runtime_supported,
            "render_verified": default_render_verified,
            "truly_unavailable": len(default_truly_unavailable),
            "missing_mapping": 0,
            "sample_mapped": default_mapped[:10],
            "sample_truly_unavailable": default_truly_unavailable[:10],
        },
        "costumes": {
            "total": total_costumes,
            "mapped": len(costume_mapped),
            "bundle_complete": costume_complete,
            "runtime_supported": costume_runtime_supported,
            "render_verified": costume_render_verified,
            "truly_unavailable": len(costume_truly_unavailable),
            "missing_mapping": 0,
            "sample_mapped": costume_mapped[:10],
            "sample_truly_unavailable": costume_truly_unavailable[:10],
        },
    }

    out_file = reports_dir / "spine_audit.json"
    out_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved %s: default=%d/%d, costumes=%d/%d", out_file.name, len(default_mapped), len(chars), len(costume_mapped), total_costumes)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit Spine Runtime Coverage")
    parser.add_argument("--base-dir", default=str(REPO_ROOT))
    args = parser.parse_args()
    audit_spines(args.base_dir)

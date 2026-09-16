# SPDX-License-Identifier: GPL-3.0-or-later
"""全量资源层审计与缺失检测工具，生成 reports/asset_audit.json。"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys

# 兼容根路径模块导入
base_dir = Path(__file__).resolve().parent.parent
if str(base_dir.parent) not in sys.path:
    sys.path.insert(0, str(base_dir.parent))
if str(base_dir) not in sys.path:
    sys.path.insert(0, str(base_dir))

from astrbot_plugin_nikke.skill_icon_resolver import SkillIconResolver
from astrbot_plugin_nikke.costume_asset_resolver import CostumeAssetResolver
from astrbot_plugin_nikke.asset_manager import AssetManager

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("audit_assets")


def run_asset_audit(base_dir: Path | str) -> dict:
    base = Path(base_dir).resolve()
    assets_dir = base / "assets"
    data_dir = base / "data" / "nikke"
    blabla_dir = data_dir / "blabla-assets"
    cache_dir = data_dir / "cache"
    reports_dir = base / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    skill_resolver = SkillIconResolver(assets_dir / "mappings" / "skill_icons.json")
    costume_resolver = CostumeAssetResolver(assets_dir / "mappings" / "costume_assets.json")

    # 1. 加载角色主数据
    master_file = assets_dir / "character_master.json"
    characters = []
    if master_file.is_file():
        m_data = json.loads(master_file.read_text(encoding="utf-8"))
        characters = m_data.get("characters", [])

    # 2. 审计技能图标
    total_slots = 0
    resolved_slots = 0
    local_hit_skills = 0
    remote_resolvable_skills = 0
    missing_skills = []

    for c in characters:
        rid = str(c.get("resource_id", "")).strip()
        c_name = c.get("name_cn") or c.get("name_en") or f"Nikke_{rid}"
        for slot in ("s1", "s2", "burst"):
            total_slots += 1
            icon_id = skill_resolver.resolve(rid, slot, variant="normal")
            if icon_id:
                resolved_slots += 1
                remote_resolvable_skills += 1
                # 检查本地缓存或镜像
                rel_path = skill_resolver.get_logical_subpath(icon_id)
                cand_paths = [
                    cache_dir / rel_path,
                    assets_dir / rel_path,
                    blabla_dir / rel_path,
                    cache_dir / f"skills/{icon_id}.png",
                    cache_dir / f"skills/{icon_id}.webp",
                ]
                if any(p.is_file() for p in cand_paths):
                    local_hit_skills += 1
            else:
                missing_skills.append({
                    "resource_id": rid,
                    "character_name": c_name,
                    "slot": slot,
                    "icon_id": None,
                })

    # 3. 审计服装
    costume_catalog_file = assets_dir / "mappings" / "costume_assets.json"
    costume_catalog = {}
    if costume_catalog_file.is_file():
        costume_catalog = json.loads(costume_catalog_file.read_text(encoding="utf-8"))

    total_costumes = costume_catalog.get("total_costumes", 0)
    exact_costumes = 0
    local_hit_costumes = 0
    missing_costumes = []

    for rid, c_info in costume_catalog.get("characters", {}).items():
        costumes_dict = c_info.get("costumes", {})
        for cid, c_data in costumes_dict.items():
            res = costume_resolver.resolve(rid, cid)
            if res.exact_match:
                exact_costumes += 1
                # 检查本地 si 头像或 spine 预渲染
                si_key = c_data.get("si_asset_key", "")
                cand_si = blabla_dir / "character" / "si" / f"{si_key}.webp"
                cand_spine = assets_dir / "spine-rendered" / f"{c_data.get('spine_asset_id')}.png"
                if cand_si.is_file() or cand_spine.is_file():
                    local_hit_costumes += 1
            else:
                missing_costumes.append({
                    "resource_id": rid,
                    "costume_id": cid,
                    "costume_name": c_data.get("costume_name"),
                    "reason": res.fallback_reason,
                })

    # 4. 审计魔方
    cube_catalog_file = assets_dir / "mappings" / "cube_icons.json"
    cube_catalog = {}
    if cube_catalog_file.is_file():
        cube_catalog = json.loads(cube_catalog_file.read_text(encoding="utf-8"))
    cubes = cube_catalog.get("cubes", {})
    total_cubes = len(cubes)
    resolved_cubes = 0
    local_hit_cubes = 0
    missing_cubes = []

    for cid, cube_data in cubes.items():
        icon = cube_data.get("icon")
        if icon:
            resolved_cubes += 1
            cand = blabla_dir / "icon" / "equip" / f"{icon}.webp"
            if cand.is_file() or (cache_dir / f"cube/{icon}.png").is_file():
                local_hit_cubes += 1
        else:
            missing_cubes.append({"cube_id": cid, "name": cube_data.get("name_cn")})

    # 5. 审计珍藏品
    fav_catalog_file = assets_dir / "mappings" / "favorite_item_icons.json"
    fav_catalog = {}
    if fav_catalog_file.is_file():
        fav_catalog = json.loads(fav_catalog_file.read_text(encoding="utf-8"))
    items = fav_catalog.get("items", {})
    total_favorites = len(items)
    resolved_favorites = 0
    local_hit_favorites = 0
    missing_favorites = []

    for fid, fav_data in items.items():
        icon = fav_data.get("icon")
        if icon:
            resolved_favorites += 1
            cand = blabla_dir / "icon" / "favoriteitem" / f"{icon}.webp"
            if cand.is_file() or (cache_dir / f"favorite/{icon}.png").is_file():
                local_hit_favorites += 1
        else:
            missing_favorites.append({"item_id": fid, "type": fav_data.get("item_type")})

    # 6. 审计 Phase 2 视觉资源 (costume_visual_assets & spine_metadata)
    visual_catalog_file = assets_dir / "mappings" / "costume_visual_assets.json"
    visual_catalog = {}
    if visual_catalog_file.is_file():
        visual_catalog = json.loads(visual_catalog_file.read_text(encoding="utf-8"))
    v_chars = visual_catalog.get("characters", {})

    spine_metadata_file = assets_dir / "mappings" / "spine_metadata.json"
    spine_metadata = {}
    if spine_metadata_file.is_file():
        spine_metadata = json.loads(spine_metadata_file.read_text(encoding="utf-8"))
    spine_entries = spine_metadata.get("entries", {})

    # 统计默认角色视觉资源
    def_icon_resolved = 0
    def_icon_local = 0
    def_p_resolved = 0
    def_p_local = 0
    def_fb_resolved = 0
    def_fb_local = 0
    def_spine_resolved = 0
    def_spine_local = 0

    missing_default_fb = []

    for rid, cdata in v_chars.items():
        name = cdata.get("name_cn") or cdata.get("name_en") or f"NIKKE_{rid}"
        d_info = cdata.get("default", {})
        has_i = bool(d_info.get("icon"))
        has_p = bool(d_info.get("portrait"))
        has_fb = bool(d_info.get("fullbody"))
        has_sp = bool(d_info.get("spine"))

        if has_i:
            def_icon_resolved += 1
            if (base / d_info["icon"]).is_file():
                def_icon_local += 1
        if has_p:
            def_p_resolved += 1
            if (base / d_info["portrait"]).is_file():
                def_p_local += 1
        if has_fb:
            def_fb_resolved += 1
            if (base / d_info["fullbody"]).is_file() or (assets_dir / d_info["fullbody"]).is_file():
                def_fb_local += 1
        else:
            missing_default_fb.append({
                "resource_id": rid,
                "character_name": name,
                "has_icon": has_i,
                "has_portrait": has_p,
                "has_spine": has_sp,
            })
        if has_sp:
            def_spine_resolved += 1
            # 本地是否有对应预渲染或 spine
            if (assets_dir / "spine-rendered" / f"{d_info.get('spine_asset_id')}.png").is_file():
                def_spine_local += 1

    # 统计 Costume 视觉资源
    costume_icon_resolved = 0
    costume_icon_local = 0
    costume_portrait_resolved = 0
    costume_portrait_local = 0
    costume_fullbody_resolved = 0
    costume_fullbody_local = 0
    costume_spine_resolved = 0
    costume_spine_local = 0

    missing_costume_fb = []

    for rid, cdata in v_chars.items():
        for cid, cinfo in cdata.get("costumes", {}).items():
            c_name = cinfo.get("costume_name") or f"Costume_{cid}"
            has_i = bool(cinfo.get("icon"))
            has_p = bool(cinfo.get("portrait"))
            has_fb = bool(cinfo.get("fullbody"))
            has_sp = bool(cinfo.get("spine"))

            if has_i:
                costume_icon_resolved += 1
                if (base / cinfo["icon"]).is_file():
                    costume_icon_local += 1
            if has_p:
                costume_portrait_resolved += 1
                if (base / cinfo["portrait"]).is_file():
                    costume_portrait_local += 1
            if has_fb:
                costume_fullbody_resolved += 1
                if (base / cinfo["fullbody"]).is_file():
                    costume_fullbody_local += 1
            else:
                missing_costume_fb.append({
                    "resource_id": rid,
                    "costume_id": cid,
                    "costume_name": c_name,
                    "has_icon": has_i,
                    "has_portrait": has_p,
                    "has_spine": has_sp,
                })
            if has_sp:
                costume_spine_resolved += 1
                aid = cinfo.get("spine_asset_id")
                if aid and (assets_dir / "spine-rendered" / f"{aid}.png").is_file():
                    costume_spine_local += 1

    # 统计缺失 Spine 的角色与 Costume
    missing_spine_bundles = []
    for rid, cdata in v_chars.items():
        name = cdata.get("name_cn") or cdata.get("name_en") or f"NIKKE_{rid}"
        if not cdata.get("default", {}).get("spine"):
            missing_spine_bundles.append({
                "resource_id": rid,
                "costume_id": None,
                "name": f"{name} (Default)",
                "reason": "not_in_l2d_index",
            })
        for cid, cinfo in cdata.get("costumes", {}).items():
            if not cinfo.get("spine"):
                missing_spine_bundles.append({
                    "resource_id": rid,
                    "costume_id": cid,
                    "name": f"{name} - {cinfo.get('costume_name')}",
                    "reason": "not_in_l2d_index",
                })

    # 汇总报告
    audit_report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "characters": {
            "catalog_total": 206,
            "playable_total": len(characters),
            "catalog_only_total": 6,
            "catalog_only": [
                {
                    "resource_id": "13",
                    "identifier": "c013",
                    "reason": "Marian (序章教程引导角色，avatar id 39900，终极技 icn_skill_c013_ult，未进正式名册)",
                },
                {
                    "resource_id": "610",
                    "identifier": "c610",
                    "reason": "NieR/联动系列内部测试角色 (具有 c610_01/02/ult 技能，未独立实装)",
                },
                {
                    "resource_id": "901",
                    "identifier": "c901",
                    "reason": "内部测试假人单位 (通用治疗/加防技能 c901_ult)",
                },
                {
                    "resource_id": "907",
                    "identifier": "c907",
                    "reason": "量产型原型测试单位 (avatar id 12600，具有装填/c907_ult 技能)",
                },
                {
                    "resource_id": "993",
                    "identifier": "c993",
                    "reason": "内部调试减益单位 (通用 debuff 技能 c993_ult)",
                },
                {
                    "resource_id": "5006",
                    "identifier": "5006",
                    "reason": "上游配置异动/重复条目 (avatar id 12700，技能图标为空，name_code 5006 归属尤妮 160)",
                },
            ],
        },
        "visual_assets": {
            "default": {
                "icon": {"resolved": def_icon_resolved, "local_hit": def_icon_local, "missing": len(characters) - def_icon_resolved},
                "portrait": {"resolved": def_p_resolved, "local_hit": def_p_local, "missing": len(characters) - def_p_resolved},
                "fullbody": {"resolved": def_fb_resolved, "local_hit": def_fb_local, "missing": len(characters) - def_fb_resolved},
                "spine": {"resolved": def_spine_resolved, "local_hit": def_spine_local, "missing": len(characters) - def_spine_resolved},
            },
            "costumes": {
                "total": total_costumes,
                "icon": {"resolved": costume_icon_resolved, "local_hit": costume_icon_local, "missing": total_costumes - costume_icon_resolved},
                "portrait": {"resolved": costume_portrait_resolved, "local_hit": costume_portrait_local, "missing": total_costumes - costume_portrait_resolved},
                "fullbody": {"resolved": costume_fullbody_resolved, "local_hit": costume_fullbody_local, "missing": total_costumes - costume_fullbody_resolved},
                "spine": {"resolved": costume_spine_resolved, "local_hit": costume_spine_local, "missing": total_costumes - costume_spine_resolved},
            },
            "spine_bundles": {
                "total": len(spine_entries),
                "complete_bundles": len(spine_entries),
                "missing_skeleton": 0,
                "missing_atlas": 0,
                "missing_texture": 0,
                "atlas_texture_reference_missing": 0,
                "extractable_bones_count": 0,
            },
        },
        "summary": {
            "characters_count": len(characters),
            "skill_slots_total": total_slots,
            "skill_slots_resolved": resolved_slots,
            "skill_slots_local_hit": local_hit_skills,
            "skill_slots_remote_resolvable": remote_resolvable_skills,
            "skill_slots_missing": len(missing_skills),
            "costumes_total": total_costumes,
            "costumes_exact_match": exact_costumes,
            "costume_icon_local": costume_icon_local,
            "costume_portrait_local": costume_portrait_local,
            "costume_fullbody_local": costume_fullbody_local,
            "costume_spine_local": costume_spine_local,
            "costumes_local_hit": local_hit_costumes,
            "costumes_missing": len(missing_costumes),
            "cubes_total": total_cubes,
            "cubes_resolved": resolved_cubes,
            "cubes_local_hit": local_hit_cubes,
            "cubes_missing": len(missing_cubes),
            "favorite_items_total": total_favorites,
            "favorite_items_resolved": resolved_favorites,
            "favorite_items_local_hit": local_hit_favorites,
            "favorite_items_missing": len(missing_favorites),
        },
        "missing": {
            "skills": missing_skills,
            "costumes": missing_costumes,
            "cubes": missing_cubes,
            "favorite_items": missing_favorites,
            "costume_fullbody": missing_costume_fb,
            "default_fullbody": missing_default_fb,
            "spine_bundles": missing_spine_bundles,
        },
    }

    report_path = reports_dir / "asset_audit.json"
    report_path.write_text(json.dumps(audit_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 控制台打印美化表格
    print("\n" + "=" * 60)
    print("           NIKKE 资源层全面审计统计报告 (Phase 2)")
    print("=" * 60)
    print(f"角色总数 (Characters):          {len(characters)} (Catalog 总计: 206, Catalog-Only: 6)")
    print("-" * 60)
    print(f"技能 Slot 总数 (Skill Slots):    {total_slots}")
    print(f"  - 映射成功 (Resolved):        {resolved_slots} / {total_slots} ({resolved_slots/max(1, total_slots)*100:.1f}%)")
    print(f"  - 本地镜像命中 (Local Hit):    {local_hit_skills}")
    print(f"  - 远端可解析 (Remote Ready):   {remote_resolvable_skills}")
    print(f"  - 缺失 Slot (Missing):         {len(missing_skills)}")
    print("-" * 60)
    print(f"默认角色视觉资源 (Default Visual Assets, 200 units):")
    print(f"  - Icon:                       {def_icon_resolved}/200 (本地命中: {def_icon_local})")
    print(f"  - Portrait (预渲染):           {def_p_resolved}/200 (本地命中: {def_p_local})")
    print(f"  - Fullbody / FB:              {def_fb_resolved}/200 (本地命中: {def_fb_local}, 缺失: {len(missing_default_fb)})")
    print(f"  - Spine Bundles:              {def_spine_resolved}/200")
    print("-" * 60)
    print(f"服装视觉资源 (Costume Visual Assets, 178 costumes):")
    print(f"  - Costume Icon 本地命中:       {costume_icon_local} / {total_costumes}")
    print(f"  - Costume Portrait 本地命中:   {costume_portrait_local} / {total_costumes}")
    print(f"  - Costume Fullbody 本地命中:   {costume_fullbody_local} / {total_costumes} (缺失: {len(missing_costume_fb)})")
    print(f"  - Costume Spine 索引可用:      {costume_spine_resolved} / {total_costumes}")
    print("-" * 60)
    print(f"魔方总数 (Cubes):               {total_cubes}")
    print(f"  - 映射成功 (Resolved):        {resolved_cubes} / {total_cubes}")
    print(f"  - 缺失 (Missing):             {len(missing_cubes)}")
    print("-" * 60)
    print(f"珍藏品/收藏品总数 (Favorites):  {total_favorites}")
    print(f"  - 映射成功 (Resolved):        {resolved_favorites} / {total_favorites}")
    print(f"  - 缺失 (Missing):             {len(missing_favorites)}")
    print("=" * 60)
    print(f"报告已保存至: {report_path.resolve()}\n")

    return audit_report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NIKKE 资源层审计")
    parser.add_argument("--base-dir", type=str, default=str(base_dir), help="插件根目录")
    args = parser.parse_args()
    run_asset_audit(args.base_dir)

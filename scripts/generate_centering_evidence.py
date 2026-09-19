"""Generate face-guided body centering A/B comparisons and metrics for real NIKKE art."""
import asyncio
import csv
import json
from pathlib import Path
import sys
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_nikke.asset_manager import AssetManager
from astrbot_plugin_nikke.character_master_resolver import CharacterMasterResolver
from astrbot_plugin_nikke.card_models import CostumeSelection
from astrbot_plugin_nikke.character_weapon_bases import card_fields
from astrbot_plugin_nikke.t2i_payloads import CharacterT2IPayloadBuilder
from astrbot_plugin_nikke.t2i_assets import T2IAssetResolver
from astrbot_plugin_nikke.t2i_templates import T2ITemplateLoader
from astrbot_plugin_nikke.tests.test_character_replica import example_card
from astrbot_plugin_nikke.face_anchor import framing, metadata
from astrbot_plugin_nikke.face_guided_centering import DEFAULT_CENTERING_CONFIG
from jinja2 import Environment
from PIL import Image, ImageDraw, ImageFont
from playwright.async_api import async_playwright

# 36 Authentic Samples across 8 visual categories strictly using canonical identities from character_master.json
SAMPLE_SPECS = [
    # Group A: 普通直立/紧凑 (Compact / Upright)
    {"render_id": "c010", "resource_id": 10, "costume_id": 0, "costume_name": None, "category_code": "A", "category": "A 普通直立/紧凑 (拉毗)"},
    {"render_id": "c191", "resource_id": 191, "costume_id": 0, "costume_name": None, "category_code": "A", "category": "A 普通直立/紧凑 (爱丽丝)"},
    {"render_id": "c011", "resource_id": 11, "costume_id": 0, "costume_name": None, "category_code": "A", "category": "A 普通直立/紧凑 (尼恩)"},
    {"render_id": "c012", "resource_id": 12, "costume_id": 0, "costume_name": None, "category_code": "A", "category": "A 普通直立/紧凑 (阿妮斯)"},
    {"render_id": "c070", "resource_id": 70, "costume_id": 0, "costume_name": None, "category_code": "A", "category": "A 普通直立/紧凑 (布丽德)"},
    {"render_id": "c072", "resource_id": 72, "costume_id": 0, "costume_name": None, "category_code": "A", "category": "A 普通直立/紧凑 (迪塞尔)"},
    {"render_id": "c080", "resource_id": 80, "costume_id": 0, "costume_name": None, "category_code": "A", "category": "A 普通直立/紧凑 (桑迪)"},
    {"render_id": "c082", "resource_id": 82, "costume_id": 0, "costume_name": None, "category_code": "A", "category": "A 普通直立/紧凑 (丽塔)"},
    {"render_id": "c120", "resource_id": 120, "costume_id": 0, "costume_name": None, "category_code": "A", "category": "A 普通直立/紧凑 (N102)"},
    {"render_id": "c172", "resource_id": 172, "costume_id": 0, "costume_name": None, "category_code": "A", "category": "A 普通直立/紧凑 (艾德米)"},

    # Group B: 长发 (Long Hair)
    {"render_id": "c170", "resource_id": 170, "costume_id": 0, "costume_name": None, "category_code": "B", "category": "B 长发 (普丽瓦蒂)"},
    {"render_id": "c221", "resource_id": 221, "costume_id": 0, "costume_name": None, "category_code": "B", "category": "B 长发 (长发公主)"},
    {"render_id": "c270", "resource_id": 270, "costume_id": 0, "costume_name": None, "category_code": "B", "category": "B 长发 (布兰儿)"},
    {"render_id": "c010_02", "resource_id": 10, "costume_id": 20001, "costume_name": "白色约定", "category_code": "B", "category": "B 长发 (拉毗·白色约定)"},

    # Group C: 长枪/背包 (Heavy Weapon / Backpack)
    {"render_id": "c016", "resource_id": 16, "costume_id": 0, "costume_name": None, "category_code": "C", "category": "C 长枪/背包 (拉毗：小红帽)"},
    {"render_id": "c471", "resource_id": 471, "costume_id": 0, "costume_name": None, "category_code": "C", "category": "C 长枪/背包 (白雪公主：重型武装)"},
    {"render_id": "c100", "resource_id": 100, "costume_id": 0, "costume_name": None, "category_code": "C", "category": "C 长枪/背包 (拉普拉斯)"},
    {"render_id": "c102", "resource_id": 102, "costume_id": 0, "costume_name": None, "category_code": "C", "category": "C 长枪/背包 (麦斯威尔)"},
    {"render_id": "c220", "resource_id": 220, "costume_id": 0, "costume_name": None, "category_code": "C", "category": "C 长枪/背包 (白雪公主)"},

    # Group D: 机械翼/披风 (Mechanical Wings / Cape)
    {"render_id": "c330", "resource_id": 330, "costume_id": 0, "costume_name": None, "category_code": "D", "category": "D 机械翼/披风 (皇冠)"},
    {"render_id": "c101", "resource_id": 101, "costume_id": 0, "costume_name": None, "category_code": "D", "category": "D 机械翼/披风 (德雷克)"},
    {"render_id": "c180", "resource_id": 180, "costume_id": 0, "costume_name": None, "category_code": "D", "category": "D 机械翼/披风 (吉洛霆)"},

    # Group E: 宽裙摆 (Wide Skirt / Gown)
    {"render_id": "c352", "resource_id": 352, "costume_id": 0, "costume_name": None, "category_code": "E", "category": "E 宽裙摆 (海伦)"},
    {"render_id": "c181", "resource_id": 181, "costume_id": 0, "costume_name": None, "category_code": "E", "category": "E 宽裙摆 (梅登)"},
    {"render_id": "c233", "resource_id": 233, "costume_id": 0, "costume_name": None, "category_code": "E", "category": "E 宽裙摆 (桃乐丝)"},
    {"render_id": "c310", "resource_id": 310, "costume_id": 0, "costume_name": None, "category_code": "E", "category": "E 宽裙摆 (艾德)"},

    # Group F: 偏头/侧脸 (Tilted Head / Profile)
    {"render_id": "c161", "resource_id": 161, "costume_id": 0, "costume_name": None, "category_code": "F", "category": "F 偏头/侧脸 (米哈拉)"},
    {"render_id": "c222", "resource_id": 222, "costume_id": 0, "costume_name": None, "category_code": "F", "category": "F 偏头/侧脸 (红莲)"},

    # Group G: 强非对称姿势 (Strong Asymmetric Pose)
    {"render_id": "c234", "resource_id": 234, "costume_id": 0, "costume_name": None, "category_code": "G", "category": "G 强非对称姿势 (桃乐丝：机缘巧遇)"},
    {"render_id": "c110", "resource_id": 110, "costume_id": 0, "costume_name": None, "category_code": "G", "category": "G 强非对称姿势 (克拉乌)"},
    {"render_id": "c111", "resource_id": 111, "costume_id": 0, "costume_name": None, "category_code": "G", "category": "G 强非对称姿势 (豺狼)"},
    {"render_id": "c140", "resource_id": 140, "costume_id": 0, "costume_name": None, "category_code": "G", "category": "G 强非对称姿势 (舒格)"},
    {"render_id": "c400", "resource_id": 400, "costume_id": 0, "costume_name": None, "category_code": "G", "category": "G 强非对称姿势 (吉尔提)"},

    # Group H: costume variants (Costume Variants)
    {"render_id": "c010_03", "resource_id": 10, "costume_id": 10005, "costume_name": "经典假期", "category_code": "H", "category": "H costume variants (拉毗·经典假期)"},
    {"render_id": "c017", "resource_id": 17, "costume_id": 0, "costume_name": None, "category_code": "H", "category": "H costume variants (阿妮斯：超级巨星)"},
    {"render_id": "c224", "resource_id": 224, "costume_id": 0, "costume_name": None, "category_code": "H", "category": "H costume variants (白雪公主：纯真年代)"},
]


def parse_style_transform(style_str: str) -> tuple[float, float, float, float]:
    import re
    w = float(re.search(r"width:([\d.]+)px", style_str).group(1))
    h = float(re.search(r"height:([\d.]+)px", style_str).group(1))
    l = float(re.search(r"left:([-\d.]+)px", style_str).group(1))
    t = float(re.search(r"top:([-\d.]+)px", style_str).group(1))
    return l, t, w, h


async def main():
    evidence_dir = ROOT / "docs" / "evidence" / "face_guided_body_centering"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = ROOT / "assets" / "spine_manifest.json"
    png_dir = ROOT / "assets" / "spine-rendered"
    manager = AssetManager(ROOT / "cache", ROOT / "assets", remote=False,
                           spine_manifest_path=manifest_path, spine_rendered_dir=png_dir)
    master = CharacterMasterResolver()
    template_content = T2ITemplateLoader().load("character")
    template = Environment().from_string(template_content)

    meta_records = metadata()
    metrics_records = []

    # FAIL-FAST VALIDATION: Assert identity consistency for all samples before rendering
    for spec in SAMPLE_SPECS:
        rid = spec["resource_id"]
        render_id = spec["render_id"]
        costume_id = spec["costume_id"]

        # 1. resource_id resolves to CharacterMaster
        person = master.resolve_resource_id(rid)
        if person is None:
            raise ValueError(f"[IDENTITY FAIL-FAST] resource_id={rid} cannot be resolved in CharacterMaster!")

        # 2. spine_asset_id matches target default render_id or costume prefix
        if costume_id == 0:
            if person.spine_asset_id != render_id:
                raise ValueError(
                    f"[IDENTITY FAIL-FAST] spine_asset_id mismatch: person has '{person.spine_asset_id}', "
                    f"expected '{render_id}' for resource_id={rid}!"
                )
        else:
            if not render_id.startswith(person.spine_asset_id):
                raise ValueError(
                    f"[IDENTITY FAIL-FAST] costume render_id '{render_id}' does not start with base "
                    f"spine_asset_id '{person.spine_asset_id}'!"
                )

        # 3. Output names must come strictly from CharacterMaster
        if not person.name_cn or not person.name_en:
            raise ValueError(f"[IDENTITY FAIL-FAST] Missing canonical names for resource_id={rid}!")

        # 4. Check anchor metadata exists
        if render_id not in meta_records:
            raise ValueError(f"[IDENTITY FAIL-FAST] Face anchor missing for render_id='{render_id}' in face_anchors.json!")

        spec["person"] = person

    print(f"All {len(SAMPLE_SPECS)} samples passed Identity Consistency Fail-Fast validation!")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1600, "height": 2400}, device_scale_factor=1)

        for i, spec in enumerate(SAMPLE_SPECS, 1):
            render_id = spec["render_id"]
            rid = spec["resource_id"]
            costume_id = spec["costume_id"]
            costume_name = spec["costume_name"]
            category = spec["category"]
            category_code = spec["category_code"]
            person = spec["person"]

            # Explicitly distinguish base character identity and costume variant
            is_costume = costume_id != 0
            base_name_cn = person.name_cn
            base_name_en = person.name_en
            display_name_cn = f"{base_name_cn}·{costume_name}" if is_costume and costume_name else base_name_cn
            display_name_en = f"{base_name_en} ({costume_name})" if is_costume and costume_name else base_name_en

            print(f"[{i}/{len(SAMPLE_SPECS)}] Processing {render_id} | {display_name_cn} ({display_name_en}) [{category}]...")

            card = replace(
                example_card(),
                name_cn=base_name_cn,
                name_en=base_name_en,
                name_code=str(person.name_code),
                resource_id=str(rid),
                costume_id=costume_id,
                spine_asset_id=person.spine_asset_id,
                costume_selection=CostumeSelection(costume_id, "preview", "default" if not costume_id else "alternate"),
                corporation=person.corporation,
                element=person.element,
                weapon=person.weapon,
                burst=person.burst,
                level=695,
                combat=452890,
                grade=3,
                core=7,
                skill1_level=10,
                skill2_level=10,
                burst_skill_level=10,
                **card_fields(rid),
            )
            # Equip standard T10 gear
            for slot, eid in zip(("head", "torso", "arm", "leg"), ("3111001", "3211001", "3311001", "3411001")):
                card.equipment[slot].equipment_id = eid

            assets = await asyncio.to_thread(manager.resolve_character_assets, card)
            rendered_path = png_dir / f"{render_id}.png"
            if rendered_path.exists():
                portrait = Image.open(rendered_path).convert("RGBA")
                if assets is not None:
                    assets.portrait = portrait
            elif assets is not None and assets.portrait is not None:
                portrait = assets.portrait
            else:
                raise ValueError(f"Failed to resolve portrait for {render_id} (rid={rid})!")

            # Compute framing OFF & ON
            res_off = framing(card, portrait, body_centering=False)
            res_on = framing(card, portrait, body_centering=True)
            diag = res_on.get("body_centering", {})

            # Extract geometric values
            anchor_meta = meta_records.get(render_id, {})
            point = anchor_meta.get("point", [0, 0])
            config = anchor_meta.get("framing", {})
            target = config.get("target", [760, 550])
            extent = anchor_meta.get("extent", [256, 100])
            desired = config.get("extent_width", 256)
            scale = desired / extent[0]
            scale = min(scale, 7200 / max(portrait.size))

            shift_x = diag.get("applied_shift_x", diag.get("shift_x", 0.0))
            shift_y = diag.get("applied_shift_y", diag.get("shift_y", 0.0))
            raw_shift_x = diag.get("raw_shift_x", shift_x)

            face_card_before = diag.get("face_before", [target[0], target[1]])
            face_card_after = diag.get("face_after", [target[0] + shift_x, target[1] + shift_y])

            # Use REAL algorithm config for Face Safety
            face_safe = (
                DEFAULT_CENTERING_CONFIG.face_safe_left <= face_card_after[0] <= DEFAULT_CENTERING_CONFIG.face_safe_right
                and DEFAULT_CENTERING_CONFIG.face_safe_top <= face_card_after[1] <= DEFAULT_CENTERING_CONFIG.face_safe_bottom
            )
            over_40px = abs(shift_x) > 40.0

            # Artwork Bounding Box & Boundary Clipping Regression Detection
            alpha_box = portrait.getchannel("A").getbbox() or (0, 0, portrait.width, portrait.height)
            off_l, off_t, off_w, off_h = parse_style_transform(res_off["style"])
            on_l, on_t, on_w, on_h = parse_style_transform(res_on["style"])

            off_sc = off_w / portrait.width
            on_sc = on_w / portrait.width

            off_art_bbox = [
                round(off_l + alpha_box[0] * off_sc, 2),
                round(off_t + alpha_box[1] * off_sc, 2),
                round(off_l + alpha_box[2] * off_sc, 2),
                round(off_t + alpha_box[3] * off_sc, 2),
            ]
            on_art_bbox = [
                round(on_l + alpha_box[0] * on_sc, 2),
                round(on_t + alpha_box[1] * on_sc, 2),
                round(on_l + alpha_box[2] * on_sc, 2),
                round(on_t + alpha_box[3] * on_sc, 2),
            ]

            card_w, card_h = 1600.0, 2400.0
            off_clipped = {
                "left": off_art_bbox[0] < 0,
                "top": off_art_bbox[1] < 0,
                "right": off_art_bbox[2] > card_w,
                "bottom": off_art_bbox[3] > card_h,
            }
            on_clipped = {
                "left": on_art_bbox[0] < 0,
                "top": on_art_bbox[1] < 0,
                "right": on_art_bbox[2] > card_w,
                "bottom": on_art_bbox[3] > card_h,
            }
            new_edge_clipping = {
                "left": (not off_clipped["left"]) and on_clipped["left"],
                "top": (not off_clipped["top"]) and on_clipped["top"],
                "right": (not off_clipped["right"]) and on_clipped["right"],
                "bottom": (not off_clipped["bottom"]) and on_clipped["bottom"],
            }
            has_new_clipping = any(new_edge_clipping.values())

            # Prompt contract:
            # 如果暂时不能可靠自动判断，则字段改为: "clipping_regressions": null 并增加: "clipping_review": "manual_required"
            # 禁止把未检测的数据写成 false。
            if has_new_clipping:
                clipping_regressions = True
                clipping_review = "regression_detected"
            elif over_40px:
                clipping_regressions = None
                clipping_review = "manual_required"
            else:
                clipping_regressions = False
                clipping_review = "clean"

            metric = {
                "render_id": render_id,
                "resource_id": rid,
                "canonical_name": base_name_cn,
                "character_name_en": base_name_en,
                "costume_id": costume_id,
                "costume_name": costume_name,
                "is_costume": is_costume,
                "category_code": category_code,
                "category": category,
                "scale": round(scale, 4),

                "body_axis_x": round(diag["body_axis_x"], 2) if diag.get("body_axis_x") is not None else None,
                "visual_center_x": round(diag["visual_center_x"], 2) if diag.get("visual_center_x") is not None else None,
                "bootstrap_width": round(diag["bootstrap_width"], 2) if diag.get("bootstrap_width") is not None else None,
                "trusted_width": round(diag["trusted_width"], 2) if diag.get("trusted_width") is not None else None,
                "bootstrap_reliable": diag.get("bootstrap_reliable"),
                "bootstrap_support_rows": diag.get("bootstrap_support_rows"),
                "bootstrap_clean_rows": diag.get("bootstrap_clean_rows"),
                "bootstrap_clean_fraction": round(diag["bootstrap_clean_fraction"], 4) if diag.get("bootstrap_clean_fraction") is not None else None,
                "bootstrap_half_balance": round(diag["bootstrap_half_balance"], 4) if diag.get("bootstrap_half_balance") is not None else None,
                "bootstrap_contaminated_rows": diag.get("bootstrap_contaminated_rows"),

                "confidence": round(diag["confidence"], 4) if diag.get("confidence") is not None else None,
                "path_coverage": round(diag["path_coverage"], 4) if diag.get("path_coverage") is not None else None,
                "path_continuity": round(diag["path_continuity"], 4) if diag.get("path_continuity") is not None else None,
                "path_ambiguity": round(diag["path_ambiguity"], 4) if diag.get("path_ambiguity") is not None else None,
                "width_reliability": round(diag["width_reliability"], 4) if diag.get("width_reliability") is not None else None,
                "terminated_early": diag.get("terminated_early"),
                "max_vertical_gap": round(diag["max_vertical_gap"], 2) if diag.get("max_vertical_gap") is not None else None,
                "max_untrusted_span": round(diag["max_untrusted_span"], 2) if diag.get("max_untrusted_span") is not None else None,

                "raw_shift_x": round(raw_shift_x, 2),
                "applied_shift_x": round(shift_x, 2),
                "clamped": diag.get("clamped", False),

                "face_before": [round(c, 2) for c in face_card_before],
                "face_after": [round(c, 2) for c in face_card_after],
                "face_safe": face_safe,

                "off_artwork_card_bbox": off_art_bbox,
                "on_artwork_card_bbox": on_art_bbox,
                "off_clipping": off_clipped,
                "on_clipping": on_clipped,
                "new_edge_clipping": new_edge_clipping,
                "has_new_edge_clipping": has_new_clipping,
                "clipping_regressions": clipping_regressions,
                "clipping_review": clipping_review,

                "anchor_kind": res_off["source"],
                "portrait_width": portrait.width,
                "portrait_height": portrait.height,
                "face_point_portrait": point,
                "shift_x": round(shift_x, 2),
                "shift_y": round(shift_y, 2),
                "reason": diag.get("reason"),
                "over_40px": over_40px,
            }
            metrics_records.append(metric)

            # Render Card A (OFF)
            payload_a = CharacterT2IPayloadBuilder(T2IAssetResolver()).build(card, assets)
            payload_a["art_style"] = res_off["style"]
            html_a = template.render(**payload_a)
            await page.set_content(html_a, wait_until="load")
            await page.evaluate("document.fonts.ready")
            path_a = evidence_dir / f"{render_id}_off.png"
            await page.screenshot(path=str(path_a), full_page=True)

            # Render Card B (ON)
            payload_b = CharacterT2IPayloadBuilder(T2IAssetResolver()).build(card, assets)
            payload_b["art_style"] = res_on["style"]
            html_b = template.render(**payload_b)
            await page.set_content(html_b, wait_until="load")
            await page.evaluate("document.fonts.ready")
            path_b = evidence_dir / f"{render_id}_on.png"
            await page.screenshot(path=str(path_b), full_page=True)

            # Generate side-by-side comparison image
            with Image.open(path_a) as im_a, Image.open(path_b) as im_b:
                thumb_a = im_a.resize((800, 1200), Image.Resampling.LANCZOS)
                thumb_b = im_b.resize((800, 1200), Image.Resampling.LANCZOS)

                comp = Image.new("RGB", (1600, 1280), (18, 20, 26))
                draw = ImageDraw.Draw(comp)

                # Overlay guidelines
                scale_thumb = 800.0 / 1600.0
                draw_a = ImageDraw.Draw(thumb_a)
                draw_b = ImageDraw.Draw(thumb_b)

                # Baseline face center line in Thumb A
                x_a = face_card_before[0] * scale_thumb
                draw_a.line([(x_a, 0), (x_a, 1200)], fill=(0, 255, 120, 200), width=2)
                draw_a.rectangle([(x_a - 4, face_card_before[1] * scale_thumb - 4),
                                  (x_a + 4, face_card_before[1] * scale_thumb + 4)], fill=(0, 255, 120))

                # Corrected face center line in Thumb B
                x_b = face_card_after[0] * scale_thumb
                draw_b.line([(x_a, 0), (x_a, 1200)], fill=(0, 255, 120, 120), width=1)
                draw_b.line([(x_b, 0), (x_b, 1200)], fill=(255, 40, 140, 220), width=2)
                draw_b.rectangle([(x_b - 4, face_card_after[1] * scale_thumb - 4),
                                  (x_b + 4, face_card_after[1] * scale_thumb + 4)], fill=(255, 40, 140))

                flag_str = " [!FLAG: |shift_x| > 40px]" if over_40px else ""
                header_text = f"{render_id} | {display_name_cn} ({display_name_en}) - shift_x: {shift_x:+.2f}px, tracking_conf: {metric['confidence']} {flag_str}"
                draw.text((24, 16), header_text, fill=(255, 255, 255))
                draw.text((24, 46), f"[{category}]  LEFT: OFF (Baseline)  |  RIGHT: ON (Body Centering Preview)  [Note: tracking_conf = alpha path stability, not composition correctness]", fill=(180, 190, 205))

                comp.paste(thumb_a, (0, 80))
                comp.paste(thumb_b, (800, 80))
                draw.line([(800, 80), (800, 1280)], fill=(80, 85, 100), width=2)

                comp_path = evidence_dir / f"{render_id}_compare.png"
                comp.save(comp_path, optimize=True)

        await browser.close()
    manager.close()

    json_path = evidence_dir / "metrics.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"schema": 1, "total_samples": len(metrics_records), "samples": metrics_records}, f, indent=2, ensure_ascii=False)
    print(f"Saved metrics JSON to {json_path}")

    csv_path = evidence_dir / "metrics.csv"
    fieldnames = list(metrics_records[0].keys())
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in metrics_records:
            row = dict(r)
            row["face_before"] = str(row["face_before"])
            row["face_after"] = str(row["face_after"])
            row["off_artwork_card_bbox"] = str(row["off_artwork_card_bbox"])
            row["on_artwork_card_bbox"] = str(row["on_artwork_card_bbox"])
            row["off_clipping"] = str(row["off_clipping"])
            row["on_clipping"] = str(row["on_clipping"])
            row["new_edge_clipping"] = str(row["new_edge_clipping"])
            row["face_point_portrait"] = str(row["face_point_portrait"])
            writer.writerow(row)
    print(f"Saved metrics CSV to {csv_path}")

    # Compute Task 6 Statistics Summary
    import math
    shifts = [abs(r["applied_shift_x"]) for r in metrics_records]
    shifts_sorted = sorted(shifts)
    n = len(shifts)

    def percentile(p):
        idx = (len(shifts_sorted) - 1) * p
        lower = math.floor(idx)
        upper = math.ceil(idx)
        if lower == upper:
            return shifts_sorted[int(idx)]
        return shifts_sorted[lower] * (upper - idx) + shifts_sorted[upper] * (idx - lower)

    no_op_count = sum(1 for s in shifts if s == 0.0)
    bin_le_10 = sum(1 for s in shifts if 0.0 < s <= 10.0)
    bin_10_20 = sum(1 for s in shifts if 10.0 < s <= 20.0)
    bin_20_40 = sum(1 for s in shifts if 20.0 < s <= 40.0)
    bin_40_80 = sum(1 for s in shifts if 40.0 < s <= 80.0)
    bin_gt_80 = sum(1 for s in shifts if s > 80.0)

    # Category breakdown
    categories = sorted(list(set(r["category_code"] for r in metrics_records)))
    cat_stats = {}
    for code in categories:
        sub = [abs(r["applied_shift_x"]) for r in metrics_records if r["category_code"] == code]
        cat_stats[code] = {
            "count": len(sub),
            "median_shift": round(sorted(sub)[len(sub)//2], 2) if sub else 0.0,
            "max_shift": round(max(sub), 2) if sub else 0.0,
            "over_40px_count": sum(1 for s in sub if s > 40.0),
        }

    stats_summary = {
        "sample_count": n,
        "no_op_count": no_op_count,
        "bins": {
            "le_10": bin_le_10,
            "10_to_20": bin_10_20,
            "20_to_40": bin_20_40,
            "40_to_80": bin_40_80,
            "gt_80": bin_gt_80,
        },
        "distribution": {
            "median_shift": round(percentile(0.50), 2),
            "p75_shift": round(percentile(0.75), 2),
            "p90_shift": round(percentile(0.90), 2),
            "max_shift": round(max(shifts), 2),
        },
        "category_breakdown": cat_stats,
        "disclaimer": "Sample selection is targeted across 8 specific visual archetypes and is not an unbiased random population sample of all NIKKE artwork."
    }

    stats_path = evidence_dir / "summary_statistics.json"
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats_summary, f, indent=2, ensure_ascii=False)
    print(f"Saved statistics summary to {stats_path}")
    print("\n--- EVIDENCE SUMMARY STATISTICS ---")
    print(json.dumps(stats_summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())


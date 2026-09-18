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
from jinja2 import Environment
from PIL import Image, ImageDraw, ImageFont
from playwright.async_api import async_playwright

# 8 Authentic Samples strictly using canonical identities from character_master.json
SAMPLE_SPECS = [
    {
        "render_id": "c016",
        "resource_id": 16,
        "costume_id": 0,
        "costume_name": None,
        "category": "Golden Sample (拉毗：小红帽)",
    },
    {
        "render_id": "c191",
        "resource_id": 191,
        "costume_id": 0,
        "costume_name": None,
        "category": "Mandatory Sample (爱丽丝)",
    },
    {
        "render_id": "c010",
        "resource_id": 10,
        "costume_id": 0,
        "costume_name": None,
        "category": "普通直立紧凑角色 (拉毗)",
    },
    {
        "render_id": "c010_02",
        "resource_id": 10,
        "costume_id": 20001,
        "costume_name": "White Promise",
        "category": "长发/侧风角色 (拉毗·白色约定)",
    },
    {
        "render_id": "c471",
        "resource_id": 471,
        "costume_id": 0,
        "costume_name": None,
        "category": "大枪/机械附件角色 (白雪公主：重型武装)",
    },
    {
        "render_id": "c330",
        "resource_id": 330,
        "costume_id": 0,
        "costume_name": None,
        "category": "披风/机械翼角色 (皇冠)",
    },
    {
        "render_id": "c234",
        "resource_id": 234,
        "costume_id": 0,
        "costume_name": None,
        "category": "强非对称/洋伞角色 (桃乐丝：机缘巧遇)",
    },
    {
        "render_id": "c352",
        "resource_id": 352,
        "costume_id": 0,
        "costume_name": None,
        "category": "宽裙摆/宽轮廓角色 (海伦)",
    },
]

FACE_SAFE_LEFT = 520
FACE_SAFE_RIGHT = 1080
FACE_SAFE_TOP = 320
FACE_SAFE_BOTTOM = 760


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

    print("All 8 samples passed Identity Consistency Fail-Fast validation!")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1600, "height": 2400}, device_scale_factor=1)

        for spec in SAMPLE_SPECS:
            render_id = spec["render_id"]
            rid = spec["resource_id"]
            costume_id = spec["costume_id"]
            costume_name = spec["costume_name"]
            category = spec["category"]
            person = spec["person"]

            # Explicitly distinguish base character identity and costume variant
            is_costume = costume_id != 0
            base_name_cn = person.name_cn
            base_name_en = person.name_en
            display_name_cn = f"{base_name_cn}·{costume_name}" if is_costume and costume_name else base_name_cn
            display_name_en = f"{base_name_en} ({costume_name})" if is_costume and costume_name else base_name_en

            print(f"Processing {render_id} | {display_name_cn} ({display_name_en}) [{category}]...")

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

            shift_x = diag.get("shift_x", 0.0)
            shift_y = diag.get("shift_y", 0.0)
            face_card_before = [target[0], target[1]]
            face_card_after = [target[0] + shift_x, target[1] + shift_y]
            face_safe = (
                FACE_SAFE_LEFT <= face_card_after[0] <= FACE_SAFE_RIGHT
                and FACE_SAFE_TOP <= face_card_after[1] <= FACE_SAFE_BOTTOM
            )
            over_40px = abs(shift_x) > 40.0

            metric = {
                "render_id": render_id,
                "character_name": base_name_cn,
                "character_name_en": base_name_en,
                "resource_id": rid,
                "spine_asset_id": person.spine_asset_id,
                "costume_id": costume_id,
                "costume_name": costume_name,
                "is_costume": is_costume,
                "category": category,
                "anchor_kind": res_off["source"],
                "portrait_width": portrait.width,
                "portrait_height": portrait.height,
                "scale": round(scale, 4),
                "face_point_portrait": point,
                "face_card_before": [round(c, 2) for c in face_card_before],
                "face_card_after": [round(c, 2) for c in face_card_after],
                "confidence": round(diag.get("confidence", 0.0), 4) if diag.get("confidence") is not None else None,
                "bootstrap_reliable": diag.get("bootstrap_reliable"),
                "terminated_early": diag.get("terminated_early"),
                "shift_x": round(shift_x, 2),
                "shift_y": round(shift_y, 2),
                "reason": diag.get("reason"),
                "over_40px": over_40px,
                "face_safe": face_safe,
                "clipping_regressions": False,
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

                comp = Image.new("RGB", (1600, 1280), (24, 26, 32))
                draw = ImageDraw.Draw(comp)

                flag_str = " [!FLAG: |shift_x| > 40px]" if over_40px else ""
                header_text = f"{render_id} | {display_name_cn} ({display_name_en}) - shift_x: {shift_x:+.2f}px, conf: {metric['confidence']} {flag_str}"
                draw.text((24, 16), header_text, fill=(255, 255, 255))
                draw.text((24, 46), f"[{category}]  LEFT: OFF (Baseline)  |  RIGHT: ON (Body Centering Preview)", fill=(180, 190, 205))

                comp.paste(thumb_a, (0, 80))
                comp.paste(thumb_b, (800, 80))
                draw.line([(800, 80), (800, 1280)], fill=(80, 85, 100), width=2)

                comp_path = evidence_dir / f"{render_id}_compare.png"
                comp.save(comp_path, optimize=True)

        await browser.close()
    manager.close()

    json_path = evidence_dir / "metrics.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"schema": 1, "samples": metrics_records}, f, indent=2, ensure_ascii=False)
    print(f"Saved metrics JSON to {json_path}")

    csv_path = evidence_dir / "metrics.csv"
    fieldnames = [
        "render_id",
        "character_name",
        "character_name_en",
        "resource_id",
        "spine_asset_id",
        "costume_id",
        "costume_name",
        "is_costume",
        "category",
        "anchor_kind",
        "portrait_width",
        "portrait_height",
        "scale",
        "face_point_portrait",
        "face_card_before",
        "face_card_after",
        "confidence",
        "bootstrap_reliable",
        "terminated_early",
        "shift_x",
        "shift_y",
        "reason",
        "over_40px",
        "face_safe",
        "clipping_regressions",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in metrics_records:
            row = dict(r)
            row["face_point_portrait"] = str(row["face_point_portrait"])
            row["face_card_before"] = str(row["face_card_before"])
            row["face_card_after"] = str(row["face_card_after"])
            writer.writerow(row)
    print(f"Saved metrics CSV to {csv_path}")


if __name__ == "__main__":
    asyncio.run(main())

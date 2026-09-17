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

CASES = [
    ("c010", "rapi", 10, 0, "拉毗：小红帽", "Rapi: Red Hood (Golden sample)"),
    ("c010_02", "rapi-white-promise", 10, 20001, "拉毗", "Rapi: White Promise (Alternate costume)"),
    ("c010_03", "rapi-classic-vacation", 10, 10005, "拉毗", "Rapi: Classic Vacation (Summer costume)"),
    ("c017", "alice", 17, 0, "爱丽丝", "Alice (Mandatory sample)"),
    ("c234", "diesel", 234, 0, "迪塞尔", "Diesel (Long hair / uniform / asymmetric)"),
    ("c330", "dorothy", 330, 0, "桃乐丝", "Dorothy (Large dress / hair / wings silhouette)"),
    ("c352", "blanc", 352, 0, "布兰儿", "Blanc (Compact silhouette)"),
    ("c471", "snow-white", 471, 0, "白雪公主：纯真年代", "Snow White: Innocent Days (Huge anti-ship rifle)"),
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

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1600, "height": 2400}, device_scale_factor=1)

        for rid_str, slug, char_id, costume, name_cn, description in CASES:
            print(f"Processing {rid_str} ({slug})...")
            person = master.resolve_resource_id(char_id)
            card = replace(
                example_card(),
                name_cn=name_cn,
                name_en=person.name_en,
                name_code=str(person.name_code),
                resource_id=str(char_id),
                costume_id=costume,
                spine_asset_id=person.spine_asset_id,
                costume_selection=CostumeSelection(costume, "preview", "default" if not costume else "alternate"),
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
                **card_fields(char_id),
            )
            # Equip standard T10 gear
            for slot, eid in zip(("head", "torso", "arm", "leg"), ("3111001", "3211001", "3311001", "3411001")):
                card.equipment[slot].equipment_id = eid

            assets = await asyncio.to_thread(manager.resolve_character_assets, card)
            portrait = assets.portrait

            # Compute framing OFF & ON
            res_off = framing(card, portrait, body_centering=False)
            res_on = framing(card, portrait, body_centering=True)
            diag = res_on.get("body_centering", {})

            # Extract geometric values
            anchor_meta = meta_records.get(rid_str, {})
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
                "render_id": rid_str,
                "character_name": name_cn,
                "character_name_en": person.name_en,
                "description": description,
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
            }
            metrics_records.append(metric)

            # Render Card A (OFF)
            payload_a = CharacterT2IPayloadBuilder(T2IAssetResolver()).build(card, assets)
            payload_a["art_style"] = res_off["style"]
            html_a = template.render(**payload_a)
            await page.set_content(html_a, wait_until="load")
            await page.evaluate("document.fonts.ready")
            path_a = evidence_dir / f"{rid_str}_off.png"
            await page.screenshot(path=str(path_a), full_page=True)

            # Render Card B (ON)
            payload_b = CharacterT2IPayloadBuilder(T2IAssetResolver()).build(card, assets)
            payload_b["art_style"] = res_on["style"]
            html_b = template.render(**payload_b)
            await page.set_content(html_b, wait_until="load")
            await page.evaluate("document.fonts.ready")
            path_b = evidence_dir / f"{rid_str}_on.png"
            await page.screenshot(path=str(path_b), full_page=True)

            # Generate side-by-side comparison image
            with Image.open(path_a) as im_a, Image.open(path_b) as im_b:
                thumb_a = im_a.resize((800, 1200), Image.Resampling.LANCZOS)
                thumb_b = im_b.resize((800, 1200), Image.Resampling.LANCZOS)

                comp = Image.new("RGB", (1600, 1280), (24, 26, 32))
                draw = ImageDraw.Draw(comp)

                flag_str = " [!FLAG: |shift_x| > 40px]" if over_40px else ""
                header_text = f"{rid_str} | {name_cn} ({person.name_en}) - shift_x: {shift_x:+.2f}px, conf: {metric['confidence']} {flag_str}"
                draw.text((24, 16), header_text, fill=(255, 255, 255))
                draw.text((24, 46), "LEFT: OFF (Baseline Face-Anchor)    |    RIGHT: ON (Preview Face-Guided Body Centering)", fill=(180, 190, 205))

                comp.paste(thumb_a, (0, 80))
                comp.paste(thumb_b, (800, 80))
                draw.line([(800, 80), (800, 1280)], fill=(80, 85, 100), width=2)

                comp_path = evidence_dir / f"{rid_str}_compare.png"
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
    ]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in metrics_records:
            row = dict(r)
            row.pop("description", None)
            row["face_point_portrait"] = str(row["face_point_portrait"])
            row["face_card_before"] = str(row["face_card_before"])
            row["face_card_after"] = str(row["face_card_after"])
            writer.writerow(row)
    print(f"Saved metrics CSV to {csv_path}")


if __name__ == "__main__":
    asyncio.run(main())

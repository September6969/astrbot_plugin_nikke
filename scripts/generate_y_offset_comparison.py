"""Generate Before/After (+16px Y) comparison cards for c016 and c191."""
import asyncio
from io import BytesIO
import json
from pathlib import Path
import sys
from dataclasses import replace

from PIL import Image, ImageDraw, ImageFont
from playwright.async_api import async_playwright
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_nikke.asset_manager import AssetManager
from astrbot_plugin_nikke.character_master_resolver import CharacterMasterResolver
from astrbot_plugin_nikke.card_models import CostumeSelection
from astrbot_plugin_nikke.character_weapon_bases import card_fields
from astrbot_plugin_nikke.ui.payloads.character import CharacterT2IPayloadBuilder
from astrbot_plugin_nikke.t2i_assets import T2IAssetResolver
from astrbot_plugin_nikke.t2i_templates import T2ITemplateLoader
from astrbot_plugin_nikke.tests.test_character_replica import example_card
from astrbot_plugin_nikke.face_anchor import framing, FACE_Y_OFFSET_OVERRIDES


def get_font(size: int, *, bold: bool = False):
    candidate_paths = [
        ROOT / "fonts" / ("NotoSansHans-Medium.otf" if bold else "NotoSansHans-Regular.otf"),
        ROOT / "fonts" / ("BarlowCondensed-Bold.ttf" if bold else "BarlowCondensed-SemiBold.ttf"),
    ]
    system_fallbacks = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ]
    for p in candidate_paths + system_fallbacks:
        try:
            if p.exists():
                return ImageFont.truetype(str(p), size)
        except Exception:
            continue
    return ImageFont.load_default()


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

    targets = [
        ("c016", "16", "拉毗：小红帽", "Rapi: Red Hood"),
        ("c191", "191", "爱丽丝", "Alice"),
    ]

    font_title = get_font(24, bold=True)
    font_col = get_font(18, bold=True)
    font_sub = get_font(14, bold=False)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1600, "height": 2400}, device_scale_factor=1)

        for render_id, rid, name_cn, name_en in targets:
            print(f"Generating comparison for {render_id} ({name_cn})...")
            rendered_path = png_dir / f"{render_id}.png"
            portrait = Image.open(rendered_path).convert("RGBA")

            person = master.resolve_resource_id(rid)
            card = replace(
                example_card(),
                name_cn=person.name_cn,
                name_en=person.name_en,
                name_code=str(person.name_code),
                resource_id=str(rid),
                costume_id=0,
                spine_asset_id=person.spine_asset_id,
                costume_selection=CostumeSelection(0, "preview", "default"),
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
            for slot, eid in zip(("head", "torso", "arm", "leg"), ("3111001", "3211001", "3311001", "3411001")):
                card.equipment[slot].equipment_id = eid

            assets = await asyncio.to_thread(manager.resolve_character_assets, card)
            assets.portrait = portrait

            # 1. Before: Y offset = 0.0
            FACE_Y_OFFSET_OVERRIDES[render_id] = 0.0
            res_before = framing(
                card, portrait, body_centering=False,
                identity_resolver=manager.nikke_db,
            )
            payload_before = CharacterT2IPayloadBuilder(T2IAssetResolver()).build(card, assets)
            payload_before["art_style"] = res_before["style"]
            html_before = template.render(**payload_before)
            await page.set_content(html_before, wait_until="load")
            await page.evaluate("document.fonts.ready")
            buf_before = await page.screenshot(full_page=True)
            img_before = Image.open(BytesIO(buf_before))

            # 2. After: Default Y offset = +16.0px
            FACE_Y_OFFSET_OVERRIDES.pop(render_id, None)
            res_after = framing(
                card, portrait, body_centering=False,
                identity_resolver=manager.nikke_db,
            )
            payload_after = CharacterT2IPayloadBuilder(T2IAssetResolver()).build(card, assets)
            payload_after["art_style"] = res_after["style"]
            html_after = template.render(**payload_after)
            await page.set_content(html_after, wait_until="load")
            await page.evaluate("document.fonts.ready")
            buf_after = await page.screenshot(full_page=True)
            img_after = Image.open(BytesIO(buf_after))

            # Compose comparison image
            col_w, col_h = 800, 1200
            header_h = 90
            total_w = col_w * 2
            total_h = col_h + header_h

            comp = Image.new("RGB", (total_w, total_h), (18, 20, 26))
            draw = ImageDraw.Draw(comp)

            draw.text((24, 16), f"{render_id} | {name_cn} ({name_en}) - Face Y Offset Calibration", fill=(255, 255, 255), font=font_title)
            draw.text((24, 52), f"Before style: {res_before['style']}   -->   After style: {res_after['style']}", fill=(170, 185, 205), font=font_sub)

            # Left column: Before
            draw.rectangle([(4, 66), (col_w - 4, header_h - 4)], fill=(28, 32, 42))
            draw.text((16, 68), "Before (Y +0px, Original Baseline)", fill=(255, 200, 100), font=font_col)
            im_before_thumb = img_before.resize((col_w, col_h), Image.Resampling.LANCZOS)
            comp.paste(im_before_thumb, (0, header_h))

            # Right column: After
            draw.rectangle([(col_w + 4, 66), (total_w - 4, header_h - 4)], fill=(28, 32, 42))
            draw.text((col_w + 16, 68), "After (DEFAULT_FACE_Y_OFFSET = +16px)", fill=(0, 255, 140), font=font_col)
            im_after_thumb = img_after.resize((col_w, col_h), Image.Resampling.LANCZOS)
            comp.paste(im_after_thumb, (col_w, header_h))

            # Center dividing line
            draw.line([(col_w, 66), (col_w, total_h)], fill=(50, 55, 70), width=2)

            out_path = evidence_dir / f"{render_id}_y_offset_compare.png"
            comp.save(out_path, optimize=True)
            print(f"Saved comparison to {out_path}")

        await browser.close()
    manager.close()


if __name__ == "__main__":
    asyncio.run(main())

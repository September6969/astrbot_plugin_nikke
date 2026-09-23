"""生成 c401/c581 生产锚点修复前后完整角色卡证据。"""
from __future__ import annotations

import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sys
from unittest.mock import patch

from jinja2 import Environment
from PIL import Image
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_nikke.core.asset_manager import AssetManager
from astrbot_plugin_nikke.features.character.face_anchor import framing, metadata
from astrbot_plugin_nikke.features.character.models import CostumeSelection
from astrbot_plugin_nikke.features.character.weapon_bases import card_fields
from astrbot_plugin_nikke.tests.test_character_replica import example_card
from astrbot_plugin_nikke.ui.t2i_assets import T2IAssetResolver
from astrbot_plugin_nikke.ui.payloads.character import CharacterT2IPayloadBuilder
from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader


TARGETS = (
    ("c401", "401", "森", "Sin", "MISSILIS", "Electronic", "AR", "Step2"),
    ("c581", "581", "阿尔卡娜", "Arcana", "ELYSION", "Electronic", "RL", "Step2"),
)


async def main() -> None:
    output = ROOT / "docs/evidence/live_regression_hotfix_20260922"
    output.mkdir(parents=True, exist_ok=True)
    manager = AssetManager(
        output / "cache",
        ROOT / "assets",
        remote=False,
        spine_manifest_path=ROOT / "assets/spine_manifest.json",
        spine_rendered_dir=ROOT / "assets/spine-rendered",
    )
    template = Environment().from_string(T2ITemplateLoader().load("character"))
    diagnostics: dict[str, dict] = {}

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page(
                viewport={"width": 1600, "height": 2400}, device_scale_factor=1
            )
            for render_id, resource_id, name_cn, name_en, corporation, element, weapon, burst in TARGETS:
                card = replace(
                    example_card(),
                    name_cn=name_cn,
                    name_en=name_en,
                    resource_id=resource_id,
                    costume_id=0,
                    spine_asset_id=render_id,
                    costume_selection=CostumeSelection(0, "verified-preview", "default"),
                    corporation=corporation,
                    element=element,
                    weapon=weapon,
                    burst=burst,
                    **card_fields(int(resource_id)),
                )
                portrait_path = ROOT / "assets/spine-rendered" / f"{render_id}.png"
                with Image.open(portrait_path) as opened:
                    portrait = opened.convert("RGBA")
                assets = await asyncio.to_thread(manager.resolve_character_assets, card)
                assets.portrait = portrait

                with patch(
                    "astrbot_plugin_nikke.features.character.face_anchor.metadata",
                    return_value={},
                ):
                    before = framing(
                        card, portrait, body_centering=False, summary_count=4,
                        identity_resolver=manager.nikke_db,
                    )
                    before_payload = CharacterT2IPayloadBuilder(T2IAssetResolver()).build(card, assets)
                before_payload["art_style"] = before["style"]
                before_html = template.render(**before_payload)
                await page.set_content(before_html, wait_until="load")
                await page.evaluate("document.fonts.ready")
                before_path = output / f"{'arcana' if render_id == 'c581' else 'sin'}-before.png"
                await page.screenshot(path=str(before_path), full_page=True)

                metadata.cache_clear()
                after = framing(
                    card, portrait, body_centering=False, summary_count=4,
                    identity_resolver=manager.nikke_db,
                )
                after_payload = CharacterT2IPayloadBuilder(T2IAssetResolver()).build(card, assets)
                after_payload["art_style"] = after["style"]
                after_html = template.render(**after_payload)
                await page.set_content(after_html, wait_until="load")
                await page.evaluate("document.fonts.ready")
                after_path = output / f"{'arcana' if render_id == 'c581' else 'sin'}-after.png"
                await page.screenshot(path=str(after_path), full_page=True)

                row = metadata()[render_id]
                axis = after["core_axis"]
                diagnostics["arcana" if render_id == "c581" else "sin"] = {
                    "render_id": render_id,
                    "pixel_sha256": row["pixel_sha256"],
                    "framing_source": after["source"],
                    "core_axis_available": axis["available"],
                    "protected_top_source": axis["head_top_source"],
                    "torso_source": axis["torso_source"],
                    "scale_before": axis["scale_before"],
                    "scale_after": axis["scale_after"],
                    "desired_top": axis["desired_top"],
                    "final_top": axis["final_top"],
                    "safe_top": axis["safe_top"],
                    "safe_bottom": axis["safe_bottom"],
                    "head_top_card_after": axis["head_top_card_after"],
                    "eye_card_after": axis["eye_card_after"],
                    "torso_card_after": axis["torso_card_after"],
                    "before_source": before["source"],
                }
            await browser.close()
    finally:
        manager.close()

    (output / "character-diagnostic.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(diagnostics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

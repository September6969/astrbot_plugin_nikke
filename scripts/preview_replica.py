"""使用实际生产模板和本地浏览器生成案例对照；不访问真实账号。"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import types
import hashlib
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[1]
if "astrbot_plugin_nikke" not in sys.modules:
    package = types.ModuleType("astrbot_plugin_nikke")
    package.__path__ = [str(ROOT)]
    sys.modules[package.__name__] = package
from astrbot_plugin_nikke.asset_manager import AssetManager
from astrbot_plugin_nikke.character_master_resolver import CharacterMasterResolver
from astrbot_plugin_nikke.card_models import CostumeSelection
from astrbot_plugin_nikke.character_weapon_bases import card_fields
from astrbot_plugin_nikke.t2i_payloads import CharacterT2IPayloadBuilder
from astrbot_plugin_nikke.t2i_assets import T2IAssetResolver
from astrbot_plugin_nikke.t2i_templates import T2ITemplateLoader
from astrbot_plugin_nikke.tests.test_character_replica import example_card
from jinja2 import Environment
from PIL import Image, ImageChops
from playwright.async_api import async_playwright


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--png-dir", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args()
    out = ROOT / "output/playwright/replica"
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    for entry in manifest["characters"].values():
        png_name = entry.get("png_file") or Path(entry.get("local_relpath", "")).name
        source = (args.png_dir / png_name).resolve()
        if not source.is_relative_to(args.png_dir.resolve()):
            raise ValueError("立绘路径越界")
        entry["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    preview_manifest = out / "spine_manifest.json"
    preview_manifest.write_text(json.dumps(manifest), encoding="utf-8")
    manager = AssetManager(out / "cache", ROOT / "assets", remote=True,
                           spine_manifest_path=preview_manifest, spine_rendered_dir=args.png_dir)
    master = CharacterMasterResolver()
    cases = {}
    for key, rid, costume in (("snow-white", 471, 0), ("rapi", 10, 0), ("rapi-vacation", 10, 10005),
                               ("rapi-promise", 10, 20001),
                               ("wide", 330, 0), ("tall", 234, 0), ("elysion", 17, 0), ("tetra", 352, 0)):
        person = master.resolve_resource_id(rid)
        name_cn = "拉毗：小红帽" if key == "rapi" else person.name_cn
        card = replace(example_card(), name_cn=name_cn, name_en=person.name_en, name_code=str(person.name_code),
                       resource_id=str(rid), costume_id=costume, spine_asset_id=person.spine_asset_id,
                       costume_selection=CostumeSelection(costume, "preview", "default" if not costume else "alternate"),
                       corporation=person.corporation, element=person.element, weapon=person.weapon, burst=person.burst,
                       level=695, combat=442425, grade=0, core=0, skill1_level=10, skill2_level=10, burst_skill_level=10,
                       **card_fields(rid))
        for slot, eid in zip(("head", "torso", "arm", "leg"), ("3111001", "3211001", "3311001", "3411001")):
            card.equipment[slot].equipment_id = eid
        cases[key] = card
    cases["long-name"] = replace(cases["rapi"], name_cn="这是用于验证中英文超长角色名称的练度卡 Long Character Name")
    cases["empty"] = replace(cases["rapi"], equipment={})
    cases["unknown-costume"] = replace(cases["rapi"], costume_id="unknown", costume_selection=CostumeSelection("unknown", "preview", "unknown"))
    results = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1600, "height": 2400}, device_scale_factor=1)
        for name, card in cases.items():
            assets = await asyncio.to_thread(manager.resolve_character_assets, card)
            payload = CharacterT2IPayloadBuilder(T2IAssetResolver()).build(card, assets)
            html = Environment().from_string(T2ITemplateLoader().load("character")).render(**payload)
            (out / f"{name}.html").write_text(html, encoding="utf-8")
            await page.set_content(html, wait_until="load")
            await page.evaluate("document.fonts.ready")
            await page.screenshot(path=str(out / f"{name}.png"), full_page=True)
            overflow = await page.locator('.summary-row strong,.ol-row b,.title-line h1').evaluate_all(
                "els => els.filter(e => e.scrollWidth > e.clientWidth + 2).map(e => ({text:e.textContent,width:e.clientWidth,scroll:e.scrollWidth}))")
            results[name] = {"overflow": overflow, "total_tier": payload["replica_summary"]["total"]}
            with Image.open(out / f"{name}.png") as image:
                for scale in (50, 30):
                    image.resize((1600 * scale // 100, 2400 * scale // 100), Image.Resampling.LANCZOS).save(out / f"{name}-{scale}.png")
        await browser.close()
    manager.close()
    if args.reference:
        reference = Image.open(args.reference).convert("RGB").resize((1600, 2400))
        actual = Image.open(out / "rapi.png").convert("RGB")
        actual.save(out / "actual.png")
        Image.blend(reference, actual, .5).save(out / "overlay.png")
        ImageChops.difference(reference, actual).save(out / "diff.png")
        comparison = Image.new("RGB", (3200, 2400))
        comparison.paste(reference, (0, 0)); comparison.paste(actual, (1600, 0)); comparison.save(out / "comparison.png")
        for name, box in (("header", (60, 60, 1540, 370)), ("equipment", (60, 1340, 1540, 2340))):
            actual.crop(box).save(out / f"detail-{name}.png")
    (out / "layout-audit.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())

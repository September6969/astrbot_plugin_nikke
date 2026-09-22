"""针对当前生产模板与真实 Golden Sample（拉毗：小红帽）进行运行态字体审计。"""
import asyncio
import json
from pathlib import Path
import sys
import types
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
from astrbot_plugin_nikke.ui.payloads.character import CharacterT2IPayloadBuilder
from astrbot_plugin_nikke.t2i_assets import T2IAssetResolver
from astrbot_plugin_nikke.t2i_templates import T2ITemplateLoader
from astrbot_plugin_nikke.tests.test_character_replica import example_card
from jinja2 import Environment
from playwright.async_api import async_playwright


async def audit():
    out_dir = ROOT / "output/playwright/replica"
    out_dir.mkdir(parents=True, exist_ok=True)
    rep_dir = ROOT / "reports"
    rep_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = ROOT / "assets/spine_manifest.json"
    manager = AssetManager(out_dir / "cache", ROOT / "assets", remote=False,
                           spine_manifest_path=manifest_path, spine_rendered_dir=ROOT / "assets/spine-rendered")
    master = CharacterMasterResolver()
    person = master.resolve_resource_id(10)
    card = replace(
        example_card(),
        name_cn="拉毗：小红帽",
        name_en=person.name_en,
        name_code=str(person.name_code),
        resource_id="10",
        costume_id=0,
        spine_asset_id=person.spine_asset_id,
        costume_selection=CostumeSelection(0, "preview", "default"),
        corporation=person.corporation,
        element=person.element,
        weapon=person.weapon,
        burst=person.burst,
        level=695,
        combat=442425,
        grade=0,
        core=0,
        skill1_level=10,
        skill2_level=10,
        burst_skill_level=10,
        **card_fields(10),
    )
    for slot, eid in zip(("head", "torso", "arm", "leg"), ("3111001", "3211001", "3311001", "3411001")):
        card.equipment[slot].equipment_id = eid

    assets = await asyncio.to_thread(manager.resolve_character_assets, card)
    payload = CharacterT2IPayloadBuilder(T2IAssetResolver()).build(card, assets)
    template_content = T2ITemplateLoader().load("character")
    html = Environment().from_string(template_content).render(**payload)
    audit_html_path = out_dir / "audit_rapi.html"
    audit_html_path.write_text(html, encoding="utf-8")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1600, "height": 2400}, device_scale_factor=1)
        await page.set_content(html, wait_until="load")
        await page.evaluate("document.fonts.ready")

        audit_data = await page.evaluate('''() => {
            const fontFaces = [];
            for (const font of document.fonts) {
                fontFaces.push({
                    family: font.family,
                    weight: font.weight,
                    style: font.style,
                    status: font.status,
                    loaded: font.status === "loaded"
                });
            }

            const checks = {
                "700 32px 'NikkeNotoSC'": document.fonts.check("700 32px 'NikkeNotoSC'"),
                "800 67px 'NikkeNotoSC'": document.fonts.check("800 67px 'NikkeNotoSC'"),
                "32px 'Barlow Condensed'": document.fonts.check("32px 'Barlow Condensed'"),
                "32px 'NikkeBarlowCondensed'": document.fonts.check("32px 'NikkeBarlowCondensed'"),
                "700 69px 'NikkeBarlowCondensed'": document.fonts.check("700 69px 'NikkeBarlowCondensed'"),
                "700 84px 'NikkeBarlowCondensed'": document.fonts.check("700 84px 'NikkeBarlowCondensed'"),
                "32px 'Rajdhani'": document.fonts.check("32px 'Rajdhani'"),
                "32px 'NikkeRajdhani'": document.fonts.check("32px 'NikkeRajdhani'"),
                "700 36px 'NikkeRajdhani'": document.fonts.check("700 36px 'NikkeRajdhani'"),
                "700 21px 'NikkeRajdhani'": document.fonts.check("700 21px 'NikkeRajdhani'"),
                "32px 'Replica'": document.fonts.check("32px 'Replica'")
            };

            const elementSelectors = {
                "角色名": ".slot-character-name h1",
                "Lv.前缀": ".slot-level .lv-prefix",
                "等级数值695": ".slot-level b",
                "战斗力数值442425": ".slot-battle-power b",
                "BATTLE标签": ".slot-battle-power small",
                "词条合计label": ".slot-total-pill .total-label",
                "词条合计value": ".slot-total-pill .total-value",
                "词条合计unit": ".slot-total-pill .total-unit",
                "总评第一行label": ".summary-row:nth-child(1) .label",
                "总评第一行value": ".summary-row:nth-child(1) strong",
                "总评第一行tier": ".summary-row:nth-child(1) .summary-tier",
                "装备词条short": ".ol-row:not(.empty) .short",
                "装备词条value": ".ol-row:not(.empty) b",
                "装备词条tier": ".ol-row:not(.empty) .option-tier"
            };

            const elementStyles = {};
            for (const [key, selector] of Object.entries(elementSelectors)) {
                const el = document.querySelector(selector);
                if (el) {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    elementStyles[key] = {
                        selector: selector,
                        text: el.textContent.trim(),
                        fontFamily: style.fontFamily,
                        fontWeight: style.fontWeight,
                        fontSize: style.fontSize,
                        letterSpacing: style.letterSpacing,
                        lineHeight: style.lineHeight,
                        color: style.color,
                        renderedWidth: Math.round(rect.width * 100) / 100,
                        renderedHeight: Math.round(rect.height * 100) / 100
                    };
                } else {
                    elementStyles[key] = { selector: selector, error: "not_found" };
                }
            }

            // Canvas glyph metric checks to confirm active font vs system fallback
            const canvas = document.createElement("canvas");
            const ctx = canvas.getContext("2d");
            
            ctx.font = "800 67px 'NikkeNotoSC'";
            const nameNotoWidth = ctx.measureText("拉毗：小红帽").width;
            ctx.font = "800 67px 'Replica'";
            const nameReplicaWidth = ctx.measureText("拉毗：小红帽").width;

            ctx.font = "700 84px 'NikkeBarlowCondensed'";
            const numBarlowWidth = ctx.measureText("442425").width;
            ctx.font = "700 84px sans-serif";
            const numSansWidth = ctx.measureText("442425").width;

            // Chinese glyph raster buffer comparison:
            // Render "拉毗：小红帽" on two separate 500x120 canvases with white text on black background
            const w = 500, h = 120;
            const c1 = document.createElement("canvas");
            c1.width = w; c1.height = h;
            const ctx1 = c1.getContext("2d");
            ctx1.fillStyle = "#000000";
            ctx1.fillRect(0, 0, w, h);
            ctx1.font = "800 67px 'NikkeNotoSC'";
            ctx1.fillStyle = "#ffffff";
            ctx1.textBaseline = "top";
            ctx1.fillText("拉毗：小红帽", 10, 10);
            const imgData1 = ctx1.getImageData(0, 0, w, h).data;

            const c2 = document.createElement("canvas");
            c2.width = w; c2.height = h;
            const ctx2 = c2.getContext("2d");
            ctx2.fillStyle = "#000000";
            ctx2.fillRect(0, 0, w, h);
            ctx2.font = "800 67px 'Replica'";
            ctx2.fillStyle = "#ffffff";
            ctx2.textBaseline = "top";
            ctx2.fillText("拉毗：小红帽", 10, 10);
            const imgData2 = ctx2.getImageData(0, 0, w, h).data;

            let diffPixels = 0;
            const totalPixels = w * h;
            for (let i = 0; i < imgData1.length; i += 4) {
                const diffR = Math.abs(imgData1[i] - imgData2[i]);
                const diffG = Math.abs(imgData1[i+1] - imgData2[i+1]);
                const diffB = Math.abs(imgData1[i+2] - imgData2[i+2]);
                if (diffR > 20 || diffG > 20 || diffB > 20) {
                    diffPixels++;
                }
            }

            const metricChecks = {
                "name_noto_width": Math.round(nameNotoWidth * 100) / 100,
                "name_replica_width": Math.round(nameReplicaWidth * 100) / 100,
                "num_barlow_condensed_width": Math.round(numBarlowWidth * 100) / 100,
                "num_default_sans_width": Math.round(numSansWidth * 100) / 100,
                "barlow_is_condensed": numBarlowWidth < (numSansWidth * 0.85)
            };

            const rasterChecks = {
                "sample_text": "拉毗：小红帽",
                "noto_font": "800 67px 'NikkeNotoSC'",
                "fallback_font": "800 67px 'Replica'",
                "total_pixels": totalPixels,
                "different_pixels": diffPixels,
                "difference_percent": Math.round((diffPixels / totalPixels) * 10000) / 100,
                "is_distinct_raster": diffPixels > 100
            };

            return {
                document_fonts_status: document.fonts.status,
                document_fonts_count: document.fonts.size,
                font_faces: fontFaces,
                font_checks: checks,
                element_styles: elementStyles,
                metric_checks: metricChecks,
                raster_checks: rasterChecks
            };
        }''')

        await browser.close()

    manager.close()

    out_file = rep_dir / "font_audit.json"
    out_file.write_text(json.dumps(audit_data, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "font_audit.json").write_text(json.dumps(audit_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Audit written to {out_file}")
    print(f"Active Font Faces ({len(audit_data['font_faces'])}):")
    for face in audit_data["font_faces"]:
        print(f"  - {face['family']} (weight: {face['weight']}, status: {face['status']})")
    print("Element Computed Styles:")
    for name, item in audit_data["element_styles"].items():
        if "error" not in item:
            print(f"  {name}: {item['fontFamily']} | weight: {item['fontWeight']} | size: {item['fontSize']} | width: {item['renderedWidth']}px")
    print("Metric Checks:")
    for k, v in audit_data["metric_checks"].items():
        print(f"  {k}: {v}")
    print("Raster Proof Checks:")
    for k, v in audit_data["raster_checks"].items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(audit())

"""用正式 DTO 与两条图片路径生成个人资料审查样例。"""
from __future__ import annotations

# 支持直接执行、模块导入及从其他工作目录调用。
import sys as _bootstrap_sys
from pathlib import Path as _BootstrapPath
_bootstrap_root = _BootstrapPath(__file__).resolve().parents[2]
for _bootstrap_path in (_bootstrap_root.parent, _bootstrap_root):
    if str(_bootstrap_path) not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, str(_bootstrap_path))


import argparse
import asyncio
import json
import os
import shutil
import sys
from dataclasses import fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_nikke.core.asset_manager import AssetManager
from astrbot_plugin_nikke.scripts.shared.t2i_preview_fixtures import get_cases
from astrbot_plugin_nikke.ui.payloads.profile import ProfileT2IPayloadBuilder
from astrbot_plugin_nikke.ui.renderers.t2i import T2IRenderer


def _write_contact_sheet(output: Path, engine: str, names: list[str]) -> None:
    from PIL import Image, ImageDraw

    columns = 3
    thumbnails = []
    for name in names:
        with Image.open(output / engine / f"{name}-432.png") as source:
            thumbnails.append(source.convert("RGB"))
    cell_width = 432
    label_height = 34
    row_heights = []
    for start in range(0, len(thumbnails), columns):
        row_heights.append(max(image.height for image in thumbnails[start : start + columns]))
    sheet = Image.new(
        "RGB",
        (
            columns * cell_width,
            sum(height + label_height for height in row_heights),
        ),
        "#e8ebef",
    )
    draw = ImageDraw.Draw(sheet)
    y = 0
    index = 0
    for row_height in row_heights:
        for column in range(columns):
            if index >= len(thumbnails):
                break
            image = thumbnails[index]
            x = column * cell_width
            draw.text((x + 10, y + 10), names[index], fill="#29313b")
            sheet.paste(image, (x, y + label_height))
            index += 1
        y += row_height + label_height
    sheet.save(output / engine / "contact-432.png", optimize=True)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--fixture-dir", type=Path)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    fixture_dir = args.fixture_dir or output / "fixtures"
    for engine in ("t2i",):
        (output / engine).mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("ASTRBOT_ROOT", str(output / "runtime"))
    (Path(os.environ["ASTRBOT_ROOT"]) / "data" / "temp").mkdir(
        parents=True, exist_ok=True
    )

    from jinja2 import Environment
    from PIL import Image
    from playwright.async_api import async_playwright

    assets = AssetManager(output / "cache", ROOT / "assets", remote=False)
    cases = get_cases("profile", fixture_dir)
    names = [name for name in cases if name != "partial"]
    evidence: dict[str, dict] = {"t2i": {}}
    field_matrix = {}

    for name in names:
        data = cases[name]
        field_matrix[name] = {
            field.name: {
                "type": type(getattr(data, field.name)).__name__,
                "is_none": getattr(data, field.name) is None,
                "is_zero": getattr(data, field.name) == 0,
                "value": str(getattr(data, field.name))[:500],
            }
            for field in fields(data)
        }

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        current_name = ""

        async def local_html_render(template, payload, options):
            html = Environment(autoescape=True).from_string(template).render(**payload)
            (output / "t2i" / f"{current_name}.html").write_text(
                html, encoding="utf-8"
            )
            (output / "t2i" / f"{current_name}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            viewport = options.get("viewport") or payload.get("canvas") or {
                "width": 1080,
                "height": 800,
            }
            page = await browser.new_page(
                viewport={"width": int(viewport["width"]), "height": int(viewport["height"])},
                device_scale_factor=1,
            )
            try:
                await page.set_content(html, wait_until="networkidle", timeout=90000)
                await page.evaluate("document.fonts.ready")
                await page.evaluate(
                    "Promise.all([...document.images].map(image => image.decode().catch(() => null)))"
                )
                metrics = await page.evaluate(
                    """() => ({
                        document:{width:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight},
                        bodyBackground:getComputedStyle(document.body).backgroundColor,
                        root:document.querySelector('.profile')?.getBoundingClientRect().toJSON() ?? null,
                        sections:[...document.querySelectorAll('.profile > section,.profile > .columns')].map(el=>({
                            title:el.querySelector('h2,.section-header')?.innerText ?? '',
                            rect:el.getBoundingClientRect().toJSON()
                        })),
                        visibleText:document.querySelector('.profile')?.innerText ?? '',
                        extraCount:document.querySelectorAll('.extra-resources .kv').length,
                        duplicateCampaignLabels:[...document.querySelectorAll('.kv > span')].filter(el=>/普通主线|困难主线/.test(el.innerText)).map(el=>el.innerText),
                        currencyIconSlots:[...document.querySelectorAll('.resources .resource-icon-slot')].map(el=>el.getBoundingClientRect().toJSON()),
                        layoutChecks:(() => {
                            const errors=[];
                            const boxes=selector=>[...document.querySelectorAll(selector)];
                            const rect=el=>el.getBoundingClientRect();
                            const contains=(outer,inner)=>inner.left>=outer.left-1&&inner.top>=outer.top-1&&inner.right<=outer.right+1&&inner.bottom<=outer.bottom+1;
                            const cards=boxes('.profile .kv,.profile .resource-card');
                            for(const card of cards){
                                const cardRect=rect(card);
                                const parent=card.closest('section,.profile-identity') ?? document.querySelector('.profile');
                                if(parent&&!contains(rect(parent),cardRect)) errors.push({kind:'card-outside-parent',field:card.dataset.field??''});
                                for(const child of card.querySelectorAll(':scope > span,:scope > strong,:scope > .resource-icon-slot,:scope > .resource-copy')){
                                    if(!contains(cardRect,rect(child))) errors.push({kind:'content-outside-card',field:card.dataset.field??'',selector:child.className||child.tagName});
                                }
                            }
                            for(const grid of boxes('.profile .kv-grid,.profile .resource-grid')){
                                const items=[...grid.children];
                                for(let left=0;left<items.length;left++) for(let right=left+1;right<items.length;right++){
                                    const a=rect(items[left]),b=rect(items[right]);
                                    if(Math.min(a.right,b.right)-Math.max(a.left,b.left)>1&&Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>1)
                                        errors.push({kind:'sibling-card-overlap',fields:[items[left].dataset.field??'',items[right].dataset.field??'']});
                                }
                            }
                            const resourceSlots=boxes('.resources .resource-icon-slot');
                            const slotLefts=[...new Set(resourceSlots.map(slot=>Math.round(rect(slot).left)))];
                            const identityOverflow=boxes('.profile-identity .kv>strong').filter(el=>el.scrollWidth>el.clientWidth+1).map(el=>({field:el.parentElement?.dataset.field??'',scrollWidth:el.scrollWidth,clientWidth:el.clientWidth,fontSize:getComputedStyle(el).fontSize}));
                            if(identityOverflow.length) errors.push({kind:'identity-value-overflow',items:identityOverflow});
                            const campaign={normal:document.querySelectorAll('[data-field="普通主线"]').length,hard:document.querySelectorAll('[data-field="困难主线"]').length};
                            if(campaign.normal>1||campaign.hard>1) errors.push({kind:'duplicate-campaign-field',campaign});
                            if(resourceSlots.length!==8) errors.push({kind:'currency-slot-count',count:resourceSlots.length});
                            return {errors,campaign,identityOverflow,resourceSlotCount:resourceSlots.length,resourceSlotColumns:slotLefts.length,resourceRows:cards.length};
                        })(),
                        images:[...document.images].map(img=>({alt:img.alt,width:img.naturalWidth,height:img.naturalHeight,complete:img.complete}))
                    })"""
                )
                evidence["t2i"][current_name] = metrics
                target = output / "t2i" / f"{current_name}-1600.png"
                await page.screenshot(path=str(target), full_page=True, type="png")
            finally:
                await page.close()
            with Image.open(target) as image:
                image.resize(
                    (432, round(image.height * 432 / image.width)),
                    Image.Resampling.LANCZOS,
                ).save(output / "t2i" / f"{current_name}-432.png", optimize=True)
            return str(target)

        renderer = T2IRenderer(local_html_render, assets, timeout=180)
        for current_name in names:
            await renderer.render_view("profile", cases[current_name])
            print(f"t2i {current_name}", flush=True)
        no_icon_assets = AssetManager(
            output / "no-icon-cache",
            output / "missing-assets",
            remote=False,
        )
        current_name = "iconless-resources-no-icons"
        no_icon_renderer = T2IRenderer(
            local_html_render,
            no_icon_assets,
            timeout=180,
        )
        await no_icon_renderer.render_view("profile", cases["iconless-resources"])
        print("t2i iconless-resources-no-icons", flush=True)
        await browser.close()
        no_icon_assets.close()

    assets.close()
    _write_contact_sheet(output, "t2i", names)
    (output / "FIELD_MATRIX.json").write_text(
        json.dumps(field_matrix, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "BASELINE_METRICS.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    layout_checks = {
        name: metrics.get("layoutChecks", {})
        for name, metrics in evidence["t2i"].items()
    }
    (output / "LAYOUT_CHECKS.json").write_text(
        json.dumps(layout_checks, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    asyncio.run(main())

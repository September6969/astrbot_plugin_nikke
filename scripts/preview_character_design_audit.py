"""通过正式角色 DTO、payload 和模板生成本地构图审查图。"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_nikke.core.asset_manager import AssetManager
from astrbot_plugin_nikke.features.character.composition import create_character_card_builder
from astrbot_plugin_nikke.features.character.master_resolver import CharacterMasterResolver
from astrbot_plugin_nikke.scripts.t2i_preview_fixtures import character_cases
from astrbot_plugin_nikke.ui.renderers.t2i import T2IRenderer


REPRESENTATIVE_CASES = (
    "c010",
    "c010_02",
    "c018",
    "c401",
    "c471",
    "c581",
    "long-name",
    "missing-art",
    "raven-unanchored",
)
DARK_STAGE_CASES = ("raven", "c010_02", "c471")
RAVEN_PORTRAIT = Path(r"E:\DevCache\nikke-raven-review-20261008\raven-linked.png")


def build_raven_case():
    """使用已核实目录身份构造合成 DTO，不请求任何真实账号数据。"""
    fixture = json.loads(
        (ROOT / "tests" / "fixtures" / "character_details_sanitized.json").read_text(
            encoding="utf-8"
        )
    )
    master = CharacterMasterResolver()
    canonical = master.resolve_resource_id(851)
    builder = create_character_card_builder(ROOT)
    directory = {
        "resource_id": canonical.resource_id,
        "name_code": canonical.name_code,
        "name_cn": canonical.name_cn,
        "name_en": canonical.name_en,
        "element": canonical.element,
        "weapon": canonical.weapon,
        "burst": canonical.burst,
        "corporation": canonical.corporation,
        "rare": canonical.rare,
    }
    detail, roster = copy.deepcopy(fixture["character_details"][0]), copy.deepcopy(
        fixture["roster_item"]
    )
    detail["name_code"] = roster["name_code"] = canonical.name_code
    detail.pop("costume_tid", None)
    detail["costume_id"] = 0
    return builder.build(
        account={"nickname": "合成示例 · 非账号数据"},
        directory=directory,
        payload={
            "roster_item": roster,
            "detail": detail,
            "state_effects": copy.deepcopy(fixture["state_effects"]),
        },
        fetched_at="2026-10-16 12:00",
        plugin_version="UI AUDIT",
    )


def _inject_portrait_for_raven(assets: AssetManager) -> None:
    """仅在本地审查器中注入带有同帧锚点的已验证立绘。"""
    from PIL import Image

    if not RAVEN_PORTRAIT.is_file():
        raise FileNotFoundError(f"缺少已验证 Raven 审查立绘：{RAVEN_PORTRAIT}")
    with Image.open(RAVEN_PORTRAIT) as source:
        portrait = source.convert("RGBA")
    anchor = json.loads(portrait.info["nikke_portrait_anchor"])
    digest = hashlib.sha256(portrait.tobytes()).hexdigest()
    if (
        portrait.size != (968, 919)
        or digest != "7fe08035ce2a9f9a444a648286ecd6c40b5441c75a1e07dc62c3b77fa48f55dc"
        or anchor.get("status") != "ready"
        or anchor.get("image_size") != [968, 919]
    ):
        raise ValueError("Raven 审查立绘或同帧锚点指纹不匹配")
    # 本地证据来自旧 schema 1；仅为走当前 schema 2 读取路径做内存格式适配。
    portrait.info["nikke_portrait_anchor"] = json.dumps(
        {**anchor, "schema": 2}, ensure_ascii=False
    )

    original_resolver = assets.resolve_character_assets
    unanchored_portrait = portrait.copy()
    unanchored_portrait.info.pop("nikke_portrait_anchor", None)
    assets.preview_raven_unanchored = False
    assets.preview_current_name = "unknown"
    assets.preview_framing = {}

    def resolve_character_assets(data, timeout=None):
        resolved = original_resolver(data, timeout)
        if str(data.resource_id) == "851" and str(data.costume_id or "0") == "0":
            source = (
                unanchored_portrait
                if assets.preview_raven_unanchored
                else portrait
            )
            resolved.portrait = source.copy()
        from astrbot_plugin_nikke.features.character.face_anchor import framing

        layout = framing(
            data,
            resolved.portrait,
            summary_count=4,
            identity_resolver=assets.nikke_db,
        )
        assets.preview_framing[assets.preview_current_name] = {
            "resource_id": str(data.resource_id),
            "name": data.name_cn,
            "costume_id": data.costume_id,
            "portrait_size": list(resolved.portrait.size),
            "portrait_pixel_sha256": hashlib.sha256(
                resolved.portrait.convert("RGBA").tobytes()
            ).hexdigest(),
            **layout,
        }
        return resolved

    assets.resolve_character_assets = resolve_character_assets


def _dark_stage(html: str) -> str:
    """只为离线对照改变透明立绘后方的舞台颜色。"""
    style = (
        "<style>html,body{background:#111820!important;}"
        ".character{background:radial-gradient(ellipse 1000px 780px at 50% 36%,"
        "rgba(67,83,104,.58) 0%,rgba(30,39,51,.34) 58%,transparent 100%),"
        "linear-gradient(180deg,#17212c 0%,#202832 48%,#111820 100%)!important;}"
        "</style>"
    )
    return html.replace("</head>", f"{style}</head>")


def _write_contact_sheets(output: Path, names: list[str]) -> None:
    from PIL import Image, ImageDraw

    width, height = 432, 648
    columns = 3
    rows = (len(names) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * width, rows * (height + 44)), "#e7e9ec")
    draw = ImageDraw.Draw(sheet)
    for index, name in enumerate(names):
        path = output / f"{name}-432.png"
        with Image.open(path) as image:
            thumb = image.convert("RGB")
        x = (index % columns) * width
        y = (index // columns) * (height + 44)
        sheet.paste(thumb, (x, y + 44))
        draw.text((x + 12, y + 12), name, fill="#20242a")
    sheet.save(output / "contact-light.png", optimize=True)

    dark_names = [name for name in DARK_STAGE_CASES if name in names]
    compare = Image.new("RGB", (2 * width, len(dark_names) * (height + 44)), "#e7e9ec")
    draw = ImageDraw.Draw(compare)
    for index, name in enumerate(dark_names):
        y = index * (height + 44)
        for column, suffix, label in (
            (0, "432", f"{name} · light"),
            (1, "dark-stage-432", f"{name} · dark stage"),
        ):
            with Image.open(output / f"{name}-{suffix}.png") as image:
                thumb = image.convert("RGB")
            x = column * width
            compare.paste(thumb, (x, y + 44))
            draw.text((x + 12, y + 12), label, fill="#20242a")
    compare.save(output / "contact-theme-comparison.png", optimize=True)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--cases", default=",".join((*REPRESENTATIVE_CASES, "raven"))
    )
    parser.add_argument("--dark-compare", action="store_true")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("ASTRBOT_ROOT", str(output / "runtime"))
    (Path(os.environ["ASTRBOT_ROOT"]) / "data" / "temp").mkdir(
        parents=True, exist_ok=True
    )

    from jinja2 import Environment
    from PIL import Image
    from playwright.async_api import async_playwright

    assets = AssetManager(output / "asset-cache", ROOT / "assets", remote=False)
    _inject_portrait_for_raven(assets)
    browser_runtime = await async_playwright().start()
    browser = await browser_runtime.chromium.launch()
    current_name = "preview"
    current_variant = "light"
    layout_reports: dict[str, dict] = {}

    async def local_html_render(template, payload, options):
        html = Environment(autoescape=True).from_string(template).render(**payload)
        if current_variant == "dark-stage":
            html = _dark_stage(html)
        html_path = output / f"{current_name}-{current_variant}.html"
        json_path = output / f"{current_name}-{current_variant}.json"
        html_path.write_text(html, encoding="utf-8")
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        page = await browser.new_page(
            viewport={"width": 1600, "height": 2400}, device_scale_factor=1
        )
        try:
            await page.set_content(html, wait_until="networkidle", timeout=90000)
            await page.evaluate("document.fonts.ready")
            await page.evaluate(
                "Promise.all([...document.images].map(image => image.decode().catch(() => null)))"
            )
            layout_reports[f"{current_name}:{current_variant}"] = await page.evaluate(
                """() => {
                    const rect = element => {
                        if (!element) return null;
                        const value = element.getBoundingClientRect();
                        return {left:value.left, top:value.top, right:value.right, bottom:value.bottom,
                                width:value.width, height:value.height};
                    };
                    const inside = (inner, outer) => inner && outer &&
                        inner.left >= outer.left - 1 && inner.top >= outer.top - 1 &&
                        inner.right <= outer.right + 1 && inner.bottom <= outer.bottom + 1;
                    const intersects = (a, b) => a && b && a.left < b.right &&
                        a.right > b.left && a.top < b.bottom && a.bottom > b.top;
                    const root = document.querySelector('.character');
                    const header = document.querySelector('.identity');
                    const title = document.querySelector('.slot-character-name h1');
                    const level = document.querySelector('.slot-level');
                    const range = document.createRange();
                    if (title) range.selectNodeContents(title);
                    const lines = [...range.getClientRects()].map(value => ({
                        left:value.left, top:value.top, right:value.right, bottom:value.bottom,
                        width:value.width, height:value.height
                    }));
                    const equipmentArea = document.querySelector('.equipment-area');
                    const summaryPanel = document.querySelector('.summary-panel');
                    const summaryRows = [...document.querySelectorAll('.summary-row')].map(rect);
                    const gearBoxes = [...document.querySelectorAll('.gear')].map(rect);
                    const skillBoxes = [...document.querySelectorAll('.skill')].map(rect);
                    const titleRect = rect(title), headerRect = rect(header), levelRect = rect(level);
                    const titleLevelOverlap = lines.some(line => intersects(line, levelRect));
                    return {
                        document: {width:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight},
                        root:rect(root), header:headerRect, title:titleRect, titleLines:lines,
                        titleScroll:{width:title?.scrollWidth ?? 0,height:title?.scrollHeight ?? 0,
                                     clientWidth:title?.clientWidth ?? 0,clientHeight:title?.clientHeight ?? 0},
                        level:levelRect, titleWithinHeader:lines.every(line => inside(line,headerRect)),
                        titleLevelOverlap,
                        scrollExceedsClient:title?.scrollHeight > title?.clientHeight + 1,
                        equipmentArea:rect(equipmentArea), summaryPanel:rect(summaryPanel),
                        summaryRows, gearBoxes, skillBoxes,
                        images:[...document.images].map(image => ({alt:image.alt,width:image.naturalWidth,height:image.naturalHeight,complete:image.complete}))
                    };
                }"""
            )
            target = output / f"{current_name}-{current_variant}-1600.png"
            await page.screenshot(path=str(target), full_page=True, type="png")
            return str(target)
        finally:
            await page.close()

    renderer = T2IRenderer(local_html_render, assets, timeout=180)
    cases = character_cases()
    cases["raven"] = build_raven_case()
    cases["raven-unanchored"] = build_raven_case()
    names = [name.strip() for name in args.cases.split(",") if name.strip()]
    missing = [name for name in names if name not in cases]
    if missing:
        raise KeyError(f"未知角色卡案例：{', '.join(missing)}")

    try:
        for current_name in names:
            current_variant = "light"
            assets.preview_raven_unanchored = current_name == "raven-unanchored"
            assets.preview_current_name = current_name
            result = await renderer.render_view("character", cases[current_name])
            with Image.open(result) as image:
                original_size = image.size
                image.resize(
                    (432, round(image.height * 432 / image.width)),
                    Image.Resampling.LANCZOS,
                ).save(output / f"{current_name}-432.png", optimize=True)
            print(f"light {current_name}: {original_size} -> 432px", flush=True)
            if args.dark_compare and current_name in DARK_STAGE_CASES:
                current_variant = "dark-stage"
                result = await renderer.render_view("character", cases[current_name])
                with Image.open(result) as image:
                    image.resize(
                        (432, round(image.height * 432 / image.width)),
                        Image.Resampling.LANCZOS,
                    ).save(
                        output / f"{current_name}-dark-stage-432.png",
                        optimize=True,
                    )
                print(f"dark-stage {current_name}: {image.size}", flush=True)
    finally:
        await browser.close()
        await browser_runtime.stop()
        assets.close()

    _write_contact_sheets(output, names)
    (output / "LAYOUT.json").write_text(
        json.dumps(layout_reports, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "ART_FRAMING.json").write_text(
        json.dumps(assets.preview_framing, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output / "AUDIT.json").write_text(
        json.dumps(
            {
                "cases": names,
                "raven": {
                    "resource_id": 851,
                    "name_code": 5143,
                    "spine_asset_id": "c851",
                    "portrait": str(RAVEN_PORTRAIT),
                    "source_evidence": str(
                        ROOT / "docs" / "evidence" / "runtime_anchor_linkage_20261008.md"
                    ),
                    "sha256_pixels": "7fe08035ce2a9f9a444a648286ecd6c40b5441c75a1e07dc62c3b77fa48f55dc",
                    "anchor": _read_raven_anchor(),
                    "source_anchor_schema": 1,
                    "preview_anchor_schema": 2,
                    "schema_adaptation": "只在预览内存中变更版本字段，像素与锚点坐标不变",
                    "preview_only_injection": True,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _read_raven_anchor() -> dict:
    """读取与 Raven PNG 像素同帧的已验证锚点元数据。"""
    from PIL import Image

    with Image.open(RAVEN_PORTRAIT) as image:
        return json.loads(image.info["nikke_portrait_anchor"])


if __name__ == "__main__":
    asyncio.run(main())

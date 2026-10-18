"""用正式总表 DTO、T2I loader 与原 Pillow renderer 生成审查预览。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_nikke.core.asset_manager import AssetManager
from astrbot_plugin_nikke.features.character.application import (
    CharacterRosterData,
    RosterOptionSummary,
)
from astrbot_plugin_nikke.features.character.builder import CharacterCardBuilder
from astrbot_plugin_nikke.features.character.registries.overload import OverloadTierRegistry
from astrbot_plugin_nikke.features.character.registries.state_effect import StateEffectRegistry
from astrbot_plugin_nikke.features.character.roster_ranking import select_top_codes
from astrbot_plugin_nikke.ui.renderers.t2i import T2IRenderer


class MissingAvatarAssets:
    """为缺图场景遮蔽一个本地头像，不改变静态身份目录。"""

    def __init__(self, assets: AssetManager, missing_resource_id: int) -> None:
        self._assets = assets
        self.character_master = assets.character_master
        self.missing_resource_id = missing_resource_id

    def get_lineup_portrait_by_resource_id(self, resource_id: Any):
        if int(resource_id) == self.missing_resource_id:
            return None, True
        return self._assets.get_lineup_portrait_by_resource_id(resource_id)


def _catalog() -> list[dict[str, Any]]:
    path = ROOT / "assets" / "data" / "character_master.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = [
        item
        for item in raw.get("characters", [])
        if item.get("name_code") is not None and item.get("resource_id") is not None
    ]
    rows.sort(key=lambda item: int(item["id"]))
    return rows


def _display_name(item: dict[str, Any]) -> str:
    return str(item.get("name_cn") or item.get("name_zh_tw") or item.get("name_en") or "未知妮姬")


def _entry(item: dict[str, Any], index: int, *, combat: int | None = None) -> dict[str, Any]:
    return {
        "name_code": str(item["name_code"]),
        "lv": 200 - index % 80,
        "combat": combat if combat is not None else 1_250_000 - index * 12_345,
        "grade": index % 4,
        "core": index % 8,
        "skill1_lv": 10 if index % 2 == 0 else 7,
        "skill2_lv": 9 if index % 3 == 0 else 6,
        "ulti_skill_lv": 10 if index % 4 == 0 else 8,
    }


def _builder() -> CharacterCardBuilder:
    assets = ROOT / "assets"
    state_path = assets / "data" / "state_effects.json"
    if not state_path.is_file():
        state_path = assets / "state_effects.json"
    tier_path = assets / "data" / "overload_tiers.json"
    if not tier_path.is_file():
        tier_path = assets / "overload_tiers.json"
    return CharacterCardBuilder(
        state_effect_registry=StateEffectRegistry.from_file(state_path),
        overload_tier_registry=OverloadTierRegistry.from_file(tier_path),
    )


def _fixture_payload(code: str, *, big: bool = False) -> dict[str, Any]:
    """用脱敏样本构造正式详情载荷；big=True 时制造大数值词条。"""
    fixture = json.loads(
        (ROOT / "tests" / "fixtures" / "character_details_sanitized.json").read_text(
            encoding="utf-8"
        )
    )
    roster_item = dict(fixture["roster_item"])
    roster_item["name_code"] = code
    detail = dict(fixture["character_details"][0])
    detail["name_code"] = code
    state_effects = [dict(effect) for effect in fixture["state_effects"]]
    if big:
        for effect in state_effects:
            functions = [dict(fn) for fn in effect.get("function_details", []) or []]
            for function in functions:
                function["function_value"] = 399900
            effect["function_details"] = functions
    return {
        "roster_item": roster_item,
        "detail": detail,
        "state_effects": state_effects,
    }


def _summary(code: str, *, status: str = "ok", big: bool = False) -> RosterOptionSummary:
    """用单卡词条汇总口径生成正式摘要，并允许注入失败/未知状态。"""
    if status == "failed":
        return RosterOptionSummary(code, "failed", complete=False, message="详情读取失败")
    if status == "unreturned":
        return RosterOptionSummary(code, "unreturned", complete=False, message="详情未返回")
    if status == "none":
        return RosterOptionSummary(code, "none", complete=True, message="无装备词条")
    if status == "unknown":
        return RosterOptionSummary(code, "unknown", complete=False, message="词条字段未识别")
    raw = _builder().option_summary(resource_id=470, payload=_fixture_payload(code, big=big))
    rows = tuple(raw["rows"])
    total = int(raw["total"])
    complete = bool(raw["complete"])
    return RosterOptionSummary(
        name_code=code,
        status="ok" if complete else "partial",
        rows=rows,
        total=total,
        complete=complete,
        message="" if complete else "部分词条未识别",
    )


def _auto_summaries(
    entries: list[dict[str, Any]], *, big: bool = False
) -> dict[str, RosterOptionSummary]:
    """为共享排序的 top-3 生成 ok 词条摘要。"""
    return {code: _summary(code, big=big) for code in select_top_codes(entries, 3)}


def _dto(
    name: str,
    entries: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
    name_overrides=None,
    summaries=None,
) -> CharacterRosterData:
    name_map = {
        str(item["name_code"]): _display_name(item)
        for item in catalog
        if item.get("name_code") is not None
    }
    if name_overrides:
        name_map.update(name_overrides)
    return CharacterRosterData(
        f"预览指挥官 · {name}",
        tuple(entries),
        name_map,
        summaries or {},
    )


def _cases(catalog: list[dict[str, Any]]) -> tuple[dict[str, CharacterRosterData], int]:
    selected = catalog[:21]
    rapi = next(item for item in catalog if str(item["name_code"]) == "3001")
    anis = next(item for item in catalog if str(item["name_code"]) == "3005")
    third = selected[2]
    roster20 = [_entry(item, index) for index, item in enumerate(selected[:20])]
    roster21 = [_entry(item, index) for index, item in enumerate(selected)]
    unknown = {"name_code": "101001", "lv": 200, "combat": 750_000}
    missing = {
        "name_code": str(rapi["name_code"]),
        "lv": None,
        "combat": 0,
        "grade": 0,
        "core": None,
        "skill1_lv": None,
        "skill2_lv": "not-a-level",
        "ulti_skill_lv": 0,
    }
    long_name = "指挥官测试用超长妮姬名称与 English Character Name Validation"
    long_entries = [_entry(rapi, 0, combat=9_999_999_999), _entry(anis, 1, combat=9_000_000_000)]
    partial_entries = [
        _entry(rapi, 0, combat=900_000),
        _entry(anis, 1, combat=800_000),
        _entry(third, 2, combat=700_000),
    ]
    fewer_entries = [_entry(rapi, 0, combat=900_000), _entry(anis, 1, combat=800_000)]
    cases = {
        "00-empty": _dto("empty", [], catalog),
        "01-single": _dto(
            "single", [_entry(rapi, 0)], catalog, summaries=_auto_summaries([_entry(rapi, 0)])
        ),
        "03-equal-combat": _dto(
            "equal-combat",
            [
                _entry(rapi, 0, combat=900_000),
                _entry(anis, 1, combat=900_000),
                _entry(selected[2], 2, combat=900_000),
            ],
            catalog,
            summaries=_auto_summaries(
                [
                    _entry(rapi, 0, combat=900_000),
                    _entry(anis, 1, combat=900_000),
                    _entry(selected[2], 2, combat=900_000),
                ]
            ),
        ),
        "20-full": _dto("full", roster20, catalog, summaries=_auto_summaries(roster20)),
        "21-top20": _dto("top20", roster21, catalog, summaries=_auto_summaries(roster21)),
        "same-name-different-code": _dto(
            "same-name",
            [_entry(rapi, 0, combat=900_000), _entry(anis, 1, combat=800_000)],
            catalog,
            {str(rapi["name_code"]): "同名妮姬", str(anis["name_code"]): "同名妮姬"},
            summaries={
                str(rapi["name_code"]): _summary(str(rapi["name_code"])),
                str(anis["name_code"]): _summary(str(anis["name_code"])),
            },
        ),
        "unknown-code": _dto("unknown", [unknown], catalog),
        "missing-values-and-zero": _dto("missing-values", [missing], catalog),
        "long-bilingual-name": _dto(
            "long-name",
            [_entry(rapi, 0)],
            catalog,
            {str(rapi["name_code"]): long_name},
        ),
        "missing-avatar": _dto(
            "missing-avatar",
            [_entry(rapi, 0)],
            catalog,
            summaries=_auto_summaries([_entry(rapi, 0)]),
        ),
        "30-normal-options": _dto(
            "normal-options", roster20, catalog, summaries=_auto_summaries(roster20)
        ),
        "31-long-name-many-options": _dto(
            "long-name-options",
            long_entries,
            catalog,
            {str(rapi["name_code"]): long_name, str(anis["name_code"]): long_name},
            summaries=_auto_summaries(long_entries, big=True),
        ),
        "32-partial-detail": _dto(
            "partial-detail",
            partial_entries,
            catalog,
            summaries={
                str(rapi["name_code"]): _summary(str(rapi["name_code"])),
                str(anis["name_code"]): _summary(str(anis["name_code"]), status="failed"),
                str(third["name_code"]): _summary(str(third["name_code"]), status="unreturned"),
            },
        ),
        "33-fewer-than-three": _dto(
            "fewer-than-three",
            fewer_entries,
            catalog,
            summaries=_auto_summaries(fewer_entries),
        ),
    }
    return cases, int(rapi["resource_id"])


def _contact_sheet(output: Path, names: list[str], engine: str) -> None:
    from PIL import Image, ImageDraw

    columns, cell_width, label_height = 3, 432, 32
    images = []
    for name in names:
        with Image.open(output / engine / f"{name}-432.png") as image:
            images.append(image.convert("RGB"))
    row_heights = [
        max(image.height for image in images[start : start + columns])
        for start in range(0, len(images), columns)
    ]
    sheet = Image.new(
        "RGB",
        (columns * cell_width, sum(height + label_height for height in row_heights)),
        "#e5e9ec",
    )
    draw = ImageDraw.Draw(sheet)
    y = index = 0
    for row_height in row_heights:
        for column in range(columns):
            if index >= len(images):
                break
            draw.text((column * cell_width + 10, y + 8), names[index], fill="#26313a")
            sheet.paste(images[index], (column * cell_width, y + label_height))
            index += 1
        y += row_height + label_height
    sheet.save(output / engine / "contact-432.png", optimize=True)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    for engine in ("t2i",):
        (output / engine).mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("ASTRBOT_ROOT", str(output / "runtime"))
    (Path(os.environ["ASTRBOT_ROOT"]) / "data" / "temp").mkdir(parents=True, exist_ok=True)

    from jinja2 import Environment
    from PIL import Image
    from playwright.async_api import async_playwright

    catalog = _catalog()
    cases, missing_resource_id = _cases(catalog)
    names = list(cases)
    assets = AssetManager(output / "cache", ROOT / "assets", remote=False)
    evidence: dict[str, Any] = {"t2i": {}}
    state = {"case": ""}

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()

        async def local_html_render(template, payload, options):
            name = state["case"]
            html = Environment(autoescape=True).from_string(template).render(**payload)
            (output / "t2i" / f"{name}.html").write_text(html, encoding="utf-8")
            (output / "t2i" / f"{name}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            viewport = options.get("viewport") or payload["canvas"]
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
                    """expectedHeight => {
                        const root=document.querySelector('.roster');
                        const rows=[...document.querySelectorAll('.roster-row')];
                        const rect=el=>el.getBoundingClientRect();
                        const contains=(outer,inner)=>inner.left>=outer.left-1&&inner.top>=outer.top-1&&inner.right<=outer.right+1&&inner.bottom<=outer.bottom+1;
                        const errors=[];
                        const rootRect=root?rect(root):null;
                        if(!root) errors.push({kind:'missing-root'});
                        for(const row of rows){
                            const rowRect=rect(row);
                            if(rootRect&&!contains(rootRect,rowRect)) errors.push({kind:'row-outside-roster',rank:row.dataset.rank});
                            for(const child of row.querySelectorAll('.rank,.avatar,.identity,.metric,.roster-options'))
                                if(!contains(rowRect,rect(child))) errors.push({kind:'content-outside-row',rank:row.dataset.rank,selector:child.className});
                        }
                        for(let i=0;i<rows.length;i++) for(let j=i+1;j<rows.length;j++){
                            const a=rect(rows[i]),b=rect(rows[j]);
                            if(Math.min(a.right,b.right)-Math.max(a.left,b.left)>1&&Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>1)
                                errors.push({kind:'sibling-row-overlap',ranks:[rows[i].dataset.rank,rows[j].dataset.rank]});
                        }
                        const textOverflow=[...document.querySelectorAll('.name,.metric,.roster-count,.roster-labels > span,.opt-label,.opt-value,.opt-tier,.options-head')]
                            .filter(el=>el.scrollWidth>el.clientWidth+1)
                            .map(el=>({text:el.innerText,scrollWidth:el.scrollWidth,clientWidth:el.clientWidth}));
                        for(const item of textOverflow) errors.push({kind:'text-clipped',...item});
                        const scale=432/innerWidth;
                        const mobileFont=selector=>{
                            const element=document.querySelector(selector);
                            return element?parseFloat(getComputedStyle(element).fontSize)*scale:null;
                        };
                        const mobileReadability={
                            labels:mobileFont('.roster-labels'),
                            skills:mobileFont('.skills'),
                            progress:mobileFont('.progress')
                        };
                        for(const [field,pixels] of Object.entries(mobileReadability))
                            if(pixels!==null&&pixels<10) errors.push({kind:'mobile-font-below-target',field,pixels});
                        const images=[...document.images].map(image=>({alt:image.alt,width:image.naturalWidth,height:image.naturalHeight,complete:image.complete}));
                        for(const image of images) if(!image.complete||image.width<=0||image.height<=0) errors.push({kind:'avatar-decode-failed',image});
                        const doc={width:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight};
                        const expected={width:1200,height:expectedHeight};
                        if(doc.width!==expected.width||doc.height!==expected.height)
                            errors.push({kind:'document-size-mismatch',doc,expected});
                        return {errors,document:doc,expected,root:rootRect?.toJSON()??null,rowCount:rows.length,mobileReadability,
                            rowRects:rows.map(row=>({rank:row.dataset.rank,rect:rect(row).toJSON(),name:row.querySelector('.name')?.innerText??''})),
                            textOverflow,images,visibleText:root?.innerText??''};
                    }""",
                    int(viewport["height"]),
                )
                target = output / "t2i" / f"{name}-1200.png"
                await page.screenshot(path=str(target), full_page=True, type="png")
                evidence["t2i"][name] = {"metrics": metrics, "diagnostics": payload["diagnostics"]}
            finally:
                await page.close()
            with Image.open(target) as image:
                image.resize(
                    (432, round(image.height * 432 / image.width)),
                    Image.Resampling.LANCZOS,
                ).save(output / "t2i" / f"{name}-432.png", optimize=True)
            return str(target)

        for name, data in cases.items():
            state["case"] = name
            page_assets = (
                MissingAvatarAssets(assets, missing_resource_id)
                if name == "missing-avatar"
                else assets
            )
            renderer = T2IRenderer(local_html_render, page_assets, timeout=180)
            await renderer.render_view("roster", data)
            print(f"t2i {name}", flush=True)
        await browser.close()

    assets.close()
    _contact_sheet(output, names, "t2i")
    layout = {
        "t2i": {name: data["metrics"] for name, data in evidence["t2i"].items()},
    }
    (output / "LAYOUT_CHECKS.json").write_text(
        json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "PREVIEW_EVIDENCE.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    errors = [
        (name, issue)
        for name, metrics in layout["t2i"].items()
        for issue in metrics["errors"]
    ]
    if errors:
        raise SystemExit(f"roster 布局发现 {len(errors)} 项错误：{errors[:8]}")
    print(f"完成 {len(names)} 个 DTO 场景；布局错误 0 项；输出：{output}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

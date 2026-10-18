"""通过生产模板生成固定日程样本的整图和手机预览。"""

# 支持直接执行、模块导入及从其他工作目录调用。
import sys as _bootstrap_sys
from pathlib import Path as _BootstrapPath
_bootstrap_root = _BootstrapPath(__file__).resolve().parents[2]
for _bootstrap_path in (_bootstrap_root.parent, _bootstrap_root):
    if str(_bootstrap_path) not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, str(_bootstrap_path))

import argparse
import asyncio
import hashlib
import importlib.metadata
import platform
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment
from PIL import Image
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT.parent))
from astrbot_plugin_nikke.core.asset_manager import AssetManager
from astrbot_plugin_nikke.features.calendar.application import CalendarApplication
from astrbot_plugin_nikke.features.calendar.canonical_models import CanonicalEvent, SourceHealth
from astrbot_plugin_nikke.features.calendar.service import CalendarService
from astrbot_plugin_nikke.integrations.calendar.visual_cache import CalendarVisualCache
from astrbot_plugin_nikke.ui.payloads.calendar import CalendarT2IPayloadBuilder
from astrbot_plugin_nikke.ui.renderers.t2i import T2IRenderer

NOW = datetime(2026, 10, 13, 6, 21, 41, 863426, tzinfo=timezone.utc)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--visual-cache-source", type=Path)
    args = parser.parse_args()
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    source_visual_cache = CalendarVisualCache(args.visual_cache_source) if args.visual_cache_source else None
    background_metadata = None
    assets = AssetManager(output / "assets", ROOT / "assets", remote=False)
    checks = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        browser_metadata = {"version": browser.version, "executable": playwright.chromium.executable_path}
        name = ""
        async def native(template, payload, options):
            html = Environment(autoescape=True).from_string(template).render(**payload)
            (output / f"{name}.html").write_text(html, encoding="utf-8")
            page = await browser.new_page(viewport=options["viewport"])
            await page.set_content(html)
            await page.evaluate("document.fonts.ready")
            image_metrics = await page.evaluate(r'''async () => {
                const sources = [...document.images].map(image => image.currentSrc || image.src);
                for (const element of document.querySelectorAll("*")) {
                    const background = getComputedStyle(element).backgroundImage;
                    for (const match of background.matchAll(/url\(([^)]+)\)/g)) {
                        sources.push(match[1].replace(/^["']|["']$/g, ""));
                    }
                }
                return await Promise.all([...new Set(sources.filter(Boolean))].map(async src => {
                    const image = new Image();
                    image.src = src;
                    try { await image.decode(); return {ok:true,width:image.naturalWidth,height:image.naturalHeight}; }
                    catch { return {ok:false,width:image.naturalWidth,height:image.naturalHeight}; }
                }));
            }''')
            bounds = await page.evaluate("""() => ({width:document.documentElement.scrollWidth,
                height:document.documentElement.scrollHeight,viewport:innerWidth,
                overflow:[...document.querySelectorAll('.title,.dates,footer')].filter(e=>e.scrollWidth>e.clientWidth+2).length})""")
            path = output / f"{name}.png"
            await page.screenshot(path=str(path), full_page=True)
            await page.close()
            with Image.open(path) as image:
                image.resize((432, round(image.height * 432 / image.width)), Image.Resampling.LANCZOS).save(output / f"{name}-mobile.png")
            checks.append({"name": name, **bounds, "images": image_metrics})
            return str(path)
        renderer = T2IRenderer(native, assets, timeout=120)
        for case, count in (("normal", 5), ("long-title", 8), ("multi-page", 17), ("empty", 0), ("partial", 4), ("unknown-time", 3), ("expired", 3), ("unconfirmed", 2)):
            service = CalendarService(output / "samples" / case, visual_cache=source_visual_cache if case == "normal" else None)
            health_at = NOW - (timedelta(days=7) if case == "expired" else timedelta())
            service.freshness = "EXPIRED" if case == "expired" else "FRESH"
            service.coverage = "PARTIAL" if case == "partial" else "COMPLETE"
            service._update_health_state = lambda: None
            service._source_datasets = {"gamekee": []}
            service._has_snapshot = True
            service.last_success_at = health_at
            service.last_updated_at = NOW.isoformat()
            service._source_health["gamekee"] = SourceHealth("gamekee", last_success_at=health_at, completeness="PARTIAL" if case == "partial" else "COMPLETE")
            service.last_sync_error = "固定失败样本" if case == "partial" else ""
            for index in range(count):
                is_verified_banner_event = case == "normal" and index == 1
                item = CanonicalEvent(
                    id="gamekee:7887" if is_verified_banner_event else f"sample-{index}",
                    title="MOST BEAUTIFUL MAID" if is_verified_banner_event else f"活动 {index+1} · " + ("很长的活动名称，用于检查自然换行及手机阅读体验" * 3 if case == "long-title" else "联盟协同作战"),
                    event_type="event",
                    start_at=datetime(2026, 10, 7, 16, tzinfo=timezone.utc) if is_verified_banner_event else (NOW - timedelta(days=1) if index % 3 else NOW + timedelta(days=2)),
                    end_at=datetime(2026, 10, 28, 14, 59, tzinfo=timezone.utc) if is_verified_banner_event else (NOW + timedelta(hours=8) if index == 1 else NOW + timedelta(days=5)),
                    sources=["gamekee"], primary_source="gamekee", fetched_at=NOW, updated_at=NOW,
                )
                if case == "unknown-time":
                    item.end_precision = "UNKNOWN" if index == 1 else "DATE_ONLY"
                if case == "unconfirmed":
                    item.start_at = None
                    item.start_precision = "UNKNOWN"
                service._events[item.id] = item
            snapshot = CalendarApplication(service).query_schedule(now=NOW)
            if case == "normal" and source_visual_cache:
                selected_path = snapshot.background_path
                expected_path = source_visual_cache.resolve_path("gamekee:7887")
                if selected_path is None or selected_path.resolve() != expected_path.resolve():
                    raise RuntimeError(f"主背景未解析到已验证的活动海报: {selected_path}")
                asset_entry = source_visual_cache._manifest["gamekee:7887"]
                with Image.open(selected_path) as source_image:
                    asset_dimensions = list(source_image.size)
                background_metadata = {
                    "event_id": "gamekee:7887",
                    "title": "MOST BEAUTIFUL MAID",
                    "source_url": asset_entry["source_url"],
                    "path": str(selected_path),
                    "sha256": hashlib.sha256(selected_path.read_bytes()).hexdigest(),
                    "dimensions": asset_dimensions,
                    "fetched_at": asset_entry.get("fetched_at"),
                }
            bundle = CalendarT2IPayloadBuilder().build(snapshot)
            if case == "normal":
                fixture = {
                    "case_id": "normal",
                    "now": NOW.isoformat(),
                    "health_at": health_at.isoformat(),
                    "freshness": service.freshness,
                    "coverage": service.coverage,
                    "events": [
                        {
                            "id": event.id,
                            "title": event.title,
                            "event_type": event.event_type,
                            "start_at": event.start_at.isoformat() if event.start_at else None,
                            "end_at": event.end_at.isoformat() if event.end_at else None,
                            "start_precision": event.start_precision,
                            "end_precision": event.end_precision,
                            "sources": event.sources,
                        } for event in service._events.values()
                    ],
                    "background_asset": background_metadata,
                }
                (output / "normal-fixture.json").write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
                (output / "normal-payload.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
            for payload in bundle["pages"]:
                name = f"{case}-{payload['page_number']}"
                await renderer.render_payload("calendar_schedule", {**bundle, **payload, "pages": [payload]})
            if case == "normal":
                name = "before-normal"
                legacy = CalendarT2IPayloadBuilder().build(service, now=NOW)
                await renderer.render_payload("calendar_schedule", {**legacy, **legacy["pages"][0]})
        await browser.close()
    assets.close()
    (output / "layout-checks.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
    def sha256(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    template_files = [ROOT / "templates" / "t2i" / "calendar_schedule.html"] + sorted((ROOT / "templates" / "t2i" / "_shared").glob("*"))
    template_files = [path for path in template_files if path.is_file()]
    output_files = [output / "normal-1.png", output / "normal-1-mobile.png", output / "normal-fixture.json", output / "normal-payload.json"]
    manifest = {
        "case_id": "normal",
        "clock": NOW.isoformat(),
        "renderer": "T2IRenderer + production T2ITemplateLoader + local Playwright Chromium",
        "python": {"executable": sys.executable, "version": platform.python_version()},
        "packages": {name: importlib.metadata.version(name) for name in ("playwright", "Pillow", "Jinja2")},
        "browser": browser_metadata,
        "viewport": {"width": 1600, "height": 900},
        "background_asset": background_metadata,
        "resources": {str(path.relative_to(ROOT)).replace("\\", "/"): sha256(path) for path in template_files},
        "asset_sha256": background_metadata["sha256"] if background_metadata else None,
        "outputs": {path.name: sha256(path) for path in output_files if path.is_file()},
    }
    (output / "baseline-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    links = "".join(f'<section><h2>{item["name"]}</h2><a href="{item["name"]}.png"><img width="432" src="{item["name"]}-mobile.png"></a></section>' for item in checks)
    (output / "index.html").write_text('<meta charset="utf-8"><title>日程预览</title><style>body{background:#edf1f6;font-family:sans-serif}main{display:flex;flex-wrap:wrap;gap:24px}</style><h1>日程优化前后预览</h1><main>'+links+'</main>', encoding="utf-8")
    assert all(c["width"] <= c["viewport"] and c["overflow"] == 0 for c in checks), checks
    print(f"已生成 {len(checks)} 张预览：{output / 'index.html'}")


if __name__ == "__main__":
    asyncio.run(main())

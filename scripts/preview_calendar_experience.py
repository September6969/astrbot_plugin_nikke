"""通过生产模板生成固定日程样本的整图和手机预览。"""
import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment
from PIL import Image
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from astrbot_plugin_nikke.core.asset_manager import AssetManager
from astrbot_plugin_nikke.features.calendar.application import CalendarApplication
from astrbot_plugin_nikke.features.calendar.canonical_models import CanonicalEvent, SourceHealth
from astrbot_plugin_nikke.features.calendar.service import CalendarService
from astrbot_plugin_nikke.ui.payloads.calendar import CalendarT2IPayloadBuilder
from astrbot_plugin_nikke.ui.renderers.t2i import T2IRenderer

NOW = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output
    output.mkdir(parents=True, exist_ok=True)
    assets = AssetManager(output / "assets", ROOT / "assets", remote=False)
    checks = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        name = ""
        async def native(template, payload, options):
            html = Environment(autoescape=False).from_string(template).render(**payload)
            (output / f"{name}.html").write_text(html, encoding="utf-8")
            page = await browser.new_page(viewport=options["viewport"])
            await page.set_content(html)
            await page.evaluate("document.fonts.ready")
            bounds = await page.evaluate("""() => ({width:document.documentElement.scrollWidth,
                height:document.documentElement.scrollHeight,viewport:innerWidth,
                overflow:[...document.querySelectorAll('.title,.dates,footer')].filter(e=>e.scrollWidth>e.clientWidth+2).length})""")
            path = output / f"{name}.png"
            await page.screenshot(path=str(path), full_page=True)
            await page.close()
            with Image.open(path) as image:
                image.resize((432, round(image.height * 432 / image.width)), Image.Resampling.LANCZOS).save(output / f"{name}-mobile.png")
            checks.append({"name": name, **bounds})
            return str(path)
        renderer = T2IRenderer(native, assets, timeout=120)
        for case, count in (("normal", 5), ("long-title", 8), ("multi-page", 17), ("empty", 0), ("partial", 4), ("unknown-time", 3), ("expired", 3), ("unconfirmed", 2)):
            service = CalendarService(output / "samples" / case)
            service._source_datasets = {"gamekee": []}
            service._has_snapshot = True
            service.last_success_at = datetime.now(timezone.utc) - (timedelta(days=7) if case == "expired" else timedelta())
            service.last_updated_at = NOW.isoformat()
            service._source_health["gamekee"] = SourceHealth("gamekee", last_success_at=NOW, completeness="PARTIAL" if case == "partial" else "COMPLETE")
            service.last_sync_error = "固定失败样本" if case == "partial" else ""
            for index in range(count):
                item = CanonicalEvent(id=f"sample-{index}", title=f"活动 {index+1} · " + ("很长的活动名称，用于检查自然换行及手机阅读体验" * 3 if case == "long-title" else "联盟协同作战"),
                    event_type="event", start_at=NOW - timedelta(days=1) if index % 3 else NOW + timedelta(days=2),
                    end_at=NOW + timedelta(hours=8) if index == 1 else NOW + timedelta(days=5), sources=["gamekee"], primary_source="gamekee")
                if case == "unknown-time":
                    item.end_precision = "UNKNOWN" if index == 1 else "DATE_ONLY"
                if case == "unconfirmed":
                    item.start_at = None
                    item.start_precision = "UNKNOWN"
                service._events[item.id] = item
            snapshot = CalendarApplication(service).query_schedule(now=NOW)
            bundle = CalendarT2IPayloadBuilder().build(snapshot)
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
    links = "".join(f'<section><h2>{item["name"]}</h2><a href="{item["name"]}.png"><img width="432" src="{item["name"]}-mobile.png"></a></section>' for item in checks)
    (output / "index.html").write_text('<meta charset="utf-8"><title>日程预览</title><style>body{background:#edf1f6;font-family:sans-serif}main{display:flex;flex-wrap:wrap;gap:24px}</style><h1>日程优化前后预览</h1><main>'+links+'</main>', encoding="utf-8")
    assert all(c["width"] <= c["viewport"] and c["overflow"] == 0 for c in checks), checks
    print(f"已生成 {len(checks)} 张预览：{output / 'index.html'}")


if __name__ == "__main__":
    asyncio.run(main())

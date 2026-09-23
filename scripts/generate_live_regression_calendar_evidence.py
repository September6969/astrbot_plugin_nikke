"""用当前公开源和已观察生产记录生成 Calendar 去重证据。"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile

from jinja2 import Environment
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_nikke.features.announcement.service import AnnouncementService
from astrbot_plugin_nikke.features.calendar.content_quality import (
    canonical_event_title,
    interval_overlap_ratio,
)
from astrbot_plugin_nikke.features.calendar.schedule_service import ScheduleService
from astrbot_plugin_nikke.ui.payloads.calendar import CalendarT2IPayloadBuilder
from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader


async def main() -> None:
    output = ROOT / "docs/evidence/live_regression_hotfix_20260922"
    runtime = Path(tempfile.gettempdir()) / "nikke-live-regression-calendar-runtime"
    output.mkdir(parents=True, exist_ok=True)
    announcement = AnnouncementService(runtime / "announcements")
    announcement_ok, announcement_message = await announcement.sync_from_source(
        locale="en", deep=False
    )
    service = ScheduleService(
        runtime / "schedule",
        visual_cache=False,
        announcement_service=announcement,
    )
    refresh_ok, refresh_message = await service.refresh_schedule_data()

    gamekee = service._source_datasets["gamekee"]
    trail = next(event for event in gamekee if "TRAIL MARKER" in event.title.upper())
    observed_trail = replace(
        trail,
        id="observed-production:trail-marker-event",
        title="Trail Marker Event",
        primary_source="observed-production",
        sources=["observed-production"],
        detail_url="https://nikke-en.com/observed/trail-marker-event",
        start_at=trail.start_at + timedelta(hours=3),
        end_at=trail.end_at - timedelta(hours=1),
        metadata={},
    )
    service._source_datasets["observed-production"] = [observed_trail]

    raw_count = sum(len(events) for events in service._source_datasets.values())
    merged = service._merge_datasets()
    service._sync_internal_stores(merged)
    service._has_snapshot = True
    service.freshness = "FRESH"
    service.coverage = "COMPLETE"
    now = datetime.now(timezone.utc)
    service.last_updated_at = now.isoformat()

    drink = next(
        event for event in merged.values()
        if canonical_event_title(event.title) == "let s drink pass"
    )
    merged_trail = next(
        event for event in merged.values()
        if canonical_event_title(event.title) == "trail marker"
    )
    payload = CalendarT2IPayloadBuilder().build(service, 30, now)
    template = Environment().from_string(T2ITemplateLoader().load("calendar_schedule"))

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1600, "height": 2400})
        for index, page_payload in enumerate(payload["pages"][:2], 1):
            html = template.render(**{**payload, **page_payload})
            await page.set_viewport_size(page_payload["canvas"])
            await page.set_content(html, wait_until="load")
            await page.evaluate("document.fonts.ready")
            await page.screenshot(
                path=str(output / f"calendar-page-{index}.png"), full_page=True
            )
        await browser.close()

    diagnostics = {
        "generated_at": now.isoformat(),
        "source": "current GameKee + current official InformationFeeds + observed production Trail Marker record",
        "announcement_fetch": {
            "ok": announcement_ok,
            "message": announcement_message,
            "records": announcement.record_count(),
        },
        "schedule_refresh": {"ok": refresh_ok, "message": refresh_message},
        "raw_event_count": raw_count,
        "canonical_event_count": len(merged),
        "page_count": len(payload["pages"]),
        "lets_drink_pass": {
            "count": sum(
                canonical_event_title(event.title) == "let s drink pass"
                for event in merged.values()
            ),
            "sources": drink.sources,
            "match_reason": drink.metadata.get("identity_match", {}).get("reasons", []),
            "event_type": drink.event_type,
        },
        "trail_marker": {
            "count": sum(
                canonical_event_title(event.title) == "trail marker"
                for event in merged.values()
            ),
            "sources": merged_trail.sources,
            "interval_overlap_ratio": interval_overlap_ratio(
                trail.start_at,
                trail.end_at,
                observed_trail.start_at,
                observed_trail.end_at,
            ),
            "match_reason": merged_trail.metadata.get("identity_match", {}).get("reasons", []),
            "event_type": merged_trail.event_type,
        },
    }
    (output / "calendar-diagnostic.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(diagnostics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

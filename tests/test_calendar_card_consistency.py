"""日程卡片等高、页内预算与进度时间精度回归。"""
from datetime import datetime, timedelta, timezone

import pytest

from astrbot_plugin_nikke.ui.payloads.calendar import CalendarT2IPayloadBuilder


def test_mixed_titles_have_equal_heights_without_losing_events():
    builder = CalendarT2IPayloadBuilder()
    items = [
        {"event_id": str(index), "title": "活动", "title_line_count": lines}
        for index, lines in enumerate([1, 2, 1, 3, 1, 2, 1, 2, 1, 1, 2])
    ]
    for item in items:
        item["layout_height"] = builder.active_card_height(item)
    pages = builder._paginate(items, [], global_has_active=True)
    assert [row["event_id"] for page in pages for row in page["active_items"]] == [str(index) for index in range(len(items))]
    for page in pages:
        rows = page["active_items"]
        expected = max(builder.active_card_height(row) for row in rows)
        assert {row["layout_height"] for row in rows} == {expected}
        content = builder.measure_page_content(rows, [], is_first_page=page["page_number"] == 1)
        assert content <= builder.compute_max_content_budget(builder.MAX_CANVAS_H)


@pytest.mark.parametrize("start_precision,end_precision,expected,basis", [
    ("EXACT", "EXACT", 0.625, "exact"),
    ("DATE_ONLY", "EXACT", 0.4, "date"),
    ("EXACT", "DATE_ONLY", 0.4, "date"),
    ("DATE_ONLY", "DATE_ONLY", 0.4, "date"),
    ("UNKNOWN", "EXACT", None, "unknown"),
])
def test_progress_keeps_exact_time_and_date_estimates_distinct(start_precision, end_precision, expected, basis):
    cst = timezone(timedelta(hours=8))
    start = datetime(2026, 10, 20, tzinfo=cst)
    end = datetime(2026, 10, 24, tzinfo=cst)
    now = datetime(2026, 10, 22, 12, tzinfo=cst)
    value, actual_basis = CalendarT2IPayloadBuilder.activity_progress(start, end, now, start_precision, end_precision)
    assert value == expected
    assert actual_basis == basis


def test_missing_and_reversed_dates_do_not_invent_progress():
    now = datetime(2026, 10, 22, tzinfo=timezone.utc)
    assert CalendarT2IPayloadBuilder.activity_progress(None, now, now, "UNKNOWN", "EXACT") == (None, "unknown")
    assert CalendarT2IPayloadBuilder.activity_progress(now, now - timedelta(days=1), now, "DATE_ONLY", "EXACT") == (None, "unknown")


@pytest.mark.asyncio
async def test_browser_cards_are_equal_and_tracks_cover_the_bottom_edge(tmp_path):
    """真实浏览器锁定等高盒模型和进度条贴底位置，防止模板与分页计算漂移。"""
    browser_api = pytest.importorskip('playwright.async_api')
    from jinja2 import Environment
    from astrbot_plugin_nikke.scripts.shared.t2i_preview_fixtures import get_cases
    from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader

    cases = get_cases('calendar_schedule', tmp_path)
    template = T2ITemplateLoader().load('calendar_schedule')
    async with browser_api.async_playwright() as api:
        browser = await api.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            for name in ('normal', 'date-only', 'unknown-end'):
                bundle = cases[name]
                for payload in bundle['pages']:
                    await page.set_viewport_size(payload['canvas'])
                    await page.set_content(Environment(autoescape=False).from_string(template).render(**{**bundle, **payload}))
                    await page.evaluate('document.fonts.ready')
                    cards = await page.evaluate('''() => [...document.querySelectorAll('.active-card')].map(node => {
                        const card = node.getBoundingClientRect(), track = node.querySelector('.card-progress-wrap').getBoundingClientRect();
                        return {height:card.height,bottom:card.bottom,trackBottom:track.bottom,width:card.width,trackWidth:track.width,trackHeight:track.height};
                    })''')
                    if cards:
                        assert max(card['height'] for card in cards) - min(card['height'] for card in cards) <= 1
                    for card in cards:
                        assert abs(card['bottom'] - card['trackBottom']) <= 1
                        assert abs(card['width'] - card['trackWidth']) <= 1
                        assert card['trackHeight'] == 6
        finally:
            await browser.close()

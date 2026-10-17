# SPDX-License-Identifier: GPL-3.0-or-later
"""Gate B: Calendar Operations Feed UI, Pagination, and Fixed Canvas Visual Contracts."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

import pytest
from jinja2 import Environment

from astrbot_plugin_nikke.features.calendar.canonical_models import (
    CanonicalEvent,
    Coverage,
    EventStatus,
    FetchOutcome,
    Freshness,
    SourceHealth,
    TimePrecision,
)
from astrbot_plugin_nikke.features.calendar.models import CalendarActivity
from astrbot_plugin_nikke.features.calendar.service import CalendarService
from astrbot_plugin_nikke.scripts.t2i_preview_fixtures import get_cases
from astrbot_plugin_nikke.ui.renderers.t2i import T2IRenderer
from astrbot_plugin_nikke.ui.t2i_assets import T2IAssetResolver
from astrbot_plugin_nikke.ui.payloads.calendar import CalendarT2IPayloadBuilder
from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader

NOW = datetime(2026, 9, 13, 4, 0, 0, tzinfo=timezone.utc)


def render_html(payload: dict) -> str:
    template = T2ITemplateLoader().load("calendar_schedule")
    return Environment(autoescape=False).from_string(template).render(**payload)



def assert_page_fits_budget(case: dict, page: dict) -> None:
    """确认页面内容测量值与画布高度预算保持一致。"""
    builder = CalendarT2IPayloadBuilder()
    effective_max = case.get("layout_limits", {}).get(
        "effective_max_canvas_height", builder.FALLBACK_MAX_CANVAS_H
    )
    global_has_active = bool(case.get("global_has_active", True))
    content_height = builder.measure_page_content(
        page["active_items"],
        page["next_items"],
        global_has_active=global_has_active,
        is_first_page=page["page_number"] == 1,
    )
    assert page["canvas"]["width"] == builder.CANVAS_W
    assert builder.MIN_CANVAS_H <= page["canvas"]["height"] <= effective_max
    assert content_height <= builder.compute_max_content_budget(effective_max)
    assert page["canvas"]["height"] == builder.compute_canvas_height(content_height, effective_max)

def assert_calendar_dom_fits(metrics: dict) -> None:
    """确认真实浏览器中的内容列表不会越过页脚或画布边界。"""
    assert metrics["contentScrollHeight"] <= metrics["contentClientHeight"] + 1
    assert metrics["documentHeight"] <= metrics["documentClientHeight"] + 1
    for listing in metrics["lists"]:
        assert listing["scrollHeight"] <= listing["clientHeight"] + 1
    for item in metrics["items"]:
        assert item["bottom"] <= metrics["content"]["bottom"] + 1
        assert item["bottom"] <= metrics["footer"]["top"] + 1


class TestOperationsFeedVisualContract:
    def test_fixed_canvas_and_frosted_panel_geometry(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        normal = cases["normal"]
        assert normal["canvas"]["width"] == 1600
        assert CalendarT2IPayloadBuilder.MIN_CANVAS_H <= normal["canvas"]["height"] <= 1600
        assert len(normal["pages"]) == 1
        assert_page_fits_budget(normal, normal["pages"][0])

        html = render_html({**normal, **normal["pages"][0]})
        assert 'width="1600"' in html or 'width: 1600px' in html
        assert f'height: {normal["canvas"]["height"]}px' in html
        assert 'overflow: hidden' in html
        assert 'class="key-visual' in html
        assert 'height: 360px' in html
        assert 'font-size: 64px' in html
        assert 'class="panel"' not in html
        assert 'key-visual--b' not in html

    def test_dynamic_canvas_and_panel_geometry(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        dyn = cases["dynamic-7-active-4-next"]
        assert dyn["canvas"]["width"] == 1600
        assert len(dyn["pages"] ) == 2
        assert [len(page["active_items"]) for page in dyn["pages"]] == [5, 2]
        assert [len(page["next_items"]) for page in dyn["pages"]] == [0, 4]
        for page in dyn["pages"]:
            assert_page_fits_budget(dyn, page)

        first = dyn["pages"][0]
        html = render_html({**dyn, **first})
        assert f'height: {first["canvas"]["height"]}px' in html
        assert 'left: 72px' in html and 'right: 72px' in html

    def test_legacy_progress_bar_contract_purged(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        for name, payload in cases.items():
            html = render_html(payload)
            # Ensure no legacy progress bar elements
            assert "progress-track" not in html, f"Legacy progress-track found in case {name}"
            assert "progress-bar" not in html, f"Legacy progress-bar found in case {name}"
            assert "progress_percent" not in html, f"Legacy progress_percent found in case {name}"
            # Ensure no legacy group titles
            assert "ENDING SOON / 即将结束" not in html, f"Legacy ending soon title in case {name}"
            assert "UPCOMING / 即将开始" not in html, f"Legacy upcoming title in case {name}"

    def test_operations_feed_sections_present(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        normal = cases["normal"]
        html = render_html({**normal, **normal["pages"][0]})
        assert "妮姬日程" in html
        assert "进行中" in html
        assert "即将开始" in html
        assert "第 1 / 1 页" in html
        assert html.count("<footer") == 1
        assert normal["range_event_count"] == normal["active_count_total"] + normal["next_count_total"]
        assert "panel-body" not in html


    def test_all_fixture_pages_fit_measured_height_budget(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        for case in cases.values():
            for page in case["pages"]:
                assert_page_fits_budget(case, page)


class TestCalendarBrowserGeometry:
    """用真实 Chromium DOM 验证 Python 预算与 CSS 盒模型没有漂移。"""

    @pytest.mark.asyncio
    async def test_medium_and_wide_titles_stay_inside_real_event_cards(self, tmp_path):
        playwright_api = pytest.importorskip("playwright.async_api")
        cases = get_cases("calendar_schedule", tmp_path)
        case = cases["title-layout-boundaries"]
        expected_ids = {
            item["event_id"]
            for page_payload in case["pages"]
            for item in page_payload["active_items"] + page_payload["next_items"]
        }
        assert expected_ids == {
            "layout-active-cjk",
            "layout-active-mixed",
            "layout-active-wide",
            "layout-active-full",
            "layout-next-cjk",
            "layout-next-wide",
        }

        async with playwright_api.async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page()
            seen_ids = []
            expected_titles = {
                item["event_id"]: item["full_title"]
                for page_payload in case["pages"]
                for item in page_payload["active_items"] + page_payload["next_items"]
            }
            for page_payload in case["pages"]:
                data = {**case, **page_payload}
                await page.set_viewport_size(
                    {"width": data["canvas"]["width"], "height": data["canvas"]["height"]}
                )
                await page.set_content(render_html(data), wait_until="load")
                await page.evaluate("document.fonts.ready")
                metrics = await page.evaluate("""() => {
                    const rect = element => {
                        const box = element.getBoundingClientRect();
                        return {top: box.top, bottom: box.bottom, left: box.left, right: box.right};
                    };
                    const textRects = element => {
                        const range = document.createRange();
                        range.selectNodeContents(element);
                        return [...range.getClientRects()].filter(box => box.width > 0 && box.height > 0)
                            .map(box => ({top: box.top, bottom: box.bottom, left: box.left, right: box.right}));
                    };
                    const groups = [...document.querySelectorAll('.active-list, .next-list')].map(list => {
                        const active = list.classList.contains('active-list');
                        const rows = [...list.children];
                        const items = rows.map(row => {
                            const title = row.querySelector(active ? '.card-title' : '.next-title');
                            const selectors = active
                                ? ['.card-meta', '.card-title', '.card-side']
                                : ['.next-time', '.next-category', '.next-title', '.next-starts'];
                            const textNodes = selectors.flatMap(selector => [...row.querySelectorAll(selector)])
                                .flatMap(textRects);
                            return {
                                kind: active ? 'active' : 'next',
                                "eventId": row.dataset.eventId,
                                "row": rect(row),
                                "title": title.textContent,
                                "titleBox": rect(title),
                                "titleLines": textRects(title),
                                "endingBadge": row.querySelector('.badge-ending')?.textContent || "",
                                textNodes
                            };
                        });
                        return {kind: active ? 'active' : 'next', items};
                    });
                    const contentArea = document.querySelector('.content-area');
                    const footer = document.querySelector('.panel-footer');
                    return {
                        groups,
                        structure: {
                            contentTag: contentArea.tagName,
                            contentParentTag: contentArea.parentElement.tagName,
                            footerParentTag: footer.parentElement.tagName
                        }
                    };
                }""")
                assert metrics["structure"] == {
                    "contentTag": "SECTION",
                    "contentParentTag": "MAIN",
                    "footerParentTag": "MAIN",
                }
                for group in metrics["groups"]:
                    for index, item in enumerate(group["items"]):
                        seen_ids.append(item["eventId"])
                        assert item["eventId"] in expected_titles
                        assert item["title"] == expected_titles[item["eventId"]], (
                            f"{group['kind']} title is not fully visible: {item}"
                        )
                        page_items = case["pages"][page_payload["page_number"] - 1]["active_items"]
                        page_items += case["pages"][page_payload["page_number"] - 1]["next_items"]
                        expected_lines = next(
                            payload["title_line_count"]
                            for payload in page_items
                            if payload["event_id"] == item["eventId"]
                        )
                        assert len(item["titleLines"]) <= expected_lines, (
                            f"{group['kind']} title wrapped beyond its conservative line budget: {item}"
                        )
                        if item["eventId"] == "layout-active-cjk":
                            assert item["endingBadge"] == "即将结束"
                        assert item["titleBox"]["top"] >= item["row"]["top"] + 1, (
                            f"{group['kind']} title starts outside its own card: {item}"
                        )
                        assert item["titleBox"]["bottom"] <= item["row"]["bottom"] - 1, (
                            f"{group['kind']} title ends outside its own card: {item}"
                        )
                        assert item["textNodes"]
                        assert all(
                            text["top"] >= item["row"]["top"] + 1
                            and text["bottom"] <= item["row"]["bottom"] - 1
                            for text in item["textNodes"]
                        ), f"{group['kind']} text content escapes its event card: {item}"
                        if index:
                            previous = group["items"][index - 1]
                            previous_text_bottom = max(text["bottom"] for text in previous["textNodes"])
                            current_text_top = min(text["top"] for text in item["textNodes"])
                            assert previous_text_bottom <= current_text_top + 1, (
                                f"adjacent {group['kind']} event text overlaps: {previous} / {item}"
                            )
            await browser.close()

        assert len(seen_ids) == len(expected_ids)
        assert set(seen_ids) == expected_ids
        assert len(seen_ids) == len(set(seen_ids))
        first_active = next(
            item
            for page_payload in case["pages"]
            for item in page_payload["active_items"]
            if item["event_id"] == "layout-active-cjk"
        )
        assert first_active["urgency"] == "CLOSING"

    @pytest.mark.asyncio
    async def test_realistic_page_has_no_clipped_next_rows(self, tmp_path):
        playwright_api = pytest.importorskip("playwright.async_api")
        cases = get_cases("calendar_schedule", tmp_path)
        case = cases["realistic-7-active-4-next"]
        assert len(case["pages"]) == 3
        assert sum(len(page["active_items"]) for page in case["pages"]) == 7
        assert sum(len(page["next_items"]) for page in case["pages"]) == 4

        async with playwright_api.async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page()
            for page_payload in case["pages"]:
                data = {**case, **page_payload}
                html = render_html(data)
                await page.set_viewport_size({"width": data["canvas"]["width"], "height": data["canvas"]["height"]})
                await page.set_content(html, wait_until="load")
                await page.evaluate("document.fonts.ready")
                metrics = await page.evaluate("""() => {
                    const rect = node => {
                        const box = node.getBoundingClientRect();
                        return {top: box.top, bottom: box.bottom, height: box.height};
                    };
                    const content = document.querySelector('.content-area');
                    const footer = document.querySelector('.panel-footer');
                    const items = [...document.querySelectorAll('.active-card, .next-row')];
                    const lists = [...document.querySelectorAll('.active-list, .next-list')];
                    return {
                        content: rect(content),
                        footer: rect(footer),
                        contentClientHeight: content.clientHeight,
                        contentScrollHeight: content.scrollHeight,
                        items: items.map(rect),
                        lists: lists.map(node => ({clientHeight: node.clientHeight, scrollHeight: node.scrollHeight})),
                        documentHeight: document.documentElement.scrollHeight,
                        documentClientHeight: document.documentElement.clientHeight
                    };
                }""")
                assert metrics["contentScrollHeight"] <= metrics["contentClientHeight"] + 1
                assert metrics["documentHeight"] <= metrics["documentClientHeight"] + 1
                for listing in metrics["lists"]:
                    assert listing["scrollHeight"] <= listing["clientHeight"] + 1
                for item in metrics["items"]:
                    assert item["bottom"] <= metrics["content"]["bottom"] + 1
                    assert item["bottom"] <= metrics["footer"]["top"] + 1
            await browser.close()


class TestPaginationBudgetAndOversize:
    # ── 基线：少量内容保持 1600x900 ──────────────────────────────
    def test_short_content_retains_min_canvas_height(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        short = cases["dynamic-short"]
        assert len(short["pages"]) == 1
        assert short["canvas"]["height"] > CalendarT2IPayloadBuilder.MIN_CANVAS_H
        assert_page_fits_budget(short, short["pages"][0])

    def test_5_active_fits_on_single_page(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        five = cases["5-active"]
        assert len(five["pages"]) == 1
        assert len(five["pages"][0]["active_items"]) == 5
        assert five["pages"][0]["page_total"] == 1
        assert five["canvas"]["height"] == 1536
        assert_page_fits_budget(five, five["pages"][0])

    def test_8_active_fits_on_single_page(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        eight = cases["8-active"]
        assert [len(page["active_items"]) for page in eight["pages"]] == [5, 3]
        assert len(eight["pages"]) == 2
        assert sum(len(page["active_items"]) for page in eight["pages"]) == 8
        for page in eight["pages"]:
            assert_page_fits_budget(eight, page)

    # ── 核心生产场景：7 Active + 4 Next 合并在单页 ─────────────────
    def test_dynamic_7_active_4_next_single_page(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        case = cases["dynamic-7-active-4-next"]
        assert [len(page["active_items"]) for page in case["pages"]] == [5, 2]
        assert [len(page["next_items"]) for page in case["pages"]] == [0, 4]
        assert sum(len(page["active_items"]) for page in case["pages"]) == 7
        assert sum(len(page["next_items"]) for page in case["pages"]) == 4
        for page in case["pages"]:
            assert_page_fits_budget(case, page)

    # ── 中等规模活动优先单页 ────────────────────────────────────────
    def test_10_active_fits_on_single_page(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        ten = cases["dynamic-10-active"]
        assert [len(page["active_items"]) for page in ten["pages"]] == [5, 5]
        assert sum(len(page["active_items"]) for page in ten["pages"]) == 10
        for page in ten["pages"]:
            assert_page_fits_budget(ten, page)

    def test_9_active_fits_on_single_page(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        nine = cases["9-active"]
        assert [len(page["active_items"]) for page in nine["pages"]] == [5, 4]
        assert sum(len(page["active_items"]) for page in nine["pages"]) == 9
        for page in nine["pages"]:
            assert_page_fits_budget(nine, page)

    def test_12_active_6_next_fits_on_single_page(self, tmp_path):
        """12 Active + 6 Next 按真实盒高完整保留，不依赖旧的人工单页高度。"""
        cases = get_cases("calendar_schedule", tmp_path)
        twelve_six = cases["dynamic-12-active-6-next"]
        assert sum(len(page["active_items"]) for page in twelve_six["pages"]) == 12
        assert sum(len(page["next_items"]) for page in twelve_six["pages"]) == 6
        assert len(twelve_six["pages"]) >= 1
        for page in twelve_six["pages"]:
            assert CalendarT2IPayloadBuilder.MIN_CANVAS_H <= page["canvas"]["height"] <= 1600

    def test_dynamic_20_active_fits_on_single_page(self, tmp_path):
        """20 Active 在无 KV 时按真实预算分页，但不得丢失或越过高度上限。"""
        cases = get_cases("calendar_schedule", tmp_path)
        twenty = cases["dynamic-20-active"]
        assert sum(len(page["active_items"]) for page in twenty["pages"]) == 20
        assert len(twenty["pages"]) >= 1
        for page in twenty["pages"]:
            assert CalendarT2IPayloadBuilder.MIN_CANVAS_H <= page["canvas"]["height"] <= 1600

    def test_16_active_fits_on_single_page(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        sixteen = cases["16-active"]
        assert [len(page["active_items"]) for page in sixteen["pages"]] == [5, 5, 5, 1]
        assert sum(len(page["active_items"]) for page in sixteen["pages"]) == 16
        for page in sixteen["pages"]:
            assert_page_fits_budget(sixteen, page)

    def test_17_active_fits_on_single_page_without_artificial_cap(self, tmp_path):
        """17 Active 不受人工 16 条上限影响，按动态预算完整分页。"""
        cases = get_cases("calendar_schedule", tmp_path)
        seventeen = cases["17-active"]
        assert sum(len(page["active_items"]) for page in seventeen["pages"]) == 17
        for page in seventeen["pages"]:
            assert CalendarT2IPayloadBuilder.MIN_CANVAS_H <= page["canvas"]["height"] <= 1600

    def test_realistic_7_active_4_next_uses_production_mix(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        case = cases["realistic-7-active-4-next"]
        pages = case["pages"]
        assert len(pages) == 3
        active = [item for page in pages for item in page["active_items"]]
        upcoming = [item for page in pages for item in page["next_items"]]
        assert len(active) == 7 and len(upcoming) == 4
        assert all(item.get("progress_pct") is not None for item in active)
        assert any(item.get("is_next_ending") for item in active)
        assert any(item.get("is_oversize") for item in active)
        for page in pages:
            assert_page_fits_budget(case, page)

    # ── 兼容旧名 8-active-paged ──────────────────────────────────
    def test_8_active_paged_single_page_compat(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        eight = cases["8-active-paged"]
        assert [len(page["active_items"]) for page in eight["pages"]] == [5, 3]
        assert sum(len(page["active_items"]) for page in eight["pages"]) == 8
        for page in eight["pages"]:
            assert_page_fits_budget(eight, page)

    # ── 长标题预算验证 ────────────────────────────────────────────
    def test_dynamic_long_titles_no_overflow(self, tmp_path):
        """Case 6: 多条长标题活动，验证预算不溢出且高度 <= MAX_CANVAS_H."""
        cases = get_cases("calendar_schedule", tmp_path)
        long_case = cases["dynamic-long-titles"]
        for page in long_case["pages"]:
            assert page["canvas"]["height"] <= CalendarT2IPayloadBuilder.MAX_CANVAS_H
            assert page["canvas"]["height"] >= CalendarT2IPayloadBuilder.MIN_CANVAS_H
            html = render_html({**long_case, **page})
            assert "is-long" in html

    def test_long_title_budget_still_prevents_overflow(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        mixed = cases["8-active-mixed-long"]
        builder = CalendarT2IPayloadBuilder()
        total = sum(len(p["active_items"]) for p in mixed["pages"])
        assert total == 8
        for page in mixed["pages"]:
            content_h = builder.measure_page_content(
                page["active_items"],
                page["next_items"],
            )
            assert content_h <= builder.MAX_CONTENT_BUDGET

    # ── progress_pct 验证 ─────────────────────────────────────────
    def test_8_active_with_progress_all_have_pct(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        progress_case = cases["8-active-with-progress"]
        active = [item for page in progress_case["pages"] for item in page["active_items"]]
        assert len(active) == 8
        for item in active:
            assert item.get("progress_pct") is not None
            assert 0.0 <= item["progress_pct"] <= 1.0
        for page in progress_case["pages"]:
            assert_page_fits_budget(progress_case, page)

    def test_8_active_render_has_footer_and_page_badge(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        eight = cases["8-active"]
        html = render_html({**eight, **eight["pages"][0]})
        assert "panel-footer" in html
        assert "第 1 / 2 页" in html
        assert "下一页：/妮姬 日程 14 2" in html

    def test_4_active_8_next_multi_page_partition(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        mixed = cases["4-active-8-next"]
        total_active_placed = sum(len(p["active_items"]) for p in mixed["pages"])
        total_next_placed = sum(len(p["next_items"]) for p in mixed["pages"])
        assert total_active_placed == 4
        assert total_next_placed == 8

    def test_oversize_title_stays_complete_with_dynamic_page_budget(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        oversize = cases["oversize-title"]
        pages = oversize["pages"]
        first_page_item = pages[0]["active_items"][0]
        assert first_page_item["is_oversize"]
        assert first_page_item["title"] == first_page_item["full_title"]
        assert first_page_item["title_line_count"] >= 2

        html = render_html({**oversize, **pages[0]})
        assert "is-oversize" in html
        assert first_page_item["full_title"] in html
        assert "长标题已省略，完整内容见文本日程" not in html


class TestGlobalVsPageEmptyState:
    def test_next_only_shows_empty_active_on_page_1(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        next_only = cases["next-only"]
        assert not next_only["global_has_active"]
        assert len(next_only["pages"]) >= 1

        p1_html = render_html({**next_only, **next_only["pages"][0]})
        assert "当前没有进行中的活动" in p1_html
        assert "即将开始" in p1_html

    def test_page_2_with_no_active_never_shows_no_active_operations_if_global_has_active(self, tmp_path):
        builder = CalendarT2IPayloadBuilder()
        active_items = [{"event_id": f"a{i}", "title": f"A{i}", "full_title": f"A{i}", "category": "活动", "category_code": "event", "time_range": "", "remaining": "1D", "is_next_ending": False, "urgency": "NORMAL", "is_long_title": False, "is_oversize": False, "end_precision": "EXACT", "progress_pct": None} for i in range(16)]
        next_items = [{"event_id": f"n{i}", "title": f"N{i}", "full_title": f"N{i}", "category": "活动", "category_code": "event", "start_time_display": "09.20", "starts_in": "3 天后开始", "start_precision": "EXACT", "is_long_title": False, "is_oversize": False} for i in range(10)]

        pages = builder._paginate(active_items, next_items, global_has_active=True)
        assert len(pages) >= 2
        p_last = pages[-1]
        bundle_meta = {
            "canvas": p_last["canvas"],
            "panel": p_last["panel"],
            "global_has_active": True,
            "range_event_count": len(active_items) + len(next_items),
            "active_count_total": len(active_items),
            "horizon_days": 14,
            "source_display": "GameKee",
            "freshness": "FRESH",
            "coverage": "COMPLETE",
            "available": True,
        }
        p_last_html = render_html({**bundle_meta, **p_last})
        if not p_last["active_items"]:
            assert "当前没有进行中的活动" not in p_last_html
            assert "即将开始" in p_last_html


class TestUrgencyAndPrecisionRules:
    def test_critical_urgency_for_exact_end_within_one_hour(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        critical_case = cases["critical"]
        active_items = critical_case["active_items"]
        assert active_items[0]["urgency"] == "CRITICAL"
        html = render_html(critical_case)
        assert "urgency-critical" in html
        assert "即将结束" in html

    def test_date_only_precision_never_produces_hourly_urgency(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        date_only_case = cases["date-only"]
        for item in date_only_case["active_items"]:
            assert item["urgency"] == "" or item["urgency"] == "NORMAL"
            assert item["end_precision"] == "DATE_ONLY"
        html = render_html(date_only_case)
        assert "剩余日期级" in html
        assert "badge-urgency badge-critical" not in html
        assert "badge-urgency badge-urgent" not in html
        assert "badge-urgency badge-closing" not in html

    def test_unknown_end_never_produces_next_ending(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        unknown_end_case = cases["unknown-end"]
        for item in unknown_end_case["active_items"]:
            assert not item["is_next_ending"]
            assert item["remaining"] == "结束时间未知"
        html = render_html(unknown_end_case)
        assert "时间待确认" in html
        assert "NEXT ENDING" not in html


    def test_upcoming_start_precision_controls_date_and_countdown_detail(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        case = cases["upcoming-precision-mix"]
        upcoming = {
            item["event_id"]: item
            for page in case["pages"]
            for item in page["next_items"]
        }
        exact = upcoming["precision-1"]
        date_only = upcoming["precision-2"]
        unknown = upcoming["precision-3"]

        assert exact["start_precision"] == "EXACT"
        assert ":" in exact["start_time_display"]
        assert "后开始" in exact["starts_in"]
        assert date_only["start_precision"] == "DATE_ONLY"
        assert ":" not in date_only["start_time_display"]
        assert "日期级" in date_only["starts_in"]
        assert unknown["start_precision"] == "UNKNOWN"
        assert unknown["start_time_display"] == "时间待定"
        assert unknown["starts_in"] == "即将开始"
        assert exact["category"] == "限时双倍"
        assert date_only["category"] == "活动通行证"

        html = render_html({**case, **case["pages"][0]})
        assert "限时双倍" in html
        assert "活动通行证" in html
        assert "时间待确认" in html

class TestBackgroundAndMultiPageRendering:
    def test_fallback_gradient_when_no_background_uri(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        no_bg = cases["no-background"]
        assert no_bg["background_data_uri"] is None
        html = render_html(no_bg)
        assert "no-poster" in html
        assert "活动图片暂不可用" in html

    def test_background_cover_crop_dimensions(self):
        """Case 7: Background Resolver scales and cover-crops for dynamic canvas height."""
        from PIL import Image
        resolver = T2IAssetResolver()
        # Create a synthetic 9:16 portrait image (1080x1920)
        img = Image.new("RGBA", (1080, 1920), color=(100, 150, 200, 255))
        uri_900 = resolver.encode(img, size=(1600, 900), cover_crop=True)
        assert uri_900 is not None and uri_900.startswith("data:image/png;base64,")

        uri_1200 = resolver.encode(img, size=(1600, 1200), cover_crop=True)
        assert uri_1200 is not None and uri_1200.startswith("data:image/png;base64,")
        # Different target sizes must produce different cache entries / URIs
        assert uri_900 != uri_1200

    def test_calendar_webp_background_embeds_verified_source_bytes(self, tmp_path):
        import base64
        from io import BytesIO
        from PIL import Image

        webp_path = tmp_path / "calendar-kv.webp"
        Image.new("RGB", (490, 162), (12, 34, 56)).save(webp_path, "WEBP", quality=92)
        source_bytes = webp_path.read_bytes()

        builder = CalendarT2IPayloadBuilder()
        uri = builder._encode_background(webp_path)

        assert uri is not None and uri.startswith("data:image/webp;base64,")
        embedded_bytes = base64.b64decode(uri.split(",", 1)[1])
        assert embedded_bytes == source_bytes
        with Image.open(BytesIO(embedded_bytes)) as embedded:
            assert embedded.format == "WEBP"
            assert embedded.size == (490, 162)

    def test_non_webp_calendar_background_keeps_png_resolver_fallback(self, tmp_path):
        from PIL import Image

        jpeg_path = tmp_path / "calendar-kv.jpg"
        Image.new("RGB", (490, 162), (12, 34, 56)).save(jpeg_path, "JPEG", quality=90)

        uri = CalendarT2IPayloadBuilder()._encode_background(jpeg_path)

        assert uri is not None and uri.startswith("data:image/png;base64,")

    @pytest.mark.asyncio
    async def test_multi_page_sequential_rendering_in_t2i_renderer(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        overflow_case = cases["portrait-kv-overflow"]
        assert len(overflow_case["pages"]) >= 2

        render_calls = []
        viewport_calls = []
        async def fake_render(template, payload, options):
            render_calls.append(payload["page_number"])
            viewport_calls.append(options.get("viewport"))
            return f"rendered_page_{payload['page_number']}.png"

        renderer = T2IRenderer(fake_render, assets=Mock())
        results = await renderer.render_view("calendar_schedule", overflow_case)

        assert isinstance(results, list)
        assert len(results) >= 2
        assert render_calls == list(range(1, len(results) + 1))
        # Case 8: Renderer passes dynamic viewport matching each page's canvas
        for i, p in enumerate(overflow_case["pages"]):
            assert viewport_calls[i] == {
                "width": p["canvas"]["width"],
                "height": p["canvas"]["height"],
            }

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_renderer_viewport_matches_dynamic_canvas_height(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        dyn = cases["dynamic-7-active-4-next"]
        captured_viewports = []

        async def fake_render(template, payload, options):
            captured_viewports.append(options.get("viewport"))
            return f"page-{payload['page_number']}.png"

        renderer = T2IRenderer(fake_render, assets=Mock())
        await renderer.render_view("calendar_schedule", dyn)

        assert captured_viewports == [
            {"width": page["canvas"]["width"], "height": page["canvas"]["height"]}
            for page in dyn["pages"]
        ]

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_single_page_returns_single_string(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        short = cases["dynamic-short"]
        assert len(short["pages"]) == 1

        async def fake_render(template, payload, options):
            return "single_page.png"

        renderer = T2IRenderer(fake_render, assets=Mock())
        result = await renderer.render_view("calendar_schedule", short)

        assert isinstance(result, str)
        assert result == "single_page.png"


class TestSourceBoundedDynamicCanvasHeight:
    """Base-bounded (1600) + Source-extended (最高2400) 动态画布高度与分页合约测试。"""

    def test_landscape_kv_uses_base_max_height(self):
        """16:9 landscape (1920x1080) -> scaled 900, 但保持 base max == 1600 (绝不压缩至 900)."""
        effective_max, w, h, scaled_h = CalendarT2IPayloadBuilder._compute_effective_max_canvas_height((1920, 1080))
        assert scaled_h == 900
        assert effective_max == 1600

    def test_square_kv_uses_base_or_source_height(self):
        """1600x1600 square -> scaled 1600, effective == 1600."""
        effective_max, w, h, scaled_h = CalendarT2IPayloadBuilder._compute_effective_max_canvas_height((1600, 1600))
        assert scaled_h == 1600
        assert effective_max == 1600

    def test_portrait_1440_1920_extends_max(self):
        """4:3-ish portrait (1440x1920) -> scaled 2133, effective_max == 2133 (成功扩展基础高度)."""
        effective_max, w, h, scaled_h = CalendarT2IPayloadBuilder._compute_effective_max_canvas_height((1440, 1920))
        assert scaled_h == 2133
        assert effective_max == 2133

    def test_portrait_1080_1920_hits_absolute_cap(self):
        """标准 9:16 KV (1080x1920) -> scaled ~2844, 命中 absolute cap == 2400."""
        effective_max, w, h, scaled_h = CalendarT2IPayloadBuilder._compute_effective_max_canvas_height((1080, 1920))
        assert scaled_h == 2844
        assert effective_max == 2400

    def test_no_kv_uses_base_max(self):
        """no background -> effective_max == 1600 (FALLBACK_MAX_CANVAS_H)."""
        effective_max, w, h, scaled_h = CalendarT2IPayloadBuilder._compute_effective_max_canvas_height(None)
        assert effective_max == 1600
        assert scaled_h is None

    def test_7_active_4_next_landscape_kv_fits_on_single_page(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        case = cases["landscape-kv-7-active-4-next"]
        assert len(case["pages"]) == 2
        assert [len(page["active_items"]) for page in case["pages"]] == [5, 2]
        assert [len(page["next_items"]) for page in case["pages"]] == [0, 4]
        assert case["layout_limits"]["effective_max_canvas_height"] == 1600
        assert case["layout_limits"]["height_policy"] == "base"
        for page in case["pages"]:
            assert_page_fits_budget(case, page)

    def test_20_active_landscape_kv_fits_on_single_page(self, tmp_path):
        """20 Active + landscape KV 按基础 1600 预算完整保留。"""
        cases = get_cases("calendar_schedule", tmp_path)
        c = cases["landscape-kv-20-active"]
        assert sum(len(page["active_items"]) for page in c["pages"]) == 20
        assert len(c["pages"]) >= 1
        for page in c["pages"]:
            assert CalendarT2IPayloadBuilder.MIN_CANVAS_H <= page["canvas"]["height"] <= 1600
        assert c["layout_limits"]["effective_max_canvas_height"] == 1600
        assert c["layout_limits"]["height_policy"] == "base"

    def test_25_active_landscape_kv_paginates_at_1600_base_max(self, tmp_path):
        """25 Active + landscape KV 超过 1600 基础预算时正常触发分页。"""
        cases = get_cases("calendar_schedule", tmp_path)
        c = cases["landscape-kv-25-active"]
        assert len(c["pages"]) >= 2
        assert sum(len(page["active_items"]) for page in c["pages"]) == 25
        assert c["layout_limits"]["effective_max_canvas_height"] == 1600
        for page in c["pages"]:
            assert CalendarT2IPayloadBuilder.MIN_CANVAS_H <= page["canvas"]["height"] <= 1600

    def test_case_5_20_normal_active_portrait_kv_single_page(self, tmp_path):
        """Case 5: 20 normal Active + 9:16 KV 在源扩展高度内完整保留。"""
        cases = get_cases("calendar_schedule", tmp_path)
        c = cases["portrait-kv-20-active"]
        assert sum(len(page["active_items"]) for page in c["pages"]) == 20
        for page in c["pages"]:
            assert CalendarT2IPayloadBuilder.MIN_CANVAS_H <= page["canvas"]["height"] <= 2400
        assert c["layout_limits"]["effective_max_canvas_height"] == 2400
        assert c["layout_limits"]["height_policy"] == "absolute_capped"

    def test_case_6_30_normal_active_portrait_kv_single_page(self, tmp_path):
        """Case 6: 30 normal Active + 9:16 KV 在源扩展高度内完整保留。"""
        cases = get_cases("calendar_schedule", tmp_path)
        c = cases["portrait-kv-30-active"]
        assert sum(len(page["active_items"]) for page in c["pages"]) == 30
        for page in c["pages"]:
            assert CalendarT2IPayloadBuilder.MIN_CANVAS_H <= page["canvas"]["height"] <= 2400
        assert c["layout_limits"]["effective_max_canvas_height"] == 2400
        assert c["layout_limits"]["height_policy"] == "absolute_capped"

    def test_case_7_45_active_portrait_kv_overflow_paginates(self, tmp_path):
        """Case 7: 45 Active + 9:16 KV -> page_total >= 2, 每页 <= effective_max_canvas_h (2400)."""
        cases = get_cases("calendar_schedule", tmp_path)
        c = cases["portrait-kv-overflow"]
        assert len(c["pages"]) >= 2
        assert sum(len(page["active_items"]) for page in c["pages"]) == 45
        for page in c["pages"]:
            assert page["canvas"]["height"] <= 2400
            assert page["canvas"]["height"] >= 900

    def test_case_9_same_background_source_across_pages(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        case = cases["portrait-kv-overflow"]
        assert len(case["pages"]) >= 2
        backgrounds = [page["background_data_uri"] for page in case["pages"]]
        assert all(background is not None for background in backgrounds)
        assert len(set(backgrounds)) == 1
        for page in case["pages"]:
            assert_page_fits_budget(case, page)

    def test_no_kv_overflow_paginates_at_1600(self, tmp_path):
        """无背景图时使用 1600 fallback 上限分页，且不丢失 Active。"""
        cases = get_cases("calendar_schedule", tmp_path)
        c = cases["no-kv-overflow"]
        assert len(c["pages"]) >= 2
        assert sum(len(page["active_items"]) for page in c["pages"]) == 25
        assert c["layout_limits"]["effective_max_canvas_height"] == 1600
        assert c["layout_limits"]["height_policy"] == "base"
        for page in c["pages"]:
            assert CalendarT2IPayloadBuilder.MIN_CANVAS_H <= page["canvas"]["height"] <= 1600

    def test_duck_typed_snapshot_builds_without_calling_bool_has_snapshot(self):
        """跨模块或鸭子类型 CalendarScheduleSnapshot 不会抛出 'bool' object is not callable."""
        from datetime import datetime, timezone
        from astrbot_plugin_nikke.features.calendar.canonical_models import QueryContext

        class ExternalSnapshot:
            def __init__(self):
                self.context = QueryContext(
                    now=datetime.now(timezone.utc),
                    snapshot_version="1.0.0",
                    events=[],
                    source_health={},
                )
                self.horizon_days = 14
                self.has_snapshot = True  # bool, NOT callable
                self.activity_count = 0
                self.data_quality = "HIGH"
                self.last_updated_at = None
                self.sync_warning = ""
                self.background_path = None
                self.fallback_text = "fallback"
                self.service_available = True

        snap = ExternalSnapshot()
        builder = CalendarT2IPayloadBuilder()
        bundle = builder.build(snap)
        assert bundle["available"] is True
        assert bundle["fallback_text"] == "fallback"
        assert len(bundle["pages"]) == 1



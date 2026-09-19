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
from astrbot_plugin_nikke.ui.t2i_payloads import CalendarT2IPayloadBuilder
from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader

NOW = datetime(2026, 9, 13, 4, 0, 0, tzinfo=timezone.utc)


def render_html(payload: dict) -> str:
    template = T2ITemplateLoader().load("calendar_schedule")
    return Environment(autoescape=False).from_string(template).render(**payload)


class TestOperationsFeedVisualContract:
    def test_fixed_canvas_and_frosted_panel_geometry(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        normal = cases["normal"]
        assert normal["canvas"] == {"width": 1600, "height": 900}
        html = render_html(normal)

        # 1600x900 viewport & canvas constraints
        assert 'width="1600"' in html or 'width: 1600px' in html or 'width:1600px' in html
        assert 'height: 900px' in html or 'height:900px' in html
        assert 'overflow: hidden' in html or 'overflow:hidden' in html

        # Centered 1180x730 frosted glass panel
        assert 'width: 1180px' in html or 'width:1180px' in html
        assert 'height: 730px' in html or 'height:730px' in html
        assert 'backdrop-filter: blur(28px)' in html or 'backdrop-filter:blur(28px)' in html

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
        html = render_html(normal)
        assert "OPERATIONS FEED" in html
        assert "ACTIVE OPERATIONS // 进行中任务" in html
        assert "NEXT OPERATIONS // 预告任务" in html
        assert "PAGE 1 / 1" in html


class TestPaginationBudgetAndOversize:
    def test_5_active_fits_on_single_page(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        five = cases["5-active"]
        assert len(five["pages"]) == 1
        assert len(five["pages"][0]["active_items"]) == 5
        assert five["pages"][0]["page_total"] == 1

    def test_8_active_splits_into_two_pages(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        eight = cases["8-active-paged"]
        assert len(eight["pages"]) == 2
        assert len(eight["pages"][0]["active_items"]) == 5
        assert len(eight["pages"][1]["active_items"]) == 3
        assert eight["pages"][0]["page_total"] == 2
        assert eight["pages"][1]["page_total"] == 2

    def test_12_active_splits_into_three_pages(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        twelve = cases["12-active-paged"]
        assert len(twelve["pages"]) == 3
        assert len(twelve["pages"][0]["active_items"]) == 5
        assert len(twelve["pages"][1]["active_items"]) == 5
        assert len(twelve["pages"][2]["active_items"]) == 2

    def test_4_active_8_next_multi_page_partition(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        mixed = cases["4-active-8-next"]
        assert len(mixed["pages"]) >= 2
        # Page 1 has 4 active items and some next items
        p1 = mixed["pages"][0]
        assert len(p1["active_items"]) == 4
        assert p1["show_active_header"]
        # Total items placed across all pages equals total input
        total_active_placed = sum(len(p["active_items"]) for p in mixed["pages"])
        total_next_placed = sum(len(p["next_items"]) for p in mixed["pages"])
        assert total_active_placed == 4
        assert total_next_placed == 8

    def test_oversize_title_policy_dedicated_page_and_ellipsis(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        oversize = cases["oversize-title"]
        pages = oversize["pages"]
        # The oversize item should have is_oversize=True
        first_page_item = pages[0]["active_items"][0]
        assert first_page_item["is_oversize"]
        # Display title is visually truncated with ellipsis while full_title is preserved
        assert first_page_item["title"].endswith("...")
        assert len(first_page_item["full_title"]) > len(first_page_item["title"])

        html = render_html({**oversize, **pages[0]})
        assert "is-oversize" in html


class TestGlobalVsPageEmptyState:
    def test_next_only_shows_empty_active_on_page_1(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        next_only = cases["next-only"]
        assert not next_only["global_has_active"]
        assert len(next_only["pages"]) >= 1

        p1_html = render_html({**next_only, **next_only["pages"][0]})
        assert "NO ACTIVE OPERATIONS" in p1_html
        assert "NEXT OPERATIONS" in p1_html

    def test_page_2_with_no_active_never_shows_no_active_operations_if_global_has_active(self, tmp_path):
        # When global_has_active=True, subsequent pages that only have next_items MUST NOT show NO ACTIVE OPERATIONS
        builder = CalendarT2IPayloadBuilder()
        active_items = [{"event_id": f"a{i}", "title": f"A{i}", "full_title": f"A{i}", "category": "活动", "category_code": "event", "time_range": "", "remaining": "1D", "is_next_ending": False, "urgency": "NORMAL", "is_long_title": False, "is_oversize": False, "end_precision": "EXACT"} for i in range(5)]
        next_items = [{"event_id": f"n{i}", "title": f"N{i}", "full_title": f"N{i}", "category": "活动", "category_code": "event", "start_time_display": "09.20", "starts_in": "3D", "is_long_title": False, "is_oversize": False} for i in range(4)]

        pages = builder._paginate(active_items, next_items, global_has_active=True)
        assert len(pages) == 2
        # Page 2 has only next_items
        p2 = pages[1]
        assert p2["active_items"] == []
        assert len(p2["next_items"]) > 0

        # Render Page 2
        bundle_meta = {
            "canvas": {"width": 1600, "height": 900},
            "global_has_active": True,
            "active_count_total": 5,
            "horizon_days": 14,
            "timezone_display": "UTC+8",
            "available": True,
        }
        p2_html = render_html({**bundle_meta, **p2})
        assert "NO ACTIVE OPERATIONS" not in p2_html
        assert "NEXT OPERATIONS" in p2_html


class TestUrgencyAndPrecisionRules:
    def test_critical_urgency_for_exact_end_within_one_hour(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        critical_case = cases["critical"]
        active_items = critical_case["active_items"]
        assert active_items[0]["urgency"] == "CRITICAL"
        html = render_html(critical_case)
        assert "urgency-critical" in html
        assert "CRITICAL" in html

    def test_date_only_precision_never_produces_hourly_urgency(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        date_only_case = cases["date-only"]
        for item in date_only_case["active_items"]:
            assert item["urgency"] == "" or item["urgency"] == "NORMAL"
        html = render_html(date_only_case)
        assert "badge-urgency badge-critical" not in html
        assert "badge-urgency badge-urgent" not in html
        assert "badge-urgency badge-closing" not in html
        assert "CRITICAL" not in html
        assert "URGENT" not in html
        assert "CLOSING" not in html

    def test_unknown_end_never_produces_next_ending(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        unknown_end_case = cases["unknown-end"]
        for item in unknown_end_case["active_items"]:
            assert not item["is_next_ending"]
            assert item["remaining"] == "结束时间未知"
        html = render_html(unknown_end_case)
        assert "NEXT ENDING" not in html


class TestBackgroundAndMultiPageRendering:
    def test_fallback_gradient_when_no_background_uri(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        no_bg = cases["no-background"]
        assert no_bg["background_data_uri"] is None
        html = render_html(no_bg)
        assert "canvas-bg-fallback" in html

    @pytest.mark.asyncio
    async def test_multi_page_sequential_rendering_in_t2i_renderer(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        eight = cases["8-active-paged"]
        assert len(eight["pages"]) == 2

        render_calls = []
        async def fake_render(template, payload, options):
            render_calls.append(payload["page_number"])
            return f"rendered_page_{payload['page_number']}.png"

        renderer = T2IRenderer(fake_render, assets=Mock())
        results = await renderer.render_view("calendar_schedule", eight)

        assert isinstance(results, list)
        assert len(results) == 2
        assert results == ["rendered_page_1.png", "rendered_page_2.png"]
        assert render_calls == [1, 2]

    @pytest.mark.asyncio
    async def test_single_page_returns_single_string(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        five = cases["5-active"]
        assert len(five["pages"]) == 1

        async def fake_render(template, payload, options):
            return "single_page.png"

        renderer = T2IRenderer(fake_render, assets=Mock())
        result = await renderer.render_view("calendar_schedule", five)

        assert isinstance(result, str)
        assert result == "single_page.png"

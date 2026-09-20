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

        # 1600x900 viewport & canvas constraints for short/base content
        assert 'width="1600"' in html or 'width: 1600px' in html or 'width:1600px' in html
        assert 'height: 900px' in html or 'height:900px' in html
        assert 'overflow: hidden' in html or 'overflow:hidden' in html

        # Centered 1180x730 frosted glass panel
        assert 'width: 1180px' in html or 'width:1180px' in html
        assert 'height: 730px' in html or 'height:730px' in html
        assert 'backdrop-filter: blur(28px)' in html or 'backdrop-filter:blur(28px)' in html

    def test_dynamic_canvas_and_panel_geometry(self, tmp_path):
        """Dynamic content expands canvas height within [900, 1600] and adjusts panel."""
        cases = get_cases("calendar_schedule", tmp_path)
        dyn = cases["dynamic-7-active-4-next"]
        assert dyn["canvas"]["width"] == 1600
        assert 900 < dyn["canvas"]["height"] <= 1600
        assert dyn["panel"]["width"] == 1180
        assert dyn["panel"]["height"] == dyn["canvas"]["height"] - 170

        html = render_html({**dyn, **dyn["pages"][0]})
        assert f"height: {dyn['canvas']['height']}px" in html
        assert f"height: {dyn['panel']['height']}px" in html

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
    # ── 基线：少量内容保持 1600x900 ──────────────────────────────
    def test_short_content_retains_min_canvas_height(self, tmp_path):
        """Case 1: 少量内容 (2 Active) -> canvas.height == 900, panel == 730."""
        cases = get_cases("calendar_schedule", tmp_path)
        short = cases["dynamic-short"]
        assert len(short["pages"]) == 1
        assert short["canvas"]["height"] == 900
        assert short["panel"]["height"] == 730

    def test_5_active_fits_on_single_page(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        five = cases["5-active"]
        assert len(five["pages"]) == 1
        assert len(five["pages"][0]["active_items"]) == 5
        assert five["pages"][0]["page_total"] == 1
        assert five["canvas"]["height"] == 900

    def test_8_active_fits_on_single_page(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        eight = cases["8-active"]
        assert len(eight["pages"]) == 1
        assert len(eight["pages"][0]["active_items"]) == 8
        assert eight["canvas"]["height"] == 900

    # ── 核心生产场景：7 Active + 4 Next 合并在单页 ─────────────────
    def test_dynamic_7_active_4_next_single_page(self, tmp_path):
        """Case 2: 7 Active + 4 Next 在同一页，画布高度动态扩展 (>900, <=1600)."""
        cases = get_cases("calendar_schedule", tmp_path)
        case = cases["dynamic-7-active-4-next"]
        assert len(case["pages"]) == 1, (
            f"Expected 1 page for 7 active + 4 next, got {len(case['pages'])}"
        )
        p1 = case["pages"][0]
        assert len(p1["active_items"]) == 7
        assert len(p1["next_items"]) == 4
        assert p1["page_total"] == 1
        assert 900 < p1["canvas"]["height"] <= 1600
        assert p1["panel"]["height"] == p1["canvas"]["height"] - 170

    # ── 中等规模活动优先单页 ────────────────────────────────────────
    def test_10_active_fits_on_single_page(self, tmp_path):
        """Case 3: 10 Active 优先单页动态增长."""
        cases = get_cases("calendar_schedule", tmp_path)
        ten = cases["dynamic-10-active"]
        assert len(ten["pages"]) == 1
        assert len(ten["pages"][0]["active_items"]) == 10
        assert 900 < ten["canvas"]["height"] <= 1600

    def test_9_active_fits_on_single_page(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        nine = cases["9-active"]
        assert len(nine["pages"]) == 1
        assert len(nine["pages"][0]["active_items"]) == 9
        assert 900 < nine["canvas"]["height"] <= 1600

    def test_12_active_6_next_fits_on_single_page(self, tmp_path):
        """12 Active + 6 Next 在最大高度预算 (1600) 内同页显示."""
        cases = get_cases("calendar_schedule", tmp_path)
        twelve_six = cases["dynamic-12-active-6-next"]
        assert len(twelve_six["pages"]) == 1
        p1 = twelve_six["pages"][0]
        assert len(p1["active_items"]) == 12
        assert len(p1["next_items"]) == 6
        assert 900 < p1["canvas"]["height"] <= 1600

    def test_dynamic_20_active_fits_on_single_page(self, tmp_path):
        """20 Active 在无KV时 (回退1600上限内) 也可单页容纳 (1588 <= 1600)."""
        cases = get_cases("calendar_schedule", tmp_path)
        twenty = cases["dynamic-20-active"]
        assert len(twenty["pages"]) == 1
        assert len(twenty["pages"][0]["active_items"]) == 20
        assert twenty["pages"][0]["canvas"]["height"] == 1588

    def test_16_active_fits_on_single_page(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        sixteen = cases["16-active"]
        assert len(sixteen["pages"]) == 1
        assert len(sixteen["pages"][0]["active_items"]) == 16
        assert sixteen["canvas"]["height"] <= 1600

    def test_17_active_fits_on_single_page_without_artificial_cap(self, tmp_path):
        """17 Active 去除人工 16 cap 后正常在动态高度中单页容纳 (1408 <= 1600)."""
        cases = get_cases("calendar_schedule", tmp_path)
        seventeen = cases["17-active"]
        assert len(seventeen["pages"]) == 1
        assert len(seventeen["pages"][0]["active_items"]) == 17
        assert seventeen["pages"][0]["canvas"]["height"] <= 1600

    # ── 兼容旧名 8-active-paged ──────────────────────────────────
    def test_8_active_paged_single_page_compat(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        eight = cases["8-active-paged"]
        assert len(eight["pages"]) == 1
        assert len(eight["pages"][0]["active_items"]) == 8

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
        prog = cases["8-active-with-progress"]
        assert len(prog["pages"]) == 1
        for item in prog["pages"][0]["active_items"]:
            assert item.get("progress_pct") is not None
            assert 0.0 <= item["progress_pct"] <= 1.0

    def test_8_active_render_has_footer_and_page_badge(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        eight = cases["8-active"]
        html = render_html({**eight, **eight["pages"][0]})
        assert "panel-footer" in html
        assert "PAGE 1 / 1" in html

    def test_4_active_8_next_multi_page_partition(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        mixed = cases["4-active-8-next"]
        total_active_placed = sum(len(p["active_items"]) for p in mixed["pages"])
        total_next_placed = sum(len(p["next_items"]) for p in mixed["pages"])
        assert total_active_placed == 4
        assert total_next_placed == 8

    def test_oversize_title_policy_dedicated_page_and_ellipsis(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        oversize = cases["oversize-title"]
        pages = oversize["pages"]
        first_page_item = pages[0]["active_items"][0]
        assert first_page_item["is_oversize"]
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
        builder = CalendarT2IPayloadBuilder()
        active_items = [{"event_id": f"a{i}", "title": f"A{i}", "full_title": f"A{i}", "category": "活动", "category_code": "event", "time_range": "", "remaining": "1D", "is_next_ending": False, "urgency": "NORMAL", "is_long_title": False, "is_oversize": False, "end_precision": "EXACT", "progress_pct": None} for i in range(16)]
        next_items = [{"event_id": f"n{i}", "title": f"N{i}", "full_title": f"N{i}", "category": "活动", "category_code": "event", "start_time_display": "09.20", "starts_in": "3D", "is_long_title": False, "is_oversize": False} for i in range(10)]

        pages = builder._paginate(active_items, next_items, global_has_active=True)
        assert len(pages) >= 2
        # Verify subsequent pages that only have next_items don't show NO ACTIVE OPERATIONS
        p_last = pages[-1]
        bundle_meta = {
            "canvas": p_last["canvas"],
            "panel": p_last["panel"],
            "global_has_active": True,
            "active_count_total": 16,
            "horizon_days": 14,
            "timezone_display": "UTC+8",
            "available": True,
        }
        p_last_html = render_html({**bundle_meta, **p_last})
        if not p_last["active_items"]:
            assert "NO ACTIVE OPERATIONS" not in p_last_html
        assert "NEXT OPERATIONS" in p_last_html


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
    async def test_renderer_viewport_matches_dynamic_canvas_height(self, tmp_path):
        """Case 8: Renderer sets Playwright viewport to exact dynamic canvas dimensions."""
        cases = get_cases("calendar_schedule", tmp_path)
        dyn = cases["dynamic-7-active-4-next"]
        captured_options = {}

        async def fake_render(template, payload, options):
            captured_options.update(options)
            return "rendered.png"

        renderer = T2IRenderer(fake_render, assets=Mock())
        await renderer.render_view("calendar_schedule", dyn)

        assert "viewport" in captured_options
        assert captured_options["viewport"]["width"] == 1600
        assert captured_options["viewport"]["height"] == dyn["canvas"]["height"]
        assert captured_options["viewport"]["height"] > 900

    @pytest.mark.asyncio
    async def test_single_page_returns_single_string(self, tmp_path):
        cases = get_cases("calendar_schedule", tmp_path)
        eight = cases["8-active"]
        assert len(eight["pages"]) == 1

        async def fake_render(template, payload, options):
            return "single_page.png"

        renderer = T2IRenderer(fake_render, assets=Mock())
        result = await renderer.render_view("calendar_schedule", eight)

        assert isinstance(result, str)
        assert result == "single_page.png"


class TestSourceBoundedDynamicCanvasHeight:
    """Case 1~9: 宣传图纵向长度驱动的动态画布高度与分页合约测试。"""

    def test_case_1_standard_9_16_portrait_kv(self):
        """Case 1: 标准 9:16 KV (1080x1920) -> scaled ~2844, effective_max == 2400."""
        effective_max, w, h, scaled_h = CalendarT2IPayloadBuilder._compute_effective_max_canvas_height((1080, 1920))
        assert scaled_h == 2844
        assert effective_max == 2400

    def test_case_2_portrait_4_3_kv(self):
        """Case 2: 4:3-ish portrait (1440x1920) -> scaled 2133, effective_max == 2133."""
        effective_max, w, h, scaled_h = CalendarT2IPayloadBuilder._compute_effective_max_canvas_height((1440, 1920))
        assert scaled_h == 2133
        assert effective_max == 2133

    def test_case_3_landscape_16_9_kv(self):
        """Case 3: 16:9 landscape (1920x1080) -> scaled 900, effective_max == 900."""
        effective_max, w, h, scaled_h = CalendarT2IPayloadBuilder._compute_effective_max_canvas_height((1920, 1080))
        assert scaled_h == 900
        assert effective_max == 900

    def test_case_4_no_background_fallback(self):
        """Case 4: no background -> effective_max == 1600 (FALLBACK_MAX_CANVAS_H)."""
        effective_max, w, h, scaled_h = CalendarT2IPayloadBuilder._compute_effective_max_canvas_height(None)
        assert effective_max == 1600
        assert scaled_h is None

    def test_case_5_20_normal_active_portrait_kv_single_page(self, tmp_path):
        """Case 5: 20 normal Active + 9:16 KV -> 1 page (canvas height 1588 <= 2400)."""
        cases = get_cases("calendar_schedule", tmp_path)
        c = cases["portrait-kv-20-active"]
        assert len(c["pages"]) == 1
        p1 = c["pages"][0]
        assert len(p1["active_items"]) == 20
        assert p1["canvas"]["height"] == 1588
        assert p1["canvas"]["height"] <= 2400
        assert c["layout_limits"]["effective_max_canvas_height"] == 2400
        assert c["layout_limits"]["background_limited"] is False

    def test_case_6_30_normal_active_portrait_kv_single_page(self, tmp_path):
        """Case 6: 30 normal Active + 9:16 KV -> 1 page (canvas height 2188 <= 2400)."""
        cases = get_cases("calendar_schedule", tmp_path)
        c = cases["portrait-kv-30-active"]
        assert len(c["pages"]) == 1
        p1 = c["pages"][0]
        assert len(p1["active_items"]) == 30
        assert p1["canvas"]["height"] == 2188
        assert p1["canvas"]["height"] <= 2400
        assert c["layout_limits"]["effective_max_canvas_height"] == 2400

    def test_case_7_45_active_portrait_kv_overflow_paginates(self, tmp_path):
        """Case 7: 45 Active + 9:16 KV -> page_total >= 2, 每页 <= effective_max_canvas_h (2400)."""
        cases = get_cases("calendar_schedule", tmp_path)
        c = cases["portrait-kv-overflow"]
        assert len(c["pages"]) == 2
        assert c["page_total"] == 2
        for page in c["pages"]:
            assert page["canvas"]["height"] <= 2400
            assert page["canvas"]["height"] >= 900
        assert len(c["pages"][0]["active_items"]) == 33
        assert len(c["pages"][1]["active_items"]) == 12
        assert c["pages"][0]["canvas"]["height"] == 2368
        assert c["pages"][1]["canvas"]["height"] == 1108

    def test_case_8_20_active_landscape_kv_paginates(self, tmp_path):
        """Case 8: 20 Active + landscape KV -> 必须分页 (3 页，各 900px 高)，证明由背景决定上限。"""
        cases = get_cases("calendar_schedule", tmp_path)
        c = cases["landscape-kv-20-active"]
        assert len(c["pages"]) == 3
        assert c["layout_limits"]["effective_max_canvas_height"] == 900
        assert c["layout_limits"]["background_limited"] is True
        for page in c["pages"]:
            assert page["canvas"]["height"] == 900
        assert len(c["pages"][0]["active_items"]) == 8
        assert len(c["pages"][1]["active_items"]) == 8
        assert len(c["pages"][2]["active_items"]) == 4

    def test_case_9_same_background_source_across_pages(self, tmp_path):
        """Case 9: 多页时所有 pages 使用同一个 source background，且各自包含有效 data URI。"""
        cases = get_cases("calendar_schedule", tmp_path)
        c = cases["portrait-kv-overflow"]
        assert len(c["pages"]) == 2
        for page in c["pages"]:
            assert page["background_data_uri"] is not None
            assert page["background_data_uri"].startswith("data:image/webp;base64,") or page["background_data_uri"].startswith("data:image/png;base64,")

    def test_no_kv_overflow_paginates_at_1600(self, tmp_path):
        """无背景图时使用 1600 fallback 上限分页：25 active -> 20 + 5."""
        cases = get_cases("calendar_schedule", tmp_path)
        c = cases["no-kv-overflow"]
        assert len(c["pages"]) == 2
        assert c["layout_limits"]["effective_max_canvas_height"] == 1600
        assert c["pages"][0]["canvas"]["height"] == 1588
        assert c["pages"][1]["canvas"]["height"] == 900
        assert len(c["pages"][0]["active_items"]) == 20
        assert len(c["pages"][1]["active_items"]) == 5


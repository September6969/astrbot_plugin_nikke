"""PR-5 T2I 基础规范门禁：CSP、显式画布视口、可读字号、溢出与负载回归（AUD-017/021/024）。

只做结构断言，不依赖截图像素；像素级的前后对照由本地 Playwright 预览完成。
"""
from __future__ import annotations

import importlib.util
import json
import re
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from jinja2 import Environment
from PIL import Image

from astrbot_plugin_nikke.core.asset_manager import AssetManager
from astrbot_plugin_nikke.features.character.application import CharacterRosterData
from astrbot_plugin_nikke.features.solo_raid.builder import Member, build_five_teams
from astrbot_plugin_nikke.scripts.shared.t2i_preview_fixtures import get_cases
from astrbot_plugin_nikke.ui.payloads.arena import ArenaT2IPayloadBuilder
from astrbot_plugin_nikke.ui.payloads.calendar import CalendarT2IPayloadBuilder
from astrbot_plugin_nikke.ui.payloads.campaign import name_layout
from astrbot_plugin_nikke.ui.payloads.favorite_grid import FavoriteGridPayloadBuilder
from astrbot_plugin_nikke.ui.payloads.roster import RosterT2IPayloadBuilder, roster_row_height
from astrbot_plugin_nikke.ui.payloads.solo_raid import SoloRaidPayloadBuilder
from astrbot_plugin_nikke.ui.renderers.t2i import T2IRenderer
from astrbot_plugin_nikke.ui.t2i_assets import T2IAssetResolver
from astrbot_plugin_nikke.ui.t2i_templates import PAGES, T2ITemplateLoader

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("campaign_preview_gate", ROOT / "scripts" / "preview" / "preview_t2i_ui.py")
campaign_preview = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(campaign_preview)


def _render(page: str, payload: dict) -> str:
    return Environment().from_string(T2ITemplateLoader().load(page)).render(**payload)


@pytest.fixture
def assets(tmp_path):
    manager = AssetManager(tmp_path / "cache", ROOT / "assets", remote=False)
    yield manager
    manager.close()


async def _captured_render(renderer: T2IRenderer, page: str, data) -> list[tuple[dict, dict]]:
    renderer._html_render.reset_mock()
    await renderer.render_view(page, data)
    return [(call.args[1], call.kwargs["options"]) for call in renderer._html_render.call_args_list]


def _arena_inputs():
    from astrbot_plugin_nikke.core.providers.arena import create_arena_application
    from astrbot_plugin_nikke.features.arena.optimizer import ThreeTeamOptimizer
    from astrbot_plugin_nikke.features.character.identity import CharacterDirectoryResolver

    arena = create_arena_application(ROOT, account_reader=None, gateway=None, identity=CharacterDirectoryResolver())
    analysis = arena.analyzer.analyze(arena.directory.parse_team("红莲/豺狼/布兰儿/桑迪/特蕾娜"))
    teams = tuple(arena.directory.parse_team(text) for text in (
        "红莲/豺狼/布兰儿/桑迪/特蕾娜", "诺雅/饼干/爱丽丝/丽塔/普丽瓦蒂", "阿妮斯/拉毗/尼恩/露菲/哈兰"))
    return arena, analysis, ThreeTeamOptimizer(arena.analyzer).solve(teams)


# ── 全模板：CSP + viewport meta ───────────────────────────────────────────────

@pytest.mark.parametrize("page", sorted(PAGES))
def test_every_template_declares_csp_and_viewport_meta(page):
    template = T2ITemplateLoader().load(page)
    csp = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)"', template)
    assert csp, page
    policy = csp.group(1)
    for directive in ("default-src 'none'", "script-src 'none'", "img-src data:", "style-src 'unsafe-inline'"):
        assert directive in policy, (page, directive)
    assert re.search(r'<meta name="viewport" content="width=(\d+|\{\{ ?[^}]+\}\})', template), page
    assert "{% include" not in template and "<script" not in template


# ── 全页面：payload 显式画布，渲染器把画布映射为视口 ──────────────────────────────

@pytest.mark.asyncio
async def test_every_page_payload_carries_canvas_and_renderer_sets_viewport(tmp_path, assets):
    renderer = T2IRenderer(AsyncMock(return_value="ok.png"), assets)
    _, analysis, plan = _arena_inputs()
    inputs = {
        "profile": get_cases("profile", tmp_path)["full"],
        "character": get_cases("character", tmp_path)["c010"],
        "calendar_schedule": get_cases("calendar_schedule", tmp_path)["normal"],
        "union_overview": get_cases("union_overview", tmp_path)["normal"],
        "union_records": get_cases("union_records", tmp_path)["normal"],
        "union_member": get_cases("union_member", tmp_path)["1-record"],
        "roster": CharacterRosterData("测试", ({"name_code": "3001", "lv": 200, "combat": 10},), {"3001": "拉毗"}),
        "arena_matchup": analysis,
        "arena_three_teams": plan,
        "favorite_grid": FavoriteGridPayloadBuilder(assets).build(
            [{"name": "拉毗", "name_code": "3001", "burst": "Step1", "element": "Fire"}] * 9
        ),
        "solo_raid": SoloRaidPayloadBuilder(assets).build(
            build_five_teams((Member("3001", "拉毗", "Step1"),))
        ),
    }
    seen = set()
    for page, data in inputs.items():
        for payload, options in await _captured_render(renderer, page, data):
            canvas = payload["canvas"]
            assert canvas["width"] > 0 and canvas["height"] > 0, page
            assert options["viewport"] == {"width": canvas["width"], "height": canvas["height"]}, page
            meta = re.search(r'<meta name="viewport" content="width=(\d+)', _render(page, payload))
            assert meta and int(meta.group(1)) == canvas["width"], page
            seen.add(page)
    renderer._html_render.reset_mock()
    await renderer.render_campaign_history(campaign_preview.fixture_record("normal"))
    payload, options = renderer._html_render.call_args.args[1], renderer._html_render.call_args.kwargs["options"]
    assert payload["canvas"] == {"width": 1600, "height": 900}
    assert options["viewport"] == {"width": 1600, "height": 900}
    seen.add("campaign")
    assert seen == set(PAGES)


# ── 共享令牌：最低可读字号与语义色 ─────────────────────────────────────────────

def test_tokens_define_thumbnail_font_floor_and_pages_override_canvas_width():
    tokens = (ROOT / "templates/t2i/_shared/tokens.css").read_text(encoding="utf-8")
    assert "--font-min: calc(var(--canvas-width) * var(--thumb-min-px) / 432)" in tokens
    assert "--thumb-min-px: 7" in tokens
    widths = {"campaign": 1600, "character": 1600, "profile": 1080, "roster": 1200,
              "union_overview": 1080, "arena_matchup": 1000}
    for page, width in widths.items():
        assert f"--canvas-width:{width}px" in T2ITemplateLoader().load(page).replace(" ", ""), page


def test_campaign_and_roster_auxiliary_text_meets_thumbnail_floor():
    campaign = T2ITemplateLoader().load("campaign")
    for selector in (".campaign .eyebrow", ".campaign .slot", ".campaign .section-header",
                     ".campaign .metric-label", ".campaign .badge", ".campaign .footer-meta",
                     ".summary-note"):
        rule = re.search(rf"{re.escape(selector)}\s*\{{([^}}]+)\}}", campaign).group(1)
        assert "font-size: var(--font-min)" in rule or "font-size:var(--font-min)" in rule, selector
    roster = T2ITemplateLoader().load("roster")
    for selector in (".identity-note", ".options-head small", ".opt-note"):
        rule = re.search(rf"{re.escape(selector)}\s*\{{([^}}]+)\}}", roster).group(1)
        assert "font-size: var(--font-min)" in rule, selector
    footer = re.search(r"\.roster-footer\s*\{([^}]+)\}", roster).group(1)
    assert float(re.search(r"font-size:\s*([0-9.]+)px", footer).group(1)) * 432 / 1200 >= 7


# ── campaign：SVG 占位、两行长名 ───────────────────────────────────────────────

def test_campaign_placeholder_fits_portrait_and_long_names_get_two_line_layout():
    components = (ROOT / "templates/t2i/_shared/components.css").read_text(encoding="utf-8")
    placeholder = re.search(r"\.placeholder\s*\{([^}]+)\}", components).group(1)
    assert "max-height: 100%" in placeholder and "max-width: 100%" in placeholder
    assert name_layout("短名") == (False, 1)
    assert name_layout("合成边界测试：超长角色正式名称与特殊行动代号") == (False, 1)
    assert name_layout("合成边界测试：超长角色正式名称与特殊行动代号补充") == (True, 1)
    assert name_layout("合成边界测试：超长角色正式名称与特殊行动代号以及额外说明文字补充") == (True, 2)

    assets = Mock(get_lineup_portrait=Mock(return_value=None))
    renderer = T2IRenderer(None, assets)
    record = campaign_preview.fixture_record("normal")
    record.members[0].name_cn = "合成边界测试：超长角色正式名称与特殊行动代号以及额外说明文字补充"
    payload = renderer.payload_builder.build(record)
    assert payload["members"][0]["name_lines"] == 2
    html = _render("campaign", payload)
    assert html.count('class="portrait-info two-line"') == 1
    assert '<svg class="placeholder"' in html
    assert ".campaign .portrait-info.two-line .character-name" in html


# ── profile：.today 徽标与超长身份值 ───────────────────────────────────────────

def test_profile_identity_values_wrap_inside_cards_when_overlong(tmp_path):
    from astrbot_plugin_nikke.ui.payloads.profile import ProfileT2IPayloadBuilder

    case = replace(get_cases("profile", tmp_path)["full"], area_id="亚洲服务器（台港澳/东南亚地区）",
                   commander_level=12_345_678_901, team_combat=98_765_432_109_876)
    html = _render("profile", ProfileT2IPayloadBuilder().build(case))
    assert html.count('class="kv is-long"') == 3
    template = T2ITemplateLoader().load("profile")
    strong = re.search(r"\.identity-grid \.kv>strong \{([^}]+)\}", template).group(1)
    assert "max-width:100%" in strong and "overflow-wrap:anywhere" in strong
    assert "white-space:nowrap" not in strong
    normal = _render("profile", ProfileT2IPayloadBuilder().build(get_cases("profile", tmp_path)["full"]))
    assert 'class="kv is-long"' not in normal


# ── roster：列宽、表头对齐、头像注释高度累加 ─────────────────────────────────────

def test_roster_avatar_note_height_accumulates_and_header_aligns(assets):
    template = T2ITemplateLoader().load("roster")
    assert "grid-template-columns: 60px 72px minmax(220px, 1fr)" in template
    assert ".roster-labels { min-height: 46px; padding: 0 15px 8px;" in template
    long_name = "指挥官测试用超长妮姬名称与 English Character Name Validation"
    assert roster_row_height(long_name, False, "头像暂不可用", None) > roster_row_height(long_name, False, "", None)
    summary = {"rows": [{"lines": 1}], "status": "ok"}
    with_note = roster_row_height(long_name, False, "头像暂不可用", summary)
    assert with_note == roster_row_height(long_name, False, "", summary) + (
        roster_row_height(long_name, False, "头像暂不可用", None) - roster_row_height(long_name, False, "", None)
    )

    class MissingAvatar:
        character_master = assets.character_master

        def get_lineup_portrait_by_resource_id(self, resource_id):
            return None, True

    data = CharacterRosterData("测试", ({"name_code": "3001", "lv": 200, "combat": 10},), {"3001": long_name})
    payload = RosterT2IPayloadBuilder(MissingAvatar()).build(data)
    row = payload["rows"][0]
    assert row["avatar_note"] == "头像暂不可用"
    assert row["row_height"] == roster_row_height(long_name, row["show_code"], "头像暂不可用", None)
    assert row["row_height"] > 120


# ── character：画布、按档位内联字体、死字段、长名、七位战力、缺图占位 ─────────────

@pytest.mark.asyncio
async def test_character_payload_embeds_only_active_fonts_and_rendered_fields(tmp_path, assets):
    from astrbot_plugin_nikke.features.character.replica import replica_fallback_codepoints

    renderer = T2IRenderer(AsyncMock(return_value="ok.png"), assets)
    cases = get_cases("character", tmp_path)
    payload, options = (await _captured_render(renderer, "character", cases["c330"]))[0]
    assert payload["canvas"] == {"width": 1600, "height": 2400} and options["viewport"]["height"] == 2400
    fonts = {key for key in payload if key.startswith("font_") or key == "replica_font"}
    # 官方名称与固定文案全部被 NikkeNotoSC 子集覆盖时，不再内联 Replica 回退字体。
    assert fonts == {"font_noto_700", "font_noto_800", "font_barlow", "font_rajdhani"}
    for dead in ("theme", "bg_gradient", "corporation_watermark", "english", "rarity", "summary",
                 "stats", "growth", "skills", "commander", "updated", "version", "font_noto"):
        assert dead not in payload
    size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    art = len(payload["character_art_data_uri"])
    # 旧版除立绘外约 2.18MB（固定内联 8 份字体约 1.97MB + 水印/死字段）；现应降到 1.25MB 以内。
    assert size - art < 1_250_000
    assert sum(len(payload[key]) for key in fonts) < 1_000_000

    fallback = replica_fallback_codepoints()
    assert fallback and ord("例") in fallback
    long_payload, _ = (await _captured_render(renderer, "character", cases["long-name"]))[0]
    assert long_payload["replica_font"].startswith("data:font/otf;base64,")
    assert long_payload["name_fit"] == "long"


def test_character_template_fits_long_names_large_combat_and_missing_icons():
    from astrbot_plugin_nikke.ui.payloads.character import _combat_fit, _name_fit

    assert _name_fit("皇冠") == ""
    assert _name_fit("普丽瓦蒂：不友善的女仆") == "mid"
    assert _name_fit("合成长名称边界示例：完整角色名称与身份说明以及超长补充说明文字") == "long"
    assert [_combat_fit(value) for value in ("287,405", "9,876,543", "12,345,678", "123,456,789", "Unknown")] == [
        "", "d7", "d8", "d9", "text",
    ]
    template = T2ITemplateLoader().load("character")
    assert "-webkit-line-clamp:2" in re.search(r"\.slot-character-name h1\.long\{([^}]+)\}", template).group(1)
    assert "text-overflow:ellipsis" in re.search(r"\.slot-character-name h1\{([^}]+)\}", template).group(1)
    sizes = {cls: float(re.search(rf"\.slot-battle-power b\.{cls}\{{font-size:([0-9.]+)px", template).group(1))
             for cls in ("d7", "d8", "d9")}
    # 七/八/九位战力缩放后的总宽度不超过六位数字在 84px 下的宽度。
    assert all(sizes[f"d{digits}"] * digits <= 84 * 6 for digits in (7, 8, 9))
    payload = {"favorite": {"icon": None, "name": "x", "level": "—"}, "cube": {"icon": None, "name": "y", "level": "—"},
               "identities": [], "equipment": [], "skill_items": [], "replica_summary": {"rows": [], "total": 0, "complete": True},
               "name": "皇冠", "name_fit": "", "combat": "1", "combat_fit": "", "level": "1", "grade": 0, "core": 0}
    html = _render("character", payload)
    assert html.count('class="icon-missing"') == 2


# ── calendar：UTC/CST 日期差、超规格项不撞页脚、宣传图不重复内联 ─────────────────

def _calendar_service(tmp_path, events, now):
    from astrbot_plugin_nikke.features.calendar.service import CalendarService
    from astrbot_plugin_nikke.integrations.calendar.visual_cache import CalendarVisualCache

    service = CalendarService(tmp_path / "calendar", visual_cache=CalendarVisualCache(tmp_path / "calendar" / "kv"))
    service._has_snapshot = True
    service.last_updated_at = now.isoformat()
    for event in events:
        service._events[event.id] = event
    return service


def _event(event_id, title, start, end, precision, now):
    from astrbot_plugin_nikke.features.calendar.canonical_models import CanonicalEvent

    return CanonicalEvent(id=event_id, title=title, event_type="event", start_at=start, end_at=end,
                          start_precision=precision, end_precision=precision, sources=["gamekee"],
                          primary_source="gamekee", fetched_at=now, updated_at=now,
                          has_started_evidence=start <= now)


def test_calendar_date_only_countdown_uses_beijing_dates(tmp_path):
    # 北京时间 09-13 12:00（UTC 04:00）；日期级开始日为北京 09-16（UTC 09-15 16:00）。
    now = datetime(2026, 9, 13, 4, 0, tzinfo=timezone.utc)
    start = datetime(2026, 9, 15, 16, 0, tzinfo=timezone.utc)
    service = _calendar_service(tmp_path, [_event("d", "日期级预告", start, start + timedelta(days=7), "DATE_ONLY", now)], now)
    payload = CalendarT2IPayloadBuilder().build(service, 14, now)
    item = payload["next_items"][0]
    assert item["start_time_display"] == "09.16"
    assert item["starts_in"] == "约 3 天后（日期级）"


def test_calendar_oversize_item_is_capped_to_page_budget(tmp_path):
    now = datetime(2026, 9, 13, 4, 0, tzinfo=timezone.utc)
    huge = "超规格长标题测试作战：" + "这是一个异常超长的活动标题，用于检验分页预算，文字不得越出卡片。" * 18
    service = _calendar_service(
        tmp_path, [_event("over", huge, now - timedelta(days=1), now + timedelta(days=3), "EXACT", now)], now)
    builder = CalendarT2IPayloadBuilder()
    payload = builder.build(service, 14, now)
    page = payload["pages"][0]
    item = page["active_items"][0]
    assert item["is_oversize"] and item["title"] == huge
    assert item["title_max_lines"] >= 1
    content = builder.measure_page_content(page["active_items"], page["next_items"], global_has_active=True, is_first_page=True)
    assert content <= builder.compute_max_content_budget(page["canvas"]["height"])
    html = _render("calendar_schedule", {**payload, **page})
    assert 'class="card-title is-capped"' in html
    assert f'--title-max-lines: {item["title_max_lines"]};' in html
    assert ".is-oversize .is-capped" in html
    assert huge in html


def test_calendar_inlines_poster_once(tmp_path):
    cases = get_cases("calendar_schedule", tmp_path)
    data = {**cases["normal"], **cases["normal"]["pages"][0], "background_data_uri": "data:image/png;base64,AAAA"}
    html = _render("calendar_schedule", data)
    assert html.count("data:image/png;base64,AAAA") == 1


# ── arena：共享样式片段与分页高度公式 ──────────────────────────────────────────

def test_arena_templates_share_style_fragment_and_canvas_follows_height_model():
    for page in ("arena_matchup", "arena_three_teams"):
        raw = (ROOT / "templates/t2i" / f"{page}.html").read_text(encoding="utf-8")
        assert "<!-- ARENA_CSS -->" in raw and ".match{" not in raw
        assert ".match{margin-top:22px" in T2ITemplateLoader().load(page)
    _, analysis, plan = _arena_inputs()
    builder = ArenaT2IPayloadBuilder()
    for result, three in ((analysis, False), (plan, True)):
        for payload in builder.pages(result):
            expected = builder.page_height(payload, payload["matches"], three=three)
            assert payload["canvas"] == {"width": 1000, "height": expected}
            assert expected <= builder.PAGE_HEIGHT or len(payload["matches"]) == 1


# ── 渲染器：线程化 Pillow 工作、复用 builder/模板、资产路径缓存 ───────────────────

@pytest.mark.asyncio
async def test_renderer_builds_payloads_off_loop_and_reuses_builders(tmp_path, assets):
    renderer = T2IRenderer(AsyncMock(return_value="ok.png"), assets)
    main_thread = threading.current_thread()
    seen: dict[str, threading.Thread] = {}
    spied = ("profile", "union_overview", "union_member", "union_records", "roster")
    for page in spied:
        builder = renderer._builder(page)
        original = builder.build

        def spy(*args, _page=page, _original=original, **kwargs):
            seen[_page] = threading.current_thread()
            return _original(*args, **kwargs)

        builder.build = spy
    await renderer.render_view("profile", get_cases("profile", tmp_path)["full"])
    await renderer.render_view("union_overview", get_cases("union_overview", tmp_path)["normal"])
    await renderer.render_view("union_member", get_cases("union_member", tmp_path)["1-record"])
    await renderer.render_view("union_records", next(iter(get_cases("union_records", tmp_path).values())))
    from astrbot_plugin_nikke.features.character.application import CharacterRosterData
    await renderer.render_view("roster", CharacterRosterData(
        commander_name="测试指挥官", characters=({"name_code": "3001", "lv": 200, "combat": 1_234_567},),
        name_map={"3001": "拉毗"},
    ))
    # 每个线程化页面都必须实际经过缓存 builder 且不在事件循环线程上构建。
    assert set(seen) == set(spied) == set(renderer._THREADED_BUILDERS)
    assert all(thread is not main_thread for thread in seen.values())
    assert renderer._builder("profile") is renderer._builder("profile")

    character_threads = []
    original_character = renderer._character_payload

    def character_spy(data):
        character_threads.append(threading.current_thread())
        return original_character(data)

    renderer._character_payload = character_spy
    await renderer.render_view("character", get_cases("character", tmp_path)["c010"])
    assert character_threads and character_threads[0] is not main_thread

    campaign_threads = []
    original_campaign = renderer.payload_builder.build

    def campaign_spy(record):
        campaign_threads.append(threading.current_thread())
        return original_campaign(record)

    renderer.payload_builder.build = campaign_spy
    await renderer.render_campaign_history(campaign_preview.fixture_record("normal"))
    assert campaign_threads and campaign_threads[0] is not main_thread


def test_template_loader_composes_each_page_once(tmp_path):
    loader = T2ITemplateLoader()
    first = loader.load("profile")
    with patch.object(Path, "read_text", side_effect=AssertionError("模板应从缓存读取")):
        assert loader.load("profile") is first


def test_asset_resolver_path_cache_hit_skips_decode_and_full_image_hash(tmp_path):
    path = tmp_path / "poster.png"
    Image.new("RGBA", (1600, 2400), "red").save(path)
    resolver = T2IAssetResolver()
    uri = resolver.encode(path, (1600, 1200))
    with patch("astrbot_plugin_nikke.ui.t2i_assets.hashlib.sha256", side_effect=AssertionError("命中路径缓存不应再计算全图摘要")), \
         patch("astrbot_plugin_nikke.ui.t2i_assets.Image.open", side_effect=AssertionError("命中路径缓存不应再解码")):
        assert resolver.encode(path, (1600, 1200)) == uri
    # 文件内容变化（修改时间/字节数不同）时不得复用旧编码。
    Image.new("RGBA", (800, 600), "blue").save(path)
    assert resolver.encode(path, (1600, 1200)) != uri


def test_verified_portrait_skips_full_image_hash_on_cache_hit(monkeypatch):
    import hashlib
    from PIL import Image
    from astrbot_plugin_nikke.core.assets.spine_manifest import VERIFIED_SOURCE_OBJECT, VERIFIED_SOURCE_SHA256
    from astrbot_plugin_nikke.ui import t2i_assets

    portrait = Image.new("RGBA", (64, 96), (10, 20, 30, 255))
    portrait.info[VERIFIED_SOURCE_SHA256] = "a" * 64
    portrait.info[VERIFIED_SOURCE_OBJECT] = id(portrait)
    hashed: list[int] = []
    original_sha256 = hashlib.sha256

    def counting_sha256(data=b""):
        hashed.append(len(data))
        return original_sha256(data)

    monkeypatch.setattr(t2i_assets.hashlib, "sha256", counting_sha256)
    resolver = t2i_assets.T2IAssetResolver()
    first = resolver.encode(portrait, (32, 48))
    assert resolver.encode(portrait, (32, 48)) == first
    assert hashed == [], "已校验来源的原图不得再做全图像素哈希（AUD-021）"

    # 派生图片继承 info 但对象身份不同：必须回到像素摘要，不能复用原图缓存。
    derived = portrait.copy()
    derived.putpixel((0, 0), (255, 0, 0, 255))
    assert derived.info.get(VERIFIED_SOURCE_SHA256) == "a" * 64
    assert resolver.encode(derived, (32, 48)) != first, "派生图片必须按像素重新计算缓存键"
    assert hashed, "派生图片应走像素摘要路径"

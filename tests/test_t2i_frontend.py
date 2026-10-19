import json
from plugin_fixtures import (
    inject_calendar_handler,
    inject_character_handler,
    inject_raid_handler,
    make_plugin_shell,
)
import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from jinja2 import Environment

from astrbot_plugin_nikke.ui.renderers.t2i import T2IRenderer
from astrbot_plugin_nikke.scripts.shared.t2i_preview_fixtures import get_cases


@pytest.mark.asyncio
@pytest.mark.parametrize("page", ["calendar_schedule", "union_overview", "union_records", "union_member", "profile", "character"])
async def test_page_fixtures(page, tmp_path):
    native = AsyncMock(return_value="preview.png")
    from pathlib import Path
    from astrbot_plugin_nikke.core.asset_manager import AssetManager
    assets = AssetManager(tmp_path / "cache", Path(__file__).resolve().parents[1] / "assets", remote=False)
    renderer = T2IRenderer(native, assets)
    for name, data in get_cases(page, tmp_path).items():
        res = await renderer.render_view(page, data)
        assert res == "preview.png" or (isinstance(res, list) and all(r == "preview.png" for r in res))
        template, payload = native.call_args.args
        assert json.loads(json.dumps(payload)) == payload
        html = Environment(autoescape=False).from_string(template).render(**payload)
        for forbidden in ("https://", "http://", "file://", "<script", "{% include", "{% import"):
            assert forbidden not in html, (page, name, forbidden)
        assert native.call_args.kwargs["options"]["type"] == "png"
    assets.close()


@pytest.mark.asyncio
async def test_character_success_uses_white_vertical_template(tmp_path):
    from pathlib import Path
    from astrbot_plugin_nikke.core.asset_manager import AssetManager
    from astrbot_plugin_nikke.features.character.replica import VERSION
    from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader

    data = next(iter(get_cases("character", tmp_path).values()))
    assets = AssetManager(
        tmp_path / "cache",
        Path(__file__).resolve().parents[1] / "assets",
        remote=False,
    )
    native = AsyncMock(return_value="white-replica.png")
    renderer = T2IRenderer(native, assets)

    assert await renderer.render_view("character", data) == "white-replica.png"
    template, payload = native.call_args.args
    assert payload["template_version"] == VERSION == "replica-1600x2400-v4-anchor-semantics"
    assert payload["character_art_data_uri"].startswith("data:image/png;base64,")
    assert "width:1600px;height:2400px" in template
    assert "background:#e8ebee" in template
    assert native.call_args.kwargs["options"]["type"] == "png"
    assets.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("page", ["calendar_schedule", "union_overview", "union_records", "union_member", "profile", "character"])
async def test_each_page_autoescape_and_failure(page, tmp_path):
    from pathlib import Path
    from astrbot_plugin_nikke.core.asset_manager import AssetManager
    from astrbot_plugin_nikke.main import NikkePlugin
    attack = '<script>alert(1)</script></style><img src=x onerror=alert(1)>'
    data = next(iter(get_cases(page, tmp_path).values()))
    if page == "calendar_schedule":
        data["active_items"][0]["title"] = attack
        data["pages"][0]["active_items"][0]["title"] = attack
    elif page == "union_overview":
        data.guild_name = attack
    elif page in ("union_records", "union_member"):
        data.participants[0].nickname = attack
    elif page == "profile":
        data.commander_name = attack
    else:
        data.name_cn = attack
    assets = AssetManager(tmp_path / "cache", Path(__file__).resolve().parents[1] / "assets", remote=False)
    native = AsyncMock(return_value="ok.png")
    renderer = T2IRenderer(native, assets)
    await renderer.render_view(page, data)
    template, payload = native.call_args.args
    html = Environment(autoescape=False).from_string(template).render(**payload)
    assert "&lt;script&gt;" in html and "&lt;/style&gt;" in html and "&lt;img" in html
    assert '<script>' not in html and '<img src=x' not in html
    assert html.count("</style>") == 1
    plugin = make_plugin_shell()
    plugin.presentation._t2i_renderer = Mock(
        render_view=AsyncMock(side_effect=RuntimeError())
    )
    assert await plugin.presentation.try_t2i(page, data) is None
    plugin.presentation._t2i_renderer.render_view.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await plugin.presentation.try_t2i(page, data)
    assets.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("page", ["profile", "union_overview"])
async def test_text_command_fallback_retains_dto(page, tmp_path):
    from astrbot_plugin_nikke.main import NikkePlugin
    plugin = make_plugin_shell()
    plugin.config = {"ui_renderer": "t2i"}
    plugin.presentation._t2i_renderer = Mock(
        render_view=AsyncMock(side_effect=RuntimeError())
    )
    data = next(iter(get_cases(page, tmp_path).values()))
    if page == "profile":
        from astrbot_plugin_nikke.adapters.astrbot.command_adapter import AstrBotCommandAdapter
        from astrbot_plugin_nikke.application.commands.profile import ProfileCommandHandler

        plugin.services.store = Mock(get_account=Mock(return_value={"qq_id": "synthetic-qq"}))
        plugin.services.profile_application = Mock(build_dashboard=AsyncMock(return_value=data))
        plugin.adapters.command = AstrBotCommandAdapter()
        plugin.handlers.profile = ProfileCommandHandler(
            account_reader=plugin.services.store,
            application=plugin.services.profile_application,
            present=plugin.presentation.render_profile,
        )
        command, args, request = plugin.me, (), plugin.services.profile_application.build_dashboard
    elif page == "union_overview":
        plugin.services.raid_application = Mock(dashboard=AsyncMock(return_value=data))
        plugin.services.store = Mock()
        inject_raid_handler(plugin)
        command, args, request = plugin.union_raid, (), plugin.services.raid_application.dashboard
    event = Mock(image_result=lambda path: path, plain_result=lambda text: text)
    results = [result async for result in command(event, *args)]
    if page == "union_overview":
        assert "联盟突袭" in results[0]
    else:
        assert len(results) == 1
        assert "个人资料" in results[0]
        assert "图片生成失败" in results[0]
    request.assert_awaited_once()
    assert plugin.presentation._t2i_renderer.render_view.call_args.args[1] is data


def test_calendar_horizon_and_classification(tmp_path):
    cases = get_cases("calendar_schedule", tmp_path)
    assert cases["normal"]["horizon_days"] == 14
    assert cases["7-days"]["horizon_days"] == 7
    assert cases["30-days"]["horizon_days"] == 30
    assert len(cases["normal"]["active_items"]) == 2
    assert len(cases["30-days"]["next_items"]) > len(cases["7-days"]["next_items"])
    assert cases["stale"]["is_stale"]
    assert not cases["unavailable"]["available"]
    assert len(cases["empty"]["active_items"]) == 0
    assert len(cases["empty"]["next_items"]) == 0


@pytest.mark.asyncio
async def test_calendar_command_fallback_same_snapshot(tmp_path):
    from astrbot_plugin_nikke.main import NikkePlugin
    from astrbot_plugin_nikke.features.calendar.service import CalendarService
    from astrbot_plugin_nikke.integrations.calendar.visual_cache import CalendarVisualCache
    plugin = make_plugin_shell()
    plugin.config = {"ui_renderer": "t2i"}
    visual_cache = CalendarVisualCache(tmp_path / "calendar")
    visual_cache.sync = AsyncMock()
    plugin.services.calendar = CalendarService(tmp_path, visual_cache=visual_cache)
    inject_calendar_handler(plugin)
    plugin.services.calendar._has_snapshot = True
    plugin.services.calendar.sync_from_source = AsyncMock()
    plugin.presentation._t2i_renderer = Mock(
        render_view=AsyncMock(side_effect=RuntimeError())
    )
    event = Mock(plain_result=lambda text: text)
    results = [result async for result in plugin.event_schedule(event)]
    assert "未来 14 天" in results[0]
    plugin.services.calendar.sync_from_source.assert_not_called()
    visual_cache.sync.assert_not_awaited()


def test_union_scopes_and_exact_values(tmp_path):
    from astrbot_plugin_nikke.ui.payloads.raid_overview import UnionOverviewT2IPayloadBuilder
    from astrbot_plugin_nikke.ui.payloads.raid_records import UnionRecordsT2IPayloadBuilder
    from astrbot_plugin_nikke.ui.payloads.raid_member import UnionMemberT2IPayloadBuilder
    from astrbot_plugin_nikke.ui.t2i_assets import T2IAssetResolver
    overview = get_cases("union_overview", tmp_path)
    partial = UnionOverviewT2IPayloadBuilder().build(overview["partial-hp"])
    assert partial["progress"] == "Unknown"
    assert partial["bosses"][1]["bar"] is None
    assert len(UnionOverviewT2IPayloadBuilder().build(overview["empty"])["bosses"]) == 5
    records = get_cases("union_records", tmp_path)
    ties = UnionRecordsT2IPayloadBuilder().build(records["tie-rank"])
    assert all(row["rank"] == "1" for row in ties["rows"])
    assert [row["nickname"] for row in ties["rows"]] == [item.nickname for item in records["tie-rank"].participants]
    members = get_cases("union_member", tmp_path)
    payload = UnionMemberT2IPayloadBuilder(Mock(get_lineup_portrait=Mock(return_value=None)), T2IAssetResolver()).build(members["3-records"])
    assert "本次返回记录" in payload["scope"]
    rows = payload["participants"][0]["rows"]
    assert len(rows) == 3 and rows[0]["label"] == "记录 01"
    assert rows[0]["damage"] == "123,456,789"
    assert all(len(row["members"]) == 5 for row in rows)
    assert "synthetic-member" not in json.dumps(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize("page,command", [("union_records", "union_raid_ranking"), ("union_member", "union_raid_my")])
async def test_union_command_failure_no_refetch(page, command):
    from astrbot_plugin_nikke.main import NikkePlugin
    from astrbot_plugin_nikke.features.raid.participants import RaidRankingData
    plugin = make_plugin_shell()
    plugin.config = {"ui_renderer": "t2i"}
    application_call = "ranking_page" if page == "union_records" else "member_page"
    plugin.services.raid_application = Mock(
        **{application_call: AsyncMock(return_value=RaidRankingData([]))}
    )
    plugin.presentation._t2i_renderer = Mock(
        render_view=AsyncMock(side_effect=RuntimeError())
    )
    inject_raid_handler(plugin)
    route = plugin.union_raid_ranking if command == "union_raid_ranking" else plugin.union_raid_my
    results = [result async for result in route(Mock(plain_result=lambda text: text))]
    assert "当前响应" in results[0]
    getattr(plugin.services.raid_application, application_call).assert_awaited_once()


def test_profile_structure_and_unknowns(tmp_path):
    from astrbot_plugin_nikke.ui.payloads.profile import ProfileT2IPayloadBuilder
    from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader
    cases = get_cases("profile", tmp_path)
    builder = ProfileT2IPayloadBuilder()
    partial = builder.build(cases["resource-partial"])
    assert len(partial["resources"]) == 8
    assert partial["resources"][0]["value"] == "未返回"
    assert partial["resources"][0]["scope"] == "PARTIAL"
    zero = builder.build(cases["zero-empty"])
    assert zero["resources"][0]["value"] == "0"
    assert zero["research_state"] == "EMPTY"
    unavailable = builder.build(cases["unavailable"])
    assert unavailable["today_state"] == "UNAVAILABLE"
    html = Environment(autoescape=False).from_string(T2ITemplateLoader().load("profile")).render(**builder.build(cases["full"]))
    assert "EXP 0" not in html
    assert html.index('class="today"') < html.index('模拟室') < html.index('资源')


def test_profile_edge_fixtures_keep_unknown_zero_partial_and_iconless_values(tmp_path):
    from astrbot_plugin_nikke.ui.payloads.profile import ProfileT2IPayloadBuilder
    from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader

    cases = get_cases("profile", tmp_path)
    builder = ProfileT2IPayloadBuilder()
    extra = builder.build(cases["extra-resources"])
    assert {item["type_id"] for item in extra["extra_resources"]} == {99001, 99002}
    assert all("未识别资源" == item["label"] for item in extra["extra_resources"])
    assert all(item["detail"].startswith("类型 ") for item in extra["extra_resources"])

    partial = builder.build(cases["partial-extra-resources"])
    assert partial["resource_state"] == "PARTIAL"
    assert partial["resources"][0]["value"] == "0"
    assert all(
        item["value"] == "未返回"
        for item in partial["resources"][1:]
    )
    assert partial["extra_resources"][0]["type_id"] == 99003

    large = builder.build(cases["large-values"])
    assert {item["label"]: item["value"] for item in large["identity"]}["部队总战力"] == "987,654,321"
    short = builder.build(cases["short-page"])
    assert short["resource_state"] == "UNKNOWN"
    assert all(item["value"] == "Unknown" for item in short["resources"])

    no_icon = ProfileT2IPayloadBuilder().build(cases["iconless-resources"])
    html = Environment().from_string(T2ITemplateLoader().load("profile")).render(**no_icon)
    assert len(no_icon["resources"]) == 8
    assert all(item["icon_data_uri"] is None for item in no_icon["resources"])
    assert html.count('class="resource-icon-slot"') == 8
    assert html.count("<img ") == 0


@pytest.mark.asyncio
async def test_character_slots_theme_and_assets(tmp_path):
    from pathlib import Path
    from astrbot_plugin_nikke.core.asset_manager import AssetManager
    native = AsyncMock(return_value="card.png")
    assets = AssetManager(tmp_path / "cache", Path(__file__).resolve().parents[1] / "assets", remote=False)
    renderer = T2IRenderer(native, assets)
    cases = get_cases("character", tmp_path)
    await renderer.render_view("character", cases["ol-max"])
    _, payload = native.call_args.args
    assert len(payload["equipment"]) == 4
    assert all(len(gear["options"]) == 3 for gear in payload["equipment"])
    assert any(row["tier"] == "T15" for gear in payload["equipment"] for row in gear["options"])
    assert len(payload["identities"]) == 4
    assert payload["character_art_data_uri"].startswith("data:image/png;base64,")
    semantic = [[row["semantic"] for row in gear["options"]] for gear in payload["equipment"]]
    await renderer.render_view("character", cases["dark"])
    other = native.call_args.args[1]
    assert semantic == [[row["semantic"] for row in gear["options"]] for gear in other["equipment"]]
    assert other["theme"] != payload["theme"]
    assert all(row["tier"] == "—" for row in payload["summary"])
    assert payload.get("corporation_watermark", "").startswith("data:image/png;base64,")
    template, _ = native.call_args.args
    html = Environment(autoescape=False).from_string(template).render(**payload)
    assert 'class="corp-watermark"' not in html
    assert 'class="equipment-grid"' in html
    assets.close()


@pytest.mark.asyncio
async def test_character_unworn_equipment_keeps_fixed_empty_rows_without_stale_options(tmp_path):
    from pathlib import Path
    from astrbot_plugin_nikke.core.asset_manager import AssetManager
    from astrbot_plugin_nikke.features.character.models import EquipmentOption

    native = AsyncMock(return_value="card.png")
    assets = AssetManager(
        tmp_path / "cache",
        Path(__file__).resolve().parents[1] / "assets",
        remote=False,
    )
    renderer = T2IRenderer(native, assets)
    card = get_cases("character", tmp_path)["ol-max"]
    for item in card.equipment.values():
        item.equipped = False
        item.options = [EquipmentOption("stale", "残留不显示", 0.1, "percent")]

    await renderer.render_view("character", card)
    payload = native.call_args.args[1]

    assert len(payload["equipment"]) == 4
    assert all(item["status"] == "未装备" for item in payload["equipment"])
    assert all(len(item["options"]) == 3 for item in payload["equipment"])
    assert all(
        row["name"] == "空槽" and row["value"] == "—" and row["state"] == "EMPTY"
        for item in payload["equipment"]
        for row in item["options"]
    )
    assert all(
        "残留不显示" not in row["name"]
        for item in payload["equipment"]
        for row in item["options"]
    )
    assets.close()


def test_profile_resource_silver_mileage_label(tmp_path):
    from astrbot_plugin_nikke.ui.payloads.profile import ProfileT2IPayloadBuilder
    from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader
    cases = get_cases("profile", tmp_path)
    builder = ProfileT2IPayloadBuilder()
    payload = builder.build(cases["full"])
    labels = [r["label"] for r in payload["resources"]]
    assert "白银积分券" in labels
    assert "躯体标签" not in labels
    html = Environment(autoescape=False).from_string(T2ITemplateLoader().load("profile")).render(**payload)
    assert "白银积分券" in html
    assert "躯体标签" not in html


def test_calendar_operations_feed_presentation(tmp_path):
    from astrbot_plugin_nikke.ui.payloads.calendar import CalendarT2IPayloadBuilder
    from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader

    cases = get_cases("calendar_schedule", tmp_path)
    normal = cases["normal"]
    assert normal["canvas"]["width"] == 1600
    assert CalendarT2IPayloadBuilder.MIN_CANVAS_H <= normal["canvas"]["height"] <= 1600
    assert "pages" in normal and len(normal["pages"]) == 1
    assert normal["global_has_active"]
    assert len(normal["active_items"]) == 2
    assert len(normal["next_items"]) == 3

    page = normal["pages"][0]
    builder = CalendarT2IPayloadBuilder()
    measured = builder.measure_page_content(
        page["active_items"], page["next_items"],
        global_has_active=True, is_first_page=True,
    )
    max_height = normal["layout_limits"]["effective_max_canvas_height"]
    assert page["canvas"]["height"] == builder.compute_canvas_height(measured, max_height)

    active_items = normal["active_items"]
    assert any(item["is_next_ending"] for item in active_items)
    assert active_items[0]["urgency"] == "CLOSING"

    html = Environment(autoescape=False).from_string(T2ITemplateLoader().load("calendar_schedule")).render(**normal)
    assert "妮姬日程" in html
    assert "进行中" in html
    assert "即将开始" in html
    assert "第 1 / 1 页" in html
    assert "1600" in html
    assert 'class="panel"' not in html
    assert "progress-track" not in html
    assert "progress-bar" not in html
    assert "progress_percent" not in html
    assert "ENDING SOON / 即将结束" not in html
    assert "UPCOMING / 即将开始" not in html


@pytest.mark.asyncio
async def test_character_card_visual_polish(tmp_path):
    from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader
    from astrbot_plugin_nikke.core.asset_manager import AssetManager
    from pathlib import Path
    assets = AssetManager(tmp_path / "cache", Path(__file__).resolve().parents[1] / "assets", remote=False)
    native = AsyncMock(return_value="preview.png")
    renderer = T2IRenderer(native, assets)
    cases = get_cases("character", tmp_path)
    await renderer.render_view("character", cases["c010"])
    template, payload = native.call_args.args
    assert "bg_gradient" in payload
    assert payload["bg_gradient"].startswith("radial-gradient(")
    html = Environment(autoescape=False).from_string(template).render(**payload)
    assert 'width:1600px;height:2400px' in html
    assert "backdrop-filter:blur(22px)" in html
    assert "overflow:hidden" in html
    assert "replica-1600x2400-v4-anchor-semantics" in html
    assert '<footer' not in html
    assert 'class="skill-strip"' in html
    assets.close()


def test_union_records_no_attack_summary(tmp_path):
    from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader
    from astrbot_plugin_nikke.ui.payloads.raid_records import UnionRecordsT2IPayloadBuilder
    cases = get_cases("union_records", tmp_path)
    builder = UnionRecordsT2IPayloadBuilder()
    template = T2ITemplateLoader().load("union_records")

    # 昵称名单不能证明未出刀，即使名单上的名字都有记录也不能断言全员出刀。
    for name in ("unattacked-members", "all-attacked", "normal"):
        payload = builder.build(cases[name])
        assert payload["no_attack"]["status"] == "UNKNOWN"
        assert payload["no_attack"]["count"] is None
        assert payload["no_attack"]["members"] == []
        html = Environment(autoescape=False).from_string(template).render(**payload)
        assert "无法确认" in html
        assert "全员已出刀" not in html

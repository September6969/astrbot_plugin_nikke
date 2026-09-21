import json
import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from jinja2 import Environment

from astrbot_plugin_nikke.ui.renderers.t2i import T2IRenderer
from astrbot_plugin_nikke.scripts.t2i_preview_fixtures import get_cases


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
    plugin = NikkePlugin.__new__(NikkePlugin)
    plugin.config = {"ui_renderer": "t2i"}
    plugin.campaign_t2i_renderer = Mock(render_view=AsyncMock(side_effect=RuntimeError()))
    assert await plugin._try_t2i(page, data) is None
    plugin.campaign_t2i_renderer.render_view.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await plugin._try_t2i(page, data)
    assets.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("page", ["profile", "union_overview", "character"])
async def test_pillow_command_fallback_retains_dto(page, tmp_path):
    from astrbot_plugin_nikke.main import NikkePlugin
    plugin = NikkePlugin.__new__(NikkePlugin)
    plugin.config = {"ui_renderer": "t2i"}
    plugin._account_or_error = Mock(return_value={})
    plugin.campaign_t2i_renderer = Mock(render_view=AsyncMock(side_effect=RuntimeError()))
    data = next(iter(get_cases(page, tmp_path).values()))
    if page == "profile":
        plugin.client = Mock(get_profile_dashboard=AsyncMock(return_value={"basic": {}, "outpost": {}, "roster": []}))
        plugin.profile_builder = Mock(build=Mock(return_value=data))
        fallback = Mock(return_value="fallback.png")
        plugin.profile_renderer = Mock(render_profile=fallback)
        command, args, request = plugin.me, (), plugin.client.get_profile_dashboard
    elif page == "union_overview":
        plugin.client = Mock(get_union_raid_overview=AsyncMock(return_value={"guild_name": "synthetic", "level_info": {}}))
        plugin.raid_builder = Mock(build=Mock(return_value=data))
        fallback = Mock(return_value="fallback.png")
        plugin.raid_renderer = Mock(render_raid_overview=fallback)
        command, args, request = plugin.union_raid, (), plugin.client.get_union_raid_overview
    else:
        plugin._directory = [{"name_code": "5065"}]
        plugin.character_identity = Mock(find=Mock(return_value=plugin._directory))
        plugin.client = Mock(get_character_detail=AsyncMock(return_value={}))
        plugin._get_profile_for_stat_calculation = AsyncMock(return_value={})
        plugin.character_stat_resources = Mock(prepare_payload=Mock(return_value={}))
        plugin.character_builder = Mock(build=Mock(return_value=data))
        fallback = Mock(return_value="fallback.png")
        plugin.character_renderer = Mock(render_character=fallback)
        command, args, request = plugin.character, ("皇冠",), plugin.client.get_character_detail
    event = Mock(image_result=lambda path: path)
    assert [result async for result in command(event, *args)] == ["fallback.png"]
    request.assert_awaited_once()
    fallback.assert_called_once_with(data)
    assert plugin.campaign_t2i_renderer.render_view.call_args.args[1] is data


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
    plugin = NikkePlugin.__new__(NikkePlugin)
    plugin.config = {"ui_renderer": "t2i"}
    plugin.calendar = CalendarService(tmp_path)
    plugin.calendar._has_snapshot = True
    plugin.calendar.sync_from_source = AsyncMock()
    plugin.campaign_t2i_renderer = Mock(render_view=AsyncMock(side_effect=RuntimeError()))
    event = Mock(plain_result=lambda text: text)
    results = [result async for result in plugin.event_schedule(event)]
    assert "未来 14 天" in results[0]
    plugin.calendar.sync_from_source.assert_not_called()


def test_union_scopes_and_exact_values(tmp_path):
    from astrbot_plugin_nikke.ui.t2i_payloads import UnionOverviewT2IPayloadBuilder, UnionRecordsT2IPayloadBuilder, UnionMemberT2IPayloadBuilder
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
    assert payload["scope"] == "CURRENT_RESPONSE_MEMBER"
    rows = payload["participants"][0]["rows"]
    assert len(rows) == 3 and rows[0]["label"] == "RECORD 01"
    assert rows[0]["damage"] == "123,456,789"
    assert all(len(row["members"]) == 5 for row in rows)
    assert "synthetic-member" not in json.dumps(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize("page,command", [("union_records", "union_raid_ranking"), ("union_member", "union_raid_my")])
async def test_union_command_failure_no_refetch(page, command):
    from astrbot_plugin_nikke.main import NikkePlugin
    plugin = NikkePlugin.__new__(NikkePlugin)
    plugin.config = {"ui_renderer": "t2i"}
    plugin._account_or_error = Mock(return_value={"game_openid": "synthetic-member"})
    plugin.client = Mock(get_union_raid_data=AsyncMock(return_value={"participate_data": []}))
    plugin.campaign_t2i_renderer = Mock(render_view=AsyncMock(side_effect=RuntimeError()))
    results = [result async for result in getattr(plugin, command)(Mock(plain_result=lambda text: text))]
    assert "当前响应" in results[0]
    plugin.client.get_union_raid_data.assert_awaited_once()


def test_profile_structure_and_unknowns(tmp_path):
    from astrbot_plugin_nikke.ui.t2i_payloads import ProfileT2IPayloadBuilder
    from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader
    cases = get_cases("profile", tmp_path)
    builder = ProfileT2IPayloadBuilder()
    partial = builder.build(cases["resource-partial"])
    assert len(partial["resources"]) == 8
    assert partial["resources"][0]["value"] == "Unknown"
    assert partial["resources"][0]["scope"] == "PARTIAL"
    zero = builder.build(cases["zero-empty"])
    assert zero["resources"][0]["value"] == "0"
    assert zero["research_state"] == "EMPTY"
    unavailable = builder.build(cases["unavailable"])
    assert unavailable["today_state"] == "UNAVAILABLE"
    html = Environment(autoescape=False).from_string(T2ITemplateLoader().load("profile")).render(**builder.build(cases["full"]))
    assert "EXP 0" not in html
    assert html.index('class="today"') < html.index('SIMULATION /') < html.index('RESOURCES /')


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


def test_profile_resource_silver_mileage_label(tmp_path):
    from astrbot_plugin_nikke.ui.t2i_payloads import ProfileT2IPayloadBuilder
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
    from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader
    cases = get_cases("calendar_schedule", tmp_path)
    normal = cases["normal"]
    assert normal["canvas"]["width"] == 1600
    assert normal["canvas"]["height"] == 900
    assert "pages" in normal and len(normal["pages"]) >= 1
    assert normal["global_has_active"]
    assert len(normal["active_items"]) == 2
    assert len(normal["next_items"]) == 3

    active_items = normal["active_items"]
    assert any(item["is_next_ending"] for item in active_items)
    assert active_items[0]["urgency"] == "CLOSING"

    html = Environment(autoescape=False).from_string(T2ITemplateLoader().load("calendar_schedule")).render(**normal)
    assert "OPERATIONS FEED" in html
    assert "ACTIVE OPERATIONS" in html
    assert "NEXT OPERATIONS" in html
    assert "1600" in html
    assert "730" in html or "1180" in html
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
    assert "replica-1600x2400-v2" in html
    assert '<footer' not in html
    assert 'class="skill-strip"' in html
    assets.close()


def test_union_records_no_attack_summary(tmp_path):
    from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader
    from astrbot_plugin_nikke.ui.t2i_payloads import UnionRecordsT2IPayloadBuilder
    cases = get_cases("union_records", tmp_path)
    builder = UnionRecordsT2IPayloadBuilder()
    template = T2ITemplateLoader().load("union_records")

    # 1. Unattacked members
    payload_unattacked = builder.build(cases["unattacked-members"])
    assert payload_unattacked["no_attack"]["status"] == "HAS_UNATTACKED"
    assert payload_unattacked["no_attack"]["count"] == 3
    assert payload_unattacked["no_attack"]["label"] == "未出刀 3 人"
    assert "未出刀队员 Alpha" in payload_unattacked["no_attack"]["members"]
    html1 = Environment(autoescape=False).from_string(template).render(**payload_unattacked)
    assert "未出刀 3 人" in html1
    assert "未出刀队员 Alpha" in html1
    assert "no-attack-chip" in html1

    # 2. All attacked
    payload_all = builder.build(cases["all-attacked"])
    assert payload_all["no_attack"]["status"] == "ALL_ATTACKED"
    assert payload_all["no_attack"]["count"] == 0
    assert payload_all["no_attack"]["label"] == "全员已出刀"
    html2 = Environment(autoescape=False).from_string(template).render(**payload_all)
    assert "全员已出刀" in html2

    # 3. Unknown (normal without union_members)
    payload_unknown = builder.build(cases["normal"])
    assert payload_unknown["no_attack"]["status"] == "UNKNOWN"
    assert payload_unknown["no_attack"]["label"] == "无法确认"
    html3 = Environment(autoescape=False).from_string(template).render(**payload_unknown)
    assert "无法确认" in html3


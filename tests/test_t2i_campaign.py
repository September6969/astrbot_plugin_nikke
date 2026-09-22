import asyncio
import importlib.util
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from jinja2 import Environment
from PIL import Image

from astrbot_plugin_nikke.core.asset_manager import AssetManager
from astrbot_plugin_nikke.ui.t2i_assets import T2IAssetResolver
from astrbot_plugin_nikke.ui.renderers.t2i import T2IRenderer

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("campaign_preview", ROOT / "scripts" / "preview_t2i_ui.py")
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["normal", "hard", "long-text", "missing-asset", "partial-data", "empty", "error", "max-density"])
async def test_render_contract(name):
    native = AsyncMock(return_value="output.png")
    assets = Mock()
    assets.get_lineup_portrait.return_value = None
    renderer = T2IRenderer(native, assets)
    record = preview.fixture_record(name)
    assert await renderer.render_campaign_history(record) == "output.png"
    template, payload = native.call_args.args
    assert json.loads(json.dumps(payload)) == payload
    assert native.call_args.kwargs["options"] == T2IRenderer.OPTIONS
    for forbidden in ("{% include", "{% import", "file://", "<script", "https://", "http://", "|safe"):
        assert forbidden not in template
    html = Environment(autoescape=False).from_string(template).render(**payload)
    if payload["available"]:
        assert html.count('<article class="portrait-card">') == 5
        assert f"{record.total_combat:,}" in html
        for member in record.members:
            assert f"{member.combat:,}" in html
    else:
        assert payload["total_combat"] == "—"
        assert not payload["members"]
    assert str(record.stage_id) not in html


@pytest.mark.asyncio
async def test_autoescape_even_without_environment_default():
    renderer = T2IRenderer(AsyncMock(return_value="ok.png"), Mock(get_lineup_portrait=Mock(return_value=None)))
    record = preview.fixture_record("normal")
    attacks = ["<script>alert(1)</script>", "</style>", "<img src=x onerror=alert(1)>"]
    record.commander_name = " ".join(attacks)
    record.members[0].name_cn = attacks[2]
    payload = renderer.payload_builder.build(record)
    html = Environment(autoescape=False).from_string(renderer.loader.load()).render(**payload)
    for attack in (attacks[0], attacks[2]):
        assert attack not in html
    assert html.count("</style>") == 1
    assert "&lt;/style&gt;" in html
    assert "&lt;script&gt;" in html and "&lt;img" in html


def test_asset_preprocessing_and_bounded_cache(tmp_path):
    resolver = T2IAssetResolver(max_entries=2, max_bytes=20000)
    for color in ("red", "green", "blue"):
        source = Image.new("RGBA", (1200, 1600), color)
        path = tmp_path / f"{color}.png"
        source.save(path)
        uri = resolver.encode(path)
        assert uri.startswith("data:image/png;base64,")
        assert resolver.encode(source) == uri
    assert len(resolver._cache) == 2
    assert resolver._bytes <= 20000
    assert resolver.encode("https://invalid.test/a.png") is None
    assert resolver.encode(tmp_path / "missing.png") is None


def test_asset_entrypoint_never_uses_spine(tmp_path):
    assets = AssetManager(tmp_path, ROOT / "assets", remote=False)
    assets.get_character_portrait = Mock(side_effect=AssertionError("禁止混用立绘"))
    try:
        assert assets.get_lineup_portrait(preview.fixture_record("normal").members[0]).size == (128, 128)
    finally:
        assets.close()
    assets.get_character_portrait.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("fail"), asyncio.TimeoutError()])
async def test_handler_fallback_same_dto_without_second_fetch(failure):
    from datetime import datetime, timezone

    from astrbot_plugin_nikke.features.campaign.application import CampaignApplication
    from astrbot_plugin_nikke.features.campaign.builder import CampaignHistoryBuilder
    from astrbot_plugin_nikke.features.campaign.stage_resolver import CampaignStageResolver
    from astrbot_plugin_nikke.main import NikkePlugin

    plugin = NikkePlugin.__new__(NikkePlugin)
    plugin.config = {"ui_renderer": "t2i"}
    plugin.client = Mock(
        get_main_quest_clear_lineup=AsyncMock(
            return_value={"code": 1300017, "msg": "no historical lineup"}
        )
    )
    account_reader = Mock()
    account_reader.get_account.return_value = {"area_id": 7, "nickname": "test"}
    plugin.campaign_application = CampaignApplication(
        resolver=CampaignStageResolver.from_file(ROOT / "assets" / "campaign_stages.json"),
        gateway=plugin.client,
        account_reader=account_reader,
        builder=CampaignHistoryBuilder(),
        clock=lambda: datetime(2026, 9, 22, 18, 0, tzinfo=timezone.utc),
        plugin_version="test-version",
    )
    plugin.store = Mock()
    plugin.campaign_t2i_renderer = Mock(render_campaign_history=AsyncMock(side_effect=failure))
    plugin.campaign_renderer = Mock(render_campaign_history=Mock(return_value="fallback.png"))
    event = Mock(
        image_result=lambda path: path,
        plain_result=lambda text: text,
        get_sender_id=lambda: "qq-123",
    )
    assert [result async for result in plugin.campaign(event, "46-40")] == ["fallback.png"]
    plugin.client.get_main_quest_clear_lineup.assert_awaited_once()
    plugin.campaign_t2i_renderer.render_campaign_history.assert_awaited_once()
    record = plugin.campaign_t2i_renderer.render_campaign_history.await_args.args[0]
    plugin.campaign_renderer.render_campaign_history.assert_called_once_with(record)


@pytest.mark.asyncio
async def test_timeout_and_cancel():
    async def slow(*args, **kwargs):
        await asyncio.sleep(10)
    renderer = T2IRenderer(slow, Mock(get_lineup_portrait=Mock(return_value=None)), timeout=0.01)
    with pytest.raises(asyncio.TimeoutError):
        await renderer.render_campaign_history(preview.fixture_record("normal"))


@pytest.mark.asyncio
async def test_native_injection_success_and_default_pillow():
    from astrbot_plugin_nikke.main import NikkePlugin
    plugin = NikkePlugin.__new__(NikkePlugin)
    plugin.config = {"ui_renderer": "t2i"}
    plugin.html_render = AsyncMock(return_value="native.png")
    plugin.asset_manager = Mock(get_lineup_portrait=Mock(return_value=None))
    plugin.campaign_renderer = Mock(render_campaign_history=Mock(return_value="pillow.png"))
    record = preview.fixture_record("normal")
    assert await plugin._render_campaign_record(record) == "native.png"
    plugin.html_render.assert_awaited_once()
    plugin.campaign_renderer.render_campaign_history.assert_not_called()
    plugin.config = {}
    assert await plugin._render_campaign_record(record) == "pillow.png"
    plugin.campaign_renderer.render_campaign_history.assert_called_once_with(record)


def test_partial_assets_preserve_identity_and_numbers():
    import base64
    import io
    source = Image.new("RGBA", (1200, 1800), "blue")
    assets = Mock(get_lineup_portrait=Mock(side_effect=[source, OSError("broken"), None, None, None]))
    renderer = T2IRenderer(None, assets)
    record = preview.fixture_record("normal")
    payload = renderer.payload_builder.build(record)
    assert payload["portrait_notice"] == "部分头像不可用"
    assert payload["members"][1]["name"] == record.members[1].name_cn
    assert payload["total_combat"] == "1,286,600"
    raw = base64.b64decode(payload["members"][0]["portrait_data_uri"].split(",", 1)[1])
    with Image.open(io.BytesIO(raw)) as image:
        assert image.width <= 272 and image.height <= 236
    html = Environment(autoescape=False).from_string(renderer.loader.load()).render(**payload)
    assert '<img src="data:image/png;base64,' in html
    assert "https://" not in html and "file://" not in html


def test_unresolved_identity_never_requests_portrait():
    assets = Mock(get_lineup_portrait=Mock(return_value=None))
    renderer = T2IRenderer(None, assets)
    record = preview.fixture_record("partial-data")
    payload = renderer.payload_builder.build(record)
    assert payload["members"][0]["name"] == "身份未确认"
    assert payload["members"][0]["portrait_data_uri"] is None
    assert "999999" not in json.dumps(payload)
    assert assets.get_lineup_portrait.call_count == 4


@pytest.mark.parametrize("field,value", [("name_cn", "长" * 37), ("combat", 1000000000)])
def test_unfittable_data_fails_to_fallback_without_truncation(field, value):
    record = preview.fixture_record("normal")
    setattr(record.members[0], field, value)
    renderer = T2IRenderer(None, Mock(get_lineup_portrait=Mock(return_value=None)))
    with pytest.raises(ValueError, match="单页可读范围"):
        renderer.payload_builder.build(record)


@pytest.mark.asyncio
async def test_cancellation_does_not_trigger_fallback():
    from astrbot_plugin_nikke.main import NikkePlugin
    plugin = NikkePlugin.__new__(NikkePlugin)
    plugin.config = {"ui_renderer": "t2i"}
    plugin.campaign_t2i_renderer = Mock(render_campaign_history=AsyncMock(side_effect=asyncio.CancelledError()))
    plugin.campaign_renderer = Mock()
    with pytest.raises(asyncio.CancelledError):
        await plugin._render_campaign_record(preview.fixture_record("normal"))
    plugin.campaign_renderer.render_campaign_history.assert_not_called()

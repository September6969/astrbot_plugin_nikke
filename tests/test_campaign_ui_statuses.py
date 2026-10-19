import importlib.util
import re
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from jinja2 import Environment
import pytest

from astrbot_plugin_nikke.application.commands.campaign import CampaignCommandHandler
from astrbot_plugin_nikke.application.commands.contracts import CommandContext, TextReply
from astrbot_plugin_nikke.features.campaign.models import ClearLineupStatus
from astrbot_plugin_nikke.ui.renderers.t2i import T2IRenderer

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("campaign_preview", ROOT / "scripts" / "preview" / "preview_t2i_ui.py")
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


def test_rate_limit_is_a_distinct_campaign_status_in_the_formal_template():
    record = preview.fixture_record("normal")
    record.status = ClearLineupStatus.RATE_LIMITED
    record.status_message = "战役查询请求过频，请稍后再试"
    record.members = []
    renderer = T2IRenderer(None, Mock(get_lineup_portrait=Mock(return_value=None)))
    payload = renderer.payload_builder.build(record)

    assert payload["status_code"] == "RATE_LIMITED"
    assert payload["status_label"] == "请求过频"
    html = Environment(autoescape=False).from_string(renderer.loader.load()).render(**payload)
    assert 'class="badge state-rate-limited">请求过频</span>' in html
    assert "战役查询请求过频，请稍后再试" in html

def test_normal_and_hard_campaign_modes_have_chinese_labels():
    renderer = T2IRenderer(None, Mock(get_lineup_portrait=Mock(return_value=None)))
    for fixture_name, expected_code, expected_label, expected_root_class in (
        ("normal", "NORMAL", "普通", "campaign normal"),
        ("hard", "HARD", "困难", "campaign hard"),
    ):
        payload = renderer.payload_builder.build(preview.fixture_record(fixture_name))
        assert payload["mode"] == expected_code
        assert payload["mode_label"] == expected_label
        html = Environment(autoescape=False).from_string(renderer.loader.load()).render(**payload)
        assert f'class="{expected_root_class}"' in html
        assert f'class="badge mode">{expected_label}</span>' in html

def test_unrecognized_campaign_mode_is_not_labeled_as_normal():
    record = preview.fixture_record("normal")
    record.mode = "UNVERIFIED"
    renderer = T2IRenderer(None, Mock(get_lineup_portrait=Mock(return_value=None)))
    payload = renderer.payload_builder.build(record)

    assert payload["mode"] == "UNKNOWN"
    assert payload["mode_label"] == "难度待确认"
    html = Environment(autoescape=False).from_string(renderer.loader.load()).render(**payload)
    assert 'class="campaign unknown"' in html
    assert 'class="badge mode">难度待确认</span>' in html


def test_campaign_history_empty_rate_limit_and_error_have_distinct_statuses():
    labels = {
        ClearLineupStatus.AVAILABLE: ("AVAILABLE", "历史阵容", "available"),
        ClearLineupStatus.UNAVAILABLE: ("UNAVAILABLE", "暂无可查询阵容", "unavailable"),
        ClearLineupStatus.RATE_LIMITED: ("RATE_LIMITED", "请求过频", "rate-limited"),
        ClearLineupStatus.ERROR: ("ERROR", "查询不可用", "error"),
    }
    renderer = T2IRenderer(None, Mock(get_lineup_portrait=Mock(return_value=None)))
    seen_codes = set()
    seen_labels = set()

    for status, (code, label, css_state) in labels.items():
        record = preview.fixture_record("normal")
        record.status = status
        record.status_message = "状态说明"
        if status != ClearLineupStatus.AVAILABLE:
            record.members = []
        payload = renderer.payload_builder.build(record)
        html = Environment(autoescape=False).from_string(renderer.loader.load()).render(**payload)

        assert payload["status_code"] == code
        assert payload["status_label"] == label
        assert f'class="badge state-{css_state}">{label}</span>' in html
        if status != ClearLineupStatus.AVAILABLE:
            assert "状态说明" in html
        seen_codes.add(payload["status_code"])
        seen_labels.add(payload["status_label"])

    assert len(seen_codes) == 4
    assert len(seen_labels) == 4


def test_formal_campaign_template_uses_five_slot_rows_in_api_order():
    renderer = T2IRenderer(None, Mock(get_lineup_portrait=Mock(return_value=None)))
    payload = renderer.payload_builder.build(preview.fixture_record("normal"))
    html = Environment(autoescape=False).from_string(renderer.loader.load()).render(**payload)
    compact = html.replace(" ", "")

    assert "grid-template-rows:repeat(5,minmax(0,1fr))" in compact
    assert html.count('<article class="portrait-card">') == 5
    slot_positions = [html.index(f'class="slot">{slot}</span>') for slot in "12345"]
    assert slot_positions == sorted(slot_positions)






@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "message"),
    [
        (ClearLineupStatus.RATE_LIMITED, "战役查询请求过频，请稍后再试"),
        (ClearLineupStatus.ERROR, "历史阵容数据结构异常，请稍后重试"),
    ],
)
async def test_command_keeps_rate_limit_and_error_text_distinct(status, message):
    record = preview.fixture_record("normal")
    record.status = status
    record.status_message = message
    record.members = []
    stage = object()
    application = Mock(resolve=Mock(return_value=stage), lookup=AsyncMock(return_value=record))
    present = AsyncMock()
    handler = CampaignCommandHandler(
        application=application,
        present=present,
        invalidate_cookie=Mock(),
    )

    result = await handler.handle(
        CommandContext(actor_id="test", parameters={"stage": "46-40"})
    )

    assert result.messages == (TextReply(message),)
    application.lookup.assert_awaited_once_with("test", stage)
    present.assert_not_awaited()

def _campaign_css_px(template: str, selector: str, property_name: str) -> float:
    match = re.search(
        rf"{re.escape(selector)}\s*\{{([^}}]+)\}}",
        template,
    )
    assert match is not None, f"missing CSS rule: {selector}"
    value = re.search(rf"{re.escape(property_name)}\s*:\s*([0-9.]+)px", match.group(1))
    assert value is not None, f"missing {property_name} in {selector}"
    return float(value.group(1))


def test_campaign_mobile_readability_budget_covers_names_levels_and_portraits():
    template = T2IRenderer(None, Mock(get_lineup_portrait=Mock(return_value=None))).loader.load()
    scale = 432 / 1600

    assert _campaign_css_px(template, ".campaign .level", "font-size") * scale >= 10
    assert _campaign_css_px(template, ".campaign .character-name", "font-size") * scale >= 10
    assert _campaign_css_px(template, ".campaign .character-name.long-name", "font-size") * scale >= 10
    assert _campaign_css_px(template, ".campaign .portrait", "width") * scale >= 40
    assert _campaign_css_px(template, ".campaign .portrait", "height") * scale >= 24

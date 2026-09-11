"""展示层回归：数据不变、固定槽位与安全页面。"""
import asyncio
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from astrbot_plugin_nikke.card_models import EquipmentOption
from astrbot_plugin_nikke.card_theme import character_theme, UI_COLORS, _relative_luminance
from astrbot_plugin_nikke.character_card_renderer import CharacterCardRenderer
from astrbot_plugin_nikke.tests.test_card_builder import build_card
from astrbot_plugin_nikke.web_service import BindingWebService

ROOT = Path(__file__).resolve().parents[1]


def test_issue_73_percent_presentation():
    for value, expected in ((.1322, "13.22%"), (.8537, "85.37%")):
        option = EquipmentOption("fixture", "测试词条", value, "percent")
        assert CharacterCardRenderer._option_value(option) == expected
        assert option.value == value


def test_four_positions_have_exactly_three_rows_even_when_unequipped():
    with tempfile.TemporaryDirectory() as td:
        renderer = CharacterCardRenderer(td, ROOT / "fonts")
        card = build_card()
        for item in card.equipment.values():
            item.equipped = False
            item.options = [EquipmentOption("stale", "残留不显示", .1, "percent")]
        with patch.object(renderer, "_text", wraps=renderer._text) as text:
            renderer.draw_equipment_column(Image.new("RGBA", (1800, 1000)), card, character_theme("ELYSION", "Fire"))
        strings = [call.args[2] for call in text.call_args_list]
        assert strings.count("空槽") == 12
        assert strings.count("未装备") == 4
        assert "残留不显示" not in strings


def test_empty_unknown_and_verified_remain_distinct():
    values = [CharacterCardRenderer._option_value(EquipmentOption("test", "test", .1322, unit))
              for unit in ("empty", "unknown", "percent")]
    assert values == ["—", "待确认", "13.22%"]


def test_binding_page_never_echoes_request_url():
    for valid in (True, False):
        service = object.__new__(BindingWebService)
        service.store = types.SimpleNamespace(get_bind_session=lambda _: {
            "expires_at": 9999999999 if valid else 0, "used_at": None})
        request = types.SimpleNamespace(match_info={"token": "a" * 43}, url="PRIVATE_BINDING_SECRET")
        response = asyncio.run(service.bind_page(request))
        assert "PRIVATE_BINDING_SECRET" not in response.text
        assert "浏览器地址栏" in response.text
        assert ("链接有效" if valid else "链接无效") in response.text


def test_shared_secondary_text_has_readable_contrast():
    light = _relative_luminance(UI_COLORS["muted"])
    dark = _relative_luminance(UI_COLORS["raised"])
    assert (light + .05) / (dark + .05) >= 4.5

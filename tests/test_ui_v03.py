"""展示层回归：数据不变、固定槽位与安全页面。"""
import asyncio
import types

from astrbot_plugin_nikke.ui.theme import character_theme, UI_COLORS, _relative_luminance
from astrbot_plugin_nikke.ui.payloads.character_labels import format_equipment_option_value
from astrbot_plugin_nikke.integrations.web.service import BindingWebService


def test_issue_73_percent_presentation():
    for value, expected in ((.1322, "13.22%"), (.8537, "85.37%")):
        option = types.SimpleNamespace(value=value, unit="percent")
        assert format_equipment_option_value(option) == expected
        assert option.value == value


def test_equipment_value_labels_keep_empty_unknown_and_flat_distinct():
    values = [
        format_equipment_option_value(types.SimpleNamespace(value=.1322, unit=unit))
        for unit in ("empty", "unknown", "percent")
    ]
    assert values == ["—", "待确认", "13.22%"]
    assert format_equipment_option_value(
        types.SimpleNamespace(value=1234.6, unit="flat")
    ) == "1,235"


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

from __future__ import annotations

from pathlib import Path
import re
from unittest.mock import AsyncMock, Mock, patch

import pytest

from astrbot_plugin_nikke.core.asset_manager import AssetManager
from astrbot_plugin_nikke.features.character.application import CharacterRosterData
from astrbot_plugin_nikke.ui.renderers.t2i import T2IRenderer
from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader
from astrbot_plugin_nikke.ui.payloads.roster import RosterT2IPayloadBuilder


@pytest.mark.asyncio
async def test_formal_roster_dto_can_render_through_t2i_page(tmp_path):
    root = Path(__file__).resolve().parents[1]
    assets = AssetManager(tmp_path / "cache", root / "assets", remote=False)
    native = AsyncMock(return_value="roster.png")
    renderer = T2IRenderer(native, assets)
    data = CharacterRosterData(
        commander_name="测试指挥官",
        characters=(
            {"name_code": "3001", "lv": 200, "combat": 1_234_567},
        ),
        name_map={"3001": "拉毗"},
    )

    try:
        with patch.object(
            assets.spine_renderer,
            "render_local_portrait",
            side_effect=AssertionError("总表头像不得触发冷 Spine 渲染"),
        ):
            assert await renderer.render_view("roster", data) == "roster.png"
        template, payload = native.call_args.args
        assert "class=\"roster\"" in template
        assert payload["rows"][0]["name"] == "拉毗"
        assert payload["rows"][0]["combat"] == "1,234,567"
        assert payload["rows"][0]["avatar_data_uri"].startswith("data:image/png;base64,")
        assert payload["diagnostics"]["avatar_lookup_count"] == 1
        assert payload["diagnostics"]["embedded_avatar_bytes"] <= 384 * 1024
        assert "roster" in T2ITemplateLoader().load("roster")
    finally:
        assets.close()


def test_roster_builder_keeps_top_twenty_order_and_unknown_values():
    characters = tuple(
        {
            "name_code": str(3001 + index),
            "lv": None if index == 20 else 200,
            "combat": 50_000 + index,
            "grade": 0,
            "core": None,
            "skill1_lv": None,
            "skill2_lv": "invalid",
            "ulti_skill_lv": 0,
            "private_detail": "must not enter the payload",
        }
        for index in range(21)
    )
    payload = RosterT2IPayloadBuilder().build(
        CharacterRosterData("测试", characters, {})
    )

    assert payload["total_count"] == 21
    assert payload["shown_count"] == 20
    assert payload["range_label"] == "显示 Top 20 / 共 21 名"
    assert [row["rank"] for row in payload["rows"]] == list(range(1, 21))
    assert [row["combat"] for row in payload["rows"][:3]] == [
        "50,020",
        "50,019",
        "50,018",
    ]
    assert payload["rows"][0]["level"] == "未返回"
    assert payload["rows"][0]["grade"] == "突破 0"
    assert payload["rows"][0]["core"] == "核心 未返回"
    assert payload["rows"][0]["skills"] == "—/?/0"
    assert "private_detail" not in str(payload)


def test_roster_unknown_codes_are_not_normalized_or_given_guessed_avatars(tmp_path):
    root = Path(__file__).resolve().parents[1]
    assets = AssetManager(tmp_path / "cache", root / "assets", remote=False)
    try:
        payload = RosterT2IPayloadBuilder(assets).build(
            CharacterRosterData(
                "测试",
                (
                    {"name_code": "101001", "combat": 10},
                    {"name_code": "999999", "combat": 9},
                ),
                {},
            )
        )
        assert [row["name_code"] for row in payload["rows"]] == [
            "101001",
            "999999",
        ]
        assert all(not row["identity_verified"] for row in payload["rows"])
        assert all(row["avatar_data_uri"] is None for row in payload["rows"])
        assert payload["diagnostics"]["avatar_lookup_count"] == 0
    finally:
        assets.close()


def test_roster_duplicate_display_names_keep_code_badges_and_distinct_avatars(tmp_path):
    root = Path(__file__).resolve().parents[1]
    assets = AssetManager(tmp_path / "cache", root / "assets", remote=False)
    try:
        payload = RosterT2IPayloadBuilder(assets).build(
            CharacterRosterData(
                "测试",
                (
                    {"name_code": "3001", "combat": 20},
                    {"name_code": "3005", "combat": 10},
                ),
                {"3001": "同名妮姬", "3005": "同名妮姬"},
            )
        )
        assert [row["name"] for row in payload["rows"]] == ["同名妮姬", "同名妮姬"]
        assert all(row["show_code"] for row in payload["rows"])
        assert all(row["identity_verified"] for row in payload["rows"])
        assert payload["rows"][0]["avatar_data_uri"] != payload["rows"][1]["avatar_data_uri"]
    finally:
        assets.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("renderer_setting", "t2i_result", "expected"),
    [
        ("t2i", "t2i.png", "t2i.png"),
        ("pillow", "t2i.png", "t2i.png"),
        ("unknown", RuntimeError("synthetic failure"), None),
    ],
)
async def test_roster_command_always_uses_t2i_without_pillow_fallback(
    renderer_setting, t2i_result, expected
):
    from plugin_fixtures import make_plugin_shell

    plugin = make_plugin_shell()
    plugin.config = {"ui_renderer": renderer_setting}
    render_view = AsyncMock(side_effect=t2i_result if isinstance(t2i_result, Exception) else None)
    if not isinstance(t2i_result, Exception):
        render_view.return_value = t2i_result
    plugin.presentation._t2i_renderer = Mock(render_view=render_view)
    data = CharacterRosterData("指挥官", ({"name_code": "3001"},), {"3001": "拉毗"})

    assert await plugin.presentation.render_roster(data) == expected
    render_view.assert_awaited_once_with("roster", data)

def test_roster_mobile_key_fields_have_readable_t2i_typography():
    template = T2ITemplateLoader().load("roster")

    def font_size(selector: str) -> float:
        match = re.search(rf"{re.escape(selector)}\s*\{{([^}}]+)\}}", template)
        assert match is not None, f"missing CSS rule: {selector}"
        value = re.search(r"font-size\s*:\s*([0-9.]+)px", match.group(1))
        assert value is not None, f"missing font-size in {selector}"
        return float(value.group(1))

    scale = 432 / 1200
    assert font_size(".roster-labels") * scale >= 10
    assert font_size(".skills") * scale >= 10
    assert font_size(".progress") * scale >= 10

# SPDX-License-Identifier: GPL-3.0-or-later
"""锁定单角色练度卡只使用白色竖版 replica 的生产合同。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from astrbot_plugin_nikke.adapters.astrbot.command_presentation import (
    AstrBotCommandPresentation,
)
from astrbot_plugin_nikke.application.commands.character import CharacterRenderFailure
from astrbot_plugin_nikke.core.config import normalize_runtime_config
from astrbot_plugin_nikke.ui.payloads.character_labels import (
    CHARACTER_EQUIPMENT_SLOT_LABELS,
)


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_config",
    [
        {},
        {"ui_renderer": "pillow"},
        {"ui_renderer": "t2i"},
        {"character_card_layout": "classic"},
        {"character_card_layout": "replica"},
    ],
)
async def test_single_character_card_always_uses_white_replica(raw_config):
    config = normalize_runtime_config(raw_config)
    assert "character_card_layout" not in config

    presentation = AstrBotCommandPresentation(
        services=SimpleNamespace(asset_manager=Mock()),
        config=lambda: config,
        html_render=lambda: None,
        context=None,
    )
    renderer = SimpleNamespace(
        render_view=AsyncMock(return_value="white-replica.png")
    )
    presentation._t2i_renderer = renderer
    card = object()

    assert await presentation.render_character_card(card) == "white-replica.png"
    renderer.render_view.assert_awaited_once_with("character", card)


@pytest.mark.asyncio
async def test_replica_render_failure_is_explicit_and_never_uses_pillow_assets():
    asset_manager = Mock()
    presentation = AstrBotCommandPresentation(
        services=SimpleNamespace(asset_manager=asset_manager),
        config=lambda: {"ui_renderer": "pillow"},
        html_render=lambda: None,
        context=None,
    )
    renderer = SimpleNamespace(
        render_view=AsyncMock(side_effect=RuntimeError("native render failed"))
    )
    presentation._t2i_renderer = renderer

    with pytest.raises(CharacterRenderFailure):
        await presentation.render_character_card(object())

    renderer.render_view.assert_awaited_once()
    asset_manager.resolve_character_assets.assert_not_called()


def test_character_card_template_is_the_white_vertical_replica():
    template = (ROOT / "templates" / "t2i" / "character.html").read_text(
        encoding="utf-8"
    )
    schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    renderers = __import__("astrbot_plugin_nikke.ui.renderers", fromlist=["*"])

    assert "width:1600px;height:2400px" in template
    assert "background:#e8ebee" in template
    assert "character_card_layout" not in schema
    assert not hasattr(renderers, "CharacterCardRenderer")
    assert not (ROOT / "ui" / "renderers" / "character.py").exists()
    assert list(CHARACTER_EQUIPMENT_SLOT_LABELS) == ["head", "torso", "arm", "leg"]

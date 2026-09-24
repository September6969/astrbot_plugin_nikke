# SPDX-License-Identifier: GPL-3.0-or-later
"""验证 UI 模块收敛及根目录兼容性 shim 的完备性与一致性。"""

import warnings
import pytest


def test_ui_package_exports():
    import astrbot_plugin_nikke.ui as ui
    assert hasattr(ui, "CardRenderer")
    assert hasattr(ui, "character_theme")
    assert hasattr(ui, "UI_COLORS")
    assert hasattr(ui, "CharacterTheme")


def test_ui_renderers_exports():
    import astrbot_plugin_nikke.ui.renderers as renderers
    assert hasattr(renderers, "CampaignHistoryRenderer")
    assert hasattr(renderers, "ProfileCardRenderer")
    assert hasattr(renderers, "UnionRaidRenderer")
    assert hasattr(renderers, "T2IRenderer")
    assert not hasattr(renderers, "CharacterCardRenderer")


def test_ui_formal_contracts_and_root_isolation():
    from astrbot_plugin_nikke.ui.theme import character_theme, UI_COLORS, CharacterTheme
    from astrbot_plugin_nikke.ui.primitives import CardRenderer
    from astrbot_plugin_nikke.ui.renderers import (
        CampaignHistoryRenderer,
        ProfileCardRenderer,
        UnionRaidRenderer,
        T2IRenderer,
    )

    assert CharacterTheme is not None
    assert character_theme is not None
    assert UI_COLORS is not None
    assert CardRenderer is not None
    assert CampaignHistoryRenderer is not None
    assert ProfileCardRenderer is not None
    assert UnionRaidRenderer is not None
    assert T2IRenderer is not None

    # 验证旧根目录垫片已被彻底收敛，不再暴露于包根
    legacy_ui_shims = [
        "card_theme",
        "renderer",
        "campaign_history_renderer",
        "character_card_renderer",
        "profile_card_renderer",
        "union_raid_renderer",
        "t2i_renderer",
    ]
    for shim in legacy_ui_shims:
        with pytest.raises(ModuleNotFoundError):
            __import__(f"astrbot_plugin_nikke.{shim}")


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
    assert hasattr(renderers, "CharacterCardRenderer")
    assert hasattr(renderers, "ProfileCardRenderer")
    assert hasattr(renderers, "UnionRaidRenderer")
    assert hasattr(renderers, "T2IRenderer")


def test_root_shims_backward_compatibility_and_identity():
    import astrbot_plugin_nikke.card_theme as card_theme
    import astrbot_plugin_nikke.renderer as renderer
    import astrbot_plugin_nikke.campaign_history_renderer as campaign_history_renderer
    import astrbot_plugin_nikke.character_card_renderer as character_card_renderer
    import astrbot_plugin_nikke.profile_card_renderer as profile_card_renderer
    import astrbot_plugin_nikke.union_raid_renderer as union_raid_renderer
    import astrbot_plugin_nikke.t2i_renderer as t2i_renderer

    import astrbot_plugin_nikke.ui.theme as ui_theme
    import astrbot_plugin_nikke.ui.primitives as ui_primitives
    from astrbot_plugin_nikke.ui.renderers import (
        CampaignHistoryRenderer,
        CharacterCardRenderer,
        ProfileCardRenderer,
        UnionRaidRenderer,
        T2IRenderer,
    )

    assert card_theme.character_theme is ui_theme.character_theme
    assert card_theme.UI_COLORS == ui_theme.UI_COLORS
    assert renderer.CardRenderer is ui_primitives.CardRenderer
    assert campaign_history_renderer.CampaignHistoryRenderer is CampaignHistoryRenderer
    assert character_card_renderer.CharacterCardRenderer is CharacterCardRenderer
    assert profile_card_renderer.ProfileCardRenderer is ProfileCardRenderer
    assert union_raid_renderer.UnionRaidRenderer is UnionRaidRenderer
    assert t2i_renderer.T2IRenderer is T2IRenderer

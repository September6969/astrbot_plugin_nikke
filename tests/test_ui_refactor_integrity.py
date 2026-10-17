# SPDX-License-Identifier: GPL-3.0-or-later
"""验证图片表现层只公开 T2I 页面渲染与素材主题能力。"""

import importlib.util


def test_ui_package_exposes_theme_but_no_pillow_card_renderer():
    import astrbot_plugin_nikke.ui as ui

    assert hasattr(ui, "character_theme")
    assert hasattr(ui, "UI_COLORS")
    assert hasattr(ui, "CharacterTheme")
    assert not hasattr(ui, "CardRenderer")
    assert importlib.util.find_spec("astrbot_plugin_nikke.ui.primitives") is None


def test_ui_renderers_only_export_t2i():
    import astrbot_plugin_nikke.ui.renderers as renderers

    assert renderers.__all__ == ["T2IRenderer"]
    assert hasattr(renderers, "T2IRenderer")
    for name in ("CampaignHistoryRenderer", "ProfileCardRenderer", "UnionRaidRenderer"):
        assert not hasattr(renderers, name)


def test_ui_root_compatibility_shims_remain_absent():
    for shim in (
        "card_theme",
        "renderer",
        "campaign_history_renderer",
        "character_card_renderer",
        "profile_card_renderer",
        "union_raid_renderer",
        "t2i_renderer",
    ):
        assert importlib.util.find_spec(f"astrbot_plugin_nikke.{shim}") is None


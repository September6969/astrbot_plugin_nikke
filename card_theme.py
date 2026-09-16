# SPDX-License-Identifier: GPL-3.0-or-later
"""兼容历史导入；正式模块已迁移至 ui.theme。"""
import warnings

from .ui.theme import (
    CORPORATION_COLORS,
    ELEMENT_TINTS,
    UI_COLORS,
    UI_RADIUS,
    UI_SPACING,
    UI_TYPE_SCALE,
    CharacterTheme,
    _choose_text_colors,
    _clamp,
    _darken,
    _extract_portrait_colors,
    _extract_portrait_palette,
    _lighten,
    _mix,
    _parse,
    _relative_luminance,
    _saturate,
    _shift_toward,
    _to_hex,
    character_theme,
)

warnings.warn(
    "Importing from card_theme is deprecated, use astrbot_plugin_nikke.ui.theme instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "CORPORATION_COLORS",
    "ELEMENT_TINTS",
    "UI_COLORS",
    "UI_RADIUS",
    "UI_SPACING",
    "UI_TYPE_SCALE",
    "CharacterTheme",
    "character_theme",
    "_relative_luminance",
    "_extract_portrait_palette",
    "_parse",
]

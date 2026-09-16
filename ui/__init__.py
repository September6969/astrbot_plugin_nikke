# SPDX-License-Identifier: GPL-3.0-or-later
"""统一 UI 表现层。"""

from .primitives import CardRenderer
from .theme import (
    CORPORATION_COLORS,
    ELEMENT_TINTS,
    UI_COLORS,
    UI_RADIUS,
    UI_SPACING,
    UI_TYPE_SCALE,
    CharacterTheme,
    character_theme,
)

__all__ = [
    "CardRenderer",
    "CharacterTheme",
    "character_theme",
    "CORPORATION_COLORS",
    "ELEMENT_TINTS",
    "UI_COLORS",
    "UI_RADIUS",
    "UI_SPACING",
    "UI_TYPE_SCALE",
]

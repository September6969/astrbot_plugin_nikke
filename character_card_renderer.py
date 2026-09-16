# SPDX-License-Identifier: GPL-3.0-or-later
"""兼容历史导入；正式模块已迁移至 ui.renderers.character。"""
import warnings

from .ui.renderers.character import CharacterCardRenderer

warnings.warn(
    "Importing CharacterCardRenderer from root is deprecated, use astrbot_plugin_nikke.ui.renderers.character instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "CharacterCardRenderer",
]

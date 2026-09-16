# SPDX-License-Identifier: GPL-3.0-or-later
"""兼容历史导入；正式模块已迁移至 ui.primitives。"""
import warnings

from .ui.primitives import CardRenderer, _font

warnings.warn(
    "Importing from renderer is deprecated, use astrbot_plugin_nikke.ui.primitives instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "CardRenderer",
    "_font",
]

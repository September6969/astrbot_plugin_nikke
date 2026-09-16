# SPDX-License-Identifier: GPL-3.0-or-later
"""兼容历史导入；正式模块已迁移至 ui.renderers.profile。"""
import warnings

from .ui.renderers.profile import ProfileCardRenderer, PROFILE_THEME

warnings.warn(
    "Importing ProfileCardRenderer from root is deprecated, use astrbot_plugin_nikke.ui.renderers.profile instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "ProfileCardRenderer",
    "PROFILE_THEME",
]

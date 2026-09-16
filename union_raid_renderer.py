# SPDX-License-Identifier: GPL-3.0-or-later
"""兼容历史导入；正式模块已迁移至 ui.renderers.raid。"""
import warnings

from .ui.renderers.raid import UnionRaidRenderer, RAID_THEME

warnings.warn(
    "Importing UnionRaidRenderer from root is deprecated, use astrbot_plugin_nikke.ui.renderers.raid instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "UnionRaidRenderer",
    "RAID_THEME",
]

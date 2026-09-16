# SPDX-License-Identifier: GPL-3.0-or-later
"""兼容历史导入；正式模块已迁移至 ui.renderers.campaign。"""
import warnings

from .ui.renderers.campaign import CampaignHistoryRenderer, THEME

warnings.warn(
    "Importing CampaignHistoryRenderer from root is deprecated, use astrbot_plugin_nikke.ui.renderers.campaign instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "CampaignHistoryRenderer",
    "THEME",
]

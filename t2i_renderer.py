# SPDX-License-Identifier: GPL-3.0-or-later
"""兼容历史导入；正式模块已迁移至 ui.renderers.t2i。"""
import warnings

from .ui.renderers.t2i import T2IRenderer

warnings.warn(
    "Importing T2IRenderer from root is deprecated, use astrbot_plugin_nikke.ui.renderers.t2i instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "T2IRenderer",
]

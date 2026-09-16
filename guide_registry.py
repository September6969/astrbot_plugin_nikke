# SPDX-License-Identifier: GPL-3.0-or-later
"""兼容历史导入；正式模块已迁移至 features.guide.registry。"""
import importlib
import sys
import warnings

_real_mod = importlib.import_module(".features.guide.registry", package=__package__ or "astrbot_plugin_nikke")

# 导出公共和私有符号至全局空间以兼容静态工具与 dir()
for _k, _v in list(_real_mod.__dict__.items()):
    if not _k.startswith("__"):
        globals()[_k] = _v

warnings.warn(
    "Importing guide_registry from root is deprecated, use astrbot_plugin_nikke.features.guide.registry instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _real_mod

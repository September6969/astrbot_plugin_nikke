# SPDX-License-Identifier: GPL-3.0-or-later
"""兼容历史导入；正式模块已迁移至 integrations.spine.local_resolver。"""
import importlib
import sys
import warnings

_real_mod = importlib.import_module(".integrations.spine.local_resolver", package=__package__ or "astrbot_plugin_nikke")

# 导出符号以兼容 dir() 与直接属性读取
for _k, _v in list(_real_mod.__dict__.items()):
    if not _k.startswith("__"):
        globals()[_k] = _v

warnings.warn(
    "Importing local_spine_resolver from root is deprecated, use astrbot_plugin_nikke.integrations.spine.local_resolver instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _real_mod

# SPDX-License-Identifier: GPL-3.0-or-later
"""Backward compatibility shim for DailyRunner."""
import importlib
import sys
import warnings

_real_mod = importlib.import_module(".features.daily.runner", package=__package__ or "astrbot_plugin_nikke")
for _k, _v in list(_real_mod.__dict__.items()):
    if not _k.startswith("__"):
        globals()[_k] = _v

warnings.warn(
    "Importing daily_runner from root is deprecated, use astrbot_plugin_nikke.features.daily.runner instead.",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _real_mod

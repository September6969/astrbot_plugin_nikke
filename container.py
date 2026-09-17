# SPDX-License-Identifier: GPL-3.0-or-later
"""Backward compatibility shim for ServiceContainer and create_container."""
import importlib
import sys
import warnings

_real_mod = importlib.import_module(".core.container", package=__package__ or "astrbot_plugin_nikke")
for _k, _v in list(_real_mod.__dict__.items()):
    if not _k.startswith("__"):
        globals()[_k] = _v

warnings.warn(
    "Importing container from root is deprecated, use astrbot_plugin_nikke.core.container instead.",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _real_mod

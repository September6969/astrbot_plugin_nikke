# SPDX-License-Identifier: GPL-3.0-or-later
"""旧命令兼容入口；实现位于 scripts/spine/finalize_costume_identity_validation.py。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.shared.compat import dispatch
dispatch(__name__, globals(), "spine.finalize_costume_identity_validation")

# SPDX-License-Identifier: GPL-3.0-or-later
"""旧命令兼容入口；实现位于 scripts/spine/check_spine_candidate_promotion.py。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.shared.compat import dispatch
dispatch(__name__, globals(), "spine.check_spine_candidate_promotion")

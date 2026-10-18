# SPDX-License-Identifier: GPL-3.0-or-later
"""旧命令兼容入口；实现位于 scripts/operations/diagnose_readonly.py。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.shared.compat import dispatch
dispatch(__name__, globals(), "operations.diagnose_readonly")

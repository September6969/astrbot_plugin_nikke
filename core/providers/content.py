# SPDX-License-Identifier: GPL-3.0-or-later
"""静态攻略与塔防领域 provider。"""

from __future__ import annotations

from pathlib import Path

from ...features.guide.application import GuideApplication
from ...features.tower.application import TowerApplication


def create_guide_application(plugin_dir: Path) -> GuideApplication:
    """从插件只读资产目录创建攻略 application。"""
    return GuideApplication(plugin_dir / "assets" / "guides")


def create_tower_application(plugin_dir: Path) -> TowerApplication:
    """从插件只读资产目录创建塔防 application。"""
    return TowerApplication(plugin_dir / "assets" / "tower_floors.json")

# SPDX-License-Identifier: GPL-3.0-or-later
"""塔罗数据服务 provider。"""

from __future__ import annotations

import logging
from pathlib import Path

from ...core.privacy import safe_exception_message
from ...features.tarot.service import TarotDataError, TarotService

logger = logging.getLogger("astrbot_plugin_nikke")


def create_tarot_service(plugin_dir: Path, data_dir: Path) -> TarotService | None:
    """创建塔罗服务；数据缺失时保留原有可选 feature 行为。"""
    try:
        return TarotService(
            plugin_dir,
            data_dir / "tarot",
            deck_mode="auto",
            rotate_reversed=True,
        )
    except (OSError, ValueError, TarotDataError) as exc:
        logger.warning("[NIKKE] 塔罗服务初始化失败：%s", safe_exception_message(exc))
        return None

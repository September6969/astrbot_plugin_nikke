# SPDX-License-Identifier: GPL-3.0-or-later
"""塔罗图片解析端口。"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .models import DrawnTarotCard


class TarotImagePort(Protocol):
    """解析牌面图片；具体格式处理由外围适配器负责。"""

    def image_for(self, draw: DrawnTarotCard) -> Path | None:
        """返回当前抽牌对应的图片路径。"""


class TarotImageProviderFactory(Protocol):
    """由组合根提供塔罗图片适配器的构造方式。"""

    def __call__(
        self,
        deck: object,
        cache_dir: Path,
        *,
        rotate_reversed: bool,
    ) -> TarotImagePort:
        """为服务创建图片解析器。"""

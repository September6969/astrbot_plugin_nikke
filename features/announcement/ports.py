# SPDX-License-Identifier: GPL-3.0-or-later
"""公告投递持久化端口。"""

from __future__ import annotations

from typing import Any, Protocol


class AnnouncementStateStore(Protocol):
    """仅暴露公告投递状态所需的读写能力。"""

    def get_setting(self, key: str, default: Any = None) -> Any:
        """读取公告 feature 自己拥有的状态。"""

    def set_setting(self, key: str, value: Any) -> None:
        """原子持久化公告状态快照。"""

# SPDX-License-Identifier: GPL-3.0-or-later
"""公告投递持久化端口。"""

from __future__ import annotations

from typing import Any, Protocol

from .models import AnnouncementRecord


class AnnouncementSource(Protocol):
    """官网公告来源的最小读取端口。"""

    last_scan: dict[str, Any] | None

    async def fetch(self) -> list[AnnouncementRecord]:
        """读取并校验一批公告。"""


class AnnouncementSourceFactory(Protocol):
    """按语言和扫描预算创建官网公告来源。"""

    def __call__(
        self, locale: str, *, max_pages: int, page_size: int
    ) -> AnnouncementSource:
        """创建一次独立来源扫描。"""


class OfficialAnnouncementFetcher(Protocol):
    """兼容回退公告源的异步读取端口。"""

    async def __call__(self) -> list[AnnouncementRecord]:
        """读取官方公告列表。"""


class AnnouncementStateStore(Protocol):
    """仅暴露公告投递状态所需的读写能力。"""

    def get_setting(self, key: str, default: Any = None) -> Any:
        """读取公告 feature 自己拥有的状态。"""

    def set_setting(self, key: str, value: Any) -> None:
        """原子持久化公告状态快照。"""

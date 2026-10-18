# SPDX-License-Identifier: GPL-3.0-or-later
"""Union Raid 查询与卡片资源 provider。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from ..._version import PLUGIN_VERSION
from ...features.account.ports import AccountStorePort
from ...features.raid.application import RaidApplication
from ...features.raid.builder import UnionRaidBuilder
from ...integrations.blablalink.client import BlaBlaClient


@dataclass(frozen=True)
class RaidResources:
    """Raid builder 与 application。"""

    builder: UnionRaidBuilder
    application: RaidApplication


def create_raid_resources(
    *,
    account_reader: AccountStorePort,
    gateway: BlaBlaClient,
    clock: Callable[[], datetime],
    plugin_version: str = PLUGIN_VERSION,
    task_factory=None,
) -> RaidResources:
    """创建 Raid 查询资源，所有外部依赖均由 composition root 提供。"""
    builder = UnionRaidBuilder()
    application = RaidApplication(
        account_reader=account_reader,
        gateway=gateway,
        builder=builder,
        clock=clock,
        plugin_version=plugin_version,
        task_factory=task_factory,
    )
    return RaidResources(builder, application)

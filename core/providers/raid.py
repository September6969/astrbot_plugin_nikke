# SPDX-License-Identifier: GPL-3.0-or-later
"""Union Raid 查询与卡片资源 provider。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..._version import PLUGIN_VERSION
from ...features.account.ports import AccountStorePort
from ...features.raid.application import RaidApplication
from ...features.raid.builder import UnionRaidBuilder
from ...integrations.blablalink.client import BlaBlaClient
from ...ui.renderers import UnionRaidRenderer


@dataclass(frozen=True)
class RaidResources:
    """Raid builder、application 与 renderer。"""

    builder: UnionRaidBuilder
    application: RaidApplication
    renderer: UnionRaidRenderer


def create_raid_resources(
    plugin_dir: Path,
    data_dir: Path,
    *,
    account_reader: AccountStorePort,
    gateway: BlaBlaClient,
    clock: Callable[[], datetime],
    plugin_version: str = PLUGIN_VERSION,
) -> RaidResources:
    """创建一组 Raid 资源，所有外部依赖均由 composition root 提供。"""
    builder = UnionRaidBuilder()
    application = RaidApplication(
        account_reader=account_reader,
        gateway=gateway,
        builder=builder,
        clock=clock,
        plugin_version=plugin_version,
    )
    renderer = UnionRaidRenderer(data_dir / "cards", plugin_dir / "fonts")
    return RaidResources(builder, application, renderer)

# SPDX-License-Identifier: GPL-3.0-or-later
"""Campaign 查询和卡片资源 provider。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ...features.campaign.application import CampaignApplication
from ...features.campaign.builder import CampaignHistoryBuilder
from ...features.campaign.stage_resolver import CampaignStageResolver
from ...features.account.ports import AccountStorePort
from ...integrations.blablalink.client import BlaBlaClient
from ..._version import PLUGIN_VERSION


@dataclass(frozen=True)
class CampaignResources:
    """共享 Campaign resolver 与该领域的应用资源。"""

    resolver: CampaignStageResolver
    builder: CampaignHistoryBuilder
    application: CampaignApplication


def create_campaign_resources(
    plugin_dir: Path,
    *,
    account_reader: AccountStorePort,
    gateway: BlaBlaClient,
    clock: Callable[[], datetime],
    plugin_version: str = PLUGIN_VERSION,
) -> CampaignResources:
    """创建 Campaign 的唯一 resolver、builder 与 application。"""
    resolver = CampaignStageResolver.from_file(
        plugin_dir / "assets" / "campaign_stages.json"
    )
    builder = CampaignHistoryBuilder()
    application = CampaignApplication(
        resolver=resolver,
        gateway=gateway,
        account_reader=account_reader,
        builder=builder,
        clock=clock,
        plugin_version=plugin_version,
    )
    return CampaignResources(resolver, builder, application)

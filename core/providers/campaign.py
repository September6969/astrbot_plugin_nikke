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
from ...ui.renderers import CampaignHistoryRenderer
from ...core.asset_manager import AssetManager
from ..._version import PLUGIN_VERSION


@dataclass(frozen=True)
class CampaignResources:
    """共享 Campaign resolver 与该领域的应用/表现资源。"""

    resolver: CampaignStageResolver
    builder: CampaignHistoryBuilder
    renderer: CampaignHistoryRenderer
    application: CampaignApplication


def create_campaign_resources(
    plugin_dir: Path,
    data_dir: Path,
    *,
    account_reader: AccountStorePort,
    gateway: BlaBlaClient,
    asset_manager: AssetManager,
    clock: Callable[[], datetime],
    plugin_version: str = PLUGIN_VERSION,
) -> CampaignResources:
    """创建 Campaign 的唯一 resolver、builder、renderer 与 application。"""
    resolver = CampaignStageResolver.from_file(
        plugin_dir / "assets" / "campaign_stages.json"
    )
    builder = CampaignHistoryBuilder()
    renderer = CampaignHistoryRenderer(
        data_dir / "cards", plugin_dir / "fonts", asset_manager
    )
    application = CampaignApplication(
        resolver=resolver,
        gateway=gateway,
        account_reader=account_reader,
        builder=builder,
        clock=clock,
        plugin_version=plugin_version,
    )
    return CampaignResources(resolver, builder, renderer, application)

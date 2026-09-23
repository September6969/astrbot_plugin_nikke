# SPDX-License-Identifier: GPL-3.0-or-later
"""Profile 查询和卡片资源 provider。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..._version import PLUGIN_VERSION
from ...core.asset_manager import AssetManager
from ...features.campaign.stage_resolver import CampaignStageResolver
from ...features.profile.application import ProfileApplication
from ...features.profile.builder import ProfileBuilder
from ...integrations.blablalink.client import BlaBlaClient
from ...ui.renderers import ProfileCardRenderer


@dataclass(frozen=True)
class ProfileResources:
    """Profile 的 builder、application 与 renderer。"""

    builder: ProfileBuilder
    application: ProfileApplication
    renderer: ProfileCardRenderer


def create_profile_resources(
    plugin_dir: Path,
    data_dir: Path,
    *,
    gateway: BlaBlaClient,
    campaign_resolver: CampaignStageResolver,
    asset_manager: AssetManager,
    clock: Callable[[], datetime],
    plugin_version: str = PLUGIN_VERSION,
) -> ProfileResources:
    """以共享 Campaign resolver 和 AssetManager 创建 Profile 资源。"""
    builder = ProfileBuilder(campaign_resolver=campaign_resolver)
    application = ProfileApplication(
        gateway=gateway,
        builder=builder,
        clock=clock,
        plugin_version=plugin_version,
    )
    renderer = ProfileCardRenderer(
        data_dir / "cards",
        plugin_dir / "fonts",
        currency_icon_provider=asset_manager.get_currency_icon,
    )
    return ProfileResources(builder, application, renderer)

# SPDX-License-Identifier: GPL-3.0-or-later
"""Profile 查询和卡片资源 provider。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from ..._version import PLUGIN_VERSION
from ...features.campaign.stage_resolver import CampaignStageResolver
from ...features.profile.application import ProfileApplication
from ...features.profile.builder import ProfileBuilder
from ...integrations.blablalink.client import BlaBlaClient


@dataclass(frozen=True)
class ProfileResources:
    """Profile 的 builder 与 application。"""

    builder: ProfileBuilder
    application: ProfileApplication


def create_profile_resources(
    *,
    gateway: BlaBlaClient,
    campaign_resolver: CampaignStageResolver,
    clock: Callable[[], datetime],
    plugin_version: str = PLUGIN_VERSION,
) -> ProfileResources:
    """以共享 Campaign resolver 创建 Profile 资源。"""
    builder = ProfileBuilder(campaign_resolver=campaign_resolver)
    application = ProfileApplication(
        gateway=gateway,
        builder=builder,
        clock=clock,
        plugin_version=plugin_version,
    )
    return ProfileResources(builder, application)

# SPDX-License-Identifier: GPL-3.0-or-later
"""Daily 自动任务 provider。"""

from __future__ import annotations

from typing import Any

from ...features.daily.ports import DailyStore
from ...features.daily.runner import DailyRunner
from ...integrations.blablalink.client import BlaBlaClient
from ...features.daily.actions import CommunityTaskService
from ...features.account.renewal import SessionRenewalService
from ...integrations.blablalink.community_actions import CommunityActionsGateway
from ...integrations.blablalink.session_renewal import SessionRenewalGateway
from ...integrations.blablalink.session_cookies import renewal_payload


def create_daily_runner(
    *, client: BlaBlaClient, store: DailyStore, config: dict[str, Any]
) -> DailyRunner:
    """创建持有显式 client/store 端口的 DailyRunner。"""
    return DailyRunner(client=client, store=store, config=config)


def create_community_automation(*, client, store, config, runner):
    """复用日常账号锁及现有客户端，不创建额外常驻任务或浏览器。"""
    gateway = CommunityActionsGateway(client)
    tasks = CommunityTaskService(gateway=gateway, store=store, config=config, account_lock=runner._account_lock)
    renewal = SessionRenewalService(gateway=SessionRenewalGateway(client, gateway), store=store, config=config,
                                    account_lock=runner._account_lock, preflight=renewal_payload)
    return tasks, renewal

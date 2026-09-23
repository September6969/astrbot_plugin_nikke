# SPDX-License-Identifier: GPL-3.0-or-later
"""Daily 自动任务 provider。"""

from __future__ import annotations

from typing import Any

from ...features.daily.ports import DailyStore
from ...features.daily.runner import DailyRunner
from ...integrations.blablalink.client import BlaBlaClient


def create_daily_runner(
    *, client: BlaBlaClient, store: DailyStore, config: dict[str, Any]
) -> DailyRunner:
    """创建持有显式 client/store 端口的 DailyRunner。"""
    return DailyRunner(client=client, store=store, config=config)

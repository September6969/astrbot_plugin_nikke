# SPDX-License-Identifier: GPL-3.0-or-later
"""统一编排 Daily、汇总、公告与日程的周期任务。"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import read_schedule_clock
from .coordinator import RuntimeCoordinator
from .ports import SchedulerSettingsStore


class RuntimeScheduler:
    """按持久化时刻和有界间隔提交后台任务给 coordinator。"""

    def __init__(
        self,
        *,
        coordinator: RuntimeCoordinator,
        store: SchedulerSettingsStore,
        config: Mapping[str, Any],
        run_daily: Callable[..., Awaitable[Any]],
        send_summary: Callable[[str], Awaitable[Any]],
        sync_announcements: Callable[[], Awaitable[Any]],
        sync_calendar: Callable[[], Awaitable[Any]],
        dispatch_announcements: Callable[[], Awaitable[Any]],
        clock: Callable[[], datetime] | None = None,
        unix_time: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        poll_interval: float = 20.0,
        announcement_interval: float = 3600.0,
        calendar_interval: float = 300.0,
    ) -> None:
        self._coordinator = coordinator
        self._store = store
        self._config = config
        self._run_daily = run_daily
        self._send_summary = send_summary
        self._sync_announcements = sync_announcements
        self._sync_calendar = sync_calendar
        self._dispatch_announcements = dispatch_announcements
        self._clock = clock or (
            lambda: datetime.now(timezone(timedelta(hours=8)))
        )
        self._unix_time = unix_time
        self._sleep = sleep
        self._poll_interval = poll_interval
        self._announcement_interval = announcement_interval
        self._calendar_interval = calendar_interval
        self._last_daily = ""
        self._last_summary = ""
        self._last_announcement_sync = 0.0
        self._last_calendar_sync = 0.0
        self._announcement_push_task: asyncio.Task | None = None

    async def tick(self) -> None:
        """执行一次时钟检查，便于 fake clock 验证而不启动无限循环。"""
        if self._coordinator.closing:
            return
        now = self._clock()
        today = now.strftime("%Y-%m-%d")
        daily_hour, daily_minute = read_schedule_clock(
            self._store.get_setting,
            "daily",
            default_hour=self._config["daily_hour"],
            default_minute=self._config["daily_minute"],
        )
        summary_hour, summary_minute = read_schedule_clock(
            self._store.get_setting,
            "summary",
            default_hour=self._config["summary_hour"],
            default_minute=self._config["summary_minute"],
        )
        if (now.hour, now.minute) == (daily_hour, daily_minute) and self._last_daily != today:
            self._last_daily = today
            self._coordinator.create_task(
                self._run_daily(today, stagger=True, automatic=True)
            )
        if (
            (now.hour, now.minute) == (summary_hour, summary_minute)
            and self._last_summary != today
        ):
            self._last_summary = today
            self._coordinator.create_task(self._send_summary(today))

        current_epoch = self._unix_time()
        if current_epoch - self._last_announcement_sync > self._announcement_interval:
            self._last_announcement_sync = current_epoch
            self._coordinator.create_task(self._sync_announcements())
        if current_epoch - self._last_calendar_sync > self._calendar_interval:
            self._last_calendar_sync = current_epoch
            self._coordinator.create_task(self._sync_calendar())
        if self._config.get("enable_announcement_push", False):
            task = self._announcement_push_task
            if task is None or task.done():
                self._announcement_push_task = self._coordinator.create_task(
                    self._dispatch_announcements()
                )

    async def run(self) -> None:
        """持续轮询；退出与取消由 RuntimeCoordinator 管理。"""
        while not self._coordinator.closing:
            await self.tick()
            await self._sleep(self._poll_interval)

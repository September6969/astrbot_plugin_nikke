# SPDX-License-Identifier: GPL-3.0-or-later
"""统一编排 Daily、汇总、公告、日程与角色数据的周期任务。"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import read_schedule_clock
from ..privacy import safe_exception_message
from .coordinator import RuntimeCoordinator
from .ports import SchedulerSettingsStore


_LOGGER = logging.getLogger(__name__)
_MAX_BACKOFF_SECONDS = 300.0
_WARNING_INTERVAL_SECONDS = 600.0
_CST = timezone(timedelta(hours=8))
# 汇总补发窗口：前序日常耗时或重启都不应丢失汇总；超出窗口不再补发。
SUMMARY_CATCHUP = timedelta(hours=6)
SUMMARY_SENT_KEY = "daily_summary_sent:{day}"


def community_due(community_day: str, hour: int, minute: int) -> datetime:
    """社区日（UTC 日期，北京时间 08:00 起算）内配置的北京时间时刻。

    北京时间 00:00–07:59 属于前一个社区日的末尾，因此落在社区日的次日日历上；
    这样 daily_hour < 8 时不会在社区日开始（08:00）就提前约 22 小时触发。
    """
    day = datetime.strptime(community_day, "%Y-%m-%d")
    due = datetime(day.year, day.month, day.day, hour, minute, tzinfo=_CST)
    return due + timedelta(days=1) if hour < 8 else due


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
        dispatch_calendar: Callable[[], Awaitable[Any]] | None = None,
        dispatch_feeds: Callable[[], Awaitable[Any]] | None = None,
        sync_character_data: Callable[[], Awaitable[Any]] | None = None,
        clock: Callable[[], datetime] | None = None,
        unix_time: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        poll_interval: float = 20.0,
        announcement_interval: float = 3600.0,
        calendar_interval: float = 300.0,
        character_interval: float = 1800.0,
    ) -> None:
        self._coordinator = coordinator
        self._store = store
        self._config = config
        self._run_daily = run_daily
        self._send_summary = send_summary
        self._sync_announcements = sync_announcements
        self._sync_calendar = sync_calendar
        self._dispatch_announcements = dispatch_announcements
        self._dispatch_calendar = dispatch_calendar
        self._dispatch_feeds = dispatch_feeds
        self._sync_character_data = sync_character_data
        self._calendar_push_task = None
        self._feed_push_task = None
        self._clock = clock or (
            lambda: datetime.now(timezone(timedelta(hours=8)))
        )
        self._unix_time = unix_time
        self._sleep = sleep
        self._poll_interval = poll_interval
        self._announcement_interval = announcement_interval
        self._calendar_interval = calendar_interval
        self._character_interval = character_interval
        self._last_daily = ""
        self._daily_task = None
        self._last_summary = ""
        self._last_announcement_sync = 0.0
        self._last_calendar_sync = 0.0
        self._last_character_sync = unix_time() if sync_character_data is not None else 0.0
        self._character_sync_task: asyncio.Task | None = None
        self._announcement_push_task: asyncio.Task | None = None

    async def tick(self) -> None:
        """执行一次时钟检查，便于 fake clock 验证而不启动无限循环。"""
        if self._coordinator.closing:
            return
        now = self._clock()
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
        # 社区按 UTC 零点（北京时间 08:00）刷新；日常与汇总统一按同一社区日计算，
        # 错过时刻允许当天补跑，汇总与结果使用同一日期键。
        community_day = now.astimezone(timezone.utc).strftime("%Y-%m-%d")
        if (now >= community_due(community_day, daily_hour, daily_minute)
            and self._last_daily != community_day
            and (self._daily_task is None or self._daily_task.done())):
            self._last_daily = community_day
            self._daily_task = self._coordinator.create_task(
                self._run_daily(community_day, stagger=True, automatic=True)
            )
        self._maybe_send_summary(now, community_day, summary_hour, summary_minute)

        current_epoch = self._unix_time()
        if current_epoch - self._last_announcement_sync > self._announcement_interval:
            self._last_announcement_sync = current_epoch
            self._coordinator.create_task(self._sync_announcements())
        if current_epoch - self._last_calendar_sync > self._calendar_interval:
            self._last_calendar_sync = current_epoch
            self._coordinator.create_task(self._sync_calendar())
        if (
            self._sync_character_data is not None
            and current_epoch - self._last_character_sync >= self._character_interval
            and (self._character_sync_task is None or self._character_sync_task.done())
        ):
            self._last_character_sync = current_epoch
            self._character_sync_task = self._coordinator.create_task(self._sync_character_data())
        if self._dispatch_calendar is not None:
            task = self._calendar_push_task
            if task is None or task.done():
                self._calendar_push_task = self._coordinator.create_task(self._dispatch_calendar())
        if self._dispatch_feeds is not None:
            task = self._feed_push_task
            if task is None or task.done():
                self._feed_push_task = self._coordinator.create_task(self._dispatch_feeds())
        if self._config.get("enable_announcement_push", False):
            task = self._announcement_push_task
            if task is None or task.done():
                self._announcement_push_task = self._coordinator.create_task(
                    self._dispatch_announcements()
                )

    def _maybe_send_summary(self, now: datetime, community_day: str, hour: int, minute: int) -> None:
        """到点后在补发窗口内发送一次；等待同日日常结束；数据库幂等键防止重启重发。"""
        due = community_due(community_day, hour, minute)
        if not due <= now < due + SUMMARY_CATCHUP or self._last_summary == community_day:
            return
        if self._daily_task is not None and not self._daily_task.done():
            return
        key = SUMMARY_SENT_KEY.format(day=community_day)
        if self._store.get_setting(key, None):
            self._last_summary = community_day
            return
        self._last_summary = community_day
        setter = getattr(self._store, "set_setting", None)
        if callable(setter):
            # 先落标记再发送：宁可极端崩溃时少发一次，也不在同分钟重启时重复发送。
            setter(key, {"sent_at": now.astimezone(timezone.utc).isoformat()})
        self._coordinator.create_task(self._send_summary(community_day))

    async def run(self) -> None:
        """持续轮询；退出与取消由 RuntimeCoordinator 管理。

        单次 tick 失败（如 SQLite 锁超时）只退避重试并节流告警，不让调度循环
        和宿主生命周期整体失败；只有取消信号向上传播。
        """
        failures = 0
        last_warning = float("-inf")
        while not self._coordinator.closing:
            delay = self._poll_interval
            try:
                await self.tick()
                failures = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failures += 1
                delay = min(self._poll_interval * (2 ** min(failures, 8)), _MAX_BACKOFF_SECONDS)
                now = self._unix_time()
                if failures == 1 or now - last_warning >= _WARNING_INTERVAL_SECONDS:
                    last_warning = now
                    _LOGGER.warning(
                        "[NIKKE] 调度检查失败（连续 %d 次），%.0f 秒后重试：%s",
                        failures,
                        delay,
                        safe_exception_message(exc),
                    )
            await self._sleep(delay)

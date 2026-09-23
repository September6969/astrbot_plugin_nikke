# SPDX-License-Identifier: GPL-3.0-or-later
"""Daily 手动、自动与状态命令用例。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from ...features.daily.models import DailyTaskResult, DailyTaskStatus
from ...features.daily.ports import DailyAccountReader, DailyCommandStore
from ...features.daily.runner import DailyRunner
from ...integrations.blablalink.client import CookieExpired
from .contracts import CommandContext, CommandResult, ImageReply, TextReply


DailySummaryRenderer = Callable[[Sequence[tuple[str, str]]], str]
DailySummarySender = Callable[[str, str], Awaitable[None]]


class DailyCommandHandler:
    """把 Daily 命令、批次调度和汇总结果集中在 framework-free 用例边界。"""

    def __init__(
        self,
        *,
        account_reader: DailyAccountReader,
        store: DailyCommandStore,
        runner: DailyRunner,
        client: Any,
        config: Mapping[str, Any],
        render_summary: DailySummaryRenderer,
        send_summary: DailySummarySender,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self._account_reader = account_reader
        self._store = store
        self._runner = runner
        self._client = client
        self._config = config
        self._render_summary = render_summary
        self._send_summary = send_summary
        self._clock = clock or self._today

    async def handle(self, context: CommandContext) -> CommandResult:
        """处理手动签到、只读状态与本地自动签到偏好。"""
        action = context.parameters.get("action", "").strip().casefold()
        if action in {"状态", "status"}:
            return await self._status(context.actor_id)
        if action in {"自动", "auto"}:
            return self._set_auto(context.actor_id, context.parameters.get("value", ""))
        if action:
            return self._text("用法：/妮姬 签到 [状态] 或 /妮姬 日常 自动 开|关")
        if not bool(self._config.get("enable_daily_actions", False)):
            return self._text("签到写操作当前由管理员关闭；可使用 /妮姬 签到 状态 只读查询。")

        try:
            account = self._account(context.actor_id)
        except Exception as exc:
            return self._text(f"签到失败：{exc}")
        if account is None:
            return self._text("尚未绑定账号，请先私聊发送 /妮姬 账号 绑定")
        try:
            result = await self._runner.run_daily_for_account(account, self._clock())
            return self._text(f"{result.account_name}：{result.detail}")
        except Exception as exc:
            return self._text(f"签到失败：{exc}")

    async def run_all_daily(
        self,
        day: str,
        *,
        stagger: bool = False,
        automatic: bool = False,
    ) -> list[DailyTaskResult]:
        """运行手动或自动批次，选择和持久化语义由 DailyRunner 统一负责。"""
        return await self._runner.run_all_daily(
            day, stagger=stagger, automatic=automatic
        )

    async def render_manual_summary(self) -> str:
        """执行管理员手动批次并渲染既有图片汇总。"""
        results = await self.run_all_daily(self._clock())
        return self._render_summary([result.summary_row() for result in results])

    async def send_automatic_summary(self, day: str) -> None:
        """只发送自动范围结果；无效或缺失缓存时重新计算自动批次。"""
        group_umo = self._store.get_setting("summary_group_umo", "")
        if not group_umo:
            return
        stored = self._store.get_setting(f"daily_results:{day}:automatic", [])
        results = (
            [DailyTaskResult.from_storage(item) for item in stored]
            if isinstance(stored, list)
            else []
        )
        if not results or any(result is None for result in results):
            results = await self.run_all_daily(day, automatic=True)
        rows = [result.summary_row() for result in results if result is not None]
        await self._send_summary(group_umo, self._render_summary(rows))

    def _set_auto(self, actor_id: str, value: str) -> CommandResult:
        value_key = value.strip().casefold()
        if value_key not in {"开", "on", "1", "关", "off", "0"}:
            return self._text("用法：/妮姬 日常 自动 开|关")
        if self._account(actor_id) is None:
            return self._text("尚未绑定账号，请先私聊发送 /妮姬 账号 绑定")
        enabled = value_key in {"开", "on", "1"}
        self._store.set_auto_daily(actor_id, enabled)
        global_state = (
            "全局签到写操作当前关闭；设置已保存，暂不会提交。"
            if not bool(self._config.get("enable_daily_actions", False))
            else "仍需保持每日汇总开启，定时任务才会处理此账号。"
        )
        return self._text(f"自动签到已{'开启' if enabled else '关闭'}。{global_state}")

    async def _status(self, actor_id: str) -> CommandResult:
        try:
            account = self._account(actor_id)
            if account is None:
                return self._text("尚未绑定账号，请先私聊发送 /妮姬 账号 绑定")
            await self._client.get_profile(account)
            status = await self._client.get_daily_signin(account)
            if not status["found"]:
                detail = "未找到签到任务"
            elif status["completed"]:
                detail = "今日已签到"
            else:
                detail = "今日待签到"
            return self._text(detail)
        except CookieExpired:
            self._store.mark_cookie_invalid(actor_id)
            return self._text("登录状态已失效，请重新发送 /妮姬 账号 绑定。")
        except Exception as exc:
            return self._text(f"查询失败：{exc}")

    def _account(self, actor_id: str) -> dict[str, Any] | None:
        account = self._account_reader.get_account(actor_id)
        return dict(account) if account is not None else None

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")

    @staticmethod
    def _text(text: str) -> CommandResult:
        return CommandResult((TextReply(text),))

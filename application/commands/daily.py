# SPDX-License-Identifier: GPL-3.0-or-later
"""Daily 手动、自动与状态命令用例。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
import asyncio
import hashlib

from datetime import datetime, timedelta, timezone
from typing import Any

from ...features.daily.models import DailyTaskResult, DailyTaskStatus
from ...features.daily.ports import DailyAccountReader, DailyCommandStore
from ...features.daily.runner import DailyRunner
from ...integrations.blablalink.client import CookieExpired
from ...features.account.errors import CredentialExpiredError
from ...core.privacy import safe_exception_message
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
        send_notice: Callable[[str, str], Awaitable[Any]] | None = None,
    ) -> None:
        self._account_reader = account_reader
        self._store = store
        self._runner = runner
        self._client = client
        self._config = config
        self._render_summary = render_summary
        self._send_summary = send_summary
        self._clock = clock or self._today
        self._send_notice = send_notice
        self._runner.on_automatic_result = self._notify_failure

    async def handle(self, context: CommandContext) -> CommandResult:
        """处理手动签到、只读状态与本地自动签到偏好。"""
        action = context.parameters.get("action", "").strip().casefold()
        community = context.parameters.get("scope") == "community"
        if community and context.is_private_chat and context.conversation_id:
            account = self._account(context.actor_id)
            if account:
                self._store.set_setting(f"daily_private:{context.actor_id}", {
                    "identity": DailyRunner.daily_identity(account), "conversation": context.conversation_id})
        if action in {"状态", "status"}:
            return await self._community_status(context.actor_id) if community else await self._status(context.actor_id)
        if action in {"自动", "auto"}:
            return self._set_auto(context.actor_id, context.parameters.get("value", ""), community=community)
        if action:
            return self._text("用法：/妮姬 签到 [状态] 或 /妮姬 日常 自动 开|关")
        if not bool(self._config.get("enable_daily_actions", False)):
            return self._text("签到写操作当前由管理员关闭；可使用 /妮姬 签到 状态 只读查询。")

        try:
            account = self._account(context.actor_id)
        except Exception as exc:
            return self._text(f"签到失败：{safe_exception_message(exc)}")
        if account is None:
            return self._text("尚未绑定账号，请先私聊发送 /妮姬 账号 绑定")
        try:
            run = self._runner.run_community_for_account if community else self._runner.run_daily_for_account
            result = await run(account, self._clock())
            return self._text(f"{result.account_name}：{result.detail}")
        except Exception as exc:
            return self._text(f"签到失败：{safe_exception_message(exc)}")

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
            return
        # 新版社区日常成功静默，只保留旧用户显式配置的签到群汇总。
        rows = [result.summary_row() for result in results if result is not None and not result.items]
        if rows:
            await self._send_summary(group_umo, self._render_summary(rows))

    def _set_auto(self, actor_id: str, value: str, *, community: bool = False) -> CommandResult:
        value_key = value.strip().casefold()
        if value_key not in {"开", "on", "1", "关", "off", "0"}:
            return self._text("用法：/妮姬 日常 自动 开|关")
        account = self._account(actor_id)
        if account is None:
            return self._text("尚未绑定账号，请先私聊发送 /妮姬 账号 绑定")
        enabled = value_key in {"开", "on", "1"}
        self._store.set_auto_daily(actor_id, enabled)
        self._store.set_setting(f"daily_scope_v2:{actor_id}",
            DailyRunner.daily_identity(account) if enabled and community else "")
        global_state = (
            "全局签到写操作当前关闭；设置已保存，暂不会提交。"
            if not bool(self._config.get("enable_daily_actions", False))
            else "定时任务独立执行；成功静默，仅异常私聊。"
        )
        return self._text(("范围：社区签到及已达成的免费奖励。请私聊使用日常命令登记异常通知会话。" if community else "范围：仅签到。") + f"自动签到已{'开启' if enabled else '关闭'}。{global_state}")

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
        except (CookieExpired, CredentialExpiredError):
            self._store.mark_cookie_invalid(actor_id)
            return self._text("登录状态已失效，请重新发送 /妮姬 账号 绑定。")
        except Exception as exc:
            return self._text(f"查询失败：{safe_exception_message(exc)}")

    async def _community_status(self, actor_id: str) -> CommandResult:
        try:
            account = self._account(actor_id)
            if not account:
                return self._text("尚未绑定账号，请先私聊发送 /妮姬 账号 绑定")
            status = await self._client.get_daily_signin(account)
            lines = ["社区日常（北京时间08:00刷新）", "签到：" + (
                "已签到" if status["completed"] else "待签到" if status["found"] else "未找到任务")]
            rewards = await self._client.get_community_rewards(account)
            labels = {"pending": "尚未达成", "claimable": "可领取", "claimed": "已领取", "unknown": "状态未知"}
            lines.extend(f"{r['name']}：{labels[r['state']]}" for r in rewards)
            if not rewards:
                lines.append("免费任务奖励：本次未返回记录")
            identity = hashlib.sha256(DailyRunner.daily_identity(account).encode()).hexdigest()
            previous = self._store.get_setting(f"community_daily:last:{identity}", {})
            if isinstance(previous, dict) and previous.get("detail"):
                lines.append("最近执行（UTC日期 " + str(previous.get("day", "未知")) + "）：\n" + previous["detail"])
            return self._text("\n".join(lines))
        except (CookieExpired, CredentialExpiredError):
            self._store.mark_cookie_invalid(actor_id)
            return self._text("登录状态已失效，请重新发送 /妮姬 账号 绑定。")
        except Exception:
            return self._text("社区日常状态暂不可用，未提交任何写操作。")

    async def _notify_failure(self, account, day, result):
        if result.status not in {DailyTaskStatus.FAILED, DailyTaskStatus.RATE_LIMITED,
                DailyTaskStatus.COOKIE_EXPIRED, DailyTaskStatus.UNKNOWN_AFTER_ACTION, DailyTaskStatus.UNAVAILABLE}:
            return
        if self._send_notice is None:
            return
        actor = str(account["qq_id"])
        current = self._account_reader.get_account(actor, with_cookie=False)
        identity = DailyRunner.daily_identity(account)
        if not current or not current.get("auto_daily_enabled") or DailyRunner.daily_identity(current) != identity:
            return
        route = self._store.get_setting(f"daily_private:{actor}", {})
        if not isinstance(route, dict) or route.get("identity") != identity or not route.get("conversation"):
            return
        key = DailyRunner.daily_run_key(day, account, "notice:" + result.status.value)
        if not self._store.claim_run(key, actor, "daily_notice", initial_status="DISPATCH_INTENT"):
            return
        try:
            sent = await asyncio.wait_for(self._send_notice(route["conversation"],
                "【社区日常需处理】\n" + result.detail + "\n/妮姬 日常 状态 查看；/妮姬 日常 自动 关 停止自动执行。"), 10)
            self._store.finish_run(key, "success" if sent is not False else "failed", "异常私聊发送已处理")
        except asyncio.CancelledError:
            self._store.finish_run(key, "UNKNOWN_AFTER_ACTION", "通知结果未知，不重复发送")
            raise
        except Exception:
            self._store.finish_run(key, "UNKNOWN_AFTER_ACTION", "通知结果未知，不重复发送")

    def _account(self, actor_id: str) -> dict[str, Any] | None:
        account = self._account_reader.get_account(actor_id)
        return dict(account) if account is not None else None

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    @staticmethod
    def _text(text: str) -> CommandResult:
        return CommandResult((TextReply(text),))

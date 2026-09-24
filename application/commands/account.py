# SPDX-License-Identifier: GPL-3.0-or-later
"""账号和管理命令的框架无关处理器。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

from ...features.account.application import AccountApplication
from .contracts import CommandContext, CommandResult, ImageReply, TextReply


@dataclass(frozen=True)
class RuntimeHealthDetails:
    """由宿主装配的只读运行时诊断信息。"""

    plugin_version: str
    directory_count: int
    web_host: str
    web_port: int
    daily_actions_enabled: bool
    cdk_redemption_enabled: bool
    diagnostics: str


class AccountCommandHandler:
    """承载账号、绑定以及管理员设置命令的权限和回复合同。"""

    _PUSH_ENABLED: Final = {"on", "开", "开启", "1"}
    _PUSH_DISABLED: Final = {"off", "关", "关闭", "0"}

    def __init__(
        self,
        *,
        application: AccountApplication,
        public_base_url: str,
        allow_group_bind: bool,
        runtime_health: Callable[[], RuntimeHealthDetails],
        render_manual_summary: Callable[[], Awaitable[str]],
    ) -> None:
        self._application = application
        self._public_base_url = public_base_url
        self._allow_group_bind = allow_group_bind
        self._runtime_health = runtime_health
        self._render_manual_summary = render_manual_summary

    async def handle(self, context: CommandContext) -> CommandResult:
        """按显式操作分派账号或管理员命令。"""
        operation = context.parameters.get("operation", "").strip().casefold()
        if operation == "account":
            return await self._account(context)
        if operation == "admin":
            return await self._admin(context)
        if operation in {
            "bind",
            "unbind",
            "status",
            "push",
            "group_set",
            "schedule",
            "summary",
            "run",
            "health",
        }:
            return await self._direct_operation(context, operation)
        return self._text("未知指令。发送 /妮姬 帮助 查看可用功能。")

    async def _account(self, context: CommandContext) -> CommandResult:
        action = context.parameters.get("action", "").strip().casefold()
        value = context.parameters.get("value", "")
        if action in {"", "状态", "status"}:
            return self._status(context)
        if action in {"绑定", "bind"}:
            return self._bind(context)
        if action in {"解绑", "unbind"}:
            return self._unbind(context)
        if action in {"汇总", "push"}:
            if not value:
                return self._text("用法：/妮姬 账号 汇总 开|关")
            return self._push(context, value)
        return self._text("用法：/妮姬 账号 [绑定|状态|解绑|汇总 开|关]")

    async def _admin(self, context: CommandContext) -> CommandResult:
        if not context.is_admin:
            return self._text("仅管理员可使用管理指令。")
        action = context.parameters.get("action", "").strip().casefold()
        if action in {"设群", "group"}:
            return self._group_set(context, authorized=True)
        if action in {"任务时间", "schedule"}:
            return self._schedule(
                context, context.parameters.get("value", ""), authorized=True
            )
        if action in {"汇总时间", "summary"}:
            return self._summary(
                context, context.parameters.get("value", ""), authorized=True
            )
        if action in {"执行", "run"}:
            return await self._run(context, authorized=True)
        if action in {"健康", "health"}:
            return self._health(context, authorized=True)
        return self._text(
            "用法：/妮姬 管理 [设群|任务时间 HH:MM|汇总时间 HH:MM|执行|健康]"
        )

    async def _direct_operation(
        self, context: CommandContext, operation: str
    ) -> CommandResult:
        if operation == "bind":
            return self._bind(context)
        if operation == "unbind":
            return self._unbind(context)
        if operation == "status":
            return self._status(context)
        if operation == "push":
            state = context.parameters.get("state", context.parameters.get("value", ""))
            return self._push(context, state)
        if operation == "group_set":
            return self._group_set(
                context,
                authorized=False,
                action=context.parameters.get("action", "set"),
            )
        if operation == "schedule":
            return self._schedule(
                context, context.parameters.get("value", ""), authorized=False
            )
        if operation == "summary":
            return self._summary(
                context, context.parameters.get("value", ""), authorized=False
            )
        if operation == "run":
            return await self._run(context, authorized=False)
        return self._health(context, authorized=False)

    def _bind(self, context: CommandContext) -> CommandResult:
        if not context.is_private_chat and not self._allow_group_bind:
            return self._text(
                "为防止绑定链接被他人抢先使用，请私聊机器人发送 /妮姬 账号 绑定。"
            )
        url = self._application.create_binding_url(
            context.actor_id, self._public_base_url
        )
        return self._text(
            "🔐 NIKKE · BlaBlaLink 安全绑定\n\n"
            "绑定链接（10 分钟有效，仅可使用一次）：\n"
            f"{url}\n\n"
            "请勿转发此链接。\n\n"
            "打开后请按照网页内的完整教程完成：\n"
            "1. 安装 NIKKE QQ 安全绑定助手\n"
            "2. 登录 BlaBlaLink\n"
            "3. 点击扩展中的「已登录，提交绑定」\n\n"
            "账号密码只在 BlaBlaLink 官方网站输入，\n"
            "机器人不会接收或保存你的账号密码。"
        )

    def _unbind(self, context: CommandContext) -> CommandResult:
        removed = self._application.unbind(context.actor_id)
        return self._text("已解除绑定。" if removed else "当前QQ尚未绑定。")

    def _status(self, context: CommandContext) -> CommandResult:
        account = self._application.account_status(context.actor_id)
        if not account:
            return self._text("未绑定，请私聊发送 /妮姬 账号 绑定。")
        state = "有效" if account["cookie_valid"] else "已失效，请重新绑定"
        return self._text(
            f"已绑定：{account['nickname'] or account['role_name'] or '未命名指挥官'}\n"
            f"区服ID：{account['area_id'] or '待识别'}\nCookie：{state}\n"
            f"每日汇总：{'开启' if account['push_enabled'] else '关闭'}\n"
            f"自动签到：{'开启' if account.get('auto_daily_enabled') else '关闭'}"
        )

    def _push(self, context: CommandContext, state: str) -> CommandResult:
        normalized = state.lower()
        if normalized not in self._PUSH_ENABLED | self._PUSH_DISABLED:
            return self._text("用法：/妮姬 账号 汇总 开|关")
        enabled = normalized in self._PUSH_ENABLED
        changed = self._application.set_daily_summary(context.actor_id, enabled)
        if not changed:
            return self._text("请先绑定账号。")
        return self._text("每日汇总已开启。" if enabled else "每日汇总已关闭。")

    def _group_set(
        self,
        context: CommandContext,
        *,
        authorized: bool,
        action: str = "",
    ) -> CommandResult:
        if not authorized and not context.is_admin:
            return self._text("仅管理员可配置汇总群。")
        if action.strip().casefold() not in {"", "set", "设群"}:
            return self._text("用法：/妮姬 管理 设群")
        group = context.parameters.get("unified_msg_origin", "")
        self._application.set_setting("summary_group_umo", group)
        return self._text(f"每日汇总目标已设为当前会话：{group}")

    def _schedule(
        self, context: CommandContext, clock: str, *, authorized: bool
    ) -> CommandResult:
        if not authorized and not context.is_admin:
            return self._text("仅管理员可修改时间。")
        try:
            hour, minute = self._parse_clock(clock)
            self._application.set_setting("daily_hour", hour)
            self._application.set_setting("daily_minute", minute)
            return self._text(f"每日任务时间已设为 {hour:02d}:{minute:02d}。")
        except Exception:
            return self._text("用法：/妮姬 管理 任务时间 HH:MM")

    def _summary(
        self, context: CommandContext, clock: str, *, authorized: bool
    ) -> CommandResult:
        if not authorized and not context.is_admin:
            return self._text("仅管理员可修改时间。")
        try:
            hour, minute = self._parse_clock(clock)
            self._application.set_setting("summary_hour", hour)
            self._application.set_setting("summary_minute", minute)
            return self._text(f"每日汇总时间已设为 {hour:02d}:{minute:02d}。")
        except Exception:
            return self._text("用法：/妮姬 管理 汇总时间 HH:MM")

    async def _run(self, context: CommandContext, *, authorized: bool) -> CommandResult:
        if not authorized and not context.is_admin:
            return self._text("仅管理员可执行全量任务。")
        return CommandResult((ImageReply(await self._render_manual_summary()),))

    def _health(self, context: CommandContext, *, authorized: bool) -> CommandResult:
        if not authorized and not context.is_admin:
            return self._text("仅管理员可查看。")
        details = self._runtime_health()
        return self._text(
            f"NIKKE插件 {details.plugin_version}\n账号：{self._application.account_count()}\n"
            f"目录：{details.directory_count}\n绑定服务：{details.web_host}:{details.web_port}\n"
            f"自动签到：{'启用' if details.daily_actions_enabled else '关闭'}\n"
            f"CDK兑换：{'启用' if details.cdk_redemption_enabled else '关闭'}\n"
            f"{details.diagnostics}"
        )

    @staticmethod
    def _parse_clock(value: str) -> tuple[int, int]:
        hour, minute = value.split(":", 1)
        parsed_hour, parsed_minute = int(hour), int(minute)
        if not (0 <= parsed_hour <= 23 and 0 <= parsed_minute <= 59):
            raise ValueError("时间范围错误")
        return parsed_hour, parsed_minute

    @staticmethod
    def _text(text: str) -> CommandResult:
        return CommandResult((TextReply(text),))

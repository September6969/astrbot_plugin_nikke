# SPDX-License-Identifier: GPL-3.0-or-later
"""双入口导航命令用例：公共大厅 /hall、指挥官工作台 /workspace 与纯 @机器人 引导。"""

from __future__ import annotations

from typing import Protocol

from .contracts import CommandContext, CommandResult, TextReply


class PortalLinksPort(Protocol):
    public_base_url: str

    def hall_public_url(self) -> str:
        """公共大厅直达链接。"""

    def create_hall_group_url(
        self, actor_id: str, conversation_id: str, group_label: str = ""
    ) -> str:
        """为当前群聊创建一次性大厅反馈引导链接。"""

    def create_workspace_url(
        self, actor_id: str, *, conversation_id: str = "", group_label: str = ""
    ) -> str:
        """为用户创建一次性工作台引导链接。"""


class PortalCommandHandler:
    """处理 /妮姬 大厅、/妮姬 工作台 与纯 @机器人 无正文响应。"""

    def __init__(
        self,
        *,
        portal_links: PortalLinksPort | None = None,
        public_base_url: str = "https://nikke.irises777.xyz",
        allow_group_workspace: bool = False,
    ) -> None:
        self._links = portal_links
        self._base = str(public_base_url).rstrip("/")
        self._allow_group_workspace = bool(allow_group_workspace)

    async def handle(self, context: CommandContext) -> CommandResult:
        mode = str(context.parameters.get("mode", "") or "").strip().casefold()
        if mode == "hall":
            return CommandResult((TextReply(self._hall_reply(context)),))
        if mode == "workspace":
            return CommandResult((TextReply(self._workspace_reply(context)),))
        if mode == "mention":
            return CommandResult((TextReply(self._mention_reply(context)),))
        return CommandResult((TextReply(self._mention_reply(context)),))

    def _hall_reply(self, context: CommandContext) -> str:
        public_url = (
            self._links.hall_public_url()
            if self._links is not None
            else f"{self._base}/hall"
        )
        if not context.is_private_chat and context.conversation_id and self._links is not None:
            try:
                group_url = self._links.create_hall_group_url(
                    context.actor_id,
                    context.conversation_id,
                    group_label=f"QQ群({context.conversation_id[-6:]})",
                )
                return (
                    "【NIKKE 公共功能大厅】\n"
                    f"带当前群聊反馈入口（可将日程 / 塔罗结果推送回本群，15 分钟内点击有效）：\n{group_url}\n\n"
                    f"匿名公共大厅（仅浏览，不连群）：{public_url}\n"
                    "需要管理个人绑定、练度或五队编组，请私聊机器人发送 /妮姬 工作台。"
                )
            except ValueError:
                pass
        return (
            "【NIKKE 公共功能大厅】\n"
            f"无需登录即可查看全部功能、复制口令、查日程卡池或抽塔罗：\n{public_url}\n"
            "需要管理个人账号或五队编组，请发送 /妮姬 工作台。"
        )

    def _workspace_reply(self, context: CommandContext) -> str:
        if not context.is_private_chat and not self._allow_group_workspace:
            return (
                "个人指挥官工作台包含绑定状态与账号分析入口。\n"
                "为保护你的链接不被群友误点，请私聊机器人发送：/妮姬 工作台"
            )
        if self._links is None:
            return "个人指挥官工作台尚未完成装配，请稍后重试。"
        try:
            url = self._links.create_workspace_url(
                context.actor_id,
                conversation_id=context.conversation_id,
                group_label=(
                    "私聊当前会话"
                    if context.is_private_chat
                    else f"QQ群({context.conversation_id[-6:]})"
                ),
            )
        except ValueError as exc:
            return str(exc)
        return (
            "【NIKKE 个人指挥官工作台】\n"
            "请点击以下一次性安全链接进入（15 分钟内首次进入有效，页面采用按需懒加载）：\n"
            f"{url}\n"
            "仅限个人使用，切勿转发他人。"
        )

    def _mention_reply(self, context: CommandContext) -> str:
        public_url = (
            self._links.hall_public_url()
            if self._links is not None
            else f"{self._base}/hall"
        )
        group_tip = (
            "｜发送 /妮姬 大厅 可带本群反馈入口"
            if not context.is_private_chat
            else ""
        )
        return (
            "你好，指挥官！NIKKE 综合助手已收束为双网页入口 + QQ 命令：\n"
            f"1. 公共功能大厅（无需登录）：{public_url}{group_tip}\n"
            "2. 个人指挥官工作台：私聊发送 /妮姬 工作台\n"
            "3. 常用指令：/妮姬 帮助｜/妮姬 日程｜/妮姬 塔罗｜/妮姬 我的"
        )

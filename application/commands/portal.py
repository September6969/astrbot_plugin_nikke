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
                    f"点击下方链接可直接打开，也能把日程、塔罗抽牌结果推回本群（15 分钟内有效）：\n{group_url}\n\n"
                    f"如果只是自己随便看看，也可以用公开直达链接：{public_url}\n"
                    "想绑定账号或查个人练度、五队配队，请私聊我发送 /妮姬 工作台。"
                )
            except ValueError:
                pass
        return (
            "【NIKKE 公共功能大厅】\n"
            f"不用登录就能看日程、卡池、公告攻略、算同步器或抽塔罗：\n{public_url}\n"
            "想看个人账号数据或配队，请发送 /妮姬 工作台。"
        )

    def _workspace_reply(self, context: CommandContext) -> str:
        if not context.is_private_chat and not self._allow_group_workspace:
            return (
                "个人工作台里有你的账号绑定和私人练度数据。\n"
                "为防链接被群友点开，请私聊我发送 /妮姬 工作台 获取专属入口。"
            )
        if self._links is None:
            return "个人工作台暂时不可用，请稍后再试。"
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
            "请点下面的链接进入工作台（15 分钟内有效，仅限本人使用，切勿转发）：\n"
            f"{url}"
        )

    def _mention_reply(self, context: CommandContext) -> str:
        public_url = (
            self._links.hall_public_url()
            if self._links is not None
            else f"{self._base}/hall"
        )
        group_tip = (
            "（群内发 /妮姬 大厅 可一键把结果推回本群）"
            if not context.is_private_chat
            else ""
        )
        return (
            "你好，指挥官！需要我做什么？\n"
            f"• 公共大厅（免登录查日程/工具/塔罗）：{public_url}{group_tip}\n"
            "• 个人工作台：私聊我发送 /妮姬 工作台\n"
            "• 常用命令：/妮姬 帮助 ｜ /妮姬 日程 ｜ /妮姬 我的 ｜ /妮姬 同步器"
        )

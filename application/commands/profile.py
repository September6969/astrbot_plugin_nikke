"""Profile 命令用例；账号读取、数据构建与图片展示各走一个注入端口。"""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from ...features.profile.application import ProfileApplication
from ...features.profile.models import ProfileDashboardData
from .contracts import CommandContext, CommandResult, ImageReply, TextReply


class ProfileAccountReader(Protocol):
    """读取命令发起者绑定账号的最小接口。"""

    def get_account(self, qq_id: str) -> Mapping[str, Any] | None:
        """读取账号及 Profile gateway 所需凭据。"""


ProfilePresenter = Callable[[ProfileDashboardData], Awaitable[str]]


class ProfileCommandHandler:
    """将 Profile application 结果转换为单张图片命令结果。"""

    def __init__(
        self,
        *,
        account_reader: ProfileAccountReader,
        application: ProfileApplication,
        present: ProfilePresenter,
    ) -> None:
        self._account_reader = account_reader
        self._application = application
        self._present = present

    async def handle(self, context: CommandContext) -> CommandResult:
        """读取绑定账号、构建 dashboard 并产生既有图片回复。"""
        account = self._account_reader.get_account(context.actor_id)
        if not account:
            return CommandResult(
                (
                    TextReply(
                        "查询失败：尚未绑定账号，请先私聊发送 /妮姬 账号 绑定"
                    ),
                )
            )

        dashboard = await self._application.build_dashboard(account)
        image_path = await self._present(dashboard)
        return CommandResult((ImageReply(image_path),))

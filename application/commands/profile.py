"""Profile 命令用例；账号读取、数据构建与图片展示各走一个注入端口。"""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from ...core.privacy import safe_exception_message
from ...features.profile.application import ProfileApplication
from ...features.profile.models import ProfileDashboardData
from ...integrations.blablalink.client import BlaBlaError, CookieExpired
from .contracts import (
    CommandContext,
    CommandFeedbackStarter,
    CommandResult,
    ImageReply,
    TextReply,
)


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
        invalidate_cookie: Callable[[str], None] | None = None,
        start_feedback: CommandFeedbackStarter | None = None,
    ) -> None:
        self._account_reader = account_reader
        self._application = application
        self._present = present
        self._invalidate_cookie = invalidate_cookie or (lambda _actor_id: None)
        self._start_feedback = start_feedback

    async def handle(self, context: CommandContext) -> CommandResult:
        """读取绑定账号、构建 dashboard 并产生既有图片回复。"""
        feedback = None
        if self._start_feedback is not None:
            feedback = self._start_feedback(context, "正在生成个人账号概览...")
        try:
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
        except CookieExpired:
            self._invalidate_cookie(context.actor_id)
            return CommandResult(
                (TextReply("登录状态已失效，请重新发送 /妮姬 账号 绑定。"),)
            )
        except (BlaBlaError, ValueError, RuntimeError) as exc:
            return CommandResult(
                (TextReply(f"查询失败：{safe_exception_message(exc)}"),)
            )
        finally:
            if feedback is not None:
                await feedback.cancel()

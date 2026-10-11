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


def format_profile(data: ProfileDashboardData) -> str:
    """图片不可用时保留同一快照中的核心资料与未知值。"""
    def value(item):
        return "未知" if item is None else str(item)

    lines = [f"个人资料 · {data.commander_name}",
             f"指挥官等级：{value(data.commander_level)} · 同步器：{value(data.synchro_level)}",
             f"普通主线：{value(data.normal_campaign)} · 困难主线：{value(data.hard_campaign)}",
             f"角色数量：{value(data.character_count)}"]
    if data.daily_available is False:
        lines.append("今日进度：暂时无法获取")
    else:
        lines.extend([f"拦截剩余：{value(data.intercept_remaining)}",
                      f"咨询剩余：{value(data.counsel_remaining)}",
                      f"派遣完成：{value(data.dispatch_completed)} · 进行中：{value(data.dispatch_in_progress)}"])
    lines.extend([f"更新时间：{data.fetched_at}", "图片生成失败，已显示文字摘要。"])
    return "\n".join(lines)


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
            try:
                image_path = await self._present(dashboard)
                if not image_path:
                    raise RuntimeError("图片未生成")
            except Exception:
                return CommandResult((TextReply(format_profile(dashboard)),))
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

"""Profile 命令用例；账号读取、数据构建与图片展示各走一个注入端口。"""

import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from ...features.profile.application import ProfileApplication
from ...features.profile.currency_registry import CurrencyRegistry
from ...features.profile.models import ProfileDashboardData
from ...features.account.errors import CredentialExpiredError
from .errors import CREDENTIAL_EXPIRED_TEXT, user_error_message
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
HistoryRecorder = Callable[[CommandContext, ProfileDashboardData], Any]
logger = logging.getLogger(__name__)


def format_profile(data: ProfileDashboardData) -> str:
    """图片不可用时保留同一快照中的核心资料与未知值。"""
    def value(item):
        if item is None:
            return "未知"
        return f"{item:,}" if isinstance(item, int) and not isinstance(item, bool) else str(item)

    lines = [f"个人资料 · {data.commander_name}",
             f"区服：{value(data.area_id or None)} · 队伍总战力：{value(data.team_combat)}",
             f"指挥官等级：{value(data.commander_level)} · 同步器：{value(data.synchro_level)}",
             f"普通主线：{value(data.normal_campaign)} · 困难主线：{value(data.hard_campaign)}",
             f"角色数量：{value(data.character_count)}"]
    if data.daily_available is False:
        lines.append("今日进度：暂时无法获取")
    else:
        lines.extend([f"拦截剩余：{value(data.intercept_remaining)}",
                      f"咨询剩余：{value(data.counsel_remaining)}",
                      f"派遣完成：{value(data.dispatch_completed)} · 进行中：{value(data.dispatch_in_progress)}"])
    lines.append("资源" + ("（部分）" if data.currencies_partial else "："))
    if data.currencies_partial:
        lines[-1] += "："
    known_types = set(CurrencyRegistry.DEFINITIONS)
    currencies = data.currencies
    for definition in CurrencyRegistry.DEFINITIONS.values():
        matches = [item for item in currencies or [] if item.type == definition.type]
        label = definition.display_name
        if len(matches) > 1:
            amount = "多条记录"
        elif matches:
            amount = value(matches[0].value)
        else:
            amount = "未知" if currencies is None else "未返回"
        lines.append(f"{label}：{amount}")
    extras = [
        item for item in currencies or [] if item.type not in known_types
    ]
    if extras:
        lines.append("其他已返回资源：")
        lines.extend(
            f"未识别资源（类型 {item.type}）：{value(item.value)}"
            for item in extras
        )
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
        record_history: HistoryRecorder | None = None,
        growth_generation: Callable[[str], int] | None = None,
    ) -> None:
        self._account_reader = account_reader
        self._application = application
        self._present = present
        self._invalidate_cookie = invalidate_cookie or (lambda _actor_id: None)
        self._start_feedback = start_feedback
        self._record_history = record_history
        self._growth_generation = growth_generation

    @staticmethod
    def _supports_kwarg(fn: Any, name: str) -> bool:
        try:
            params = inspect.signature(fn).parameters.values()
        except (TypeError, ValueError):
            return False
        return any(
            p.kind == inspect.Parameter.VAR_KEYWORD or p.name == name
            for p in params
        )

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

            generation = (
                self._growth_generation(context.actor_id)
                if self._growth_generation is not None
                else None
            )
            dashboard = await self._application.build_dashboard(account)
            if self._record_history is not None:
                try:
                    kwargs: dict[str, Any] = {}
                    if self._supports_kwarg(self._record_history, "account"):
                        kwargs["account"] = account
                    if self._supports_kwarg(self._record_history, "expected_generation"):
                        kwargs["expected_generation"] = generation
                    self._record_history(context, dashboard, **kwargs)
                except Exception as exc:
                    # 历史记录失败不能影响资料主流程；也不写入半成品快照。
                    logger.warning("[NIKKE] 养成历史记录跳过：%s", type(exc).__name__)
            try:
                image_path = await self._present(dashboard)
                if not image_path:
                    raise RuntimeError("图片未生成")
            except Exception:
                return CommandResult((TextReply(format_profile(dashboard)),))
            return CommandResult((ImageReply(image_path),))
        except CredentialExpiredError:
            self._invalidate_cookie(context.actor_id)
            return CommandResult((TextReply(CREDENTIAL_EXPIRED_TEXT),))
        except (ValueError, RuntimeError) as exc:
            return CommandResult(
                (TextReply(f"查询失败：{user_error_message(exc)}"),)
            )
        finally:
            if feedback is not None:
                await feedback.cancel()

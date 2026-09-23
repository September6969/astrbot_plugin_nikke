"""塔罗命令用例；以显式文本/图片结果与 AstrBot 解耦。"""

import logging

from ...core.privacy import safe_exception_message
from ...features.tarot.service import TarotDataError, TarotService
from .contracts import CommandContext, CommandResult, ImageReply, TextReply


_LOGGER = logging.getLogger(__name__)


class TarotCommandHandler:
    def __init__(self, service: TarotService | None):
        self.service = service

    async def handle(self, context: CommandContext) -> CommandResult:
        service = self.service
        if service is None:
            return CommandResult(
                (TextReply("塔罗功能暂不可用：牌库资源尚未准备完成。"),)
            )

        action = context.parameters.get("action", "").strip().casefold()
        if action in {"", "帮助", "help"}:
            return CommandResult((TextReply(service.format_help()),))
        if action in {"状态", "status"}:
            return CommandResult((TextReply(service.format_status()),))

        try:
            if action in {"单抽", "单张", "single", "one"}:
                reading = service.draw_single()
            elif action in {"三张", "三张牌", "three", "spread"}:
                reading = service.draw_three()
            elif action in {"今日", "每日", "daily", "today"}:
                user_key = f"{context.platform_name}:{context.actor_id}"
                reading = service.draw_daily(user_key)
            else:
                return CommandResult(
                    (
                        TextReply(
                            "用法：/妮姬 塔罗 [单抽|三张|今日|状态|帮助]"
                        ),
                    )
                )

            messages = [
                ImageReply(str(image_path))
                for image_path in service.image_paths(reading)
                if image_path is not None
            ]
            messages.append(TextReply(service.format_reading(reading)))
            return CommandResult(tuple(messages))
        except TarotDataError as exc:
            _LOGGER.warning(
                "[NIKKE] 塔罗牌库错误：%s", safe_exception_message(exc)
            )
            return CommandResult((TextReply("塔罗牌库暂不可用，请稍后再试。"),))
        except (OSError, ValueError) as exc:
            _LOGGER.warning(
                "[NIKKE] 塔罗抽牌失败：%s", safe_exception_message(exc)
            )
            return CommandResult((TextReply("塔罗抽牌失败，请稍后再试。"),))

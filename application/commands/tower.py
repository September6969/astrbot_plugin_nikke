"""塔层命令到框架无关查询用例的薄适配。"""

from ...features.tower.application import TowerApplication
from .contracts import CommandContext, CommandResult, TextReply


class TowerCommandHandler:
    def __init__(self, application: TowerApplication) -> None:
        self.application = application

    async def handle(self, context: CommandContext) -> CommandResult:
        text = await self.application.describe(
            context.parameters.get("tower", ""),
            context.parameters.get("floor", ""),
        )
        return CommandResult((TextReply(text),))

from pathlib import Path

import pytest

from astrbot_plugin_nikke.application.commands.contracts import CommandContext, TextReply
from astrbot_plugin_nikke.application.commands.tower import TowerCommandHandler
from astrbot_plugin_nikke.features.tower.application import TowerApplication


@pytest.mark.asyncio
async def test_tower_command_reads_verified_static_snapshot_without_account() -> None:
    root = Path(__file__).resolve().parents[1]
    application = TowerApplication(root / "assets" / "tower_floors.json")

    result = await TowerCommandHandler(application).handle(
        CommandContext(parameters={"tower": "极乐净土", "floor": "1"})
    )

    assert len(result.messages) == 1
    assert isinstance(result.messages[0], TextReply)
    assert "7,740" in result.messages[0].text

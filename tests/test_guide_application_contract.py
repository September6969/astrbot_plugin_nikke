from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from astrbot_plugin_nikke.application.commands.contracts import CommandContext, TextReply
from astrbot_plugin_nikke.application.commands.guide import GuideCommandHandler
from astrbot_plugin_nikke.features.guide.application import GuideApplication


@pytest.mark.asyncio
async def test_guide_command_uses_injected_page_size_and_clock(tmp_path: Path) -> None:
    image = tmp_path / "guide.png"
    image.write_bytes(b"fixture")
    rows = [
        {
            "id": f"guide-{index}",
            "category": "progression",
            "title": f"攻略-{index}",
            "files": [image.name],
            "source": "fixture source",
            "credit": "fixture author",
            "license": "fixture license",
            "updated_at": "2026-01-01",
            "game_version": "fixture version",
        }
        for index in range(5)
    ]
    (tmp_path / "registry.json").write_text(
        json.dumps(rows, ensure_ascii=False), encoding="utf-8"
    )
    application = GuideApplication(
        tmp_path,
        page_size=2,
        clock=lambda: date(2026, 4, 2),
    )

    result = await GuideCommandHandler(application).handle(
        CommandContext(parameters={"category": "练度", "page": "1"})
    )

    texts = [message.text for message in result.messages if isinstance(message, TextReply)]
    assert "第 1/3 页" in texts[0]
    assert sum(text.startswith("攻略-") for text in texts) == 2
    assert all("内容可能过期" in text for text in texts if text.startswith("攻略-"))

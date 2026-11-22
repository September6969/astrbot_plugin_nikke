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


# PR-6B G7-misc-dead-e：GuideApplication 按 registry.json stat 签名缓存已校验索引。


def _write_registry(root: Path, titles: list[str], image_name: str = "guide.png") -> None:
    rows = [
        {
            "id": f"guide-{index}",
            "category": "progression",
            "title": title,
            "files": [image_name],
            "source": "fixture source",
            "credit": "fixture author",
            "license": "fixture license",
            "updated_at": "2026-01-01",
            "game_version": "fixture version",
        }
        for index, title in enumerate(titles)
    ]
    (root / "registry.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def _counting_factory():
    from astrbot_plugin_nikke.features.guide.registry import GuideRegistry

    calls: list[Path] = []

    def factory(root: Path) -> GuideRegistry:
        calls.append(root)
        return GuideRegistry(root)

    return calls, factory


def test_guide_registry_is_loaded_once_while_unchanged(tmp_path: Path) -> None:
    (tmp_path / "guide.png").write_bytes(b"fixture")
    _write_registry(tmp_path, ["攻略-A"])
    calls, factory = _counting_factory()
    application = GuideApplication(tmp_path, registry_factory=factory)
    assert [e.title for e in application.page("progression").entries] == ["攻略-A"]
    assert [e.title for e in application.page("progression").entries] == ["攻略-A"]
    assert len(calls) == 1


def test_guide_registry_reloads_when_signature_changes(tmp_path: Path) -> None:
    import os

    (tmp_path / "guide.png").write_bytes(b"fixture")
    _write_registry(tmp_path, ["攻略-A"])
    calls, factory = _counting_factory()
    application = GuideApplication(tmp_path, registry_factory=factory)
    application.page("progression")
    _write_registry(tmp_path, ["攻略-B", "攻略-C"])
    registry = tmp_path / "registry.json"
    stat = registry.stat()
    os.utime(registry, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    page = application.page("progression")
    assert [e.title for e in page.entries] == ["攻略-B", "攻略-C"]
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_guide_image_deleted_after_caching_fails_closed(tmp_path: Path) -> None:
    image = tmp_path / "guide.png"
    image.write_bytes(b"fixture")
    _write_registry(tmp_path, ["攻略-A"])
    application = GuideApplication(tmp_path)
    assert application.page("progression").entries
    image.unlink()
    result = await GuideCommandHandler(application).handle(
        CommandContext(parameters={"category": "练度", "page": "1"})
    )
    assert result.messages[0].text.startswith("攻略索引暂不可用")


def test_guide_registry_missing_then_added_is_picked_up(tmp_path: Path) -> None:
    calls, factory = _counting_factory()
    application = GuideApplication(tmp_path, registry_factory=factory)
    assert application.page("progression").total_entries == 0
    (tmp_path / "guide.png").write_bytes(b"fixture")
    _write_registry(tmp_path, ["攻略-A"])
    assert application.page("progression").total_entries == 1


def test_guide_failed_registry_load_is_never_cached(tmp_path: Path) -> None:
    (tmp_path / "registry.json").write_text("{not json", encoding="utf-8")
    calls, factory = _counting_factory()
    application = GuideApplication(tmp_path, registry_factory=factory)
    for _ in range(2):
        with pytest.raises(ValueError):
            application.page("progression")
    assert len(calls) == 2

# SPDX-License-Identifier: GPL-3.0-or-later
"""05/27 真实入口接线：调度发送器、通知人范围与账号同步后的成长快照。"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot_plugin_nikke.adapters.astrbot.runtime import AstrBotRuntimeAdapter
from astrbot_plugin_nikke.application.commands.contracts import (
    CommandContext,
    CommandResult,
    ImageReply,
)
from astrbot_plugin_nikke.application.commands.character import CharacterCommandHandler
from astrbot_plugin_nikke.application.commands.profile import ProfileCommandHandler
from astrbot_plugin_nikke.features.character.application import CharacterRosterData
from astrbot_plugin_nikke.features.announcement.feeds import (
    FeedCatalog,
    FeedItem,
    FeedSubscriptions,
    VideoCatalog,
)


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def get_setting(self, key, default=None):
        return self.values.get(key, default)

    def set_setting(self, key, value):
        self.values[key] = value


class StaticCatalog:
    def __init__(self, items: list[FeedItem]) -> None:
        self._items = list(items)

    def items(self, *, now):
        return tuple(self._items)


class UnavailableVideoSource:
    cached_items = ()
    last_error = "测试未同步"

    async def refresh(self, *, now=None):
        return self.cached_items


def feed_item(title: str = "合成新闻", entity_id: str = "n1") -> FeedItem:
    return FeedItem(
        kind="news",
        entity_id=entity_id,
        version=2,
        title=title,
        url="https://example.invalid/news/1",
        published_at="2026-09-20T00:00:00+00:00",
    )


@pytest.mark.asyncio
async def test_runtime_feed_dispatch_mentions_only_subscriber_and_skips_without_subscription() -> None:
    store = MemoryStore()
    news = StaticCatalog([])
    feeds = FeedSubscriptions(
        store,
        FeedCatalog({"news": news, "schedule": StaticCatalog([]), "video": VideoCatalog(UnavailableVideoSource())}),
        clock=lambda: datetime(2026, 9, 21, tzinfo=timezone.utc),
    )
    coordinator = SimpleNamespace(closing=False, create_task=lambda coro: None)
    runtime = object.__new__(AstrBotRuntimeAdapter)
    runtime._coordinator = coordinator
    runtime._services = SimpleNamespace(toolbox=SimpleNamespace(feeds=feeds))
    runtime._context = SimpleNamespace(send_message=AsyncMock(return_value=True))

    # 无订阅：即使有新闻也不发送。
    news._items.append(feed_item())
    await runtime._dispatch_feeds()
    runtime._context.send_message.assert_not_awaited()

    target = FeedSubscriptions.target_key("group:1", "user-a", False)
    feeds.command(target, "订阅", "新闻")
    news._items.append(feed_item("第二条新闻", entity_id="n2"))
    await runtime._dispatch_feeds()

    runtime._context.send_message.assert_awaited_once()
    conversation, chain = runtime._context.send_message.await_args.args
    assert conversation == "group:1"
    components = chain.chain
    assert any(getattr(component, "qq", None) == "user-a" for component in components)
    assert any("第二条新闻" in getattr(component, "text", "") for component in components)

    # 本轮已投递，跨轮询不重复。
    await runtime._dispatch_feeds()
    assert runtime._context.send_message.await_count == 1


def dashboard() -> SimpleNamespace:
    return SimpleNamespace(
        commander_name="合成指挥官",
        area_id="1",
        team_combat=1000,
        commander_level=150,
        synchro_level=200,
        normal_campaign="10-1",
        hard_campaign="5-1",
        character_count=80,
        daily_available=False,
        intercept_remaining=None,
        counsel_remaining=None,
        dispatch_completed=None,
        dispatch_in_progress=None,
        currencies=[],
        currencies_partial=False,
        fetched_at="2026-09-21 12:00",
    )


class FakeApplication:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    async def build_dashboard(self, _account):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return dashboard()


def profile_handler(application, recorded: list) -> ProfileCommandHandler:
    async def present(_dashboard):
        return "synthetic.png"

    def record(context, dashboard):
        recorded.append((context.actor_id, dashboard))

    return ProfileCommandHandler(
        account_reader=SimpleNamespace(
            get_account=lambda _actor: {"nickname": "合成指挥官", "game_uid": "1"}
        ),
        application=application,
        present=present,
        record_history=record,
    )


@pytest.mark.asyncio
async def test_growth_history_records_only_after_successful_account_sync() -> None:
    recorded: list = []
    handler = profile_handler(FakeApplication(), recorded)
    result = await handler.handle(CommandContext(actor_id="user-a"))

    assert result.messages == (ImageReply("synthetic.png"),)
    assert len(recorded) == 1
    assert recorded[0][0] == "user-a"

    recorded.clear()
    handler = profile_handler(FakeApplication(error=ValueError("上游失败")), recorded)
    failed = await handler.handle(CommandContext(actor_id="user-a"))
    assert failed.messages and "上游失败" in failed.messages[0].text
    assert recorded == []

    # 历史记录本身失败不影响资料返回，也不写入半成品。
    async def no_image(_dashboard):
        return None

    handler = ProfileCommandHandler(
        account_reader=SimpleNamespace(get_account=lambda _actor: {"nickname": "合成"}),
        application=FakeApplication(),
        present=no_image,
        record_history=lambda _context, _dashboard: (_ for _ in ()).throw(RuntimeError("存储失败")),
    )
    result = await handler.handle(CommandContext(actor_id="user-a"))
    assert isinstance(result, CommandResult)
    assert result.messages


@pytest.mark.asyncio
async def test_roster_snapshot_hook_runs_only_after_successful_roster_read() -> None:
    recorded: list = []

    async def image(_data):
        return "synthetic.png"

    class RosterApplication:
        def __init__(self, error=None):
            self.error = error

        async def roster(self, _actor, _directory):
            if self.error is not None:
                raise self.error
            return CharacterRosterData(
                commander_name="合成指挥官",
                characters=(
                    {"name_code": 1001, "lv": 200, "grade": 2},
                    {"name_code": 1002, "lv": 180, "grade": 0},
                ),
                name_map={},
            )

    def handler(application):
        return CharacterCommandHandler(
            application=application,
            directory=lambda: (),
            render_roster=image,
            render_card=image,
            invalidate_cookie=lambda _actor: None,
            record_roster=lambda actor, rows: recorded.append((actor, tuple(rows))),
        )

    result = await handler(RosterApplication()).handle(CommandContext(actor_id="user-a"))
    assert result.messages == (ImageReply("synthetic.png"),)
    assert len(recorded) == 1
    assert recorded[0][0] == "user-a"
    assert len(recorded[0][1]) == 2

    recorded.clear()
    failed = await handler(RosterApplication(error=ValueError("上游失败"))).handle(
        CommandContext(actor_id="user-a")
    )
    assert failed.messages and "上游失败" in failed.messages[0].text
    assert recorded == []

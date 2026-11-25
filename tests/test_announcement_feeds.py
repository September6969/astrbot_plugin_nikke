# SPDX-License-Identifier: GPL-3.0-or-later
"""05 官方新闻与通知：假发送器验证无订阅不发、跨轮询去重、订阅隔离与源不可用。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

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
        self._items = items

    def items(self, *, now):
        return tuple(self._items)


class FakeVideoSource:
    """测试用视频缓存：默认未同步，可显式注入已缓存条目。"""

    def __init__(self, items=()) -> None:
        self.cached_items = tuple(items)
        self.last_error = "" if items else "尚未完成首次同步"
        self.refresh_calls = 0

    async def refresh(self, *, now=None):
        self.refresh_calls += 1
        return self.cached_items


def item(kind: str, entity_id: str, version: int = 1, title: str = "合成条目") -> FeedItem:
    return FeedItem(
        kind=kind,
        entity_id=entity_id,
        version=version,
        title=title,
        url=f"https://example.invalid/{kind}/{entity_id}",
        published_at="2026-09-20T00:00:00+00:00",
    )


def build(news: list[FeedItem] | None = None, schedule: list[FeedItem] | None = None):
    store = MemoryStore()
    catalog = FeedCatalog(
        {
            "news": StaticCatalog(news or []),
            "schedule": StaticCatalog(schedule or []),
            "video": VideoCatalog(FakeVideoSource()),
        }
    )
    subs = FeedSubscriptions(store, catalog, clock=lambda: datetime(2026, 9, 21, tzinfo=timezone.utc))
    return store, catalog, subs


class Sender:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool, str]] = []

    async def __call__(self, conversation, actor, private, text):
        self.calls.append((conversation, actor, private, text))
        return True


def target(actor: str, conversation: str = "group:1", private: bool = False) -> str:
    return FeedSubscriptions.target_key(conversation, actor, private)


@pytest.mark.asyncio
async def test_no_subscription_means_no_read_and_no_send() -> None:
    _, _, subs = build(news=[item("news", "n1")])
    sender = Sender()

    result = await subs.dispatch_due(sender, now=datetime(2026, 9, 21, tzinfo=timezone.utc))

    assert result == {"succeeded": 0, "failed": 0, "unknown": 0}
    assert sender.calls == []


@pytest.mark.asyncio
async def test_cross_poll_dedupe_and_baseline_at_subscribe() -> None:
    news = [item("news", "n1", title="旧新闻")]
    store, catalog, subs = build(news=news)
    key = target("user-a")
    subs.command(key, "订阅", "新闻")

    sender = Sender()
    now = datetime(2026, 9, 21, tzinfo=timezone.utc)
    await subs.dispatch_due(sender, now=now)
    assert sender.calls == [], "订阅前的旧新闻不能补推"

    news.append(item("news", "n2", title="新新闻"))
    await subs.dispatch_due(sender, now=now)
    assert len(sender.calls) == 1
    assert sender.calls[0][1] == "user-a"
    assert "新新闻" in sender.calls[0][3]

    # 跨轮询不重复。
    await subs.dispatch_due(sender, now=now)
    await subs.dispatch_due(sender, now=now)
    assert len(sender.calls) == 1


@pytest.mark.asyncio
async def test_subscription_kinds_are_isolated_between_users() -> None:
    store, catalog, subs = build(
        news=[item("news", "n1", title="新闻一")],
        schedule=[item("schedule", "s1", title="活动一")],
    )
    subs.command(target("user-a", "group:1"), "订阅", "新闻")
    subs.command(target("user-b", "group:2", private=True), "订阅", "日程")
    # 重新写入基线后追加新条目，模拟两条新内容。
    catalog._catalogs["news"]._items.append(item("news", "n2", title="新闻二"))
    catalog._catalogs["schedule"]._items.append(item("schedule", "s2", title="活动二"))

    sender = Sender()
    await subs.dispatch_due(sender, now=datetime(2026, 9, 21, tzinfo=timezone.utc))

    by_actor = {call[1]: call for call in sender.calls}
    assert set(by_actor) == {"user-a", "user-b"}
    assert "新闻二" in by_actor["user-a"][3]
    assert "活动" not in by_actor["user-a"][3]
    assert "活动二" in by_actor["user-b"][3]
    assert by_actor["user-b"][2] is True

    # user-a 取消新闻后不再收到任何新内容。
    subs.command(target("user-a", "group:1"), "取消订阅", "新闻")
    catalog._catalogs["news"]._items.append(item("news", "n3", title="新闻三"))
    sender.calls.clear()
    await subs.dispatch_due(sender, now=datetime(2026, 9, 21, tzinfo=timezone.utc))
    assert all(call[1] != "user-a" for call in sender.calls)


@pytest.mark.asyncio
async def test_unavailable_source_skips_delivery_and_is_reported() -> None:
    store, catalog, subs = build()
    key = target("user-a")
    subs.command(key, "订阅", "视频")

    sender = Sender()
    result = await subs.dispatch_due(sender, now=datetime(2026, 9, 21, tzinfo=timezone.utc))
    assert result["succeeded"] == 0
    assert sender.calls == []

    status = subs.command(key, "状态", "")
    assert "视频来源：暂不可用" in status
    # 订阅状态仍然保留，恢复来源后可继续使用。
    assert "已订阅（个人订阅）：视频" in status


def test_kind_parsing_and_partial_unsubscribe() -> None:
    _, _, subs = build(news=[item("news", "n1")], schedule=[item("schedule", "s1")])
    key = target("user-a")
    assert "已订阅" in subs.command(key, "订阅", "新闻,日程")
    assert "已订阅（个人订阅）：新闻、日程" in subs.command(key, "状态", "")
    with pytest.raises(ValueError, match="未知订阅类型"):
        subs.command(key, "订阅", "直播")

    assert "剩余：日程" in subs.command(key, "取消订阅", "新闻")
    assert "已取消你在当前会话的全部订阅" in subs.command(key, "取消订阅", "")
    assert "尚未开通订阅" in subs.command(key, "状态", "")


def test_schedule_catalog_uses_calendar_application_snapshot_and_maps_identity() -> None:
    """回归：ScheduleCatalog 必须走 CalendarApplication.query_schedule，而不是内部服务方法。"""
    from types import SimpleNamespace

    from astrbot_plugin_nikke.features.announcement.feeds import FeedUnavailable, ScheduleCatalog
    from astrbot_plugin_nikke.features.calendar.application import CalendarApplication
    from astrbot_plugin_nikke.features.calendar.canonical_models import CanonicalEvent, QueryContext

    now = datetime(2026, 9, 21, tzinfo=timezone.utc)
    # 正式 CalendarApplication + 未装配日历服务：必须降级为不可用，而不是 AttributeError。
    unavailable = ScheduleCatalog(CalendarApplication(None))
    with pytest.raises(FeedUnavailable, match="尚未就绪"):
        unavailable.items(now=now)

    event = CanonicalEvent(
        id="blabla:abc",
        title="合成活动",
        event_type="recruit",
        start_at=now,
        end_at=now.replace(day=22),
        detail_url="https://example.invalid/event",
        metadata={"identity_key": "GLOBAL:recruit:cycle-1"},
    )

    class CalendarService:
        last_updated_at = None
        last_sync_error = ""
        data_quality = "FRESH"

        @staticmethod
        def normalize_horizon(value):
            return 14

        def freeze_query_context(self, current):
            return QueryContext(
                now=current, snapshot_version="1", events=(event,),
                source_health={}, freshness="FRESH", coverage="COMPLETE",
            )

        @staticmethod
        def has_snapshot():
            return True

        @staticmethod
        def activity_count():
            return 1

        @staticmethod
        def format_schedule_text(*_args, **_kwargs):
            return ""

        @staticmethod
        def resolve_visual_path(_event_id):
            return None

        async def refresh_schedule_data(self):
            return True, "ok"

    application = CalendarApplication(CalendarService())
    items = ScheduleCatalog(application).items(now=now)
    assert len(items) == 1
    assert items[0].entity_id == event.id
    assert items[0].title == event.title
    assert items[0].kind == "schedule"

    # 没有 id 时回退到稳定 identity_key，仍然只发标题和链接。
    identity_only = SimpleNamespace(
        identity_key="GLOBAL:union_raid:season-1", title="身份事件",
        start_at=now, end_at=now, end_precision="EXACT", start_precision="EXACT",
        detail_url="https://example.invalid/raid", version=3,
    )
    class IdentityCalendar(CalendarService):
        def freeze_query_context(self, current):
            return QueryContext(
                now=current, snapshot_version="1", events=(identity_only,),
                source_health={}, freshness="FRESH", coverage="COMPLETE",
            )
    fallback = ScheduleCatalog(CalendarApplication(IdentityCalendar())).items(now=now)
    assert fallback[0].entity_id == "GLOBAL:union_raid:season-1"
    assert fallback[0].url == "https://example.invalid/raid"


@pytest.mark.asyncio
async def test_resubscribe_during_source_outage_preserves_baseline_and_prevents_flood() -> None:
    """回归：重复订阅时上游失败不得用空结果覆盖既有 baseline；并发调用不重复发送。"""
    import asyncio
    from astrbot_plugin_nikke.features.announcement.feeds import (
        FeedCatalog,
        FeedSubscriptions,
        FeedUnavailable,
    )

    store, _ = (
        build()[0],
        None,
    )

    class ToggleNewsCatalog:
        def __init__(self) -> None:
            self.fail = False
            self.rows = [item("news", "n-old", version=1)]

        def items(self, *, now):
            if self.fail:
                raise FeedUnavailable("临时超时")
            return tuple(self.rows)

    class StaticScheduleCatalog:
        def items(self, *, now):
            return (item("schedule", "s-1", version=1),)

    news_cat = ToggleNewsCatalog()
    catalog = FeedCatalog({"news": news_cat, "schedule": StaticScheduleCatalog()})
    subs = FeedSubscriptions(store, catalog, clock=lambda: datetime(2026, 9, 21, tzinfo=timezone.utc))
    key = target("user-a")

    # 1. 首次订阅建立基线，且不落盘死字段 reminder_hours。
    subs.command(key, "订阅", "新闻")
    saved = store.get_setting(subs.SETTING, {})["targets"][key]
    assert "reminder_hours" not in saved
    assert saved["baseline"] == {"news:n-old": 1}

    # 2. 新闻源短暂故障期间追订“日程”，不得清空已有 news:n-old 基线。
    news_cat.fail = True
    subs.command(key, "订阅", "日程")
    saved_during_outage = store.get_setting(subs.SETTING, {})["targets"][key]
    assert saved_during_outage["baseline"]["news:n-old"] == 1
    assert saved_during_outage["baseline"]["schedule:s-1"] == 1

    # 3. 来源恢复且仅新增 n-new，旧条目 n-old 不应被重新推送；并发 dispatch_due 只发一次。
    news_cat.fail = False
    news_cat.rows = [item("news", "n-old", version=1), item("news", "n-new", version=1)]

    async def slow_sender(conversation, actor, private, text):
        await asyncio.sleep(0.02)
        sent.append((conversation, actor, private, text))
        return True

    sent: list[tuple[str, str, bool, str]] = []
    results = await asyncio.gather(
        subs.dispatch_due(slow_sender, now=datetime(2026, 9, 21, 1, tzinfo=timezone.utc)),
        subs.dispatch_due(slow_sender, now=datetime(2026, 9, 21, 1, tzinfo=timezone.utc)),
    )
    assert sum(r["succeeded"] for r in results) == 1
    assert len(sent) == 1
    assert "https://example.invalid/news/n-new" in sent[0][3]
    assert "n-old" not in sent[0][3]
    assert "n-old" not in sent[0][3]

    # 4. 与 AnnouncementDelivery 使用各自独立的 SETTING，互不干扰或重复串台。
    from astrbot_plugin_nikke.features.announcement.delivery import AnnouncementDelivery

    broadcast = AnnouncementDelivery(store)
    assert broadcast.SETTING != subs.SETTING
    assert store.get_setting(broadcast.SETTING, {}) == {}

# SPDX-License-Identifier: GPL-3.0-or-later
"""官方新闻 / 视频 / 日程订阅（05）。

复用现有公告仓储、日程快照和持久化投递状态机，实现：
- 新闻、视频、日程三类订阅互相独立，可分别开通与取消；
- 只向订阅者本人所在的会话发送（群内只 @ 本人），不广播给其他用户；
- 以投递状态机去重，跨轮询不重复发送；
- 上游暂不可用时跳过本轮并保留状态，命令入口显示明确的不可用说明。
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Protocol

from .delivery import AnnouncementDelivery, PlannedPush, aware

logger = logging.getLogger(__name__)

KINDS: dict[str, str] = {"news": "新闻", "video": "视频", "schedule": "日程"}
KIND_ALIASES = {
    "新闻": "news", "news": "news", "公告": "news",
    "视频": "video", "video": "video", "videos": "video",
    "日程": "schedule", "schedule": "schedule", "calendar": "schedule",
    "全部": "all", "all": "all",
}
_HELP = (
    "三类订阅互相独立：新闻、视频、日程。\n"
    "开通：/妮姬 新闻 订阅 新闻,日程\n"
    "查看：/妮姬 新闻 状态\n"
    "取消：/妮姬 新闻 取消订阅 [新闻|视频|日程]\n"
    "群内只 @ 订阅者本人；不同会话与用户互不影响。"
)


class FeedUnavailable(RuntimeError):
    """某一类上游来源当前不可用。"""


@dataclass(frozen=True, slots=True)
class FeedItem:
    """一条可投递的新闻/视频/日程记录。"""

    kind: str
    entity_id: str
    version: int
    title: str
    url: str
    published_at: str

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"未知订阅类型：{self.kind}")
        if not str(self.entity_id).strip() or not str(self.title).strip():
            raise ValueError("订阅记录缺少身份或标题")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("订阅记录版本必须是正整数")
        aware(self.published_at)


class FeedCatalogPort(Protocol):
    """从现有仓储/快照读取三类记录。"""

    def items(self, *, now: datetime) -> tuple[FeedItem, ...]: ...


class AnnouncementCatalog:
    """把公告仓储适配为“新闻”来源；不执行网络请求。"""

    def __init__(self, announcements: Any) -> None:
        self._announcements = announcements

    def items(self, *, now: datetime) -> tuple[FeedItem, ...]:
        if self._announcements is None:
            raise FeedUnavailable("公告仓储尚未就绪")
        records = self._announcements.list_announcements(limit=100)
        result: list[FeedItem] = []
        for record in records:
            content_id = getattr(record, "content_id", "")
            title = getattr(record, "title", "")
            url = getattr(record, "source_url", "") or ""
            published = getattr(record, "published_at", "")
            version = getattr(record, "content_version", 1)
            if not content_id or not title or not published:
                continue
            try:
                result.append(
                    FeedItem(
                        kind="news",
                        entity_id=str(content_id),
                        version=int(version),
                        title=str(title),
                        url=str(url),
                        published_at=str(published),
                    )
                )
            except (ValueError, TypeError):
                continue
        return tuple(result)


class ScheduleCatalog:
    """把当前日程快照适配为“日程”来源；只读取已冻结快照。"""

    def __init__(self, calendar: Any, clock: Callable[[], datetime] | None = None) -> None:
        self._calendar = calendar
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def items(self, *, now: datetime) -> tuple[FeedItem, ...]:
        # CalendarApplication 没有 has_snapshot/freeze_query_context；统一走热查询快照。
        if self._calendar is None:
            raise FeedUnavailable("日程服务尚未就绪")
        snapshot = self._calendar.query_schedule(now=now)
        if not snapshot.service_available:
            raise FeedUnavailable("日程服务尚未就绪")
        if not snapshot.has_snapshot:
            raise FeedUnavailable("日程快照尚未就绪")
        context = snapshot.context
        result: list[FeedItem] = []
        for event in context.events:
            event_id = str(
                getattr(event, "id", "")
                or getattr(event, "identity_key", "")
                or getattr(event, "event_id", "")
            )
            title = str(getattr(event, "title", "") or "")
            start = getattr(event, "start_at", None)
            if not event_id or not title or not isinstance(start, datetime):
                continue
            if start < now - timedelta(days=1):
                continue
            result.append(
                FeedItem(
                    kind="schedule",
                    entity_id=event_id,
                    version=int(getattr(event, "version", 1) or 1),
                    title=title,
                    url=str(getattr(event, "detail_url", "") or ""),
                    published_at=now.astimezone(timezone.utc).isoformat(),
                )
            )
        return tuple(result)


class VideoCatalog:
    """官方频道 Atom 视频来源；只读热缓存，由后台调度刷新。"""

    def __init__(self, source: Any) -> None:
        self._source = source

    def items(self, *, now: datetime) -> tuple[FeedItem, ...]:
        cached = tuple(self._source.cached_items)
        if cached:
            return cached
        reason = getattr(self._source, "last_error", "") or "尚未完成首次同步"
        raise FeedUnavailable(f"官方视频来源暂不可用（{reason}）")

    async def refresh(self, *, now: datetime) -> None:
        await self._source.refresh(now=now)


class FeedCatalog:
    """组合三类来源；单类失败不影响其他已支持类型。"""

    def __init__(self, catalogs: Mapping[str, FeedCatalogPort]) -> None:
        self._catalogs = dict(catalogs)
        self.last_unavailable: dict[str, str] = {}

    async def refresh(self, *, now: datetime) -> None:
        """在后台调度中刷新可拉取的异步来源；单类失败不影响其他类型。"""
        for kind in KINDS:
            catalog = self._catalogs.get(kind)
            refresh = getattr(catalog, "refresh", None)
            if not callable(refresh):
                continue
            try:
                await refresh(now=now)
            except Exception as exc:
                self.last_unavailable[kind] = f"来源读取失败（{type(exc).__name__}）"
                logger.warning("[NIKKE] %s 订阅来源刷新失败：%s", KINDS[kind], type(exc).__name__)

    def items(self, *, now: datetime) -> tuple[FeedItem, ...]:
        self.last_unavailable = {}
        collected: list[FeedItem] = []
        for kind in KINDS:
            catalog = self._catalogs.get(kind)
            if catalog is None:
                self.last_unavailable[kind] = "未装配来源"
                continue
            try:
                collected.extend(catalog.items(now=now))
            except FeedUnavailable as exc:
                self.last_unavailable[kind] = str(exc)
            except Exception as exc:  # 上游异常不能拖垮订阅/调度
                logger.warning("[NIKKE] %s 订阅来源读取失败：%s", KINDS[kind], type(exc).__name__)
                self.last_unavailable[kind] = "来源读取失败"
        # 同一实体只保留最高版本，避免上游重复行导致重复推送。
        best: dict[tuple[str, str], FeedItem] = {}
        for item in collected:
            key = (item.kind, item.entity_id)
            current = best.get(key)
            if current is None or item.version > current.version:
                best[key] = item
        return tuple(best.values())


def _parse_kinds(value: str) -> list[str]:
    names: list[str] = []
    for part in str(value or "").replace("，", ",").replace("、", ",").split(","):
        key = part.strip().casefold()
        if not key:
            continue
        kind = KIND_ALIASES.get(key)
        if kind is None:
            raise ValueError(f"未知订阅类型：{part}（可用：新闻、视频、日程）")
        if kind == "all":
            for name in KINDS:
                if name not in names:
                    names.append(name)
            continue
        if kind not in names:
            names.append(kind)
    return names


class FeedSubscriptions(AnnouncementDelivery):
    """三类订阅的持久化状态与去重投递；只向订阅者本人发送。"""

    SETTING = "feed_subscriptions_v1"

    def __init__(self, store, catalog: FeedCatalog, *, clock: Callable[[], datetime] | None = None) -> None:
        super().__init__(store)
        self.catalog = catalog
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def target_key(conversation_id: str, actor_id: str, private: bool) -> str:
        if not conversation_id or not actor_id:
            raise ValueError("当前会话无法保存订阅，请在支持主动消息的会话内重试。")
        return json.dumps([conversation_id, actor_id, bool(private)], ensure_ascii=False)

    def command(self, target: str, action: str, value: str = "") -> str:
        action_key = str(action or "").strip().casefold()
        if action_key in {"取消订阅", "unsubscribe", "取消"}:
            kinds = _parse_kinds(value) if value.strip() else []
            return self._unsubscribe(target, kinds)
        if action_key in {"状态", "status"}:
            return self._status(target)
        if not value.strip():
            return _HELP
        kinds = _parse_kinds(value)
        if not kinds:
            raise ValueError("请至少选择一个订阅类型")
        return self._subscribe(target, kinds)

    def _subscribe(self, target: str, kinds: Iterable[str]) -> str:
        selected = tuple(dict.fromkeys(kinds))
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError("订阅时钟必须包含明确时区")
        items_ok = True
        try:
            items = self.catalog.items(now=now)
        except Exception:
            items = ()
            items_ok = False
        unavailable_kinds = (
            set(getattr(self.catalog, "last_unavailable", {}).keys())
            if items_ok
            else set(KINDS)
        )
        state = self._state()
        existing = state["targets"].get(target, {})
        if existing.get("enabled"):
            current = [kind for kind in existing.get("kinds", []) if kind in KINDS]
            merged = list(dict.fromkeys([*current, *selected]))
        else:
            merged = list(selected)
        prev_baseline = (
            existing.get("baseline")
            if isinstance(existing.get("baseline"), Mapping)
            else {}
        )
        next_baseline: dict[str, int] = {}
        # 重订阅或单源短暂故障时保留既有 baseline，防止来源恢复后误把历史条目全量重推。
        for key, ver in prev_baseline.items():
            kind_prefix = str(key).split(":", 1)[0]
            if kind_prefix in merged and isinstance(ver, int) and not isinstance(ver, bool):
                next_baseline[str(key)] = ver
        for item in items:
            if item.kind in merged and item.kind not in unavailable_kinds:
                item_key = f"{item.kind}:{item.entity_id}"
                if item.version > next_baseline.get(item_key, 0):
                    next_baseline[item_key] = item.version
        state["targets"][target] = {
            "enabled": True,
            "kinds": merged,
            "subscribed_at": existing.get("subscribed_at") or now.astimezone(timezone.utc).isoformat(),
            "baseline": next_baseline,
        }
        self.store.set_setting(self.SETTING, state)
        return (
            "已订阅（当前会话仅通知你本人；负责新公告/视频/新上线日程提醒）："
            + "、".join(KINDS[kind] for kind in merged)
            + "\n提示：若需要活动结束前 24 小时截止提醒，请使用 /妮姬 日程 订阅。\n"
            + _HELP
        )

    def _unsubscribe(self, target: str, kinds: Iterable[str]) -> str:
        state = self._state()
        preference = state["targets"].get(target)
        if not preference or not preference.get("enabled"):
            return "你在当前会话尚未开通订阅。\n" + _HELP
        selected = list(kinds)
        if not selected:
            preference["enabled"] = False
            preference["kinds"] = []
            self.store.set_setting(self.SETTING, state)
            return "已取消你在当前会话的全部订阅。"
        remaining = [kind for kind in preference.get("kinds", []) if kind not in selected]
        preference["kinds"] = remaining
        if not remaining:
            preference["enabled"] = False
        self.store.set_setting(self.SETTING, state)
        removed = "、".join(KINDS[kind] for kind in selected)
        return f"已取消：{removed}。剩余：" + ("、".join(KINDS[kind] for kind in remaining) or "无")

    def _status(self, target: str) -> str:
        preference = self._state()["targets"].get(target, {})
        if not preference.get("enabled"):
            return "你在当前会话尚未开通订阅。\n" + _HELP
        kinds = "、".join(KINDS[kind] for kind in preference.get("kinds", []))
        delivered = sum(1 for record in self._state()["delivered"].values() if record.get("target") == target)
        lines = [
            f"已订阅（个人订阅）：{kinds}",
            f"已投递记录：{delivered} 条",
            "说明：新闻/视频/新日程推送仅针对本人；活动结束前 24h 提醒见 /妮姬 日程 订阅；全群公告广播受管理员 enable_announcement_push 控制。",
            "取消：/妮姬 新闻 取消订阅 [类型]",
        ]
        for kind, reason in self.catalog.last_unavailable.items():
            if kind in preference.get("kinds", []):
                lines.append(f"{KINDS[kind]}来源：暂不可用（{reason}）")
        return "\n".join(lines)

    def plan(self, records=(), deadlines=(), *, now=None) -> list[PlannedPush]:
        current = aware(now or self._clock())
        state = self._state()
        enabled = {
            target: preference
            for target, preference in state["targets"].items()
            if preference.get("enabled") and preference.get("kinds")
        }
        if not enabled:
            return []
        try:
            items = self.catalog.items(now=current)
        except Exception:
            return []
        pushes: list[PlannedPush] = []
        for target, preference in enabled.items():
            kinds = set(preference.get("kinds", []))
            baseline = preference.get("baseline", {})
            subscribed_at = aware(preference.get("subscribed_at") or current.isoformat())
            for item in items:
                if item.kind not in kinds:
                    continue
                key = f"{item.kind}:{item.entity_id}"
                known = baseline.get(key)
                if known is not None and item.version <= known:
                    continue
                if (
                    known is None
                    and item.kind == "video"
                    and aware(item.published_at) < subscribed_at
                ):
                    # 视频没有版本基线时，首次缓存中的旧视频不得补推。
                    continue
                push = PlannedPush(
                    target=target,
                    entity_id=key,
                    version=item.version,
                    push_type="feed",
                    text=f"【{KINDS[item.kind]}】{item.title}\n{item.url}",
                    reminder_hour=None,
                )
                if push.key not in state["delivered"] and push.key not in state["dispatch_intents"]:
                    pushes.append(push)
        return pushes

    async def dispatch_due(self, sender, *, now=None) -> dict[str, int]:
        """仅当存在订阅时才读取来源并发送；发送器逐条标记结果。"""
        if not any(
            item.get("enabled") and item.get("kinds")
            for item in self._state()["targets"].values()
        ):
            return {"succeeded": 0, "failed": 0, "unknown": 0}

        current = aware(now or self._clock())
        await self.catalog.refresh(now=current)

        async def send(target: str, text: str) -> bool:
            preference = self._state()["targets"].get(target, {})
            if not preference.get("enabled"):
                return False
            try:
                conversation, actor, private = json.loads(target)
            except (TypeError, ValueError):
                return False
            return await sender(conversation, actor, bool(private), text)

        return await self.dispatch((), (), send, now=current)


__all__ = [
    "AnnouncementCatalog",
    "FeedCatalog",
    "FeedItem",
    "FeedSubscriptions",
    "FeedUnavailable",
    "KINDS",
    "ScheduleCatalog",
    "VideoCatalog",
]

# SPDX-License-Identifier: GPL-3.0-or-later
"""官方新闻 / 视频 / 日程订阅（05）。

复用现有公告仓储、日程快照和持久化投递状态机，实现：
- 新闻、视频、日程三类订阅互相独立，可分别开通与取消；
- 为每类来源独立维护基线初始化状态：``uninitialized`` / ``initialized`` / ``initialized_unavailable``；
- 首次订阅或追加新类型时若对应来源不可用，保持 ``uninitialized``，待来源首次恢复时将当期快照
  整体写入基线并标记 ``initialized``，绝不向用户轰炸历史消息；
- 已初始化来源在短暂故障期间保持 ``initialized_unavailable`` 且绝不清空已有基线；恢复后仅推送
  版本高于基线或窗口内新增的内容，并受 ``_dispatch_lock`` + ``DISPATCH_INTENT`` 幂等保护；
- 只向订阅者本人所在的会话发送（群内只 @ 本人），不广播给其他用户。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Protocol

from .delivery import AnnouncementDelivery, PlannedPush, aware

logger = logging.getLogger(__name__)

KINDS: dict[str, str] = {"news": "新闻", "video": "视频", "schedule": "日程"}
_LABEL_TO_KIND: dict[str, str] = {f"【{label}】": kind for kind, label in KINDS.items()}
KIND_ALIASES = {
    "新闻": "news", "news": "news", "公告": "news",
    "视频": "video", "video": "video", "videos": "video",
    "日程": "schedule", "schedule": "schedule", "calendar": "schedule",
    "全部": "all", "all": "all",
}
KIND_STATE_UNINITIALIZED = "uninitialized"
KIND_STATE_INITIALIZED = "initialized"
KIND_STATE_UNAVAILABLE = "initialized_unavailable"
VALID_KIND_STATES = frozenset(
    {KIND_STATE_UNINITIALIZED, KIND_STATE_INITIALIZED, KIND_STATE_UNAVAILABLE}
)
_HISTORY_RECOVERY_DAYS = 14

_HELP = (
    "可以分别订阅官方新闻、视频和新作活动日程，群里只 @ 你自己。\n"
    "• 开通：/妮姬 新闻 订阅 新闻,日程\n"
    "• 查看：/妮姬 新闻 状态\n"
    "• 取消：/妮姬 新闻 取消订阅 [新闻|视频|日程]"
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


def _normalize_kind_states(preference: Mapping[str, Any], kinds: Iterable[str]) -> dict[str, str]:
    """兼容旧版持久化记录（缺省 kind_states 的已订阅类型按 initialized 处理）。"""
    raw = preference.get("kind_states")
    states: dict[str, str] = {}
    if isinstance(raw, Mapping):
        for kind in kinds:
            val = raw.get(kind)
            states[kind] = val if isinstance(val, str) and val in VALID_KIND_STATES else KIND_STATE_INITIALIZED
    else:
        for kind in kinds:
            states[kind] = KIND_STATE_INITIALIZED
    return states


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
        now_iso = now.astimezone(timezone.utc).isoformat()
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
        items_by_kind: dict[str, list[FeedItem]] = {}
        for item in items:
            items_by_kind.setdefault(item.kind, []).append(item)

        state = self._state()
        existing = state["targets"].get(target, {})
        existing_enabled = bool(existing.get("enabled"))
        existing_kinds = (
            [kind for kind in existing.get("kinds", []) if kind in KINDS]
            if existing_enabled
            else []
        )
        merged = list(dict.fromkeys([*existing_kinds, *selected]))
        prev_states = _normalize_kind_states(existing, existing_kinds) if existing_enabled else {}
        prev_sub_times = (
            dict(existing.get("kind_subscribed_at"))
            if isinstance(existing.get("kind_subscribed_at"), Mapping)
            else {}
        )
        prev_baseline = (
            existing.get("baseline")
            if isinstance(existing.get("baseline"), Mapping)
            else {}
        )

        # 保留所有仍在合并列表中的既有基线；历史退订后重订的同类型也沿用既有基线防重推。
        next_baseline: dict[str, int] = {}
        for key, ver in prev_baseline.items():
            kind_prefix = str(key).split(":", 1)[0]
            if kind_prefix in merged and isinstance(ver, int) and not isinstance(ver, bool):
                next_baseline[str(key)] = ver

        next_states: dict[str, str] = {}
        next_sub_times: dict[str, str] = {}
        pending_init_labels: list[str] = []
        for kind in merged:
            if kind in existing_kinds:
                next_sub_times[kind] = str(
                    prev_sub_times.get(kind) or existing.get("subscribed_at") or now_iso
                )
            else:
                next_sub_times[kind] = now_iso

            if kind in existing_kinds:
                prior_state = prev_states.get(kind, KIND_STATE_INITIALIZED)
            else:
                # 退订后重订若该类型仍保留旧基线条目，也按首次需要同步当前快照而不重置已投递水位。
                prior_state = (
                    KIND_STATE_INITIALIZED
                    if any(k.startswith(f"{kind}:") for k in next_baseline)
                    else KIND_STATE_UNINITIALIZED
                )

            if kind in unavailable_kinds:
                if prior_state == KIND_STATE_UNINITIALIZED:
                    next_states[kind] = KIND_STATE_UNINITIALIZED
                    pending_init_labels.append(KINDS[kind])
                else:
                    next_states[kind] = KIND_STATE_UNAVAILABLE
            else:
                for item in items_by_kind.get(kind, ()):
                    item_key = f"{item.kind}:{item.entity_id}"
                    if item.version > next_baseline.get(item_key, 0):
                        next_baseline[item_key] = item.version
                next_states[kind] = KIND_STATE_INITIALIZED

        state["targets"][target] = {
            "enabled": True,
            "kinds": merged,
            "subscribed_at": str(existing.get("subscribed_at") or now_iso),
            "kind_subscribed_at": next_sub_times,
            "kind_states": next_states,
            "baseline": next_baseline,
        }
        self.store.set_setting(self.SETTING, state)
        msg = (
            "已为你开启订阅："
            + "、".join(KINDS[kind] for kind in merged)
            + "（有更新时会在当前会话通知你）"
        )
        if pending_init_labels:
            msg += (
                f"\n提示：{'、'.join(pending_init_labels)} 暂时连不上官方接口，"
                "恢复后会自动从当时起同步最新内容，不会把旧消息全发一遍。"
            )
        msg += "\n💡 如需活动结束前 24 小时到期提醒，可用 /妮姬 日程 订阅。"
        return msg

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
        if isinstance(preference.get("kind_states"), dict):
            for kind in selected:
                preference["kind_states"].pop(kind, None)
        if not remaining:
            preference["enabled"] = False
        self.store.set_setting(self.SETTING, state)
        removed = "、".join(KINDS[kind] for kind in selected)
        return f"已取消：{removed}。剩余：" + ("、".join(KINDS[kind] for kind in remaining) or "无")

    def _status(self, target: str) -> str:
        state = self._state()
        preference = state["targets"].get(target, {})
        if not preference.get("enabled"):
            return "你在当前会话尚未开通订阅。\n" + _HELP
        active_kinds = [k for k in preference.get("kinds", []) if k in KINDS]
        kinds_text = "、".join(KINDS[kind] for kind in active_kinds)
        kind_states = _normalize_kind_states(preference, active_kinds)
        delivered = sum(1 for record in state["delivered"].values() if record.get("target") == target)
        lines = [
            f"已订阅更新通知：{'、'.join(KINDS[kind] for kind in active_kinds)}（已推送 {delivered} 条）",
            "💡 活动到期前 24 小时提醒请用 /妮姬 日程 订阅；取消请发 /妮姬 新闻 取消订阅 [类型]。",
        ]
        for kind in active_kinds:
            k_state = kind_states.get(kind)
            reason = self.catalog.last_unavailable.get(kind, "")
            if k_state == KIND_STATE_UNINITIALIZED:
                lines.append(f"{KINDS[kind]}暂未获取到最新列表，恢复后只通知之后的新内容。")
            elif reason or k_state == KIND_STATE_UNAVAILABLE:
                lines.append(f"{KINDS[kind]}目前暂不可用，稍后恢复后会继续推送更新。")
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
        items_ok = True
        try:
            items = self.catalog.items(now=current)
        except Exception:
            items = ()
            items_ok = False
        unavailable_kinds = (
            set(getattr(self.catalog, "last_unavailable", {}).keys())
            if items_ok
            else set(KINDS)
        )
        items_by_kind: dict[str, list[FeedItem]] = {}
        for item in items:
            items_by_kind.setdefault(item.kind, []).append(item)

        pushes: list[PlannedPush] = []
        state_dirty = False
        for target, preference in enabled.items():
            active_kinds = [k for k in preference.get("kinds", []) if k in KINDS]
            kind_states = _normalize_kind_states(preference, active_kinds)
            baseline = preference.setdefault("baseline", {})
            if not isinstance(baseline, dict):
                baseline = {}
                preference["baseline"] = baseline
            kind_sub_map = (
                preference.get("kind_subscribed_at")
                if isinstance(preference.get("kind_subscribed_at"), Mapping)
                else {}
            )
            default_sub = aware(preference.get("subscribed_at") or current.isoformat())

            for kind in active_kinds:
                current_k_state = kind_states.get(kind, KIND_STATE_INITIALIZED)
                if kind in unavailable_kinds:
                    if current_k_state == KIND_STATE_INITIALIZED:
                        kind_states[kind] = KIND_STATE_UNAVAILABLE
                        state_dirty = True
                    continue

                # 情况 1：首次订阅或追订时来源故障，今日才首次恢复 -> 全量纳入基线，零历史轰炸！
                if current_k_state == KIND_STATE_UNINITIALIZED:
                    for item in items_by_kind.get(kind, ()):
                        key = f"{item.kind}:{item.entity_id}"
                        if item.version > int(baseline.get(key, 0) or 0):
                            baseline[key] = item.version
                    kind_states[kind] = KIND_STATE_INITIALIZED
                    state_dirty = True
                    continue

                # 情况 2：已初始化类型从短暂故障恢复 -> 恢复为 initialized，保留原 baseline。
                if current_k_state == KIND_STATE_UNAVAILABLE:
                    kind_states[kind] = KIND_STATE_INITIALIZED
                    state_dirty = True

                archive_floor = current - timedelta(days=_HISTORY_RECOVERY_DAYS)
                kind_sub_at = aware(kind_sub_map.get(kind) or default_sub)
                effective_floor = max(archive_floor, kind_sub_at)
                for item in items_by_kind.get(kind, ()):
                    key = f"{item.kind}:{item.entity_id}"
                    known = baseline.get(key)
                    if known is not None and item.version <= known:
                        continue
                    if known is None and aware(item.published_at) < effective_floor:
                        # 订阅前发布的近期内容或超过 14 天恢复窗的老旧归档进入快照时不补推；等价保护新闻/视频/日程。
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

            if preference.get("kind_states") != kind_states:
                preference["kind_states"] = kind_states
                state_dirty = True

        if state_dirty:
            self.store.set_setting(self.SETTING, state)
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
            prefix = text.split("\n", 1)[0]
            for label, kind in _LABEL_TO_KIND.items():
                if prefix.startswith(label) and kind not in (preference.get("kinds") or ()):
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
    "KIND_STATE_INITIALIZED",
    "KIND_STATE_UNAVAILABLE",
    "KIND_STATE_UNINITIALIZED",
    "KINDS",
    "ScheduleCatalog",
    "VideoCatalog",
]

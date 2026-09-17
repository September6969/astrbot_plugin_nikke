# SPDX-License-Identifier: GPL-3.0-or-later
"""统一日程服务 (ScheduleService)。

核心架构：
1. 抓取与查询解耦：用户命令原则上只读本地标准化缓存/快照，不现场等待远程接口；
2. 多数据源字段级合并与去重（Manual > Official > GameKee）；
3. 状态自算（UPCOMING / ACTIVE / ENDED）与分级时间精度（EXACT / DATE_ONLY）；
4. L1 内存缓存 (TTL 300s) + L2 持久化快照 (原子写，保留 >= 72 小时)；
5. 数据质量跟踪（FRESH / STALE / PARTIAL / UNAVAILABLE）；
6. 变更检测 (Change Detection)，无变化时不重复写库与刷新；
7. 100% 兼容既有 CalendarService 的查询与分组接口。
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from .models import CalendarActivity, _aware_utc
from astrbot_plugin_nikke.features.calendar.canonical_models import (
    CanonicalEvent,
    quality_badge,
    CST,
)
from ...integrations.blablalink.fetch_client import FetchClient
from ...core.privacy import safe_exception_message
from astrbot_plugin_nikke.features.calendar.schedule_adapters import (
    BaseScheduleAdapter,
    GameKeeScheduleAdapter,
    OfficialAnnouncementScheduleAdapter,
    ManualOverrideScheduleAdapter,
)

logger = logging.getLogger("nikke.schedule.service")

CAT_LABELS = {
    "coop": "协同",
    "union_raid": "联盟突袭",
    "solo_raid": "单人突袭",
    "recruit": "招募",
    "maintenance": "维护",
    "update": "更新",
    "event": "活动",
}


class _ActivitiesDict(dict):
    """支持测试用例与旧代码直接对 _activities 进行字典操作的双向同步字典。"""

    def __init__(self, service: ScheduleService, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._service = service

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key, value)
        if hasattr(self, "_service") and self._service is not None:
            if isinstance(value, CanonicalEvent):
                self._service._events[key] = value
            elif isinstance(value, CalendarActivity):
                self._service._events[key] = CanonicalEvent.from_calendar_activity(value)

    def pop(self, key: str, default: Any = None) -> Any:
        res = super().pop(key, default)
        if hasattr(self, "_service") and self._service is not None:
            self._service._events.pop(key, None)
        return res

    def clear(self) -> None:
        super().clear()
        if hasattr(self, "_service") and self._service is not None:
            self._service._events.clear()


def _title_similarity(a: str, b: str) -> float:
    """计算两个活动标题的相似度（兼顾子串、编辑距离与字符交集）。"""
    ca = "".join(c for c in a.casefold() if c.isalnum() or '\u4e00' <= c <= '\u9fff')
    cb = "".join(c for c in b.casefold() if c.isalnum() or '\u4e00' <= c <= '\u9fff')
    if not ca or not cb:
        return 0.0
    if ca == cb or ca in cb or cb in ca:
        return 1.0

    seq_ratio = difflib.SequenceMatcher(None, ca, cb).ratio()

    # 字符重合度
    set_a, set_b = set(ca), set(cb)
    char_overlap = len(set_a & set_b) / max(1, min(len(set_a), len(set_b)))

    # 2-gram 词素交集
    ba = {ca[i:i+2] for i in range(len(ca)-1)}
    bb = {cb[i:i+2] for i in range(len(cb)-1)}
    jaccard = (len(ba & bb) / len(ba | bb)) if (ba and bb) else 0.0

    return max(seq_ratio, char_overlap, jaccard)


def _is_same_event(a: CanonicalEvent, b: CanonicalEvent) -> bool:
    """判断两个事件是否指同一活动：
    1. 同一事件类别；
    2. 起止时间在 30 分钟容差内（或均为 DATE_ONLY 同一天）；
    3. 标题关键词或语义相关。
    """
    if a.event_type != b.event_type and "event" not in (a.event_type, b.event_type):
        return False

    time_matched = False
    if a.start_at and b.start_at and a.end_at and b.end_at:
        start_diff = abs((a.start_at - b.start_at).total_seconds())
        end_diff = abs((a.end_at - b.end_at).total_seconds())
        if start_diff <= 1800 and end_diff <= 1800:
            time_matched = True
        else:
            return False

    similarity = _title_similarity(a.title, b.title)
    # 起止时间高度吻合且有公共特征（如包含联动/突袭/协同）或相似度 >= 0.35 即可视作同一活动
    if time_matched and similarity >= 0.35:
        return True

    return similarity >= 0.65


def _merge_two_events(base: CanonicalEvent, incoming: CanonicalEvent) -> CanonicalEvent:
    """字段级多源合并规则：
    Manual Override > Official > Raid/Co-op > GameKee > Fallback
    具体字段优先级（遵循规格）：
    - title: Manual -> GameKee (更地道活动名) -> Official -> 其他
    - banner_url: Manual -> GameKee -> Official
    - detail_url: Manual -> GameKee -> Official
    - start_at / end_at / precision: Manual -> Official (官方权威时间) -> GameKee
    - event_type: Manual -> Official -> GameKee
    """
    events = [base, incoming]
    by_source: dict[str, CanonicalEvent] = {}
    for ev in events:
        by_source[ev.primary_source] = ev

    manual = by_source.get("manual")
    official = by_source.get("official")
    gamekee = by_source.get("gamekee")

    # title
    if manual and manual.title:
        title = manual.title
    elif gamekee and gamekee.title:
        title = gamekee.title
    elif official and official.title:
        title = official.title
    else:
        title = incoming.title or base.title

    # banner_url
    if manual and manual.banner_url:
        banner = manual.banner_url
    elif gamekee and gamekee.banner_url:
        banner = gamekee.banner_url
    elif official and official.banner_url:
        banner = official.banner_url
    else:
        banner = incoming.banner_url or base.banner_url

    # detail_url
    if manual and manual.detail_url:
        detail = manual.detail_url
    elif gamekee and gamekee.detail_url:
        detail = gamekee.detail_url
    elif official and official.detail_url:
        detail = official.detail_url
    else:
        detail = incoming.detail_url or base.detail_url

    # start_at / end_at / time_precision (官方时间优先)
    if manual and manual.end_at:
        start_at = manual.start_at
        end_at = manual.end_at
        precision = manual.time_precision
    elif official and official.end_at:
        start_at = official.start_at
        end_at = official.end_at
        precision = official.time_precision
    elif gamekee and gamekee.end_at:
        start_at = gamekee.start_at
        end_at = gamekee.end_at
        precision = gamekee.time_precision
    else:
        start_at = incoming.start_at or base.start_at
        end_at = incoming.end_at or base.end_at
        precision = incoming.time_precision or base.time_precision

    # event_type
    if manual and manual.event_type:
        event_type = manual.event_type
    elif official and official.event_type and official.event_type != "event":
        event_type = official.event_type
    elif gamekee and gamekee.event_type:
        event_type = gamekee.event_type
    else:
        event_type = incoming.event_type or base.event_type

    combined_sources = list(dict.fromkeys(base.sources + incoming.sources))
    primary_source = "manual" if manual else ("official" if official else "gamekee")
    confidence = max(base.confidence or 0.0, incoming.confidence or 0.0)
    event_id = (gamekee.id if gamekee else None) or (official.id if official else None) or incoming.id

    merged = CanonicalEvent(
        id=event_id,
        title=title,
        event_type=event_type,
        start_at=start_at,
        end_at=end_at,
        banner_url=banner,
        detail_url=detail,
        time_precision=precision,
        sources=combined_sources,
        primary_source=primary_source,
        confidence=confidence,
        version=max(base.version, incoming.version),
    )
    return merged


class ScheduleService:
    def __init__(
        self,
        data_dir: Path | str,
        *,
        fetch_client: FetchClient | None = None,
        announcement_service: Any = None,
        ttl_seconds: float = 300.0,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_path = self.data_dir / "calendar_cache.json"

        self.fetch_client = fetch_client or FetchClient()
        self.announcement_service = announcement_service
        self.ttl_seconds = ttl_seconds

        # L1 内存缓存与活动字典
        self._events: dict[str, CanonicalEvent] = {}
        self._activities: _ActivitiesDict = _ActivitiesDict(self)
        self._has_snapshot: bool = False
        self._last_batch_hash: str = ""
        self._last_refresh_monotonic: float = 0.0

        self.last_updated_at: str | None = None
        self.last_sync_report: dict[str, int] | None = None
        self.last_sync_error: str = ""
        self.data_quality: str = "UNAVAILABLE"

        # 默认适配器链
        self.adapters: list[BaseScheduleAdapter] = [
            ManualOverrideScheduleAdapter(self.data_dir / "schedule_overrides.json"),
            GameKeeScheduleAdapter(self.fetch_client),
            OfficialAnnouncementScheduleAdapter(self.announcement_service),
        ]

        self._load_cache()

    def has_snapshot(self) -> bool:
        return self._has_snapshot

    def activity_count(self) -> int:
        return len(self._activities)

    def list_activities(self) -> list[CalendarActivity]:
        """兼容接口：返回 CalendarActivity 列表供 T2I 渲染。"""
        return list(self._activities.values())

    def list_canonical(self) -> list[CanonicalEvent]:
        return list(self._events.values())

    @staticmethod
    def normalize_horizon(value: Any) -> int:
        """只接受 7、14、30 天，默认 14 天。"""
        if value is None or value == "":
            return 14
        if type(value) is bool:
            raise ValueError("日程范围只支持 7、14、30 天")
        if type(value) is int:
            if value in (7, 14, 30):
                return value
            raise ValueError("日程范围只支持 7、14、30 天")
        if isinstance(value, str):
            s = value.strip()
            if not s:
                return 14
            if s.isascii() and s.isdecimal():
                v = int(s)
                if v in (7, 14, 30):
                    return v
        raise ValueError("日程范围只支持 7、14、30 天")

    def _sync_internal_stores(self, events: dict[str, CanonicalEvent]) -> None:
        dict.clear(self._activities)
        self._events = dict(events)
        for eid, ev in self._events.items():
            dict.__setitem__(self._activities, eid, ev.to_calendar_activity())

    def _load_cache(self) -> None:
        if not self.cache_path.is_file():
            self._has_snapshot = False
            self._sync_internal_stores({})
            self.data_quality = "UNAVAILABLE"
            return

        try:
            content = self.cache_path.read_text(encoding="utf-8")
            data = json.loads(content)
            raw_activities = data.get("activities", [])
            events: dict[str, CanonicalEvent] = {}
            for item in raw_activities:
                if "event_type" in item:
                    event = CanonicalEvent.from_dict(item)
                else:
                    act = CalendarActivity.from_dict(item)
                    event = CanonicalEvent.from_calendar_activity(act)
                events[event.id] = event

            self._sync_internal_stores(events)
            self.last_updated_at = data.get("updated_at")
            self._last_batch_hash = self._compute_batch_hash(list(events.values()))
            self._has_snapshot = True

            now_utc = datetime.now(timezone.utc)
            if self.last_updated_at:
                try:
                    up_dt = _aware_utc(self.last_updated_at)
                    if (now_utc - up_dt).total_seconds() < self.ttl_seconds:
                        self.data_quality = "FRESH"
                    else:
                        self.data_quality = "STALE"
                except Exception:
                    self.data_quality = "STALE"
            else:
                self.data_quality = "STALE"

            logger.info("[NIKKE] 载入活动日程快照: %d 条活动 (%s)", len(events), self.data_quality)
        except Exception as exc:
            logger.warning("[NIKKE] 日程缓存损坏或解析失败，保留空快照: %s", safe_exception_message(exc))
            self._sync_internal_stores({})
            self._has_snapshot = False
            self.data_quality = "UNAVAILABLE"

    def _compute_batch_hash(self, events: Sequence[CanonicalEvent]) -> str:
        parts = [e.fingerprint for e in sorted(events, key=lambda x: x.id)]
        return hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()

    def _save_cache(self) -> None:
        payload = {
            "schema": 2,
            "updated_at": self.last_updated_at or datetime.now(timezone.utc).isoformat(),
            "activities": [event.to_dict() for event in self._events.values()],
        }
        tmp_path = self.cache_path.with_suffix(".json.tmp")
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        tmp_path.replace(self.cache_path)

    async def refresh_schedule_data(self) -> tuple[bool, str]:
        """统一刷新流程 (Refresh Path)。"""
        all_fetched: list[CanonicalEvent] = []
        source_fail_errors: list[str] = []

        for adapter in self.adapters:
            try:
                events = await adapter.fetch()
                if events:
                    all_fetched.extend(events)
            except Exception as exc:
                err_msg = f"{adapter.source_name}: {safe_exception_message(exc)}"
                source_fail_errors.append(err_msg)
                logger.warning("[NIKKE] 数据源抓取失败: %s", err_msg)

        now_utc = datetime.now(timezone.utc)
        self._last_refresh_monotonic = time.monotonic()

        if not all_fetched:
            err = "; ".join(source_fail_errors) or "全部数据源抓取失败"
            self.last_sync_error = err
            if self._has_snapshot and self._events:
                self.data_quality = "STALE"
                logger.warning("[NIKKE] 日程刷新全部失败，降级使用本地旧快照: %s", err)
                return False, err
            self.data_quality = "UNAVAILABLE"
            return False, err

        # 多数据源合并与去重
        merged_events: list[CanonicalEvent] = []
        for incoming in all_fetched:
            matched_idx = -1
            for idx, existing in enumerate(merged_events):
                if existing.id == incoming.id or _is_same_event(existing, incoming):
                    matched_idx = idx
                    break

            if matched_idx >= 0:
                merged_events[matched_idx] = _merge_two_events(merged_events[matched_idx], incoming)
            else:
                merged_events.append(incoming)

        # 变更检测
        new_batch_hash = self._compute_batch_hash(merged_events)
        changed = (new_batch_hash != self._last_batch_hash)

        indexed: dict[str, CanonicalEvent] = {}
        for event in merged_events:
            old = self._events.get(event.id)
            if old is not None:
                v = old.version if event.fingerprint == old.fingerprint else old.version + 1
            else:
                v = 1
            object.__setattr__(event, "version", v)
            indexed[event.id] = event

        self._sync_internal_stores(indexed)
        self._has_snapshot = True
        self.last_sync_error = ""
        self.last_updated_at = now_utc.isoformat()

        if source_fail_errors:
            self.data_quality = "PARTIAL"
        else:
            self.data_quality = "FRESH"

        if changed or not self.cache_path.is_file():
            self._last_batch_hash = new_batch_hash
            try:
                self._save_cache()
                logger.info("[NIKKE] 日程快照更新并持久化: %d 条活动 (%s)", len(indexed), self.data_quality)
            except Exception as exc:
                logger.error("[NIKKE] 日程快照持久化失败: %s", safe_exception_message(exc))
        else:
            logger.debug("[NIKKE] 日程数据未发生变更，跳过写盘")

        return True, "ok"

    async def sync_from_source(self, fetcher: Any = None) -> tuple[bool, str]:
        """兼容既有 sync_from_source 接口。"""
        if fetcher is not None:
            try:
                res = fetcher.fetch() if hasattr(fetcher, "fetch") else fetcher()
                if asyncio.iscoroutine(res):
                    incoming = await res
                else:
                    incoming = res
                canonical_list: list[CanonicalEvent] = []
                for item in incoming:
                    if isinstance(item, CanonicalEvent):
                        canonical_list.append(item)
                    elif isinstance(item, CalendarActivity):
                        canonical_list.append(CanonicalEvent.from_calendar_activity(item))

                # 批次内去重并做版本检测
                deduped: dict[str, CanonicalEvent] = {}
                for ev in canonical_list:
                    if ev.id not in deduped:
                        deduped[ev.id] = ev

                merged: dict[str, CanonicalEvent] = {}
                for eid, ev in deduped.items():
                    old = self._events.get(eid)
                    if old is not None:
                        v = old.version if ev.fingerprint == old.fingerprint else old.version + 1
                    else:
                        v = 1
                    object.__setattr__(ev, "version", v)
                    merged[eid] = ev

                self._sync_internal_stores(merged)
                self._has_snapshot = True
                self.last_sync_error = ""
                self.last_updated_at = datetime.now(timezone.utc).isoformat()
                self.data_quality = "FRESH"
                self.last_sync_report = getattr(fetcher, "last_scan", None)
                self._save_cache()
                return True, "ok"
            except Exception as exc:
                err = safe_exception_message(exc)
                self.last_sync_error = err
                return False, err

        return await self.refresh_schedule_data()

    def get_current(self) -> list[CanonicalEvent]:
        """查询路径 (Query Path)：直接读取当前 L1 内存缓存，不现场发起网络请求。"""
        return list(self._events.values())

    def list_window(self, days: int = 14, now: datetime | None = None) -> list[CalendarActivity]:
        """查询在指定 horizon 范围内的活动 (兼容 CalendarActivity 格式)。"""
        current = _aware_utc(now) if now else datetime.now(timezone.utc)
        horizon = timedelta(days=days)

        results: list[CalendarActivity] = []
        for act in self._activities.values():
            if act.is_active(current):
                results.append(act)
            elif act.is_upcoming(current) and act.start_at <= current + horizon:
                results.append(act)

        results.sort(key=lambda a: (a.start_at, a.end_at))
        return results

    def list_reminder_deadlines(self, now: datetime | None = None) -> list[CalendarActivity]:
        """只返回当前处于 active 状态的活动用于截止提醒。"""
        current = _aware_utc(now) if now else datetime.now(timezone.utc)
        active_acts = [act for act in self._activities.values() if act.is_active(current)]
        active_acts.sort(key=lambda a: a.end_at)
        return active_acts

    def group_window(self, days: int = 14, now: datetime | None = None) -> dict[str, list[CalendarActivity]]:
        """统一文本与图片展示的分组规则。"""
        current = _aware_utc(now) if now else datetime.now(timezone.utc)
        horizon = timedelta(days=self.normalize_horizon(days))
        soon, active, upcoming = [], [], []

        for act in self._activities.values():
            if act.is_active(current):
                (soon if act.end_at - current <= timedelta(hours=24) else active).append(act)
            elif act.is_upcoming(current) and act.start_at <= current + horizon:
                upcoming.append(act)

        soon.sort(key=lambda a: a.end_at)
        active.sort(key=lambda a: a.end_at)
        upcoming.sort(key=lambda a: a.start_at)
        return {"ending_soon": soon, "active": active, "upcoming": upcoming}

    def format_schedule_text(
        self,
        days: int = 14,
        now: datetime | None = None,
        fallback_error: str = "",
    ) -> str:
        current = _aware_utc(now) if now else datetime.now(timezone.utc)

        if not self._has_snapshot:
            if fallback_error:
                return f"暂时无法获取官方日程：{fallback_error}。当前没有可用缓存，请稍后重试。"
            return "功能尚未就绪，正在同步官方日程，请稍候。"

        groups = self.group_window(days, current)
        soon, active, upcoming = groups["ending_soon"], groups["active"], groups["upcoming"]

        lines: list[str] = [f"【NIKKE 近期日程 · 未来 {days} 天】"]
        if self.last_updated_at:
            try:
                updated_dt = _aware_utc(self.last_updated_at).astimezone(CST)
                badge = quality_badge(self.data_quality, updated_dt)
                lines.append(f"（{badge} · 最近更新时间: {updated_dt.strftime('%Y-%m-%d %H:%M:%S')}）")
            except Exception:
                pass

        error_to_show = fallback_error or self.last_sync_error
        if error_to_show:
            lines.append(f"⚠️ 日程数据同步失败：{error_to_show}，以下为本地缓存。")

        if not soon and not active and not upcoming:
            lines.append(f"未来 {days} 天暂无已记录活动。")
            return "\n".join(lines).strip()

        def _format_item(act: CalendarActivity) -> str:
            label = CAT_LABELS.get(act.category, "活动")
            start_str = act.start_at.astimezone(CST).strftime("%m/%d %H:%M")
            end_str = act.end_at.astimezone(CST).strftime("%m/%d %H:%M")
            rem = act.remaining_display(current)
            return f"• [{label}] {act.title}\n  {start_str} → {end_str} · {rem}"

        if soon:
            lines.append("【即将结束】")
            for act in soon:
                lines.append(_format_item(act))

        if active:
            lines.append("【进行中】")
            for act in active:
                lines.append(_format_item(act))

        if upcoming:
            lines.append("【即将开始】")
            for act in upcoming:
                lines.append(_format_item(act))

        return "\n".join(lines).strip()

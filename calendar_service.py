# SPDX-License-Identifier: GPL-3.0-or-later
"""NIKKE 结构化活动日程服务。

遵循 Calendar v0.4 规格：
1. 维护本地结构化 activity snapshot，支持原子缓存写入；
2. 规范化 7/14/30 天 horizon 过滤，默认 14 天；
3. 输出互斥的【即将结束】、【进行中】、【即将开始】三组展示；
4. 同步失败时绝不破坏现有缓存，保留旧快照并提供告警提示；
5. list_reminder_deadlines 必须只返回 active 活动；
6. 统一使用 timezone-aware UTC datetime 计算，CST (UTC+8) 展示。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .calendar_models import CalendarActivity, _aware_utc
from .calendar_sources import GameKeeNikkeScheduleSource
from .log_privacy import safe_exception_message

logger = logging.getLogger("nikke.calendar.service")
CST = timezone(timedelta(hours=8))

CAT_LABELS = {
    "coop": "协同",
    "union_raid": "联盟突袭",
    "solo_raid": "单人突袭",
    "recruit": "招募",
    "maintenance": "维护",
    "update": "更新",
    "event": "活动",
}


class CalendarService:
    def __init__(self, data_dir: Path | str) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_path = self.data_dir / "calendar_cache.json"

        self._activities: dict[str, CalendarActivity] = {}
        self._has_snapshot: bool = False
        self.last_updated_at: str | None = None
        self.last_sync_report: dict[str, int] | None = None
        self.last_sync_error: str = ""

        self._load_cache()

    def has_snapshot(self) -> bool:
        return self._has_snapshot

    def activity_count(self) -> int:
        return len(self._activities)

    def list_activities(self) -> list[CalendarActivity]:
        return list(self._activities.values())

    @staticmethod
    def normalize_horizon(value: Any) -> int:
        """只接受 7、14、30 天，默认 14 天。

        严格拒绝 bool、float 以及不在白名单内的值。
        """
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

    def _load_cache(self) -> None:
        if not self.cache_path.is_file():
            self._has_snapshot = False
            self._activities = {}
            return

        try:
            content = self.cache_path.read_text(encoding="utf-8")
            data = json.loads(content)
            raw_activities = data.get("activities", [])
            activities: dict[str, CalendarActivity] = {}
            for item in raw_activities:
                act = CalendarActivity.from_dict(item)
                activities[act.event_id] = act
            self._activities = activities
            self.last_updated_at = data.get("updated_at")
            self._has_snapshot = True
            logger.info("[NIKKE] 载入活动日程缓存: %d 条活动", len(activities))
        except Exception as exc:
            logger.warning("[NIKKE] 活动日程缓存损坏或解析失败，保留空快照: %s", safe_exception_message(exc))
            self._activities = {}
            self._has_snapshot = False

    def _save_cache(self) -> None:
        payload = {
            "schema": 1,
            "updated_at": self.last_updated_at or datetime.now(timezone.utc).isoformat(),
            "activities": [act.to_dict() for act in self._activities.values()],
        }
        tmp_path = self.cache_path.with_suffix(".json.tmp")
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        tmp_path.replace(self.cache_path)

    async def sync_from_source(self, fetcher: Any = None) -> tuple[bool, str]:
        """从上游数据源拉取活动并原子更新缓存。

        若同步失败，绝不修改、清空现有快照或删除现有缓存。
        """
        if fetcher is None:
            fetcher = GameKeeNikkeScheduleSource()

        try:
            if hasattr(fetcher, "fetch") and callable(fetcher.fetch):
                res = fetcher.fetch()
            elif callable(fetcher):
                res = fetcher()
            else:
                raise TypeError(f"未知的 fetcher 类型: {type(fetcher)}")

            if inspect.isawaitable(res):
                incoming = await res
            else:
                incoming = res

            if not isinstance(incoming, list):
                raise ValueError(f"数据源返回必须是 CalendarActivity 列表: {type(incoming)}")

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            err = safe_exception_message(exc)
            self.last_sync_error = err
            logger.warning("[NIKKE] 日程数据同步失败: %s", err)
            return False, err

        # 批次内按 event_id 去重
        deduped: dict[str, CalendarActivity] = {}
        for act in incoming:
            if not isinstance(act, CalendarActivity):
                continue
            if act.event_id not in deduped:
                deduped[act.event_id] = act

        # 版本控制：fingerprint 不变时继承旧版本，变化时递增
        merged: dict[str, CalendarActivity] = {}
        for eid, act in deduped.items():
            old = self._activities.get(eid)
            if old is not None:
                if act.fingerprint == old.fingerprint:
                    v = old.version
                else:
                    v = old.version + 1
            else:
                v = 1
            object.__setattr__(act, "version", v)
            merged[eid] = act

        self._activities = merged
        self._has_snapshot = True
        self.last_sync_error = ""
        self.last_updated_at = datetime.now(timezone.utc).isoformat()
        self.last_sync_report = getattr(fetcher, "last_scan", None)
        try:
            self._save_cache()
        except Exception as exc:
            logger.error("[NIKKE] 日程缓存保存失败: %s", safe_exception_message(exc))

        return True, "ok"

    def list_window(self, days: int = 14, now: datetime | None = None) -> list[CalendarActivity]:
        """查询在指定 horizon 范围内的活动 (active + upcoming 在窗口内)。"""
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
        """只返回当前处于 active 状态的活动用于截止提醒，按 end_at 升序排列。"""
        current = _aware_utc(now) if now else datetime.now(timezone.utc)
        active_acts = [act for act in self._activities.values() if act.is_active(current)]
        active_acts.sort(key=lambda a: a.end_at)
        return active_acts

    def format_schedule_text(
        self,
        days: int = 14,
        now: datetime | None = None,
        fallback_error: str = "",
    ) -> str:
        current = _aware_utc(now) if now else datetime.now(timezone.utc)
        horizon = timedelta(days=days)

        if not self._has_snapshot:
            if fallback_error:
                return f"暂时无法获取官方日程：{fallback_error}。当前没有可用缓存，请稍后重试。"
            return "功能尚未就绪，正在同步官方日程，请稍候。"

        soon: list[CalendarActivity] = []
        active: list[CalendarActivity] = []
        upcoming: list[CalendarActivity] = []

        for act in self._activities.values():
            if act.is_active(current):
                if act.end_at - current <= timedelta(hours=24):
                    soon.append(act)
                else:
                    active.append(act)
            elif act.is_upcoming(current) and act.start_at <= current + horizon:
                upcoming.append(act)

        soon.sort(key=lambda a: a.end_at)
        active.sort(key=lambda a: a.end_at)
        upcoming.sort(key=lambda a: a.start_at)

        lines: list[str] = [f"【NIKKE 近期日程 · 未来 {days} 天】"]
        if self.last_updated_at:
            try:
                updated_dt = _aware_utc(self.last_updated_at).astimezone(CST)
                lines.append(f"（最近更新时间: {updated_dt.strftime('%Y-%m-%d %H:%M:%S')}）")
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

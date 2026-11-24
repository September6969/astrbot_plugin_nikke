# SPDX-License-Identifier: GPL-3.0-or-later
"""养成历史（27）：保存账户成长快照、展示关键差异并管理存储生命周期。

快照只由**成功的账号同步**写入；同一天重复同步会覆盖当天快照并计次，不产生重复条目。
不同用户使用独立键，解绑时由账号命令清除；读取只返回调用者自己的记录。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Protocol

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))
KEY_PREFIX = "growth_history_v1:"
MAX_ENTRIES = 120
MAX_AGE_DAYS = 180

FIELD_LABELS: dict[str, str] = {
    "commander_level": "指挥官等级",
    "team_combat": "队伍总战力",
    "synchro_level": "同步器等级",
    "character_count": "角色数量",
    "normal_campaign": "普通主线",
    "hard_campaign": "困难主线",
    "core_dust": "芯尘",
    "credits": "信用点",
    "battle_data": "战斗数据",
    "roster_count": "名单角色数",
}
_NUMERIC_FIELDS = frozenset(FIELD_LABELS)
_TEXT_FIELDS = frozenset({"normal_campaign", "hard_campaign"})
_CURRENCY_TYPES = {3000: "core_dust", 2000: "credits", 1000: "battle_data"}


class GrowthHistoryError(ValueError):
    """快照字段或用户标识不合法。"""


class GrowthStorePort(Protocol):
    def get_setting(self, key: str, default: Any = None) -> Any: ...

    def set_setting(self, key: str, value: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class GrowthPoint:
    captured_at: str
    day: str
    fields: Mapping[str, Any]
    samples: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "captured_at": self.captured_at,
            "day": self.day,
            "fields": dict(self.fields),
            "samples": self.samples,
        }


@dataclass(frozen=True, slots=True)
class GrowthChange:
    field: str
    label: str
    before: Any
    after: Any

    @property
    def delta(self) -> int | None:
        if isinstance(self.before, int) and isinstance(self.after, int):
            return self.after - self.before
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "label": self.label,
            "before": self.before,
            "after": self.after,
            "delta": self.delta,
        }


@dataclass(frozen=True, slots=True)
class GrowthRecordResult:
    recorded: bool
    duplicate_same_day: bool
    point: GrowthPoint | None
    previous: GrowthPoint | None
    changes: tuple[GrowthChange, ...] = ()


def _field_key(field: str) -> str:
    if field not in FIELD_LABELS:
        raise GrowthHistoryError(f"未知快照字段：{field}")
    return field


def _clean_fields(values: Mapping[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in values.items():
        _field_key(key)
        if value is None:
            continue
        if key in _TEXT_FIELDS:
            text = str(value).strip()
            if text:
                cleaned[key] = text
            continue
        if isinstance(value, bool):
            raise GrowthHistoryError(f"{FIELD_LABELS[key]} 必须是非负整数")
        if isinstance(value, str) and value.strip().isascii() and value.strip().isdigit():
            value = int(value.strip())
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        if not isinstance(value, int) or value < 0:
            raise GrowthHistoryError(f"{FIELD_LABELS[key]} 必须是非负整数")
        cleaned[key] = value
    return cleaned


def snapshot_from_dashboard(dashboard: Any) -> dict[str, Any]:
    """从 Profile dashboard DTO 提取非敏感成长字段；缺失字段留空。"""
    fields: dict[str, Any] = {}
    for key in ("commander_level", "team_combat", "synchro_level", "character_count"):
        value = getattr(dashboard, key, None)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            fields[key] = value
    for key in ("normal_campaign", "hard_campaign"):
        value = getattr(dashboard, key, None)
        if isinstance(value, str) and value.strip():
            fields[key] = value.strip()
    for item in getattr(dashboard, "currencies", None) or ():
        currency_type = getattr(item, "type", None)
        amount = getattr(item, "value", None)
        key = _CURRENCY_TYPES.get(currency_type) if isinstance(currency_type, int) else None
        if key and isinstance(amount, int) and not isinstance(amount, bool) and amount >= 0:
            fields[key] = amount
    return fields


class GrowthHistory:
    """按用户隔离的成长快照仓库；读写均经过字段校验。"""

    def __init__(
        self,
        store: GrowthStorePort,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _key(self, actor_id: str) -> str:
        text = str(actor_id or "").strip()
        if not text:
            raise GrowthHistoryError("缺少用户标识")
        return f"{KEY_PREFIX}{text}"

    def _load(self, actor_id: str) -> list[GrowthPoint]:
        raw = self._store.get_setting(self._key(actor_id), [])
        if not isinstance(raw, list):
            return []
        points: list[GrowthPoint] = []
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            day = str(item.get("day") or "")
            captured = str(item.get("captured_at") or "")
            fields = item.get("fields")
            if not day or not captured or not isinstance(fields, Mapping):
                continue
            samples = item.get("samples", 1)
            points.append(
                GrowthPoint(
                    captured_at=captured,
                    day=day,
                    fields=dict(fields),
                    samples=samples if isinstance(samples, int) and samples >= 1 else 1,
                )
            )
        points.sort(key=lambda point: point.captured_at)
        return points

    def _save(self, actor_id: str, points: list[GrowthPoint], now: datetime) -> None:
        cutoff = (now.astimezone(CST) - timedelta(days=MAX_AGE_DAYS)).date().isoformat()
        kept = [point for point in points if point.day >= cutoff][-MAX_ENTRIES:]
        self._store.set_setting(self._key(actor_id), [point.to_dict() for point in kept])

    def record(
        self,
        actor_id: str,
        fields: Mapping[str, Any],
        *,
        now: datetime | None = None,
        source: str = "profile",
    ) -> GrowthRecordResult:
        """写入一次成功同步快照；无效或空字段直接失败，绝不写入占位数据。"""
        current = now or self._clock()
        if not isinstance(current, datetime) or current.tzinfo is None:
            raise GrowthHistoryError("快照时间必须包含明确时区")
        if not isinstance(fields, Mapping):
            raise GrowthHistoryError("快照字段必须是映射")
        cleaned = _clean_fields(fields)
        if not cleaned:
            raise GrowthHistoryError("快照没有任何可用字段，未记录")
        day = current.astimezone(CST).date().isoformat()
        captured = current.astimezone(timezone.utc).isoformat()
        points = self._load(actor_id)
        previous = points[-1] if points else None
        duplicate = previous is not None and previous.day == day
        if duplicate:
            point = GrowthPoint(
                captured_at=captured,
                day=day,
                fields=cleaned,
                samples=previous.samples + 1,
            )
            points[-1] = point
        else:
            point = GrowthPoint(captured_at=captured, day=day, fields=cleaned, samples=1)
            points.append(point)
        points.sort(key=lambda item: item.captured_at)
        self._save(actor_id, points, current)
        baseline = previous if not duplicate else (points[-2] if len(points) > 1 else None)
        changes = diff_points(baseline, point)
        logger.debug(
            "[NIKKE] 养成历史已记录：用户=%s 来源=%s 同日重复=%s 字段数=%d",
            "***", source, duplicate, len(cleaned),
        )
        return GrowthRecordResult(
            recorded=True,
            duplicate_same_day=duplicate,
            point=point,
            previous=baseline,
            changes=changes,
        )

    def points(self, actor_id: str, *, limit: int = 10) -> tuple[GrowthPoint, ...]:
        if not 1 <= limit <= MAX_ENTRIES:
            raise GrowthHistoryError("历史条数上限必须在 1–120")
        return tuple(self._load(actor_id)[-limit:])

    def changes(self, actor_id: str) -> tuple[GrowthChange, ...]:
        points = self._load(actor_id)
        if len(points) < 2:
            return ()
        return diff_points(points[-2], points[-1])

    def clear(self, actor_id: str) -> None:
        """解绑或用户主动清空时删除全部快照。"""
        self._store.set_setting(self._key(actor_id), None)


def diff_points(before: GrowthPoint | None, after: GrowthPoint | None) -> tuple[GrowthChange, ...]:
    """比较两个快照的关键字段；只报告实际变化。"""
    if before is None or after is None:
        return ()
    changes: list[GrowthChange] = []
    for key, label in FIELD_LABELS.items():
        old = before.fields.get(key)
        new = after.fields.get(key)
        if old is None and new is None:
            continue
        if old == new:
            continue
        changes.append(GrowthChange(field=key, label=label, before=old, after=new))
    return tuple(changes)


def render_growth_history(
    points: tuple[GrowthPoint, ...],
    changes: tuple[GrowthChange, ...],
    *,
    upstream_error: str = "",
    roster: RosterSnapshot | None = None,
) -> str:
    """渲染养成历史；空数据与上游失败分别说明。"""
    lines = ["【养成历史】"]
    if upstream_error:
        lines.append(f"本次同步失败：{upstream_error}")
        lines.append("未写入新快照；以下仅展示此前成功记录。")
    if not points:
        lines.append("暂无成长快照（账户）。成功同步账号资料后会自动记录；空数据不会生成占位记录。")
        if roster is None:
            return "\n".join(lines)
    else:
        latest = points[-1]
        lines.append(
            f"最近快照：{latest.day}（采样 {latest.samples} 次） · 字段 {len(latest.fields)} 项"
        )
        for key, label in FIELD_LABELS.items():
            value = latest.fields.get(key)
            if value is None:
                continue
            lines.append(f"· {label}：{value}")
    if changes:
        lines.append("")
        lines.append("较上次变化：")
        for change in changes:
            delta = change.delta
            suffix = f"（{delta:+d}）" if delta not in (None, 0) else ""
            lines.append(
                f"· {change.label}：{change.before if change.before is not None else '—'}"
                f" → {change.after if change.after is not None else '—'}{suffix}"
            )
    elif len(points) >= 2:
        lines.append("较上次无关键字段变化。")
    if roster is not None:
        lines.append("")
        lines.append(f"角色快照：{len(roster.characters)} 名（{roster.day}）")
        if roster.changes:
            for change in roster.changes[:10]:
                if change.field == "new":
                    lines.append(f"· 新增 {change.name}")
                else:
                    label = "等级" if change.field == "level" else "突破"
                    lines.append(f"· {change.name} {label}：{change.before} → {change.after}")
        else:
            lines.append("较上次角色快照无等级/突破变化。")
    lines.append(f"共保存 {len(points)} 条快照（最多 {MAX_ENTRIES} 条，保留 {MAX_AGE_DAYS} 天）。")
    return "\n".join(lines)


ROSTER_KEY_PREFIX = "growth_roster_v1:"
ROSTER_MAX_CHARACTERS = 300


@dataclass(frozen=True, slots=True)
class CharacterPoint:
    name_code: str
    name: str
    level: int
    grade: int
    combat: int


@dataclass(frozen=True, slots=True)
class CharacterChange:
    name_code: str
    name: str
    field: str
    before: int | None
    after: int | None


@dataclass(frozen=True, slots=True)
class RosterSnapshot:
    captured_at: str
    day: str
    characters: tuple[CharacterPoint, ...]
    changes: tuple[CharacterChange, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "captured_at": self.captured_at,
            "day": self.day,
            "characters": [
                {
                    "name_code": item.name_code,
                    "name": item.name,
                    "level": item.level,
                    "grade": item.grade,
                    "combat": item.combat,
                }
                for item in self.characters
            ],
            "changes": [
                {
                    "name_code": item.name_code,
                    "name": item.name,
                    "field": item.field,
                    "before": item.before,
                    "after": item.after,
                }
                for item in self.changes
            ],
        }


class RosterGrowthHistory:
    """只保留最近一次角色名单快照与相对上次的变化，避免无界存储。"""

    def __init__(self, store: GrowthStorePort, *, clock: Callable[[], datetime] | None = None) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _key(self, actor_id: str) -> str:
        text = str(actor_id or "").strip()
        if not text:
            raise GrowthHistoryError("缺少用户标识")
        return f"{ROSTER_KEY_PREFIX}{text}"

    @staticmethod
    def _optional_int(value: Any, field: str) -> int:
        if value in (None, ""):
            return 0
        if isinstance(value, bool):
            raise GrowthHistoryError(f"角色 {field} 必须是非负整数")
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise GrowthHistoryError(f"角色 {field} 必须是非负整数") from exc
        if parsed < 0:
            raise GrowthHistoryError(f"角色 {field} 必须是非负整数")
        return parsed

    def record(
        self,
        actor_id: str,
        rows: Any,
        *,
        now: datetime | None = None,
    ) -> RosterSnapshot:
        """写入成功读取的角色名单快照；空名单或非法条目不会生成占位快照。"""
        if not isinstance(rows, (list, tuple)):
            raise GrowthHistoryError("角色名单必须是数组")
        current = now or self._clock()
        if not isinstance(current, datetime) or current.tzinfo is None:
            raise GrowthHistoryError("快照时间必须包含明确时区")
        characters: list[CharacterPoint] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            code = str(row.get("name_code") or "").strip()
            if not code or code in seen:
                continue
            seen.add(code)
            characters.append(
                CharacterPoint(
                    name_code=code,
                    name=str(row.get("name_zh_tw") or row.get("name_zh_cn") or row.get("name") or code),
                    level=self._optional_int(row.get("lv", row.get("level")), "等级"),
                    grade=self._optional_int(row.get("grade"), "突破"),
                    combat=self._optional_int(row.get("combat"), "战力"),
                )
            )
            if len(characters) >= ROSTER_MAX_CHARACTERS:
                break
        if not characters:
            raise GrowthHistoryError("角色名单为空，未记录")
        characters.sort(key=lambda item: item.name_code)
        previous = self.latest(actor_id)
        changes: list[CharacterChange] = []
        if previous is not None:
            before = {item.name_code: item for item in previous.characters}
            for item in characters:
                old = before.get(item.name_code)
                if old is None:
                    changes.append(CharacterChange(item.name_code, item.name, "new", None, item.level))
                    continue
                for field in ("level", "grade"):
                    old_value = getattr(old, field)
                    new_value = getattr(item, field)
                    if old_value != new_value:
                        changes.append(CharacterChange(item.name_code, item.name, field, old_value, new_value))
        day = current.astimezone(CST).date().isoformat()
        snapshot = RosterSnapshot(
            captured_at=current.astimezone(timezone.utc).isoformat(),
            day=day,
            characters=tuple(characters),
            changes=tuple(changes[:50]),
        )
        self._store.set_setting(self._key(actor_id), snapshot.to_dict())
        return snapshot

    def latest(self, actor_id: str) -> RosterSnapshot | None:
        raw = self._store.get_setting(self._key(actor_id), None)
        if not isinstance(raw, Mapping):
            return None
        characters_raw = raw.get("characters")
        if not isinstance(characters_raw, list):
            return None
        characters = tuple(
            CharacterPoint(
                name_code=str(item.get("name_code") or ""),
                name=str(item.get("name") or ""),
                level=int(item.get("level") or 0),
                grade=int(item.get("grade") or 0),
                combat=int(item.get("combat") or 0),
            )
            for item in characters_raw
            if isinstance(item, Mapping) and str(item.get("name_code") or "").strip()
        )
        changes_raw = raw.get("changes")
        changes = tuple(
            CharacterChange(
                name_code=str(item.get("name_code") or ""),
                name=str(item.get("name") or ""),
                field=str(item.get("field") or ""),
                before=item.get("before") if isinstance(item.get("before"), int) else None,
                after=item.get("after") if isinstance(item.get("after"), int) else None,
            )
            for item in changes_raw or ()
            if isinstance(item, Mapping)
        )
        return RosterSnapshot(
            captured_at=str(raw.get("captured_at") or ""),
            day=str(raw.get("day") or ""),
            characters=characters,
            changes=changes,
        )

    def clear(self, actor_id: str) -> None:
        self._store.set_setting(self._key(actor_id), None)


__all__ = [
    "FIELD_LABELS",
    "GrowthChange",
    "GrowthHistory",
    "GrowthHistoryError",
    "CharacterChange",
    "CharacterPoint",
    "GrowthPoint",
    "GrowthRecordResult",
    "ROSTER_KEY_PREFIX",
    "ROSTER_MAX_CHARACTERS",
    "RosterGrowthHistory",
    "RosterSnapshot",
    "MAX_AGE_DAYS",
    "MAX_ENTRIES",
    "diff_points",
    "render_growth_history",
    "snapshot_from_dashboard",
]

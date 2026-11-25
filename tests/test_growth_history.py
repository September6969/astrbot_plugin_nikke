# SPDX-License-Identifier: GPL-3.0-or-later
"""27 养成历史：空数据、同日重复、失败不写入、用户隔离与解绑清理。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from astrbot_plugin_nikke.features.growth.history import (
    FIELD_LABELS,
    GrowthHistory,
    GrowthHistoryError,
    RosterGrowthHistory,
    render_growth_history,
    snapshot_from_dashboard,
)


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def get_setting(self, key, default=None):
        return self.values.get(key, default)

    def set_setting(self, key, value):
        self.values[key] = value


def history(store=None) -> GrowthHistory:
    return GrowthHistory(store or MemoryStore(), clock=lambda: datetime.now(timezone.utc))


def test_empty_history_is_explicit_and_does_not_fabricate_points() -> None:
    service = history()
    text = render_growth_history(service.points("user-a"), service.changes("user-a"))
    assert "还没有成长记录" in text
    assert service.points("user-a") == ()


def test_same_day_repeat_overwrites_and_counts_samples() -> None:
    store = MemoryStore()
    service = history(store)
    first = datetime(2026, 9, 21, 1, 0, tzinfo=timezone.utc)
    second = datetime(2026, 9, 21, 6, 0, tzinfo=timezone.utc)

    result = service.record("user-a", {"commander_level": 100, "credits": 1000}, now=first)
    assert result.recorded and result.duplicate_same_day is False
    assert result.changes == ()

    again = service.record("user-a", {"commander_level": 101, "credits": 1200}, now=second)
    assert again.duplicate_same_day is True
    points = service.points("user-a")
    assert len(points) == 1
    assert points[0].samples == 2
    assert points[0].fields["commander_level"] == 101

    # 同一天覆盖不产生“较上次”变化行。
    assert service.changes("user-a") == ()
    assert "较上次无关键字段变化" not in render_growth_history(points, (), )


def test_changes_compare_latest_with_previous_day() -> None:
    service = history()
    day1 = datetime(2026, 9, 20, 3, 0, tzinfo=timezone.utc)
    day2 = datetime(2026, 9, 21, 3, 0, tzinfo=timezone.utc)
    service.record("user-a", {"commander_level": 100, "credits": 1000, "normal_campaign": "10-1"}, now=day1)
    result = service.record("user-a", {"commander_level": 102, "credits": 900, "normal_campaign": "10-2"}, now=day2)

    changes = {change.field: change for change in result.changes}
    assert changes["commander_level"].delta == 2
    assert changes["credits"].delta == -100
    assert changes["normal_campaign"].before == "10-1"
    assert "较上次变化" in render_growth_history(service.points("user-a"), result.changes)


def test_empty_or_invalid_snapshot_is_not_written() -> None:
    store = MemoryStore()
    service = history(store)
    with pytest.raises(GrowthHistoryError, match="没有任何可用字段"):
        service.record("user-a", {})
    with pytest.raises(GrowthHistoryError, match="非负整数"):
        service.record("user-a", {"credits": -1})
    with pytest.raises(GrowthHistoryError, match="未知快照字段"):
        service.record("user-a", {"cookie": "secret"})
    assert service.points("user-a") == ()
    assert store.values == {}


def test_upstream_failure_renders_previous_records_without_new_write() -> None:
    store = MemoryStore()
    service = history(store)
    service.record("user-a", {"commander_level": 100}, now=datetime(2026, 9, 20, tzinfo=timezone.utc))
    before = dict(store.values)

    text = render_growth_history(
        service.points("user-a"), service.changes("user-a"), upstream_error="网络超时"
    )
    assert "本次没能同步最新数据（网络超时）" in text
    assert "先看之前的记录" in text
    assert store.values == before


def test_users_are_isolated_and_unbind_clears_only_owner() -> None:
    store = MemoryStore()
    service = history(store)
    now = datetime(2026, 9, 21, tzinfo=timezone.utc)
    service.record("user-a", {"commander_level": 100}, now=now)
    service.record("user-b", {"commander_level": 200}, now=now)
    assert service.points("user-a")[0].fields["commander_level"] == 100
    assert service.points("user-b")[0].fields["commander_level"] == 200

    service.clear("user-a")
    assert service.points("user-a") == ()
    assert service.points("user-b")[0].fields["commander_level"] == 200


def test_retention_prunes_old_entries_and_caps_length() -> None:
    service = history()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for day in range(5):
        service.record("user-a", {"commander_level": day}, now=start + timedelta(days=day))
    # 240 天后再次记录：旧记录超出 180 天保留期被清理。
    service.record("user-a", {"commander_level": 99}, now=start + timedelta(days=240))
    points = service.points("user-a", limit=120)
    assert [point.fields["commander_level"] for point in points] == [99]


def test_snapshot_extraction_uses_only_non_sensitive_fields() -> None:
    dashboard = SimpleNamespace(
        commander_level=150,
        team_combat=120000,
        synchro_level=200,
        character_count=90,
        normal_campaign="20-1",
        hard_campaign="10-1",
        currencies=(
            SimpleNamespace(type=3000, value=5000),
            SimpleNamespace(type=2000, value=6000),
            SimpleNamespace(type=1000, value=7000),
            SimpleNamespace(type=99, value=8000),
        ),
    )
    fields = snapshot_from_dashboard(dashboard)
    assert fields == {
        "commander_level": 150,
        "team_combat": 120000,
        "synchro_level": 200,
        "character_count": 90,
        "normal_campaign": "20-1",
        "hard_campaign": "10-1",
        "core_dust": 5000,
        "credits": 6000,
        "battle_data": 7000,
    }
    assert "cookie" not in fields
    assert set(FIELD_LABELS) >= set(fields)


def test_roster_snapshot_keeps_latest_and_reports_character_changes() -> None:
    store = MemoryStore()
    roster = RosterGrowthHistory(store, clock=lambda: datetime(2026, 9, 21, tzinfo=timezone.utc))
    first = roster.record(
        "user-a",
        [
            {"name_code": 1001, "lv": 200, "grade": 2, "combat": 100000},
            {"name_code": 1002, "lv": 180, "grade": 0, "combat": 80000},
        ],
        now=datetime(2026, 9, 20, tzinfo=timezone.utc),
    )
    assert not first.changes
    assert len(first.characters) == 2

    second = roster.record(
        "user-a",
        [
            {"name_code": 1001, "lv": 210, "grade": 3, "combat": 120000},
            {"name_code": 1003, "lv": 150, "grade": 0, "combat": 70000},
        ],
        now=datetime(2026, 9, 21, tzinfo=timezone.utc),
    )
    fields = {(change.name_code, change.field) for change in second.changes}
    assert ("1001", "level") in fields
    assert ("1001", "grade") in fields
    assert ("1003", "new") in fields
    # 1002 已离开名单，最新快照不再包含它。
    assert {item.name_code for item in roster.latest("user-a").characters} == {"1001", "1003"}

    text = render_growth_history(
        GrowthHistory(MemoryStore()).points("user-a"), (), roster=roster.latest("user-a")
    )
    assert "角色练度记录：共 2 名" in text
    assert "新入手" in text

    roster.clear("user-a")
    assert roster.latest("user-a") is None


def test_roster_snapshot_is_per_user_and_rejects_empty_lists() -> None:
    roster = RosterGrowthHistory(MemoryStore())
    with pytest.raises(GrowthHistoryError, match="为空"):
        roster.record("user-a", [])
    with pytest.raises(GrowthHistoryError, match="数组"):
        roster.record("user-a", {"name_code": 1})
    roster.record("user-a", [{"name_code": 1, "lv": 1}])
    assert roster.latest("user-a") is not None
    assert roster.latest("user-b") is None


def test_identity_isolation_clear_all_and_generation_race_protection() -> None:
    store = MemoryStore()
    now = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)
    hist = GrowthHistory(store, clock=lambda: now)
    roster = RosterGrowthHistory(store, clock=lambda: now)

    id1 = "global:81:111111"
    id2 = "jp:82:222222"
    hist.record("user-a", {"commander_level": 100}, now=now - timedelta(days=10), identity=id1)
    hist.record("user-a", {"commander_level": 120}, now=now, identity=id1)
    hist.record("user-a", {"commander_level": 250}, now=now, identity=id2)
    roster.record("user-a", [{"name_code": 1001, "lv": 200}], now=now, identity=id1)

    assert [p.fields["commander_level"] for p in hist.points("user-a", identity=id1)] == [100, 120]
    assert [p.fields["commander_level"] for p in hist.points("user-a", identity=id2)] == [250]
    assert [p.fields["commander_level"] for p in hist.query_range("user-a", days=3, identity=id1)] == [120]

    # 模拟清空前启动的并发拉取：先读代数，再清空，最后旧拉取回写不得落盘。
    stale_gen = hist.generation("user-a")
    hist.clear("user-a")
    roster.clear("user-a")
    assert hist.points("user-a", identity=id1) == ()
    assert hist.points("user-a", identity=id2) == ()
    assert roster.latest("user-a", identity=id1) is None

    stale = hist.record(
        "user-a", {"commander_level": 111}, now=now, identity=id1, expected_generation=stale_gen
    )
    stale_roster = roster.record(
        "user-a", [{"name_code": 1001, "lv": 205}], now=now, identity=id1, expected_generation=stale_gen
    )
    assert stale.recorded is False
    assert stale_roster.recorded is False
    assert hist.points("user-a", identity=id1) == ()
    assert roster.latest("user-a", identity=id1) is None


def test_roster_preserves_none_vs_zero_and_same_day_changes() -> None:
    store = MemoryStore()
    roster = RosterGrowthHistory(store, clock=lambda: datetime(2026, 9, 21, tzinfo=timezone.utc))
    d1 = datetime(2026, 9, 20, 1, 0, tzinfo=timezone.utc)
    d2_am = datetime(2026, 9, 21, 1, 0, tzinfo=timezone.utc)
    d2_pm = datetime(2026, 9, 21, 5, 0, tzinfo=timezone.utc)

    roster.record("user-a", [{"name_code": 1001, "lv": None, "grade": 0, "combat": None}], now=d1)
    first = roster.latest("user-a")
    assert first.characters[0].level is None
    assert first.characters[0].grade == 0
    assert first.characters[0].combat is None

    # d1 lv=None -> d2 lv=200 不应凭空伪造从 0 到 200 的变化；突破 0 -> 1 应记录。
    up = roster.record("user-a", [{"name_code": 1001, "lv": 200, "grade": 1}], now=d2_am)
    assert [(c.field, c.before, c.after) for c in up.changes] == [("grade", 0, 1)]

    # 同天再次读取名单无新变化时，保留当天已记录的变化摘要。
    repeat = roster.record("user-a", [{"name_code": 1001, "lv": 200, "grade": 1}], now=d2_pm)
    assert [(c.field, c.before, c.after) for c in repeat.changes] == [("grade", 0, 1)]

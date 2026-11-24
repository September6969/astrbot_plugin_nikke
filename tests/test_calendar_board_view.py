# SPDX-License-Identifier: GPL-3.0-or-later
"""04 卡池与活动日历：固定时间边界、类型分组与缺失字段。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from astrbot_plugin_nikke.features.calendar.board import (
    build_board,
    group_of,
    normalize_group,
    render_board,
    up_rate_of,
)
from astrbot_plugin_nikke.features.calendar.canonical_models import CanonicalEvent

CST = timezone(timedelta(hours=8))


def event(
    event_id: str,
    title: str,
    event_type: str,
    start: datetime,
    end: datetime,
    **metadata,
) -> CanonicalEvent:
    return CanonicalEvent(
        id=event_id,
        title=title,
        event_type=event_type,
        start_at=start,
        end_at=end,
        sources=["blabla"],
        primary_source="blabla",
        metadata=metadata,
    )


def fixed_now() -> datetime:
    return datetime(2026, 9, 21, 12, 0, tzinfo=CST)


def test_groups_cover_pool_activity_skin_and_raid_only() -> None:
    now = fixed_now()
    events = (
        event("pool", "Pick Up · 新角色", "recruit", now - timedelta(days=2), now + timedelta(days=10)),
        event("story", "NO CALLER ID", "story_event", now - timedelta(days=1), now + timedelta(days=5)),
        event("skin", "转盘时装", "costume_gacha", now, now + timedelta(days=3)),
        event("solo", "个人突袭", "solo_raid", now, now + timedelta(days=2)),
        event("union", "联盟突袭", "union_raid", now, now + timedelta(days=2)),
        event("maint", "维护", "maintenance", now, now + timedelta(hours=4)),
    )

    board = build_board(events, now)

    assert [item.event_id for item in board.by_group("卡池")] == ["pool"]
    assert [item.event_id for item in board.by_group("活动")] == ["story"]
    assert [item.event_id for item in board.by_group("皮肤")] == ["skin"]
    assert {item.event_id for item in board.by_group("突袭")} == {"solo", "union"}
    # 维护不是可参与活动，不能被塞进任何展示组。
    assert board.unclassified == 1
    assert group_of(events[-1]) is None
    assert normalize_group("时装") == "皮肤"
    assert normalize_group("unknown") is None


def test_fixed_boundaries_and_countdown_use_beijing_time() -> None:
    now = fixed_now()
    ongoing = event(
        "ongoing", "进行中卡池", "recruit",
        now - timedelta(days=1), now + timedelta(days=10, hours=16),
    )
    starts_now = event("starts", "刚好开始", "event", now, now + timedelta(hours=2))
    ends_now = event("ends", "刚好结束", "event", now - timedelta(hours=2), now)
    upcoming = event("soon", "即将开始", "recruit", now + timedelta(minutes=30), now + timedelta(days=1))
    date_only = CanonicalEvent(
        id="dateonly", title="仅日期活动", event_type="event",
        start_at=now - timedelta(days=1), end_at=now + timedelta(days=2),
        end_precision="DATE_ONLY",
    )

    board = build_board((ongoing, starts_now, ends_now, upcoming, date_only), now)
    by_id = {item.event_id: item for item in board.items}

    assert by_id["ongoing"].status == "进行中"
    assert by_id["ongoing"].countdown == "剩余 10天16小时"
    assert by_id["ongoing"].start_display == (now - timedelta(days=1)).strftime("%m-%d %H:%M")
    assert by_id["starts"].status == "进行中"
    assert by_id["ends"].status == "已结束"
    assert by_id["ends"].countdown == "已结束"
    assert by_id["soon"].status == "即将开始"
    assert by_id["soon"].countdown == "距开始 30分钟"
    # 只有日期精度时不得伪造小时倒计时。
    assert "当日截止（仅日期）" in by_id["dateonly"].countdown

    text = render_board(board)
    assert "北京时间 UTC+8" in text
    assert "2026-09-21 12:00" in text
    assert "【卡池】" in text and "【活动】" in text


def test_up_rate_missing_is_explicit_and_only_pools_report_it() -> None:
    now = fixed_now()
    plain = event("plain", "无概率卡池", "recruit", now - timedelta(days=1), now + timedelta(days=1))
    assert up_rate_of(plain) == (None, True)
    assert "UP 概率：上游未提供（缺失）" in render_board(build_board((plain,), now))

    detailed = event(
        "detailed", "有概率卡池", "recruit", now - timedelta(days=1), now + timedelta(days=1),
        up_rate={"SSR": 1.5, "SR": 3.0},
    )
    rate, missing = up_rate_of(detailed)
    assert missing is False
    assert rate == "SR 3%、SSR 1.5%"
    assert "UP 概率：SR 3%、SSR 1.5%" in render_board(build_board((detailed,), now))

    # 非数值概率字段不能被当作已公布概率。
    bogus = event("bogus", "坏概率", "recruit", now, now + timedelta(days=1), up_rate="up")
    assert up_rate_of(bogus) == (None, True)

    # 皮肤等非卡池记录不产生“概率缺失”噪音。
    skin = event("skin", "转盘时装", "costume_gacha", now, now + timedelta(days=1))
    skin_board = build_board((skin,), now)
    assert skin_board.up_rate_missing is False
    assert skin_board.items[0].up_rate is None


def test_type_filter_limits_output_and_rejects_unknown_group() -> None:
    now = fixed_now()
    events = (
        event("pool", "卡池", "recruit", now, now + timedelta(days=1)),
        event("skin", "皮肤", "costume_gacha", now, now + timedelta(days=1)),
    )
    only_skin = build_board(events, now, groups=("皮肤",))
    assert [item.group for item in only_skin.items] == ["皮肤"]
    assert only_skin.unclassified == 0

    with_maint = (*events, event("maint", "维护", "maintenance", now, now + timedelta(hours=2)))
    only_skin_with_maint = build_board(with_maint, now, groups=("皮肤",))
    assert [item.group for item in only_skin_with_maint.items] == ["皮肤"]
    assert only_skin_with_maint.unclassified == 1

    try:
        build_board(events, now, groups=("不存在",))
    except ValueError as exc:
        assert "未知日程类型" in str(exc)
    else:  # pragma: no cover - 明确失败比静默忽略更安全
        raise AssertionError("未知类型必须报错")

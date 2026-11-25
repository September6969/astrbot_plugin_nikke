# SPDX-License-Identifier: GPL-3.0-or-later
"""公开同步器/赛季数据的解析、幂等写入与缺失字段边界。"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from astrbot_plugin_nikke.features.solo_raid.public_source import (
    build_season_payload,
    parse_season_detail,
    parse_season_index,
    write_season_payload,
)
from astrbot_plugin_nikke.features.sync.public_source import (
    build_sync_payload,
    parse_sync_ranges,
    write_sync_payload,
)

SYNC_JS = (
    "let n=[{from:201,to:250,credit:1694200,battleData:0x13f96d8,coreDust:1e4},"
    "{from:251,to:300,credit:3134e3,battleData:0x2609350,coreDust:1e4}];e.s(["
)

INDEX_HTML = """
<a class="ayneWG_seasonSwitchItem ayneWG_seasonSwitchItemOn" aria-current="page" href="/zh-tw/raids/solo">
<span class="ayneWG_seasonSwitchTitle">單人突襲 賽季 43<!-- -->, Goddess of Victory</span>
<span class="ayneWG_seasonMeta">11/12(四) 12:00 ~ 11/19(四) 04:59</span></a>
<a class="ayneWG_seasonSwitchItem" href="/zh-tw/raids/solo-42">
<span class="ayneWG_seasonSwitchTitle">單人突襲 賽季 42<!-- -->, Altruia</span>
<span class="ayneWG_seasonMeta">10/15(四) 12:00 ~ 10/22(四) 04:59</span></a>
"""

DETAIL_HTML = """
<section aria-label="首領資訊"><ul class="ayneWG_bossList"><li class="ayneWG_boss">
<h3 class="ayneWG_bossName">Goddess of Victory</h3><dl class="ayneWG_attrs">
<div class="ayneWG_attr"><dt>屬性</dt><dd><img/>風壓</dd></div>
<div class="ayneWG_attr"><dt>弱點</dt><dd>燃燒代碼</dd></div>
</dl><p class="ayneWG_gimmick">這段攻略正文不應被索引。</p></li></ul></section>
"""


def test_sync_parser_expands_ranges_and_is_idempotent(tmp_path=None) -> None:
    rows = parse_sync_ranges(SYNC_JS)
    assert rows[0] == {"from": 201, "to": 250, "credits": 1694200, "battle_data": 20944600, "core_dust": 10000}
    payload = build_sync_payload(rows, checked_at="2026-11-23")
    assert len(payload["levels"]) == 100
    assert payload["levels"][0]["level"] == 201
    path = Path("output") / ".test-sync-costs.json"
    try:
        assert write_sync_payload(path, payload) is True
        assert write_sync_payload(path, payload) is False
    finally:
        path.unlink(missing_ok=True)


def test_season_parser_keeps_only_facts_and_normalizes_timezone() -> None:
    index_rows = parse_season_index(INDEX_HTML)
    assert [row["id"] for row in index_rows] == ["43", "42"]
    detail = parse_season_detail(DETAIL_HTML)
    assert detail == {
        "name": "Goddess of Victory",
        "element": "風壓",
        "weakness": "燃燒",
        "recommended": "",
    }
    assert "攻略正文" not in detail.values()

    payload = build_season_payload(
        index_rows,
        {"43": detail, "42": {**detail, "name": "Altruia"}},
        as_of=dt.date(2026, 11, 23),
        checked_at="2026-11-23",
        existing_seasons=[
            {"id": "43", "ends_at": "2026-11-18T19:59:00+00:00", "custom_field": "keep"},
            {"id": "42", "ends_at": "2026-10-21T19:59:00+00:00"},
            {"id": "41", "name": "赛季 41", "ends_at": "2026-09-30T19:59:00+00:00", "source_url": "https://nikkehub.com/zh-tw/raids/solo-41", "checked_at": "2026-11-23", "bosses": []},
        ],
    )
    by_id = {season["id"]: season for season in payload["seasons"]}
    assert by_id["43"]["ends_at"] == "2026-11-18T19:59:00+00:00"
    assert by_id["43"]["custom_field"] == "keep"
    assert by_id["42"]["ends_at"] == "2026-10-21T19:59:00+00:00"
    # 本次索引未出现的旧赛季不能丢。
    assert by_id["41"]["name"] == "赛季 41"
    assert "已结束" not in payload["note"]
    assert "不擅自补年份" in payload["note"]

    # 新赛季无旧记录时只给月日，不擅自编年份。
    unknown = build_season_payload(
        index_rows[:1], {"43": {**detail, "name": "New Season"}},
        as_of=dt.date(2026, 11, 23), checked_at="2026-11-23",
    )
    assert unknown["seasons"][0]["ends_at"] == ""

    try:
        build_season_payload(
            index_rows[:1],
            {"43": {**detail, "weakness": ""}},
            as_of=dt.date(2026, 11, 23), checked_at="2026-11-23",
        )
    except ValueError as exc:
        assert "缺少公开弱点" in str(exc)
    else:
        raise AssertionError("缺少弱点必须失败并保留旧文件")

    path = Path("output") / ".test-solo-seasons.json"
    try:
        assert write_season_payload(path, payload) is True
        assert write_season_payload(path, payload) is False
    finally:
        path.unlink(missing_ok=True)

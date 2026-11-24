# SPDX-License-Identifier: GPL-3.0-or-later
"""22 单人突袭五队：可维护数据、全局去重、爆裂链、估伤边界、方案隔离与阵容图。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from jinja2 import Environment, StrictUndefined

from astrbot_plugin_nikke.features.solo_raid.builder import (
    Member,
    SoloRaidError,
    build_five_teams,
    check_burst_chain,
    parse_members,
    render_plan,
)
from astrbot_plugin_nikke.features.solo_raid.plans import SoloRaidPlanStore
from astrbot_plugin_nikke.features.solo_raid.seasons import SeasonCatalog, season_status
from astrbot_plugin_nikke.ui.payloads.solo_raid import SoloRaidPayloadBuilder
from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader

SOURCE = "https://example.invalid/synthetic-solo-raid.json"


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def get_setting(self, key, default=None):
        return self.values.get(key, default)

    def set_setting(self, key, value):
        self.values[key] = value


def season_payload() -> dict:
    return {
        "schema_version": 1,
        "seasons": [
            {
                "id": "s1",
                "name": "合成赛季",
                "source_url": SOURCE,
                "checked_at": "2026-09-21",
                "bosses": [
                    {"id": "b1", "name": "合成首领", "weakness": "风压", "element": "Wind"}
                ],
            }
        ],
    }


def roster() -> tuple[Member, ...]:
    members: list[Member] = []
    for index in range(1, 6):
        members.append(Member(f"b1-{index}", f"一号{index}", "Step1"))
        members.append(Member(f"b2-{index}", f"二号{index}", "Step2"))
    for index in range(1, 16):
        members.append(Member(f"b3-{index}", f"三号{index}", "Step3"))
    return tuple(members)


def test_season_catalog_requires_verifiable_source_and_reports_empty(tmp_path=None) -> None:
    catalog = SeasonCatalog.from_payload(season_payload())
    assert catalog.available is True
    assert catalog.latest().bosses[0].weakness == "风压"

    empty = SeasonCatalog.from_payload({"schema_version": 1, "seasons": [], "note": "待导入"})
    assert empty.available is False
    assert "待导入" in empty.reason

    with pytest.raises(ValueError, match="HTTPS"):
        SeasonCatalog.from_payload(
            {
                "schema_version": 1,
                "seasons": [
                    {
                        "id": "s1", "name": "坏来源",
                        "source_url": "http://example.invalid/x", "checked_at": "2026-09-21",
                        "bosses": [{"id": "b", "name": "B", "weakness": "风"}],
                    }
                ],
            }
        )


def test_five_teams_are_unique_and_chain_valid() -> None:
    season = SeasonCatalog.from_payload(season_payload()).latest()
    plan = build_five_teams(roster(), season=season)

    assert len(plan.teams) == 5
    assert plan.chain_ok is True
    assert plan.issues == ()
    codes = [member.name_code for team in plan.teams for member in team.members]
    assert len(codes) == 25
    assert len(set(codes)) == 25
    assert all(len(team.members) == 5 for team in plan.teams)

    # 输入重复时全局去重，不把同一角色放进两队。
    duplicated = build_five_teams((*roster(), Member("b1-1", "重复", "Step1")))
    duplicated_codes = [member.name_code for team in duplicated.teams for member in team.members]
    assert len(duplicated_codes) == len(set(duplicated_codes)) == 25


def test_short_roster_reports_missing_roles_and_chain_gaps() -> None:
    shortage = tuple(roster()[:7])
    plan = build_five_teams(shortage)
    assert plan.chain_ok is False
    assert any("人数不足" in issue for issue in plan.issues)
    assert any("缺少" in issue for issue in plan.issues)
    assert any(not team.chain_ok for team in plan.teams)

    ok, issues = check_burst_chain((Member("a", "A", "Step1"), Member("b", "B", "Step2")))
    assert ok is False
    assert issues == ("缺少 B3",)


def test_damage_estimate_is_optional_and_labeled() -> None:
    plan = build_five_teams(roster())
    assert plan.damage_total is None
    text = render_plan(plan)
    assert "无法估算" in text or "不估算伤害" in text
    assert "官方" not in text

    modeled = build_five_teams(
        roster(),
        damage_model={"per_member": 1000, "chain_bonus": 500, "label": "合成估算"},
    )
    assert modeled.damage_total == 5 * (1000 * 5 + 500)
    assert "合成估算" in render_plan(modeled)
    assert "配置化估算" in modeled.estimate_note

    with pytest.raises(SoloRaidError, match="非负整数"):
        build_five_teams(roster(), damage_model={"per_member": -1})


def test_plan_store_is_owner_scoped_and_round_trips() -> None:
    store = MemoryStore()
    plans = SoloRaidPlanStore(store, clock=lambda: datetime(2026, 9, 21, tzinfo=timezone.utc))
    plan = build_five_teams(roster(), season=SeasonCatalog.from_payload(season_payload()).latest())

    saved = plans.save("user-a", plan)
    assert saved.actor_id == "user-a"
    loaded = plans.load("user-a")
    assert loaded is not None
    assert len(loaded.teams) == 5
    assert [member.name_code for member in loaded.teams[0].members] == [
        member.name_code for member in plan.teams[0].members
    ]
    # 其他用户看不到该方案。
    assert plans.load("user-b") is None
    assert not any("user-a" in key for key in store.values if "user-b" in key)

    plans.clear("user-a")
    assert plans.load("user-a") is None


def test_lineup_payload_and_template_keep_five_teams_with_placeholders() -> None:
    plan = build_five_teams(roster(), season=SeasonCatalog.from_payload(season_payload()).latest())
    payload = SoloRaidPayloadBuilder().build(plan, boss=plan and SeasonCatalog.from_payload(season_payload()).latest().bosses[0])
    markup = Environment(undefined=StrictUndefined).from_string(
        T2ITemplateLoader().load("solo_raid")
    ).render(**payload)
    assert markup.count("第 ") == 5
    assert "合成首领" in markup
    assert "solo-placeholder" in markup
    assert "无法估伤" in markup or "不估算伤害" in markup
    assert payload["canvas"]["width"] == 1000


def test_parse_members_rejects_duplicates_and_keeps_burst_tokens() -> None:
    members = parse_members("拉毗:B3,尼恩:B1,阿妮斯:B2")
    assert [member.burst for member in members] == ["Step3", "Step1", "Step2"]
    with pytest.raises(SoloRaidError, match="重复"):
        parse_members("拉毗,拉毗")


def test_imported_season_43_and_historical_index_status(tmp_path) -> None:
    import json
    from pathlib import Path

    bundled = Path(__file__).resolve().parents[1] / "assets" / "data" / "solo_raid_seasons.json"
    assert not bundled.exists()
    assert SeasonCatalog.from_file(bundled).available is False

    season_file = tmp_path / "solo-raid-seasons.json"
    season_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "seasons": [
                    {
                        "id": "42",
                        "name": "赛季 42",
                        "source_url": "https://example.invalid/solo-42",
                        "checked_at": "2026-11-24",
                        "ends_at": "2026-10-21T19:59:00+00:00",
                        "bosses": [{"id": "b42", "name": "Altruia", "weakness": "电击", "element": ""}],
                    },
                    {
                        "id": "43",
                        "name": "赛季 43",
                        "source_url": "https://www.blablalink.com/?plate_type=official",
                        "checked_at": "2026-11-24",
                        "ends_at": "2026-11-18T19:59:00+00:00",
                        "bosses": [{"id": "b43", "name": "Goddess of Victory", "weakness": "燃烧", "element": "风压"}],
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    catalog = SeasonCatalog.from_file(season_file)
    assert catalog.available is True and len(catalog.seasons) == 2
    season = catalog.latest()
    assert season.season_id == "43"
    before = season_status(season, datetime(2026, 11, 18, 19, 58, tzinfo=timezone.utc))
    after = season_status(season, datetime(2026, 11, 18, 20, 0, tzinfo=timezone.utc))
    assert "进行中" in before
    assert "已结束" in after and "2026-11-19 04:59" in after

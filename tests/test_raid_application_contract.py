import ast
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from astrbot_plugin_nikke.features.raid.application import (
    RaidApplication,
    RaidMemberIdentityUnavailable,
)
from astrbot_plugin_nikke.features.raid.builder import UnionRaidBuilder
from astrbot_plugin_nikke.features.raid.models import RaidResponseCoverage, RaidState


class RaidAccountReader:
    def __init__(self):
        self.account = {"area_id": 81, "game_openid": "stable-openid"}
        self.requested_ids = []

    def get_account(self, qq_id):
        self.requested_ids.append(qq_id)
        return self.account


class RaidGateway:
    def __init__(self, *, overview=None, raid_data=None, season_data=None):
        self.overview_requests = []
        self.raid_snapshot_requests = []
        self.raid_data_requests = []
        self.season_requests = []
        self.raid_data = raid_data or {
            "manager_info": {"id": "1000007"},
            "level_info": [],
            "participate_data": [],
        }
        self.season_data = season_data or {"participate_data": []}
        self.overview = overview

    async def get_union_raid_overview(self, account, *, attacks=False):
        self.overview_requests.append((account, attacks))
        return self.overview or {
            "guild_id": "guild-7",
            "guild_name": "雪原",
            "level_info": {
                "manager_info": {
                    "id": "1000007",
                    "season_start_date": "2026-09-01T00:00:00+00:00",
                    "season_end_date": "2026-09-22T10:30:00+00:00",
                },
                "level_info": [
                    {
                        "difficulty": 12,
                        "level": 3,
                        "boss_info": [
                            {
                                "boss_id": 17,
                                "current_hp": 50,
                                "max_hp": 100,
                                "name_localvalues": {"zh-cn": "雪原守卫"},
                            }
                        ],
                    }
                ],
            },
        }

    async def get_union_raid_data(self, account):
        self.raid_data_requests.append(account)
        return self.raid_data

    async def get_union_raid_snapshot(self, account):
        self.raid_snapshot_requests.append(account)
        return {
            "guild_id": "guild-7",
            "guild_name": "雪原",
            "level_info": self.raid_data,
        }

    async def get_union_raid_season(self, account, *, guild_id, season_id, levels=False):
        self.season_requests.append((account, guild_id, season_id, levels))
        return self.season_data


def attack(openid, damage):
    return {
        "openid": openid,
        "nickname": f"member-{openid}",
        "boss_id": "boss-1",
        "day": 1,
        "difficulty": 2,
        "level": 3,
        "step": 4,
        "total_damage": damage,
        "is_final_hit": False,
        "squad": [
            {"tid": str(slot), "lv": 100, "combat": 1000, "slot": slot}
            for slot in range(1, 6)
        ],
    }


def offseason_builder(tmp_path):
    manifest_path = tmp_path / "seasons.json"
    manifest_path.write_text(
        json.dumps(
            [
                {
                    "id": 1234567,
                    "start_ts": 10,
                    "end_ts": 100,
                    "caculate_ts": 101,
                    "season_start_date": "2026-01-01T00:00:00+00:00",
                    "season_end_date": "2026-01-02T00:00:00+00:00",
                    "caculate_date": "2026-01-03T00:00:00+00:00",
                }
            ]
        ),
        encoding="utf-8",
    )
    return UnionRaidBuilder(manifest_path)


@pytest.mark.asyncio
async def test_overview_uses_one_injected_clock_snapshot_for_state_and_display():
    account_reader = RaidAccountReader()
    gateway = RaidGateway()
    clock_calls = []
    query_time = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)

    def clock():
        clock_calls.append(query_time)
        return query_time

    application = RaidApplication(
        account_reader=account_reader,
        gateway=gateway,
        builder=UnionRaidBuilder(),
        clock=clock,
        plugin_version="test-version",
    )

    overview = await application.overview("qq-123")

    assert account_reader.requested_ids == ["qq-123"]
    assert gateway.overview_requests == [(account_reader.account, False)]
    assert clock_calls == [query_time]
    assert overview.raid_state is RaidState.ACTIVE
    assert overview.response_coverage is RaidResponseCoverage.CURRENT_RESPONSE
    assert overview.fetched_at == "2026-09-22 18:00"
    assert overview.plugin_version == "test-version"


@pytest.mark.asyncio
async def test_overview_uses_same_clock_for_offseason_state_and_history_totals(tmp_path):
    account_reader = RaidAccountReader()
    gateway = RaidGateway(
        overview={
            "guild_id": "guild-7",
            "guild_name": "雪原",
            "level_info": {"manager_info": {"id": "0"}, "level_info": []},
        },
        season_data={
            "participate_data": [
                {"total_damage": "7"},
                {"damage": 12},
            ]
        },
    )
    query_time = datetime.fromtimestamp(200, timezone.utc)
    clock_calls = []
    application = RaidApplication(
        account_reader=account_reader,
        gateway=gateway,
        builder=offseason_builder(tmp_path),
        clock=lambda: clock_calls.append(query_time) or query_time,
        plugin_version="test-version",
    )

    overview = await application.overview("qq-123")

    assert clock_calls == [query_time]
    assert overview.raid_state is RaidState.OFFSEASON
    assert overview.previous_season.season_id == "1234567"
    assert overview.previous_season.total_attacks == 2
    assert overview.previous_season.total_damage == 19
    assert gateway.season_requests == [
        (account_reader.account, "guild-7", "1234567", False)
    ]


@pytest.mark.asyncio
async def test_ranking_uses_explicit_latest_season_only_for_empty_offseason_response(tmp_path):
    account_reader = RaidAccountReader()
    gateway = RaidGateway(
        raid_data={
            "manager_info": {"id": "0"},
            "level_info": [],
            "participate_data": [],
        },
        season_data={"participate_data": [attack("member-1", 12)]},
    )
    query_time = datetime.fromtimestamp(200, timezone.utc)
    clock_calls = []
    application = RaidApplication(
        account_reader=account_reader,
        gateway=gateway,
        builder=offseason_builder(tmp_path),
        clock=lambda: clock_calls.append(query_time) or query_time,
        plugin_version="test-version",
    )

    ranking = await application.ranking("qq-123")

    assert gateway.raid_snapshot_requests == [account_reader.account]
    assert gateway.raid_data_requests == []
    assert gateway.overview_requests == []
    assert gateway.season_requests == [
        (account_reader.account, "guild-7", "1234567", False)
    ]
    assert clock_calls == [query_time]
    assert ranking.scope == "第 234567 季 · LAST_SEASON_RESPONSE"
    assert [(item.nickname, item.total_damage) for item in ranking.participants] == [
        ("member-member-1", 12)
    ]


@pytest.mark.asyncio
async def test_ranking_does_not_fallback_for_nonempty_or_non_offseason_response(tmp_path):
    account_reader = RaidAccountReader()
    payload = {
        "manager_info": {"id": "0"},
        "level_info": [],
        "participate_data": [attack("current", 5)],
    }
    gateway = RaidGateway(raid_data=payload)
    application = RaidApplication(
        account_reader=account_reader,
        gateway=gateway,
        builder=offseason_builder(tmp_path),
        clock=lambda: datetime.fromtimestamp(200, timezone.utc),
        plugin_version="test-version",
    )

    ranking = await application.ranking("qq-123")

    assert [item.nickname for item in ranking.participants] == ["member-current"]
    assert ranking.scope == "CURRENT_RESPONSE"
    assert gateway.raid_snapshot_requests == [account_reader.account]
    assert gateway.overview_requests == []
    assert gateway.season_requests == []


@pytest.mark.asyncio
async def test_ranking_does_not_fallback_for_empty_active_response(tmp_path):
    account_reader = RaidAccountReader()
    gateway = RaidGateway(
        raid_data={
            "manager_info": {
                "id": "1000007",
                "season_end_date": "1970-01-01T00:10:00+00:00",
            },
            "level_info": [],
            "participate_data": [],
        }
    )
    application = RaidApplication(
        account_reader=account_reader,
        gateway=gateway,
        builder=offseason_builder(tmp_path),
        clock=lambda: datetime.fromtimestamp(200, timezone.utc),
        plugin_version="test-version",
    )

    ranking = await application.ranking("qq-123")

    assert ranking.participants == []
    assert ranking.scope == "CURRENT_RESPONSE"
    assert gateway.raid_snapshot_requests == [account_reader.account]
    assert gateway.overview_requests == []
    assert gateway.season_requests == []


@pytest.mark.asyncio
async def test_member_uses_exact_stable_openid_for_historical_response(tmp_path):
    account_reader = RaidAccountReader()
    gateway = RaidGateway(
        raid_data={
            "manager_info": {"id": "0"},
            "level_info": [],
            "participate_data": [],
        },
        season_data={
            "participate_data": [
                attack("stable-openid", 9),
                attack("stable-openid-extra", 100),
            ]
        },
    )
    application = RaidApplication(
        account_reader=account_reader,
        gateway=gateway,
        builder=offseason_builder(tmp_path),
        clock=lambda: datetime.fromtimestamp(200, timezone.utc),
        plugin_version="test-version",
    )

    ranking = await application.member("qq-123")

    assert ranking.scope == "CURRENT_RESPONSE_MEMBER"
    assert [(item.nickname, item.total_damage) for item in ranking.participants] == [
        ("member-stable-openid", 9)
    ]
    assert gateway.season_requests == [
        (account_reader.account, "guild-7", "1234567", False)
    ]
    assert gateway.raid_snapshot_requests == [account_reader.account]
    assert gateway.overview_requests == []


@pytest.mark.asyncio
async def test_member_rejects_missing_stable_openid_before_fetching_attacks():
    account_reader = RaidAccountReader()
    account_reader.account = {"area_id": 81, "game_openid": "  "}
    gateway = RaidGateway()
    application = RaidApplication(
        account_reader=account_reader,
        gateway=gateway,
        builder=UnionRaidBuilder(),
        clock=lambda: datetime.now(timezone.utc),
        plugin_version="test-version",
    )

    with pytest.raises(RaidMemberIdentityUnavailable):
        await application.member("qq-123")

    assert gateway.raid_snapshot_requests == []
    assert gateway.raid_data_requests == []
    assert gateway.overview_requests == []
    assert gateway.season_requests == []


def test_main_raid_entrypoints_delegate_data_work_to_application():
    repository_root = Path(__file__).resolve().parents[1]
    tree = ast.parse(
        (repository_root / "main.py").read_text(encoding="utf-8")
    )
    plugin = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "NikkePlugin"
    )
    raid_methods = {
        node.name: node
        for node in plugin.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in {"union_raid", "union_raid_ranking", "union_raid_my"}
    }
    assert set(raid_methods) == {"union_raid", "union_raid_ranking", "union_raid_my"}
    forbidden_calls = {
        "get_union_raid_data",
        "get_union_raid_overview",
        "get_union_raid_season",
        "build_ranking",
        "build_member_ranking",
        "resolve_raid_state",
    }
    for method in raid_methods.values():
        assert not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in forbidden_calls
            for node in ast.walk(method)
        )
        assert not any(
            isinstance(node, ast.Attribute) and node.attr == "_seasons"
            for node in ast.walk(method)
        )
        assert not any(
            isinstance(node, ast.Dict)
            for node in ast.walk(method)
        )

# SPDX-License-Identifier: GPL-3.0-or-later
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from astrbot_plugin_nikke.main import NikkePlugin, normalize_nikke_prefix
from astrbot_plugin_nikke.features.raid.builder import UnionRaidBuilder
from astrbot_plugin_nikke.features.raid.models import (
    PreviousSeasonSummary,
    RaidState,
    UnionRaidOverviewData,
)
from astrbot_plugin_nikke.ui.payloads.raid_overview import UnionOverviewT2IPayloadBuilder


class UnionRaidStateResolutionTests(unittest.TestCase):
    def setUp(self):
        self.sample_seasons = [
            {
                "id": 1000044,
                "season_start_date": "2026-09-03 20:00:00",
                "season_end_date": "2026-09-09 19:59:59",
                "caculate_date": "2026-09-12 19:59:59",
                "start_ts": 1788436800.0,
                "end_ts": 1788955199.0,
                "caculate_ts": 1789214399.0,
            }
        ]

    def test_resolve_active_state_from_manager_info(self):
        manager = {
            "id": "1000044",
            "season_start_date": "2026-09-03T20:00:00",
            "season_end_date": "2026-09-09T19:59:59",
            "season_rank_calculate_date": "2026-09-12T19:59:59",
        }
        now_ts = datetime.fromisoformat("2026-09-05T12:00:00").timestamp()
        state = UnionRaidBuilder.resolve_raid_state(manager, [], now_ts=now_ts)
        self.assertEqual(state, RaidState.ACTIVE)

    def test_resolve_settlement_state_from_manager_info(self):
        manager = {
            "id": "1000044",
            "season_start_date": "2026-09-03T20:00:00",
            "season_end_date": "2026-09-09T19:59:59",
            "season_rank_calculate_date": "2026-09-12T19:59:59",
        }
        now_ts = datetime.fromisoformat("2026-09-10T12:00:00").timestamp()
        state = UnionRaidBuilder.resolve_raid_state(manager, [], now_ts=now_ts)
        self.assertEqual(state, RaidState.SETTLEMENT)

    def test_resolve_offseason_state_when_manager_id_zero(self):
        manager = {"id": "0"}
        now_ts = 1789300000.0  # after caculate_ts
        state = UnionRaidBuilder.resolve_raid_state(
            manager, [], now_ts=now_ts, seasons=self.sample_seasons
        )
        self.assertEqual(state, RaidState.OFFSEASON)

    def test_resolve_unknown_when_manager_not_dict(self):
        state = UnionRaidBuilder.resolve_raid_state(None, [])
        self.assertEqual(state, RaidState.UNKNOWN)

    def test_build_in_offseason_does_not_generate_placeholder_bosses(self):
        builder = UnionRaidBuilder()
        builder._seasons = self.sample_seasons
        data = builder.build(
            guild_name="TestGuild",
            level_info_payload={"manager_info": {"id": "0"}, "level_info": []},
            fetched_at="2026-09-15 12:00",
            plugin_version="0.2.0",
            now=1789300000.0,
        )
        self.assertEqual(data.raid_state, RaidState.OFFSEASON)
        self.assertEqual(data.bosses, [])
        self.assertIsNotNone(data.previous_season)
        self.assertEqual(data.previous_season.season_id, "1000044")
        self.assertEqual(data.previous_season.season_number, 44)


class T2IOffseasonPayloadTests(unittest.TestCase):
    def test_offseason_payload_has_empty_bosses_and_previous_season(self):
        builder = UnionOverviewT2IPayloadBuilder()
        prev = PreviousSeasonSummary(
            season_id="1000044",
            season_number=44,
            start_at="2026-09-03T20:00:00",
            end_at="2026-09-09T19:59:59",
            settled_at="2026-09-12T19:59:59",
            total_attacks=93,
            total_damage=564066761468,
        )
        data = UnionRaidOverviewData(
            guild_name="吉萝婷魔界粉丝会",
            difficulty=None,
            level=None,
            total_progress=None,
            total_current_hp=None,
            total_max_hp=None,
            bosses=[],
            season_end=None,
            season_start=None,
            fetched_at="2026-09-15 12:00",
            plugin_version="0.2.0",
            raid_state=RaidState.OFFSEASON,
            previous_season=prev,
        )
        payload = builder.build(data)
        self.assertEqual(payload["raid_state"], "OFFSEASON")
        self.assertEqual(payload["bosses"], [])
        self.assertIsNotNone(payload["previous_season"])
        self.assertEqual(payload["previous_season"]["season_name"], "第 44 季")
        self.assertEqual(payload["previous_season"]["total_attacks"], 93)
        self.assertIn("564.07B", payload["previous_season"]["total_damage_formatted"])


class PrefixNormalizationAndCommandTests(unittest.IsolatedAsyncioTestCase):
    def test_normalize_nikke_prefix(self):
        self.assertEqual(normalize_nikke_prefix("#妮姬 突袭"), "/妮姬 突袭")
        self.assertEqual(normalize_nikke_prefix("#妮姬   公告"), "/妮姬   公告")
        self.assertEqual(normalize_nikke_prefix("#nikke raid"), "/nikke raid")
        self.assertEqual(normalize_nikke_prefix("/妮姬 突袭"), "/妮姬 突袭")
        self.assertEqual(normalize_nikke_prefix("普通消息"), "普通消息")

    async def test_announcement_simplification_notice_on_extra_args(self):
        from astrbot_plugin_nikke.application.commands.announcement import AnnouncementCommandHandler

        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.announcement_command_handler = AnnouncementCommandHandler(
            application=None,
            push_enabled=lambda: False,
        )
        event = SimpleNamespace(plain_result=lambda text: text)

        for bad_arg in ("10", "5", "最新", "活动", "语言 ja", "分类 维护"):
            reply = [item async for item in plugin.nikke(event, "公告", bad_arg)]
            self.assertIn("公告命令已简化，请使用：", reply[0])
            self.assertIn("/妮姬 公告", reply[0])

    async def test_hash_prefix_in_nikke_command(self):
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.tower_registry = None
        event = SimpleNamespace(plain_result=lambda text: text)

        called = False
        async def mock_info(ev, name):
            nonlocal called
            called = True
            yield "info called with " + name

        plugin.info = mock_info
        replies = [item async for item in plugin.nikke(event, "#妮姬", "查询", "资料 拉毗")]
        self.assertTrue(called)
        self.assertIn("拉毗", replies[0])

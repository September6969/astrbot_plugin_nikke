# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit and regression tests for Union Raid models, builder, and renderer."""

import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image

from astrbot_plugin_nikke.union_raid_models import BossStatus, RaidBossData, UnionRaidOverviewData
from astrbot_plugin_nikke.union_raid_builder import UnionRaidBuilder
from astrbot_plugin_nikke.union_raid_renderer import UnionRaidRenderer


class UnionRaidBuilderTests(unittest.TestCase):
    def setUp(self):
        self.builder = UnionRaidBuilder()

    def test_hp_semantics_and_status_progression(self):
        payload = {
            "level_info": [
                {
                    "difficulty": 1,
                    "level": 3,
                    "boss_info": [
                        {"boss_id": "101", "name_localkey": "Boss 1", "current_hp": 0, "max_hp": 1000},
                        {"boss_id": "102", "name_localkey": "Boss 2", "current_hp": 500, "max_hp": 1000},
                        {"boss_id": "103", "name_localkey": "Boss 3", "current_hp": 1000, "max_hp": 1000},
                        {"boss_id": "104", "name_localkey": "Boss 4", "current_hp": 1000, "max_hp": 1000},
                    ],
                }
            ],
            "manager_info": {"season_end_date": "2026-09-10"},
        }
        data = self.builder.build(
            guild_name="测试联盟",
            level_info_payload=payload,
            fetched_at="2026-09-05 12:00",
            plugin_version="0.1.8",
        )
        self.assertEqual(data.guild_name, "测试联盟")
        self.assertEqual(data.difficulty, 1)
        self.assertEqual(data.level, 3)
        self.assertEqual(len(data.bosses), 4)

        # Status progression: DEFEATED -> CURRENT -> NEXT -> LOCKED
        b1, b2, b3, b4 = data.bosses
        self.assertEqual(b1.status, BossStatus.DEFEATED)
        self.assertEqual(b1.hp_percent, 0.0)
        self.assertEqual(b1.cleared_percent, 1.0)

        self.assertEqual(b2.status, BossStatus.CURRENT)
        self.assertEqual(b2.hp_percent, 0.5)
        self.assertEqual(b2.cleared_percent, 0.5)

        self.assertEqual(b3.status, BossStatus.NEXT)
        self.assertEqual(b3.hp_percent, 1.0)
        self.assertEqual(b3.cleared_percent, 0.0)

        self.assertEqual(b4.status, BossStatus.LOCKED)
        self.assertEqual(b4.hp_percent, 1.0)
        self.assertEqual(b4.cleared_percent, 0.0)

    def test_weighted_total_progress_differs_from_simple_average(self):
        # Boss 1: max=100, cur=0 (100% cleared)
        # Boss 2: max=900, cur=450 (50% cleared)
        # Weighted cleared = 1 - (450 / 1000) = 55.0%
        # Simple arithmetic average would be (100% + 50%) / 2 = 75.0%
        payload = {
            "level_info": [
                {
                    "difficulty": 2,
                    "level": 1,
                    "boss_info": [
                        {"boss_id": "1", "current_hp": 0, "max_hp": 100},
                        {"boss_id": "2", "current_hp": 450, "max_hp": 900},
                    ],
                }
            ],
            "manager_info": {},
        }
        data = self.builder.build(
            guild_name="加权测试",
            level_info_payload=payload,
            fetched_at="2026-09-05 12:00",
            plugin_version="0.1.8",
        )
        self.assertIsNotNone(data.total_progress)
        self.assertAlmostEqual(data.total_progress, 0.55, places=4)
        self.assertNotAlmostEqual(data.total_progress, 0.75, places=2)
        self.assertEqual(data.total_current_hp, 450)
        self.assertEqual(data.total_max_hp, 1000)

    def test_missing_or_invalid_boss_hp_hides_total_progress(self):
        payload = {
            "level_info": [
                {
                    "difficulty": 1,
                    "level": 1,
                    "boss_info": [
                        {"boss_id": "1", "current_hp": 0, "max_hp": 100},
                        {"boss_id": "2", "current_hp": 0, "max_hp": 0},  # Invalid max_hp
                    ],
                }
            ],
            "manager_info": {},
        }
        data = self.builder.build(
            guild_name="缺失测试",
            level_info_payload=payload,
            fetched_at="2026-09-05 12:00",
            plugin_version="0.1.8",
        )
        self.assertIsNone(data.total_progress)
        self.assertIsNone(data.total_current_hp)
        self.assertIsNone(data.total_max_hp)

    def test_missing_current_hp_is_unknown_and_not_defeated_and_real_zero_is_defeated(self):
        payload = {
            "level_info": [
                {
                    "difficulty": 1,
                    "level": 2,
                    "boss_info": [
                        {"boss_id": "1", "current_hp": 0, "max_hp": 5000},  # Real 0 -> DEFEATED
                        {"boss_id": "2", "current_hp": None, "max_hp": 5000},  # Missing HP -> UNKNOWN, not DEFEATED!
                        {"boss_id": "3", "current_hp": 3000, "max_hp": 5000},
                    ],
                }
            ],
            "manager_info": {},
        }
        data = self.builder.build(
            guild_name="测试血量判别",
            level_info_payload=payload,
            fetched_at="2026-09-05 12:00",
            plugin_version="0.1.8",
        )
        b1, b2, b3 = data.bosses
        # 真实 0 正常判定为 DEFEATED
        self.assertEqual(b1.status, BossStatus.DEFEATED)
        self.assertEqual(b1.current_hp, 0)
        self.assertEqual(b1.hp_percent, 0.0)

        # 未知血量判定为 UNKNOWN，绝不误判为 DEFEATED
        self.assertEqual(b2.status, BossStatus.UNKNOWN)
        self.assertIsNone(b2.current_hp)
        self.assertIsNone(b2.hp_percent)

        # 存在未知血量时隐藏加权总进度
        self.assertIsNone(data.total_progress)

    def test_all_bosses_defeated(self):
        payload = {
            "level_info": [
                {
                    "difficulty": 1,
                    "level": 5,
                    "boss_info": [
                        {"boss_id": "1", "current_hp": 0, "max_hp": 1000},
                        {"boss_id": "2", "current_hp": 0, "max_hp": 1000},
                    ],
                }
            ],
            "manager_info": {},
        }
        data = self.builder.build(
            guild_name="全破联盟",
            level_info_payload=payload,
            fetched_at="2026-09-05 12:00",
            plugin_version="0.1.8",
        )
        self.assertTrue(all(b.status == BossStatus.DEFEATED for b in data.bosses))
        self.assertEqual(data.total_progress, 1.0)

    def test_privacy_no_sensitive_ids_in_dto(self):
        payload = {
            "level_info": [
                {
                    "difficulty": 1,
                    "level": 1,
                    "boss_info": [{"boss_id": "1", "current_hp": 500, "max_hp": 1000}],
                }
            ],
            "manager_info": {},
        }
        data = self.builder.build(
            guild_name="安全联盟",
            level_info_payload=payload,
            fetched_at="2026-09-05 12:00",
            plugin_version="0.1.8",
        )
        forbidden_attrs = ["openid", "member_id", "cookie", "qq", "uid"]
        for attr in forbidden_attrs:
            self.assertFalse(hasattr(data, attr))
            self.assertFalse(hasattr(data.bosses[0], attr))

    def test_real_sanitized_fixture_regression(self):
        fixture_path = Path(__file__).resolve().parent / "fixtures" / "union_raid_overview.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            fixture = json.load(f)

        data = self.builder.build(
            guild_name="真实抓包联盟",
            level_info_payload=fixture.get("data", {}),
            fetched_at="2026-09-05 12:00",
            plugin_version="0.1.8",
        )
        self.assertEqual(data.guild_name, "真实抓包联盟")
        self.assertGreater(len(data.bosses), 0)
        for boss in data.bosses:
            self.assertIn(boss.status, list(BossStatus))


class UnionRaidRendererTests(unittest.TestCase):
    def test_render_raid_overview_outputs_1600px_card(self):
        fonts_dir = Path(__file__).resolve().parents[1] / "fonts"
        with tempfile.TemporaryDirectory() as td:
            renderer = UnionRaidRenderer(td, fonts_dir)
            bosses = [
                RaidBossData(
                    boss_id="101",
                    name="古铁",
                    current_hp=0,
                    max_hp=10000000,
                    hp_percent=0.0,
                    cleared_percent=1.0,
                    status=BossStatus.DEFEATED,
                    elements=["风压", "灼热"],
                ),
                RaidBossData(
                    boss_id="102",
                    name="掘墓",
                    current_hp=6500000,
                    max_hp=10000000,
                    hp_percent=0.65,
                    cleared_percent=0.35,
                    status=BossStatus.CURRENT,
                    elements=["电击"],
                ),
                RaidBossData(
                    boss_id="103",
                    name="铁匠",
                    current_hp=10000000,
                    max_hp=10000000,
                    hp_percent=1.0,
                    cleared_percent=0.0,
                    status=BossStatus.NEXT,
                    elements=["铁甲"],
                ),
                RaidBossData(
                    boss_id="104",
                    name="神罚",
                    current_hp=10000000,
                    max_hp=10000000,
                    hp_percent=1.0,
                    cleared_percent=0.0,
                    status=BossStatus.LOCKED,
                    elements=["水冷"],
                ),
            ]
            data = UnionRaidOverviewData(
                guild_name="方舟先锋突击队",
                difficulty=2,
                level=4,
                total_progress=0.5875,
                total_current_hp=26500000,
                total_max_hp=40000000,
                bosses=bosses,
                season_end="2026-09-15 23:59",
                fetched_at="2026-09-05 12:00",
                plugin_version="0.1.8",
            )
            path = renderer.render_raid_overview(data)
            self.assertTrue(path.endswith(".png"))
            with Image.open(path) as img:
                self.assertEqual(img.size[0], 1600)
                self.assertGreater(img.size[1], 800)

    def test_render_raid_overview_with_unknown_hp_does_not_crash(self):
        fonts_dir = Path(__file__).resolve().parents[1] / "fonts"
        with tempfile.TemporaryDirectory() as td:
            renderer = UnionRaidRenderer(td, fonts_dir)
            bosses = [
                RaidBossData(
                    boss_id="101",
                    name="未知Boss",
                    current_hp=None,
                    max_hp=None,
                    hp_percent=None,
                    cleared_percent=None,
                    status=BossStatus.UNKNOWN,
                    elements=[],
                ),
            ]
            data = UnionRaidOverviewData(
                guild_name="测试联盟",
                difficulty=1,
                level=1,
                total_progress=None,
                total_current_hp=None,
                total_max_hp=None,
                bosses=bosses,
                season_end=None,
                fetched_at="2026-09-05 12:00",
                plugin_version="0.1.8",
            )
            path = renderer.render_raid_overview(data)
            self.assertTrue(path.endswith(".png"))
            with Image.open(path) as img:
                self.assertEqual(img.size[0], 1600)


class UnionRaidRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_chinese_and_legacy_raid_commands_route_correctly(self):
        from astrbot_plugin_nikke.main import NikkePlugin

        plugin = NikkePlugin.__new__(NikkePlugin)
        calls = []

        async def fake_union_raid(event):
            calls.append("union_raid")
            yield "突袭结果"

        plugin.union_raid = fake_union_raid

        class FakeEvent:
            pass

        event = FakeEvent()

        # 1. Direct /妮姬 联盟突袭
        results = [r async for r in plugin.nikke(event, "联盟突袭")]
        self.assertEqual(results, ["突袭结果"])

        # 2. Direct /妮姬 突袭
        results = [r async for r in plugin.nikke(event, "突袭")]
        self.assertEqual(results, ["突袭结果"])

        # 3. Direct /nikke raid
        results = [r async for r in plugin.nikke(event, "raid")]
        self.assertEqual(results, ["突袭结果"])

        # 4. Via query: /妮姬 查询 突袭
        results = [r async for r in plugin.query(event, "突袭")]
        self.assertEqual(results, ["突袭结果"])

        self.assertEqual(len(calls), 4)


if __name__ == "__main__":
    unittest.main()
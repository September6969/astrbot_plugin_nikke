"""Union Raid Increment A 的范围、数值与排名语义回归。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from astrbot_plugin_nikke.raid_participants import build_ranking, format_ranking
from astrbot_plugin_nikke.union_raid_builder import UnionRaidBuilder
from astrbot_plugin_nikke.union_raid_models import RaidResponseCoverage, UnionRaidOverviewData
from astrbot_plugin_nikke.union_raid_renderer import UnionRaidRenderer


def _level(*bosses: dict, difficulty: int = 1, level: int = 1) -> dict:
    return {"difficulty": difficulty, "level": level, "boss_info": list(bosses)}


def _attack(openid: str, damage: int) -> dict:
    return {
        "openid": openid,
        "nickname": "合成成员",
        "boss_id": "synthetic-boss",
        "day": 1,
        "difficulty": 1,
        "level": 1,
        "step": 1,
        "total_damage": damage,
        "is_final_hit": False,
        "squad": [
            {"tid": str(slot), "lv": 100, "combat": 1_000, "slot": slot}
            for slot in range(1, 6)
        ],
    }


class RaidIncrementATests(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = UnionRaidBuilder()

    def test_multiple_level_items_never_selects_first_as_current(self) -> None:
        payload = {
            "level_info": [
                _level({"boss_id": "first", "current_hp": 1, "max_hp": 100}, difficulty=1, level=1),
                _level({"boss_id": "second", "current_hp": 2, "max_hp": 100}, difficulty=2, level=2),
            ]
        }

        data = self.builder.build(
            guild_name="合成联盟",
            level_info_payload=payload,
            fetched_at="2026-09-06 13:30",
            plugin_version="test",
        )

        self.assertEqual(data.response_coverage, RaidResponseCoverage.UNKNOWN_COVERAGE)
        self.assertIsNone(data.difficulty)
        self.assertIsNone(data.level)
        self.assertEqual(data.bosses, [])
        self.assertIsNone(data.total_progress)

    def test_duplicate_boss_records_hide_aggregate_without_dropping_records(self) -> None:
        payload = {
            "level_info": [
                _level(
                    {"boss_id": "duplicate", "current_hp": 50, "max_hp": 100},
                    {"boss_id": "duplicate", "current_hp": 40, "max_hp": 100},
                )
            ]
        }

        data = self.builder.build(
            guild_name="合成联盟",
            level_info_payload=payload,
            fetched_at="2026-09-06 13:30",
            plugin_version="test",
        )

        self.assertEqual(data.response_coverage, RaidResponseCoverage.UNKNOWN_COVERAGE)
        self.assertTrue(data.partial_boss_records)
        self.assertEqual(len(data.bosses), 2)
        self.assertIsNone(data.total_progress)

    def test_bool_float_and_bad_numeric_do_not_become_hp(self) -> None:
        invalid_values = (True, 2.5, "2.5", "bad", [])
        for value in invalid_values:
            with self.subTest(value=value):
                data = self.builder.build(
                    guild_name="合成联盟",
                    level_info_payload={
                        "level_info": [
                            _level({"boss_id": "boss", "current_hp": value, "max_hp": 100})
                        ]
                    },
                    fetched_at="2026-09-06 13:30",
                    plugin_version="test",
                )
                self.assertIsNone(data.bosses[0].current_hp)
                self.assertIsNone(data.bosses[0].hp_percent)
                self.assertIsNone(data.total_progress)

    def test_negative_integer_strings_keep_existing_hp_clamp(self) -> None:
        for value in (-10, "-10"):
            with self.subTest(value=value):
                data = self.builder.build(
                    guild_name="合成联盟",
                    level_info_payload={
                        "level_info": [
                            _level({"boss_id": "boss", "current_hp": value, "max_hp": 100})
                        ]
                    },
                    fetched_at="2026-09-06 13:30",
                    plugin_version="test",
                )
                self.assertEqual(data.bosses[0].current_hp, 0)
                self.assertEqual(data.bosses[0].hp_percent, 0.0)

    def test_bad_level_context_never_becomes_default_or_first_item(self) -> None:
        data = self.builder.build(
            guild_name="合成联盟",
            level_info_payload={
                "level_info": [
                    _level(
                        {"boss_id": "boss", "current_hp": 10, "max_hp": 100},
                        difficulty=True,
                        level=1.5,
                    )
                ],
                "manager_info": [],
            },
            fetched_at="2026-09-06 13:30",
            plugin_version="test",
        )

        self.assertEqual(data.response_coverage, RaidResponseCoverage.CURRENT_RESPONSE)
        self.assertIsNone(data.difficulty)
        self.assertIsNone(data.level)
        self.assertEqual(len(data.bosses), 1)

    def test_negative_level_context_is_unknown_not_zero(self) -> None:
        data = self.builder.build(
            guild_name="合成联盟",
            level_info_payload={
                "level_info": [
                    _level(
                        {"boss_id": "boss", "current_hp": 10, "max_hp": 100},
                        difficulty=-1,
                        level="-2",
                    )
                ]
            },
            fetched_at="2026-09-06 13:30",
            plugin_version="test",
        )

        self.assertIsNone(data.difficulty)
        self.assertIsNone(data.level)

    def test_malformed_level_container_stays_unknown_without_crashing(self) -> None:
        data = self.builder.build(
            guild_name="合成联盟",
            level_info_payload={"level_info": {"boss_info": []}},
            fetched_at="2026-09-06 13:30",
            plugin_version="test",
        )

        self.assertEqual(data.response_coverage, RaidResponseCoverage.UNKNOWN_COVERAGE)
        self.assertEqual(data.bosses, [])
        self.assertIsNone(data.total_progress)

    def test_ranking_calls_rows_returned_records_not_attacks(self) -> None:
        ranking = build_ranking(
            {"participate_data": [_attack("synthetic-openid", 10), _attack("synthetic-openid", 20)]}
        )

        text = format_ranking(ranking)
        self.assertIn("2 条返回记录", text)
        self.assertNotIn("2 刀", text)
        self.assertIn("不代表完整赛季或实际攻击次数", text)

    def test_unknown_coverage_renderer_handles_missing_context(self) -> None:
        data = UnionRaidOverviewData(
            guild_name="合成联盟",
            difficulty=None,
            level=None,
            total_progress=None,
            total_current_hp=None,
            total_max_hp=None,
            bosses=[],
            season_end=None,
            fetched_at="2026-09-06 13:30",
            plugin_version="test",
            response_coverage=RaidResponseCoverage.UNKNOWN_COVERAGE,
        )

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "cards"
            fonts_dir = Path(__file__).resolve().parents[1] / "fonts"
            path = UnionRaidRenderer(output_dir, fonts_dir).render_raid_overview(data)
            with Image.open(path) as image:
                self.assertEqual(image.size[0], 1600)
                self.assertGreater(image.size[1], 400)

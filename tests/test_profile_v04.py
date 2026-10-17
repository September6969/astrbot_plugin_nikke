# SPDX-License-Identifier: GPL-3.0-or-later
"""Profile Dashboard v0.4 单元测试与端到端渲染回归。"""

import unittest

from astrbot_plugin_nikke.features.character.registries.memorial import MemorialCategoryRegistry
from astrbot_plugin_nikke.features.profile.builder import (
    ProfileBuilder,
    format_compact_number,
    _parse_storage_fullness,
    _parse_sim_room_record,
    _parse_currencies,
)
from astrbot_plugin_nikke.features.profile.models import (
    CurrencyItem,
    MemorialCountData,
    ProfileDashboardData,
    RecycleResearchData,
    SimulationRoomDailyRecord,
)
from astrbot_plugin_nikke.features.character.registries.research import research_zh_name


class ProfileV04UnitTests(unittest.TestCase):
    def test_format_compact_number(self):
        self.assertEqual(format_compact_number(0), "0")
        self.assertEqual(format_compact_number(999), "999")
        self.assertEqual(format_compact_number(1000), "1K")
        self.assertEqual(format_compact_number(1500), "1.5K")
        self.assertEqual(format_compact_number(10000), "10K")
        self.assertEqual(format_compact_number(10497), "10.5K")
        self.assertEqual(format_compact_number(26000000), "26M")
        self.assertEqual(format_compact_number(26500000), "26.5M")
        self.assertEqual(format_compact_number(130000000), "130M")
        self.assertEqual(format_compact_number(None), "—")
        self.assertEqual(format_compact_number("invalid"), "—")

    def test_memorial_category_registry(self):
        registry = MemorialCategoryRegistry()
        raw_memorials = [
            MemorialCountData("HandWriting", 94),
            MemorialCountData("CallLog", 39),
            MemorialCountData("Data", 80),
            MemorialCountData("OldTales", 8),
            MemorialCountData("UnbreakableSphere", 4),
        ]
        summary, partial = registry.summarize(raw_memorials, jukebox_count=180)
        self.assertFalse(partial)
        self.assertEqual(
            [(item.display_name, item.count) for item in summary],
            [("手机", 94), ("通话记录", 39), ("数据资料", 92), ("BGM", 180)],
        )

        empty_summary, empty_partial = registry.summarize(None, jukebox_count=None)
        self.assertIsNone(empty_summary)
        self.assertFalse(empty_partial)

        unknown_summary, unknown_partial = registry.summarize(
            [MemorialCountData("Unmapped", 8)], jukebox_count=None
        )
        self.assertIsNone(unknown_summary)
        self.assertTrue(unknown_partial)

    def test_parse_storage_fullness(self):
        self.assertEqual(_parse_storage_fullness(0), 0.0)
        self.assertEqual(_parse_storage_fullness(0.059), 5.9)
        self.assertEqual(_parse_storage_fullness(0.0687727), 6.9)
        self.assertEqual(_parse_storage_fullness(1.0), 100.0)
        self.assertEqual(_parse_storage_fullness(15.5), 15.5)
        self.assertIsNone(_parse_storage_fullness(None))
        self.assertIsNone(_parse_storage_fullness("bad"))

    def test_parse_sim_room_record(self):
        self.assertEqual(_parse_sim_room_record({"chapter": 3, "difficulty": 5}), "5-C")
        self.assertEqual(_parse_sim_room_record({"chapter": 1, "difficulty": 4}), "4-A")
        self.assertEqual(_parse_sim_room_record({"chapter": 2, "difficulty": 5}), "5-B")
        self.assertIsNone(_parse_sim_room_record(None))
        self.assertIsNone(_parse_sim_room_record({}))

    def test_research_zh_name(self):
        self.assertEqual(research_zh_name("General"), "通用研究")
        self.assertEqual(research_zh_name("Attacker"), "火力型")
        self.assertEqual(research_zh_name("Defender"), "防御型")
        self.assertEqual(research_zh_name("Supporter"), "辅助型")
        self.assertEqual(research_zh_name("Elysion"), "极乐净土")
        self.assertEqual(research_zh_name("Missilis"), "米西里斯")
        self.assertEqual(research_zh_name("Tetra"), "泰特拉")
        self.assertEqual(research_zh_name("Pilgrim"), "朝圣者")
        self.assertEqual(research_zh_name("Abnormal"), "反常")
        self.assertEqual(research_zh_name("Unknown"), "Unknown")
        self.assertIsNone(research_zh_name(None))

    def test_parse_currencies(self):
        raw = [
            {"type": 99, "value": 50000},
            {"type": 1000, "value": 130000000},
            {"type": 2000, "value": 26000000},
            {"type": 3000, "value": 10497},
            {"type": 5100, "value": 50},
            {"type": 5200, "value": 120},
            {"type": 11000, "value": 3500},
            {"type": 12000, "value": 800},
        ]
        items = _parse_currencies(raw)
        self.assertEqual(len(items), 8)
        self.assertEqual(items[0].display_name, "珠宝")
        self.assertEqual(items[0].compact_value, "50K")
        self.assertEqual(items[1].display_name, "信用点")
        self.assertEqual(items[1].compact_value, "130M")
        self.assertEqual(items[2].display_name, "战斗数据辑")
        self.assertEqual(items[2].compact_value, "26M")
        self.assertEqual(items[3].display_name, "芯尘")
        self.assertEqual(items[3].compact_value, "10.5K")

# SPDX-License-Identifier: GPL-3.0-or-later
"""Profile Dashboard v0.4 单元测试与端到端渲染回归。"""

import unittest

from astrbot_plugin_nikke.features.character.registries.memorial import MemorialCategoryRegistry
from astrbot_plugin_nikke.features.profile.models import MemorialCountData
from astrbot_plugin_nikke.features.character.registries.research import research_zh_name


class ProfileV04UnitTests(unittest.TestCase):
    # PR-6B G7-misc-dead-b：v0.4 死币种表与旧解析器（与 CurrencyRegistry 矛盾）已删除，
    # 其生产等价路径由 CurrencyRegistry / ProfileBuilder 测试覆盖。

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


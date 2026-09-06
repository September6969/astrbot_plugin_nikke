"""夜间计划中的请求合同与数值边界回归。"""
import unittest
from unittest.mock import AsyncMock

from astrbot_plugin_nikke.client import BlaBlaClient, BlaBlaError
from astrbot_plugin_nikke.union_raid_builder import UnionRaidBuilder


class ContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_campaign_unknown_error_propagates(self):
        client = BlaBlaClient.__new__(BlaBlaClient)
        error = BlaBlaError("未知业务错误", "999999")
        client._community_request = AsyncMock(side_effect=error)
        with self.assertRaises(BlaBlaError) as raised:
            await client.get_main_quest_clear_lineup({}, 1, 1)
        self.assertIs(raised.exception, error)

    def test_hp_clamp_applies_to_dto_and_total(self):
        for raw, expected in [(150, 100), (-10, 0), (25, 25)]:
            with self.subTest(raw=raw):
                data = UnionRaidBuilder().build(
                    guild_name="测试", fetched_at="", plugin_version="test",
                    level_info_payload={"level_info": [{"boss_info": [
                        {"boss_id": "1", "current_hp": raw, "max_hp": 100}
                    ]}]},
                )
                self.assertEqual(data.bosses[0].current_hp, expected)
                self.assertEqual(data.total_current_hp, expected)
                self.assertEqual(data.bosses[0].hp_percent, expected / 100)
                self.assertEqual(data.total_progress, 1 - expected / 100)

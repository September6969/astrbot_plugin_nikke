"""请求来自公开 union 前端，返回结构仍需线上只读验证。"""
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from astrbot_plugin_nikke.client import BlaBlaClient, BlaBlaError


class SeasonTests(IsolatedAsyncioTestCase):
    async def test_verified_request_contract(self):
        client = BlaBlaClient()
        client._post = AsyncMock(return_value={"data": {"participate_data": []}})
        await client.get_union_raid_season({"cookie": "fake", "area_id": "3"}, guild_id="fake-guild", season_id="fake-season")
        client._post.assert_awaited_once_with("/api/game/proxy/Game/GetUnionRaidDataOfGuildSeason", "fake", {
            "area_id": 3, "guild_id": "fake-guild", "season_id": "fake-season"})

    async def test_malformed_response_rejected(self):
        client = BlaBlaClient()
        client._post = AsyncMock(return_value={"data": None})
        with self.assertRaises(BlaBlaError):
            await client.get_union_raid_season({"cookie": "fake", "area_id": "3"}, guild_id="fake", season_id="fake", levels=True)

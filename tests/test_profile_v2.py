"""Profile V2 的 synthetic 合同、请求预算和出图闭环测试。"""

import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from astrbot_plugin_nikke.client import (
    CHARACTERS,
    OUTPOST,
    PROFILE,
    BlaBlaClient,
    BlaBlaError,
    CookieExpired,
)
from astrbot_plugin_nikke.profile_builder import ProfileBuilder
from astrbot_plugin_nikke.profile_card_renderer import ProfileCardRenderer
from astrbot_plugin_nikke.profile_models import (
    MemorialCountData,
    ProfileDashboardData,
    RecycleResearchData,
)
from astrbot_plugin_nikke.main import NikkePlugin


class ProfileV2BuilderTests(unittest.TestCase):
    def build(self, *, basic=None, outpost=None, roster=None):
        return ProfileBuilder().build(
            account={"area_id": "3"},
            basic=basic or {},
            outpost=outpost or {},
            roster=roster,
            fetched_at="2026-09-06 12:00",
            plugin_version="0.1.8",
        )

    def test_bad_numeric_values_are_unknown_without_truncation_or_crash(self):
        data = self.build(
            basic={
                "lv": True,
                "team_combat": 1.5,
                "character_count": "1.5",
            },
            outpost={
                "synchro_level": "  ",
                "outpost_battle_level": "bad",
            },
            roster=[
                {"lv": "200", "combat": 80000},
                {"lv": "bad", "combat": math.nan},
                "not-a-character",
            ],
        )
        self.assertIsNone(data.commander_level)
        self.assertIsNone(data.team_combat)
        self.assertIsNone(data.character_count)
        self.assertIsNone(data.synchro_level)
        self.assertIsNone(data.outpost_battle_level)
        self.assertTrue(data.roster_partial)
        self.assertIsNone(data.max_level)
        self.assertIsNone(data.max_combat)

    def test_partial_research_and_collection_never_claim_complete_totals(self):
        data = self.build(
            outpost={
                "recycle_room_researches": [
                    {"tid": 1101, "lv": 5, "exp": 10},
                    "malformed-entry",
                    {"tid": 1201, "lv": "bad", "exp": 3},
                ],
                "memorial_counts": [
                    {"category": "first", "count": 5},
                    {"category": "second", "count": "bad"},
                ],
            }
        )
        self.assertEqual(len(data.recycle_room_researches), 3)
        self.assertTrue(data.research_partial)
        self.assertIsNone(data.recycle_room_summary)
        self.assertEqual(len(data.memorial_counts), 2)
        self.assertTrue(data.memorial_partial)
        self.assertIsNone(data.memorial_summary)

    def test_partial_roster_does_not_use_filtered_length_as_total(self):
        data = self.build(
            basic={"character_costume_count": 0},
            roster=[{"lv": 200, "combat": 100000}, {}],
        )
        self.assertTrue(data.roster_partial)
        self.assertIsNone(data.character_count)
        self.assertIsNone(data.max_level)
        self.assertIsNone(data.max_combat)
        self.assertEqual(data.character_costume_count, 0)


class ProfileV2RendererTests(unittest.TestCase):
    def renderer(self, directory):
        root = Path(__file__).resolve().parents[1]
        return ProfileCardRenderer(Path(directory), root / "fonts")

    def full_data(self):
        return ProfileDashboardData(
            commander_name="完整资料",
            area_id="3",
            synchro_level=200,
            outpost_battle_level=15,
            normal_campaign="35-1",
            hard_campaign="20-3",
            character_count=120,
            max_level=200,
            max_combat=100000,
            fetched_at="2026-09-06 12:00",
            plugin_version="0.1.8",
            commander_level=250,
            team_combat=123456,
            created_at="2024-01-01",
            character_costume_count=15,
            progress_tribe_tower="300",
            sim_room_overclock_score="99999",
            infra_core_level="3",
            tactic_academy_class="12",
            tactic_academy_lesson="34",
            jukebox_count="42",
            recycle_room_researches=[
                RecycleResearchData("1101", 5, 10, "Attacker", "Class"),
            ],
            memorial_counts=[MemorialCountData("private-category", 7)],
            outpost_available=True,
            roster_available=True,
        )

    def test_profile_sections_have_single_ownership_and_target_order(self):
        with tempfile.TemporaryDirectory() as directory:
            renderer = self.renderer(directory)
            with patch.object(renderer, "_section_panel", wraps=renderer._section_panel) as panel:
                path = renderer.render_profile(self.full_data())
            titles = [call.args[2] for call in panel.call_args_list]
            self.assertEqual(
                titles,
                [
                    "BASIC INFO / 基本信息",
                    "CAMPAIGN / 主线进度",
                    "OUTPOST / 前哨基地",
                    "ROSTER / 妮姬统计",
                    "COLLECTION / 收藏",
                    "RESEARCH / 研究",
                    "MORE / 更多数据",
                ],
            )
            with Image.open(path) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.width, 1200)

            with patch.object(renderer, "_text", wraps=renderer._text) as text:
                renderer.render_profile(self.full_data())
            rendered = str(text.call_args_list)
            self.assertIn("点唱机收集", rendered)
            self.assertNotIn("回收室研究", rendered)
            self.assertNotIn("收藏记录", rendered)
            self.assertNotIn("private-category", rendered)

    def test_failure_and_partial_statuses_are_visible_without_fake_zeroes(self):
        data = self.full_data()
        data.synchro_level = None
        data.outpost_battle_level = None
        data.infra_core_level = None
        data.tactic_academy_class = None
        data.tactic_academy_lesson = None
        data.jukebox_count = None
        data.outpost_available = False
        data.roster_available = False
        data.roster_partial = True
        data.max_level = None
        data.max_combat = None
        data.research_partial = True
        data.memorial_partial = True
        with tempfile.TemporaryDirectory() as directory:
            renderer = self.renderer(directory)
            with patch.object(renderer, "_text", wraps=renderer._text) as text:
                path = renderer.render_profile(data)
            rendered = str(text.call_args_list)
            self.assertIn("前哨资料", rendered)
            self.assertIn("获取失败", rendered)
            self.assertIn("花名册状态", rendered)
            self.assertNotIn("等级合计", rendered)
            self.assertNotIn("收藏记录", rendered)
            with Image.open(path) as image:
                self.assertGreater(image.height, 200)


class ProfileV2ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_dashboard_uses_three_profile_requests_and_preserves_partial_status(self):
        calls = []

        class SyntheticClient(BlaBlaClient):
            async def _post(self, path, cookie, payload):
                calls.append((path, payload))
                if path == PROFILE:
                    return {
                        "data": {
                            "basic_info": {
                                "nickname": "合成账号",
                                "character_count": 120,
                                "character_costume_count": 15,
                            }
                        }
                    }
                if path == OUTPOST:
                    raise BlaBlaError("synthetic outpost failure", endpoint="GetUserProfileOutpostInfo")
                if path == CHARACTERS:
                    return {"data": {"characters": []}}
                raise AssertionError(path)

        result = await SyntheticClient().get_profile_dashboard(
            {"cookie": "synthetic-cookie", "area_id": "3", "game_openid": "synthetic-openid"}
        )
        self.assertEqual([path for path, _ in calls].count(PROFILE), 1)
        self.assertEqual([path for path, _ in calls].count(OUTPOST), 1)
        self.assertEqual([path for path, _ in calls].count(CHARACTERS), 1)
        self.assertEqual(result["roster"], [])
        self.assertFalse(result["outpost_available"])
        self.assertTrue(result["roster_available"])

        with tempfile.TemporaryDirectory() as directory:
            dashboard = ProfileBuilder().build(
                account={"area_id": "3"},
                basic=result["basic"],
                outpost=result["outpost"],
                roster=result["roster"],
                outpost_available=result["outpost_available"],
                roster_available=result["roster_available"],
                fetched_at="2026-09-06 12:00",
                plugin_version="0.1.8",
            )
            path = ProfileCardRenderer(Path(directory), Path(__file__).resolve().parents[1] / "fonts").render_profile(dashboard)
            with Image.open(path) as image:
                self.assertEqual(image.format, "PNG")

    async def test_optional_cookie_expired_is_not_downgraded_to_empty_profile(self):
        class ExpiredClient(BlaBlaClient):
            async def _post(self, path, cookie, payload):
                if path == PROFILE:
                    return {"data": {"basic_info": {"nickname": "合成账号"}}}
                raise CookieExpired("synthetic cookie expired", endpoint=path.rsplit("/", 1)[-1])

        with self.assertRaises(CookieExpired):
            await ExpiredClient().get_profile_dashboard(
                {"cookie": "synthetic-cookie", "area_id": "3", "game_openid": "synthetic-openid"}
            )

    async def test_me_command_uses_real_client_builder_renderer_chain(self):
        calls = []

        class SyntheticClient(BlaBlaClient):
            async def _post(self, path, cookie, payload):
                calls.append(path)
                if path == PROFILE:
                    return {"data": {"basic_info": {"nickname": "命令链合成账号", "character_count": 2}}}
                if path == OUTPOST:
                    return {"data": {"outpost_info": {"synchro_level": 200}}}
                if path == CHARACTERS:
                    return {"data": {"characters": [{"lv": 200, "combat": 80000}, {"lv": 180, "combat": 70000}]}}
                raise AssertionError(path)

        class Store:
            @staticmethod
            def get_account(qq_id):
                return {
                    "qq_id": qq_id,
                    "cookie": "synthetic-cookie",
                    "area_id": "3",
                    "game_openid": "synthetic-openid",
                }

        class Event:
            @staticmethod
            def get_sender_id():
                return "synthetic-qq"

            @staticmethod
            def image_result(path):
                return path

            @staticmethod
            def plain_result(text):
                return text

        with tempfile.TemporaryDirectory() as directory:
            plugin = NikkePlugin.__new__(NikkePlugin)
            plugin.store = Store()
            plugin.client = SyntheticClient()
            plugin.profile_builder = ProfileBuilder()
            plugin.profile_renderer = ProfileCardRenderer(
                Path(directory), Path(__file__).resolve().parents[1] / "fonts"
            )
            plugin.feedback_manager = None
            results = [item async for item in plugin.me(Event())]
            self.assertEqual(len(results), 1)
            with Image.open(results[0]) as image:
                self.assertEqual(image.format, "PNG")
            self.assertEqual(calls.count(PROFILE), 1)
            self.assertEqual(calls.count(OUTPOST), 1)
            self.assertEqual(calls.count(CHARACTERS), 1)

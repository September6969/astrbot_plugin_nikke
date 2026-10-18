"""Profile V2 的 synthetic 合同、请求预算和出图闭环测试。"""

from plugin_fixtures import make_plugin_shell
import math
import unittest
from datetime import datetime, timezone


from astrbot_plugin_nikke.adapters.astrbot.command_adapter import AstrBotCommandAdapter
from astrbot_plugin_nikke.application.commands.profile import ProfileCommandHandler
from astrbot_plugin_nikke.integrations.blablalink.client import (
    CHARACTERS,
    OUTPOST,
    PROFILE,
    BlaBlaClient,
    BlaBlaError,
    CookieExpired,
)
from astrbot_plugin_nikke.features.profile.builder import ProfileBuilder
from astrbot_plugin_nikke.features.profile.application import ProfileApplication
from astrbot_plugin_nikke.features.profile.models import (
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
        from astrbot_plugin_nikke.ui.payloads.profile import ProfileT2IPayloadBuilder
        payload = ProfileT2IPayloadBuilder().build(dashboard)
        self.assertEqual(payload["commander"], "合成账号")
        self.assertEqual(payload["outpost_state"], "UNAVAILABLE")

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

    async def test_me_command_uses_profile_application_handler_chain(self):
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

        plugin = make_plugin_shell()
        plugin.services.store = Store()
        plugin.services.profile_application = ProfileApplication(
            gateway=SyntheticClient(),
            builder=ProfileBuilder(),
            clock=lambda: datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc),
            plugin_version="test-version",
        )
        plugin.adapters.command = AstrBotCommandAdapter()
        plugin.handlers.profile = ProfileCommandHandler(
            account_reader=plugin.services.store,
            application=plugin.services.profile_application,
            present=plugin.presentation.render_profile,
        )
        plugin.services.feedback_manager = None
        results = [item async for item in plugin.me(Event())]
        self.assertEqual(len(results), 1)
        self.assertIn("命令链合成账号", str(results[0]))
        self.assertEqual(calls.count(PROFILE), 1)
        self.assertEqual(calls.count(OUTPOST), 1)
        self.assertEqual(calls.count(CHARACTERS), 1)

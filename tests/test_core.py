# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from astrbot_plugin_nikke.client import (
    BlaBlaClient,
    BlaBlaError,
    CdkRedemptionResult,
    CookieExpired,
)
from astrbot_plugin_nikke.renderer import CardRenderer
from astrbot_plugin_nikke.storage import NikkeStore
from astrbot_plugin_nikke.web_service import BindingWebService
from astrbot_plugin_nikke.web_service import public_error


VALID_COOKIE = "game_token=secret-token; game_uid=12345; game_openid=67890"


def assert_fixture_sanitized(test: unittest.TestCase, value):
    if isinstance(value, dict):
        for item in value.values():
            assert_fixture_sanitized(test, item)
    elif isinstance(value, list):
        for item in value:
            assert_fixture_sanitized(test, item)
    elif isinstance(value, str):
        test.assertIn(value, {"", "[已脱敏]"})


class BindingApiTests(unittest.IsolatedAsyncioTestCase):
    def test_public_error_contains_endpoint_and_masks_credentials(self):
        error = BlaBlaError("token=abc user@example.com", "1300001", "CheckLogin")
        result = public_error(error)
        self.assertIn("[CheckLogin/1300001]", result)
        self.assertNotIn("abc", result)
        self.assertNotIn("user@example.com", result)

    async def test_api_rejects_untrusted_browser_origin(self):
        with tempfile.TemporaryDirectory() as td:
            store = NikkeStore(td)
            service = BindingWebService(store, object(), Path(td) / "extension.zip")
            from aiohttp.test_utils import TestClient, TestServer

            client = TestClient(TestServer(service.app()))
            await client.start_server()
            try:
                response = await client.get(
                    "/api/bind/status?token=" + "a" * 40,
                    headers={"Origin": "https://attacker.example"},
                )
                self.assertEqual(response.status, 403)
                preflight = await client.options(
                    "/api/bind/cookies",
                    headers={"Origin": "chrome-extension://abcdefghijklmnopabcdefghijklmnop"},
                )
                self.assertEqual(preflight.status, 204)
                self.assertEqual(
                    preflight.headers.get("Access-Control-Allow-Origin"),
                    "chrome-extension://abcdefghijklmnopabcdefghijklmnop",
                )
            finally:
                await client.close()

    async def test_session_endpoint_requires_service_key(self):
        with tempfile.TemporaryDirectory() as td:
            store = NikkeStore(td)
            service = BindingWebService(store, object(), Path(td) / "extension.zip", "service-secret")
            from aiohttp.test_utils import TestClient, TestServer

            client = TestClient(TestServer(service.app()))
            await client.start_server()
            try:
                denied = await client.post("/api/bind/session", json={"qq_id": "123456"})
                self.assertEqual(denied.status, 401)
                created = await client.post(
                    "/api/bind/session",
                    json={"qq_id": "123456"},
                    headers={"Authorization": "Bearer service-secret"},
                )
                self.assertEqual(created.status, 201)
                payload = await created.json()
                self.assertTrue(payload["ok"])
                self.assertIsNotNone(store.get_bind_session(payload["token"]))
            finally:
                await client.close()

    async def test_cookie_submission_keeps_only_blablalink_site_cookies(self):
        class CaptureClient:
            def __init__(self):
                self.cookie = ""

            async def validate_cookie(self, cookie):
                self.cookie = cookie
                from astrbot_plugin_nikke.client import ValidationResult
                return ValidationResult(True, "12345", "67890", "角色", "昵称", "3")

        with tempfile.TemporaryDirectory() as td:
            store = NikkeStore(td)
            store.create_bind_session("a" * 40, "123456", 600)
            capture = CaptureClient()
            service = BindingWebService(store, capture, Path(td) / "extension.zip")
            from aiohttp.test_utils import TestClient, TestServer

            client = TestClient(TestServer(service.app()))
            await client.start_server()
            try:
                response = await client.post(
                    "/api/bind/cookies",
                    json={
                        "token": "a" * 40,
                        "cookies": [
                            {"name": "game_token", "value": "token", "domain": ".blablalink.com"},
                            {"name": "game_uid", "value": "12345", "domain": ".blablalink.com"},
                            {"name": "game_openid", "value": "67890", "domain": ".blablalink.com"},
                            {"name": "site_session", "value": "needed", "domain": "www.blablalink.com"},
                            {"name": "foreign", "value": "secret", "domain": ".example.com"},
                        ],
                        "x_common_params": json.dumps({"openid": "runtime-openid", "language": "zh-TW"}),
                        "user_agent": "Test Browser",
                    },
                )
                self.assertEqual(response.status, 200)
                self.assertIn("site_session=needed", capture.cookie)
                self.assertNotIn("foreign=secret", capture.cookie)
            finally:
                await client.close()


class FakeClient(BlaBlaClient):
    def __init__(self, responses):
        super().__init__(5)
        self.responses = responses
        self.calls = []

    async def _post(self, path, cookie, payload):
        self.calls.append((path, cookie, payload))
        value = self.responses[path]
        if isinstance(value, Exception):
            raise value
        return value


class OpenIdFallbackClient(BlaBlaClient):
    def __init__(self):
        super().__init__(5)
        self.payloads = []

    async def _post(self, path, cookie, payload):
        self.payloads.append((path, payload))
        if path == "/api/ugc/direct/standalonesite/User/GetUserGamePlayerInfo":
            if payload.get("intl_openid"):
                return {"code": 0, "data": {"area_id": 3, "role_name": "指挥官"}}
            raise BlaBlaError("MetaData no user account", "1300001")
        if path == "/api/game/proxy/Game/GetUserProfileBasicInfo":
            return {"code": 0, "data": {"basic_info": {"nickname": "测试账号"}}}
        raise AssertionError(path)


class CanonicalOpenIdClient(BlaBlaClient):
    def __init__(self):
        super().__init__(5)

    async def _post(self, path, cookie, payload):
        if path == "/api/ugc/direct/standalonesite/User/GetUserGamePlayerInfo":
            if payload.get("intl_openid") == "3-67890":
                return {"code": 0, "data": {"area_id": 3, "role_name": "指挥官"}}
            raise BlaBlaError("MetaData no user account", "1300001")
        if path == "/api/ugc/proxy/standalonesite/User/GetUserInfoNew":
            return {"code": 0, "data": {"info": {"intl_openid": "3-67890"}}}
        if path == "/api/ugc/direct/standalonesite/User/GetUserPrivacySetting":
            return {"code": 0, "data": {}}
        if path == "/api/game/proxy/Game/GetUserProfileBasicInfo":
            return {"code": 0, "data": {"basic_info": {"nickname": "正式账号"}}}
        raise AssertionError(path)


class CommunitySigninClient(BlaBlaClient):
    def __init__(self, completed: bool = False):
        super().__init__(5)
        self.completed = completed
        self.calls = []

    async def _community_request(self, method, path, account, *, params=None, payload=None):
        self.calls.append((method, path, payload))
        if method == "POST":
            self.completed = True
            return {"code": 0, "msg": "ok", "data": {}}
        return {
            "code": 0,
            "msg": "ok",
            "data": {
                "tasks": [{
                    "task_name": "每日簽到",
                    "task_id": "daily-task",
                    "reward_infos": [{"is_completed": self.completed}],
                }]
            },
        }


class CdkClient(BlaBlaClient):
    def __init__(self, result=None):
        super().__init__(5)
        self.result = result
        self.calls = []

    async def _community_request(self, method, path, account, *, params=None, payload=None):
        self.calls.append((method, path, payload))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result or {"code": 0, "msg": "ok", "data": {}}


class StoreTests(unittest.TestCase):
    def test_single_use_and_encryption(self):
        with tempfile.TemporaryDirectory() as td:
            store = NikkeStore(td)
            store.create_bind_session("a" * 40, "10001", 600)
            qq_id = store.consume_bind_session(
                "a" * 40, VALID_COOKIE, "12345", "67890", "丽塔", "丽塔", "3"
            )
            self.assertEqual(qq_id, "10001")
            self.assertEqual(store.get_account("10001")["cookie"], VALID_COOKIE)
            conn = sqlite3.connect(Path(td) / "nikke.sqlite3")
            try:
                encrypted = conn.execute("SELECT cookie_cipher FROM accounts").fetchone()[0]
            finally:
                conn.close()
            self.assertNotIn(b"secret-token", encrypted)
            with self.assertRaises(ValueError):
                store.consume_bind_session(
                    "a" * 40, VALID_COOKIE, "12345", "67890", "丽塔", "丽塔", "3"
                )

    def test_expired_session_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = NikkeStore(td)
            store.create_bind_session("b" * 40, "10001", -1)
            with self.assertRaises(ValueError):
                store.consume_bind_session(
                    "b" * 40, VALID_COOKIE, "12345", "67890", "", "", "3"
                )

    def test_idempotent_run(self):
        with tempfile.TemporaryDirectory() as td:
            store = NikkeStore(td)
            self.assertTrue(store.claim_run("2026-09-05:1:daily", "1", "daily"))
            self.assertFalse(store.claim_run("2026-09-05:1:daily", "1", "daily"))

    def test_failed_run_can_be_retried_without_duplication(self):
        with tempfile.TemporaryDirectory() as td:
            store = NikkeStore(td)
            key = "cdk:1:digest"
            self.assertTrue(store.claim_run(key, "1", "cdk"))
            store.finish_run(key, "failed", "请求失败")
            self.assertTrue(store.retry_run(key, {"failed"}, stale_after=120))
            self.assertEqual(store.get_run(key)["status"], "running")
            self.assertFalse(store.retry_run(key, {"failed"}, stale_after=120))


class ClientTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _community_account():
        return {
            "cookie": VALID_COOKIE + "; game_gameid=3",
            "x_common_params": json.dumps({"openid": "runtime", "intl_game_id": "3", "language": "zh-TW"}),
            "user_agent": "Test Browser",
        }

    async def test_daily_signin_checks_before_and_after_write(self):
        client = CommunitySigninClient()
        result = await client.perform_daily_signin(self._community_account())
        self.assertEqual(result, "签到成功")
        self.assertEqual([call[0] for call in client.calls], ["GET", "POST", "GET"])

    async def test_daily_signin_skips_completed_task(self):
        client = CommunitySigninClient(completed=True)
        result = await client.perform_daily_signin(self._community_account())
        self.assertEqual(result, "今日已经签到")
        self.assertEqual([call[0] for call in client.calls], ["GET"])

    async def test_cdk_redeem_uses_official_endpoint_once(self):
        from astrbot_plugin_nikke.client import CDK_REDEEM

        client = CdkClient()
        result = await client.redeem_cdk(self._community_account(), "TESTCODE")
        self.assertTrue(result.success)
        self.assertEqual(client.calls, [("POST", CDK_REDEEM, {"cdkey": "TESTCODE"})])

    async def test_cdk_terminal_errors_are_localized(self):
        cases = {
            "1302009": "次数已达上限",
            "1302015": "无效或已过期",
            "1302016": "已经兑换过",
            "1302017": "全服可用次数已耗尽",
        }
        for code, message in cases.items():
            with self.subTest(code=code):
                client = CdkClient(BlaBlaError("upstream", code, "RecordCdkRedemption"))
                result = await client.redeem_cdk(self._community_account(), "TESTCODE")
                self.assertFalse(result.success)
                self.assertTrue(result.terminal)
                self.assertIn(message, result.message)

    async def test_cdk_cookie_expired_is_preserved(self):
        client = CdkClient(BlaBlaError("expired", "300001", "RecordCdkRedemption"))
        with self.assertRaises(CookieExpired):
            await client.redeem_cdk(self._community_account(), "TESTCODE")

    async def test_cookie_expired_is_preserved(self):
        class ExpiredClient(BlaBlaClient):
            async def _post(self, path, cookie, payload):
                from astrbot_plugin_nikke.client import CookieExpired
                raise CookieExpired("expired", "401", path.rsplit("/", 1)[-1])

        from astrbot_plugin_nikke.client import CookieExpired
        with self.assertRaises(CookieExpired):
            await ExpiredClient(5).validate_cookie(VALID_COOKIE)

    async def test_1300015_retries_are_bounded(self):
        class RetryClient(BlaBlaClient):
            def __init__(self):
                super().__init__(5)
                self.count = 0

            async def _post(self, path, cookie, payload):
                from astrbot_plugin_nikke.client import PLAYER_INFO, PROFILE
                if path == PLAYER_INFO:
                    self.count += 1
                    if self.count < 3:
                        raise BlaBlaError("system", "1300015", "GetUserGamePlayerInfo")
                    return {"code": 0, "data": {"area_id": 3, "role_name": "角色"}}
                if path == PROFILE:
                    return {"code": 0, "data": {"basic_info": {}}}
                raise AssertionError(path)

        from unittest.mock import AsyncMock, patch
        client = RetryClient()
        with patch("astrbot_plugin_nikke.client.asyncio.sleep", new=AsyncMock()):
            result = await client.validate_cookie(VALID_COOKIE)
        self.assertEqual(result.area_id, "3")
        self.assertEqual(client.count, 3)

    async def test_two_accounts_keep_cookie_isolated(self):
        class IsolationClient(BlaBlaClient):
            async def _post(self, path, cookie, payload):
                from astrbot_plugin_nikke.client import PLAYER_INFO, PROFILE
                uid = self.parse_cookie(cookie)["game_uid"]
                if path == PLAYER_INFO:
                    await asyncio.sleep(0)
                    return {"code": 0, "data": {"area_id": int(uid), "role_name": uid}}
                if path == PROFILE:
                    return {"code": 0, "data": {"basic_info": {"nickname": uid}}}
                raise AssertionError(path)

        first = "game_token=a; game_uid=1; game_openid=11"
        second = "game_token=b; game_uid=2; game_openid=22"
        results = await asyncio.gather(
            IsolationClient(5).validate_cookie(first),
            IsolationClient(5).validate_cookie(second),
        )
        self.assertEqual([item.nickname for item in results], ["1", "2"])

    async def test_player_lookup_falls_back_to_game_openid(self):
        client = OpenIdFallbackClient()
        result = await client.validate_cookie(VALID_COOKIE)
        self.assertEqual(result.area_id, "3")
        self.assertEqual(result.nickname, "测试账号")
        self.assertIn(
            ("/api/ugc/direct/standalonesite/User/GetUserGamePlayerInfo", {"intl_openid": "67890"}),
            client.payloads,
        )

    async def test_player_lookup_uses_canonical_openid(self):
        client = CanonicalOpenIdClient()
        result = await client.validate_cookie(VALID_COOKIE)
        self.assertEqual(result.area_id, "3")
        self.assertEqual(result.game_openid, "3-67890")
        self.assertEqual(result.nickname, "正式账号")

    async def test_validation_and_profile(self):
        from astrbot_plugin_nikke.client import CHECK_LOGIN, PLAYER_INFO, PROFILE

        client = FakeClient(
            {
                PLAYER_INFO: {"code": 0, "data": {"area_id": 3, "role_name": "旧名称"}},
                PROFILE: {"code": 0, "data": {"basic_info": {"nickname": "新名称"}}},
                CHECK_LOGIN: {"code": 0, "data": {}},
            }
        )
        result = await client.validate_cookie(VALID_COOKIE)
        self.assertTrue(result.valid)
        self.assertEqual(result.nickname, "新名称")
        self.assertEqual(result.area_id, "3")
        self.assertTrue(all(call[1] == VALID_COOKIE for call in client.calls))

    async def test_missing_required_cookie(self):
        client = FakeClient({})
        with self.assertRaises(BlaBlaError):
            await client.validate_cookie("game_token=x; game_uid=1")

    def test_ael_formula(self):
        value = BlaBlaClient.calculate_ael({"grade": 3, "core": 2, "effects": []})
        self.assertEqual(value, round(1.1 * 1.13, 4))

    def test_ael_uses_attack_and_element_effects(self):
        value = BlaBlaClient.calculate_ael(
            {
                "grade": 0,
                "core": 0,
                "equipment_effects": [
                    {"function_type": "StatAtk", "function_value": 1190},
                    {"function_type": "IncElementDmg", "function_value": 2300},
                ],
            }
        )
        self.assertEqual(value, round((1 + 0.9 * 0.119) * (1 + 0.23 + 0.10), 4))


class RendererTests(unittest.TestCase):
    def test_summary_card(self):
        with tempfile.TemporaryDirectory() as td:
            renderer = CardRenderer(td, td)
            path = renderer.render_summary([(f"用户{i}", "签到成功") for i in range(25)])
            self.assertTrue(Path(path).exists())
            self.assertGreater(Path(path).stat().st_size, 1000)


class ExtensionTests(unittest.TestCase):
    def test_extension_permissions_are_scoped(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "extension" / "manifest.json").read_text(encoding="utf-8"))
        hosts = manifest["host_permissions"]
        self.assertNotIn("<all_urls>", hosts)
        self.assertEqual(set(manifest["permissions"]), {"cookies", "tabs", "storage", "webRequest"})
        background = (root / "extension" / "background.js").read_text(encoding="utf-8")
        self.assertIn("x-common-params", background)
        self.assertIn("https://*.blablalink.com/*", background)
        self.assertNotIn("requestBody", background)

        popup = (root / "extension" / "popup.js").read_text(encoding="utf-8")
        self.assertIn("buildFallbackContext", popup)
        self.assertIn("game_openid", popup)
        self.assertNotIn("requestBody", popup)
        self.assertIn("url.password", popup)


class ProfileFixtureTests(unittest.TestCase):
    def test_profile_fixtures_keep_confirmed_keys_and_are_fully_sanitized(self):
        root = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
        profile = json.loads((root / "profile_basic_full_keys.json").read_text(encoding="utf-8"))
        outpost = json.loads((root / "outpost_full_keys.json").read_text(encoding="utf-8"))
        basic = profile["data"]["basic_info"]
        outpost_info = outpost["data"]["outpost_info"]

        self.assertTrue({"lv", "icon_id", "created_at", "team_combat", "progress_tribe_tower"} <= set(basic))
        self.assertTrue({"infra_core_level", "recycle_room_researches", "memorial_counts"} <= set(outpost_info))

        def assert_sanitized(value):
            if isinstance(value, dict):
                for item in value.values():
                    assert_sanitized(item)
            elif isinstance(value, list):
                for item in value:
                    assert_sanitized(item)
            elif isinstance(value, str):
                self.assertIn(value, {"", "[已脱敏]"})

        assert_sanitized(profile["data"])
        assert_sanitized(outpost["data"])


class HelpTests(unittest.TestCase):
    def test_help_lists_six_chinese_entries_and_english_aliases(self):
        from astrbot_plugin_nikke.main import NikkePlugin

        text = NikkePlugin._help_text()
        self.assertIn("六个入口：帮助｜账号｜我的｜查询｜签到｜兑换", text)
        self.assertIn("/nikke bind", text)
        self.assertIn("/nikke roster", text)
        self.assertIn("/nikke cdk", text)
        self.assertNotIn("/nikke export", text)
        self.assertNotIn("【管理员】", text)

    def test_help_category_alias(self):
        from astrbot_plugin_nikke.main import NikkePlugin

        text = NikkePlugin._help_text("account")
        self.assertIn("【账号】", text)
        self.assertNotIn("【管理员】", text)

    def test_admin_help_is_permission_scoped(self):
        from astrbot_plugin_nikke.main import NikkePlugin

        self.assertEqual(NikkePlugin._help_text("管理"), "管理指令仅对管理员显示。")
        self.assertIn("【管理员】", NikkePlugin._help_text("管理", True))

    def test_removed_placeholders_are_not_registered(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "main.py").read_text(encoding="utf-8")
        self.assertIn('@filter.command("妮姬", alias={"nikke"})', source)
        for command in ("skill", "advise", "stage", "tower", "cube", "collection", "image", "export"):
            self.assertNotIn(f'command("nikke {command}")', source)


class UnionRaidFixtureTests(unittest.TestCase):
    def test_four_confirmed_union_raid_fixtures_are_sanitized(self):
        fixture_dir = Path(__file__).resolve().parent / "fixtures"
        expected = {
            "union_raid_overview.json": ("GetUnionRaidLevelInfo", "level_info"),
            "union_raid_boss_list.json": ("GetUnionRaidLevelInfo", "boss_info"),
            "union_raid_ranking.json": ("GetUnionRaidData", "participate_data"),
            "union_raid_my_data.json": ("GetUnionRaidData", "participate_data"),
        }
        for name, (endpoint, data_key) in expected.items():
            content = json.loads((fixture_dir / name).read_text(encoding="utf-8"))
            self.assertEqual(content["method"], "POST")
            self.assertTrue(content["endpoint"].endswith(endpoint))
            self.assertEqual(
                content["request_keys"],
                ["guild_id", "intl_open_id", "nikke_area_id"],
            )
            self.assertIn(data_key, content["data"])
            assert_fixture_sanitized(self, content["data"])

    def test_union_raid_capture_has_confirmed_boss_and_account_rows(self):
        fixture_dir = Path(__file__).resolve().parent / "fixtures"
        overview = json.loads(
            (fixture_dir / "union_raid_overview.json").read_text(encoding="utf-8")
        )
        my_data = json.loads(
            (fixture_dir / "union_raid_my_data.json").read_text(encoding="utf-8")
        )
        boss_list = json.loads(
            (fixture_dir / "union_raid_boss_list.json").read_text(encoding="utf-8")
        )
        self.assertTrue(overview["data"]["level_info"])
        self.assertTrue(overview["data"]["level_info"][0]["boss_info"])
        self.assertTrue(boss_list["data"]["boss_info"])
        self.assertTrue(my_data["data"]["participate_data"])


class CommandRoutingTests(unittest.IsolatedAsyncioTestCase):
    def test_profile_rows_use_confirmed_optional_fields(self):
        from astrbot_plugin_nikke.main import NikkePlugin

        rows = dict(
            NikkePlugin._profile_rows(
                {"area_id": "3", "nickname": "测试"},
                {
                    "nickname": "测试",
                    "lv": 99,
                    "team_combat": 1234567,
                    "icon_id": 42,
                    "created_at": "2024-01-01",
                    "character_count": 80,
                    "character_costume_count": 12,
                    "progress_normal_campaign": 100,
                    "progress_hard_campaign": 50,
                    "progress_tribe_tower": 200,
                    "sim_room_overclock_current_sub_season_high_score": 31,
                },
                {
                    "synchro_level": 300,
                    "outpost_battle_level": 250,
                    "infra_core_level": 20,
                    "tactic_academy_class": 9,
                    "tactic_academy_lesson": 3,
                    "jukebox_count": 25,
                    "recycle_room_researches": [{"lv": 10}, {"lv": 20}],
                    "memorial_counts": [{"count": 4}, {"count": 6}],
                },
            )
        )
        self.assertEqual(rows["指挥官等级"], "99")
        self.assertEqual(rows["部队总战力"], "1,234,567")
        self.assertEqual(rows["回收室研究"], "2 项 · 等级合计 30")
        self.assertEqual(rows["收藏记录"], "10")

    async def test_chinese_and_legacy_commands_share_one_root_router(self):
        from astrbot_plugin_nikke.main import NikkePlugin

        plugin = NikkePlugin.__new__(NikkePlugin)
        calls = []

        async def account(event, action="", value=""):
            calls.append(("account", action, value))
            yield "账号结果"

        async def roster(event):
            calls.append(("roster",))
            yield "练度结果"

        plugin.account = account
        plugin.roster = roster
        event = object()

        chinese = [item async for item in plugin.nikke(event, "账号", "绑定", "")]
        legacy = [item async for item in plugin.nikke(event, "roster", "", "")]
        self.assertEqual(chinese, ["账号结果"])
        self.assertEqual(legacy, ["练度结果"])
        self.assertEqual(calls, [("account", "绑定", ""), ("roster",)])

    async def test_character_query_requires_unique_match(self):
        from astrbot_plugin_nikke.main import NikkePlugin

        class Event:
            def get_sender_id(self):
                return "10001"

            def plain_result(self, text):
                return text

        class Store:
            def get_account(self, qq_id):
                return {"qq_id": qq_id, "cookie": VALID_COOKIE}

        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.store = Store()
        plugin._directory = [
            {"name_code": 1, "name_cn": "爱丽丝", "name_en": "Alice"},
            {"name_code": 2, "name_cn": "爱丽丝：仙境兔女郎", "name_en": "Alice: Wonderland Bunny"},
        ]
        result = [item async for item in plugin.character(Event(), "丽丝")]
        self.assertEqual(len(result), 1)
        self.assertIn("找到多个角色", result[0])
        self.assertIn("爱丽丝：仙境兔女郎", result[0])

    async def test_character_query_rejects_unowned_character(self):
        from astrbot_plugin_nikke.main import NikkePlugin

        class Event:
            def get_sender_id(self):
                return "10001"

            def plain_result(self, text):
                return text

        class Store:
            def get_account(self, qq_id):
                return {"qq_id": qq_id, "cookie": VALID_COOKIE}

        class FakeClient:
            async def get_roster(self, account, include_details=True):
                return [{"name_code": 999, "lv": 1}]

        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.store = Store()
        plugin.client = FakeClient()
        plugin._directory = [
            {"name_code": 1, "name_cn": "爱丽丝", "name_en": "Alice"},
        ]
        result = [item async for item in plugin.character(Event(), "爱丽丝")]
        self.assertEqual(len(result), 1)
        self.assertIn("未持有", result[0])
        self.assertIn("爱丽丝", result[0])

    async def test_group_cdk_is_idempotent_and_never_persists_plaintext(self):
        from astrbot_plugin_nikke.main import NikkePlugin

        class Event:
            def get_sender_id(self):
                return "10001"

            def plain_result(self, text):
                return text

        class Store:
            def __init__(self):
                self.runs = {}

            def get_account(self, qq_id):
                return {"qq_id": qq_id, "cookie": VALID_COOKIE}

            def get_run(self, key):
                return self.runs.get(key)

            def claim_run(self, key, qq_id, action):
                if key in self.runs:
                    return False
                self.runs[key] = {"status": "running", "detail": ""}
                return True

            def retry_run(self, key, statuses, stale_after=0):
                return False

            def finish_run(self, key, status, detail=""):
                self.runs[key] = {"status": status, "detail": detail}

            def mark_cookie_invalid(self, qq_id):
                raise AssertionError("不应失效")

        class Client:
            def __init__(self):
                self.calls = 0

            async def redeem_cdk(self, account, code):
                self.calls += 1
                return CdkRedemptionResult(True, True, "兑换成功", "0")

        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.config = {"enable_cdk_redemption": True}
        plugin.store = Store()
        plugin.client = Client()
        code = "SECRETCODE123"
        first = [item async for item in plugin.cdk(Event(), code)]
        second = [item async for item in plugin.cdk(Event(), code)]
        persisted = json.dumps(plugin.store.runs, ensure_ascii=False)
        self.assertEqual(plugin.client.calls, 1)
        self.assertEqual(first, second)
        self.assertNotIn(code, persisted)
        self.assertNotIn(code, "".join(first))


if __name__ == "__main__":
    unittest.main()

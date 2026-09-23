# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from astrbot_plugin_nikke.integrations.blablalink.client import (
    BlaBlaClient,
    BlaBlaError,
    CdkRedemptionResult,
    CookieExpired,
)
from astrbot_plugin_nikke.ui.primitives import CardRenderer
from astrbot_plugin_nikke.core.storage import NikkeStore
from astrbot_plugin_nikke.features.account.status import (
    BIND_SESSION_PENDING,
    BIND_SESSION_SUCCESS,
)
from astrbot_plugin_nikke.integrations.web.service import BindingWebService
from astrbot_plugin_nikke.integrations.web.service import public_error


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
                from astrbot_plugin_nikke.integrations.blablalink.client import ValidationResult
                return ValidationResult(True, "12345", "67890", "角色", "昵称", "3")

        with tempfile.TemporaryDirectory() as td:
            store = NikkeStore(td)
            store.create_bind_session(
                "a" * 40, "123456", 600, status=BIND_SESSION_PENDING
            )
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
        return self.result if self.result is not None else {"code": 0, "msg": "ok", "data": {"success": True}}


class StoreTests(unittest.TestCase):
    def test_single_use_and_encryption(self):
        with tempfile.TemporaryDirectory() as td:
            store = NikkeStore(td)
            store.create_bind_session(
                "a" * 40, "10001", 600, status=BIND_SESSION_PENDING
            )
            qq_id = store.consume_bind_session(
                "a" * 40,
                VALID_COOKIE,
                "12345",
                "67890",
                "丽塔",
                "丽塔",
                "3",
                success_status=BIND_SESSION_SUCCESS,
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
                    "a" * 40,
                    VALID_COOKIE,
                    "12345",
                    "67890",
                    "丽塔",
                    "丽塔",
                    "3",
                    success_status=BIND_SESSION_SUCCESS,
                )

    def test_expired_session_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = NikkeStore(td)
            store.create_bind_session(
                "b" * 40, "10001", -1, status=BIND_SESSION_PENDING
            )
            with self.assertRaises(ValueError):
                store.consume_bind_session(
                    "b" * 40,
                    VALID_COOKIE,
                    "12345",
                    "67890",
                    "",
                    "",
                    "3",
                    success_status=BIND_SESSION_SUCCESS,
                )

    def test_idempotent_run(self):
        with tempfile.TemporaryDirectory() as td:
            store = NikkeStore(td)
            self.assertTrue(store.claim_run("2026-09-05:1:daily", "1", "daily", initial_status="DISPATCH_INTENT"))
            self.assertFalse(store.claim_run("2026-09-05:1:daily", "1", "daily", initial_status="DISPATCH_INTENT"))

    def test_failed_run_can_be_retried_without_duplication(self):
        with tempfile.TemporaryDirectory() as td:
            store = NikkeStore(td)
            key = "cdk:1:digest"
            self.assertTrue(store.claim_run(key, "1", "cdk", initial_status="DISPATCH_INTENT"))
            store.finish_run(key, "failed", "请求失败")
            self.assertTrue(store.transition_run(
                key,
                from_statuses={"failed"},
                to_status="DISPATCH_INTENT",
                refresh_created_at=True,
            ))
            self.assertEqual(store.get_run(key)["status"], "DISPATCH_INTENT")
            self.assertFalse(store.transition_run(
                key,
                from_statuses={"failed"},
                to_status="DISPATCH_INTENT",
                refresh_created_at=True,
            ))

    def test_stale_dispatch_intent_cannot_be_reclaimed_as_retryable(self):
        with tempfile.TemporaryDirectory() as td:
            store = NikkeStore(td)
            key = "cdk:game:synthetic-intent"
            with patch("astrbot_plugin_nikke.core.storage.time.time", return_value=1000):
                self.assertTrue(store.claim_run(key, "1", "cdk", initial_status="DISPATCH_INTENT"))
            with patch("astrbot_plugin_nikke.core.storage.time.time", return_value=1180):
                self.assertFalse(store.transition_run(
                    key,
                    from_statuses={"failed"},
                    to_status="DISPATCH_INTENT",
                    refresh_created_at=True,
                ))
                self.assertTrue(
                    store.transition_run(
                        key,
                        from_statuses={"running", "DISPATCH_INTENT"},
                        to_status="UNKNOWN_AFTER_ACTION",
                        stale_after=120,
                        detail="结果未确认",
                    )
                )
                self.assertEqual(store.get_run(key)["status"], "UNKNOWN_AFTER_ACTION")
                self.assertFalse(store.transition_run(
                    key,
                    from_statuses={"failed"},
                    to_status="DISPATCH_INTENT",
                    refresh_created_at=True,
                ))


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
        from astrbot_plugin_nikke.integrations.blablalink.client import CDK_REDEEM

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

    async def test_cdk_empty_or_default_success_envelope_is_unknown(self):
        for response in ({}, {"code": 0, "msg": "ok"}, {"code": 0, "msg": "ok", "data": {}}):
            with self.subTest(response=response):
                client = CdkClient(response)
                result = await client.redeem_cdk(self._community_account(), "TESTCODE")
                self.assertFalse(result.success)
                self.assertTrue(result.is_unknown)
                self.assertFalse(result.terminal)
                self.assertEqual(result.code, "UNKNOWN_AFTER_ACTION")

    async def test_cdk_success_requires_integer_code_and_explicit_marker(self):
        for response in (
            {"code": True, "msg": "ok", "data": {"success": True}},
            {"code": "0", "msg": "ok", "data": {"success": True}},
            {"code": 0, "msg": "ok", "data": {"success": False}},
        ):
            with self.subTest(response=response):
                client = CdkClient(response)
                result = await client.redeem_cdk(self._community_account(), "TESTCODE")
                self.assertTrue(result.is_unknown)
                self.assertFalse(result.success)
        client = CdkClient({"code": 0, "msg": "ok", "data": {"redeemed": True}})
        result = await client.redeem_cdk(self._community_account(), "TESTCODE")
        self.assertTrue(result.success)

    async def test_cookie_expired_is_preserved(self):
        class ExpiredClient(BlaBlaClient):
            async def _post(self, path, cookie, payload):
                from astrbot_plugin_nikke.integrations.blablalink.client import CookieExpired
                raise CookieExpired("expired", "401", path.rsplit("/", 1)[-1])

        from astrbot_plugin_nikke.integrations.blablalink.client import CookieExpired
        with self.assertRaises(CookieExpired):
            await ExpiredClient(5).validate_cookie(VALID_COOKIE)

    async def test_1300015_retries_are_bounded(self):
        class RetryClient(BlaBlaClient):
            def __init__(self):
                super().__init__(5)
                self.count = 0

            async def _post(self, path, cookie, payload):
                from astrbot_plugin_nikke.integrations.blablalink.client import PLAYER_INFO, PROFILE
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
        with patch("astrbot_plugin_nikke.integrations.blablalink.client.asyncio.sleep", new=AsyncMock()):
            result = await client.validate_cookie(VALID_COOKIE)
        self.assertEqual(result.area_id, "3")
        self.assertEqual(client.count, 3)

    async def test_two_accounts_keep_cookie_isolated(self):
        class IsolationClient(BlaBlaClient):
            async def _post(self, path, cookie, payload):
                from astrbot_plugin_nikke.integrations.blablalink.client import PLAYER_INFO, PROFILE
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
        from astrbot_plugin_nikke.integrations.blablalink.client import CHECK_LOGIN, PLAYER_INFO, PROFILE

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
        self.assertIn('@filter.command("妮姬", alias={"nikke", "#妮姬", "#nikke"})', source)
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
    def test_profile_builder_extracts_confirmed_optional_fields(self):
        from astrbot_plugin_nikke.features.profile.builder import ProfileBuilder

        data = ProfileBuilder().build(
            account={"area_id": "3", "nickname": "测试"},
            basic={
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
            outpost={
                "synchro_level": 300,
                "outpost_battle_level": 250,
                "infra_core_level": 20,
                "tactic_academy_class": 9,
                "tactic_academy_lesson": 3,
                "jukebox_count": 25,
                "recycle_room_researches": [{"lv": 10}, {"lv": 20}],
                "memorial_counts": [{"count": 4}, {"count": 6}],
            },
            roster=None,
            fetched_at="2026-09-22 12:00",
            plugin_version="test",
        )

        self.assertEqual(data.commander_level, 99)
        self.assertEqual(data.team_combat, 1234567)
        self.assertEqual(data.progress_tribe_tower, "200")
        self.assertEqual([item.level for item in data.recycle_room_researches], [10, 20])
        self.assertEqual([item.count for item in data.memorial_counts], [4, 6])
        self.assertFalse(hasattr(data, "icon_id"))

    def test_profile_builder_uses_campaign_resolver(self):
        from astrbot_plugin_nikke.features.profile.builder import ProfileBuilder
        from astrbot_plugin_nikke.features.campaign.stage_resolver import CampaignStageResolver

        resolver = CampaignStageResolver({
            "NORMAL": {"46": {"46-40": 6046044}},
            "HARD": {"35": {"35-36": 7035044}},
        })
        data = ProfileBuilder(campaign_resolver=resolver).build(
            account={"area_id": "3", "nickname": "测试"},
            basic={
                "progress_normal_campaign": 6046044,
                "progress_hard_campaign": 7035044,
            },
            outpost={},
            roster=None,
            fetched_at="2026-09-22 12:00",
            plugin_version="test",
        )
        self.assertEqual(data.normal_campaign, "46-40")
        self.assertEqual(data.hard_campaign, "35-36")

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

    async def test_m5_command_routing(self):
        from astrbot_plugin_nikke.main import NikkePlugin

        plugin = NikkePlugin.__new__(NikkePlugin)
        calls = []

        async def campaign(event, arg1="", arg2=""):
            calls.append(("campaign", arg1, arg2))
            yield "战役结果"

        async def cdk_batch(event, raw_codes=""):
            calls.append(("cdk_batch", raw_codes))
            yield "批量CDK结果"

        async def cdk_available(event):
            calls.append(("cdk_available",))
            yield "可用CDK结果"

        async def cdk_history(event):
            calls.append(("cdk_history",))
            yield "CDK历史结果"

        async def event_schedule(event):
            calls.append(("event_schedule",))
            yield "日程结果"

        async def announcements_view(event):
            calls.append(("announcements_view",))
            yield "公告结果"

        async def guide(event, category="", page="1"):
            calls.append(("guide", category))
            yield "攻略结果"

        plugin.campaign = campaign
        plugin.cdk_batch = cdk_batch
        plugin.cdk_available = cdk_available
        plugin.cdk_history = cdk_history
        plugin.event_schedule = event_schedule
        plugin.announcements_view = announcements_view
        plugin.guide = guide
        event = object()

        r1 = [item async for item in plugin.nikke(event, "战役", "46-40", "")]
        r2 = [item async for item in plugin.nikke(event, "cdk", "批量", "CODE1 CODE2")]
        r3 = [item async for item in plugin.nikke(event, "cdk", "可用", "")]
        r4 = [item async for item in plugin.nikke(event, "cdk", "历史", "")]
        r6 = [item async for item in plugin.nikke(event, "日程", "", "")]
        r7 = [item async for item in plugin.nikke(event, "公告", "", "")]
        r8 = [item async for item in plugin.nikke(event, "攻略", "练度", "")]

        self.assertEqual(r1, ["战役结果"])
        self.assertEqual(r2, ["批量CDK结果"])
        self.assertEqual(r3, ["可用CDK结果"])
        self.assertEqual(r4, ["CDK历史结果"])
        self.assertEqual(r6, ["日程结果"])
        self.assertEqual(r7, ["公告结果"])
        self.assertEqual(r8, ["攻略结果"])
        self.assertEqual(
            calls,
            [
                ("campaign", "46-40", ""),
                ("cdk_batch", "CODE1 CODE2"),
                ("cdk_available",),
                ("cdk_history",),
                ("event_schedule",),
                ("announcements_view",),
                ("guide", "练度"),
            ],
        )

    async def test_character_query_requires_unique_match(self):
        from astrbot_plugin_nikke.main import NikkePlugin
        from astrbot_plugin_nikke.features.character.application import CharacterAmbiguousMatch

        class Event:
            def get_sender_id(self):
                return "10001"

            def plain_result(self, text):
                return text

        class Application:
            async def build_card(self, request):
                raise CharacterAmbiguousMatch(
                    ("爱丽丝", "爱丽丝：仙境兔女郎")
                )

        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.character_application = Application()
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
        from astrbot_plugin_nikke.features.character.application import CharacterNotOwned

        class Event:
            def get_sender_id(self):
                return "10001"

            def plain_result(self, text):
                return text

        class Application:
            async def build_card(self, request):
                raise CharacterNotOwned("爱丽丝")

        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.character_application = Application()
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
                return {
                    "qq_id": qq_id,
                    "cookie": VALID_COOKIE,
                    "game_uid": "game-10001",
                    "area_id": "global",
                    "platform": "global",
                }

            def get_run(self, key):
                return self.runs.get(key)

            def claim_run(self, key, qq_id, action, *, initial_status):
                if key in self.runs:
                    return False
                self.runs[key] = {"status": initial_status, "detail": ""}
                return True

            def transition_run(self, key, *, from_statuses, to_status, detail="", stale_after=None, refresh_created_at=False):
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
        self.assertIn("兑换成功", first[0])
        self.assertIn("已有处理记录", second[0])
        self.assertNotIn(code, persisted)
        self.assertNotIn(code, "".join(first + second))

    async def test_character_command_delegates_identity_and_fetch_to_application(self):
        from astrbot_plugin_nikke.main import NikkePlugin
        from astrbot_plugin_nikke.features.character.application import CharacterNotOwned

        class Event:
            def get_sender_id(self):
                return "10001"
            def plain_result(self, text):
                return text

        class Application:
            def __init__(self):
                self.requests = []

            async def build_card(self, request):
                self.requests.append(request)
                raise CharacterNotOwned("爱丽丝")

        plugin = NikkePlugin.__new__(NikkePlugin)
        application = Application()
        plugin.character_application = application
        plugin._directory = [
            {"name_code": 1, "name_cn": "爱丽丝", "name_en": "Alice"},
        ]
        results = [item async for item in plugin.character(Event(), "爱丽丝")]
        self.assertEqual(len(results), 1)
        self.assertIn("未持有", results[0])
        self.assertEqual(len(application.requests), 1)
        self.assertEqual(application.requests[0].qq_id, "10001")
        self.assertEqual(application.requests[0].query, "爱丽丝")
        self.assertEqual(tuple(application.requests[0].directory), tuple(plugin._directory))

    async def test_roster_command_delegates_account_and_name_mapping_to_application(self):
        from unittest.mock import AsyncMock, Mock

        from astrbot_plugin_nikke.main import NikkePlugin
        from astrbot_plugin_nikke.features.character.application import CharacterRosterData

        class Event:
            def get_sender_id(self):
                return "10001"

            def image_result(self, path):
                return path

        directory = [{"name_code": "alice", "name_cn": "爱丽丝"}]
        data = CharacterRosterData(
            commander_name="测试指挥官",
            characters=({"name_code": "alice", "lv": 200},),
            name_map={"alice": "爱丽丝"},
        )
        application = Mock(roster=AsyncMock(return_value=data))
        renderer = Mock(render_roster=Mock(return_value="roster.png"))
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.character_application = application
        plugin.renderer = renderer
        plugin._directory = directory

        result = [item async for item in plugin.roster(Event())]

        self.assertEqual(result, ["roster.png"])
        application.roster.assert_awaited_once_with("10001", directory)
        renderer.render_roster.assert_called_once_with(
            "测试指挥官", data.characters, data.name_map
        )

    async def test_info_command_refuses_ambiguous_identity_instead_of_rendering_first(self):
        from unittest.mock import Mock

        from astrbot_plugin_nikke.main import NikkePlugin
        from astrbot_plugin_nikke.features.character.application import CharacterAmbiguousMatch

        class Event:
            def plain_result(self, text):
                return text

        application = Mock(
            info=Mock(
                side_effect=CharacterAmbiguousMatch(("爱丽丝", "仙境兔女郎"))
            )
        )
        renderer = Mock()
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.character_application = application
        plugin.renderer = renderer
        plugin._directory = []

        result = [item async for item in plugin.info(Event(), "丽丝")]

        self.assertEqual(len(result), 1)
        self.assertIn("找到多个角色", result[0])
        self.assertIn("仙境兔女郎", result[0])
        renderer.render.assert_not_called()

    async def test_terminate_delegates_to_runtime_coordinator(self):
        from astrbot_plugin_nikke.main import NikkePlugin
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.runtime = SimpleNamespace(close=AsyncMock())

        await plugin.terminate()
        plugin.runtime.close.assert_awaited_once()

if __name__ == "__main__":
    unittest.main()

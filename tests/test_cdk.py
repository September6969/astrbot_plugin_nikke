# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from astrbot_plugin_nikke.cdk_models import CdkBatchResult, CdkRedeemResult
from astrbot_plugin_nikke.cdk_service import CDK_PATTERN, CdkInputParser, CdkService
from astrbot_plugin_nikke.client import BlaBlaClient, BlaBlaError, CdkRedemptionResult, CookieExpired


class CdkInputParserTests(unittest.TestCase):
    def test_parser_preserves_case_and_strips_separators(self):
        text = "NIKKE2026, aliceLove; Dorothy_999\nRedHood2024"
        codes = CdkInputParser.parse(text)
        self.assertEqual(codes, ["NIKKE2026", "aliceLove", "Dorothy_999", "RedHood2024"])

    def test_parser_deduplicates_codes(self):
        text = "NIKKE2026 NIKKE2026 aliceLove aliceLove"
        codes = CdkInputParser.parse(text)
        self.assertEqual(codes, ["NIKKE2026", "aliceLove"])

    def test_parser_limits_max_items(self):
        text = " ".join(f"CODE_{i}" for i in range(25))
        codes = CdkInputParser.parse(text, max_items=10)
        self.assertEqual(len(codes), 10)
        self.assertEqual(codes[0], "CODE_0")
        self.assertEqual(codes[-1], "CODE_9")

    def test_parser_filters_invalid_tokens(self):
        text = "ab   valid_cdk_123   " + "x" * 70 + "   another_cdk"
        codes = CdkInputParser.parse(text)
        self.assertEqual(codes, ["valid_cdk_123", "another_cdk"])

    def test_parser_rejects_3_char_cdk(self):
        text = "abc GOOD1234"
        codes = CdkInputParser.parse(text)
        self.assertEqual(codes, ["GOOD1234"])

    def test_parser_rejects_invalid_symbols(self):
        text = "ABC!!! test@code foo/bar GOOD_123 GOOD-456"
        codes = CdkInputParser.parse(text)
        self.assertEqual(codes, ["GOOD_123", "GOOD-456"])

    def test_parser_rejects_chinese_chars(self):
        text = "中文CDK VALID1234"
        codes = CdkInputParser.parse(text)
        self.assertEqual(codes, ["VALID1234"])

    def test_parser_boundary_lengths(self):
        valid_4 = "AB12"
        valid_64 = "A" * 64
        invalid_65 = "A" * 65
        text = f"{valid_4} {valid_64} {invalid_65}"
        codes = CdkInputParser.parse(text)
        self.assertEqual(codes, [valid_4, valid_64])

    def test_parser_preserves_case_distinctness(self):
        text = "AliceCode aliceCode"
        codes = CdkInputParser.parse(text)
        self.assertEqual(codes, ["AliceCode", "aliceCode"])

    def test_parser_separators_support(self):
        text = "CODE1,CODE2；CODE3\nCODE4"
        codes = CdkInputParser.parse(text)
        self.assertEqual(codes, ["CODE1", "CODE2", "CODE3", "CODE4"])

    def test_shared_cdk_pattern_consistency(self):
        import astrbot_plugin_nikke.main as main_mod

        self.assertIs(main_mod.CDK_PATTERN, CDK_PATTERN)
        self.assertEqual(CDK_PATTERN.pattern, r"[A-Za-z0-9_-]{4,64}")
        self.assertFalse(CDK_PATTERN.fullmatch("abc"))
        self.assertTrue(CDK_PATTERN.fullmatch("abcd"))
        self.assertTrue(CDK_PATTERN.fullmatch("A" * 64))
        self.assertFalse(CDK_PATTERN.fullmatch("A" * 65))


class CdkServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_success(self):
        client = AsyncMock(spec=BlaBlaClient)
        client.redeem_cdk.return_value = CdkRedemptionResult(
            success=True, terminal=True, message="兑换成功", code="0"
        )
        service = CdkService(client)
        res = await service.redeem_single({"game_uid": "123"}, "NIKKE2026")
        self.assertTrue(res.success)
        self.assertEqual(res.code, "NIKKE2026")
        self.assertIn("兑换成功", res.message)

    async def test_single_business_failure_has_blablalink_fallback(self):
        client = AsyncMock(spec=BlaBlaClient)
        client.redeem_cdk.return_value = CdkRedemptionResult(
            success=False, terminal=True, message="兑换码已失效", code="1300050"
        )
        service = CdkService(client)
        res = await service.redeem_single({"game_uid": "123"}, "EXPIRED_CODE")
        self.assertFalse(res.success)
        self.assertIn("BlaBlaLink", res.message)

    async def test_single_network_timeout_marks_unknown(self):
        client = AsyncMock(spec=BlaBlaClient)
        client.redeem_cdk.side_effect = httpx.TimeoutException("Read timed out")
        service = CdkService(client)
        res = await service.redeem_single({"game_uid": "123"}, "TIMEOUT_CODE")
        self.assertFalse(res.success)
        self.assertTrue(res.is_unknown)
        self.assertIn("网络请求超时", res.message)

    async def test_batch_halts_on_cookie_expired(self):
        client = AsyncMock(spec=BlaBlaClient)
        # 第1个成功，第2个抛 CookieExpired
        client.redeem_cdk.side_effect = [
            CdkRedemptionResult(True, True, "兑换成功", "0"),
            CookieExpired("Cookie失效", "300001", "RedeemCdk"),
        ]
        service = CdkService(client)
        batch = await service.redeem_batch(
            {"game_uid": "123"}, ["CODE1", "CODE2", "CODE3", "CODE4"], delay=0
        )
        self.assertTrue(batch.stopped_by_cookie)
        # 只尝试了2个，后2个未发送
        self.assertEqual(len(batch.results), 2)
        self.assertTrue(batch.results[0].success)
        self.assertFalse(batch.results[1].success)
        self.assertIn("登录状态已失效", batch.results[1].message)

    async def test_batch_halts_on_rate_limit(self):
        client = AsyncMock(spec=BlaBlaClient)
        # 第1个成功，第2个遇到限流
        client.redeem_cdk.side_effect = [
            CdkRedemptionResult(True, True, "兑换成功", "0"),
            BlaBlaError("请求过频", "212000", "RedeemCdk"),
        ]
        service = CdkService(client)
        batch = await service.redeem_batch(
            {"game_uid": "123"}, ["CODE1", "CODE2", "CODE3"], delay=0
        )
        self.assertTrue(batch.stopped_by_rate_limit)
        self.assertEqual(len(batch.results), 2)
        self.assertTrue(batch.results[0].success)
        self.assertIn("请求过频", batch.results[1].message)

    async def test_single_blabla_timeout_error_marks_unknown(self):
        from astrbot_plugin_nikke.client import BlaBlaTimeoutError
        client = AsyncMock(spec=BlaBlaClient)
        client.redeem_cdk.side_effect = BlaBlaTimeoutError("RedeemCdk 请求超时", endpoint="RedeemCdk")
        service = CdkService(client)
        res = await service.redeem_single({"game_uid": "123"}, "TIMEOUT_CODE")
        self.assertFalse(res.success)
        self.assertTrue(res.is_unknown)
        self.assertIn("网络请求超时", res.message)

    async def test_single_and_batch_share_account_lock(self):
        client = AsyncMock(spec=BlaBlaClient)
        execution_order = []

        async def fake_redeem(account, code):
            execution_order.append(f"start_{code}")
            await asyncio.sleep(0.05)
            execution_order.append(f"end_{code}")
            return CdkRedemptionResult(True, True, "ok", "0")

        client.redeem_cdk.side_effect = fake_redeem
        service = CdkService(client)

        # 同时发起单条与批量，测试同一账号下的锁互斥
        task1 = asyncio.create_task(service.redeem_single({"game_uid": "shared_uid"}, "SINGLE1", account_key="shared_uid"))
        task2 = asyncio.create_task(service.redeem_batch({"game_uid": "shared_uid"}, ["BATCH1", "BATCH2"], account_key="shared_uid", delay=0.01))

        await asyncio.gather(task1, task2)

        # 检查两个操作互斥执行，不会交替穿插
        first_group = execution_order[:2]
        if first_group == ["start_SINGLE1", "end_SINGLE1"]:
            self.assertEqual(execution_order[2:], ["start_BATCH1", "end_BATCH1", "start_BATCH2", "end_BATCH2"])
        else:
            self.assertEqual(execution_order[:4], ["start_BATCH1", "end_BATCH1", "start_BATCH2", "end_BATCH2"])
            self.assertEqual(execution_order[4:], ["start_SINGLE1", "end_SINGLE1"])


class CdkClientUnpackingTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_get_cdk_redemption_unpacks_nested_data(self):
        from astrbot_plugin_nikke.client import GET_CDK_REDEMPTION
        client = BlaBlaClient()
        account = {"cookie": "game_uid=1", "game_openid": "openid"}

        # 1. data -> list
        client._community_request = AsyncMock(return_value={
            "code": 0, "msg": "ok", "data": {"list": [{"cdkey": "CODE1"}, {"cdkey": "CODE2"}]}
        })
        items = await client.get_cdk_redemption(account)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["cdkey"], "CODE1")
        client._community_request.assert_called_with("POST", GET_CDK_REDEMPTION, account, payload={})

        # 2. data -> direct list
        client._community_request = AsyncMock(return_value={
            "code": 0, "msg": "ok", "data": [{"cdkey": "DIRECT1"}]
        })
        items = await client.get_cdk_redemption(account)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["cdkey"], "DIRECT1")
        client._community_request.assert_called_with("POST", GET_CDK_REDEMPTION, account, payload={})

        # 3. data -> cdk_list
        client._community_request = AsyncMock(return_value={
            "code": 0, "msg": "ok", "data": {"cdk_list": [{"cdkey": "ALT1"}]}
        })
        items = await client.get_cdk_redemption(account)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["cdkey"], "ALT1")

    async def test_client_get_cdk_redemption_history_unpacks_nested_data(self):
        from astrbot_plugin_nikke.client import GET_CDK_REDEMPTION_HISTORY
        client = BlaBlaClient()
        account = {"cookie": "game_uid=1", "game_openid": "openid"}

        client._community_request = AsyncMock(return_value={
            "code": 0, "msg": "ok", "data": {"list": [{"cdkey": "HIST1", "status": "已兑换"}]}
        })
        items = await client.get_cdk_redemption_history(account)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["cdkey"], "HIST1")
        client._community_request.assert_called_with(
            "POST",
            GET_CDK_REDEMPTION_HISTORY,
            account,
            payload={
                "page_num": 1,
                "page_size": 20,
            },
        )

    async def test_client_get_cdk_redemption_history_unpacks_cdk_redemption_list(self):
        from astrbot_plugin_nikke.client import GET_CDK_REDEMPTION_HISTORY
        client = BlaBlaClient()
        account = {"cookie": "game_uid=1", "game_openid": "openid"}

        client._community_request = AsyncMock(return_value={
            "code": 0,
            "msg": "ok",
            "data": {
                "cdk_redemption_list": [
                    {
                        "cdk": "TESTCODE1",
                        "status": 1,
                    },
                    {
                        "cdk": "TESTCODE2",
                        "status": 1,
                    },
                ]
            },
        })
        items = await client.get_cdk_redemption_history(account)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["cdk"], "TESTCODE1")
        self.assertEqual(items[1]["cdk"], "TESTCODE2")
        client._community_request.assert_called_with(
            "POST",
            GET_CDK_REDEMPTION_HISTORY,
            account,
            payload={
                "page_num": 1,
                "page_size": 20,
            },
        )

    async def test_client_get_cdk_redemption_raises_on_error(self):
        client = BlaBlaClient()
        account = {"cookie": "game_uid=1", "game_openid": "openid"}

        # 验证接口失败时抛出受控异常，不静默返回 []
        client._community_request = AsyncMock(side_effect=BlaBlaError("社区系统错误", "500", "GetCdkRedemption"))
        with self.assertRaises(BlaBlaError) as cm:
            await client.get_cdk_redemption(account)
        self.assertEqual(cm.exception.code, "500")

        client._community_request = AsyncMock(side_effect=CookieExpired("登录状态已失效", "300001", "GetCdkRedemption"))
        with self.assertRaises(CookieExpired):
            await client.get_cdk_redemption(account)

    async def test_client_get_cdk_redemption_unpacks_cdk_redemption_list(self):
        client = BlaBlaClient()
        account = {"cookie": "game_uid=1", "game_openid": "openid"}
        client._community_request = AsyncMock(return_value={
            "code": 0, "msg": "ok", "data": {"cdk_redemption_list": [{"cdkey": "OFFICIAL_LIST_CODE"}]}
        })
        items = await client.get_cdk_redemption(account)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["cdkey"], "OFFICIAL_LIST_CODE")

    async def test_rate_limited_is_not_terminal_and_retryable_in_main(self):
        from astrbot_plugin_nikke.main import NikkePlugin

        client = AsyncMock(spec=BlaBlaClient)
        client.redeem_cdk.side_effect = BlaBlaError("请求过频，请稍后再试", "212000", "RedeemCdk")
        service = CdkService(client)
        res = await service.redeem_single({"game_uid": "uid1"}, "RATELIMIT_CODE")
        self.assertFalse(res.success)
        self.assertTrue(res.is_rate_limited)
        self.assertFalse(res.terminal)

        # 验证 main.cdk() 记录状态为 "failed" 而不是 "terminal"
        class Event:
            def get_sender_id(self):
                return "10001"
            def plain_result(self, text):
                return text

        class Store:
            def __init__(self):
                self.runs = {}
            def get_account(self, qq_id):
                return {"qq_id": qq_id, "game_uid": "uid1", "cookie": "cookie"}
            def get_run(self, key):
                return self.runs.get(key)
            def claim_run(self, key, qq_id, action):
                self.runs[key] = {"status": "running", "detail": ""}
                return True
            def retry_run(self, key, statuses, stale_after=0):
                if key in self.runs and self.runs[key]["status"] in statuses:
                    self.runs[key]["status"] = "running"
                    return True
                return False
            def finish_run(self, key, status, detail=""):
                self.runs[key] = {"status": status, "detail": detail}

        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.config = {"enable_cdk_redemption": True}
        plugin.store = Store()
        plugin.cdk_service = service

        # 第一次触发限流
        results1 = [item async for item in plugin.cdk(Event(), "RATELIMIT_CODE")]
        self.assertEqual(len(results1), 1)
        run_key = list(plugin.store.runs.keys())[0]
        self.assertEqual(plugin.store.runs[run_key]["status"], "failed")

        # 第二次由于状态是 failed（在 retryable 集合中），应该能够重新触发重试而非直接返回已处理
        results2 = [item async for item in plugin.cdk(Event(), "RATELIMIT_CODE")]
        self.assertEqual(len(results2), 1)
        # 1次直接调用 + 2次通过 plugin 调用 = 3次
        self.assertEqual(client.redeem_cdk.call_count, 3)

    async def test_http_temporary_error_is_not_terminal_and_retryable(self):
        client = AsyncMock(spec=BlaBlaClient)
        client.redeem_cdk.side_effect = BlaBlaError("HTTP 502 Bad Gateway", "502", "RecordCdkRedemption")
        service = CdkService(client)
        res = await service.redeem_single({"game_uid": "uid1"}, "HTTP_502_CODE")
        self.assertFalse(res.success)
        self.assertFalse(res.terminal)
        self.assertIn("可稍后重试", res.message)

        # 同样针对 500
        client.redeem_cdk.side_effect = BlaBlaError("HTTP 500 Internal Server Error", "500", "RecordCdkRedemption")
        res500 = await service.redeem_single({"game_uid": "uid1"}, "HTTP_500_CODE")
        self.assertFalse(res500.success)
        self.assertFalse(res500.terminal)

    async def test_rebind_account_changes_run_key_scope(self):
        from astrbot_plugin_nikke.main import NikkePlugin

        class Event:
            def get_sender_id(self):
                return "10001"
            def plain_result(self, text):
                return text

        class Store:
            def __init__(self):
                self.current_uid = "uid_A"
                self.runs = {}
            def get_account(self, qq_id):
                return {"qq_id": qq_id, "game_uid": self.current_uid, "cookie": "cookie"}
            def get_run(self, key):
                return self.runs.get(key)
            def claim_run(self, key, qq_id, action):
                self.runs[key] = {"status": "running", "detail": ""}
                return True
            def finish_run(self, key, status, detail=""):
                self.runs[key] = {"status": status, "detail": detail}

        client = AsyncMock(spec=BlaBlaClient)
        client.redeem_cdk.return_value = CdkRedemptionResult(True, True, "兑换成功", "0")
        service = CdkService(client)

        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.config = {"enable_cdk_redemption": True}
        plugin.store = Store()
        plugin.cdk_service = service

        # 账号 A 兑换
        [item async for item in plugin.cdk(Event(), "TESTCODE123")]
        keys_a = list(plugin.store.runs.keys())
        self.assertEqual(len(keys_a), 1)
        self.assertIn("10001:uid_A", keys_a[0])

        # 换绑为账号 B
        plugin.store.current_uid = "uid_B"
        [item async for item in plugin.cdk(Event(), "TESTCODE123")]
        keys_b = list(plugin.store.runs.keys())
        self.assertEqual(len(keys_b), 2)
        self.assertIn("10001:uid_B", keys_b[1])
        # 两个账号各自兑换了一次，client 调用2次
        self.assertEqual(client.redeem_cdk.call_count, 2)


class CdkCommandHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from astrbot_plugin_nikke.main import NikkePlugin

        class Event:
            def get_sender_id(self):
                return "10001"

            def plain_result(self, text):
                return text

        class Store:
            def get_account(self, qq_id):
                return {"qq_id": qq_id, "game_uid": "uid1", "cookie": "cookie"}

        self.event = Event()
        self.plugin = NikkePlugin.__new__(NikkePlugin)
        self.plugin.config = {"enable_cdk_redemption": True}
        self.plugin.store = Store()
        self.client = AsyncMock(spec=BlaBlaClient)
        self.plugin.client = self.client

    async def test_cdk_available_identifies_real_cdk_field(self):
        self.client.get_cdk_redemption.return_value = [
            {"cdk": "TESTAVAILABLE", "status": 0}
        ]
        results = [item async for item in self.plugin.cdk_available(self.event)]
        self.assertEqual(len(results), 1)
        text = results[0]
        self.assertIn("TESTAVAILABLE", text)
        self.assertNotIn("未知", text)

    async def test_cdk_available_filters_status_not_zero(self):
        self.client.get_cdk_redemption.return_value = [
            {"cdk": "AVAILABLE1", "status": 0},
            {"cdk": "USED1", "status": 1},
        ]
        results = [item async for item in self.plugin.cdk_available(self.event)]
        self.assertEqual(len(results), 1)
        text = results[0]
        self.assertIn("AVAILABLE1", text)
        self.assertNotIn("USED1", text)

    async def test_cdk_available_supports_string_status(self):
        self.client.get_cdk_redemption.return_value = [
            {"cdk": "AVAILABLE_STRING", "status": "0"},
            {"cdk": "USED_STRING", "status": "1"},
        ]
        results = [item async for item in self.plugin.cdk_available(self.event)]
        self.assertEqual(len(results), 1)
        text = results[0]
        self.assertIn("AVAILABLE_STRING", text)
        self.assertNotIn("USED_STRING", text)

    async def test_cdk_available_filters_before_limiting_to_15(self):
        items = [{"cdk": f"USED_{i}", "status": 1} for i in range(5)]
        items += [{"cdk": f"VALID_{i}", "status": 0} for i in range(18)]
        self.client.get_cdk_redemption.return_value = items

        results = [item async for item in self.plugin.cdk_available(self.event)]
        self.assertEqual(len(results), 1)
        text = results[0]
        for i in range(15):
            self.assertIn(f"VALID_{i}", text)
        self.assertNotIn("VALID_15", text)
        self.assertNotIn("USED_", text)

    async def test_cdk_history_identifies_real_cdk_field(self):
        self.client.get_cdk_redemption_history.return_value = [
            {"cdk": "HISTORYCODE", "status": 1}
        ]
        results = [item async for item in self.plugin.cdk_history(self.event)]
        self.assertEqual(len(results), 1)
        text = results[0]
        expected_mask = self.plugin._mask_cdk("HISTORYCODE")
        self.assertEqual(expected_mask, "HI***DE")
        self.assertIn(expected_mask, text)
        self.assertNotIn("• ***:", text)
        self.assertNotIn("未知", text)

    async def test_cdk_compatibility_fields(self):
        self.client.get_cdk_redemption.return_value = [
            {"cdkey": "LEGACY_KEY", "status": 0},
            {"code": "LEGACY_CODE", "status": 0},
            {"title": "LEGACY_TITLE", "status": 0},
            {"cdk": "NONE_STATUS", "status": None},
        ]
        results_avail = [item async for item in self.plugin.cdk_available(self.event)]
        self.assertEqual(len(results_avail), 1)
        text_avail = results_avail[0]
        self.assertIn("LEGACY_KEY", text_avail)
        self.assertIn("LEGACY_CODE", text_avail)
        self.assertIn("LEGACY_TITLE", text_avail)
        self.assertIn("NONE_STATUS", text_avail)

        self.client.get_cdk_redemption_history.return_value = [
            {"cdkey": "HISTKEY123", "status": "已兑换"},
            {"code": "HISTCODE456", "status": "已兑换"},
        ]
        results_hist = [item async for item in self.plugin.cdk_history(self.event)]
        self.assertEqual(len(results_hist), 1)
        text_hist = results_hist[0]
        self.assertIn(self.plugin._mask_cdk("HISTKEY123"), text_hist)
        self.assertIn(self.plugin._mask_cdk("HISTCODE456"), text_hist)

    async def test_cdk_available_empty_after_filter(self):
        self.client.get_cdk_redemption.return_value = [
            {"cdk": "USED_ALL", "status": 1}
        ]
        results = [item async for item in self.plugin.cdk_available(self.event)]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], "官方暂无可查询的可用 CDK 列表。")


if __name__ == "__main__":
    unittest.main()

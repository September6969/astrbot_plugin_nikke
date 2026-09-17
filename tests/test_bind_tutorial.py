# SPDX-License-Identifier: GPL-3.0-or-later
"""BlaBlaLink 绑定教程与 API 标准化测试套件。"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from aiohttp.test_utils import TestClient, TestServer

from astrbot_plugin_nikke.integrations.web.bind_template import render_bind_page
from astrbot_plugin_nikke.integrations.blablalink.client import BlaBlaClient, ValidationResult
from astrbot_plugin_nikke.core.storage import NikkeStore
from astrbot_plugin_nikke.integrations.web.service import BindingWebService


class TestBindTutorialPage(IsolatedAsyncioTestCase):
    def test_render_valid_session(self):
        token = "a" * 40
        now = int(time.time())
        session = {
            "token_hash": "hash1",
            "qq_id": "1234567890",
            "created_at": now,
            "expires_at": now + 600,
            "used_at": None,
            "status": "pending",
            "error": "",
        }
        page = render_bind_page(token, session, "https://bot.example.com")
        self.assertIn("NIKKE · BlaBlaLink 安全绑定", page)
        self.assertIn("● 链接有效", page)
        self.assertIn("Microsoft Edge", page)
        self.assertIn("Google Chrome", page)
        self.assertIn("edge://extensions", page)
        self.assertIn("chrome://extensions", page)
        self.assertIn("加载解压缩的扩展", page)
        self.assertIn("https://www.blablalink.com/", page)
        self.assertIn("常见问题 (FAQ)", page)
        self.assertIn("viewTutorial", page)

    def test_render_expired_session(self):
        token = "b" * 40
        now = int(time.time())
        session = {
            "token_hash": "hash2",
            "qq_id": "1234567890",
            "created_at": now - 700,
            "expires_at": now - 100,
            "used_at": None,
            "status": "pending",
            "error": "",
        }
        page = render_bind_page(token, session, "https://bot.example.com")
        self.assertIn("● 链接已过期", page)
        self.assertIn("本链接已过期。请返回 QQ", page)

    def test_render_used_session(self):
        token = "c" * 40
        now = int(time.time())
        session = {
            "token_hash": "hash3",
            "qq_id": "1234567890",
            "created_at": now - 300,
            "expires_at": now + 300,
            "used_at": now - 50,
            "status": "consumed",
            "error": "",
        }
        page = render_bind_page(token, session, "https://bot.example.com")
        self.assertIn("● 此绑定链接已经使用", page)
        self.assertIn("此绑定链接已经使用过", page)


class TestBindWebServiceAPI(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp_dir.name)
        self.store = NikkeStore(self.data_dir)
        self.client = BlaBlaClient()
        self.zip_path = self.data_dir / "extension.zip"
        self.zip_path.write_bytes(b"dummy zip content")
        self.service = BindingWebService(
            self.store,
            self.client,
            self.zip_path,
            api_key="test-api-key",
            public_base_url="https://nikke.irises777.xyz",
        )
        self.server = TestServer(self.service.app())
        self.test_client = TestClient(self.server)
        await self.test_client.start_server()

    async def asyncTearDown(self):
        await self.test_client.close()
        self.tmp_dir.cleanup()

    async def test_submit_missing_cookies_returns_standard_code(self):
        token = "x" * 40
        self.store.create_bind_session(token, "12345678", 600)

        # 缺少 game_uid 和 game_openid
        payload = {
            "token": token,
            "cookies": [{"name": "game_token", "value": "tok", "domain": "blablalink.com"}],
            "x_common_params": '{"openid":"op123"}',
        }
        resp = await self.test_client.post("/api/bind/cookies", json=payload)
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["code"], "MISSING_COOKIES")
        self.assertIn("game_openid", data["message"])
        # 兼容旧字段
        self.assertEqual(data["error"], data["message"])

    async def test_submit_expired_token_returns_token_expired_code(self):
        token = "e" * 40
        # 创建已过期的 session
        self.store.create_bind_session(token, "12345678", -10)

        payload = {
            "token": token,
            "cookies": [
                {"name": "game_token", "value": "tok", "domain": "blablalink.com"},
                {"name": "game_uid", "value": "uid", "domain": "blablalink.com"},
                {"name": "game_openid", "value": "openid", "domain": "blablalink.com"},
            ],
            "x_common_params": '{"openid":"op123"}',
        }
        resp = await self.test_client.post("/api/bind/cookies", json=payload)
        self.assertEqual(resp.status, 410)
        data = await resp.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["code"], "TOKEN_EXPIRED")

    async def test_submit_success_returns_bound_code_and_masked_status(self):
        token = "s" * 40
        self.store.create_bind_session(token, "12345678", 600)

        mock_validation = ValidationResult(
            valid=True,
            game_uid="uid123",
            game_openid="openid123",
            nickname="IRISES",
            role_name="指挥官",
            area_id="jp",
        )
        self.client.validate_cookie = AsyncMock(return_value=mock_validation)

        payload = {
            "token": token,
            "cookies": [
                {"name": "game_token", "value": "tok", "domain": "blablalink.com"},
                {"name": "game_uid", "value": "uid", "domain": "blablalink.com"},
                {"name": "game_openid", "value": "openid", "domain": "blablalink.com"},
            ],
            "x_common_params": '{"openid":"openid123"}',
        }
        resp = await self.test_client.post("/api/bind/cookies", json=payload)
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["code"], "BOUND")
        self.assertEqual(data["data"]["nickname"], "IRISES")
        self.assertEqual(data["nickname"], "IRISES")
        self.assertEqual(data["qq_id"], "12345678")

        # 查询状态
        status_resp = await self.test_client.get(f"/api/bind/status?token={token}")
        self.assertEqual(status_resp.status, 200)
        status_data = await status_resp.json()
        self.assertTrue(status_data["ok"])
        self.assertIn(status_data["status"], ("success", "consumed"))
        self.assertEqual(status_data["nickname"], "IRISES")
        self.assertEqual(status_data["masked_qq"], "********5678")

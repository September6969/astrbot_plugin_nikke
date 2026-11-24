# SPDX-License-Identifier: GPL-3.0-or-later
"""PR-1B：绑定页轮询、Web 输入校验、配置归一化、脱敏与运行稳定性回归。"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from astrbot_plugin_nikke.adapters.astrbot.command_presentation import AstrBotCommandPresentation
from astrbot_plugin_nikke.adapters.astrbot.runtime import AstrBotRuntimeAdapter
from astrbot_plugin_nikke.application.commands.cdk import CdkCommandHandler
from astrbot_plugin_nikke.application.commands.contracts import CommandContext
from astrbot_plugin_nikke.core.config import bounded_bool, normalize_runtime_config
from astrbot_plugin_nikke.core.feedback import DelayedFeedbackManager
from astrbot_plugin_nikke.core.lifecycle.scheduler import RuntimeScheduler
from astrbot_plugin_nikke.core.storage import NikkeStore
from astrbot_plugin_nikke.integrations.web import service as web_service
from astrbot_plugin_nikke.integrations.web.bind_template import render_bind_page
from astrbot_plugin_nikke.integrations.web.service import BindingWebService

TOKEN = "T" * 43


# ------------------------------------------------------------------ AUD-001

def test_bind_page_polling_recognises_success_and_failed() -> None:
    session = {"status": "pending", "expires_at": int(time.time()) + 600, "used_at": None, "error": ""}
    page = render_bind_page(TOKEN, session, "https://bot.example.com")
    assert "data.status === 'success'" in page
    assert "data.status === 'consumed'" in page and "data.status === 'bound'" in page
    assert "data.status === 'failed'" in page
    assert "}, 4000);" in page and "}, 2500);" not in page
    for anchor in page.split("<a ")[1:]:
        if 'target="_blank"' in anchor.split(">")[0]:
            assert 'rel="noopener noreferrer"' in anchor.split(">")[0]


# ------------------------------------------------------------------ Web 输入与反代

@pytest.fixture
def store(tmp_path, monkeypatch) -> NikkeStore:
    monkeypatch.delenv("NIKKE_ENCRYPTION_KEY", raising=False)
    return NikkeStore(tmp_path)


async def _client(service: BindingWebService) -> TestClient:
    client = TestClient(TestServer(service.app()))
    await client.start_server()
    return client


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [b"{not json", b"[1, 2]", b"\xff\xfe"], ids=["broken", "array", "binary"])
async def test_invalid_json_bodies_return_400(store, payload) -> None:
    service = BindingWebService(store, object(), Path("x.zip"), api_key="synthetic-key")
    client = await _client(service)
    try:
        cookies = await client.post("/api/bind/cookies", data=payload, headers={"Content-Type": "application/json"})
        session = await client.post(
            "/api/bind/session",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": "Bearer synthetic-key"},
        )
        assert cookies.status == 400 and (await cookies.json())["code"] == "INVALID_JSON"
        assert session.status == 400 and (await session.json())["code"] == "INVALID_JSON"
    finally:
        await client.close()


def _cookie_body(**overrides):
    body = {
        "token": TOKEN,
        "cookies": [
            {"name": name, "value": "v", "domain": ".blablalink.com"}
            for name in ("game_token", "game_uid", "game_openid")
        ],
        "x_common_params": json.dumps({"openid": "o"}),
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"user_agent": "Mozilla\r\nX-Injected: 1"}, "INVALID_USER_AGENT"),
        ({"cookies": [{"name": "game_token", "value": "a;b=c", "domain": "blablalink.com"}]}, "INVALID_COOKIES"),
        ({"cookies": [{"name": "game_token", "value": "a\nb", "domain": "blablalink.com"}]}, "INVALID_COOKIES"),
        ({"cookies": ["not-an-object"]}, "INVALID_COOKIES"),
    ],
    ids=["ua-newline", "cookie-semicolon", "cookie-newline", "cookie-item-type"],
)
async def test_cookie_and_user_agent_injection_rejected(store, overrides, code) -> None:
    store.create_bind_session(TOKEN, "10001", status="pending")
    client_stub = SimpleNamespace(validate_cookie=AsyncMock())
    service = BindingWebService(store, client_stub, Path("x.zip"))
    client = await _client(service)
    try:
        response = await client.post("/api/bind/cookies", json=_cookie_body(**overrides))
        assert response.status == 400
        assert (await response.json())["code"] == code
    finally:
        await client.close()
    client_stub.validate_cookie.assert_not_awaited()


@pytest.mark.asyncio
async def test_user_agent_semicolons_are_allowed(store) -> None:
    store.create_bind_session(TOKEN, "10001", status="pending")
    result = SimpleNamespace(game_uid="u", game_openid="o", nickname="n", role_name="r", area_id="81")
    client_stub = SimpleNamespace(validate_cookie=AsyncMock(return_value=result))
    service = BindingWebService(store, client_stub, Path("x.zip"))
    client = await _client(service)
    try:
        response = await client.post("/api/bind/cookies", json=_cookie_body())
        assert response.status == 200, await response.text()
    finally:
        await client.close()
    assert store.get_bind_session(TOKEN)["status"] == "success"


@pytest.mark.parametrize("value", ["caddy", "10.0.0.0/33", "not an ip"])
def test_invalid_trusted_proxy_does_not_break_startup(store, value) -> None:
    service = BindingWebService(store, object(), Path("x.zip"), trusted_proxy_ip=value)
    assert service._trusted_proxy is None


def test_trusted_proxy_accepts_cidr_and_uses_forwarded_client(store) -> None:
    service = BindingWebService(store, object(), Path("x.zip"), trusted_proxy_ip="172.16.0.0/12")
    request = SimpleNamespace(
        remote="172.18.0.5",
        headers=SimpleNamespace(getall=lambda name, default: ["198.51.100.7"]),
    )
    assert service._request_ip(request) == "198.51.100.7"
    request.remote = "203.0.113.9"
    assert service._request_ip(request) == "203.0.113.9"


def test_rate_buckets_are_pruned_and_capped(store, monkeypatch) -> None:
    monkeypatch.setattr(web_service, "RATE_BUCKET_LIMIT", 10)
    service = BindingWebService(store, object(), Path("x.zip"))
    for index in range(30):
        service._requests[(f"198.51.100.{index}", "default")].append(float(index))
    service._prune_rate_buckets(now=1000.0)
    assert not service._requests  # 全部超出 60s 窗口

    for index in range(30):
        service._requests[(f"198.51.100.{index}", "default")].append(1000.0 + index)
    service._prune_rate_buckets(now=1030.0)
    assert len(service._requests) < 10
    assert ("198.51.100.29", "default") in service._requests


# ------------------------------------------------------------------ AUD-018 / AUD-025 配置

@pytest.mark.parametrize(
    ("raw", "expected"),
    [("false", False), ("False", False), ("0", False), ("off", False), ("关", False),
     ("true", True), ("1", True), ("on", True), (1, True), (0, False), ("maybe", None), (2, None), (None, None)],
)
def test_boolean_config_is_strict(raw, expected) -> None:
    for default in (True, False):
        assert bounded_bool(raw, default=default) is (default if expected is None else expected)


def test_normalize_runtime_config_rejects_string_false_and_bad_proxy() -> None:
    config = normalize_runtime_config(
        {"enable_daily_actions": "false", "allow_group_bind": "true", "web_trusted_proxy_ip": "caddy",
         "binding_api_key": None, "web_host": 123}
    )
    assert config["enable_daily_actions"] is False
    assert config["allow_group_bind"] is True
    assert config["enable_cdk_redemption"] is False
    assert config["voice_dynamic_enabled"] is True
    assert config["web_trusted_proxy_ip"] == ""
    assert config["binding_api_key"] == ""
    assert config["web_host"] == "123"
    assert normalize_runtime_config({"web_trusted_proxy_ip": " 10.0.0.1 "})["web_trusted_proxy_ip"] == "10.0.0.1/32"


# ------------------------------------------------------------------ AUD-006 CDK 文案

@pytest.mark.asyncio
@pytest.mark.parametrize(("operation", "method"), [("available", "get_cdk_redemption"), ("history", "get_cdk_redemption_history")])
async def test_cdk_errors_do_not_echo_raw_exception(operation, method) -> None:
    store = SimpleNamespace(
        get_account=lambda actor_id, with_cookie=True: {"qq_id": actor_id, "game_uid": "g", "cookie": "c"},
        mark_cookie_invalid=lambda actor_id: None,
    )
    client = AsyncMock()
    getattr(client, method).side_effect = RuntimeError("game_token=LEAKED-SECRET upstream exploded")
    handler = CdkCommandHandler(account_reader=store, store=store, client=client, service=AsyncMock(),
                                config={"enable_cdk_redemption": True})
    result = await handler.handle(CommandContext(actor_id="qq-1", parameters={"operation": operation}))
    text = " ".join(getattr(message, "text", "") for message in result.messages)
    assert "LEAKED-SECRET" not in text and "RuntimeError" not in text
    assert "请稍后重试" in text


# ------------------------------------------------------------------ AUD-003 调度器取消

@pytest.mark.asyncio
async def test_scheduler_propagates_cancellation() -> None:
    coordinator = SimpleNamespace(closing=False, create_task=lambda coroutine: asyncio.ensure_future(coroutine))

    class _Store:
        def get_setting(self, key, default=None):
            raise asyncio.CancelledError

    scheduler = RuntimeScheduler(
        coordinator=coordinator, store=_Store(),
        config={"daily_hour": 8, "daily_minute": 0, "summary_hour": 8, "summary_minute": 30},
        run_daily=AsyncMock(), send_summary=AsyncMock(), sync_announcements=AsyncMock(),
        sync_calendar=AsyncMock(), dispatch_announcements=AsyncMock(), sleep=AsyncMock(),
    )
    with pytest.raises(asyncio.CancelledError):
        await scheduler.run()


# ------------------------------------------------------------------ AUD-011 停服顺序

def test_cleanup_order_stops_web_first_and_client_last() -> None:
    registered: list[str] = []
    services = SimpleNamespace(
        web=SimpleNamespace(stop=AsyncMock()),
        asset_manager=SimpleNamespace(close=AsyncMock()),
        voice_application=SimpleNamespace(close=AsyncMock()),
        feedback_manager=SimpleNamespace(close=AsyncMock()),
        calendar=SimpleNamespace(aclose=AsyncMock()),
        client=SimpleNamespace(aclose=AsyncMock()),
    )
    adapter = SimpleNamespace(
        _services=services,
        _coordinator=SimpleNamespace(register_cleanup=lambda name, _fn: registered.append(name)),
    )
    AstrBotRuntimeAdapter._register_cleanup(adapter)
    shutdown_order = list(reversed(registered))
    assert shutdown_order[0] == "web"
    assert shutdown_order[-1] == "client"
    assert shutdown_order == ["web", "assets", "voice", "feedback", "calendar", "client"]


# ------------------------------------------------------------------ AUD-018 句柄与渲染缓存

@pytest.mark.asyncio
async def test_feedback_handles_released_when_cancelled_before_start() -> None:
    manager = DelayedFeedbackManager(task_factory=asyncio.ensure_future)
    handles = [manager.start_delayed_feedback(AsyncMock(), delay=10) for _ in range(3)]
    for handle in handles:
        handle.delayed_task.cancel()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert manager._active_handles == set()


def test_renderer_not_cached_until_host_html_render_available() -> None:
    host: dict[str, object] = {"render": None}
    presentation = AstrBotCommandPresentation(
        services=SimpleNamespace(asset_manager=None),
        html_render=lambda: host["render"],
        context=SimpleNamespace(),
    )
    first = presentation._renderer()
    assert presentation._t2i_renderer is None
    host["render"] = AsyncMock()
    second = presentation._renderer()
    assert second is not first
    assert presentation._renderer() is second

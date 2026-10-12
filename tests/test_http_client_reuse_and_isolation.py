# SPDX-License-Identifier: GPL-3.0-or-later
"""HTTP 客户端复用与严格 Cookie 隔离测试套件 (Phase C1)。"""

from __future__ import annotations

import asyncio
from typing import Any
import httpx
import pytest

from astrbot_plugin_nikke.integrations.blablalink.client import (
    BlaBlaClient,
    BlaBlaTimeoutError,
    CookieExpired,
    API_BASE,
)
from astrbot_plugin_nikke.integrations.blablalink.fetch_client import (
    FetchClient,
)
from astrbot_plugin_nikke.integrations.blablalink.http_transport import (
    IsolatedAsyncClient,
    IsolatedCookies,
)


@pytest.mark.asyncio
async def test_isolated_cookies_never_stores_response_set_cookie():
    """验证 IsolatedCookies 永不将响应 Set-Cookie 写入 CookieJar。"""
    cookies = IsolatedCookies()
    request = httpx.Request("GET", "https://api.blablalink.com/test")
    response = httpx.Response(
        200,
        request=request,
        headers={"Set-Cookie": "session_token=secret_xyz; Path=/; Domain=api.blablalink.com"},
    )
    cookies.extract_cookies(response)
    assert len(cookies) == 0
    assert list(cookies.items()) == []


@pytest.mark.asyncio
async def test_blabla_client_reuses_underlying_client_across_calls():
    """验证同服务实例连续请求只创建一次对应客户端，不同服务实例互不影响。"""
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "0", "data": {"status": "ok"}})

    transport1 = httpx.MockTransport(handler)
    transport2 = httpx.MockTransport(handler)

    client1 = BlaBlaClient(transport=transport1)
    client2 = BlaBlaClient(transport=transport2)

    try:
        # Client 1 请求
        resp1_a = await client1._post("/test", "cookie_1", {"k": 1})
        underlying_client1 = client1._client
        assert underlying_client1 is not None

        resp1_b = await client1._post("/test", "cookie_1", {"k": 2})
        assert client1._client is underlying_client1  # 复用同一实例

        # Client 2 独立实例
        resp2_a = await client2._post("/test", "cookie_2", {"k": 3})
        underlying_client2 = client2._client
        assert underlying_client2 is not None
        assert underlying_client2 is not underlying_client1  # 不同实例互不影响

    finally:
        await client1.aclose()
        await client2.aclose()


@pytest.mark.asyncio
async def test_blabla_client_aclose_is_idempotent_and_prevents_subsequent_requests():
    """验证关闭两次安全（幂等），关闭后禁止发起新请求，且不静默重开。"""
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "0", "data": {}})

    transport = httpx.MockTransport(handler)
    client = BlaBlaClient(transport=transport)

    await client._post("/test", "cookie_1", {})
    assert client._client is not None

    # 关闭第一次
    await client.aclose()
    assert client._client is None
    assert client._closed is True

    # 关闭第二次（必须幂等无异常）
    await client.aclose()
    assert client._closed is True

    # 关闭后禁止发请求，抛出 RuntimeError
    with pytest.raises(RuntimeError, match="已关闭"):
        await client._post("/test", "cookie_1", {})

    with pytest.raises(RuntimeError, match="已关闭"):
        await client.get_directory()


@pytest.mark.asyncio
async def test_cookie_strict_isolation_between_accounts_and_public_cdn():
    """验证 Set-Cookie 绝不污染共享 jar，账号 A 与账号 B 及公开请求 Cookie 严格隔离。"""
    captured_requests: list[tuple[str, str]] = []

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        cookie_header = request.headers.get("cookie", "")
        captured_requests.append((str(request.url), cookie_header))
        # CDN 目录返回 list
        if "cdn" in str(request.url):
            return httpx.Response(200, json=[])
        # 模拟服务端下发敏感 Set-Cookie
        return httpx.Response(
            200,
            headers={"Set-Cookie": f"server_assigned={cookie_header}; Path=/; Domain=blablalink.com"},
            json={"code": "0", "data": {"echo": cookie_header}},
        )

    transport = httpx.MockTransport(mock_handler)
    client = BlaBlaClient(transport=transport)

    try:
        # 1. 账号 A 发起请求
        await client._post("/user/info", "token_a=111", {})
        assert len(client._client.cookies) == 0  # 绝不吸收进 client.cookies

        # 2. 账号 B 发起请求
        await client._post("/user/info", "token_b=222", {})
        assert len(client._client.cookies) == 0

        # 3. 公开请求（例如 get_directory CDN 请求）
        await client.get_directory()

        # 校验各请求携带的实际 Cookie 头部
        # captured_requests[0]: A 请求，只带 token_a
        assert captured_requests[0][1] == "token_a=111"
        # captured_requests[1]: B 请求，只带 token_b，绝不含 token_a
        assert captured_requests[1][1] == "token_b=222"
        # captured_requests[2] & [3]: CDN 请求，绝不携带任何 Cookie
        assert captured_requests[2][1] == ""
        assert captured_requests[3][1] == ""

    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_concurrent_requests_cookie_isolation():
    """并发场景下，大量不同账号的 Cookie 头部严格隔离，无并发状态竞态。"""
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        req_cookie = request.headers.get("cookie", "")
        await asyncio.sleep(0.01)  # 模拟网络延时触发并发交错
        return httpx.Response(
            200,
            headers={"Set-Cookie": f"secret={req_cookie}; Path=/"},
            json={"code": "0", "data": {"echo": req_cookie}},
        )

    transport = httpx.MockTransport(mock_handler)
    client = BlaBlaClient(transport=transport)

    try:
        async def call_user(i: int):
            cookie = f"user_{i}=token_{i}"
            res = await client._post("/api/action", cookie, {"idx": i})
            return i, res["data"]["echo"]

        tasks = [call_user(i) for i in range(50)]
        results = await asyncio.gather(*tasks)

        for i, echo in results:
            expected = f"user_{i}=token_{i}"
            assert echo == expected, f"并发 Cookie 污染：期望 {expected}，实际收到 {echo}"

        assert len(client._client.cookies) == 0

    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_code_11003_and_token_expired_retained():
    """验证错误码 11003 及 Token 失效错误语义严格保留。"""
    async def handler_expired(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "11003", "msg": "token expired"})

    transport = httpx.MockTransport(handler_expired)
    client = BlaBlaClient(transport=transport)

    try:
        with pytest.raises(CookieExpired) as exc:
            await client._post("/test", "cookie", {})
        assert exc.value.code == "11003"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_fetch_client_reuse_and_aclose():
    """验证 FetchClient 客户端复用、单次超时覆盖与优雅关闭。"""
    call_count = 0

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"result": "ok", "call": call_count})

    transport = httpx.MockTransport(mock_handler)
    fetch_client = FetchClient(transport=transport, max_retries=1)

    try:
        data1 = await fetch_client.get_json("https://example.com/api/1")
        assert data1["call"] == 1
        underlying = fetch_client._client
        assert underlying is not None

        # 第二次请求复用同一 underlying 实例
        data2 = await fetch_client.get_json("https://example.com/api/2", timeout=2.5)
        assert data2["call"] == 2
        assert fetch_client._client is underlying

        # 关闭
        await fetch_client.aclose()
        assert fetch_client._closed is True
        assert fetch_client._client is None

        # 关闭后请求被阻断
        with pytest.raises(RuntimeError, match="已关闭"):
            await fetch_client.get_json("https://example.com/api/3")

    finally:
        await fetch_client.aclose()

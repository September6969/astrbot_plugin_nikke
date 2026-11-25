# SPDX-License-Identifier: GPL-3.0-or-later
"""ShiftyPad 同源会话网页：引导兑换、Cookie+CSRF+Origin、禁用开关与隐私边界（aiohttp 本地）。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from astrbot_plugin_nikke.features.shiftypad.identity import (
    UidMappingResolver,
    official_share_url,
)
from astrbot_plugin_nikke.features.shiftypad.models import (
    ShiftypadIdentity,
    ShiftypadPrivateError,
    ShiftypadProfile,
    ShiftypadUpstreamError,
)
from astrbot_plugin_nikke.features.shiftypad.storage import ShiftypadReadOnlyStore
from astrbot_plugin_nikke.integrations.web.shiftypad_service import (
    COOKIE,
    CSRF_HEADER,
    ShiftypadWebService,
)

OPENID = "12345-1234567890"
ORIGIN = "https://example.test"


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def get_setting(self, key, default=None):
        return self.values.get(key, default)

    def set_setting(self, key, value):
        self.values[key] = value


def mapping() -> UidMappingResolver:
    return UidMappingResolver.from_payload(
        {
            "schema_version": 1,
            "status": "OPERATOR_VERIFIED",
            "source_url": "https://example.invalid/shiftypad-map.json",
            "checked_at": "2026-11-23",
            "entries": [
                {"uid": "123456789", "server": "na", "openid": OPENID, "area_id": "83"}
            ],
        }
    )


def identity() -> ShiftypadIdentity:
    return ShiftypadIdentity(
        openid=OPENID, uid="123456789", server="na", area_id="83",
        source="trusted_mapping", source_url=official_share_url(OPENID),
    )


def profile(nickname: str = "公开昵称", level: int = 300) -> ShiftypadProfile:
    return ShiftypadProfile(
        identity=identity(),
        nickname=nickname,
        level=level,
        team_combat=123456,
        nikke_count=2,
        synchro_level=200,
        visibility="public",
        fetched_at="2026-11-23T00:00:00+00:00",
    )


class FakeFetcher:
    def __init__(self) -> None:
        self.value = profile()
        self.error: Exception | None = None
        self.calls = 0

    async def fetch(self, _identity):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.value


async def build(clock, *, enabled_box=None, session_ttl: int = 3600, access_log=object()):
    store = MemoryStore()
    readonly = ShiftypadReadOnlyStore(store, clock=lambda: datetime.now(timezone.utc))
    fetcher = FakeFetcher()
    flag = enabled_box if enabled_box is not None else [True]
    service = ShiftypadWebService(
        store=store,
        readonly=readonly,
        resolver=mapping(),
        fetcher=fetcher,
        site_origin=ORIGIN,
        clock=clock,
        session_ttl=session_ttl,
        enabled=lambda: flag[0],
    )
    app = web.Application()
    service.mount(app)
    server_kwargs = {} if type(access_log) is object else {"access_log": access_log}
    client = TestClient(TestServer(app, **server_kwargs))
    await client.start_server()
    return client, service, store, fetcher, readonly


def token_from(link: str) -> str:
    return link.rsplit("/", 1)[-1]


async def claim_headers(client: TestClient, token: str) -> dict[str, str]:
    claimed = await client.post(
        "/shiftypad/api/claim",
        data={"token": token},
        headers={"Origin": ORIGIN},
        allow_redirects=False,
    )
    assert claimed.status == 303
    assert claimed.headers["Location"] == "/shiftypad/edit"
    morsel = claimed.cookies[COOKIE]
    assert morsel["secure"] and morsel["httponly"] and morsel["samesite"] == "Lax"
    cookie = morsel.value
    state = await client.get("/shiftypad/api/state", headers={"Cookie": f"{COOKIE}={cookie}"})
    assert state.status == 200
    body = await state.json()
    return {
        "Cookie": f"{COOKIE}={cookie}",
        "Origin": ORIGIN,
        CSRF_HEADER: body["csrf"],
    }


@pytest.mark.asyncio
async def test_open_claim_preview_bind_sync_unbind_and_csp() -> None:
    clock = [1000.0]
    client, service, _, fetcher, _ = await build(lambda: clock[0])
    try:
        link = service.create_link("user-a")
        assert link.startswith(f"{ORIGIN}/shiftypad/open/")
        token = token_from(link)

        # GET /shiftypad/open/{token} 不消费令牌、禁止被嵌入、无 unsafe-inline。
        open_resp = await client.get(f"/shiftypad/open/{token}")
        assert open_resp.status == 200
        csp = open_resp.headers["Content-Security-Policy"]
        assert "frame-ancestors 'none'" in csp
        assert "unsafe-inline" not in csp
        assert open_resp.headers["Referrer-Policy"] == "no-referrer"

        headers = await claim_headers(client, token)
        # 一次性令牌不能二次兑换。
        replay = await client.post(
            "/shiftypad/api/claim",
            data={"token": token},
            headers={"Origin": ORIGIN},
        )
        assert replay.status == 410

        edit_page = await client.get("/shiftypad/edit", headers={"Cookie": headers["Cookie"]})
        assert edit_page.status == 200
        edit_html = await edit_page.text()
        assert "ShiftyPad 只读导入" in edit_html
        assert token not in edit_html

        state = await client.get("/shiftypad/api/state", headers={"Cookie": headers["Cookie"]})
        body = await state.json()
        assert body["ok"] and body["status"] == "unbound"
        assert body["uid_standalone_supported"] is False

        no_confirm = await client.post(
            "/shiftypad/api/preview",
            headers=headers,
            json={"uid": "123456789", "server": "na", "confirmed_public": False},
        )
        assert no_confirm.status == 400
        assert (await no_confirm.json())["code"] == "PUBLIC_CONFIRM_REQUIRED"

        uid_only = await client.post(
            "/shiftypad/api/preview",
            headers=headers,
            json={"uid": "999999999", "server": "jp", "confirmed_public": True},
        )
        assert uid_only.status == 400
        assert (await uid_only.json())["code"] == "UID_UNRESOLVED"

        preview = await client.post(
            "/shiftypad/api/preview",
            headers=headers,
            json={
                "uid": "123456789",
                "server": "na",
                "public_ref": official_share_url(OPENID),
                "confirmed_public": True,
            },
        )
        assert preview.status == 200
        preview_body = await preview.json()
        assert preview_body["nickname"] == "公开昵称"
        assert "openid" not in preview_body.get("identity", {})

        bound = await client.post(
            "/shiftypad/api/bind",
            headers=headers,
            json={"preview_id": preview_body["preview_id"]},
        )
        assert bound.status == 200
        assert (await bound.json())["status"]["nickname"] == "公开昵称"
        bound_state = await client.get("/shiftypad/api/state", headers={"Cookie": headers["Cookie"]})
        assert OPENID not in await bound_state.text()

        fetcher.value = profile("新昵称", 301)
        synced = await client.post("/shiftypad/api/sync", headers=headers, json={})
        assert synced.status == 200
        assert (await synced.json())["binding"]["level"] == 301

        fetcher.error = ShiftypadPrivateError("公开开关已关闭")
        stale = await client.post("/shiftypad/api/sync", headers=headers, json={})
        assert stale.status == 409
        assert (await stale.json())["code"] == "PRIVATE"

        # stale 状态依然允许重试恢复。
        fetcher.error = None
        fetcher.value = profile("恢复昵称", 302)
        recovered = await client.post("/shiftypad/api/sync", headers=headers, json={})
        assert recovered.status == 200
        assert (await recovered.json())["status"] == "ready"

        unbound = await client.post("/shiftypad/api/unbind", headers=headers, json={})
        assert unbound.status == 200
        final_state = await client.get("/shiftypad/api/state", headers={"Cookie": headers["Cookie"]})
        assert (await final_state.json())["status"] == "unbound"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_security_boundaries_origin_csrf_body_limit_and_disable_switch() -> None:
    clock = [1000.0]
    enabled = [True]
    client, service, _, _, _ = await build(lambda: clock[0], enabled_box=enabled, session_ttl=600)
    try:
        assert (await client.get("/shiftypad/edit")).status == 401
        token_a = token_from(service.create_link("user-a"))
        token_b = token_from(service.create_link("user-b"))
        headers_a = await claim_headers(client, token_a)
        headers_b = await claim_headers(client, token_b)

        # Origin 与 CSRF 防护。
        bad_origin = await client.post(
            "/shiftypad/api/unbind",
            headers={"Cookie": headers_a["Cookie"], "Origin": "https://evil.example", CSRF_HEADER: headers_a[CSRF_HEADER]},
            json={},
        )
        assert bad_origin.status == 403
        assert (await bad_origin.json())["code"] == "FORBIDDEN_ORIGIN"

        bad_csrf = await client.post(
            "/shiftypad/api/unbind",
            headers={"Cookie": headers_a["Cookie"], "Origin": ORIGIN, CSRF_HEADER: "wrong"},
            json={},
        )
        assert bad_csrf.status == 403
        assert (await bad_csrf.json())["code"] == "FORBIDDEN_CSRF"

        # 超过 16KB 的请求体必须被 413 拦截。
        oversized = await client.post(
            "/shiftypad/api/preview",
            headers=headers_a,
            json={"confirmed_public": True, "public_ref": "a" * (20 * 1024)},
        )
        assert oversized.status == 413

        # B 用户看不到 A 的绑定。
        ok_p = await client.post(
            "/shiftypad/api/preview",
            headers=headers_a,
            json={"uid": "123456789", "server": "na", "public_ref": official_share_url(OPENID), "confirmed_public": True},
        )
        pid = (await ok_p.json())["preview_id"]
        assert (await client.post("/shiftypad/api/bind", headers=headers_a, json={"preview_id": pid})).status == 200
        assert (await (await client.get("/shiftypad/api/state", headers={"Cookie": headers_b["Cookie"]})).json())["status"] == "unbound"

        # 会话过期后不可用。
        clock[0] += 601
        assert (await client.get("/shiftypad/api/state", headers={"Cookie": headers_a["Cookie"]})).status == 401

        # 关闭配置开关后 fail-closed。
        enabled[0] = False
        with pytest.raises(ValueError, match="enable_shiftypad_readonly"):
            service.create_link("user-c")
        assert (await client.get("/shiftypad/api/state", headers={"Cookie": headers_b["Cookie"]})).status == 404
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_upstream_failure_and_preview_mismatch_are_explicit() -> None:
    clock = [1000.0]
    client, service, _, fetcher, _ = await build(lambda: clock[0])
    try:
        headers = await claim_headers(client, token_from(service.create_link("user-a")))
        fetcher.error = ShiftypadUpstreamError("上游 503")
        failed = await client.post(
            "/shiftypad/api/preview",
            headers=headers,
            json={"uid": "", "server": "", "public_ref": official_share_url(OPENID), "confirmed_public": True},
        )
        assert failed.status == 502
        assert (await failed.json())["code"] == "UPSTREAM"

        fetcher.error = None
        ok = await client.post(
            "/shiftypad/api/preview",
            headers=headers,
            json={"uid": "", "server": "", "public_ref": official_share_url(OPENID), "confirmed_public": True},
        )
        body = await ok.json()
        mismatch = await client.post(
            "/shiftypad/api/bind", headers=headers, json={"preview_id": "wrong"}
        )
        assert mismatch.status == 400
        assert (await mismatch.json())["code"] == "PREVIEW_MISMATCH"
        assert body["preview_id"] != "wrong"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_shiftypad_referrer_policy_and_zero_token_leakage_in_logs(caplog) -> None:
    import logging
    from types import SimpleNamespace
    from aiohttp import ClientSession
    from astrbot_plugin_nikke.integrations.web.service import BindingWebService

    # 使用与生产 BindingWebService.start 一致的 web.AppRunner(..., access_log=None) 启动真实服务。
    store = MemoryStore()
    readonly = ShiftypadReadOnlyStore(store, clock=lambda: datetime.now(timezone.utc))
    service = ShiftypadWebService(
        store=store,
        readonly=readonly,
        resolver=mapping(),
        fetcher=FakeFetcher(),
        site_origin=ORIGIN,
        clock=lambda: 1000.0,
        session_ttl=3600,
        enabled=lambda: True,
    )
    web_service = BindingWebService(store, SimpleNamespace(), mapping_path := None, public_base_url=ORIGIN)  # type: ignore[arg-type]
    assert mapping_path is None
    web_service.add_route_installer(service.mount)
    runner = web.AppRunner(web_service.app(), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
    base_url = f"http://127.0.0.1:{port}"
    try:
        link = service.create_link("user-a")
        token = token_from(link)
        with caplog.at_level(logging.DEBUG):
            async with ClientSession() as session:
                async with session.get(f"{base_url}/shiftypad/open/{token}") as open_resp:
                    assert open_resp.status == 200
                    assert open_resp.headers["Referrer-Policy"] == "no-referrer"
                    assert '<meta name="referrer" content="no-referrer">' in await open_resp.text()

                async with session.post(
                    f"{base_url}/shiftypad/api/claim",
                    data={"token": token},
                    headers={"Origin": ORIGIN},
                    allow_redirects=False,
                ) as claim_resp:
                    assert claim_resp.status == 303
                    assert claim_resp.headers["Referrer-Policy"] == "no-referrer"
                    cookie_val = claim_resp.cookies[COOKIE].value

                cookie_header = {"Cookie": f"{COOKIE}={cookie_val}"}
                async with session.get(f"{base_url}/shiftypad/edit", headers=cookie_header) as edit_resp:
                    assert edit_resp.status == 200
                    assert edit_resp.headers["Referrer-Policy"] == "no-referrer"
                    assert '<meta name="referrer" content="no-referrer">' in await edit_resp.text()

                async with session.get(f"{base_url}/shiftypad/static/editor.js") as static_resp:
                    assert static_resp.status == 200
                    assert static_resp.headers["Referrer-Policy"] == "no-referrer"

                async with session.post(
                    f"{base_url}/shiftypad/api/claim",
                    data={"token": token},
                    headers={"Origin": ORIGIN},
                ) as bad_resp:
                    assert bad_resp.status == 410
                    assert token not in await bad_resp.text()

        for record in caplog.records:
            rendered = record.getMessage()
            assert token not in rendered
            assert cookie_val not in rendered
    finally:
        await runner.cleanup()

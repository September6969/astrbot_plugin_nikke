# SPDX-License-Identifier: GPL-3.0-or-later
"""ShiftyPad 短时网页：成功、公开确认、过期、跨用户与隐私边界（aiohttp 本地）。"""

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
from astrbot_plugin_nikke.integrations.web.shiftypad_service import ShiftypadWebService

OPENID = "12345-1234567890"


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


async def build(clock):
    store = MemoryStore()
    readonly = ShiftypadReadOnlyStore(store, clock=lambda: datetime.now(timezone.utc))
    fetcher = FakeFetcher()
    service = ShiftypadWebService(
        store=store,
        readonly=readonly,
        resolver=mapping(),
        fetcher=fetcher,
        site_origin="https://example.test",
        clock=clock,
    )
    app = web.Application()
    service.mount(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client, service, store, fetcher, readonly


def token_from(link: str) -> str:
    return link.rsplit("/", 1)[-1]


@pytest.mark.asyncio
async def test_page_preview_bind_sync_and_unbind_flow() -> None:
    clock = [1000.0]
    client, service, _, fetcher, _ = await build(lambda: clock[0])
    try:
        link = service.create_link("user-a")
        token = token_from(link)
        page = await client.get(f"/shiftypad/{token}")
        assert page.status == 200
        assert "ShiftyPad 只读导入" in await page.text()

        state = await client.get("/api/shiftypad/state", params={"token": token})
        body = await state.json()
        assert body["ok"] and body["status"] == "unbound"
        assert body["uid_standalone_supported"] is False

        # 未确认公开/授权时拒绝预览。
        no_confirm = await client.post(
            "/api/shiftypad/preview",
            json={"token": token, "uid": "123456789", "server": "na", "confirmed_public": False},
        )
        assert no_confirm.status == 400
        assert (await no_confirm.json())["code"] == "PUBLIC_CONFIRM_REQUIRED"

        # 只有数字 UID 且无可信映射时明确 unresolved，不猜接口。
        uid_only = await client.post(
            "/api/shiftypad/preview",
            json={"token": token, "uid": "999999999", "server": "jp", "confirmed_public": True},
        )
        assert uid_only.status == 400
        assert (await uid_only.json())["code"] == "UID_UNRESOLVED"

        preview = await client.post(
            "/api/shiftypad/preview",
            json={
                "token": token,
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
        assert preview_body["preview_id"]

        bound = await client.post(
            "/api/shiftypad/bind",
            json={"token": token, "preview_id": preview_body["preview_id"]},
        )
        assert bound.status == 200
        assert (await bound.json())["status"]["nickname"] == "公开昵称"
        bound_state = await client.get("/api/shiftypad/state", params={"token": token})
        bound_state_text = await bound_state.text()
        assert OPENID not in bound_state_text
        assert (await bound_state.json())["uid_mapping_available"] is True

        fetcher.value = profile("新昵称", 301)
        synced = await client.post("/api/shiftypad/sync", json={"token": token})
        assert synced.status == 200
        synced_body = await synced.json()
        assert synced_body["changed"] is True
        assert synced_body["binding"]["level"] == 301

        fetcher.error = ShiftypadPrivateError("公开开关已关闭")
        stale = await client.post("/api/shiftypad/sync", json={"token": token})
        assert stale.status == 409
        stale_body = await stale.json()
        assert stale_body["code"] == "PRIVATE"
        assert stale_body["binding"]["nickname"] == "新昵称"

        unbound = await client.post("/api/shiftypad/unbind", json={"token": token})
        assert unbound.status == 200
        final_state = await client.get("/api/shiftypad/state", params={"token": token})
        assert (await final_state.json())["status"] == "unbound"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_expiry_cross_user_and_invalid_tokens() -> None:
    clock = [1000.0]
    client, service, _, _, _ = await build(lambda: clock[0])
    try:
        token_a = token_from(service.create_link("user-a"))
        token_b = token_from(service.create_link("user-b"))
        assert (await client.get(f"/shiftypad/{'x' * 32}")).status == 410

        # user-b 的入口看不到 user-a 的绑定；两个入口只按 token 所属用户操作。
        preview = await client.post(
            "/api/shiftypad/preview",
            json={
                "token": token_a, "uid": "123456789", "server": "na",
                "public_ref": official_share_url(OPENID), "confirmed_public": True,
            },
        )
        assert preview.status == 200
        preview_id = (await preview.json())["preview_id"]
        assert (await client.post(
            "/api/shiftypad/bind", json={"token": token_a, "preview_id": preview_id}
        )).status == 200
        state_b = await client.get("/api/shiftypad/state", params={"token": token_b})
        assert (await state_b.json())["status"] == "unbound"

        clock[0] += 601
        expired = await client.get("/api/shiftypad/state", params={"token": token_a})
        assert (await expired.json())["status"] == "expired"
        expired_page = await client.get(f"/shiftypad/{token_a}")
        assert expired_page.status == 410

        invalid = await client.post(
            "/api/shiftypad/preview",
            json={"token": "short", "confirmed_public": True},
        )
        assert invalid.status == 410
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_upstream_failure_and_preview_mismatch_are_explicit() -> None:
    clock = [1000.0]
    client, service, _, fetcher, _ = await build(lambda: clock[0])
    try:
        token = token_from(service.create_link("user-a"))
        fetcher.error = ShiftypadUpstreamError("上游 503")
        failed = await client.post(
            "/api/shiftypad/preview",
            json={
                "token": token, "uid": "", "server": "",
                "public_ref": official_share_url(OPENID), "confirmed_public": True,
            },
        )
        assert failed.status == 502
        assert (await failed.json())["code"] == "UPSTREAM"

        fetcher.error = None
        ok = await client.post(
            "/api/shiftypad/preview",
            json={
                "token": token, "uid": "", "server": "",
                "public_ref": official_share_url(OPENID), "confirmed_public": True,
            },
        )
        body = await ok.json()
        mismatch = await client.post(
            "/api/shiftypad/bind", json={"token": token, "preview_id": "wrong"}
        )
        assert mismatch.status == 400
        assert (await mismatch.json())["code"] == "PREVIEW_MISMATCH"
        assert body["preview_id"] != "wrong"
    finally:
        await client.close()

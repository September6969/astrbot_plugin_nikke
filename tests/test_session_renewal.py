"""续期全部外部写入使用 MockTransport 或模拟网关，不加载真实账号。"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
import json
import sqlite3
import time
import uuid
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from astrbot_plugin_nikke.core.storage import NikkeStore
from astrbot_plugin_nikke.features.account.renewal import SessionRenewalService
from astrbot_plugin_nikke.features.account.renewal_errors import RenewalFailure
from astrbot_plugin_nikke.features.daily.runner import DailyRunner
from astrbot_plugin_nikke.features.daily.action_models import binding_stamp
from astrbot_plugin_nikke.integrations.blablalink.client import BlaBlaClient
from astrbot_plugin_nikke.integrations.blablalink.community_actions import CommunityActionsGateway
from astrbot_plugin_nikke.integrations.blablalink.session_renewal import SessionRenewalGateway
from astrbot_plugin_nikke.integrations.blablalink.session_cookies import (
    apply_set_cookies, capture_material, cookie_header, renewal_payload,
)


NOW = 1792670400
COOKIE = "game_token=synthetic-old; game_uid=synthetic-game; game_openid=synthetic-openid"


def material():
    values = {"game_token": "synthetic-old", "game_uid": "synthetic-game", "game_openid": "synthetic-openid"}
    cookies = [{"name": k, "value": v, "domain": ".blablalink.com", "path": "/", "hostOnly": False,
                "expirationDate": NOW + 3600, "secure": True, "httpOnly": True, "sameSite": "lax"} for k, v in values.items()]
    payload = {**values, "game_channelid": 131, "game_id": "synthetic-original-game-id", "game_expire_time": NOW + 7200}
    return capture_material(cookies, payload)


def bind(store, actor="one", *, session=None, cookie=COOKIE, uid="synthetic-game"):
    token = "binding-" + actor + uuid.uuid4().hex
    store.create_bind_session(token, actor, status="pending")
    store.consume_bind_session(token, cookie, uid, "synthetic-openid", "合成账号", "", "3",
        x_common_params=json.dumps({"openid": "synthetic-openid", "intl_game_id": "synthetic-game-id"}),
        success_status="success", session_material=material() if session is None else session)
    return store.get_account(actor)


class RenewalGateway:
    def __init__(self):
        self.identity = AsyncMock(side_effect=["synthetic-openid", "synthetic-openid"])
        candidate = material()
        candidate["cookies"][0]["value"] = "synthetic-new"
        self.request_candidate = AsyncMock(return_value=(COOKIE.replace("synthetic-old", "synthetic-new"), candidate))
        self.invalidate = Mock()


@pytest.fixture
def env(tmp_path):
    store = NikkeStore(tmp_path)
    account = bind(store)
    config = {"enable_daily_actions": True}
    gateway = RenewalGateway()
    service = SessionRenewalService(gateway=gateway, store=store, config=config,
        account_lock=DailyRunner(store=store)._account_lock, preflight=renewal_payload, clock=lambda: NOW)
    return store, account, config, gateway, service


@pytest.mark.asyncio
async def test_verified_same_account_atomic_replacement_and_experimental_claim(env):
    store, account, _, gateway, service = env
    result = await service.execute(account)
    assert result.status == "validated" and "尚未证明有效期延长" in result.detail
    saved = store.get_account("one")
    assert saved["cookie"] != account["cookie"]
    assert saved["binding_generation"] == account["binding_generation"]
    assert saved["binding_revision"] != account["binding_revision"]
    gateway.invalidate.assert_called_once()
    assert "synthetic-new" not in store.db_path.read_bytes().decode("utf-8", errors="ignore")
    assert "session_material" not in store.get_account("one", with_cookie=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["wrong_account", "validation_failed", "no_cookie", "timeout", "hard_expired", "missing", "cancel"])
async def test_failed_renewal_preserves_old_credentials_and_does_not_retry(env, scenario):
    store, account, _, gateway, service = env
    if scenario == "wrong_account": gateway.identity.side_effect = ["synthetic-openid", "other-account"]
    if scenario == "validation_failed": gateway.identity.side_effect = ["synthetic-openid", ValueError("token=synthetic-secret")]
    if scenario == "no_cookie": gateway.request_candidate.side_effect = ValueError("no cookie")
    if scenario == "timeout": gateway.request_candidate.side_effect = TimeoutError("synthetic-secret")
    if scenario == "cancel": gateway.request_candidate.side_effect = asyncio.CancelledError()
    if scenario == "missing": account["session_material"] = {}
    if scenario == "hard_expired": account["session_material"]["login_payload"]["game_expire_time"] = NOW - 1
    if scenario == "cancel":
        with pytest.raises(asyncio.CancelledError): await service.execute(account)
    else:
        result = await service.execute(account)
        assert result.status != "validated" and "synthetic-secret" not in result.detail
    assert store.get_account("one")["cookie"] == COOKIE
    calls = gateway.request_candidate.await_count
    await service.execute(account)
    assert gateway.request_candidate.await_count == calls


@pytest.mark.asyncio
async def test_rebind_during_validation_wins_over_old_candidate(env):
    store, account, _, gateway, service = env
    async def identity(a):
        if a["cookie"] != COOKIE:
            bind(store, cookie="synthetic-rebound", uid="different-game")
        return "synthetic-openid"
    gateway.identity.side_effect = identity
    result = await service.execute(account)
    assert result.status == "binding_changed"
    assert store.get_account("one")["cookie"] == "synthetic-rebound"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["encrypt", "compare", "sql", "cache"])
async def test_storage_failure_cas_and_cache_failure_are_distinguished(env, monkeypatch, failure):
    store, account, _, gateway, service = env
    if failure == "encrypt": monkeypatch.setattr(store._cipher, "encrypt", Mock(side_effect=RuntimeError("synthetic-secret")))
    if failure == "compare": monkeypatch.setattr(store, "replace_session", Mock(return_value=False))
    if failure == "sql": monkeypatch.setattr(store, "replace_session", Mock(side_effect=sqlite3.OperationalError("synthetic-secret")))
    if failure == "cache": gateway.invalidate.side_effect = RuntimeError("synthetic-secret")
    result = await service.execute(account)
    assert "synthetic-secret" not in result.detail
    if failure == "cache":
        assert result.status == "saved_cache_error"
        assert store.get_account("one")["cookie"] != COOKIE
    else:
        assert store.get_account("one")["cookie"] == COOKIE


@pytest.mark.asyncio
async def test_automatic_is_separate_optin_and_expiry_unknown_does_not_probe(env):
    store, account, _, gateway, service = env
    store.set_auto_daily("one", True)
    assert (await service.execute(account, automatic=True)).status == "disabled"
    store.set_setting("session_renewal:auto:one", binding_stamp(account))
    account["session_material"]["cookies"][0].pop("expirationDate")
    assert (await service.execute(account, automatic=True)).status == "not_due"
    gateway.request_candidate.assert_not_awaited()


@pytest.mark.asyncio
async def test_same_account_multibind_and_concurrent_renewal_share_frequency_limit(env):
    store, first, _, gateway, service = env
    second = bind(store, "two")
    gateway.identity.side_effect = None
    gateway.identity.return_value = "synthetic-openid"
    results = await asyncio.gather(service.execute(first), service.execute(second))
    assert gateway.request_candidate.await_count == 1
    assert {r.status for r in results} == {"validated", "frequency_limited"}


@pytest.mark.asyncio
async def test_real_http_contract_validates_candidate_and_never_pollutes_global_cookie_jar(tmp_path):
    store = NikkeStore(tmp_path)
    account = bind(store)
    requests = []
    async def handle(request):
        requests.append((request.url.path, request.headers.get("cookie")))
        if request.url.path.endswith("/Login"):
            body = json.loads(request.content)
            assert body["game_expire_time"] == NOW + 7200
            assert body["game_id"] == "synthetic-original-game-id"
            return httpx.Response(200, json={"code": 0, "data": {}}, headers=[
                ("set-cookie", "game_token=synthetic-new; Domain=.blablalink.com; Path=/; Max-Age=3600; Secure; HttpOnly; SameSite=Strict")])
        if request.url.path.endswith("CheckLogin"):
            return httpx.Response(200, json={"code": 0, "data": {}})
        if request.url.path.endswith("GetUserInfoNew"):
            return httpx.Response(200, json={"code": 0, "data": {"info": {"intl_openid": "synthetic-openid"}}})
        raise AssertionError(request.url.path)
    client = BlaBlaClient(transport=httpx.MockTransport(handle), account_reader=store)
    gateway = SessionRenewalGateway(client, CommunityActionsGateway(client))
    service = SessionRenewalService(gateway=gateway, store=store, config={"enable_daily_actions": True},
        account_lock=DailyRunner(store=store)._account_lock, preflight=renewal_payload, clock=lambda: NOW)
    try:
        assert (await service.execute(account)).status == "validated"
        assert not list((await client._get_client()).cookies.items())
        assert requests[-1][1].startswith("game_token=synthetic-new")
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("body,headers", [({"code": 0}, []), ({"code": 0}, [("set-cookie", "unrelated=x; Path=/")]),
    ({"code": 0}, [("set-cookie", "game_token=gone; Max-Age=0; Path=/")]),
    ({"code": 300001}, [("set-cookie", "game_token=x; Path=/")])])
async def test_http200_code_or_cookie_alone_is_not_renewal_success(tmp_path, body, headers):
    store = NikkeStore(tmp_path)
    account = bind(store)
    client = BlaBlaClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body, headers=headers)))
    gateway = SessionRenewalGateway(client, Mock())
    try:
        with pytest.raises((ValueError, RenewalFailure)): await gateway.request_candidate(account, NOW)
        assert store.get_account("one")["cookie"] == COOKIE
    finally:
        await client.aclose()


def test_cookie_attributes_session_deletion_and_scope_are_preserved():
    initial = material()
    candidate = apply_set_cookies(initial, ["game_token=new; Domain=.blablalink.com; Path=/; Secure; HttpOnly; SameSite=Strict"], NOW)
    token = next(c for c in candidate["cookies"] if c["name"] == "game_token")
    assert token["session"] is True and "expirationDate" not in token
    assert token["secure"] and token["httpOnly"] and token["sameSite"] == "Strict"
    assert "game_token=new" in cookie_header(candidate["cookies"], "https://api.blablalink.com/api/user/CheckLogin", NOW)
    assert cookie_header(candidate["cookies"], "https://unrelated.example/", NOW) == ""
    with pytest.raises(ValueError): apply_set_cookies(initial, ["game_token=x; Domain=unrelated.example; Path=/"], NOW)
    # 仅变更本地过期时间不能构造用例的成功结果。
    changed = deepcopy(initial)
    changed["cookies"][0]["expirationDate"] = NOW + 29 * 86400
    assert renewal_payload({"cookie": COOKIE, "session_material": changed}, NOW)["game_expire_time"] == NOW + 7200


def test_binding_material_filters_password_and_is_optional():
    with pytest.raises(ValueError): capture_material(material()["cookies"], {"password": "never-save"})
    assert capture_material(material()["cookies"])["source"] == "cookies-only"


def test_cache_invalidation_is_scoped_to_stable_game_identity():
    client = BlaBlaClient()
    identity = ("one", "openid", "uid", "3", "rev")
    same = ("two", "openid", "uid", "3", "rev2")
    other = ("other", "different", "uid2", "3", "rev")
    for item in (identity, same, other): client._query_cache[(item, "profile", ())] = (0, {})
    client.invalidate_account_cache({"qq_id": "one", "game_openid": "openid", "game_uid": "uid", "area_id": "3", "binding_revision": "rev"})
    assert list(client._query_cache) == [(other, "profile", ())]


def test_sqlite_atomic_replacement_rolls_back_both_credentials_and_material(env):
    store, account, _, gateway, _ = env
    with store._connect() as conn:
        conn.execute("CREATE TRIGGER reject_session BEFORE UPDATE OF cookie_cipher ON accounts BEGIN SELECT RAISE(ABORT,'synthetic storage rejection'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.replace_session(account, "synthetic-new", {"cookies": []})
    current = store.get_account("one")
    assert current["cookie"] == COOKIE
    assert current["session_material"] == account["session_material"]
    assert current["binding_revision"] == account["binding_revision"]


@pytest.mark.asyncio
async def test_disabling_auto_during_candidate_validation_does_not_replace(env):
    store, account, _, gateway, service = env
    store.set_setting("session_renewal:auto:one", binding_stamp(account))
    async def identity(a):
        if a["cookie"] != COOKIE:
            store.set_setting("session_renewal:auto:one", None)
        return "synthetic-openid"
    gateway.identity.side_effect = identity
    result = await service.execute(account, automatic=True)
    assert result.status == "binding_changed" and store.get_account("one")["cookie"] == COOKIE

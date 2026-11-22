# SPDX-License-Identifier: GPL-3.0-or-later
"""PR-1A：换绑授权边界、绑定会话竞态与密钥就绪（AUD-002 / AUD-007 / AUD-014）。"""

from __future__ import annotations

import stat
import threading
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer
from cryptography.fernet import Fernet

from astrbot_plugin_nikke.core.health import collect_runtime_health
from astrbot_plugin_nikke.core.storage import NikkeStore, encryption_key_ready
from astrbot_plugin_nikke.integrations.web.service import BindingWebService


@pytest.fixture(autouse=True)
def _no_env_key(monkeypatch):
    monkeypatch.delenv("NIKKE_ENCRYPTION_KEY", raising=False)


def _bind(store: NikkeStore, token: str, *, uid: str, openid: str, qq_id: str = "10001") -> str:
    store.create_bind_session(token, qq_id, status="pending")
    return store.consume_bind_session(
        token, "game_token=synthetic", uid, openid, "nick", "role", "81", success_status="success"
    )


# ------------------------------------------------------------------ AUD-002

def test_legacy_row_without_openid_and_same_uid_keeps_authorization(tmp_path) -> None:
    store = NikkeStore(tmp_path)
    qq_id = _bind(store, "t1", uid="uid-a", openid="")
    store.set_auto_daily(qq_id, True)

    _bind(store, "t2", uid="uid-a", openid="openid-a")

    assert store.get_account(qq_id, with_cookie=False)["auto_daily_enabled"] == 1


def test_openid_change_with_same_uid_revokes_authorization(tmp_path) -> None:
    store = NikkeStore(tmp_path)
    qq_id = _bind(store, "t1", uid="uid-a", openid="openid-a")
    store.set_auto_daily(qq_id, True)
    store.set_setting(f"daily_scope_v2:{qq_id}", "community")

    _bind(store, "t2", uid="uid-a", openid="openid-other")

    assert store.get_account(qq_id, with_cookie=False)["auto_daily_enabled"] == 0
    assert store.get_setting(f"daily_scope_v2:{qq_id}", None) is None


def test_rebind_reset_does_not_touch_other_users_or_run_history(tmp_path) -> None:
    store = NikkeStore(tmp_path)
    first = _bind(store, "t1", uid="uid-a", openid="openid-a", qq_id="10001")
    other = _bind(store, "t2", uid="uid-c", openid="openid-c", qq_id="10002")
    for qq_id in (first, other):
        store.set_auto_daily(qq_id, True)
        store.set_setting(f"daily_scope_v2:{qq_id}", "community")
    for status in ("SUCCEEDED", "DISPATCH_INTENT", "UNKNOWN_AFTER_ACTION"):
        assert store.claim_run(f"community:uid-a:{status}", first, "like", initial_status=status)

    _bind(store, "t3", uid="uid-b", openid="openid-b", qq_id="10001")

    assert store.get_account(other, with_cookie=False)["auto_daily_enabled"] == 1
    assert store.get_setting(f"daily_scope_v2:{other}", None) == "community"
    assert {run["status"] for run in store.list_runs(action="like")} == {
        "SUCCEEDED",
        "DISPATCH_INTENT",
        "UNKNOWN_AFTER_ACTION",
    }


def test_first_bind_keeps_default_authorization_off(tmp_path) -> None:
    store = NikkeStore(tmp_path)
    qq_id = _bind(store, "t1", uid="uid-a", openid="openid-a")
    assert store.get_account(qq_id, with_cookie=False)["auto_daily_enabled"] == 0


# ------------------------------------------------------------------ AUD-014

def test_failure_still_recorded_for_unconsumed_session(tmp_path) -> None:
    store = NikkeStore(tmp_path)
    store.create_bind_session("pending-token", "10001", status="pending")

    store.fail_bind_session("pending-token", "cookie rejected", status="failed")

    session = store.get_bind_session("pending-token")
    assert session["status"] == "failed"
    assert session["error"] == "cookie rejected"


# ------------------------------------------------------------------ AUD-007

def test_key_file_is_created_atomically_with_owner_only_permissions(tmp_path) -> None:
    store = NikkeStore(tmp_path)
    mode = stat.S_IMODE(store.key_path.stat().st_mode)
    assert mode == 0o600
    Fernet(store.key_path.read_bytes())
    assert store.has_valid_key()


def test_existing_key_is_never_overwritten(tmp_path) -> None:
    key = Fernet.generate_key()
    (tmp_path / "secret.key").write_bytes(key)

    NikkeStore(tmp_path)

    assert (tmp_path / "secret.key").read_bytes() == key


def test_concurrent_first_start_converges_on_one_key(tmp_path) -> None:
    # 只验证密钥创建竞态；数据库建表不在此并发（生产为单进程单 store）。
    barrier = threading.Barrier(4)
    keys: list[bytes] = []
    errors: list[BaseException] = []

    def start() -> None:
        try:
            store = NikkeStore.__new__(NikkeStore)
            store.key_path = tmp_path / "secret.key"
            barrier.wait()
            keys.append(store._load_or_create_key())
        except BaseException as exc:  # pragma: no cover - 失败时由断言展示
            errors.append(exc)

    threads = [threading.Thread(target=start) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, errors
    assert len(set(keys)) == 1
    assert (tmp_path / "secret.key").read_bytes().strip() == keys[0]


def test_env_key_mode_does_not_create_key_file_and_reports_ready(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NIKKE_ENCRYPTION_KEY", Fernet.generate_key().decode())

    store = NikkeStore(tmp_path)

    assert not store.key_path.exists()
    assert store.has_valid_key()
    snapshot = collect_runtime_health(tmp_path, min_free_bytes=0)
    assert snapshot.secret_key_present
    assert "密钥缺失" not in snapshot.issues


def test_invalid_env_key_is_not_ready(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NIKKE_ENCRYPTION_KEY", "not-a-fernet-key")
    assert not encryption_key_ready(tmp_path / "secret.key")


def test_missing_key_is_not_ready(tmp_path) -> None:
    assert not encryption_key_ready(tmp_path / "secret.key")
    assert "密钥缺失" in collect_runtime_health(tmp_path, min_free_bytes=0).issues


@pytest.mark.asyncio
@pytest.mark.parametrize("env_key", [False, True], ids=["file-key", "env-key"])
async def test_healthz_ready_for_both_key_deployments(tmp_path, monkeypatch, env_key) -> None:
    if env_key:
        monkeypatch.setenv("NIKKE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    store = NikkeStore(tmp_path)
    service = BindingWebService(store, object(), Path("unused-extension.zip"))
    client = TestClient(TestServer(service.app()))
    await client.start_server()
    try:
        response = await client.get("/healthz")
        body = await response.json()
    finally:
        await client.close()

    assert response.status == 200, body
    assert body["storage"] == "ready"

# SPDX-License-Identifier: GPL-3.0-or-later
"""REFACTOR_PLAN_V2 Phase 0 回归基线。

`xfail(strict=True)` 标记的用例记录已复核但尚未修复的缺陷（AUD 编号见计划）。
修复缺陷的 PR 必须同时删除对应标记；若缺陷被意外修好而标记仍在，strict 会让测试变红。
"""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from astrbot_plugin_nikke.core.lifecycle.scheduler import RuntimeScheduler
from astrbot_plugin_nikke.core.privacy import sanitize_log_text
from astrbot_plugin_nikke.core.storage import NikkeStore
from astrbot_plugin_nikke.main import NikkePlugin
from test_command_routing_contract import Event, _plugin_with_recorders


# ---------------------------------------------------------------- 隐私脱敏矩阵

_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2VjcmV0LXNpZ25hdHVyZQ"
_PRIVACY_CASES = (
    pytest.param("GET /api/bind/status?x=1", (), id="short-route-names-kept"),
    pytest.param("Authorization: Bearer LEAKTOKEN1", ("LEAKTOKEN1",), id="authorization-header"),
    pytest.param("game_token=LEAKTOKEN2; game_uid=LEAKUID3", ("LEAKTOKEN2", "LEAKUID3"), id="known-cookie-pairs"),
    pytest.param('{"access_token": "LEAKTOKEN4"}', ("LEAKTOKEN4",), id="json-token"),
    pytest.param("https://x.example/cb?token=LEAKTOKEN5&ok=1", ("LEAKTOKEN5",), id="query-token"),
    pytest.param("Set-Cookie: sessionid=LEAKSESSION6; Path=/", ("LEAKSESSION6",), id="set-cookie-first-pair"),
    pytest.param(
        "Cookie: game_channelid=LEAKCHANNEL7; game_adult_status=1; game_login_game=LEAKLOGIN8",
        ("LEAKCHANNEL7", "LEAKLOGIN8"),
        id="AUD-006-full-cookie-header",
    ),
    pytest.param(
        "open https://nikke.example.com/bind/LEAKBIND9xxxxxxxxxxxxxxxxxxxxxxxxxxxx now",
        ("LEAKBIND9",),
        id="AUD-006-bind-link-token",
    ),
    pytest.param(
        "GET /arena/open/LEAKARENA10xxxxxxxxxxxxxxxxxxxxxx?x=1",
        ("LEAKARENA10",),
        id="AUD-006-arena-link-token",
    ),
    pytest.param(
        f"upstream said Bearer {_JWT}",
        (_JWT.split(".")[-1],),
        id="AUD-006-bare-bearer-jwt",
    ),
    pytest.param(
        'password="LEAK PART11"',
        ("PART11",),
        id="AUD-006-quoted-value-with-space",
    ),
)


@pytest.mark.parametrize(("text", "secrets"), _PRIVACY_CASES)
def test_privacy_boundary_matrix(text: str, secrets: tuple[str, ...]) -> None:
    sanitized = sanitize_log_text(text, max_length=1000)
    for secret in secrets:
        assert secret not in sanitized, sanitized


# ---------------------------------------------------------------- 换绑与绑定会话

def _bind(store: NikkeStore, token: str, *, uid: str, openid: str) -> str:
    store.create_bind_session(token, "10001", status="pending")
    return store.consume_bind_session(
        token,
        "game_token=synthetic-token",
        uid,
        openid,
        "nickname",
        "role",
        "81",
        success_status="success",
    )


@pytest.fixture
def store(tmp_path, monkeypatch) -> NikkeStore:
    monkeypatch.delenv("NIKKE_ENCRYPTION_KEY", raising=False)
    return NikkeStore(tmp_path)


def test_same_game_account_rebind_keeps_authorization(store: NikkeStore) -> None:
    qq_id = _bind(store, "token-a", uid="uid-a", openid="openid-a")
    store.set_auto_daily(qq_id, True)
    store.set_setting(f"daily_scope_v2:{qq_id}", "community")

    _bind(store, "token-b", uid="uid-a", openid="openid-a")

    assert store.get_account(qq_id, with_cookie=False)["auto_daily_enabled"] == 1
    assert store.get_setting(f"daily_scope_v2:{qq_id}", "") == "community"


def test_rebind_to_another_game_account_revokes_inherited_authorization(
    store: NikkeStore,
) -> None:
    qq_id = _bind(store, "token-a", uid="uid-a", openid="openid-a")
    store.set_auto_daily(qq_id, True)
    store.set_setting(f"daily_scope_v2:{qq_id}", "community")
    assert store.claim_run("community:uid-a:2026-11-22", qq_id, "browse", initial_status="UNKNOWN_AFTER_ACTION")

    _bind(store, "token-b", uid="uid-b", openid="openid-b")

    assert store.get_account(qq_id, with_cookie=False)["auto_daily_enabled"] == 0
    assert store.get_setting(f"daily_scope_v2:{qq_id}", "") in ("", None)
    # 历史记录与未决保护必须完整保留。
    assert store.get_run("community:uid-a:2026-11-22")["status"] == "UNKNOWN_AFTER_ACTION"


def test_late_failure_does_not_overwrite_consumed_bind_session(store: NikkeStore) -> None:
    _bind(store, "token-a", uid="uid-a", openid="openid-a")

    store.fail_bind_session("token-a", "late loser", status="failed")

    assert store.get_bind_session("token-a")["status"] == "success"


# ---------------------------------------------------------------- 调度器异常边界

class _Coordinator:
    def __init__(self) -> None:
        self.closing = False
        self.tasks: list[asyncio.Task] = []

    def create_task(self, coroutine):
        task = asyncio.ensure_future(coroutine)
        self.tasks.append(task)
        return task


class _FlakyStore:
    def __init__(self) -> None:
        self.calls = 0

    def get_setting(self, key, default=None):
        self.calls += 1
        if self.calls == 1:
            raise sqlite3.OperationalError("database is locked")
        return default


async def _noop(*_args, **_kwargs):
    return None


@pytest.mark.asyncio
async def test_scheduler_survives_transient_sqlite_lock() -> None:
    coordinator = _Coordinator()
    ticks = 0

    async def sleep(_seconds: float) -> None:
        nonlocal ticks
        ticks += 1
        if ticks >= 3:
            coordinator.closing = True

    scheduler = RuntimeScheduler(
        coordinator=coordinator,
        store=_FlakyStore(),
        config={"daily_hour": 8, "daily_minute": 0, "summary_hour": 8, "summary_minute": 30},
        run_daily=_noop,
        send_summary=_noop,
        sync_announcements=_noop,
        sync_calendar=_noop,
        dispatch_announcements=_noop,
        sleep=sleep,
    )

    await scheduler.run()

    assert ticks >= 3
    await asyncio.gather(*coordinator.tasks)


# ---------------------------------------------------------------- 命令尾参黄金表

class _RawEvent(Event):
    def __init__(self, message: str) -> None:
        self.message_str = message


async def _route_framework_split(plugin: NikkePlugin, message: str):
    """模拟 AstrBot 按空白切分并按位置传参（main.nikke 最多 4 个参数）。"""
    parts = message.split()[1:]
    parts += [""] * (4 - len(parts))
    return [
        result
        async for result in NikkePlugin.nikke(plugin, _RawEvent(message), *parts[:4])
    ]


_TAIL_ARGUMENT_CASES = (
    pytest.param("/妮姬 兑换 CODE-1", "cdk", {"operation": "single", "code": "CODE-1"}, id="single-cdk"),
    pytest.param("/妮姬 查询 练度 拉毗", "character", {"operation": "character", "name": "拉毗"}, id="single-word-name"),
    pytest.param(
        "/妮姬 兑换 批量 CDK1 CDK2 CDK3",
        "cdk",
        {"operation": "batch", "codes": "CDK1 CDK2 CDK3"},
        id="AUD-008-space-batch-cdk",
    ),
    pytest.param(
        "/妮姬 查询 练度 Red Hood",
        "character",
        {"operation": "character", "name": "Red Hood"},
        id="AUD-008-multi-word-name",
    ),
)


@pytest.mark.asyncio
@pytest.mark.parametrize(("message", "handler", "parameters"), _TAIL_ARGUMENT_CASES)
async def test_tail_arguments_survive_framework_split(message, handler, parameters) -> None:
    plugin, recorders = _plugin_with_recorders()
    assert await _route_framework_split(plugin, message) == [("plain", handler)]
    actual = dict(recorders[handler].contexts[-1].parameters)
    for key, value in parameters.items():
        assert actual.get(key) == value, actual


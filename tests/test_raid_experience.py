"""综合突袭查询使用人工样本验证范围、分页及缓存隔离。"""
from dataclasses import asdict
import json

import pytest

from astrbot_plugin_nikke.features.raid.experience import analyze, paginate, AttendanceEvidence
from astrbot_plugin_nikke.tests.test_raid_participants import attack


def test_partial_squad_keeps_damage_but_invalid_damage_is_excluded():
    data = analyze({"participate_data": [attack("a", 10), dict(attack("b", 20), squad=[]), attack("c", "bad")]})
    assert data.total_damage == 30
    assert data.excluded_records == 1
    assert data.incomplete
    assert data.participants[0].attacks[0].details_complete is False
    assert "openid" not in json.dumps(asdict(data))


def test_same_names_do_not_prove_attendance_and_names_only_never_do():
    payload = {"participate_data": [attack("a", 10)], "union_members": ["同名"]}
    assert analyze(payload).attendance_status == "UNKNOWN"
    evidence = AttendanceEvidence("s", 0, {"a": "同名", "b": "同名"}, "s", 0, True, True)
    data = analyze(payload, attendance=evidence)
    assert data.unattacked == ["同名"]
    assert data.attendance_status == "HAS_UNATTACKED"
    evidence.attack_day = 2
    assert analyze(payload, attendance=evidence).attendance_status == "UNKNOWN"


def test_pagination_keeps_denominator_and_zero_is_unknown_share():
    data = analyze({"participate_data": [attack(str(i), i) for i in range(16)]})
    page = paginate(data, 2)
    assert len(page.participants) == 1
    assert page.total_damage == sum(range(16))
    assert page.total_pages == 2
    with pytest.raises(ValueError):
        paginate(data, 3)
    with pytest.raises(ValueError):
        paginate(data, 0)


def test_history_scope_is_preserved_in_member_page():
    data = analyze({"participate_data": [attack("me", 4)]}, member_id="me", season_id="1000007", historical=True)
    page = paginate(data, 1, member=True)
    assert page.scope == "LAST_SEASON_MEMBER"
    assert page.season_id == "1000007"


def test_all_invalid_damage_is_unknown_but_verified_zero_stays_zero():
    from astrbot_plugin_nikke.ui.payloads.raid_records import UnionRecordsT2IPayloadBuilder
    builder = UnionRecordsT2IPayloadBuilder()
    bad = builder.build(analyze({"participate_data": [attack("me", "bad")]}))
    zero = builder.build(analyze({"participate_data": [attack("me", 0)]}))
    assert bad["total_damage"] == "未知"
    assert zero["total_damage"] == "0"
    assert zero["rows"][0]["share"] == "—"


import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from astrbot_plugin_nikke.features.raid.application import RaidApplication
from astrbot_plugin_nikke.features.raid.builder import UnionRaidBuilder
from astrbot_plugin_nikke.features.account.errors import CredentialExpiredError


def application():
    accounts = {name: {"game_openid": name, "cookie": "secret", "binding_revision": "1"} for name in ("a", "b")}
    snapshot = {"guild_name": "测试联盟", "guild_id": "g", "errors": [],
        "level_info": {"manager_info": {"id": "123", "season_start_date": "2026-10-01T00:00:00+00:00",
            "season_end_date": "2026-10-30T00:00:00+00:00"}, "level_info": []},
        "attacks": {"manager_info": {"id": "123"}, "participate_data": [attack("a", 100), attack("b", 20)]}}
    gateway = SimpleNamespace(get_union_raid_dashboard=AsyncMock(side_effect=lambda _: deepcopy(snapshot)))
    app = RaidApplication(account_reader=SimpleNamespace(get_account=lambda who: accounts.get(who)),
        gateway=gateway, builder=UnionRaidBuilder(), clock=lambda: datetime(2026, 10, 10, tzinfo=timezone.utc), plugin_version="test", task_factory=asyncio.create_task)
    return app, gateway, accounts, snapshot


@pytest.mark.asyncio
async def test_dashboard_ranking_member_share_fetch_then_expire_and_rebind():
    app, gateway, accounts, _ = application()
    timer = [0]
    app._monotonic = lambda: timer[0]
    dashboard, ranking = await asyncio.gather(app.dashboard("a"), app.ranking_page("a"))
    assert dashboard.ranking.total_damage == ranking.total_damage == 120
    assert (await app.member_page("a")).total_damage == 100
    assert gateway.get_union_raid_dashboard.await_count == 1
    await app.dashboard("b")
    assert gateway.get_union_raid_dashboard.await_count == 2
    timer[0] = 31
    await app.dashboard("a")
    assert gateway.get_union_raid_dashboard.await_count == 3
    accounts["a"]["binding_revision"] = "2"
    await app.dashboard("a")
    assert gateway.get_union_raid_dashboard.await_count == 4
    accounts.pop("a")
    with pytest.raises(ValueError):
        await app.dashboard("a")


@pytest.mark.asyncio
async def test_partial_failure_keeps_bosses_and_is_not_cached():
    app, gateway, _, snapshot = application()
    snapshot.pop("attacks")
    snapshot["errors"] = ["attacks"]
    data = await app.dashboard("a")
    assert data.guild_name == "测试联盟"
    assert data.ranking is None and data.notices
    await app.dashboard("a")
    assert gateway.get_union_raid_dashboard.await_count == 2


@pytest.mark.asyncio
async def test_history_auth_error_is_never_hidden_or_cached():
    app, gateway, _, snapshot = application()
    app._builder.resolve_response_state = lambda *a, **k: __import__("astrbot_plugin_nikke.features.raid.models", fromlist=["RaidState"]).RaidState.OFFSEASON
    app._builder.latest_completed_season_id = lambda **k: "1000007"
    gateway.get_union_raid_season = AsyncMock(side_effect=CredentialExpiredError("expired"))
    with pytest.raises(CredentialExpiredError):
        await app.dashboard("a")
    assert not app._query_cache and not app._query_tasks


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_cancel_other_query():
    app, gateway, _, snapshot = application()
    started, release = asyncio.Event(), asyncio.Event()
    async def load(_):
        started.set()
        await release.wait()
        return deepcopy(snapshot)
    gateway.get_union_raid_dashboard.side_effect = load
    first = asyncio.create_task(app.dashboard("a"))
    await started.wait()
    second = asyncio.create_task(app.ranking_page("a"))
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    assert (await second).total_damage == 120
    assert gateway.get_union_raid_dashboard.await_count == 1
    assert not app._query_tasks


@pytest.mark.asyncio
async def test_rebind_while_inflight_does_not_return_old_account_data():
    app, gateway, accounts, snapshot = application()
    async def load(_):
        accounts["a"] = {**accounts["a"], "binding_revision": "changed"}
        return deepcopy(snapshot)
    gateway.get_union_raid_dashboard.side_effect = load
    with pytest.raises(ValueError, match="账号状态已变化"):
        await app.dashboard("a")
    assert not app._query_cache


@pytest.mark.asyncio
async def test_last_waiter_cancel_releases_task_and_next_request_can_retry():
    app, gateway, _, snapshot = application()
    started, stopped = asyncio.Event(), asyncio.Event()
    async def load(_):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    gateway.get_union_raid_dashboard.side_effect = load
    request = asyncio.create_task(app.dashboard("a"))
    await started.wait()
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert stopped.is_set()
    assert not app._query_tasks and not app._query_cache and not app._query_waiters
    gateway.get_union_raid_dashboard.side_effect = lambda _: deepcopy(snapshot)
    assert (await app.dashboard("a")).ranking.total_damage == 120


@pytest.mark.asyncio
async def test_gateway_fetches_identity_once_and_auth_error_wins():
    from astrbot_plugin_nikke.integrations.blablalink.client import BlaBlaClient, CookieExpired
    client = object.__new__(BlaBlaClient)
    client._union_raid_context = AsyncMock(return_value={"guild_id": "g", "guild_name": "联盟", "request": {}})
    client._post = AsyncMock(side_effect=[{"data": {"level_info": []}}, {"data": {"participate_data": []}}])
    result = await client.get_union_raid_dashboard({"cookie": "test"})
    assert client._union_raid_context.await_count == 1 and client._post.await_count == 2
    assert result["errors"] == []
    client._post.side_effect = [RuntimeError("network"), CookieExpired("expired")]
    with pytest.raises(CookieExpired):
        await client.get_union_raid_dashboard({"cookie": "test"})


@pytest.mark.asyncio
async def test_real_gateway_context_uses_one_guild_request():
    from astrbot_plugin_nikke.integrations.blablalink.client import BlaBlaClient, MY_GUILD_INFO, UNION_RAID_DATA
    client = object.__new__(BlaBlaClient)
    async def post(endpoint, cookie, payload):
        if endpoint == MY_GUILD_INFO:
            return {"data": {"guild_id": "g", "guild_name": "测试"}}
        assert payload == {"guild_id": "g", "nikke_area_id": 81, "intl_open_id": "a"}
        return {"data": {"participate_data": []} if endpoint == UNION_RAID_DATA else {"level_info": []}}
    client._post = AsyncMock(side_effect=post)
    await client.get_union_raid_dashboard({"cookie": "test", "area_id": "81", "game_openid": "a"})
    assert client._post.await_count == 3
    assert sum(c.args[0] == MY_GUILD_INFO for c in client._post.await_args_list) == 1


def test_same_cookie_rebind_changes_revision_even_in_same_second(tmp_path):
    from astrbot_plugin_nikke.core.storage import NikkeStore
    from astrbot_plugin_nikke.features.account.status import BIND_SESSION_PENDING, BIND_SESSION_SUCCESS
    store = NikkeStore(tmp_path)
    def bind(token):
        store.create_bind_session(token, "a", status=BIND_SESSION_PENDING)
        store.consume_bind_session(token, "same-cookie", "uid", "a", "测试", "角色", "81", success_status=BIND_SESSION_SUCCESS)
        return store.get_account("a")["binding_revision"]
    old = bind("first")
    assert bind("second") != old
    store.delete_account("a")
    assert store.get_account("a") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["ranking", "member", "overview"])
async def test_all_commands_cancel_feedback_and_fall_back_without_refetch(operation):
    from astrbot_plugin_nikke.application.commands.raid import RaidCommandHandler
    from astrbot_plugin_nikke.application.commands.contracts import CommandContext
    app, _, _, _ = application()
    feedback = SimpleNamespace(cancel=AsyncMock())
    handler = RaidCommandHandler(application=app, render_overview=AsyncMock(side_effect=RuntimeError()),
        render_ranking=AsyncMock(side_effect=RuntimeError()), invalidate_cookie=lambda _: None,
        start_feedback=lambda *args: feedback)
    result = await handler.handle(CommandContext(actor_id="a", parameters={"operation": operation, "page": "1"}))
    assert "联盟突袭" in result.messages[0].text
    feedback.cancel.assert_awaited_once()
    assert app._gateway.get_union_raid_dashboard.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("page", ["0", "-1", "a", "1.5", "999999999999999999999", "²"])
async def test_invalid_page_is_rejected_before_fetch(page):
    from astrbot_plugin_nikke.application.commands.raid import RaidCommandHandler
    from astrbot_plugin_nikke.application.commands.contracts import CommandContext
    app, gateway, _, _ = application()
    handler = RaidCommandHandler(application=app, render_overview=AsyncMock(),
        render_ranking=AsyncMock(), invalidate_cookie=lambda _: None)
    result = await handler.handle(CommandContext(actor_id="a", parameters={"operation": "ranking", "page": page}))
    assert "页码" in result.messages[0].text
    gateway.get_union_raid_dashboard.assert_not_awaited()

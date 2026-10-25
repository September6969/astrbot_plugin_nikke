"""社区动作离线故障注入：使用真实 SQLite、稳定身份锁和模拟网关。"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import uuid
from unittest.mock import AsyncMock

import pytest

from astrbot_plugin_nikke.core.storage import NikkeStore
from astrbot_plugin_nikke.features.daily.runner import DailyRunner
from astrbot_plugin_nikke.features.daily.actions import CommunityTaskService
from astrbot_plugin_nikke.features.daily.action_models import PostCandidate, TaskProgress, binding_stamp
from astrbot_plugin_nikke.integrations.blablalink.community_actions import parse_progress, parse_post


NOW = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
PERIOD = "community-utc:2026-10-22"


def bind(store, actor="one", uid="synthetic-game", cookie="synthetic-cookie"):
    token = "bind-" + actor + uuid.uuid4().hex
    store.create_bind_session(token, actor, status="pending")
    store.consume_bind_session(token, cookie, uid, "synthetic-openid", "合成账号", "", "3", success_status="success")
    return store.get_account(actor)


class Gateway:
    def __init__(self, current=0, target=2):
        self.tasks = {k: TaskProgress(k, "72" if k == "browse" else "73", PERIOD, target, current, current == target)
                      for k in ("browse", "like")}
        self.posts = [PostCandidate(str(i), False) for i in range(1, 12)]
        self.dispatched = []
        self.liked_posts = set()
        self.error = None
        self.credit = True
        self.reads = 0
        self.delay = 0
        self.pending_credit = None

    async def identity(self, account):
        return account["game_openid"]

    async def progress(self, account):
        self.reads += 1
        if self.pending_credit:
            kind, countdown = self.pending_credit
            if countdown <= 0:
                old = self.tasks[kind]
                self.tasks[kind] = replace(old, current=old.current + 1, completed=old.current + 1 == old.target)
                self.pending_credit = None
            else:
                self.pending_credit = (kind, countdown - 1)
        return dict(self.tasks)

    async def candidates(self, account):
        return self.posts

    async def liked(self, account, post_id):
        return post_id in self.liked_posts

    async def dispatch(self, account, kind, post_id):
        self.dispatched.append((kind, post_id))
        if self.error:
            raise self.error
        if kind == "like":
            self.liked_posts.add(post_id)
        if self.credit:
            self.pending_credit = kind, self.delay


@pytest.fixture
def env(tmp_path):
    store = NikkeStore(tmp_path)
    account = bind(store)
    gateway = Gateway()
    config = {"enable_daily_actions": True}
    runner = DailyRunner(store=store)
    service = CommunityTaskService(gateway=gateway, store=store, config=config,
        account_lock=runner._account_lock, sleep=AsyncMock(), clock=lambda: NOW)
    return store, account, gateway, config, service


@pytest.mark.asyncio
@pytest.mark.parametrize("current,target,expected", [(0, 2, 4), (1, 2, 2), (2, 2, 0), (0, 3, 6)])
async def test_only_missing_progress_is_executed_and_verified(env, current, target, expected):
    store, account, gateway, _, service = env
    gateway.__init__(current=current, target=target)
    result = await service.execute(account)
    assert result.status == "completed"
    assert len(gateway.dispatched) == expected
    assert all(r["status"] == "VERIFIED" for r in store.list_runs(action="community_action"))
    await service.execute(account)
    assert len(gateway.dispatched) == expected


@pytest.mark.asyncio
async def test_status_has_no_candidates_or_page_opening_side_effect(env):
    _, account, gateway, _, service = env
    gateway.candidates = AsyncMock(side_effect=AssertionError("不能为查询打开帖子"))
    result = await service.status(account)
    assert "0/2" in result.detail and "未核实到账" in result.detail
    assert not gateway.dispatched


@pytest.mark.asyncio
async def test_missing_state_only_blocks_corresponding_task(env):
    _, account, gateway, _, service = env
    gateway.tasks["browse"] = None
    result = await service.execute(account)
    assert result.status == "incomplete"
    assert all(k == "like" for k, _ in gateway.dispatched)


@pytest.mark.asyncio
async def test_duplicates_liked_unknown_and_candidate_shortage(env):
    _, account, gateway, _, service = env
    gateway.tasks["browse"] = replace(gateway.tasks["browse"], current=2, completed=True)
    gateway.posts = [PostCandidate("liked", True), PostCandidate("unknown", None),
                     PostCandidate("safe", False), PostCandidate("safe", False)]
    result = await service.execute(account)
    assert result.status == "incomplete"
    assert gateway.dispatched == [("like", "safe")]


@pytest.mark.asyncio
async def test_like_is_rechecked_after_waiting(env):
    _, account, gateway, _, service = env
    gateway.tasks["browse"] = replace(gateway.tasks["browse"], current=2, completed=True)
    gateway.posts = [PostCandidate("one", False)]
    gateway.liked = AsyncMock(side_effect=[False, True])
    await service.execute(account)
    assert not gateway.dispatched


@pytest.mark.asyncio
@pytest.mark.parametrize("delay", [1, 2])
async def test_delayed_progress_is_read_only_rechecked_without_budget_reset(env, delay):
    _, account, gateway, config, service = env
    gateway.delay = delay
    config["community_run_action_budget"] = 1
    await service.execute(account)
    assert len(gateway.dispatched) == 2
    assert gateway.reads > 5


@pytest.mark.asyncio
async def test_accepted_request_without_credit_pauses_after_restart(env, tmp_path):
    store, account, gateway, config, service = env
    gateway.credit = False
    first = await service.execute(account)
    assert first.status == "unknown_after_action"
    record = store.list_runs(action="community_action")[0]
    assert record["status"] == "UNKNOWN_AFTER_ACTION"
    assert json.loads(record["detail"])["request"] == "accepted"
    service.store = NikkeStore(tmp_path)
    second = await service.execute(account)
    assert "只查询不补做" in second.detail
    assert sum(kind == "browse" for kind, _ in gateway.dispatched) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [TimeoutError("synthetic-secret"), ConnectionError(), RuntimeError("429"),
                                      RuntimeError("captcha"), RuntimeError("session expired"), asyncio.CancelledError()])
async def test_failures_and_cancellation_leave_durable_unknown_and_never_replay(env, error):
    store, account, gateway, _, service = env
    gateway.error = error
    if isinstance(error, asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await service.execute(account)
    else:
        result = await service.execute(account)
        assert "synthetic-secret" not in result.detail
    assert store.list_runs(action="community_action")[0]["status"] == "UNKNOWN_AFTER_ACTION"
    before = len(gateway.dispatched)
    gateway.error = None
    # 另一个任务也会停在自己的第一次未知请求，不会重发第一任务。
    await service.execute(account)
    assert gateway.dispatched[:before] == [("browse", "1")]
    assert sum(k == "browse" for k, _ in gateway.dispatched) == 1


@pytest.mark.asyncio
async def test_persisted_intent_precedes_network_and_cycle_budget_survives_new_runner(env):
    store, account, gateway, config, service = env
    config.update(community_run_action_budget=1, community_cycle_action_budget=1)
    original = gateway.dispatch
    async def dispatch(a, kind, post):
        assert store.list_runs(action="community_action")[-1]["status"] == "DISPATCH_INTENT"
        await original(a, kind, post)
    gateway.dispatch = dispatch
    await service.execute(account)
    await service.execute(account)
    assert len(gateway.dispatched) == 2


@pytest.mark.asyncio
async def test_same_account_multibind_manual_auto_and_concurrent_commands_share_budget(env):
    store, first, gateway, config, service = env
    second = bind(store, "two")
    store.set_setting("community_actions:auto:two", binding_stamp(second))
    await asyncio.gather(service.execute(first), service.execute(second, automatic=True), service.execute(first))
    assert len(gateway.dispatched) == 4


@pytest.mark.asyncio
async def test_multi_instance_reservation_stops_overlapping_dispatch(env):
    store, account, gateway, config, service = env
    competing = CommunityTaskService(gateway=gateway, store=store, config=config,
        account_lock=DailyRunner(store=store)._account_lock, sleep=AsyncMock(), clock=lambda: NOW)
    original = gateway.dispatch
    async def dispatch(a, kind, post):
        await asyncio.sleep(0.01)
        await original(a, kind, post)
    gateway.dispatch = dispatch
    await asyncio.gather(service.execute(account), competing.execute(account))
    assert len(gateway.dispatched) <= 4
    assert len(gateway.dispatched) == len(set(gateway.dispatched))


@pytest.mark.asyncio
async def test_cross_cycle_can_use_same_post_and_rebind_cannot_reset_cycle_budget(env):
    store, account, gateway, config, service = env
    config["community_cycle_action_budget"] = 1
    await service.execute(account)
    rebound = bind(store)
    await service.execute(rebound)
    assert len(gateway.dispatched) == 2
    gateway.tasks = {k: replace(t, period="community-utc:2026-10-23", current=0, completed=False) for k, t in gateway.tasks.items()}
    service.clock = lambda: NOW + timedelta(days=1)
    await service.execute(rebound)
    assert len(gateway.dispatched) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["global", "preference", "rebind"])
async def test_disable_or_rebind_while_queued_prevents_dispatch(env, mode):
    store, account, gateway, config, service = env
    store.set_setting("community_actions:auto:one", binding_stamp(account))
    async def close(_):
        if mode == "global": config["enable_daily_actions"] = False
        if mode == "preference": store.set_setting("community_actions:auto:one", None)
        if mode == "rebind": bind(store)
    service.sleep = close
    await service.execute(account, automatic=True)
    assert not gateway.dispatched


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["global", "preference"])
async def test_reenable_after_disable_during_progress_preserves_records_and_budget(env, tmp_path, mode):
    store, account, gateway, config, service = env
    store.set_setting("community_actions:auto:one", binding_stamp(account))
    original = gateway.progress

    async def close_during_progress(a):
        progress = await original(a)
        # 模拟查询仍在等待上游响应时，用户关闭写操作授权。
        if gateway.reads == 2:
            if mode == "global":
                config["enable_daily_actions"] = False
            else:
                store.set_setting("community_actions:auto:one", None)
        return progress

    gateway.progress = close_during_progress
    assert (await service.execute(account, automatic=True)).status == "disabled"
    assert not gateway.dispatched
    record = store.list_runs(action="community_action")[0]
    assert record["status"] == "NOT_SENT"

    config["enable_daily_actions"] = True
    store.set_setting("community_actions:auto:one", binding_stamp(account))
    gateway.progress = original
    # 重新打开数据库，确保恢复依赖持久记录且不会重置周期预算。
    service.store = NikkeStore(tmp_path)
    resumed = await service.execute(account, automatic=True)
    assert resumed.status == "incomplete"
    assert gateway.dispatched == [("browse", "2"), ("like", "1"), ("like", "2")]
    detail = json.loads(service.store.get_run(record["run_key"])["detail"])
    assert detail["target"] == 2 and detail["post_id"] == "1"
    assert detail["request"] == "not_sent"
    assert service.store.get_run(record["run_key"])["status"] == "NOT_SENT"
    await service.execute(account, automatic=True)
    assert len(gateway.dispatched) == 3


@pytest.mark.asyncio
async def test_old_auto_preference_does_not_authorize_new_writes(env):
    store, account, gateway, _, service = env
    store.set_auto_daily("one", True)
    await service.execute(account, automatic=True)
    assert not gateway.dispatched


def official_task(kind=13, **overrides):
    return {"task_type": kind, "task_id": "72" if kind == 13 else "73", "cyclical_type": 1, "periodicity_type": 1,
            "reward_infos": [{"need_completed_times": 7, "completed_times": 2, "is_completed": False}], **overrides}


@pytest.mark.parametrize("override", [{"task_id": "new"}, {"cyclical_type": 2}, {"periodicity_type": False},
    {"reward_infos": []}, {"reward_infos": [{"need_completed_times": "5", "completed_times": 2, "is_completed": False}]},
    {"reward_infos": [{"need_completed_times": 5, "completed_times": 5, "is_completed": False}]}])
def test_unknown_contract_never_guesses_progress(override):
    assert parse_progress([official_task(**override)], PERIOD)["browse"] is None


def test_dynamic_target_stable_identity_and_duplicate_task():
    assert parse_progress([official_task()], PERIOD)["browse"].target == 7
    assert parse_progress([official_task(), official_task()], PERIOD)["browse"] is None
    assert parse_progress([], PERIOD) == {"browse": None, "like": None}
    assert parse_post({"post_uuid": "known", "my_upvote": {"is_star": "false"}}).liked is None
    with pytest.raises(Exception): parse_post({"id": "unknown"})


def test_public_catalog_fixture_is_evidence_not_account_status():
    from pathlib import Path
    root = Path(__file__).parent / "fixtures/community_actions"
    catalog = json.loads((root / "public_task_catalog.json").read_text(encoding="utf-8"))
    assert "not account progress" in catalog["source"]
    parsed = parse_progress(catalog["tasks"], PERIOD)
    assert parsed["browse"].task_id == "72" and parsed["like"].task_id == "73"
    provenance = json.loads((root / "provenance.json").read_text(encoding="utf-8"))
    assert all(len(s["sha256"]) == 64 for s in provenance["sources"])


@pytest.mark.asyncio
async def test_persisted_process_lease_is_read_only_after_abrupt_restart(env):
    store, account, gateway, _, service = env
    from astrbot_plugin_nikke.features.daily.action_models import account_scope
    store.claim_run("community-account-lease:v1:" + account_scope(account), "one", "community_account_lease", initial_status="LEASED")
    result = await service.execute(account)
    assert result.status == "busy_or_interrupted"
    assert not gateway.dispatched
    assert (await service.status(account)).status == "status"


@pytest.mark.asyncio
async def test_unknown_previous_cycle_does_not_grant_another_budget(env):
    store, account, gateway, _, service = env
    gateway.credit = False
    await service.execute(account)
    gateway.credit = True
    gateway.tasks = {k: replace(t, period="community-utc:2026-10-23") for k, t in gateway.tasks.items()}
    service.clock = lambda: NOW + timedelta(days=1)
    await service.execute(account)
    assert sum(kind == "browse" for kind, _ in gateway.dispatched) == 1


@pytest.mark.asyncio
async def test_same_community_identity_different_game_roles_cannot_bypass_budget(env):
    store, first, gateway, config, service = env
    other = bind(store, "two", uid="another-role")
    with store._connect() as conn:
        conn.execute("UPDATE accounts SET area_id='81' WHERE qq_id='two'")
    other = store.get_account("two")
    config["community_cycle_action_budget"] = 1
    await service.execute(first)
    await service.execute(other)
    assert len(gateway.dispatched) == 2

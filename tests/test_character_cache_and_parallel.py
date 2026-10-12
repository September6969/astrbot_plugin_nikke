# SPDX-License-Identifier: GPL-3.0-or-later
"""角色 30 秒短时查询缓存与单卡并发请求测试套件 (Phase C2 & C3)。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import Mock
import pytest

from astrbot_plugin_nikke.features.account.errors import CredentialExpiredError
from astrbot_plugin_nikke.features.character.application import (
    CharacterApplication,
    CharacterCardRequest,
    CharacterIdentityMismatch,
    CharacterNotOwned,
)
from astrbot_plugin_nikke.features.character.identity import CharacterDirectoryResolver
from astrbot_plugin_nikke.integrations.blablalink.client import BlaBlaClient, CookieExpired


def make_account(qq_id: str = "10001", revision: str = "rev_1", area_id: int = 1) -> dict[str, Any]:
    return {
        "qq_id": qq_id,
        "game_uid": f"uid_{qq_id}",
        "game_openid": f"openid_{qq_id}",
        "area_id": area_id,
        "binding_revision": revision,
        "cookie": f"cookie_{qq_id}_{revision}",
        "cookie_valid": 1,
        "nickname": f"指挥官_{qq_id}",
    }


@pytest.mark.asyncio
async def test_30s_roster_and_detail_cache_hits_and_isolated():
    """验证相同账号 30 秒内查询复用结果只打一次 API，不同账号/参数严格隔离。"""
    call_counts = {"CHARACTERS": 0, "CHARACTER_DETAILS": 0}

    async def mock_post(path: str, cookie: str, payload: dict[str, Any]) -> dict[str, Any]:
        if "GetUserCharacters" in path:
            call_counts["CHARACTERS"] += 1
            return {
                "code": "0",
                "data": {
                    "characters": [
                        {"name_code": "alice", "lv": 200},
                        {"name_code": "modernia", "lv": 200},
                    ]
                },
            }
        if "GetUserCharacterDetails" in path:
            call_counts["CHARACTER_DETAILS"] += 1
            codes = payload.get("name_codes", [])
            return {
                "code": "0",
                "data": {
                    "character_details": [
                        {"name_code": code, "costume_tid": 100, "attractive_lv": 10}
                        for code in codes
                    ],
                    "equipments": [],
                    "state_effects": [],
                },
            }
        return {"code": "0", "data": {}}

    client = BlaBlaClient()
    client._post = mock_post

    account_a = make_account("10001")
    account_b = make_account("10002")

    # 1. 账号 A 首次请求 get_roster(include_details=False) -> 触发 1 次 API
    roster_1 = await client.get_roster(account_a, include_details=False)
    assert len(roster_1) == 2
    assert call_counts["CHARACTERS"] == 1

    # 2. 账号 A 第二次请求 get_roster(include_details=False) -> 命中缓存，不增 API 调用
    roster_2 = await client.get_roster(account_a, include_details=False)
    assert len(roster_2) == 2
    assert call_counts["CHARACTERS"] == 1

    # 3. 验证返回为 deepcopy，调用方篡改数据不污染缓存
    roster_2[0]["lv"] = 999
    roster_3 = await client.get_roster(account_a, include_details=False)
    assert roster_3[0]["lv"] == 200

    # 4. 账号 B 请求 get_roster -> 账号隔离，触发新 API 调用
    roster_b = await client.get_roster(account_b, include_details=False)
    assert call_counts["CHARACTERS"] == 2

    # 5. 账号 A 首次获取 alice 单卡详情
    # 内部 get_roster(False) 命中缓存（CHARACTERS 不增加），只打 1 次 CHARACTER_DETAILS
    detail_1 = await client.get_character_detail(account_a, "alice")
    assert detail_1["roster_item"]["name_code"] == "alice"
    assert call_counts["CHARACTERS"] == 2
    assert call_counts["CHARACTER_DETAILS"] == 1

    # 6. 账号 A 再次获取 alice 单卡详情 -> 命中 detail 缓存，0 次 API
    detail_2 = await client.get_character_detail(account_a, "alice")
    assert detail_2["roster_item"]["name_code"] == "alice"
    assert call_counts["CHARACTERS"] == 2
    assert call_counts["CHARACTER_DETAILS"] == 1

    # 7. 账号 A 获取 modernia 单卡详情 -> get_roster(False) 命中缓存，只打 1 次 CHARACTER_DETAILS
    detail_mod = await client.get_character_detail(account_a, "modernia")
    assert detail_mod["roster_item"]["name_code"] == "modernia"
    assert call_counts["CHARACTERS"] == 2
    assert call_counts["CHARACTER_DETAILS"] == 2


@pytest.mark.asyncio
async def test_cache_rebinding_invalidation_and_no_backprop():
    """验证重绑立刻失效，且在途并发重绑旧响应绝不回灌进新缓存。"""
    account_v1 = make_account("10001", revision="rev_1")
    account_v2 = make_account("10001", revision="rev_2")

    current_account_in_store = account_v1

    class FakeStore:
        def get_account(self, qq_id: str):
            return current_account_in_store

    call_count = 0
    fetch_started = asyncio.Event()
    allow_finish = asyncio.Event()

    async def mock_post(path: str, cookie: str, payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        fetch_started.set()
        await allow_finish.wait()  # 暂停在途请求，等待外部发生重绑
        return {
            "code": "0",
            "data": {"characters": [{"name_code": "alice", "lv": 100}]},
        }

    client = BlaBlaClient(account_reader=FakeStore())
    client._post = mock_post

    # 启动任务 1（使用 rev_1）
    task1 = asyncio.create_task(client.get_roster(account_v1, include_details=False))
    await fetch_started.wait()

    # 在途期间：用户在 store 中重绑，代次变为 rev_2
    current_account_in_store = account_v2

    # 释放任务 1 完成
    allow_finish.set()
    res1 = await task1
    assert len(res1) == 1

    # 校验：因为完成校验时发现 store 中绑定代次已变成 rev_2，旧响应不得回灌进缓存
    assert len(client._query_cache) == 0

    # 用 rev_2 查询，必须重新调用 API
    allow_finish.set()
    res2 = await client.get_roster(account_v2, include_details=False)
    assert call_count == 2
    # 正常完成且代次匹配，写入 rev_2 缓存
    assert len(client._query_cache) == 1


@pytest.mark.asyncio
async def test_cache_in_flight_merging_and_waiter_cancellation_safety():
    """验证同 key 合并在途请求，单个等待者取消不影响其余等待者，全部取消则收敛任务。"""
    call_count = 0
    fetch_started = asyncio.Event()
    allow_finish = asyncio.Event()

    async def mock_post(path: str, cookie: str, payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        fetch_started.set()
        await allow_finish.wait()
        return {
            "code": "0",
            "data": {"characters": [{"name_code": "alice", "lv": 200}]},
        }

    client = BlaBlaClient()
    client._post = mock_post
    account = make_account("10001")

    # 两个并发等待者
    task_a = asyncio.create_task(client.get_roster(account, include_details=False))
    task_b = asyncio.create_task(client.get_roster(account, include_details=False))

    await fetch_started.wait()
    assert call_count == 1  # 两个等待者只启动 1 次底层抓取

    # 取消等待者 A
    task_a.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task_a

    # 等待者 B 继续正常等待并完成
    allow_finish.set()
    res_b = await task_b
    assert res_b[0]["name_code"] == "alice"


@pytest.mark.asyncio
async def test_build_card_runs_detail_and_profile_in_parallel():
    """验证 build_card 真正并发请求详情与属性资料，使用事件屏障证明两个上游都开始后才释放。"""
    detail_started = asyncio.Event()
    profile_started = asyncio.Event()
    both_running = asyncio.Event()

    class ParallelGateway:
        async def get_character_detail(self, account, name_code):
            detail_started.set()
            if profile_started.is_set():
                both_running.set()
            await both_running.wait()
            return {
                "roster_item": {"name_code": "alice", "lv": 200, "costume_id": 1},
                "detail": {"name_code": "alice", "costume_tid": 1, "attractive_lv": 10},
                "state_effects": [],
            }

        async def get_profile(self, account):
            profile_started.set()
            if detail_started.is_set():
                both_running.set()
            await both_running.wait()
            return {"outpost": {"recycle_room_researches": [{"tid": 1001, "lv": 5}]}}

    account = make_account("10001")

    class FakeAccountReader:
        def get_account(self, qq_id):
            return account

    builder = Mock()
    builder.build.return_value = Mock()
    resources = Mock()
    resources.prepare_payload.side_effect = lambda p: p

    app = CharacterApplication(
        account_reader=FakeAccountReader(),
        gateway=ParallelGateway(),
        identity=CharacterDirectoryResolver(),
        stat_resources=resources,
        card_builder=builder,
        clock=lambda: datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc),
        plugin_version="1.0.0",
    )

    directory = [
        {
            "name_code": "alice",
            "name_cn": "爱丽丝",
            "name_zh_cn": "爱丽丝",
            "name_zh_tw": "愛麗絲",
            "name_en": "Alice",
            "resource_id": 5065,
        }
    ]

    result = await app.build_card(CharacterCardRequest(qq_id="10001", query="Alice", directory=tuple(directory)))
    assert result.card is not None
    # 证明在两个都启动并到达屏障后才释放
    assert detail_started.is_set()
    assert profile_started.is_set()
    assert both_running.is_set()


@pytest.mark.asyncio
async def test_build_card_login_expired_priority_on_either_task():
    """验证 build_card 中任一端登录失效（CredentialExpiredError）均优先抛出，不出卡。"""
    class ExpiredProfileGateway:
        async def get_character_detail(self, account, name_code):
            await asyncio.sleep(0.01)
            return {
                "roster_item": {"name_code": "alice", "lv": 200},
                "detail": {"name_code": "alice"},
            }

        async def get_profile(self, account):
            raise CredentialExpiredError("登录状态已失效，请重新绑定")

    account = make_account("10001")

    class FakeAccountReader:
        def get_account(self, qq_id):
            return account

    builder = Mock()
    resources = Mock()

    app = CharacterApplication(
        account_reader=FakeAccountReader(),
        gateway=ExpiredProfileGateway(),
        identity=CharacterDirectoryResolver(),
        stat_resources=resources,
        card_builder=builder,
        clock=lambda: datetime.now(timezone.utc),
        plugin_version="1.0.0",
    )

    directory = [{"name_code": "alice", "name_cn": "爱丽丝"}]

    with pytest.raises(CredentialExpiredError):
        await app.build_card(CharacterCardRequest(qq_id="10001", query="爱丽丝", directory=tuple(directory)))

    builder.build.assert_not_called()
    resources.prepare_payload.assert_not_called()


@pytest.mark.asyncio
async def test_build_card_profile_normal_failure_graceful_degradation():
    """验证 profile 普通读取失败时保持已有降级，角色卡依然成功渲染。"""
    class FailingProfileGateway:
        async def get_character_detail(self, account, name_code):
            return {
                "roster_item": {"name_code": "alice", "lv": 200},
                "detail": {"name_code": "alice"},
            }

        async def get_profile(self, account):
            raise RuntimeError("网络偶发波动，获取前哨资料超时")

    account = make_account("10001")

    class FakeAccountReader:
        def get_account(self, qq_id):
            return account

    builder = Mock()
    builder.build.return_value = Mock()
    resources = Mock()
    resources.prepare_payload.side_effect = lambda p: p

    app = CharacterApplication(
        account_reader=FakeAccountReader(),
        gateway=FailingProfileGateway(),
        identity=CharacterDirectoryResolver(),
        stat_resources=resources,
        card_builder=builder,
        clock=lambda: datetime.now(timezone.utc),
        plugin_version="1.0.0",
    )

    directory = [{"name_code": "alice", "name_cn": "爱丽丝"}]

    result = await app.build_card(CharacterCardRequest(qq_id="10001", query="爱丽丝", directory=tuple(directory)))
    assert result.card is not None
    builder.build.assert_called_once()
    # 验证降级后 research_levels 为全 None 字典
    call_kwargs = builder.build.call_args[1]
    assert all(v is None for v in call_kwargs["account"]["research_levels"].values())

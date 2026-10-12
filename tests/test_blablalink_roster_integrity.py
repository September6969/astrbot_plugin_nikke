# SPDX-License-Identifier: GPL-3.0-or-later
"""验证 BlaBlaLinkClient get_roster 练度字段正确性与 get_daily_contents_progress 无重名定义。"""

import ast
from unittest.mock import AsyncMock

import pytest

from astrbot_plugin_nikke.integrations.blablalink.client import (
    BlaBlaClient,
    BlaBlaError,
    CookieExpired,
)


def test_no_duplicate_method_definitions_in_client():
    """AST 检查：确保 BlaBlaClient 内部无重复方法定义。"""
    import inspect
    from astrbot_plugin_nikke.integrations.blablalink import client as client_module

    source = inspect.getsource(client_module)
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            method_names = [item.name for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))]
            duplicates = [name for name in set(method_names) if method_names.count(name) > 1]
            assert not duplicates, f"类 {node.name} 中存在重复方法定义: {duplicates}"


@pytest.mark.asyncio
async def test_get_roster_skills_only_no_roster_field_overwrite():
    """A1 验证：get_roster 只能补足技能，不能让详情覆盖名单的 lv/combat/grade/core。"""
    client = BlaBlaClient()

    roster_raw = [
        {
            "name_code": "c100",
            "lv": 400,
            "combat": 200000,
            "grade": 3,
            "core": 7,
            "custom_note": "original_roster",
        }
    ]
    details_raw = [
        {
            "name_code": "c100",
            "lv": 1,
            "combat": 100,
            "grade": 0,
            "core": 0,
            "skill1_lv": 10,
            "skill2_lv": 9,
            "ulti_skill_lv": 8,
            "head_equip_option1_id": "malformed_id",
            "custom_note": "overwritten_from_detail",
        }
    ]

    async def mock_post(path, cookie, payload):
        if "GetCharacterList" in path or "characters" in path.lower():
            return {"data": {"characters": roster_raw}}
        if "GetCharacterDetail" in path or "detail" in path.lower():
            return {"data": {"character_details": details_raw, "state_effects": []}}
        return {}

    client._post = AsyncMock(side_effect=mock_post)

    account = {"area_id": "1", "game_openid": "test_openid", "cookie": "test_cookie"}
    result = await client.get_roster(account, include_details=True)

    assert len(result) == 1
    char = result[0]
    # 名单的基础字段必须胜出
    assert char["lv"] == 400
    assert char["combat"] == 200000
    assert char["grade"] == 3
    assert char["core"] == 7
    assert char["custom_note"] == "original_roster"
    # 技能等级补足
    assert char["skill1_lv"] == 10
    assert char["skill2_lv"] == 9
    assert char["ulti_skill_lv"] == 8
    # 不得向总表残留 equipment_effects
    assert "equipment_effects" not in char
    # 不修改原始入参/mock对象
    assert roster_raw[0].get("skill1_lv") is None


@pytest.mark.asyncio
async def test_get_roster_edge_cases():
    """A1 验证：详情缺失、未知角色、空名单、include_details=False、重复/异常 name_code。"""
    client = BlaBlaClient()

    # 1. 空名单
    client._post = AsyncMock(return_value={"data": {"characters": []}})
    assert await client.get_roster({"area_id": "1", "cookie": "c"}, include_details=True) == []

    # 2. include_details=False
    raw_list = [{"name_code": "c001", "lv": 200}]
    client._post = AsyncMock(return_value={"data": {"characters": raw_list}})
    res = await client.get_roster({"area_id": "1", "cookie": "c"}, include_details=False)
    assert res == raw_list
    assert client._post.call_count == 1  # 仅请求一次名单，不请求详情

    # 3. 详情缺失某角色、未知角色在详情中、异常空 name_code、重复 name_code
    roster_multi = [
        {"name_code": "c001", "lv": 200},
        {"name_code": "c002", "lv": 150},  # 详情中缺失
        {"name_code": "", "lv": 10},        # 异常空 name_code
        {"name_code": "c001", "lv": 200},  # 重复项
    ]
    details_multi = [
        {"name_code": "c001", "skill1_lv": 7},
        {"name_code": "c999", "skill1_lv": 10},  # 名单中不存在的未知角色
        {"name_code": None, "skill1_lv": 5},
    ]

    async def mock_post_multi(path, cookie, payload):
        if "GetUserCharacters" in path or "characters" in path.lower():
            return {"data": {"characters": roster_multi}}
        if "GetUserCharacterDetails" in path or "detail" in path.lower():
            return {"data": {"character_details": details_multi}}
        return {}

    client._post = AsyncMock(side_effect=mock_post_multi)
    merged = await client.get_roster({"area_id": "1", "cookie": "c"}, include_details=True)
    assert len(merged) == 4
    assert merged[0]["skill1_lv"] == 7
    # 详情缺失时不写入 None，不变成 0
    assert "skill1_lv" not in merged[1]
    assert "skill1_lv" not in merged[2]
    assert merged[3]["skill1_lv"] == 7


@pytest.mark.asyncio
async def test_get_daily_contents_progress_semantics():
    """A2 验证：正常响应、非法响应抛出 BlaBlaError、登录失效抛出 CookieExpired。"""
    client = BlaBlaClient()
    account = {"area_id": "1", "cookie": "test_cookie"}

    # 1. 正常响应
    client._post = AsyncMock(return_value={"data": {"daily_progress": [{"inquire_count": 5}]}})
    res = await client.get_daily_contents_progress(account)
    assert res == {"inquire_count": 5}

    # 2. 非法响应（不是 dict 或 daily_progress 不是非空 list）
    client._post = AsyncMock(return_value={"data": {"daily_progress": []}})
    with pytest.raises(BlaBlaError, match="每日内容进度格式异常"):
        await client.get_daily_contents_progress(account)

    client._post = AsyncMock(return_value={"data": None})
    with pytest.raises(BlaBlaError, match="每日内容进度格式异常"):
        await client.get_daily_contents_progress(account)

    # 3. 登录失效异常
    client._post = AsyncMock(side_effect=CookieExpired("登录已失效", code=11003))
    with pytest.raises(CookieExpired):
        await client.get_daily_contents_progress(account)

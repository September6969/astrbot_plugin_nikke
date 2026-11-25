# SPDX-License-Identifier: GPL-3.0-or-later
"""26 公开分享 ID：只读白名单、非 UID 边界、上游失败与命令入口。"""

from __future__ import annotations

import httpx
import pytest

from astrbot_plugin_nikke.application.commands.toolbox import ToolboxCommandHandler
from astrbot_plugin_nikke.integrations.nikke_api.share_profile import (
    ShareProfile,
    ShareProfileError,
    fetch_public_share,
    parse_share_profile,
    render_share_profile,
    validate_share_id,
)
from astrbot_plugin_nikke.main import NikkePlugin
from plugin_fixtures import make_plugin_shell
from test_command_routing_contract import Event
from test_toolbox_commands import MemoryStore, toolbox_services


def payload() -> dict:
    return {
        "intlOpenId": "should-not-leak",
        "areaId": 83,
        "profile": {
            "nickname": "公开昵称",
            "level": 333,
            "teamCombat": 355847,
            "nikkeCount": 111,
            "campaign": {
                "normal": {"stage": "40-35 STAGE"},
                "hard": {"stage": "19-14 STAGE"},
            },
        },
        "outpost": {"synchroLevel": 248},
    }


def test_parse_keeps_only_public_allowlisted_fields() -> None:
    profile = parse_share_profile(payload())
    assert profile.nickname == "公开昵称"
    assert profile.level == 333
    assert profile.team_combat == 355847
    assert profile.nikke_count == 111
    assert profile.synchro_level == 248
    assert profile.normal_stage == "40-35 STAGE"

    rendered = render_share_profile(profile)
    assert "公开昵称" in rendered
    assert "不是本站 UID 接口" in rendered
    assert "should-not-leak" not in rendered
    assert not hasattr(profile, "intl_open_id")


def test_share_id_validation_rejects_urls_and_short_values() -> None:
    with pytest.raises(ShareProfileError, match="格式无效"):
        validate_share_id("https://www.blablalink.com/user?openid=secret")
    with pytest.raises(ShareProfileError, match="格式无效"):
        validate_share_id("short")
    assert validate_share_id("AbCd_123-xyz") == "AbCd_123-xyz"


@pytest.mark.asyncio
async def test_fetch_maps_public_statuses_and_never_sends_credentials() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "missing" in str(request.url):
            return httpx.Response(404, json={"error": "not found"})
        if "private" in str(request.url):
            return httpx.Response(403, json={"error": "private"})
        if "disabled" in str(request.url):
            return httpx.Response(503, json={"error": "credentials not configured"})
        return httpx.Response(200, json=payload())

    transport = httpx.MockTransport(handler)
    profile = await fetch_public_share("AbCd_123-xyz", transport=transport)
    assert profile.nickname == "公开昵称"
    assert requests and "Cookie" not in requests[0].headers

    for identifier, message in (
        ("missing-share", "不存在或未公开"),
        ("private-share", "未授权公开"),
        ("disabled-share", "未配置查询账号"),
    ):
        with pytest.raises(ShareProfileError, match=message):
            await fetch_public_share(identifier, transport=transport)


@pytest.mark.asyncio
async def test_share_command_is_separate_from_uid_and_requires_opt_in_and_confirm() -> None:
    store = MemoryStore()
    services = toolbox_services(store)
    calls: list[str] = []

    async def lookup(value):
        calls.append(value)
        return ShareProfile(
            nickname="公开昵称", level=333, team_combat=355847, nikke_count=111,
            synchro_level=248, normal_stage="40-35 STAGE", hard_stage="19-14 STAGE",
        )

    plugin = make_plugin_shell()
    plugin.config = {}

    # 1. 默认关闭时 fail-closed，绝不触发外发请求。
    services.public_share_enabled = False
    services.share_lookup = None
    plugin.handlers.toolbox = ToolboxCommandHandler(services)
    disabled_res = [item async for item in plugin.nikke(Event(), "我的妮姬", "分享", "AbCd_123-xyz")]
    assert "默认关闭" in disabled_res[0][1]
    assert "enable_public_share_api" in disabled_res[0][1]
    assert calls == []

    # 2. 开启开关但未带“确认”时，只披露第三方传输范围，不发送请求。
    services.public_share_enabled = True
    services.share_lookup = lookup
    disclosure_res = [item async for item in plugin.nikke(Event(), "我的妮姬", "分享", "AbCd_123-xyz")]
    disclosure_text = disclosure_res[0][1]
    assert "nikke-api.pages.dev" in disclosure_text
    assert "仅发送你输入的公开分享 ID" in disclosure_text
    assert "确认" in disclosure_text
    assert calls == []

    # 3. 用户明确“确认”后，执行只读查询。
    results = [item async for item in plugin.nikke(Event(), "我的妮姬", "分享", "AbCd_123-xyz 确认")]
    text = results[0][1]
    assert calls == ["AbCd_123-xyz"]
    assert "【公开分享资料】公开昵称" in text
    assert "不是本站 UID 接口" in text
    assert "同步器：248" in text

    # UID 命令仍保持受限；分享入口不复用也不改变该边界。
    uid_text = await _uid(plugin)
    assert "与你当前绑定的账号一致" in uid_text


async def _uid(plugin: NikkePlugin) -> str:
    results = [item async for item in plugin.nikke(Event(), "uid", "123456789")]
    return results[0][1]

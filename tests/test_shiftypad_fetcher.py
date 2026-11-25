# SPDX-License-Identifier: GPL-3.0-or-later
"""ShiftyPad 官方公开档案抓取合同：白名单字段、公开开关与失败边界。"""

from __future__ import annotations

import httpx
import pytest

from astrbot_plugin_nikke.features.shiftypad.fetcher import parse_public_profile
from astrbot_plugin_nikke.integrations.shiftypad.official import (
    ENDPOINT,
    OfficialPublicProfileFetcher,
)
from astrbot_plugin_nikke.features.shiftypad.models import (
    ShiftypadIdentity,
    ShiftypadPrivateError,
    ShiftypadUpstreamError,
)

OPENID = "12345-1234567890"


def identity() -> ShiftypadIdentity:
    return ShiftypadIdentity(
        openid=OPENID, uid="123456789", server="na",
        source_url="https://www.blablalink.com/shiftyspad/home",
    )


def payload() -> dict:
    return {
        "code": 0,
        "data": {
            "nickname": "公开昵称",
            "level": 333,
            "team_combat": 355847,
            "character_count": 2,
            "synchro_level": 248,
            "campaign": {"normal": {"stage": "40-35"}, "hard": {"stage": "19-14"}},
            "shiftyspad_settings": {"show_nikke_info": 1, "show_outpost_info": 1},
            "characters": [
                {"name_code": 1001, "lv": 200, "grade": 2, "combat": 120000},
                {"name_code": 1002, "lv": 180, "grade": 0, "combat": 90000},
            ],
            "intl_openid": "must-not-leak",
        },
    }


def test_parse_keeps_minimal_public_snapshot() -> None:
    profile = parse_public_profile(payload(), identity())
    assert profile.nickname == "公开昵称"
    assert profile.level == 333
    assert profile.team_combat == 355847
    assert profile.nikke_count == 2
    assert profile.synchro_level == 248
    assert profile.normal_stage == "40-35"
    assert profile.characters[0].name_code == "1001"
    assert profile.visibility == "public"
    assert "must-not-leak" not in str(profile.to_dict(include_identity=False))


def test_private_switch_or_missing_nickname_fails_explicitly() -> None:
    private = payload()
    private["data"]["shiftyspad_settings"]["show_nikke_info"] = 0
    with pytest.raises(ShiftypadPrivateError, match="未公开"):
        parse_public_profile(private, identity())

    missing = payload()
    missing["data"].pop("nickname")
    with pytest.raises(ShiftypadUpstreamError, match="缺少昵称"):
        parse_public_profile(missing, identity())

    upstream = {"code": 500, "msg": "server error"}
    with pytest.raises(ShiftypadUpstreamError):
        parse_public_profile(upstream, identity())


@pytest.mark.asyncio
async def test_fetcher_maps_http_statuses_without_cookies() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "private" in request.content.decode():
            return httpx.Response(403, json={"error": "private"})
        return httpx.Response(200, json=payload())

    fetcher = OfficialPublicProfileFetcher(transport=httpx.MockTransport(handler))
    profile = await fetcher.fetch(identity())
    assert profile.nickname == "公开昵称"
    assert requests[0].url == ENDPOINT
    assert "Cookie" not in requests[0].headers
    assert b"intl_openid" in requests[0].content

    private_identity = ShiftypadIdentity(openid="99999-9999999999")
    with pytest.raises(ShiftypadPrivateError):
        await OfficialPublicProfileFetcher(
            transport=httpx.MockTransport(lambda request: httpx.Response(403))
        ).fetch(private_identity)
    with pytest.raises(ShiftypadUpstreamError):
        await OfficialPublicProfileFetcher(
            transport=httpx.MockTransport(lambda request: httpx.Response(404))
        ).fetch(private_identity)

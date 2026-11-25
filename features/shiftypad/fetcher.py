# SPDX-License-Identifier: GPL-3.0-or-later
"""官方 ShiftyPad 公开档案的只读抓取器。

路径依据官方 ShiftyPad 前端公开代码中使用的
``/api/ugc/direct/standalonesite/User/GetUserProfile``（以 ``intl_openid`` 查询）。
本模块**不携带 Cookie、Token 或登录态**，只接受公开 OpenID；响应格式仍标记为
``unverified_contract``，遇到未知结构会明确失败，绝不把猜测字段当成功。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

from .identity import OPENID_RE
from .models import (
    ShiftypadCharacter,
    ShiftypadIdentity,
    ShiftypadPrivateError,
    ShiftypadProfile,
    ShiftypadUpstreamError,
)

ENDPOINT = "https://api.blablalink.com/api/ugc/direct/standalonesite/User/GetUserProfile"
SOURCE_PAGE = "https://www.blablalink.com/shiftyspad/home"
CONTRACT = "official_public_profile_unverified_2026-11-23"


class PublicProfileFetcher(Protocol):
    async def fetch(self, identity: ShiftypadIdentity) -> ShiftypadProfile:
        """按公开身份读取最小快照；未公开或上游失败时必须抛出。"""


def _first_int(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value >= 0:
            return value
        if isinstance(value, str) and value.strip().isascii() and value.strip().isdigit():
            return int(value.strip())
    return None


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()[:80]
    return ""


def _nested_mappings(data: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    candidates = [data]
    for key in ("user_info", "profile", "basic_info", "role_info", "game_info"):
        value = data.get(key)
        if isinstance(value, Mapping):
            candidates.append(value)
    return candidates


def parse_public_profile(
    payload: Mapping[str, Any],
    identity: ShiftypadIdentity,
    *,
    fetched_at: str | None = None,
) -> ShiftypadProfile:
    """从官方公开响应提取最小字段；未知/缺失结构显式失败。"""
    if not isinstance(payload, Mapping):
        raise ShiftypadUpstreamError("公开档案响应不是对象")
    if payload.get("code") not in (0, None):
        message = str(payload.get("msg") or payload.get("message") or "")
        if any(word in message.casefold() for word in ("private", "隐私", "非公开", "not public")):
            raise ShiftypadPrivateError("该 ShiftyPad 档案未公开")
        raise ShiftypadUpstreamError("公开档案接口返回失败")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise ShiftypadUpstreamError("公开档案响应缺少 data")
    maps = _nested_mappings(data)
    settings = data.get("shiftyspad_settings")
    if not isinstance(settings, Mapping):
        settings = data.get("privacy_shows") if isinstance(data.get("privacy_shows"), Mapping) else {}
    for key in ("show_nikke_info", "show_outpost_info"):
        value = settings.get(key) if isinstance(settings, Mapping) else None
        if value in (0, "0", False):
            raise ShiftypadPrivateError("该 ShiftyPad 档案的持有妮姬或前哨未公开")

    nickname = _first_text(
        *(mapping.get("nickname") for mapping in maps),
        *(mapping.get("role_name") for mapping in maps),
        *(mapping.get("name") for mapping in maps),
    )
    if not nickname:
        raise ShiftypadUpstreamError("公开档案缺少昵称，响应合同未确认")
    level = _first_int(*(mapping.get("level") for mapping in maps), *(mapping.get("lv") for mapping in maps))
    team_combat = _first_int(
        *(mapping.get("team_combat") for mapping in maps),
        *(mapping.get("teamCombat") for mapping in maps),
    )
    synchro = _first_int(
        *(mapping.get("synchro_level") for mapping in maps),
        *(mapping.get("synchroLevel") for mapping in maps),
    )
    nikke_count = _first_int(
        *(mapping.get("nikke_count") for mapping in maps),
        *(mapping.get("character_count") for mapping in maps),
    )
    normal = _first_text(
        *(mapping.get("normal_campaign") for mapping in maps),
        *(mapping.get("progress_normal_campaign") for mapping in maps),
    )
    hard = _first_text(
        *(mapping.get("hard_campaign") for mapping in maps),
        *(mapping.get("progress_hard_campaign") for mapping in maps),
    )
    campaign = data.get("campaign")
    if isinstance(campaign, Mapping):
        normal_map = campaign.get("normal")
        hard_map = campaign.get("hard")
        if isinstance(normal_map, Mapping):
            normal = normal or _first_text(normal_map.get("stage"))
        if isinstance(hard_map, Mapping):
            hard = hard or _first_text(hard_map.get("stage"))

    characters: list[ShiftypadCharacter] = []
    raw_characters = None
    for key in ("characters", "user_characters", "nikke_list", "user_nikkelist_info"):
        if isinstance(data.get(key), list):
            raw_characters = data[key]
            break
    for row in raw_characters or ():
        if not isinstance(row, Mapping):
            continue
        code = str(row.get("name_code") or row.get("resource_id") or "").strip()
        if not code:
            continue
        characters.append(
            ShiftypadCharacter(
                name_code=code,
                level=_first_int(row.get("lv"), row.get("level")),
                grade=_first_int(row.get("grade"), row.get("limit_break")),
                combat=_first_int(row.get("combat")),
            )
        )
    if nikke_count is None and characters:
        nikke_count = len(characters)

    visibility = "public"
    if not settings:
        visibility = "unknown"
    return ShiftypadProfile(
        identity=identity,
        nickname=nickname,
        level=level,
        team_combat=team_combat,
        nikke_count=nikke_count,
        synchro_level=synchro,
        normal_stage=normal,
        hard_stage=hard,
        visibility=visibility,
        characters=tuple(characters),
        fetched_at=fetched_at or datetime.now(timezone.utc).isoformat(),
        source_url=identity.source_url or SOURCE_PAGE,
        contract=CONTRACT,
    )


__all__ = [
    "CONTRACT",
    "SOURCE_PAGE",
    "PublicProfileFetcher",
    "parse_public_profile",
]

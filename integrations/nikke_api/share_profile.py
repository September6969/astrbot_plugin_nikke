# SPDX-License-Identifier: GPL-3.0-or-later
"""公开分享 ID 资料入口（26，可选）。

来源：公开项目 https://github.com/leegunwoooo/nikke-api
路由：``GET https://nikke-api.pages.dev/api/user/<blablaid>``。
这是 **BlablaLink 公开分享 ID** 的只读资料，不是本站 UID 接口，也不代表账号所有权；
只返回白名单展示字段，不保存、不转发 intlOpenId 等标识。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import quote

import httpx

SHARE_API_BASE = "https://nikke-api.pages.dev"
SHARE_SOURCE = "https://github.com/leegunwoooo/nikke-api"
SHARE_NOTE = (
    "公开分享 ID 资料由第三方公开项目 nikke-api 只读转发 BlablaLink 分享资料；"
    "它不是本站 UID 接口，不能证明账号归属，也不解锁任何私有权限。"
)
_SHARE_ID = re.compile(r"^[A-Za-z0-9_\-=+/]{8,256}$")


class ShareProfileError(ValueError):
    """分享 ID 或上游响应不符合公开只读合同。"""


@dataclass(frozen=True, slots=True)
class ShareProfile:
    nickname: str
    level: int | None
    team_combat: int | None
    nikke_count: int | None
    synchro_level: int | None
    normal_stage: str
    hard_stage: str
    source_url: str = SHARE_SOURCE
    note: str = SHARE_NOTE


def validate_share_id(value: Any) -> str:
    text = str(value or "").strip()
    if not _SHARE_ID.fullmatch(text):
        raise ShareProfileError("分享 ID 格式无效；请只粘贴公开分享 ID，不要粘贴完整 URL 或 Cookie")
    return text


def parse_share_profile(payload: Mapping[str, Any]) -> ShareProfile:
    """只保留公开展示字段；未知字段（含 intlOpenId）一律丢弃。"""
    if not isinstance(payload, Mapping):
        raise ShareProfileError("上游响应不是对象")
    profile = payload.get("profile")
    outpost = payload.get("outpost")
    if not isinstance(profile, Mapping):
        raise ShareProfileError("上游响应缺少公开 profile")
    profile = dict(profile)
    outpost = dict(outpost) if isinstance(outpost, Mapping) else {}
    campaign = profile.get("campaign") if isinstance(profile.get("campaign"), Mapping) else {}
    normal = campaign.get("normal") if isinstance(campaign.get("normal"), Mapping) else {}
    hard = campaign.get("hard") if isinstance(campaign.get("hard"), Mapping) else {}

    def optional_int(value: Any) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None

    def stage(value: Mapping[str, Any]) -> str:
        text = value.get("stage")
        return text.strip() if isinstance(text, str) and text.strip() else "未知"

    nickname = profile.get("nickname")
    if not isinstance(nickname, str) or not nickname.strip():
        raise ShareProfileError("公开资料缺少昵称")
    return ShareProfile(
        nickname=nickname.strip()[:40],
        level=optional_int(profile.get("level")),
        team_combat=optional_int(profile.get("teamCombat")),
        nikke_count=optional_int(profile.get("nikkeCount")),
        synchro_level=optional_int(outpost.get("synchroLevel")),
        normal_stage=stage(normal),
        hard_stage=stage(hard),
    )


async def fetch_public_share(
    share_id: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout: float = 10.0,
) -> ShareProfile:
    """读取用户直接提供的公开分享资料；不发送任何本插件账号凭据。"""
    identifier = validate_share_id(share_id)
    url = f"{SHARE_API_BASE}/api/user/{quote(identifier, safe='')}"
    try:
        async with httpx.AsyncClient(
            timeout=timeout, transport=transport, follow_redirects=False
        ) as client:
            response = await client.get(
                url,
                headers={"Accept": "application/json", "User-Agent": "astrbot-plugin-nikke/1.0"},
            )
    except httpx.HTTPError as exc:
        raise ShareProfileError("公开分享资料暂不可用（网络异常）") from exc
    if response.status_code == 404:
        raise ShareProfileError("该公开分享不存在或未公开")
    if response.status_code in (401, 403):
        raise ShareProfileError("该公开分享未授权公开")
    if response.status_code == 503:
        raise ShareProfileError("公开分享服务当前未配置查询账号")
    if response.status_code != 200:
        raise ShareProfileError(f"公开分享服务返回 HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ShareProfileError("公开分享响应不是 JSON") from exc
    return parse_share_profile(payload)


def render_share_profile(profile: ShareProfile) -> str:
    def value(item: int | None) -> str:
        return "未知" if item is None else str(item)

    return "\n".join(
        (
            f"【公开分享资料】{profile.nickname}",
            f"等级：{value(profile.level)} · 队伍总战力：{value(profile.team_combat)}",
            f"角色数量：{value(profile.nikke_count)} · 同步器：{value(profile.synchro_level)}",
            f"普通主线：{profile.normal_stage} · 困难主线：{profile.hard_stage}",
            profile.note,
            f"来源：{profile.source_url}",
        )
    )


__all__ = [
    "SHARE_API_BASE",
    "SHARE_NOTE",
    "SHARE_SOURCE",
    "ShareProfile",
    "ShareProfileError",
    "fetch_public_share",
    "parse_share_profile",
    "render_share_profile",
    "validate_share_id",
]

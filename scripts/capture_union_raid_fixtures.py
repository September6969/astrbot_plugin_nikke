# SPDX-License-Identifier: GPL-3.0-or-later
"""从官网已确认 endpoint 抓取并完全脱敏联盟突袭响应结构。"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from astrbot_plugin_nikke.client import API_BASE
from astrbot_plugin_nikke.storage import NikkeStore
from astrbot_plugin_nikke.scripts.raid_evidence import semantic_sanitize


MY_GUILD = "/api/game/proxy/Game/GetMyGuildInfo"
CURRENT_RAID = "/api/game/proxy/Game/GetUnionRaidData"
CURRENT_RAID_LEVEL = "/api/game/proxy/Game/GetUnionRaidLevelInfo"


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return 0
    if isinstance(value, float):
        return 0.0
    if isinstance(value, str):
        return "[已脱敏]" if value else ""
    return None


def find_first(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if value.get(key) not in (None, ""):
            return value[key]
        for item in value.values():
            found = find_first(item, key)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_first(item, key)
            if found not in (None, ""):
                return found
    return None


async def post(client: httpx.AsyncClient, account: dict[str, Any], path: str, payload: dict[str, Any]) -> dict:
    response = await client.post(
        API_BASE + path,
        json=payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Cookie": account["cookie"],
            "Origin": "https://www.blablalink.com",
            "Referer": "https://www.blablalink.com/",
        },
    )
    response.raise_for_status()
    return response.json()


async def capture(data_dir: Path, output_dir: Path) -> None:
    accounts = NikkeStore(data_dir).list_accounts(with_cookie=True)
    if len(accounts) != 1:
        raise RuntimeError("需要恰好一个授权绑定账号，避免隐式选择其它账号")
    account = accounts[0]
    area_id = int(account.get("area_id") or 0)
    openid = str(account.get("game_openid") or "")
    if not area_id or not openid:
        raise RuntimeError("授权账号缺少游戏上下文")
    game_openid = openid

    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        guild = await post(client, account, MY_GUILD, {"ignore_toast": True})
        if str(guild.get("code", "")) not in {"", "0"}:
            raise RuntimeError(f"GetMyGuildInfo 返回业务码 {guild.get('code')}")
        guild_id = find_first(guild.get("data", {}), "guild_id")
        if not guild_id:
            raise RuntimeError("授权账号当前没有可识别的联盟 guild_id")

        payload = {"guild_id": guild_id, "nikke_area_id": area_id, "intl_open_id": game_openid}
        level_response = await post(client, account, CURRENT_RAID_LEVEL, payload)
        raid_response = await post(client, account, CURRENT_RAID, payload)

    for response in (level_response, raid_response):
        if str(response.get("code")) != "0" or not isinstance(response.get("data"), dict):
            raise RuntimeError("突袭读取失败，不生成成功 fixture")

    level_data = level_response.get("data", {})
    raid_data = raid_response.get("data", {})
    boss_rows = []
    for level in level_data.get("level_info", []):
        if isinstance(level, dict):
            boss_rows.extend(item for item in level.get("boss_info", []) if isinstance(item, dict))
    candidates = {openid, game_openid}
    try:
        common_params = json.loads(str(account.get("x_common_params") or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        common_params = {}
    if isinstance(common_params, dict):
        context_openid = str(common_params.get("openid") or "")
        if context_openid:
            candidates.add(context_openid)
    my_records = [
        item
        for item in raid_data.get("participate_data", [])
        if isinstance(item, dict) and str(item.get("openid", "")) in candidates
    ]
    responses = {
        "union_raid_overview.json": (CURRENT_RAID_LEVEL, level_response, level_data),
        "union_raid_boss_list.json": (
            CURRENT_RAID_LEVEL,
            level_response,
            {"boss_info": boss_rows},
        ),
        "union_raid_ranking.json": (CURRENT_RAID, raid_response, raid_data),
        "union_raid_my_data.json": (
            CURRENT_RAID,
            raid_response,
            {"participate_data": my_records},
        ),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    # 对整组响应统一转换，保证 ranking/my 两份证据中的匿名关系一致。
    semantic = semantic_sanitize({name: data for name, (_, _, data) in responses.items()})
    (output_dir / "union_raid_semantic.json").write_text(
        json.dumps({"kind": "synthetic_proportional", "data": semantic}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for name, (endpoint, response, data) in responses.items():
        content = {
            "endpoint": endpoint,
            "method": "POST",
            "request_keys": sorted(payload),
            "business_code": str(response.get("code", "")),
            "data": sanitize(data),
        }
        (output_dir / name).write_text(
            json.dumps(content, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(capture(args.data_dir, args.output_dir))


if __name__ == "__main__":
    main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""用已授权账号抓取并完全脱敏 Profile/Outpost 响应结构。"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from astrbot_plugin_nikke.integrations.blablalink.client import BlaBlaClient, OUTPOST, PROFILE
from astrbot_plugin_nikke.core.storage import NikkeStore


def sanitize(value: Any) -> Any:
    """保留全部键与容器结构，将所有实际标量替换为同类型安全值。"""
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


async def capture(data_dir: Path, output_dir: Path) -> None:
    store = NikkeStore(data_dir)
    accounts = store.list_accounts(with_cookie=True)
    if not accounts:
        raise RuntimeError("没有可用的授权绑定账号")
    account = accounts[0]
    area_id = str(account.get("area_id", ""))
    if not area_id:
        raise RuntimeError("授权账号缺少 area_id")

    payload: dict[str, Any] = {"nikke_area_id": int(area_id)}
    if account.get("game_openid"):
        payload["intl_open_id"] = account["game_openid"]

    client = BlaBlaClient()
    profile, outpost = await asyncio.gather(
        client._post(PROFILE, account["cookie"], payload),
        client._post(OUTPOST, account["cookie"], {"nikke_area_id": int(area_id)}),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "profile_basic_full_keys.json": {
            "endpoint": PROFILE,
            "method": "POST",
            "request_keys": sorted(payload),
            "data": sanitize(profile.get("data", {})),
        },
        "outpost_full_keys.json": {
            "endpoint": OUTPOST,
            "method": "POST",
            "request_keys": ["nikke_area_id"],
            "data": sanitize(outpost.get("data", {})),
        },
    }
    for name, content in files.items():
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

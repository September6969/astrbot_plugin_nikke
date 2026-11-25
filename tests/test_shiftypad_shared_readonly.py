# SPDX-License-Identifier: GPL-3.0-or-later
"""ShiftyPad 只读快照接入既有愿望单/单人突袭：fresh、隔离与 stale 边界。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from astrbot_plugin_nikke.application.commands.toolbox import ToolboxCommandHandler
from astrbot_plugin_nikke.features.shiftypad.models import (
    ShiftypadCharacter,
    ShiftypadIdentity,
    ShiftypadPrivateError,
    ShiftypadProfile,
)
from astrbot_plugin_nikke.features.shiftypad.storage import ShiftypadReadOnlyStore
from astrbot_plugin_nikke.main import NikkePlugin
from plugin_fixtures import make_plugin_shell
from test_command_routing_contract import Event
from test_toolbox_commands import MemoryStore, toolbox_services

OPENID = "12345-1234567890"


def directory_rows() -> tuple[dict, ...]:
    rows: list[dict] = []
    for index in range(1, 6):
        rows.append({
            "name_code": 9000 + index, "resource_id": 700 + index,
            "name_zh_cn": f"一号{index}", "name_zh_tw": f"一號{index}",
            "rare": "SSR", "corporation": "ELYSION", "pool_status": "ordinary_recruit",
            "burst": "Step1", "element": "Fire",
        })
        rows.append({
            "name_code": 9100 + index, "resource_id": 800 + index,
            "name_zh_cn": f"二号{index}", "name_zh_tw": f"二號{index}",
            "rare": "SSR", "corporation": "MISSILIS", "pool_status": "ordinary_recruit",
            "burst": "Step2", "element": "Wind",
        })
    for index in range(1, 16):
        rows.append({
            "name_code": 9200 + index, "resource_id": 900 + index,
            "name_zh_cn": f"三号{index}", "name_zh_tw": f"三號{index}",
            "rare": "SSR", "corporation": "TETRA", "pool_status": "ordinary_recruit",
            "burst": "Step3", "element": "Iron",
        })
    return tuple(rows)


def profile(actor_openid: str = OPENID, *, empty_characters: bool = False) -> ShiftypadProfile:
    rows = directory_rows()
    return ShiftypadProfile(
        identity=ShiftypadIdentity(
            openid=actor_openid, uid="123456789", server="na", area_id="83",
            source="trusted_mapping", source_url="https://example.invalid/map.json",
        ),
        nickname="只读指挥官",
        level=300,
        team_combat=123456,
        nikke_count=len(rows),
        synchro_level=200,
        visibility="public",
        characters=() if empty_characters else tuple(
            ShiftypadCharacter(
                name_code=str(row["name_code"]), level=200, grade=2, combat=100000
            )
            for row in rows
        ),
        fetched_at="2026-11-23T00:00:00+00:00",
    )


class PrivateFetcher:
    async def fetch(self, _identity):
        raise ShiftypadPrivateError("公开开关已关闭")


def plugin_with_readonly(actor: str, *, empty_characters: bool = False):
    store = MemoryStore()
    services = toolbox_services(store)
    services.account_reader = None
    rows = directory_rows()
    services.grid_rows = rows
    services.wishlist_rows = rows
    readonly = ShiftypadReadOnlyStore(store)
    readonly.bind(actor, profile(empty_characters=empty_characters))
    services.shiftypad_readonly = readonly
    plugin = make_plugin_shell()
    plugin.config = {}
    plugin.handlers.toolbox = ToolboxCommandHandler(services)
    return plugin, services, readonly


async def route(plugin: NikkePlugin, command: str, arg1: str = "", arg2: str = "") -> str:
    results = [item async for item in plugin.nikke(Event(), command, arg1, arg2)]
    assert results
    return results[0][1]


@pytest.mark.asyncio
async def test_fresh_readonly_snapshot_feeds_wishlist_and_solo_raid() -> None:
    plugin, _, _ = plugin_with_readonly("synthetic-user")
    wishlist = await route(plugin, "愿望单", "均衡")
    assert "角色来源：ShiftyPad 只读快照" in wishlist
    assert "测试" not in wishlist
    assert "一号1" in wishlist or "三号1" in wishlist

    solo = await route(plugin, "单人突袭", "编组")
    assert "角色来源：ShiftyPad 只读快照" in solo
    assert "第 1 队" in solo
    assert "缺少可靠伤害公式" in solo
    # 角色目录补齐的爆裂定位被使用，而不是凭空写死。
    assert "爆裂链：全部通过" in solo


@pytest.mark.asyncio
async def test_stale_or_other_users_snapshot_does_not_recommend() -> None:
    plugin, _, readonly = plugin_with_readonly("synthetic-user")
    await readonly.sync("synthetic-user", PrivateFetcher())
    stale_wishlist = await route(plugin, "愿望单", "均衡")
    assert "没有 fresh 的 ShiftyPad 只读绑定" in stale_wishlist
    stale_solo = await route(plugin, "单人突袭", "编组")
    assert "没有 fresh 的 ShiftyPad 只读绑定" in stale_solo

    other_plugin, _, _ = plugin_with_readonly("other-user")
    other_wishlist = await route(other_plugin, "愿望单", "均衡")
    assert "没有 fresh 的 ShiftyPad 只读绑定" in other_wishlist
    other_solo = await route(other_plugin, "单人突袭", "编组")
    assert "没有 fresh 的 ShiftyPad 只读绑定" in other_solo


@pytest.mark.asyncio
async def test_manual_pool_still_takes_precedence_over_readonly() -> None:
    plugin, _, _ = plugin_with_readonly("synthetic-user")
    manual = await route(plugin, "愿望单", "均衡", "测试1号:2")
    assert "角色来源：手工输入。" in manual
    assert "ShiftyPad 只读快照" not in manual


@pytest.mark.asyncio
async def test_empty_readonly_characters_is_an_explicit_gap_not_fake_roster() -> None:
    plugin, _, _ = plugin_with_readonly("synthetic-user", empty_characters=True)
    wishlist = await route(plugin, "愿望单", "均衡")
    assert "没有角色字段" in wishlist
    solo = await route(plugin, "单人突袭", "编组")
    assert "没有角色字段" in solo

# SPDX-License-Identifier: GPL-3.0-or-later
"""十项本地工具的适配器路由与命令入口集成验收（合成数据、离线）。"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from astrbot_plugin_nikke.application.commands.contracts import ImageReply, TextReply
from astrbot_plugin_nikke.application.commands.toolbox import ToolboxCommandHandler
from astrbot_plugin_nikke.features.announcement.feeds import (
    FeedCatalog,
    FeedSubscriptions,
    VideoCatalog,
)
from astrbot_plugin_nikke.features.calendar.canonical_models import CanonicalEvent
from astrbot_plugin_nikke.features.character.identity import CharacterDirectoryResolver
from astrbot_plugin_nikke.features.counsel.bank import CounselBank
from astrbot_plugin_nikke.features.favorite_grid.grid import FavoriteRanking
from astrbot_plugin_nikke.features.growth.history import GrowthHistory
from astrbot_plugin_nikke.features.identity.public_profile import ManualProfileStore
from astrbot_plugin_nikke.features.solo_raid.plans import SoloRaidPlanStore
from astrbot_plugin_nikke.features.solo_raid.seasons import SeasonCatalog
from astrbot_plugin_nikke.integrations.nikke_calc.engine import SoloRaidDamageEngine
from astrbot_plugin_nikke.features.sync.cost_table import SyncCostTable
from astrbot_plugin_nikke.integrations.nikke_calc.engine import SoloRaidDamageEngine
from astrbot_plugin_nikke.main import NikkePlugin
from plugin_fixtures import make_plugin_shell
from test_command_routing_contract import Event


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def get_setting(self, key, default=None):
        return self.values.get(key, default)

    def set_setting(self, key, value):
        self.values[key] = value


class EmptyCatalog:
    def items(self, *, now):
        return ()


class EmptyVideoSource:
    cached_items = ()
    last_error = "测试未同步"

    async def refresh(self, *, now=None):
        return self.cached_items


SOURCE = "https://example.invalid/synthetic-toolbox.json"


def grid_rows() -> tuple[dict, ...]:
    return tuple(
        {
            "name_code": 9000 + index,
            "resource_id": 700 + index,
            "name_zh_cn": f"测试{index}号",
            "name_zh_tw": f"測試{index}號",
            "name_en": f"Test Unit {index}",
            "rare": "SSR",
            "burst": ("Step1", "Step2", "Step3")[index % 3],
            "element": "Fire",
        }
        for index in range(1, 13)
    )


def counsel_bank() -> CounselBank:
    return CounselBank.from_payload(
        {
            "schema_version": 1,
            "source_url": SOURCE,
            "license": "synthetic-only",
            "checked_at": "2026-09-21",
            "entries": [
                {
                    "id": "c1",
                    "nikke": "测试1号",
                    "aliases": ["一号"],
                    "question": "作战时会怎么做？",
                    "keywords": ["作战"],
                    "options": [
                        {"id": "a", "label": "稳扎稳打"},
                        {"id": "b", "label": "主动出击"},
                    ],
                    "answer_id": "a",
                    "source_url": SOURCE,
                }
            ],
        }
    )


def toolbox_services(store: MemoryStore) -> SimpleNamespace:
    now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
    events = (
        CanonicalEvent(
            id="pool", title="合成卡池", event_type="recruit",
            start_at=datetime(2026, 9, 20, 2, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 10, 2, 2, 0, tzinfo=timezone.utc),
        ),
        CanonicalEvent(
            id="skin", title="合成皮肤", event_type="costume_gacha",
            start_at=datetime(2026, 9, 21, 2, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 9, 25, 2, 0, tzinfo=timezone.utc),
        ),
    )
    calendar = SimpleNamespace(
        query_schedule=lambda: SimpleNamespace(
            service_available=True,
            has_snapshot=True,
            context=SimpleNamespace(events=events, now=now),
        )
    )
    feeds = FeedSubscriptions(
        store,
        FeedCatalog(
            {
                "news": EmptyCatalog(),
                "schedule": EmptyCatalog(),
                "video": VideoCatalog(EmptyVideoSource()),
            }
        ),
        clock=lambda: now,
    )
    table = SyncCostTable.from_records(
        (
            {"level": 200, "core_dust": 1000, "credits": 1000, "battle_data": 100},
            {"level": 201, "core_dust": 1100, "credits": 1100, "battle_data": 110},
        ),
        source_url=SOURCE,
        checked_at="2026-09-21",
    )
    season_catalog = SeasonCatalog.from_payload(
        {
            "schema_version": 1,
            "seasons": [
                {
                    "id": "s1", "name": "合成赛季", "source_url": SOURCE,
                    "checked_at": "2026-09-21",
                    "bosses": [{"id": "b1", "name": "合成首领", "weakness": "风压", "element": "Wind"}],
                }
            ],
        }
    )

    async def roster_loader(_account):
        return [
            {"name_code": 9001, "burst": "Step1", "grade": 2},
            {"name_code": 9002, "burst": "Step2", "grade": 0},
        ]

    async def profile_loader(_account):
        return {
            "basic": {
                "nickname": "合成指挥官",
                "lv": 120,
                "team_combat": 123456,
                "currencies": [
                    {"type": 3000, "value": 500},
                    {"type": 2000, "value": 800},
                    {"type": 1000, "value": 50},
                ],
            },
            "outpost": {"synchro_level": 199, "outpost_battle_level": 120},
        }

    return SimpleNamespace(
        calendar=calendar,
        feeds=feeds,
        counsel=counsel_bank(),
        sync_table=table,
        sync_table_error="",
        wishlist_rows=grid_rows(),
        wishlist_exclusions=(),
        overload_recommendations={},
        overload_recommendation_label="",
        solo_catalog=season_catalog,
        solo_plans=SoloRaidPlanStore(store),
        solo_damage_model=None,
        roster_loader=roster_loader,
        profile_loader=profile_loader,
        account_reader=SimpleNamespace(
            get_account=lambda actor: {
                "game_uid": "123456789",
                "nickname": "合成指挥官",
            }
        ),
        manual_profiles=ManualProfileStore(store),
        growth=GrowthHistory(store),
        grid_rows=grid_rows(),
        grid_resolver=CharacterDirectoryResolver(),
        grid_ranking=FavoriteRanking(store),
    )


def plugin_with_toolbox(store: MemoryStore | None = None):
    store = store or MemoryStore()
    plugin = make_plugin_shell()
    plugin.config = {}
    plugin.handlers.toolbox = ToolboxCommandHandler(toolbox_services(store))
    return plugin, store


async def route(plugin: NikkePlugin, command: str, arg1: str = "", arg2: str = "") -> str:
    results = [item async for item in plugin.nikke(Event(), command, arg1, arg2)]
    assert results, (command, arg1, arg2)
    kind, payload = results[0]
    assert kind == "plain", (kind, payload)
    return payload


@pytest.mark.asyncio
async def test_calendar_board_route_groups_and_missing_probability() -> None:
    plugin, _ = plugin_with_toolbox()
    text = await route(plugin, "卡池")
    assert "【卡池】" in text and "【皮肤】" in text
    assert "UP 概率：官方日程未提供可靠概率字段（缺失，未推断）" in text
    assert "北京时间" in text

    only_skin = await route(plugin, "卡池", "皮肤")
    assert "【皮肤】" in only_skin
    assert "【卡池】" not in only_skin
    assert "未知类型" in await route(plugin, "卡池", "直播")


@pytest.mark.asyncio
async def test_news_subscription_route_is_personal_and_explicit() -> None:
    plugin, _ = plugin_with_toolbox()
    assert "尚未开通订阅" in await route(plugin, "新闻", "状态")
    assert "已订阅" in await route(plugin, "新闻", "订阅", "新闻")
    status_text = await route(plugin, "新闻", "状态")
    assert "已订阅（个人订阅）：新闻" in status_text
    assert "enable_announcement_push" in status_text
    assert "已取消" in await route(plugin, "新闻", "取消订阅")


@pytest.mark.asyncio
async def test_counsel_sync_wishlist_and_overload_routes() -> None:
    plugin, _ = plugin_with_toolbox()
    counsel = await route(plugin, "咨询", "一号", "作战")
    assert "【咨询答案】" in counsel and "稳扎稳打" in counsel and "【推荐】" in counsel

    sync = await route(plugin, "同步器", "计算", "199 201 0 0 0 100 100 10")
    assert "同步器等级" in sync
    assert "瓶颈" in sync

    account_sync = await route(plugin, "同步器", "计算", "账号 201 100 100 10")
    assert "当前等级来自已绑定账号只读资料" in account_sync

    wishlist = await route(plugin, "愿望单", "均衡", "测试1号:2")
    assert "愿望单推荐" in wishlist
    assert "覆盖限制" in wishlist

    advice = await route(plugin, "洗词条", "攻击力增加", "头部,1,防御力增加,4")
    assert "【超限洗词条助手】" in advice
    assert "重洗" in advice
    simulation = await route(plugin, "洗词条模拟", "攻击力增加", "头部,1,防御力增加,4")
    assert "模拟：" in simulation
    assert "系统随机" in simulation
    assert "定制模块" in simulation

    # 支持读取已绑定账号角色的实际装备词条进行只读对比。
    async def fake_card_loader(_actor, _query):
        return SimpleNamespace(
            name_cn="拉毗",
            equipment={
                "head": SimpleNamespace(
                    equipped=True,
                    options=(SimpleNamespace(display_name="防御力增加", tier=6, locked=False),),
                )
            },
        )

    plugin.handlers.toolbox._domain_handlers["calc_tools"].services.card_loader = fake_card_loader
    bound_advice = await route(plugin, "洗词条", "攻击力增加", "账号:拉毗")
    assert "已绑定账号角色实际超限词条（拉毗" in bound_advice
    assert "防御力增加（6 阶）" in bound_advice


@pytest.mark.asyncio
async def test_solo_raid_uid_growth_and_grid_routes() -> None:
    plugin, _ = plugin_with_toolbox()
    season_text = await route(plugin, "单人突袭", "赛季")
    assert "合成赛季" in season_text and "合成首领" in season_text

    names = "测试1号:B1,测试2号:B2,测试3号:B3,测试4号:B3,测试5号:B3,测试6号:B1,测试7号:B2,测试8号:B3,测试9号:B3"
    plan_text = await route(plugin, "单人突袭", "编组", names)
    assert "第 1 队" in plan_text
    assert "缺少可靠伤害公式" in plan_text
    saved = await route(plugin, "单人突袭", "保存", names)
    assert "仅你本人可见" in saved
    mine = await route(plugin, "单人突袭", "我的")
    assert "已保存方案" in mine
    one_team = await route(plugin, "单人突袭", "队", "1")
    assert "第 1 队" in one_team
    assert "仅你自己可见" in one_team

    uid_text = await route(plugin, "uid", "123456789")
    assert "OWN_BOUND_UID" not in uid_text
    assert "与你当前绑定的账号一致" in uid_text
    assert "公开 UID 查询：不可用" in uid_text

    empty_growth = await route(plugin, "养成历史")
    assert "暂无成长快照" in empty_growth
    saved_manual = await route(plugin, "我的妮姬", "手工", "手工昵称,120,备注")
    assert "已保存本人手工资料" in saved_manual
    assert "未验证" in saved_manual
    assert "手工昵称" in await route(plugin, "我的妮姬", "手工状态")

    grid = await route(
        plugin, "九宫格",
        "测试1号,测试2号,测试3号,测试4号,测试5号,测试6号,测试7号,测试8号,测试9号",
    )
    assert "P1 测试1号" in grid and "P9 测试9号" in grid
    rank = await route(plugin, "本命榜")
    assert "【本命九宫格 · 人气榜 TOP 10】" in rank
    assert "测试1号（1 票）" in rank


@pytest.mark.asyncio
async def test_tool_help_and_unknown_tool_state() -> None:
    plugin, _ = plugin_with_toolbox()
    tool_help = await route(plugin, "帮助", "工具")
    assert "【工具】" in tool_help
    assert "/妮姬 九宫格" in tool_help

    shell = make_plugin_shell()
    text = await route(shell, "卡池")
    assert "本地工具功能尚未就绪" in text


@pytest.mark.asyncio
async def test_manual_sync_costs_work_without_operator_table() -> None:
    store = MemoryStore()
    services = toolbox_services(store)
    services.sync_table = None
    services.sync_table_error = "未配置同步器等级成本表（缺少可靠成本数据，不猜测等级消耗）。"
    plugin = make_plugin_shell()
    plugin.config = {}
    plugin.handlers.toolbox = ToolboxCommandHandler(services)

    missing = await route(plugin, "同步器", "计算", "199 201 0 0 0 100 100 10")
    assert "手工成本" in missing
    assert "未配置同步器等级成本表" in missing

    manual = await route(
        plugin, "同步器", "计算",
        "手工 199 201 0 0 0 100 100 10 3000 4500 1200",
    )
    assert "同步器等级" in manual
    assert "成本来源：用户手工输入（未验证；仅用于本次计算）" in manual
    assert "预计" in manual
    assert "瓶颈" in manual


@pytest.mark.asyncio
async def test_imported_season_43_is_displayed_as_ended_with_boss_and_lineup() -> None:
    from astrbot_plugin_nikke.features.solo_raid.seasons import SeasonCatalog

    store = MemoryStore()
    services = toolbox_services(store)
    services.solo_catalog = SeasonCatalog.from_payload(
        {
            "schema_version": 1,
            "seasons": [
                {
                    "id": "43",
                    "name": "赛季 43",
                    "source_url": "https://www.blablalink.com/?plate_type=official",
                    "checked_at": "2026-11-24",
                    "ends_at": "2026-11-18T19:59:00+00:00",
                    "bosses": [
                        {
                            "id": "solo-43-boss",
                            "name": "Goddess of Victory",
                            "weakness": "燃烧",
                            "element": "风压",
                        }
                    ],
                }
            ],
        }
    )
    plugin = make_plugin_shell()
    plugin.config = {}
    plugin.handlers.toolbox = ToolboxCommandHandler(
        services,
        clock=lambda: datetime(2026, 12, 1, tzinfo=timezone.utc),
    )

    season_text = await route(plugin, "单人突袭", "赛季")
    assert "赛季 43" in season_text
    assert "Goddess of Victory" in season_text
    assert "弱点 燃烧" in season_text and "属性 风压" in season_text
    assert "已结束" in season_text
    assert "2026-11-19 04:59" in season_text
    assert "不会显示为进行中" in season_text

    names = (
        "测试1号:B1,测试2号:B2,测试3号:B3,测试4号:B3,测试5号:B3,"
        "测试6号:B1,测试7号:B2,测试8号:B3,测试9号:B3"
    )
    lineup = await route(plugin, "单人突袭", "编组", names)
    assert "Goddess of Victory" in lineup
    assert "缺少可靠伤害公式" in lineup


@pytest.mark.asyncio
async def test_solo_raid_command_uses_local_mit_engine_when_configured() -> None:
    from pathlib import Path

    store = MemoryStore()
    services = toolbox_services(store)
    names = []
    for index in range(1, 6):
        names.append(f"L1-{index}:B1")
        names.append(f"L2-{index}:B2")
    for index in range(1, 16):
        names.append(f"L3-{index}:B3")
    pool = ",".join(names)
    engine_path = Path(__file__).resolve().parent / "fixtures" / "fake_nikke_calc"
    mapping = {name.split(":")[0]: name.split(":")[0] for name in names}
    services.solo_engine = SoloRaidDamageEngine(
        engine_path, mapping, python=sys.executable, timeout=30,
        work_dir=Path("output") / ".engine-runs",
    )
    plugin = make_plugin_shell()
    plugin.config = {}
    plugin.handlers.toolbox = ToolboxCommandHandler(services)

    text = await route(plugin, "单人突袭", "编组", pool)
    assert "伤害：" in text
    assert "nikke-calc" in text
    assert "MIT" in text
    assert "不是官方伤害数值" in text
    assert "无法估伤" not in text

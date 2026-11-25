# SPDX-License-Identifier: GPL-3.0-or-later
"""合规数据边界验证：默认不随仓分发无开源许可网页数据，仅内置 MIT 衍生名称映射与显式缺口降级。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from astrbot_plugin_nikke.application.commands.toolbox import ToolboxCommandHandler
from astrbot_plugin_nikke.core.providers.toolbox import create_toolbox_services
from astrbot_plugin_nikke.features.counsel.bank import CounselBank
from astrbot_plugin_nikke.features.overload_advice.advisor import (
    load_character_targets,
    load_default_line_counts,
    load_recommendations,
)
from astrbot_plugin_nikke.features.solo_raid.seasons import SeasonCatalog
from astrbot_plugin_nikke.features.sync.cost_table import SyncCostTable
from astrbot_plugin_nikke.integrations.nikke_calc.engine import load_name_mapping
from plugin_fixtures import make_plugin_shell
from test_command_routing_contract import Event
from test_toolbox_commands import MemoryStore

ROOT = Path(__file__).resolve().parents[1]


async def route(plugin, command: str, arg1: str = "", arg2: str = "") -> str:
    results = [item async for item in plugin.nikke(Event(), command, arg1, arg2)]
    assert results
    return results[0][1]


def test_unlicensed_third_party_banks_are_not_bundled_and_degrade_safely() -> None:
    from astrbot_plugin_nikke.features.catalog import public_catalog_payload

    for rel in (
        "assets/data/counsel_bank.json",
        "assets/data/sync-level-costs.json",
    ):
        assert not (ROOT / rel).exists(), f"不应默认随仓分发无开源许可或旧命名资产：{rel}"

    # 同步器(WTFPL+交叉核验)、前哨(Lv.1-800)、超限(MIT 200角色)与突袭赛季(MIT+公告 S36-43)均已合法入仓。
    assert (ROOT / "assets" / "data" / "sync_level_costs.json").is_file()
    assert (ROOT / "assets" / "data" / "outpost_rates.json").is_file()
    assert (ROOT / "assets" / "data" / "overload_recommendations.json").is_file()
    assert (ROOT / "assets" / "data" / "solo_raid_seasons.json").is_file()

    services = create_toolbox_services(
        plugin_dir=ROOT,
        data_dir=ROOT / "output" / ".nonexistent-data",
        store=MemoryStore(),
        calendar=None,
        announcements=None,
        account_reader=None,
        roster_loader=None,
        profile_loader=None,
        config={},
    )
    assert services.counsel.available is False
    # 咨询题库未导入时，公共目录默认隐藏 counsel.search 入口
    public_ids = {f["id"] for f in public_catalog_payload({"counsel_available": False})["features"]}
    assert "counsel.search" not in public_ids

    assert isinstance(services.sync_table, SyncCostTable)
    assert services.sync_table.levels[0] == 2 and services.sync_table.levels[-1] == 1400
    assert services.sync_table_error == ""
    assert services.outpost_table is not None and services.outpost_table.max_level == 800
    assert len(services.overload_character_targets or {}) == 200
    assert services.solo_catalog.available is True
    assert services.solo_catalog.latest().season_id == "43"


def test_mit_derived_engine_name_mapping_loads_cleanly() -> None:
    path = ROOT / "assets" / "data" / "solo_raid_engine_names.json"
    assert path.is_file()
    mapping = load_name_mapping(path)
    assert len(mapping) >= 200
    assert (ROOT / "integrations" / "nikke_calc" / "LICENSE-nikke-calc.txt").is_file()


@pytest.mark.asyncio
async def test_operator_imported_data_files_work_through_commands(tmp_path: Path) -> None:
    counsel_path = tmp_path / "counsel-bank.json"
    counsel_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_url": "https://example.invalid/counsel",
                "license": "Operator Authorized",
                "checked_at": "2026-11-24",
                "entries": [
                    {
                        "id": "c-1",
                        "nikke": "艾德米",
                        "aliases": ["Admi"],
                        "question_no": 1,
                        "question": "遇到流浪猫时",
                        "keywords": ["猫咪", "温柔"],
                        "options": [
                            {"id": "1", "label": "轻轻抚摸"},
                            {"id": "2", "label": "转身离开"},
                        ],
                        "answer_id": "1",
                        "answer_index": 1,
                        "source_url": "https://example.invalid/counsel/c-1",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    sync_path = tmp_path / "sync-level-costs.json"
    sync_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "label": "运营者导入成本表",
                "source_url": "https://example.invalid/sync",
                "checked_at": "2026-11-24",
                "levels": [
                    {
                        "level": 201,
                        "core_dust": 10000,
                        "credits": 1694200,
                        "battle_data": 20944600,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    overload_path = tmp_path / "overload-recommendations.json"
    overload_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_url": "https://example.invalid/overload",
                "checked_at": "2026-11-24",
                "default_line_counts": {"element_bonus": 4, "atk_pct": 2},
                "default_targets": ["优越代码伤害增加", "攻击力增加"],
                "recommendations": {
                    "alice": {
                        "targets": [
                            {"label": "优越代码伤害增加", "count": 4},
                            {"label": "攻击力增加", "count": 4},
                        ],
                        "flex_count": 0,
                        "source_url": "https://example.invalid/overload/alice",
                        "checked_at": "2026-11-24",
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    season_path = tmp_path / "solo-raid-seasons.json"
    season_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "seasons": [
                    {
                        "id": "43",
                        "name": "赛季 43",
                        "source_url": "https://example.invalid/solo-43",
                        "checked_at": "2026-11-24",
                        "ends_at": "2026-11-01T19:59:00+00:00",
                        "bosses": [
                            {"id": "b1", "name": "Boss A", "weakness": "燃烧", "element": "风压"}
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    services = create_toolbox_services(
        plugin_dir=ROOT,
        data_dir=tmp_path,
        store=MemoryStore(),
        calendar=None,
        announcements=None,
        account_reader=None,
        roster_loader=None,
        profile_loader=None,
        config={},
    )
    assert isinstance(services.counsel, CounselBank) and services.counsel.available
    assert isinstance(services.sync_table, SyncCostTable)
    assert services.solo_catalog.available
    assert "__default__" in services.overload_recommendations
    assert set(load_character_targets(overload_path)) == {"alice"}
    assert load_default_line_counts(overload_path)["优越代码伤害增加"] == 4
    assert "__default__" in load_recommendations(overload_path)
    assert SeasonCatalog.from_file(season_path).available

    plugin = make_plugin_shell()
    plugin.config = {}
    plugin.handlers.toolbox = ToolboxCommandHandler(services)
    assert "轻轻抚摸" in await route(plugin, "咨询", "艾德米", "猫咪")
    assert "1,694,200" in await route(plugin, "同步器", "计算", "200 201 0 0 0 100000 100000 100000")
    assert "赛季 43" in await route(plugin, "单人突袭", "赛季")

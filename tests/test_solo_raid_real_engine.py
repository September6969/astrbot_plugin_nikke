# SPDX-License-Identifier: GPL-3.0-or-later
"""真实 MIT 引擎 smoke：有本地检出时经机器人命令跑五队估伤。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from astrbot_plugin_nikke.application.commands.toolbox import ToolboxCommandHandler
from astrbot_plugin_nikke.features.solo_raid.plans import SoloRaidPlanStore
from astrbot_plugin_nikke.features.solo_raid.seasons import SeasonCatalog
from astrbot_plugin_nikke.integrations.nikke_calc.engine import (
    PINNED_COMMIT,
    SoloRaidDamageEngine,
    load_name_mapping,
)
from astrbot_plugin_nikke.main import NikkePlugin
from plugin_fixtures import make_plugin_shell
from test_command_routing_contract import Event
from test_toolbox_commands import MemoryStore

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "output" / "nikke-calc"
MAPPING = ROOT / "assets" / "data" / "solo_raid_engine_names.json"


@pytest.mark.asyncio
@pytest.mark.skipif(
    not (ENGINE / "runner" / "sim.py").is_file() or not MAPPING.is_file(),
    reason="本地 nikke-calc 检出或映射不存在",
)
async def test_real_engine_through_solo_raid_command() -> None:
    mapping = load_name_mapping(MAPPING)
    master = json.loads((ROOT / "assets" / "data" / "character_master.json").read_text(encoding="utf-8"))["characters"]
    rows = [
        row for row in master
        if str(row.get("name_code")) in mapping or str(row.get("resource_id")) in mapping
    ]
    buckets = {"Step1": [], "Step2": [], "Step3": []}
    for row in rows:
        if row.get("burst") in buckets:
            buckets[row["burst"]].append(row)
    selected = []
    for stage, count in (("Step1", 5), ("Step2", 5), ("Step3", 15)):
        selected.extend(buckets[stage][:count])
    if len(selected) < 25:
        pytest.skip("本机角色目录与引擎映射交集不足 25 人")

    pool = ",".join(f"{row.get('name_cn') or row.get('name_zh_tw')}:{ {'Step1':'B1','Step2':'B2','Step3':'B3'}[row['burst']] }" for row in selected)
    services = SimpleNamespace(
        solo_catalog=SeasonCatalog.from_file(ROOT / "assets" / "data" / "solo_raid_seasons.json"),
        solo_plans=SoloRaidPlanStore(MemoryStore()),
        solo_damage_model=None,
        solo_engine=SoloRaidDamageEngine(
            ENGINE, mapping, timeout=180, concurrency=2,
            work_dir=ROOT / "output" / ".engine-runs",
        ),
        grid_rows=tuple(selected),
        wishlist_rows=tuple(selected),
        account_reader=None,
    )
    plugin = make_plugin_shell()
    plugin.config = {}
    plugin.handlers.toolbox = ToolboxCommandHandler(services)
    result = [item async for item in plugin.nikke(Event(), "单人突袭", "编组", pool)]
    text = result[0][1]
    assert "伤害：" in text
    assert "nikke-calc" in text
    assert "不是官方伤害" in text
    assert "无法估伤" not in text
    assert PINNED_COMMIT in text

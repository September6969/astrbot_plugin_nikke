# SPDX-License-Identifier: GPL-3.0-or-later
"""PR-4A：角色/突袭/战役/资料核心修复与客户端缓存（AUD-010 / AUD-019 / AUD-021 / AUD-024）。"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from astrbot_plugin_nikke.application.commands.character import CharacterCommandHandler
from astrbot_plugin_nikke.features.campaign.stage_resolver import CampaignStageResolver
from astrbot_plugin_nikke.features.character.builder import CharacterCardBuilder
from astrbot_plugin_nikke.features.character.models import CubeData, FavoriteItemData, OptionSummary
from astrbot_plugin_nikke.features.character.stat_calculator import CharacterStatCalculator
from astrbot_plugin_nikke.features.profile.currency_registry import CurrencyRegistry
from astrbot_plugin_nikke.features.raid.builder import previous_season_with_stats, utc_timestamp
from astrbot_plugin_nikke.features.raid.models import PreviousSeasonSummary
from astrbot_plugin_nikke.integrations.blablalink.client import (
    CHARACTER_DETAILS,
    CHARACTERS,
    BlaBlaClient,
    _require_area_id,
)
from astrbot_plugin_nikke.integrations.character.stat_resources import CharacterStatResourceLoader
from test_card_builder import build_card, load_fixture

ACCOUNT = {"qq_id": "10001", "game_openid": "openid", "game_uid": "uid", "area_id": "81",
           "cookie": "game_token=synthetic", "binding_revision": "rev-1"}


# ------------------------------------------------------------------ 区服校验

def test_require_area_id_rejects_empty_values_readably() -> None:
    assert _require_area_id("81") == 81
    assert _require_area_id(81) == 81
    for bad in ("", None, " ", "abc", "-1"):
        with pytest.raises(ValueError, match="区服"):
            _require_area_id(bad)


# ------------------------------------------------------------------ AUD-010 缓存复用

def _transport(calls: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append(path.rsplit("/", 1)[-1])
        body = json.loads(request.content or b"{}")
        if path.endswith(CHARACTERS.rsplit("/", 1)[-1]):
            return httpx.Response(200, json={"code": 0, "data": {"characters": [
                {"name_code": code, "combat": 100 - index} for index, code in enumerate((1, 2, 3))]}})
        codes = body.get("name_codes", [])
        return httpx.Response(200, json={"code": 0, "data": {"character_details": [
            {"name_code": code, "skill1_lv": 10, "skill2_lv": 10, "ulti_skill_lv": 10} for code in codes],
            "state_effects": []}})
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_detail_requests_reuse_cached_full_roster() -> None:
    calls: list[str] = []
    client = BlaBlaClient(transport=_transport(calls))
    try:
        await client.get_roster(dict(ACCOUNT), True)
        for code in ("1", "2", "3"):
            await client.get_character_detail(dict(ACCOUNT), code)
    finally:
        await client.aclose()
    roster_endpoint = CHARACTERS.rsplit("/", 1)[-1]
    detail_endpoint = CHARACTER_DETAILS.rsplit("/", 1)[-1]
    assert calls.count(roster_endpoint) == 1  # 之前每个详情都会再拉一次 ("roster", False)
    assert calls.count(detail_endpoint) == 1 + 3


@pytest.mark.asyncio
async def test_invalidate_cache_cancels_inflight_queries() -> None:
    client = BlaBlaClient(transport=_transport([]))
    gate = asyncio.Event()

    async def slow():
        await gate.wait()
        return []

    task = asyncio.ensure_future(client._execute_cached(dict(ACCOUNT), "probe", 1, slow))
    await asyncio.sleep(0)
    client.invalidate_cache("10001")
    with pytest.raises(asyncio.CancelledError):
        await task
    await client.aclose()


def test_invalidate_account_cache_handles_already_invalid_accounts() -> None:
    client = BlaBlaClient()
    identity = client._account_identity_key(ACCOUNT)
    client._query_cache[(identity, "roster", True)] = (float("inf"), [])
    client.invalidate_account_cache({**ACCOUNT, "cookie_valid": False})
    assert not client._query_cache
    asyncio.run(client.aclose())


# ------------------------------------------------------------------ AUD-019 fail-closed

def _arcana_tables():
    from astrbot_plugin_nikke.features.character.stat_calculator import CharacterStatTables
    # 与 test_arcana_game_panel 相同的真实样本静态表片段
    return CharacterStatTables(
        level_stats={
            "statEnhance": {"grade_ratio": 200, "grade_hp": 3000, "grade_attack": 20,
                            "grade_defence": 100, "core_hp": 200, "core_attack": 200, "core_defence": 200},
            "curves": {"supporter": {"hp": [None] * 525 + [4444355], "atk": [None] * 525 + [148145],
                                      "defByWeapon": {"RL": [None] * 525 + [28905]}}},
        },
        research_table={"records": [{"id": 1001, "hp": 450, "attack": 0, "defence": 0},
                                    {"id": 1103, "hp": 750, "attack": 0, "defence": 5},
                                    {"id": 1201, "hp": 0, "attack": 25, "defence": 5}]},
        attractive_table={"records": [{"attractive_level": 30, "supporter_hp_rate": 40997,
                                         "supporter_attack_rate": 1367, "supporter_defence_rate": 273}]},
        equipment_table={"records": [{"id": 3131001, "stat": [{"stat_type": "Atk", "stat_value": 5012}]}]},
        verified=True,
    )


def _arcana_inputs(cube_tid):
    return {"class_name": "Supporter", "corporation": "ELYSION", "weapon_type": "RL", "level": 526,
            "grade": 3, "core": 2, "bond_level": 30,
            "research_levels": {"general": 240, "supporter": 119, "elysion": 116},
            "equipment": [{"tid": 0, "level": 0, "corporation_type": 0}] * 4,
            "cube": {"tid": cube_tid, "level": 3}, "favorite_item": {"tid": 0, "level": 0}}


def test_equipped_cube_without_static_record_is_not_verified() -> None:
    calculator = CharacterStatCalculator(_arcana_tables())
    baseline = calculator.calculate(_arcana_inputs(0))
    assert baseline.reason is None and baseline.hp is not None
    missing = calculator.calculate(_arcana_inputs(1234))
    # 之前按 0 计算并仍标记 calculated_verified；现在 fail-closed
    assert missing.hp is None and missing.reason and "魔方 1234" in missing.reason


def test_missing_overload_registry_does_not_crash_unknown_option_inventory() -> None:
    observed: list = []
    fixture = load_fixture()
    builder = CharacterCardBuilder(
        overload_tier_registry=None,
        unknown_ol_inventory=SimpleNamespace(observe=lambda *args: observed.append(args)),
    )
    builder.build(
        account={"nickname": "测试指挥官"}, directory=fixture["directory"],
        payload={"roster_item": fixture["roster_item"], "detail": fixture["character_details"][0],
                 "state_effects": fixture["state_effects"]},
        fetched_at="2026-09-05 05:30", plugin_version="test",
    )
    assert build_card() is not None


def test_text_fallback_formats_percent_and_unknown_items() -> None:
    card = build_card()
    card.option_totals = [OptionSummary(display_name="攻击力增加", value=0.1181, unit="percent")]
    card.cube = CubeData(tid=1234, level=3)
    card.favorite_item = FavoriteItemData(tid=None, level=None)
    text = CharacterCommandHandler._format_character_card(card)
    assert "攻击力增加：11.81%" in text
    assert "percent" not in text
    assert "魔方：魔方 1234" in text
    assert "收藏品：未识别的收藏品" in text


# ------------------------------------------------------------------ 静态表缓存

def test_stat_resource_cache_expires_and_falls_back_to_stale(tmp_path) -> None:
    from astrbot_plugin_nikke.integrations.character.stat_resources import StaticResourceSpec
    spec = StaticResourceSpec("probe", "https://example.invalid/probe.json", "probe.json")
    fetched: list[str] = []
    loader = CharacterStatResourceLoader(tmp_path, fetcher=lambda url: fetched.append(url) or b'{"v": 1}')
    assert loader._load_spec(spec) == {"v": 1}
    envelope = json.loads((tmp_path / "probe.json").read_text(encoding="utf-8"))
    envelope["fetched_at"] = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    (tmp_path / "probe.json").write_text(json.dumps(envelope), encoding="utf-8")

    def failing(url):
        raise OSError("offline")

    stale = CharacterStatResourceLoader(tmp_path, fetcher=failing)
    assert stale._load_spec(spec) == {"v": 1}  # 过期且刷新失败时继续使用旧缓存
    fresh = CharacterStatResourceLoader(tmp_path, fetcher=lambda url: b'{"v": 2}')
    assert fresh._load_spec(spec) == {"v": 2}  # 过期且可刷新时更新


# ------------------------------------------------------------------ 突袭 / 战役 / 资料

def test_raid_naive_times_are_parsed_as_utc() -> None:
    assert utc_timestamp("2026-09-23 05:00:00") == datetime(2026, 9, 23, 5, tzinfo=timezone.utc).timestamp()
    assert utc_timestamp("2026-09-23T13:00:00+08:00") == datetime(2026, 9, 23, 5, tzinfo=timezone.utc).timestamp()


def test_previous_season_stats_backfill() -> None:
    previous = PreviousSeasonSummary("101", 101, "2026-09-01", "2026-09-10")
    filled = previous_season_with_stats(previous, [{"total_damage": 5}, {"damage": 7}, "bad"])
    assert (filled.total_attacks, filled.total_damage) == (2, 12)
    assert previous_season_with_stats(previous, None) is previous


def test_stage_id_seen_odd_times_stays_ambiguous() -> None:
    resolver = CampaignStageResolver({
        "NORMAL": {"1": {"1-1": 900, "1-2": 900, "1-3": 900, "1-4": 901}},
    })
    assert 900 not in resolver.by_id  # 第三次出现不得重新登记
    assert resolver.by_id[901].name == "1-4"


def test_currency_registry_errors_are_bounded() -> None:
    registry = CurrencyRegistry()
    for _ in range(500):
        registry.parse(["not-an-object"])
    assert len(registry.errors) <= CurrencyRegistry.MAX_ERRORS


def test_probe_compare_detects_truncated_batch() -> None:
    import importlib.util
    path = Path(__file__).resolve().parents[1] / "scripts" / "operations" / "verify_character_details_batch.py"
    spec = importlib.util.spec_from_file_location("verify_batch_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    single = {"data": {"character_details": [{"name_code": 1, "head_equip_tid": 5}], "state_effects": [{"id": 9}]}}
    assert module.compare(single, {"1": single})["all_consistent"] is True
    truncated = {"data": {"character_details": [{"name_code": 1, "head_equip_tid": None}], "state_effects": []}}
    report = module.compare(truncated, {"1": single})
    assert report["all_consistent"] is False
    assert report["equipment_mismatch"][0]["fields"] == ["head_equip_tid"]
    assert report["state_effects_missing"] == [{"name_code": "1", "count": 1}]

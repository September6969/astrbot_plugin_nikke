"""AUD-015：大模板均衡搜索、同阶段替补排序与私聊珍藏可达性（含来源标注）。"""

import json
import time
from collections import defaultdict
from itertools import product
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot_plugin_nikke.application.commands.arena import ArenaCommandHandler
from astrbot_plugin_nikke.application.commands.contracts import CommandContext
from astrbot_plugin_nikke.features.arena.analyzer import SUBSTITUTE_LIMIT, balanced_combinations
from astrbot_plugin_nikke.features.arena.models import ArenaRosterSnapshot
from astrbot_plugin_nikke.features.arena.roster import ArenaRosterProvider
from astrbot_plugin_nikke.features.arena.statistics import SnapshotStatisticsProvider
from astrbot_plugin_nikke.integrations.blablalink.client import BlaBlaClient
from test_arena_core import arena

ENEMY = "红莲/豺狼/布兰儿/桑迪/特蕾娜"
TREASURE_TEMPLATES = ("moran-system-atk", "moran-system-def", "helm-treasure-carry", "cat-team",
                      "privaty-stun", "jackal-bay-share", "soda-laplace-stun")


ROOT = Path(__file__).resolve().parents[1]


def template(arena, template_id):
    return next(item for item in arena.analyzer.templates if item["id"] == template_id)


def spy_evaluations(arena):
    seen = defaultdict(list)
    original = arena.analyzer._evaluate

    def record(item, keys, context):
        seen[item["id"]].append(keys)
        return original(item, keys, context)

    arena.analyzer._evaluate = record
    return seen


def base_roster(arena):
    """私聊基础名单只含主表 name_code 映射的本体键。"""
    return frozenset(arena.directory.by_code.values())


def provider(arena, keys, details=None):
    calls = []

    async def get_roster(_account, include_details=True):
        calls.append(include_details)
        return [{"name_code": arena.directory.characters[key].name_code} for key in sorted(keys)]

    gateway = SimpleNamespace(get_roster=get_roster)
    if details is not None:
        gateway.cached_character_details = lambda _account: details
    accounts = SimpleNamespace(get_account=lambda _actor: {"cookie_valid": True})
    return ArenaRosterProvider(accounts, gateway, arena.directory), calls


def exclusive_details(arena, variants):
    tid_of = {variant: tid for tid, variant in arena.directory.treasure_items.items()}
    return {arena.directory.characters[arena.directory.characters[variant].base_key].name_code:
            {"favorite_item_tid": int(tid_of[variant]), "favorite_item_lv": 1} for variant in variants}


# ---- 搜索覆盖率 ----

def test_balanced_enumeration_rotates_every_slot_instead_of_tail_only(arena):
    slots = template(arena, "nayuta-carry")["slots"]
    budget = 146
    first = list(balanced_combinations(slots, arena.analyzer._base))[:budget]
    coverage = [len({keys[index] for keys in first}) for index in range(5)]
    # 旧的 product() 截断在同一预算下只轮换尾槽：P2 仅 1 个选项。
    legacy = [keys for keys in product(*slots)
              if len({arena.analyzer._base(key) for key in keys}) == 5][:budget]
    assert len({keys[1] for keys in legacy}) == 1
    assert all(coverage[index] >= min(len(slots[index]), 6) for index in range(5))
    assert first == list(balanced_combinations(slots, arena.analyzer._base))[:budget]
    offsets = [sum(slot.index(key) for slot, key in zip(slots, keys)) for keys in first]
    assert offsets == sorted(offsets)
    assert all(len({arena.analyzer._base(key) for key in keys}) == 5 for keys in first)


def test_balanced_enumeration_is_complete_and_never_repeats(arena):
    slots = [("scarlet",), ("jackal", "noah", "scarlet"), ("blanc", "centi"),
             ("centi", "trina", "biscuit"), ("trina", "rapunzel")]
    expected = {keys for keys in product(*slots) if len(set(keys)) == 5}
    produced = list(balanced_combinations(slots, arena.analyzer._base))
    assert len(produced) == len(set(produced))
    assert set(produced) == expected


def test_unused_budget_flows_to_large_templates(arena):
    # 旧实现在私聊全名单下 searched=956<2048 即因单模板平均额度 102 截断。
    seen = spy_evaluations(arena)
    enemy = arena.directory.parse_team(ENEMY)
    snapshot = ArenaRosterSnapshot(base_roster(arena), "available", 0, "", ())
    result = arena.analyzer.analyze(enemy, snapshot)
    assert result.searched == 2048
    assert any("均衡抽样" in warning for warning in result.warnings)
    nayuta = seen["nayuta-carry"]
    assert len(nayuta) > 2048 // len(arena.analyzer.templates)
    slots = template(arena, "nayuta-carry")["slots"]
    for index in range(1, 5):
        owned = [key for key in slots[index] if key in snapshot.keys]
        assert len({keys[index] for keys in nayuta}) >= min(len(owned), 5)


def test_sandbox_search_uses_full_budget_and_stays_deterministic_and_fast(arena):
    seen = spy_evaluations(arena)
    enemy = arena.directory.parse_team(ENEMY)
    started = time.perf_counter()
    first = arena.analyzer.analyze(enemy)
    assert time.perf_counter() - started < 1.5
    assert first.searched == 2048
    assert first == arena.analyzer.analyze(enemy)
    # 每个可行模板都分到额度，小模板穷举后剩余额度均衡流向大模板。
    assert set(seen) == {item["id"] for item in arena.analyzer.templates}
    sizes = {item["id"]: len(set(seen[item["id"]])) for item in arena.analyzer.templates}
    assert sizes["soda-laplace-stun"] == 4
    assert min(sizes[name] for name in ("nayuta-carry", "moran-system-atk", "noah-biscuit-stall")) > 120


def test_owned_large_template_recommendations_vary_front_slots(arena):
    nayuta = template(arena, "nayuta-carry")
    owned = frozenset(arena.analyzer._base(key) for slot in nayuta["slots"] for key in slot)
    arena.analyzer.templates = [nayuta]
    snapshot = ArenaRosterSnapshot(owned, "available", 0, "", ())
    result = arena.analyzer.analyze(arena.directory.parse_team(ENEMY), snapshot, limit=300,
                                    candidate_limit=60)
    assert result.recommendations
    assert len({item.team.keys[1] for item in result.recommendations}) >= 3
    assert len({item.team.keys[2] for item in result.recommendations}) >= 3


# ---- 同阶段替补排序 ----

def substitute_fixture(arena):
    enemy = arena.directory.parse_team(ENEMY)
    stage = arena.directory.characters["noah"].burst
    pool = sorted(key for key, char in arena.directory.characters.items()
                  if char.burst == stage and char.base_key == key and key not in enemy.keys
                  and key != "noah")[:SUBSTITUTE_LIMIT + 2]
    boosted = pool[-1]
    fixture = {"id": "fixture", "required": [enemy.keys[0]], "archetype": "fixture", "reason": "测试模板",
               "slots": [(enemy.keys[0],), (enemy.keys[1],), (enemy.keys[2],), ("noah",), (enemy.keys[4],)]}
    # 不可行模板也计入出现频次：boosted 出现 3 次，pool[-2] 出现 1 次，其余为 0。
    boosters = [{"id": f"boost-{index}", "required": ["noah"], "archetype": "x", "reason": "x",
                 "slots": [(boosted,), (pool[-2],) if index == 0 else ("scarlet",), (), (), ()]}
                for index in range(3)]
    arena.analyzer.templates = [fixture, *boosters]
    # 零频次候选按充能效率排序，刻意与字母顺序相反。
    for rank, key in enumerate(pool[:-2]):
        arena.analyzer.parameters[key] = {2.0: 10.0 + rank, 3.0: 20.0 + rank}
    return enemy, pool, boosted


def test_substitutes_rank_by_template_frequency_then_charge_not_alphabet(arena):
    enemy, pool, boosted = substitute_fixture(arena)
    allowed = set(enemy.keys) - {enemy.keys[3]} | set(pool)
    ranked = arena.analyzer.substitutes(("noah",), allowed, set(enemy.keys))
    expected = (boosted, pool[-2], *reversed(pool[:-2]))[:SUBSTITUTE_LIMIT]
    assert ranked == expected
    # 旧实现按字母序盲选 pool[:5]，会漏掉模板高频的 boosted。
    assert pool[0] not in ranked and pool[1] not in ranked


def test_substitute_recommendations_follow_ranked_order_and_stay_labeled(arena):
    enemy, pool, boosted = substitute_fixture(arena)
    owned = frozenset(set(enemy.keys) - {enemy.keys[3]} | set(pool))
    result = arena.analyzer.analyze(enemy, ArenaRosterSnapshot(owned, "available", 0, "", ()), limit=300)
    used = {item.team.keys[3] for item in result.recommendations}
    assert used <= set(arena.analyzer.substitutes(("noah",), set(owned), set(enemy.keys)))
    assert pool[0] not in used and boosted in used
    assert all("替补尚未验证" in item.warnings[0] and "P4" in item.warnings[0]
               for item in result.recommendations)
    assert result == arena.analyzer.analyze(enemy, ArenaRosterSnapshot(owned, "available", 0, "", ()),
                                            limit=300)


# ---- 珍藏可达性与来源标注 ----

def test_treasure_registry_maps_every_variant_to_its_exclusive_item(arena):
    directory = arena.directory
    assert len(directory.treasure_items) == len(directory.variant_of) == 21
    assert set(directory.treasure_items.values()) == set(directory.variant_of.values())
    registry = json.loads((ROOT / "assets/data/favorite_items.json").read_text(encoding="utf-8"))
    for tid, variant in directory.treasure_items.items():
        base = directory.characters[directory.characters[variant].base_key]
        assert registry[tid] == f"si_favoriteitem_c{int(base.resource_id):03d}_00"
    # 通用收藏品（娃娃）不会被当作专属珍藏。
    assert not {tid for tid in directory.treasure_items if tid.startswith("10")}


@pytest.mark.asyncio
async def test_basic_roster_never_fabricates_treasure_and_labels_inference(arena):
    roster, calls = provider(arena, base_roster(arena))
    snapshot = await roster.owned("a")
    assert calls == [False]
    assert not snapshot.keys & set(arena.directory.variant_of.values())
    assert "helm_treasure" in snapshot.favorite_unconfirmed and not snapshot.favorites
    enemy = arena.directory.parse_team(ENEMY)
    templates = list(arena.analyzer.templates)
    for template_id in TREASURE_TEMPLATES:
        arena.analyzer.templates = [next(item for item in templates if item["id"] == template_id)]
        assert not arena.analyzer.analyze(enemy, snapshot, limit=300).recommendations, template_id
    arena.analyzer.templates = templates
    result = arena.analyzer.analyze(enemy, snapshot)
    assert any(warning.startswith("基础名单推测") and "手动标记" in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_cached_official_detail_makes_all_treasure_templates_reachable(arena):
    variants = tuple(arena.directory.variant_of.values())
    roster, calls = provider(arena, base_roster(arena), exclusive_details(arena, variants))
    snapshot = await roster.owned("a")
    assert calls == [False]  # 仍只读一次基础名单，详情只来自既有缓存
    assert set(variants) <= snapshot.keys
    assert dict(snapshot.favorites) == {key: "official_detail" for key in variants}
    assert not snapshot.favorite_unconfirmed
    enemy = arena.directory.parse_team(ENEMY)
    templates = list(arena.analyzer.templates)
    for template_id in TREASURE_TEMPLATES:
        arena.analyzer.templates = [next(item for item in templates if item["id"] == template_id)]
        result = arena.analyzer.analyze(enemy, snapshot, limit=300)
        assert result.recommendations, template_id
        item = result.recommendations[0]
        labels = [evidence.text for evidence in item.evidence if evidence.text.startswith("珍藏来源")]
        assert labels and all("官方详情确认" in text for text in labels)
        assert not any("手动标记" in warning for warning in item.warnings)
    arena.analyzer.templates = templates
    assert any("官方详情确认 21 名" in warning for warning in arena.analyzer.analyze(enemy, snapshot).warnings)


@pytest.mark.asyncio
async def test_other_favorite_item_is_absent_and_blocks_manual_mark(arena):
    helm = arena.directory.characters["helm"].name_code
    roster, _ = provider(arena, {"helm", "moran"}, {helm: {"favorite_item_tid": 100602, "favorite_item_lv": 15}})
    arena.roster = roster
    snapshot = await arena.read_marked_roster("a", ("helm_treasure", "moran_treasure", "privaty_treasure"))
    assert "helm_treasure" not in snapshot.keys and "helm_treasure" in snapshot.favorite_absent
    assert dict(snapshot.favorites) == {"moran_treasure": "manual"}
    assert any("官方详情显示未装备" in note and "海伦" in note for note in snapshot.notes)
    assert any("本体不在已绑定角色名单内" in note and "普丽瓦蒂" in note for note in snapshot.notes)


@pytest.mark.asyncio
async def test_failing_detail_cache_falls_back_to_inference_without_blocking(arena):
    roster, _ = provider(arena, {"helm"})

    def broken(_account):
        raise RuntimeError("cache-broken")

    roster.gateway.cached_character_details = broken
    snapshot = await roster.owned("a")
    assert snapshot.status == "available" and snapshot.favorite_unconfirmed == ("helm_treasure",)


@pytest.mark.parametrize(("text", "marks"), [
    (ENEMY + " 珍藏:海伦,牡丹", ("helm_treasure", "moran_treasure")),
    (ENEMY + " 珍藏：海伦、海伦 珍藏", ("helm_treasure",)),
    (ENEMY + "\n珍藏 普丽瓦蒂", ("privaty_treasure",)),
    ("红莲/豺狼/布兰儿/特蕾娜/桑迪 珍藏", ()),
    ("红莲/豺狼/布兰儿/特蕾娜/桑迪 珍藏 珍藏:Helm", ("helm_treasure",)),
])
def test_favorite_mark_syntax_never_eats_treasure_names(arena, text, marks):
    team_text, parsed = arena.directory.split_favorite_marks(text)
    assert parsed == marks
    assert len(arena.directory.parse_team(team_text).characters) == 5


def test_favorite_mark_rejects_characters_without_treasure(arena):
    with pytest.raises(ValueError, match="没有已收录的珍藏形态"):
        arena.directory.split_favorite_marks(ENEMY + " 珍藏:红莲")


@pytest.mark.asyncio
async def test_private_manual_mark_reaches_template_and_is_labeled_everywhere(arena):
    helm = template(arena, "helm-treasure-carry")
    owned = {arena.analyzer._base(key) for slot in helm["slots"] for key in slot}
    roster, _ = provider(arena, owned)
    arena.roster = roster
    arena.analyzer.templates = [helm]
    handler = ArenaCommandHandler(arena, enabled=True)

    async def solve(value):
        reply = await handler.handle(CommandContext(actor_id="a", is_private_chat=True,
                                                    parameters={"action": "解队", "value": value}))
        return reply.messages[0].text

    unmarked = await solve(ENEMY)
    assert "建议 1" not in unmarked and "基础名单推测" in unmarked
    marked = await solve(ENEMY + " 珍藏:海伦")
    assert "建议 1 海伦 珍藏/" in marked
    assert "珍藏来源 手动标记：海伦 珍藏" in marked
    assert "珍藏形态 手动标记 1 名" in marked
    result = await arena.analyze(ENEMY + " 珍藏:海伦", actor_id="a", owned=True)
    assert all(any("手动标记" in warning for warning in item.warnings) for item in result.recommendations)


@pytest.mark.asyncio
async def test_group_sandbox_ignores_marks_with_explicit_note(arena):
    handler = ArenaCommandHandler(arena, enabled=True)
    reply = await handler.handle(CommandContext(actor_id="a", parameters={
        "action": "解队", "value": ENEMY + " 珍藏:海伦"}))
    assert "全角色沙盒" in reply.messages[0].text and "珍藏标记未使用" in reply.messages[0].text


@pytest.mark.asyncio
async def test_three_team_import_accepts_mark_line(arena):
    owned = base_roster(arena)
    roster, _ = provider(arena, owned)
    arena.roster = roster
    handler = ArenaCommandHandler(arena, enabled=True)
    value = "\n".join((ENEMY, "诺雅/饼干/爱丽丝/丽塔/普丽瓦蒂", "阿妮斯/拉毗/尼恩/露菲/哈兰", "珍藏:海伦,牡丹"))
    reply = await handler.handle(CommandContext(actor_id="a", is_private_chat=True,
                                                parameters={"action": "三队导入", "value": value}))
    assert "第 3 场对位" in reply.messages[0].text
    assert "珍藏形态 手动标记 2 名" in reply.messages[0].text


@pytest.mark.asyncio
async def test_my_command_separates_favorite_provenance(arena):
    details = exclusive_details(arena, ("helm_treasure",))
    roster, _ = provider(arena, {"helm", "moran", "scarlet"}, details)
    arena.roster = roster
    handler = ArenaCommandHandler(arena, enabled=True)
    reply = await handler.handle(CommandContext(actor_id="a", is_private_chat=True,
                                                parameters={"action": "我的"}))
    text = reply.messages[0].text
    assert "已映射 3 人" in text
    assert "珍藏形态 官方详情确认 1 名｜基础名单推测 1 名（未计入）" in text
    assert "珍藏:角色名" in text


@pytest.mark.asyncio
async def test_client_exposes_only_cached_details_of_the_same_binding():
    client = BlaBlaClient()
    detail = {"name_code": 5066, "favorite_item_tid": 200701, "favorite_item_lv": 2}

    async def post(path, _cookie, _payload):
        if "Details" in path:
            return {"data": {"character_details": [detail], "state_effects": []}}
        return {"data": {"characters": [{"name_code": 5066}]}}

    client._post = AsyncMock(side_effect=post)
    account = {"qq_id": "1", "area_id": "1", "game_openid": "openid-a", "cookie": "game_token=a"}
    other = {**account, "qq_id": "2", "game_openid": "openid-b", "cookie": "game_token=b"}
    assert client.cached_character_details(account) == {}
    await client.get_character_detail(account, "5066")
    requests = client._post.await_count
    cached = client.cached_character_details(account)
    assert cached == {"5066": detail}
    assert client._post.await_count == requests
    cached["5066"]["favorite_item_tid"] = 0
    assert client.cached_character_details(account)["5066"]["favorite_item_tid"] == 200701
    assert client.cached_character_details(other) == {}
    for key, (_expiry, data) in list(client._query_cache.items()):
        client._query_cache[key] = (0.0, data)
    assert client.cached_character_details(account) == {}
    await client.aclose()


def test_similar_statistics_state_pooled_combination_scope(tmp_path):
    attacker = ("a", "b", "c", "d", "e")
    defender = ("f", "g", "h", "i", "j")
    rows = [
        {"mine": ("a", "b", "c", "d", "x"), "enemy": defender, "wins": 1, "losses": 2},
        {"mine": attacker, "enemy": ("f", "g", "h", "i", "x"), "wins": 2, "losses": 0},
    ]
    payload = {
        "schema_version": 2, "source": "https://nikkeari.cc", "fetched_at": "2020-01-01T00:00:00+00:00",
        "matchup_direction": "attacker_vs_defender", "game_patch": "test-patch",
        "server": "JP", "seasons": ["fixture"], "sample_size": 5, "license": "synthetic-test",
        "mapping_coverage": 1, "records": rows,
    }
    path = tmp_path / "history.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    mine, enemy = SimpleNamespace(keys=attacker), SimpleNamespace(keys=defender)
    text = SnapshotStatisticsProvider(path).matchup(mine, enemy).text
    assert "4/5 相似" in text and "合并 2 组差异位角色不同的攻守组合" in text
    assert "不代表本阵容或本对手的实测胜率" in text
    payload["records"] = [{"mine": list(attacker), "enemy": list(defender), "wins": 3, "losses": 2}]
    path.write_text(json.dumps(payload), encoding="utf-8")
    exact = SnapshotStatisticsProvider(path).matchup(mine, enemy).text
    assert "5/5 同站位" in exact and "合并" not in exact

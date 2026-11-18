"""历史快照口径、置信区间与失效回退。"""

import json
from dataclasses import replace
from types import SimpleNamespace

from astrbot_plugin_nikke.features.arena.statistics import SnapshotStatisticsProvider, wilson_interval
from astrbot_plugin_nikke.scripts.arena.sync_history import build_snapshot
from test_arena_core import arena


def test_wilson_uncertainty_for_small_samples():
    assert wilson_interval(0, 0) == (0, 1)
    lower, upper = wilson_interval(1, 0)
    assert 0 < lower < 0.5
    assert 0.99 < upper <= 1
    wide = wilson_interval(2, 2)
    narrow = wilson_interval(200, 200)
    assert wide[1] - wide[0] > narrow[1] - narrow[0]


def test_exact_order_and_stale_source_are_preserved(tmp_path, arena):
    team = arena.directory.parse_team("红莲/豺狼/布兰儿/桑迪/特蕾娜")
    payload = {
        "schema_version": 2, "source": "https://nikkeari.cc", "fetched_at": "2020-01-01T00:00:00+00:00",
        "matchup_direction": "attacker_vs_defender",
        "game_patch": "unknown", "server": "GLOBAL", "seasons": ["fixture"], "sample_size": 4,
        "license": "synthetic-test", "mapping_coverage": 1,
        "records": [{"mine": list(team.keys), "enemy": list(team.keys), "wins": 3, "losses": 1}],
    }
    path = tmp_path / "history.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    stats = SnapshotStatisticsProvider(path)
    assert stats.status == "stale"
    evidence = stats.matchup(team, team)
    assert "3 胜 1 负" in evidence.text
    assert "补丁未知" in evidence.text and "30 天" in evidence.text
    assert evidence.provenance.version == "unknown"
    swapped = replace(team, characters=tuple(reversed(team.characters)))
    assert stats.matchup(swapped, team) is None
    payload["records"].append(payload["records"][0])
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert SnapshotStatisticsProvider(path).status == "unavailable"


def test_missing_snapshot_keeps_core_available(tmp_path, arena):
    provider = SnapshotStatisticsProvider(tmp_path / "missing.json")
    assert provider.status == "unavailable"
    team = arena.directory.parse_team("红莲/豺狼/布兰儿/桑迪/特蕾娜")
    arena.analyzer.statistics = provider
    assert arena.analyzer.analyze(team).recommendations


def test_similarity_uses_both_sides_and_only_best_tier(tmp_path):
    attacker = ("a", "b", "c", "d", "e")
    defender = ("f", "g", "h", "i", "j")
    rows = [
        {"mine": attacker, "enemy": ("f", "g", "h", "x", "y"), "wins": 14, "losses": 1},
        {"mine": ("a", "b", "c", "d", "x"), "enemy": defender, "wins": 1, "losses": 2},
        {"mine": attacker, "enemy": ("f", "g", "h", "i", "x"), "wins": 2, "losses": 0},
        {"mine": ("a", "b", "x", "y", "z"), "enemy": defender, "wins": 100, "losses": 0},
    ]
    payload = {
        "schema_version": 2, "source": "https://nikkeari.cc", "fetched_at": "2020-01-01T00:00:00+00:00",
        "matchup_direction": "attacker_vs_defender", "game_patch": "test-patch",
        "server": "JP", "seasons": ["fixture"], "sample_size": 120, "license": "synthetic-test",
        "mapping_coverage": 1, "records": rows,
    }
    path = tmp_path / "history.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    mine = SimpleNamespace(keys=attacker)
    enemy = SimpleNamespace(keys=defender)
    evidence = SnapshotStatisticsProvider(path).matchup(mine, enemy)
    assert "4/5 相似" in evidence.text
    assert "我方 P5、对方 P5" in evidence.text
    assert "3 胜 2 负，样本 5" in evidence.text
    assert SnapshotStatisticsProvider(path).matchup(enemy, mine) is None
    payload["records"] = [rows[0]]
    payload["sample_size"] = 15
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert "3/5 相似" in SnapshotStatisticsProvider(path).matchup(mine, enemy).text


def test_sync_aggregation_keeps_complete_denominators_and_removes_players():
    keys = ["a", "b", "c", "d", "e"]
    other = ["f", "g", "h", "i", "j"]
    rules = {"names": {key: {"ja": key} for key in keys + other}, "parameters": {}}
    characters = [{"id": index, "name": key} for index, key in enumerate(keys + other)]
    tournament = {"id": 1, "play_server": "JP", "season": "test"}
    rounds = []
    for won in (True, True, False):
        rounds.append({"attacker_team": list(range(5)), "defender_team": list(range(5, 10)),
                       "attacker_player_id": "private-a", "defender_player_id": "private-b",
                       "winner_player_id": "private-a" if won else "private-b"})
    snapshot = build_snapshot(rules, characters, tournament, rounds, "test-patch")
    assert snapshot["sample_size"] == 3
    assert len(snapshot["records"]) == 1
    assert snapshot["records"][0]["wins"] == 2 and snapshot["records"][0]["losses"] == 1
    assert "private-a" not in json.dumps(snapshot)
    mirror = dict(rounds[0], defender_team=rounds[0]["attacker_team"])
    snapshot = build_snapshot(rules, characters, tournament, [mirror], "test-patch")
    assert snapshot["sample_size"] == snapshot["records"][0]["wins"] == 1
    assert snapshot["records"][0]["losses"] == 0

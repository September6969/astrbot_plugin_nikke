import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from astrbot_plugin_nikke.character_stat_resources import (
    BASE_RESOURCE_SPECS,
    CharacterStatResourceLoader,
    map_research_levels,
)
from astrbot_plugin_nikke.asset_manager import AssetManager


def _level_stats():
    curves = {}
    for class_name in ("attacker", "defender", "supporter"):
        curves[class_name] = {
            "hp": list(range(1, 526)),
            "atk": list(range(1, 526)),
            "defByWeapon": {
                weapon: list(range(1, 526)) for weapon in ("RL", "AR", "SMG", "SG", "SR", "MG")
            },
        }
    return {
        "schemaVersion": 2,
        "updatedAt": "2026-09-09T00:00:00Z",
        "statEnhance": {
            "grade_ratio": 200,
            "grade_hp": 3000,
            "grade_attack": 20,
            "grade_defence": 100,
            "core_hp": 200,
            "core_attack": 200,
            "core_defence": 200,
        },
        "curves": curves,
    }


def _base_payloads():
    return {
        "level_stats": _level_stats(),
        "cube_catalog": {"cubes": [{"cube_id": 1000301}]},
        "research_table": {"version": "0.0.1", "records": [
            {"id": 1001, "hp": 1, "attack": 1, "defence": 1},
            {"id": 1101, "hp": 1, "attack": 1, "defence": 1},
            {"id": 1102, "hp": 1, "attack": 1, "defence": 1},
            {"id": 1103, "hp": 1, "attack": 1, "defence": 1},
            {"id": 1201, "hp": 1, "attack": 1, "defence": 1},
            {"id": 1202, "hp": 1, "attack": 1, "defence": 1},
            {"id": 1203, "hp": 1, "attack": 1, "defence": 1},
            {"id": 1204, "hp": 1, "attack": 1, "defence": 1},
            {"id": 1205, "hp": 1, "attack": 1, "defence": 1},
        ]},
        "attractive_table": {"version": "0.0.1", "records": [{"id": 1, "attractive_level": 1}]},
        "equipment_table": {"version": "0.0.1", "records": [{"id": 1, "stat": []}]},
    }


class CharacterStatResourceTests(unittest.TestCase):
    def test_research_rejects_non_integer_values_without_guessing(self):
        for value in (True, False, 1.5, 10.0, " 10", "+10", "１", float("nan"), None):
            with self.subTest(value=value):
                self.assertIsNone(map_research_levels([{"tid": 1001, "lv": value}])["general"])
                self.assertIsNone(map_research_levels([{"tid": value, "lv": 10}])["general"])

    def test_research_mapping_is_explicit_and_unknown_rows_are_ignored(self):
        result = map_research_levels([
            {"tid": 1001, "lv": 10},
            {"tid": "1201", "lv": 7},
            {"tid": 9999, "lv": 99},
            {"tid": 1101, "lv": "bad"},
        ])
        self.assertEqual(result["general"], 10)
        self.assertEqual(result["elysion"], 7)
        self.assertIsNone(result["attacker"])

    def test_loader_fetches_base_and_dynamic_ids_once_then_reads_cache(self):
        payloads = _base_payloads()
        payloads["cube_1000301"] = {"id": 1000301, "hp": [1], "atk": [2], "def": [3]}
        payloads["favorite_100602"] = {"id": 100602, "hp": [4], "atk": [5], "def": [6]}
        calls = []
        by_url = {
            BASE_RESOURCE_SPECS[0].url: payloads["level_stats"],
            BASE_RESOURCE_SPECS[1].url: payloads["cube_catalog"],
            BASE_RESOURCE_SPECS[2].url: payloads["research_table"],
            BASE_RESOURCE_SPECS[3].url: payloads["attractive_table"],
            BASE_RESOURCE_SPECS[4].url: payloads["equipment_table"],
            AssetManager.game_resource_url("equip/zh-tw/cube_1000301.json"): payloads["cube_1000301"],
            AssetManager.game_resource_url("equip/zh-tw/favorite_100602.json"): payloads["favorite_100602"],
        }

        def fetcher(url):
            calls.append(url)
            return json.dumps(by_url[url]).encode()

        with tempfile.TemporaryDirectory() as directory:
            loader = CharacterStatResourceLoader(directory, fetcher=fetcher)
            self.assertTrue(loader.load_base().verified)
            loader.ensure_ids(cube_ids=[1000301, 1000301], favorite_ids=[100602])
            self.assertEqual(calls.count(AssetManager.game_resource_url("equip/zh-tw/cube_1000301.json")), 1)
            self.assertEqual(calls.count(AssetManager.game_resource_url("equip/zh-tw/favorite_100602.json")), 1)
            self.assertEqual(loader.tables().cube_records["1000301"]["atk"], [2])
            self.assertEqual(
                loader.source_report()["level_stats"]["sha256"],
                hashlib.sha256(json.dumps(by_url[BASE_RESOURCE_SPECS[0].url]).encode()).hexdigest(),
            )

            def fail_fetcher(url):
                raise AssertionError(f"不应重新下载缓存: {url}")

            cached = CharacterStatResourceLoader(directory, fetcher=fail_fetcher)
            self.assertTrue(cached.load_base().verified)
            cached.ensure_ids(cube_ids=[1000301], favorite_ids=[100602])


if __name__ == "__main__":
    unittest.main()

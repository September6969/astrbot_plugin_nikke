# SPDX-License-Identifier: GPL-3.0-or-later

import json
import unittest
from pathlib import Path

from astrbot_plugin_nikke.character_master_resolver import CharacterMasterResolver, ResolvedCharacter


class CharacterMasterTests(unittest.TestCase):
    def setUp(self):
        self.resolver = CharacterMasterResolver()
        self.master_file = Path(__file__).resolve().parents[1] / "assets" / "character_master.json"

    def test_master_json_integrity(self):
        self.assertTrue(self.master_file.is_file())
        with open(self.master_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data.get("schema_version"), 1)
        self.assertEqual(data.get("source"), "blablalink_official_directory")
        characters = data.get("characters", [])
        self.assertEqual(len(characters), 200)

        prefixes = set()
        resource_ids = set()
        for c in characters:
            self.assertIn("id", c)
            self.assertIn("battle_tid_prefix", c)
            self.assertIn("resource_id", c)
            self.assertIn("name_code", c)
            self.assertIn("character_key", c)
            self.assertIn("spine_asset_id", c)
            self.assertIn("name_cn", c)
            self.assertIn("name_en", c)

            prefix = c["battle_tid_prefix"]
            self.assertNotIn(prefix, prefixes, f"Duplicate battle_tid_prefix: {prefix}")
            prefixes.add(prefix)

            res_id = c["resource_id"]
            self.assertNotIn(res_id, resource_ids, f"Duplicate resource_id: {res_id}")
            resource_ids.add(res_id)

            self.assertTrue(c["name_cn"], f"Missing name_cn for {c}")
            self.assertTrue(c["name_en"], f"Missing name_en for {c}")
            self.assertTrue(c["spine_asset_id"].startswith("c"), f"Invalid spine_asset_id for {c}")

    def test_resolver_total_count(self):
        self.assertEqual(self.resolver.total_count, 200)

    def test_resolve_five_regression_battle_tids(self):
        cases = [
            (433004, "皇冠", "Crown", "330", "c330", 5065),
            (301704, "阿妮斯：超级巨星", "Anis: Star", "17", "c017", 5169),
            (447105, "白雪公主：重型武装", "Snow White: Heavy Arms", "471", "c471", 5161),
            (423401, "桃乐丝：机缘巧遇", "Dorothy: Serendipity", "234", "c234", 5145),
            (235207, "海伦", "Helm", "352", "c352", 5066),
        ]
        for tid, exp_cn, exp_en, exp_res, exp_spine, exp_nc in cases:
            char = self.resolver.resolve_battle_tid(tid)
            self.assertIsNotNone(char, f"Failed to resolve tid {tid}")
            self.assertEqual(char.name_cn, exp_cn)
            self.assertEqual(char.name_en, exp_en)
            self.assertEqual(str(char.resource_id), exp_res)
            self.assertEqual(char.spine_asset_id, exp_spine)
            self.assertEqual(char.name_code, exp_nc)

            # Member identity method
            cn, en, res_id, spine_id, rchar = self.resolver.resolve_member_identity(tid)
            self.assertEqual(cn, exp_cn)
            self.assertEqual(en, exp_en)
            self.assertEqual(res_id, exp_res)
            self.assertEqual(spine_id, exp_spine)
            self.assertIs(rchar, char)

    def test_resolve_core_break_levels(self):
        # 301700 through 301710 all resolve to Anis: Star
        for tid in (301700, 301701, 301702, 301703, 301704, 301705, 301710):
            char = self.resolver.resolve_battle_tid(tid)
            self.assertIsNotNone(char)
            self.assertEqual(char.name_cn, "阿妮斯：超级巨星")
            self.assertEqual(char.resource_id, 17)

    def test_resolve_by_identifier(self):
        # By key
        crown = self.resolver.resolve_by_identifier("crown")
        self.assertIsNotNone(crown)
        self.assertEqual(crown.name_cn, "皇冠")

        # By spine ID
        anis = self.resolver.resolve_by_identifier("c017")
        self.assertIsNotNone(anis)
        self.assertEqual(anis.name_cn, "阿妮斯：超级巨星")

        # By Chinese name
        helm = self.resolver.resolve_by_identifier("海伦")
        self.assertIsNotNone(helm)
        self.assertEqual(helm.resource_id, 352)

        # By English name
        snow = self.resolver.resolve_by_identifier("Snow White: Heavy Arms")
        self.assertIsNotNone(snow)
        self.assertEqual(snow.resource_id, 471)

    def test_unknown_tid_handling(self):
        cn, en, res_id, spine_id, char = self.resolver.resolve_member_identity(99999999)
        self.assertEqual(cn, "未知妮姬(99999999)")
        self.assertEqual(en, "Unknown(99999999)")
        self.assertEqual(res_id, "")
        self.assertEqual(spine_id, "")
        self.assertIsNone(char)


if __name__ == "__main__":
    unittest.main()

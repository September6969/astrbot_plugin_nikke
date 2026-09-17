# SPDX-License-Identifier: GPL-3.0-or-later
import json
import tempfile
import unittest
from pathlib import Path

from astrbot_plugin_nikke.features.character.skill_icon_resolver import SkillIconResolver


class SkillIconResolverTests(unittest.TestCase):
    def setUp(self):
        self.mapping_path = Path(__file__).resolve().parents[1] / "assets" / "mappings" / "skill_icons.json"

    def test_resolver_loads_default_catalog_with_characters(self):
        resolver = SkillIconResolver(self.mapping_path)
        self.assertGreaterEqual(resolver.total_characters, 200)

    def test_resolve_normal_character_skills(self):
        resolver = SkillIconResolver(self.mapping_path)
        # 102 (Maxwell): s1 is generic reload, s2 is generic crit dmg, burst is c102_ult
        s1 = resolver.resolve(102, "s1")
        self.assertEqual(s1, "icn_skill_statreloadtime_01")
        self.assertTrue(resolver.is_generic_icon(s1))

        s2 = resolver.resolve("102", "s2")
        self.assertEqual(s2, "icn_skill_criticaldamage_01")
        self.assertTrue(resolver.is_generic_icon(s2))

        burst = resolver.resolve(102, "burst")
        self.assertEqual(burst, "icn_skill_c102_ult")
        self.assertFalse(resolver.is_generic_icon(burst))

    def test_slot_aliases_normalization(self):
        resolver = SkillIconResolver(self.mapping_path)
        self.assertEqual(resolver.resolve(102, "skill1"), "icn_skill_statreloadtime_01")
        self.assertEqual(resolver.resolve(102, "skill_1"), "icn_skill_statreloadtime_01")
        self.assertEqual(resolver.resolve(102, "1"), "icn_skill_statreloadtime_01")
        self.assertEqual(resolver.resolve(102, "skill2"), "icn_skill_criticaldamage_01")
        self.assertEqual(resolver.resolve(102, "ulti"), "icn_skill_c102_ult")
        self.assertEqual(resolver.resolve(102, "ult"), "icn_skill_c102_ult")

    def test_unknown_character_returns_none(self):
        resolver = SkillIconResolver(self.mapping_path)
        self.assertIsNone(resolver.resolve(999999, "s1"))
        self.assertIsNone(resolver.resolve("not_a_character", "s1"))
        self.assertIsNone(resolver.resolve(None, "s1"))
        self.assertIsNone(resolver.resolve(True, "s1"))

    def test_invalid_slot_returns_none(self):
        resolver = SkillIconResolver(self.mapping_path)
        self.assertIsNone(resolver.resolve(102, "s3"))
        self.assertIsNone(resolver.resolve(102, "invalid"))
        self.assertIsNone(resolver.resolve(102, ""))

    def test_favorite_variant_falls_back_to_normal_when_empty(self):
        resolver = SkillIconResolver(self.mapping_path)
        # favorite variant 未配置时回退到 normal
        fav_s1 = resolver.resolve(102, "s1", variant="favorite")
        self.assertEqual(fav_s1, "icn_skill_statreloadtime_01")

    def test_favorite_variant_returns_custom_when_configured(self):
        with tempfile.TemporaryDirectory() as td:
            custom_file = Path(td) / "skill_icons.json"
            data = {
                "schema_version": 1,
                "characters": {
                    "352": {
                        "normal": {
                            "s1": "icn_skill_statcritical_01",
                            "s2": "icn_skill_atkup_01",
                            "burst": "icn_skill_c352_ult",
                        },
                        "favorite": {
                            "s1": "icn_skill_c352_fav_01",
                        },
                    }
                },
            }
            custom_file.write_text(json.dumps(data), encoding="utf-8")
            resolver = SkillIconResolver(custom_file)

            # favorite 命中
            self.assertEqual(resolver.resolve(352, "s1", variant="favorite"), "icn_skill_c352_fav_01")
            # favorite 未配 s2，回退到 normal s2
            self.assertEqual(resolver.resolve(352, "s2", variant="favorite"), "icn_skill_atkup_01")
            # normal 模式依然返回 normal s1
            self.assertEqual(resolver.resolve(352, "s1", variant="normal"), "icn_skill_statcritical_01")

    def test_logical_subpath_deduplication(self):
        resolver = SkillIconResolver(self.mapping_path)
        generic_path = resolver.get_logical_subpath("icn_skill_atkup_01")
        self.assertEqual(generic_path, "skills/generic/icn_skill_atkup_01.png")

        char_path = resolver.get_logical_subpath("icn_skill_c102_ult")
        self.assertEqual(char_path, "skills/character/icn_skill_c102_ult.png")

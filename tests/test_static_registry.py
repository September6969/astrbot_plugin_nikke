import json
import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

from astrbot_plugin_nikke.static_registry import StaticDataRegistry


class StaticDataRegistryTests(unittest.TestCase):
    def setUp(self):
        self.assets = Path(__file__).resolve().parents[1] / "assets"

    def test_verified_registries_expose_exact_ids_and_metadata(self):
        registry = StaticDataRegistry(self.assets)

        self.assertTrue(registry.is_valid)
        self.assertEqual(registry.metadata("equipment").source_ref, "assets/README.md")
        costumes = registry.mapping("costume")
        self.assertEqual(len(costumes), 41)
        self.assertEqual(costumes["10005"], "c010_03")
        self.assertEqual(registry.resolve("costume", "10005"), "c010_03")
        self.assertEqual(costumes["20001"], "c010_02")
        self.assertEqual(registry.resolve("costume", "20001"), "c010_02")
        self.assertIsNone(registry.resolve("costume", "10014"))
        self.assertEqual(
            registry.resolve("equipment", "3100901"),
            "icn_equipment_head_attacker_t9_3",
        )
        self.assertEqual(registry.resolve("cube", 1000304), "ie_10004")
        self.assertEqual(registry.resolve("favorite_item", "100602"), "si_favoriteitem_sr_00")

    def test_unknown_ids_are_not_normalized_or_guessed(self):
        registry = StaticDataRegistry(self.assets)

        self.assertIsNone(registry.resolve("equipment", "310090"))
        self.assertIsNone(registry.resolve("equipment", "../3100901"))
        self.assertIsNone(registry.resolve("unknown", "3100901"))
        for resource_id in (True, False, 1000304.0, " 1000304", "1000304 ", "+1000304"):
            with self.subTest(resource_id=resource_id):
                self.assertIsNone(registry.resolve("cube", resource_id))

    def test_hash_mismatch_disables_only_tampered_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for name in ("registry_manifest.json", "equipment.json", "cubes.json", "favorite_items.json", "costumes.json"):
                shutil.copy2(self.assets / name, target / name)

            content = (target / "equipment.json").read_text(encoding="utf-8")
            (target / "equipment.json").write_text(content + "\n", encoding="utf-8")
            registry = StaticDataRegistry(target)

            self.assertFalse(registry.is_valid)
            self.assertTrue(any("equipment sha256" in error for error in registry.errors))
            self.assertEqual(registry.mapping("equipment"), {})
            self.assertEqual(registry.resolve("cube", "1000304"), "ie_10004")

    def test_duplicate_mapping_keys_disable_only_ambiguous_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for name in ("registry_manifest.json", "equipment.json", "cubes.json", "favorite_items.json", "costumes.json"):
                shutil.copy2(self.assets / name, target / name)

            # 更新 manifest hash，确保本测试验证的是重复键合同，而不是 hash 失败。
            duplicate = b'{"3100901":"icn_equipment_head_attacker_t9_3","3100901":"icn_equipment_head_attacker_t9_1"}'
            (target / "equipment.json").write_bytes(duplicate)
            manifest = json.loads((target / "registry_manifest.json").read_text(encoding="utf-8"))
            manifest["registries"]["equipment"]["sha256"] = hashlib.sha256(duplicate).hexdigest()
            (target / "registry_manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
            )

            registry = StaticDataRegistry(target)

            self.assertEqual(registry.mapping("equipment"), {})
            self.assertTrue(any("重复键" in error for error in registry.errors))
            self.assertEqual(registry.resolve("cube", "1000304"), "ie_10004")

    def test_manifest_is_json_and_declares_all_supported_maps(self):
        manifest = json.loads((self.assets / "registry_manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(
            set(manifest["registries"]),
            {"equipment", "cube", "favorite_item", "costume"},
        )

    def test_costume_ids_are_explicit_and_use_asset_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for name in ("registry_manifest.json", "equipment.json", "cubes.json", "favorite_items.json", "costumes.json"):
                shutil.copy2(self.assets / name, target / name)

            content = json.dumps({"schema_version": 2, "entries": [{
                "costume_id": "skin_01", "character_resource_id": "191", "spine_asset_id": "c191_01",
                "source": "CharacterCostumeTable", "source_sha256": "a" * 64, "verified_at": "2026-09-09",
            }]}).encode("utf-8")
            (target / "costumes.json").write_bytes(content)
            manifest = json.loads((target / "registry_manifest.json").read_text(encoding="utf-8"))
            manifest["registries"]["costume"]["sha256"] = hashlib.sha256(content).hexdigest()
            (target / "registry_manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
            )

            registry = StaticDataRegistry(target)

            self.assertEqual(registry.resolve("costume", "skin_01"), "c191_01")
            self.assertIsNone(registry.resolve("costume", "../skin_01"))
            self.assertIsNone(registry.resolve("costume", True))


if __name__ == "__main__":
    unittest.main()

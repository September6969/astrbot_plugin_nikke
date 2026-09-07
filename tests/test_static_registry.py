import json
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
        self.assertEqual(
            registry.resolve("equipment", "3100901"),
            "icn_equipment_head_attacker_t9_3",
        )
        self.assertEqual(registry.resolve("cube", 1000304), "harmony_cube_1000304")
        self.assertEqual(registry.resolve("favorite_item", "100602"), "favorite_item_100602")

    def test_unknown_ids_are_not_normalized_or_guessed(self):
        registry = StaticDataRegistry(self.assets)

        self.assertIsNone(registry.resolve("equipment", "310090"))
        self.assertIsNone(registry.resolve("equipment", "../3100901"))
        self.assertIsNone(registry.resolve("unknown", "3100901"))

    def test_hash_mismatch_disables_only_tampered_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for name in ("registry_manifest.json", "equipment.json", "cubes.json", "favorite_items.json"):
                shutil.copy2(self.assets / name, target / name)

            content = (target / "equipment.json").read_text(encoding="utf-8")
            (target / "equipment.json").write_text(content + "\n", encoding="utf-8")
            registry = StaticDataRegistry(target)

            self.assertFalse(registry.is_valid)
            self.assertTrue(any("equipment sha256" in error for error in registry.errors))
            self.assertEqual(registry.mapping("equipment"), {})
            self.assertEqual(registry.resolve("cube", "1000304"), "harmony_cube_1000304")

    def test_manifest_is_json_and_declares_all_supported_maps(self):
        manifest = json.loads((self.assets / "registry_manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(
            set(manifest["registries"]),
            {"equipment", "cube", "favorite_item"},
        )


if __name__ == "__main__":
    unittest.main()

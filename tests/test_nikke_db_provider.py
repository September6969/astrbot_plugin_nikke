# SPDX-License-Identifier: GPL-3.0-or-later

import json
import tempfile
import unittest
from pathlib import Path

from astrbot_plugin_nikke.nikke_db_provider import NikkeDbProvider


class NikkeDbProviderTests(unittest.TestCase):
    def test_costume_file_accepts_only_strict_verified_shape(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "costumes.json"
            path.write_text(json.dumps({"schema_version": 2, "entries": [{
                "costume_id": "skin_01", "character_resource_id": "191", "spine_asset_id": "c191_01",
                "source": "CharacterCostumeTable", "source_sha256": "a" * 64, "verified_at": "2026-09-09",
            }, {"costume_id": "bad", "character_resource_id": "191", "spine_asset_id": "../c1"}]}), encoding="utf-8")
            provider = NikkeDbProvider(td, td)
            self.assertEqual(provider.costume_map, {"skin_01": "c191_01"})
            self.assertEqual(len(provider.costume_errors), 1)

    def test_id_normalization_and_overrides(self):
        with tempfile.TemporaryDirectory() as td:
            provider = NikkeDbProvider(td, td)
            self.assertEqual(provider.normalize_resource_id(191), "c191")
            self.assertEqual(provider.normalize_resource_id("10"), "c010")
            self.assertEqual(provider.normalize_resource_id("c470"), "c470")

            provider.NIKKE_DB_ID_OVERRIDES["special_999"] = "c999_custom"
            try:
                self.assertEqual(provider.resolve_character_id("special_999"), "c999_custom")
            finally:
                provider.NIKKE_DB_ID_OVERRIDES.pop("special_999", None)

    def test_invalid_ids_are_rejected_instead_of_sanitized(self):
        with tempfile.TemporaryDirectory() as td:
            provider = NikkeDbProvider(td, td)
            invalid_values = [True, False, 1.5, -1, None, {}, [], "19.1", "../191", "c191/00"]

            for value in invalid_values:
                with self.subTest(value=value):
                    self.assertEqual(provider.normalize_resource_id(value), "missing")
                    self.assertEqual(provider.resolve_character_id(value), "missing")

    def test_invalid_costume_mapping_and_url_segments_fall_back_safely(self):
        with tempfile.TemporaryDirectory() as td:
            provider = NikkeDbProvider(td, td)
            provider.COSTUME_OVERRIDES["bad_skin"] = "../c191_01"
            try:
                self.assertEqual(provider.resolve_character_id(191, costume_id=True), "missing")
                self.assertEqual(provider.resolve_character_id(191, costume_id="bad_skin"), "missing")
                self.assertEqual(provider.resolve_spine_bundle_urls("../191"), {})
                self.assertEqual(provider.resolve_spine_bundle_urls("191", action="../aim"), {})
            finally:
                provider.COSTUME_OVERRIDES.pop("bad_skin", None)

    def test_costume_mapping_does_not_fallback_unknown_to_default(self):
        with tempfile.TemporaryDirectory() as td:
            provider = NikkeDbProvider(td, td)
            provider.COSTUME_OVERRIDES["skin_01"] = "c191_01"
            try:
                # 已映射皮肤返回皮肤 ID
                self.assertEqual(provider.resolve_character_id(191, costume_id="skin_01"), "c191_01")
                # 未知皮肤不能伪装成默认角色
                self.assertEqual(provider.resolve_character_id(191, costume_id="unknown_skin"), "missing")
                # 无皮肤参数返回默认角色 ID
                self.assertEqual(provider.resolve_character_id(191), "c191")
            finally:
                provider.COSTUME_OVERRIDES.pop("skin_01", None)

    def test_costume_states_are_distinct(self):
        with tempfile.TemporaryDirectory() as td:
            provider = NikkeDbProvider(td, td)
            provider.COSTUME_OVERRIDES["skin_01"] = "c191_01"
            try:
                self.assertEqual(provider.costume_cache_token(None)[0], "default")
                self.assertEqual(provider.costume_cache_token(0)[0], "default")
                self.assertEqual(provider.costume_cache_token("skin_01")[0], "known")
                self.assertEqual(provider.costume_cache_token("unknown_skin")[0], "unknown")
                self.assertEqual(provider.costume_cache_token(True)[0], "invalid")
                self.assertNotEqual(
                    NikkeDbProvider.compute_cache_key("c191", None),
                    NikkeDbProvider.compute_cache_key("c191", "unknown_skin"),
                )
            finally:
                provider.COSTUME_OVERRIDES.pop("skin_01", None)

    def test_spine_identity_requires_verified_l2d_index(self):
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td) / "cache"
            index_dir = cache / "nikke-db" / "index"
            index_dir.mkdir(parents=True)
            (index_dir / "l2d.json").write_text(json.dumps([
                {"id": "c191", "version": 4.1}, {"id": "c191_01", "version": 4.1}
            ]), encoding="utf-8")
            provider = NikkeDbProvider(cache, td)
            self.assertEqual(provider.resolve_spine_asset_id(191), "c191")
            provider.COSTUME_OVERRIDES["skin_01"] = "c191_01"
            try:
                self.assertEqual(provider.resolve_spine_asset_id(191, costume_id="skin_01"), "c191_01")
                self.assertEqual(provider.resolve_spine_asset_id(191, costume_id="unknown"), "missing")
            finally:
                provider.COSTUME_OVERRIDES.pop("skin_01", None)

    def test_cache_key_generation_contract(self):
        key = NikkeDbProvider.compute_cache_key("c191", "skin_01", "v1", "4.1", "1.0")
        self.assertEqual(key, "c191_skin_01_v1_4.1_1.0")

        # 验证默认值
        default_key = NikkeDbProvider.compute_cache_key("c191")
        self.assertEqual(default_key, "c191_default_src_none_1.0")

    def test_spine_version_resolution_from_index_cache(self):
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "cache"
            index_dir = cache_dir / "nikke-db" / "index"
            index_dir.mkdir(parents=True)
            index_data = [
                {"id": "c010_03", "name": "Anis", "version": 4.1},
                {"id": "c191", "name": "Alice"},  # 无 version 字段
            ]
            (index_dir / "l2d.json").write_text(json.dumps(index_data), encoding="utf-8")

            provider = NikkeDbProvider(cache_dir, td, remote=False)
            # 明确标记 4.1
            self.assertEqual(provider.resolve_spine_version("c010_03"), 4.1)
            # 无版本标记时严格返回 None，禁止盲猜默认 runtime
            self.assertIsNone(provider.resolve_spine_version("c191"))
            # 未收录角色返回 None
            self.assertIsNone(provider.resolve_spine_version("c999"))

    def test_spine_bundle_urls(self):
        with tempfile.TemporaryDirectory() as td:
            provider = NikkeDbProvider(td, td)
            urls = provider.resolve_spine_bundle_urls("191", action="aim")
            self.assertEqual(
                urls["skel"],
                "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/l2d/c191/aim/c191_00.skel",
            )
            self.assertEqual(
                urls["atlas"],
                "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/l2d/c191/aim/c191_00.atlas",
            )
            self.assertEqual(
                urls["png"],
                "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/l2d/c191/aim/c191_00.png",
            )

    def test_negative_cache_and_concurrency_lock(self):
        with tempfile.TemporaryDirectory() as td:
            provider = NikkeDbProvider(td, td)
            self.assertFalse(provider.is_failed("c191"))
            provider.mark_failed("c191", duration=60)
            self.assertTrue(provider.is_failed("c191"))

            lock1 = provider.get_character_lock("c191")
            lock2 = provider.get_character_lock("c191")
            self.assertIs(lock1, lock2)
            lock3 = provider.get_character_lock("c010")
            self.assertIsNot(lock1, lock3)


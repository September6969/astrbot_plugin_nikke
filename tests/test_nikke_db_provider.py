# SPDX-License-Identifier: GPL-3.0-or-later

import json
import tempfile
import unittest
from pathlib import Path

from astrbot_plugin_nikke.nikke_db_provider import NikkeDbProvider


class NikkeDbProviderTests(unittest.TestCase):
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

    def test_costume_mapping_and_fallback_to_default(self):
        with tempfile.TemporaryDirectory() as td:
            provider = NikkeDbProvider(td, td)
            provider.COSTUME_OVERRIDES["skin_01"] = "c191_01"
            try:
                # 已映射皮肤返回皮肤 ID
                self.assertEqual(provider.resolve_character_id(191, costume_id="skin_01"), "c191_01")
                # 未知皮肤安全回退至默认角色 ID
                self.assertEqual(provider.resolve_character_id(191, costume_id="unknown_skin"), "c191")
                # 无皮肤参数返回默认角色 ID
                self.assertEqual(provider.resolve_character_id(191), "c191")
            finally:
                provider.COSTUME_OVERRIDES.pop("skin_01", None)

    def test_static_full_body_urls(self):
        with tempfile.TemporaryDirectory() as td:
            provider = NikkeDbProvider(td, td)
            url = provider.get_full_body_url(191)
            self.assertEqual(
                url,
                "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/images/FB/c191_00.png",
            )
            provider.COSTUME_OVERRIDES["skin_01"] = "c191_01"
            try:
                skin_url = provider.get_full_body_url(191, costume_id="skin_01")
                self.assertEqual(
                    skin_url,
                    "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/images/FB/c191_01_00.png",
                )
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


# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for LineupPortraitResolver.

Ensures 100% offline, deterministic portrait resolution with multi-level fallback.
"""

from pathlib import Path
import unittest
from unittest.mock import patch

from astrbot_plugin_nikke.features.character.lineup_portrait_resolver import (
    LineupPortraitResolver,
    LineupPortraitResolution,
)


class LineupPortraitResolverTests(unittest.TestCase):
    def setUp(self):
        # 使用本地镜像根目录进行测试
        self.resolver = LineupPortraitResolver(
            base_dir="data/nikke/blabla-assets",
            asset_dir="assets",
        )

    def test_resolve_default_character_by_resource_id(self):
        # Rapi: resource_id 10
        res = self.resolver.resolve(tid=10, character_id=10)
        self.assertIsInstance(res, LineupPortraitResolution)
        self.assertFalse(res.is_fallback)
        self.assertIsNone(res.fallback_reason)
        self.assertEqual(res.resource_id, 10)
        self.assertEqual(res.costume_index, 0)
        self.assertEqual(res.dimensions, (128, 128))
        self.assertTrue(res.local_path.is_file())
        self.assertTrue(str(res.local_path).endswith("si_c010_00_s.webp"))

    def test_resolve_default_character_by_battle_tid(self):
        # Rapi: battle tid 101001 -> resource_id 10
        res = self.resolver.resolve(tid=101001)
        self.assertIsInstance(res, LineupPortraitResolution)
        self.assertFalse(res.is_fallback)
        self.assertEqual(res.resource_id, 10)
        self.assertEqual(res.costume_index, 0)
        self.assertTrue(res.local_path.is_file())

    def test_resolve_costume_by_costume_id(self):
        # Liter Guardfish: costume_id 10001 -> resource_id 82, costume_index 1
        res = self.resolver.resolve(costume_id="10001")
        self.assertIsInstance(res, LineupPortraitResolution)
        self.assertFalse(res.is_fallback)
        self.assertEqual(res.resource_id, 82)
        self.assertEqual(res.costume_index, 1)
        self.assertTrue(res.local_path.is_file())
        self.assertTrue(str(res.local_path).endswith("si_c082_01_s.webp"))

    def test_fallback_when_costume_id_unknown(self):
        # 提供合法角色 (Rapi 10)，但传入不存在的 costume_id
        res = self.resolver.resolve(tid=10, costume_id="9999999")
        self.assertIsInstance(res, LineupPortraitResolution)
        self.assertTrue(res.is_fallback)
        self.assertIn("COSTUME_ID_9999999_NOT_FOUND", res.fallback_reason)
        # 应优雅降级为原皮 (00)
        self.assertEqual(res.costume_index, 0)
        self.assertEqual(res.resource_id, 10)
        self.assertTrue(res.local_path.is_file())
        self.assertTrue(str(res.local_path).endswith("si_c010_00_s.webp"))

    def test_fallback_when_character_unknown(self):
        # 完全未知的角色 ID
        res = self.resolver.resolve(tid=9999999)
        self.assertIsInstance(res, LineupPortraitResolution)
        self.assertTrue(res.is_fallback)
        self.assertEqual(res.fallback_reason, "UNRECOGNIZED_CHARACTER_ID")
        self.assertIsNone(res.resource_id)
        # 应返回通用占位图
        self.assertTrue(res.local_path.is_file())
        self.assertIn("default_avatar", str(res.local_path))

    def test_zero_network_guarantee(self):
        # 确保解析全过程绝不调用 httpx 或 socket
        with patch("httpx.Client.get") as mock_get:
            res = self.resolver.resolve(tid=10, costume_id="10001")
            self.assertFalse(mock_get.called)


if __name__ == "__main__":
    unittest.main()

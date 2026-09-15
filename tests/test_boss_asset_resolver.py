# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for BossAssetResolver.

Ensures 100% offline, deterministic boss asset resolution with robust fallback,
verified manifest integration, conflict prevention, and zero network calls.
"""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from astrbot_plugin_nikke.boss_asset_resolver import (
    BossAssetResolver,
    BossAssetResolution,
)


class BossAssetResolverTests(unittest.TestCase):
    def setUp(self):
        self.resolver = BossAssetResolver(
            base_dir="data/nikke/blabla-assets",
            asset_dir="assets",
        )

    def test_known_verified_boss_resolves_to_real_mirrored_image(self):
        """已知已验证 Boss 必须解析至真实本地镜像，绝不能返回 default_boss.webp。"""
        # 测试赛季 35 真实 Boss: Dual Ring (2420020214)
        res = self.resolver.resolve(boss_id="2420020214")
        self.assertIsInstance(res, BossAssetResolution)
        self.assertFalse(res.is_fallback, "Verified boss must NOT be flagged as fallback")
        self.assertIsNone(res.fallback_reason)
        self.assertEqual(res.icon_id, "ecg002")
        self.assertEqual(res.monster_model_id, "242002")
        self.assertIn("雙環", res.boss_name)
        self.assertTrue(res.local_path.is_file(), f"File does not exist: {res.local_path}")
        self.assertIn("full_ecg002.webp", str(res.local_path))
        self.assertEqual(res.dimensions, (1024, 1024))

        # 核心验收断言: 已知 Boss 绝不能返回 default_boss.webp
        self.assertNotIn(
            "default_boss",
            str(res.local_path).lower(),
            "assert known verified boss does NOT return default_boss.webp",
        )

        # 再次验证赛季 36 真实 Boss: Modernia (3520040134)
        res_m = self.resolver.resolve(boss_id="3520040134")
        self.assertFalse(res_m.is_fallback)
        self.assertEqual(res_m.icon_id, "mbg004_anmi")
        self.assertNotIn("default_boss", str(res_m.local_path).lower())

        # 验证测试别名 Boss: 101 (Alteisen)
        res_101 = self.resolver.resolve(boss_id="101")
        self.assertFalse(res_101.is_fallback)
        self.assertEqual(res_101.icon_id, "mbg001_psid")
        self.assertNotIn("default_boss", str(res_101.local_path).lower())

    def test_known_icon_id_resolves_correct_image(self):
        """已知 icon_id 能精准映射至对应的本地素材与相对 URI。"""
        test_icons = [
            ("ecg002", "full_ecg002.webp"),
            ("eba001", "full_eba001.webp"),
            ("ebg002_dmtr", "full_ebg002_dmtr.webp"),
            ("bbg003", "full_bbg003.webp"),
            ("mbg002", "full_mbg002.webp"),
        ]
        for icon_id, expected_file in test_icons:
            with self.subTest(icon_id=icon_id):
                res = self.resolver.resolve(icon_id=icon_id)
                self.assertFalse(res.is_fallback)
                self.assertEqual(res.icon_id, icon_id)
                self.assertTrue(res.local_path.is_file())
                self.assertIn(expected_file, str(res.local_path))
                self.assertEqual(res.relative_uri, f"/icon/monster_full/{expected_file}")
                self.assertNotIn("default_boss", str(res.local_path).lower())

    def test_known_monster_model_id_resolves_correct_mapping(self):
        """已知 monster_model_id 能通过 manifest 反查对应 icon_id 并命中文件。"""
        res = self.resolver.resolve(monster_model_id="242002")
        self.assertFalse(res.is_fallback)
        self.assertEqual(res.icon_id, "ecg002")
        self.assertIn("full_ecg002.webp", str(res.local_path))
        self.assertNotIn("default_boss", str(res.local_path).lower())

    def test_known_boss_with_missing_file_falls_back_safely(self):
        """已知 Boss 但文件在文件系统缺失时，安全降级至 default_boss 并标记 BOSS_IMAGE_MISSING。"""
        with tempfile.TemporaryDirectory() as td:
            isolated_resolver = BossAssetResolver(
                base_dir=td,
                asset_dir=td,
                manifest_path="data/nikke/blabla-manifests/boss_identity_manifest.json",
            )
            res = isolated_resolver.resolve(boss_id="2420020214")
            self.assertTrue(res.is_fallback)
            self.assertEqual(res.fallback_reason, "BOSS_IMAGE_MISSING")
            self.assertIn("default_boss", str(res.local_path).lower())

    def test_unknown_boss_falls_back(self):
        """未收录的未知 Boss 安全降级至 default_boss 并标记 UNKNOWN_BOSS。"""
        res = self.resolver.resolve(boss_id="nonexistent_boss_99999999")
        self.assertTrue(res.is_fallback)
        self.assertEqual(res.fallback_reason, "UNKNOWN_BOSS")
        self.assertIn("default_boss", str(res.local_path).lower())
        self.assertEqual(res.dimensions, (256, 256))

    def test_conflicting_boss_id_and_icon_id_fails_safely(self):
        """若入参中的 boss_id 与 icon_id 存在事实冲突，安全降级且不盲目推断。"""
        # 2420020214 实际是 Dual Ring (ecg002)，如果错误传入 mbg001_psid (Alteisen)
        res = self.resolver.resolve(boss_id="2420020214", icon_id="mbg001_psid")
        self.assertTrue(res.is_fallback)
        self.assertEqual(res.fallback_reason, "CONFLICTING_IDENTIFIERS")
        self.assertIn("default_boss", str(res.local_path).lower())

    def test_no_positional_inference(self):
        """严格按唯一标识符解析，绝不因数组下标或位置顺序猜测 Boss。"""
        # 即使入参按反序或无规律传入，解析结果依然确定且独立
        res_first = self.resolver.resolve(boss_id="2420020214")
        res_second = self.resolver.resolve(boss_id="2420060124")
        self.assertEqual(res_first.icon_id, "ecg002")
        self.assertEqual(res_second.icon_id, "ecg006")
        self.assertNotEqual(res_first.local_path, res_second.local_path)

        # 随机整数下标入参不会被误判为数组索引
        res_idx = self.resolver.resolve(boss_id="0")
        self.assertTrue(res_idx.is_fallback)
        self.assertEqual(res_idx.fallback_reason, "UNKNOWN_BOSS")

    def test_empty_parameters_fallback(self):
        """完全无入参时安全降级。"""
        res = self.resolver.resolve()
        self.assertIsInstance(res, BossAssetResolution)
        self.assertTrue(res.is_fallback)
        self.assertEqual(res.fallback_reason, "NO_BOSS_IDENTIFIER")
        self.assertEqual(res.boss_name, "Boss ?")
        self.assertTrue(res.local_path.is_file())
        self.assertIn("default_boss", str(res.local_path).lower())

    def test_zero_network_guarantee(self):
        """100% 离线，在解析已知与未知 Boss 过程中禁止发起任何 HTTP/网络调用。"""
        with patch("httpx.Client.get") as mock_get, patch("httpx.AsyncClient.get") as mock_aget:
            self.resolver.resolve(boss_id="2420020214")
            self.resolver.resolve(icon_id="ecg002")
            self.resolver.resolve(boss_id="99999999", icon_id="unknown_icon")
            self.assertFalse(mock_get.called)
            self.assertFalse(mock_aget.called)


if __name__ == "__main__":
    unittest.main()


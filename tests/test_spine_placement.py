# SPDX-License-Identifier: GPL-3.0-or-later
"""角色放置元数据 (CharacterPlacementMeta) 与锚点加权算法测试。"""

from unittest import TestCase

from astrbot_plugin_nikke.spine_placement import (
    Point,
    Rect,
    SkeletonAnchorSet,
    compute_clamped_visual_anchor,
    compute_placement_meta,
)
from astrbot_plugin_nikke.asset_manager import AssetManager
from astrbot_plugin_nikke.character_visual_resolver import CharacterVisualAssetResolver


class SpinePlacementTests(TestCase):
    def test_pelvis_preferred_as_body_anchor(self):
        anchors = SkeletonAnchorSet(
            pelvis=Point(0.50, 0.55),
            chest=Point(0.50, 0.35),
            head=Point(0.50, 0.20),
        )
        body_anchor = anchors.derive_body_anchor(root=Point(0.50, 0.90))
        self.assertEqual(body_anchor, Point(0.50, 0.55))

    def test_chest_and_pelvis_midpoint_fallback(self):
        anchors = SkeletonAnchorSet(
            chest=Point(0.50, 0.30),
            pelvis=None,
        )
        body_anchor = anchors.derive_body_anchor(root=Point(0.50, 0.90))
        # 缺少 pelvis 时回退到 chest
        self.assertEqual(body_anchor, Point(0.50, 0.30))

    def test_root_fallback_when_pelvis_and_chest_absent(self):
        anchors = SkeletonAnchorSet(head=Point(0.50, 0.20))
        body_anchor = anchors.derive_body_anchor(root=Point(0.50, 0.90))
        self.assertEqual(body_anchor, Point(0.50, 0.90))

    def test_feet_center_derivation(self):
        anchors = SkeletonAnchorSet(
            left_foot=Point(0.40, 0.88),
            right_foot=Point(0.60, 0.88),
        )
        fc = anchors.derive_feet_center()
        self.assertAlmostEqual(fc.x, 0.50)
        self.assertAlmostEqual(fc.y, 0.88)

    def test_clamped_visual_anchor_prevents_large_weapon_drag(self):
        # 人物身体锚点居中于 (0.50, 0.50)
        body_anchor = Point(0.50, 0.50)
        # 模拟一把巨大的右侧武器/特效拉偏 alpha bbox 中心到 x=0.90
        skewed_alpha = Rect(0.40, 0.10, 1.40, 0.90)  # center.x = 0.90 (偏离 +0.40)

        # 钳位算法 (max_offset_x = 0.15, weight_x = 0.30)
        anchor = compute_clamped_visual_anchor(body_anchor, skewed_alpha, max_offset_x=0.15, weight_x=0.30)

        # 即使偏差高达 0.40，被 clamp 到 0.15，再乘 0.30 仅允许偏移 0.045
        self.assertAlmostEqual(anchor.x, 0.50 + 0.15 * 0.30, places=3)
        self.assertLess(anchor.x, 0.56)

    def test_normalized_placement_meta_within_0_to_1(self):
        sem_points = {
            "head": (0.49, 0.21),
            "chest": (0.50, 0.34),
            "pelvis": (0.51, 0.49),
            "left_foot": (0.44, 0.88),
            "right_foot": (0.58, 0.89),
        }
        meta = compute_placement_meta("352", None, sem_points, (100, 80, 900, 950), (1000, 1000))
        d = meta.as_dict()

        for key in ("head", "chest", "pelvis", "feet_center", "body_anchor", "visual_anchor"):
            pt = d.get(key)
            self.assertIsNotNone(pt)
            self.assertTrue(0.0 <= pt[0] <= 1.0)
            self.assertTrue(0.0 <= pt[1] <= 1.0)

        self.assertEqual(meta.source, "runtime-skeleton")
        self.assertGreater(meta.confidence, 0.90)

    def test_alpha_only_fallback(self):
        meta = compute_placement_meta("999", None, {}, (200, 200, 800, 800), (1000, 1000))
        self.assertEqual(meta.source, "alpha-fallback")
        self.assertAlmostEqual(meta.body_anchor[0], 0.50)
        self.assertAlmostEqual(meta.body_anchor[1], 0.50)

    def test_visual_resolver_and_asset_manager_placement_lookup(self):
        resolver = CharacterVisualAssetResolver()
        # 查拉毗 (10:default)
        placement = resolver.get_character_placement("10")
        self.assertIsNotNone(placement)
        self.assertEqual(placement.get("resource_id"), "10")
        self.assertIn("body_anchor", placement)

        # 查拉毗皮肤 (10:10005)
        costume_placement = resolver.get_character_placement("10", "10005")
        self.assertIsNotNone(costume_placement)
        self.assertEqual(costume_placement.get("costume_id"), "10005")

        # 查不存在的角色
        self.assertIsNone(resolver.get_character_placement("999999"))

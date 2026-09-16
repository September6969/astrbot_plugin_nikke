# SPDX-License-Identifier: GPL-3.0-or-later
"""骨骼语义推断、映射规则与人工覆盖测试。"""

import json
import tempfile
from pathlib import Path
from unittest import TestCase

from astrbot_plugin_nikke.spine_runtime import ParsedBone, ParsedSkeleton
from astrbot_plugin_nikke.spine_semantic_mapper import SpineSemanticMapper, SemanticBoneMatch


def make_mock_skeleton() -> ParsedSkeleton:
    bones = [
        ParsedBone(0, "root", None, 0, 0, 0, 0),
        ParsedBone(1, "all", 0, 0, 20, 0, 0),
        ParsedBone(2, "lower_boddy", 1, 0, 500, 0, 0),
        ParsedBone(3, "c_breast_belt", 2, 0, 300, 0, 0),
        ParsedBone(4, "c_head", 3, 0, 250, 0, 0),
        ParsedBone(5, "c_neck", 3, 0, 100, 0, 0),
        ParsedBone(6, "c_shoulder_l", 3, -100, 200, 0, 0),
        ParsedBone(7, "c_shoulder_r", 3, 100, 200, 0, 0),
        ParsedBone(8, "c_foot_l", 2, -80, -400, 0, 0),
        ParsedBone(9, "c_foot_r", 2, 80, -400, 0, 0),
        ParsedBone(10, "random_prop_weapon", 0, 400, 100, 0, 0),
    ]
    return ParsedSkeleton(
        version="4.1",
        bounds=(-500, -500, 1000, 1600),
        bones=bones,
        slots=[],
        animations=[],
    )


class SpineSemanticTests(TestCase):
    def test_name_based_mapping_infers_standard_roles(self):
        skel = make_mock_skeleton()
        inferred = SpineSemanticMapper.infer_semantics(skel)

        self.assertIn("root", inferred)
        self.assertEqual(inferred["root"].bone_name, "root")
        self.assertEqual(inferred["root"].source, "auto-name")

        self.assertIn("head", inferred)
        self.assertEqual(inferred["head"].bone_name, "c_head")

        self.assertIn("chest", inferred)
        self.assertEqual(inferred["chest"].bone_name, "c_breast_belt")

        self.assertIn("pelvis", inferred)
        self.assertEqual(inferred["pelvis"].bone_name, "lower_boddy")

        self.assertIn("left_foot", inferred)
        self.assertEqual(inferred["left_foot"].bone_name, "c_foot_l")

        self.assertIn("right_foot", inferred)
        self.assertEqual(inferred["right_foot"].bone_name, "c_foot_r")

    def test_no_false_forced_match_on_random_props(self):
        skel = make_mock_skeleton()
        inferred = SpineSemanticMapper.infer_semantics(skel)
        # random_prop_weapon 不能被强行认定为核心角色骨骼
        matched_bones = {m.bone_name for m in inferred.values()}
        self.assertNotIn("random_prop_weapon", matched_bones)

    def test_manual_override_takes_absolute_priority(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "overrides.json"
            p.write_text(
                json.dumps({
                    "entries": {
                        "test_char:default": {
                            "head": "custom_overridden_head",
                            "pelvis": "custom_overridden_pelvis",
                        }
                    }
                }),
                encoding="utf-8",
            )
            mapper = SpineSemanticMapper(overrides_path=p)
            skel = make_mock_skeleton()
            matches = mapper.get_semantic_mapping("test_char:default", skel)

            self.assertEqual(matches["head"].bone_name, "custom_overridden_head")
            self.assertEqual(matches["head"].confidence, 1.0)
            self.assertEqual(matches["head"].source, "manual")

            self.assertEqual(matches["pelvis"].bone_name, "custom_overridden_pelvis")
            self.assertEqual(matches["pelvis"].confidence, 1.0)
            self.assertEqual(matches["pelvis"].source, "manual")

            # 没覆盖的 chest 依然保持自动推断
            self.assertEqual(matches["chest"].bone_name, "c_breast_belt")
            self.assertEqual(matches["chest"].source, "auto-name")

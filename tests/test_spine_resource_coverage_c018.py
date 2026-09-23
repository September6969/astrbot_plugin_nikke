# SPDX-License-Identifier: GPL-3.0-or-later
"""c018 正式资源链路与覆盖快照的离线合同测试。"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from astrbot_plugin_nikke.core.asset_manager import AssetManager
from astrbot_plugin_nikke.features.character.face_anchor import framing
from astrbot_plugin_nikke.features.character.weapon_bases import card_fields
from astrbot_plugin_nikke.features.character.visual_resolver import CharacterVisualAssetResolver
from astrbot_plugin_nikke.tests.test_card_builder import build_card


class SpineResourceCoverageC018Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]

    def _json(self, relative: str) -> dict:
        return json.loads((self.root / relative).read_text(encoding="utf-8"))

    def test_character_master_keeps_c018_identity(self) -> None:
        rows = self._json("assets/character_master.json")["characters"]
        row = next(item for item in rows if item.get("resource_id") == 18)
        self.assertEqual(row["spine_asset_id"], "c018")
        self.assertEqual(row["character_key"], "neon_vision_eye")

    def test_production_manifest_and_rendered_png_contain_c018(self) -> None:
        manifest = self._json("assets/spine_manifest.json")
        entry = manifest["characters"]["c018"]
        png = self.root / entry["local_relpath"]
        self.assertTrue(png.is_file())
        self.assertEqual(entry["spine_asset_id"], "c018")
        self.assertEqual(entry["character_resource_id"], "18")
        self.assertEqual(entry["sha256"], hashlib.sha256(png.read_bytes()).hexdigest())

    def test_production_face_anchor_contains_c018_and_matches_png(self) -> None:
        manifest = self._json("assets/spine_manifest.json")
        entry = manifest["characters"]["c018"]
        png = self.root / entry["local_relpath"]
        anchors = self._json("assets/data/face_anchors.json")["records"]
        record = anchors["c018"]
        with Image.open(png) as image:
            rgba = image.convert("RGBA")
            self.assertEqual(record["pixel_sha256"], hashlib.sha256(rgba.tobytes()).hexdigest())
            self.assertEqual(record["image_size"], list(rgba.size))
        self.assertNotEqual(record.get("anchor_kind"), "anchor_unavailable")

    def test_runtime_portrait_uses_c018_manifest_not_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = AssetManager(Path(directory) / "cache", self.root / "assets", remote=False)
            try:
                image = manager.get_character_portrait(101801, "18")
                expected = self._json("assets/spine_manifest.json")["characters"]["c018"]
                self.assertEqual(list(image.size), [expected["width"], expected["height"]])
                self.assertNotEqual(image.size, (600, 900))
            finally:
                manager.close()

    def test_visual_catalog_exposes_c018_rendered_portrait_and_spine(self) -> None:
        resolver = CharacterVisualAssetResolver()
        portrait = resolver.resolve(18, kind="portrait")
        spine = resolver.resolve(18, kind="spine")
        self.assertTrue(portrait.exact_match)
        self.assertEqual(portrait.logical_key, "assets/spine-rendered/c018.png")
        self.assertTrue(spine.exact_match)
        self.assertEqual(spine.asset_id, "c018")

    def test_production_framing_uses_c018_eye_anchor_without_guessing_torso(self) -> None:
        card = replace(
            build_card(),
            name_code="5170",
            resource_id="18",
            costume_id=0,
            spine_asset_id="c018",
            corporation="MISSILIS",
            element="Electronic",
            weapon="RL",
            burst="Step3",
            **card_fields(18),
        )
        with Image.open(self.root / "assets/spine-rendered/c018.png") as opened:
            portrait = opened.convert("RGBA")
        result = framing(card, portrait, body_centering=False, summary_count=4)
        self.assertEqual(result["source"], "eye_attachment")
        self.assertFalse(result["core_axis"]["available"])
        self.assertEqual(result["core_axis"]["reason"], "core_axis_unavailable")

    def test_coverage_snapshot_does_not_hide_c018(self) -> None:
        report = self._json("docs/evidence/spine_resource_coverage_20260923/coverage.json")
        missing = {row["render_id"] for row in report["upstream_exists_but_manifest_missing"]}
        self.assertNotIn("c018", missing)
        self.assertTrue(any(row["render_id"] == "c018" for row in report["covered_verified"]))

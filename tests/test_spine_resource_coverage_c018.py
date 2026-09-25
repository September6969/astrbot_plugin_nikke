# SPDX-License-Identifier: GPL-3.0-or-later
"""c018 正式资源链路与覆盖快照的离线合同测试。"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import replace
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from astrbot_plugin_nikke.core.asset_manager import AssetManager
from astrbot_plugin_nikke.features.character.face_anchor import framing
from astrbot_plugin_nikke.features.character.master_resolver import CharacterMasterResolver
from astrbot_plugin_nikke.features.character.weapon_bases import card_fields
from astrbot_plugin_nikke.integrations.nikke_db.provider import NikkeDbProvider
from astrbot_plugin_nikke.features.character.visual_resolver import CharacterVisualAssetResolver
from astrbot_plugin_nikke.tests.test_card_builder import build_card
from astrbot_plugin_nikke.ui.renderers.t2i import T2IRenderer


class SpineResourceCoverageC018Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]

    def _json(self, relative: str) -> dict:
        return json.loads((self.root / relative).read_text(encoding="utf-8"))

    def test_character_master_keeps_c018_identity(self) -> None:
        rows = self._json("assets/data/character_master.json")["characters"]
        row = next(item for item in rows if item.get("resource_id") == 18)
        self.assertEqual(row["spine_asset_id"], "c018")
        self.assertEqual(row["character_key"], "neon_vision_eye")
        master = CharacterMasterResolver(self.root / "assets/data/character_master.json")
        provider = NikkeDbProvider(self.root / "audit-cache-unused", self.root / "assets", remote=False, master_resolver=master)
        canonical = master.resolve_resource_id(18)
        self.assertIsNotNone(canonical)
        self.assertEqual(canonical.spine_asset_id, "c018")
        self.assertEqual(provider.resolve_render_id(18), "c018")

    def test_production_manifest_and_rendered_png_contain_c018(self) -> None:
        manifest = self._json("assets/spine_manifest.json")
        entry = manifest["characters"]["c018"]
        png = self.root / entry["local_relpath"]
        self.assertTrue(png.is_file())
        self.assertEqual(entry["spine_asset_id"], "c018")
        self.assertEqual(entry["character_resource_id"], "18")
        self.assertEqual(entry["sha256"], hashlib.sha256(png.read_bytes()).hexdigest())
        self.assertEqual(entry["sha256"], "045b0b3b568e7a2731ea42fb56b35b418e75f845842c889f22ac5963e58a33c5")
        with Image.open(png) as opened:
            rgba = opened.convert("RGBA")
            self.assertEqual(list(rgba.size), [entry["width"], entry["height"]])
            self.assertEqual(list(rgba.getchannel("A").getbbox()), entry["alpha_bbox"])
            self.assertEqual(list(rgba.size), [2536, 3830])
            self.assertEqual(hashlib.sha256(rgba.tobytes()).hexdigest(), "c69086e57ee92e93764763c090018f5d0bbb11bc44dd0b7c8aa234a7f720cd80")
        self.assertEqual(entry["runtime_version"], "4.1")

    def test_current_upstream_snapshot_has_l2d_bundle_and_no_c018_fb(self) -> None:
        snapshot = self._json("docs/evidence/spine_resource_coverage_post_refactor/upstream_asset_snapshot.json")
        paths = [row["path"] for row in snapshot["l2d_files"]]
        self.assertTrue({
            "l2d/c018/c018_00.skel",
            "l2d/c018/c018_00.atlas",
            "l2d/c018/c018_00.png",
        } <= set(paths))
        fb_paths = {row["path"] for row in snapshot["fb_files"]}
        self.assertNotIn("images/FB/c018_00.png", fb_paths)

    def test_production_face_anchor_contains_c018_and_matches_png(self) -> None:
        manifest = self._json("assets/spine_manifest.json")
        entry = manifest["characters"]["c018"]
        png = self.root / entry["local_relpath"]
        anchors = self._json("assets/data/face_anchors.json")["records"]
        record = anchors["c018"]
        with Image.open(png) as image:
            rgba = image.convert("RGBA")
            self.assertEqual(record["pixel_sha256"], hashlib.sha256(rgba.tobytes()).hexdigest())
            self.assertEqual(record["png_sha256"], hashlib.sha256(png.read_bytes()).hexdigest())
            self.assertEqual(record["image_size"], list(rgba.size))
        self.assertNotEqual(record.get("anchor_kind"), "anchor_unavailable")
        self.assertEqual(record["runtime"], "4.1.20")
        self.assertIsNone(record.get("core_axis"))
        self.assertEqual(record["core_axis_reason"], "upper_torso_unavailable")
        self.assertEqual(record["anchor_kind"], "eye_attachment")

        transform = record["png_transform"]
        bbox = transform["alpha_bbox"]
        padding = transform["crop_padding"]
        render_width = transform["render_size"][0]
        self.assertEqual([bbox[2] - bbox[0] + 2 * padding, bbox[3] - bbox[1] + 2 * padding], record["image_size"])
        expected_point = [
            record["point_1024"][0] * render_width / 1024 - bbox[0] + padding,
            record["point_1024"][1] * render_width / 1024 - bbox[1] + padding,
        ]
        self.assertAlmostEqual(record["point"][0], expected_point[0], places=8)
        self.assertAlmostEqual(record["point"][1], expected_point[1], places=8)
        self.assertAlmostEqual(record["point"][0], 467.2466204157688, places=8)
        self.assertAlmostEqual(record["point"][1], 592.8506619118557, places=8)

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
        record = self._json("assets/data/face_anchors.json")["records"]["c018"]
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
        identity = NikkeDbProvider(self.root / "assets", self.root / "assets", remote=False)
        result = framing(
            card,
            portrait,
            body_centering=False,
            summary_count=4,
            identity_resolver=identity,
        )
        self.assertEqual(result["source"], "eye_attachment")
        self.assertFalse(result["core_axis"]["available"])
        self.assertEqual(result["core_axis"]["reason"], "core_axis_unavailable")
        style_values = {
            key: value
            for key, value in (part.split(":", 1) for part in result["style"].split(";") if ":" in part)
        }
        image_width = float(style_values["width"].removesuffix("px"))
        scale = image_width / portrait.width
        left = float(style_values["left"].removesuffix("px"))
        top = float(style_values["top"].removesuffix("px"))
        eye_x = left + record["point"][0] * scale
        eye_y = top + record["point"][1] * scale
        self.assertAlmostEqual(eye_x, 760.0, places=2)
        self.assertEqual(result["vertical_guard_source"], "face_safe_top")
        self.assertAlmostEqual(
            result["guard_top_source_y"],
            record["point"][1] - record["extent"][1],
        )
        self.assertGreaterEqual(
            result["guard_top_card_after"], result["safe_top"] - 1.0
        )
        self.assertGreaterEqual(result["vertical_correction_y"], 0.0)
        self.assertLess(result["vertical_correction_y"], 10.0)
        self.assertAlmostEqual(
            eye_y, 566.0 + result["vertical_correction_y"], places=2
        )

    def test_stale_c018_face_anchor_fails_closed(self) -> None:
        card = replace(
            build_card(),
            name_code="5170",
            resource_id="18",
            costume_id=0,
            spine_asset_id="c018",
            **card_fields(18),
        )
        with Image.open(self.root / "assets/spine-rendered/c018.png") as opened:
            stale_portrait = opened.convert("RGBA").copy()
        stale_portrait.putpixel((0, 0), (255, 0, 0, 255))
        identity = NikkeDbProvider(self.root / "assets", self.root / "assets", remote=False)
        result = framing(card, stale_portrait, body_centering=False, summary_count=4, identity_resolver=identity)

        self.assertEqual(result["source"], "anchor_unavailable")
        self.assertFalse(result.get("core_axis", {}).get("available", False))

    def test_current_white_card_renderer_consumes_verified_c018_portrait(self) -> None:
        async def exercise() -> None:
            card = replace(
                build_card(),
                name_code="5170",
                resource_id="18",
                costume_id=0,
                spine_asset_id="c018",
                **card_fields(18),
            )
            captured: dict[str, object] = {}

            async def native_render(template, payload, *, options):
                captured["template"] = template
                captured["payload"] = payload
                captured["options"] = options
                return "c018-white-card-render.png"

            with tempfile.TemporaryDirectory() as directory:
                manager = AssetManager(Path(directory) / "cache", self.root / "assets", remote=False)
                try:
                    renderer = T2IRenderer(native_render, manager)
                    result = await renderer.render_view("character", card)
                    self.assertEqual(result, "c018-white-card-render.png")
                    template = str(captured["template"])
                    self.assertIn("width=1600", template)
                    self.assertIn("width:1600px;height:2400px", template)
                    self.assertIn("#f2f4f7", template)
                    payload = captured["payload"]
                    self.assertIsInstance(payload, dict)
                    data_uri = payload["character_art_data_uri"]
                    encoded = base64.b64decode(data_uri.partition(",")[2])
                    with Image.open(self.root / "assets/spine-rendered/c018.png") as opened:
                        expected_uri = renderer.payload_builder.resolver.encode(opened.convert("RGBA"), (1600, 2400))
                    self.assertEqual(data_uri, expected_uri)
                    self.assertTrue(encoded.startswith(b"\x89PNG\r\n\x1a\n"))
                finally:
                    manager.close()

        asyncio.run(exercise())

    def test_coverage_snapshot_does_not_hide_c018(self) -> None:
        from scripts.audit_spine_resource_coverage import audit

        snapshot = self._json("docs/evidence/spine_resource_coverage_post_refactor/upstream_asset_snapshot.json")
        report = audit(self.root, snapshot, generated_from_head="c018-test")
        self.assertNotIn("c018", report["sets"]["upstream_exists_manifest_missing"])
        self.assertNotIn("c018", report["sets"]["render_asset_gap"])
        self.assertTrue(report["manifest_status"]["c018"]["valid"])

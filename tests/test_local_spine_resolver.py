# SPDX-License-Identifier: GPL-3.0-or-later
"""LocalSpineBundleResolver 单元测试。"""

import tempfile
import unittest
from pathlib import Path

from astrbot_plugin_nikke.local_spine_resolver import LocalSpineBundleResolver, SpineBundle


class LocalSpineBundleResolverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.resolver = LocalSpineBundleResolver(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_path_traversal_protection(self):
        self.assertIsNone(self.resolver.resolve_bundle("../etc/passwd"))
        self.assertIsNone(self.resolver.resolve_bundle(".."))
        self.assertIsNone(self.resolver.resolve_bundle("c010/../../something"))

    def test_missing_directory_returns_none(self):
        self.assertIsNone(self.resolver.resolve_bundle("c999"))

    def test_successful_resolution_4_0(self):
        char_dir = self.root / "l2d" / "c010"
        char_dir.mkdir(parents=True)
        # Skeleton binary with 4.0 header
        skel_bytes = b"\x00\x00Spine 4.0.64\x00\x01\x02\x03" + b"\x00" * 50
        (char_dir / "c010.skel").write_bytes(skel_bytes)
        # Atlas declared texture page
        (char_dir / "c010.atlas").write_text("\ufeffc010.png\nsize: 1024,1024\n", encoding="utf-8")
        (char_dir / "c010.png").write_bytes(b"PNGDATA")

        bundle = self.resolver.resolve_bundle("c010")
        self.assertIsNotNone(bundle)
        self.assertIsInstance(bundle, SpineBundle)
        self.assertEqual(bundle.asset_id, "c010")
        self.assertEqual(bundle.version, "4.0")
        self.assertEqual(bundle.skel_path.name, "c010.skel")
        self.assertEqual(bundle.atlas_path.name, "c010.atlas")
        self.assertEqual(len(bundle.texture_paths), 1)
        self.assertEqual(bundle.texture_paths[0].name, "c010.png")

    def test_successful_resolution_4_1_multiple_textures(self):
        char_dir = self.root / "c330"
        char_dir.mkdir(parents=True)
        skel_bytes = b"\x00\x00Spine 4.1.24\x00\x01\x02\x03" + b"\x00" * 50
        (char_dir / "c330_00.skel").write_bytes(skel_bytes)
        (char_dir / "c330_00.atlas").write_text("c330_00.png\nsize: 1024,1024\n\nc330_01.png\nsize: 1024,1024\n", encoding="utf-8")
        (char_dir / "c330_00.png").write_bytes(b"PNG1")
        (char_dir / "c330_01.png").write_bytes(b"PNG2")

        bundle = self.resolver.resolve_bundle("c330")
        self.assertIsNotNone(bundle)
        self.assertEqual(bundle.version, "4.1")
        self.assertEqual(len(bundle.texture_paths), 2)
        self.assertEqual([p.name for p in bundle.texture_paths], ["c330_00.png", "c330_01.png"])

    def test_missing_texture_fails_fast(self):
        char_dir = self.root / "l2d" / "c017"
        char_dir.mkdir(parents=True)
        skel_bytes = b"\x00\x00Spine 4.0.64\x00\x01\x02\x03" + b"\x00" * 50
        (char_dir / "c017.skel").write_bytes(skel_bytes)
        (char_dir / "c017.atlas").write_text("c017.png\nsize: 1024,1024\n\nc017_2.png\n", encoding="utf-8")
        (char_dir / "c017.png").write_bytes(b"PNG1")
        # c017_2.png is missing!

        self.assertIsNone(self.resolver.resolve_bundle("c017"))

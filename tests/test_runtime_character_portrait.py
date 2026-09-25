# SPDX-License-Identifier: GPL-3.0-or-later
"""测试上游 Spine 立绘进入当前角色卡资产链。"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch

from PIL import Image

from astrbot_plugin_nikke.core.asset_manager import AssetManager
from astrbot_plugin_nikke.features.character.models import CharacterCardAssets
from astrbot_plugin_nikke.integrations.nikke_db.provider import SpineBundleSource
from astrbot_plugin_nikke.integrations.spine.prerenderer import SpineBundle, SpinePreRenderer
from astrbot_plugin_nikke.tests.test_card_builder import build_card
from astrbot_plugin_nikke.tests.test_character_replica import example_card
from astrbot_plugin_nikke.ui.payloads.character import CharacterT2IPayloadBuilder
from astrbot_plugin_nikke.ui.t2i_assets import T2IAssetResolver


class _FakeRuntime:
    version = "4.1"

    def __init__(self) -> None:
        self.calls = 0

    def render(self, bundle, *, animation: str, skin: str | None = None) -> Image.Image:
        self.calls += 1
        return Image.new("RGBA", (32, 64), (22, 177, 88, 255))


class _FakeFetcher:
    def __init__(self, bundle: SpineBundle) -> None:
        self.bundle = bundle
        self.calls = 0

    def fetch(self, urls, cache_key, *, budget_seconds=None, expected_blob_hashes=None) -> SpineBundle:
        self.calls += 1
        return self.bundle


class RuntimeCharacterPortraitTests(unittest.TestCase):
    def _bundle(self, root: Path) -> SpineBundle:
        bundle_dir = root / "bundle"
        bundle_dir.mkdir()
        skeleton = bundle_dir / "runtime.json"
        skeleton.write_text(json.dumps({"skeleton": {"spine": "4.1.20"}}), encoding="utf-8")
        atlas = bundle_dir / "hero.atlas"
        atlas.write_text(
            "portrait/page-1.png\nsize: 16,16\nformat: RGBA8888\nfilter: Linear,Linear\nrepeat: none\nregion\nbounds: 0,0,16,16\n",
            encoding="utf-8",
        )
        texture = bundle_dir / "portrait" / "page-1.png"
        texture.parent.mkdir()
        Image.new("RGBA", (16, 16), "white").save(texture)
        return SpineBundle(skeleton, atlas, (texture,))

    def _source(self) -> SpineBundleSource:
        return SpineBundleSource(
            asset_id="c020",
            source_version="a" * 40,
            runtime_version=None,
            urls={
                "skel": "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/" + "b" * 40 + "/l2d/c020/hero.json",
                "atlas": "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/" + "b" * 40 + "/l2d/c020/hero.atlas",
                "portrait/page-1.png": "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/" + "b" * 40 + "/l2d/c020/portrait/page-1.png",
            },
            blob_hashes={},
        )

    def _manager(self, root: Path, *, runtime: _FakeRuntime | None = None):
        cache_dir = root / "cache"
        fake_runtime = runtime or _FakeRuntime()
        fetcher = _FakeFetcher(self._bundle(root))
        renderer = SpinePreRenderer(cache_dir, runtime={"4.1": fake_runtime}, fetcher=fetcher)
        manager = AssetManager(cache_dir, root / "assets", remote=True, spine_renderer=renderer)
        source = self._source()
        manager.nikke_db.resolve_spine_bundle_source = lambda *_args, **_kwargs: source
        return manager, fake_runtime, fetcher, source

    def test_bundled_portrait_wins_without_upstream_lookup_or_render(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            rendered = assets / "spine-rendered"
            rendered.mkdir(parents=True)
            image_path = rendered / "c018.png"
            Image.new("RGBA", (25, 40), (201, 17, 31, 255)).save(image_path)
            (assets / "spine_manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "characters": {
                            "c018": {
                                "png_file": "c018.png",
                                "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
                                "width": 25,
                                "height": 40,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            manager, runtime, fetcher, _source = self._manager(root)
            try:
                with patch.object(manager.nikke_db, "resolve_spine_bundle_source", side_effect=AssertionError("unexpected upstream lookup")):
                    image = manager.get_character_portrait(101801, "18")
                self.assertEqual(image.getpixel((0, 0)), (201, 17, 31, 255))
                self.assertEqual((runtime.calls, fetcher.calls), (0, 0))
            finally:
                manager.close()

    def test_real_c018_manifest_portrait_reaches_white_card_payload(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            manager = AssetManager(Path(directory) / "cache", repo_root / "assets", remote=False)
            try:
                card = replace(example_card(), resource_id="18", costume_id=0, spine_asset_id="c018")
                assets = manager.resolve_character_assets(card, timeout=6.0)
                expected = T2IAssetResolver().encode(assets.portrait, (1600, 2400))
                payload = CharacterT2IPayloadBuilder(
                    T2IAssetResolver(), identity_resolver=manager.nikke_db
                ).build(card, assets)
                self.assertEqual(payload["character_art_data_uri"], expected)
                self.assertNotEqual(assets.portrait.size, (600, 900))
            finally:
                manager.close()

    def test_unmanifested_portrait_renders_once_then_hits_content_versioned_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager, runtime, fetcher, source = self._manager(root)
            try:
                with patch.object(manager.nikke_db, "resolve_spine_bundle_source", return_value=source):
                    first = manager.get_character_portrait(301701, "20")
                    second = manager.get_character_portrait(301701, "20")
                self.assertEqual(first.getpixel((0, 0)), (22, 177, 88, 255))
                self.assertEqual(second.getpixel((0, 0)), (22, 177, 88, 255))
                self.assertEqual(runtime.calls, 1)
                self.assertEqual(fetcher.calls, 1)
                self.assertTrue(list((root / "cache" / "portraits").glob("*.png")))
            finally:
                manager.close()

    def test_invalid_bundled_entry_falls_through_to_verified_upstream_render(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            rendered = assets / "spine-rendered"
            rendered.mkdir(parents=True)
            Image.new("RGBA", (12, 12), "red").save(rendered / "c020.png")
            (assets / "spine_manifest.json").write_text(
                json.dumps({"schema_version": 1, "characters": {"c020": {"png_file": "c020.png", "sha256": "0" * 64}}}),
                encoding="utf-8",
            )
            manager, runtime, fetcher, source = self._manager(root)
            try:
                with patch.object(manager.nikke_db, "resolve_spine_bundle_source", return_value=source):
                    image = manager.get_character_portrait(301701, "20")
                self.assertEqual(image.getpixel((0, 0)), (22, 177, 88, 255))
                self.assertEqual((runtime.calls, fetcher.calls), (1, 1))
            finally:
                manager.close()

    def test_changed_upstream_tree_gets_a_distinct_runtime_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager, runtime, fetcher, first_source = self._manager(root)
            second_source = SpineBundleSource(
                asset_id=first_source.asset_id,
                source_version="b" * 40,
                runtime_version=None,
                urls=first_source.urls,
                blob_hashes=first_source.blob_hashes,
            )
            try:
                with patch.object(manager.nikke_db, "resolve_spine_bundle_source", side_effect=[first_source, second_source]):
                    manager.get_character_portrait(301701, "20")
                    manager.get_character_portrait(301701, "20")
                self.assertEqual((runtime.calls, fetcher.calls), (2, 2))
            finally:
                manager.close()

    def test_runtime_portrait_is_passed_to_current_character_card_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager, runtime, fetcher, source = self._manager(root)
            try:
                with patch.object(manager.nikke_db, "resolve_spine_bundle_source", return_value=source):
                    assets = manager.resolve_character_assets(replace(build_card(), resource_id="20"), timeout=3.0)
                self.assertIsInstance(assets, CharacterCardAssets)
                self.assertEqual(assets.portrait.getpixel((0, 0)), (22, 177, 88, 255))
                self.assertEqual(runtime.calls, 1)
                self.assertEqual(fetcher.calls, 1)
            finally:
                manager.close()

    def test_missing_upstream_bundle_and_worker_failure_keep_card_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager, runtime, fetcher, _source = self._manager(root)
            try:
                with patch.object(manager.nikke_db, "resolve_spine_bundle_source", return_value=None):
                    missing = manager.get_character_portrait(301701, "20")
                self.assertEqual(missing.size, (600, 900))
                self.assertEqual((runtime.calls, fetcher.calls), (0, 0))

                with patch.object(manager.nikke_db, "resolve_spine_bundle_source", return_value=self._source()):
                    with patch.object(manager.spine_renderer, "render_full_body", return_value=None):
                        failed = manager.get_character_portrait(301701, "20")
                self.assertEqual(failed.size, (600, 900))
                self.assertEqual(fetcher.calls, 1)
            finally:
                manager.close()


if __name__ == "__main__":
    unittest.main()

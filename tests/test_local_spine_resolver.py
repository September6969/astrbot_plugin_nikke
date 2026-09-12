import tempfile
from pathlib import Path
from unittest import TestCase

from PIL import Image

from astrbot_plugin_nikke.local_spine_resolver import (
    LocalSpineBundleResolver,
    LocalSpineResolveError,
)


class LocalSpineResolverTests(TestCase):
    def make_bundle(self, root: Path, asset_id: str = "c010", version: str = "4.1") -> Path:
        bundle = root / "l2d" / asset_id
        bundle.mkdir(parents=True)
        (bundle / f"{asset_id}_00.skel").write_bytes(b"12345678\x074.1.24" if version == "4.1" else b"12345678\x074.0.47")
        Image.new("RGBA", (20, 20), "red").save(bundle / "one.png")
        Image.new("RGBA", (24, 24), "blue").save(bundle / "two.png")
        (bundle / f"{asset_id}_00.atlas").write_text(
            "\ufeffone.png\nsize: 20, 20\n\n"
            "two.png\nsize: 24, 24\n",
            encoding="utf-8-sig",
        )
        return bundle

    def test_resolves_bom_multi_page_bundle_and_real_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_bundle(root)
            result = LocalSpineBundleResolver(root).resolve("c010")
            self.assertEqual(result.runtime_version, "4.1")
            self.assertEqual([path.name for path in result.texture_paths], ["one.png", "two.png"])
            self.assertEqual(result.as_spine_bundle().textures, result.texture_paths)

    def test_resolves_nested_atlas_texture_page(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "l2d" / "c010"
            bundle.mkdir(parents=True)
            (bundle / "c010_00.skel").write_bytes(b"header 4.0.47")
            nested = bundle / "textures"
            nested.mkdir()
            page = nested / "body.png"
            Image.new("RGBA", (24, 16), "purple").save(page)
            (bundle / "c010_00.atlas").write_text(
                "\ufefftextures/body.png\nsize: 24, 16\n", encoding="utf-8-sig"
            )

            result = LocalSpineBundleResolver(root).resolve("c010")

            self.assertEqual(result.texture_paths, (page.resolve(),))

    def test_supports_40_without_guessing_from_character(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_bundle(root, "c999", version="4.0")
            result = LocalSpineBundleResolver(root).resolve("c999")
            self.assertEqual(result.runtime_version, "4.0")

    def test_rejects_invalid_asset_id_and_atlas_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_bundle(root)
            with self.assertRaises(LocalSpineResolveError):
                LocalSpineBundleResolver(root).resolve("../c010")
            atlas = root / "l2d" / "c010" / "c010_00.atlas"
            atlas.write_text("../outside.png\nsize: 20, 20\n", encoding="utf-8")
            with self.assertRaises(LocalSpineResolveError):
                LocalSpineBundleResolver(root).resolve("c010")

    def test_rejects_missing_or_corrupt_texture_and_unknown_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self.make_bundle(root)
            (bundle / "two.png").unlink()
            with self.assertRaisesRegex(LocalSpineResolveError, "缺少 atlas 纹理页"):
                LocalSpineBundleResolver(root).resolve("c010")

            self.make_bundle(root, "c011", version="4.1")
            (root / "l2d" / "c011" / "c011_00.skel").write_bytes(b"no version header")
            with self.assertRaisesRegex(LocalSpineResolveError, "版本未知"):
                LocalSpineBundleResolver(root).resolve("c011")

    def test_rejects_ambiguous_named_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self.make_bundle(root)
            (bundle / "c010.skel").write_bytes(b"header 4.1.24")
            with self.assertRaisesRegex(LocalSpineResolveError, "歧义"):
                LocalSpineBundleResolver(root).resolve("c010")

    def test_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self.make_bundle(root)
            outside = root.parent / f"{root.name}-outside.png"
            Image.new("RGBA", (20, 20), "green").save(outside)
            try:
                (bundle / "one.png").unlink()
                try:
                    (bundle / "one.png").symlink_to(outside)
                except (OSError, NotImplementedError):
                    self.skipTest("当前环境不允许创建符号链接")
                with self.assertRaisesRegex(LocalSpineResolveError, "路径越界"):
                    LocalSpineBundleResolver(root).resolve("c010")
            finally:
                outside.unlink(missing_ok=True)

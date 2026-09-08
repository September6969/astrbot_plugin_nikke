"""正式 Spine 编排层的离线契约测试。

测试中的 FakeRuntime 只验证依赖注入边界，不代表已安装、授权或联调真实
Spine runtime；真实 runtime、合法测试素材和 Linux headless 仍单独登记。
"""

import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

from PIL import Image, ImageDraw

from astrbot_plugin_nikke.spine_prerenderer import (
    SpineBundle,
    SpineBundleFetcher,
    SpineJob,
    SpinePreRenderer,
    SpineRenderError,
)


class FakeRuntime:
    """合成 runtime，只用于测试 adapter 的输入输出合同。"""

    version = "4.1"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def render(self, bundle: SpineBundle, *, animation: str, skin: str | None = None) -> Image.Image:
        self.calls.append((animation, skin))
        image = Image.new("RGBA", (320, 420), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((100, 120, 220, 330), fill=(240, 80, 150, 255))
        return image


def make_bundle(root: Path) -> SpineBundle:
    texture = root / "page.png"
    Image.new("RGBA", (64, 64), (255, 255, 255, 255)).save(texture, format="PNG")
    skeleton = root / "sample.json"
    skeleton.write_text(json.dumps({"skeleton": {"spine": "4.1.24"}}), encoding="utf-8")
    atlas = root / "sample.atlas"
    atlas.write_text("page.png\nsize: 64, 64\n\n", encoding="utf-8")
    return SpineBundle(skeleton=skeleton, atlas=atlas, textures=(texture,))


class SpineFormalBackendTests(TestCase):
    def test_injected_runtime_renders_cropped_rgba_and_preserves_animation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = FakeRuntime()
            renderer = SpinePreRenderer(root / "cache", runtime=runtime)

            result = renderer.render_full_body(
                make_bundle(root),
                "4.1",
                animation="idle",
                skin="default",
            )

            self.assertIsNotNone(result)
            self.assertEqual(result.mode, "RGBA")
            self.assertLess(result.width, 320)
            self.assertLess(result.height, 420)
            self.assertEqual(runtime.calls, [("idle", "default")])

    def test_runtime_version_mismatch_and_missing_runtime_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = make_bundle(root)
            runtime = FakeRuntime()

            self.assertIsNone(
                SpinePreRenderer(root / "mismatch", runtime=runtime).render_full_body(bundle, "4.2")
            )
            self.assertEqual(runtime.calls, [])
            self.assertIsNone(SpinePreRenderer(root / "none").render_full_body(bundle, "4.1"))

    def test_binary_bundle_with_unknown_version_does_not_guess_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = make_bundle(root)
            unknown_skeleton = root / "unknown.skel"
            unknown_skeleton.write_bytes(b"binary without inspected version")
            bundle = SpineBundle(unknown_skeleton, source.atlas, source.textures)
            runtime = FakeRuntime()
            self.assertIsNone(SpinePreRenderer(root / "unknown", runtime=runtime).render_full_body(bundle, "4.1"))
            self.assertEqual(runtime.calls, [])

    def test_handle_job_writes_versioned_png_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = FakeRuntime()
            renderer = SpinePreRenderer(root / "cache", runtime=runtime)
            results: list[Image.Image | None] = []

            renderer.handle_job(
                SpineJob(
                    cache_key="c191_default_src_4.1_2.0",
                    character_id="c191",
                    runtime_version="4.1",
                    bundle=make_bundle(root),
                    callback=results.append,
                )
            )

            self.assertEqual(len(results), 1)
            self.assertIsNotNone(renderer.cached_portrait("c191_default_src_4.1_2.0"))

    def test_fetcher_downloads_allowed_bundle_and_rejects_scope_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fetcher = SpineBundleFetcher(root / "bundles")
            base = "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/l2d/c191/aim/c191_00"
            payloads = {
                ".skel": b"binary-skeleton",
                ".atlas": b"page.png\nsize: 64, 64\n",
                ".png": b"png-bytes",
            }

            def open_stream(_method, url, **_kwargs):
                context = MagicMock()
                response = MagicMock()
                response.iter_bytes.return_value = [payloads[Path(url).suffix]]
                context.__enter__.return_value = response
                return context

            with patch("astrbot_plugin_nikke.spine_prerenderer.httpx.stream", side_effect=open_stream):
                bundle = fetcher.fetch(
                    {"skel": base + ".skel", "atlas": base + ".atlas", "png": base + ".png"},
                    "c191_default",
                )

            self.assertTrue(all(path.is_file() for path in bundle.all_files()))
            with self.assertRaises(SpineRenderError):
                fetcher.fetch(
                    {"skel": "https://evil.example/l2d/c191.skel", "atlas": base + ".atlas", "png": base + ".png"},
                    "bad",
                )

    def test_bundle_mapping_rejects_invalid_texture_entries(self):
        with self.assertRaises(SpineRenderError):
            SpineBundle.from_mapping(
                {"skel": "sample.json", "atlas": "sample.atlas", "textures": ["page.png", 42]}
            )

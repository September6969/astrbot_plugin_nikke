# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

from astrbot_plugin_nikke.core.asset_manager import AssetManager
from astrbot_plugin_nikke.integrations.nikke_db.resource_store import NikkeDbResourceStore
from astrbot_plugin_nikke.integrations.spine.local_resolver import LocalSpineResolveError
from astrbot_plugin_nikke.integrations.spine.prerenderer import SpineBundle, SpineJob, SpinePreRenderer
from astrbot_plugin_nikke.integrations.spine.runtime_meta import SpineRuntimeMetadataStore


class SpineRuntimeCacheV2Tests(unittest.TestCase):
    def _bundle_files(self, root: Path, render_id: str = "c018") -> None:
        bundle = root / "l2d" / render_id
        bundle.mkdir(parents=True)
        (bundle / f"{render_id}_00.skel").write_bytes(b"header Spine 4.1.20\x00")
        (bundle / f"{render_id}_00.atlas").write_text(f"{render_id}_00.png\nsize: 2,2\n", encoding="utf-8")
        Image.new("RGBA", (2, 2), (255, 0, 0, 255)).save(bundle / f"{render_id}_00.png")

    def test_local_vendor_bundle_survives_index_and_resolves_real_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._bundle_files(root)
            (root / "index").mkdir()
            (root / "index" / "l2d.json").write_text(json.dumps([{"id": "c018", "version": 4.1}]), encoding="utf-8")
            store = NikkeDbResourceStore(root, remote=False)
            bundle = store.resolve_local("c018")
            self.assertEqual(bundle.runtime_version, "4.1")
            self.assertEqual(store.source_version("c018"), "4.1")

    def test_remote_bundle_is_written_atomically_and_then_local_first(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = NikkeDbResourceStore(root, remote=True)
            urls = {
                "skel": "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/l2d/c018/c018_00.skel",
                "atlas": "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/l2d/c018/c018_00.atlas",
                "png": "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/l2d/c018/c018_00.png",
            }
            payload = {
                "skel": b"header Spine 4.1.20\x00",
                "atlas": b"c018_00.png\nsize: 2,2\n",
            }
            image = io.BytesIO()
            Image.new("RGBA", (2, 2), (255, 0, 0, 255)).save(image, "PNG")
            payload["png"] = image.getvalue()

            class Response:
                def __init__(self, body):
                    self.body = body

                def __enter__(self):
                    return self

                def __exit__(self, *_):
                    return False

                def raise_for_status(self):
                    return None

                def iter_bytes(self):
                    yield self.body

            with patch("astrbot_plugin_nikke.integrations.nikke_db.resource_store.httpx.stream", side_effect=lambda method, url, **_: Response(payload[Path(url).suffix[1:]])):
                bundle = store.ensure_bundle("c018", urls, allow_remote=True)
            self.assertIsNotNone(bundle)
            self.assertEqual(bundle.runtime_version, "4.1")
            self.assertTrue((root / "l2d" / "c018" / "c018_00.skel").is_file())
            with patch("astrbot_plugin_nikke.integrations.nikke_db.resource_store.httpx.stream", side_effect=AssertionError("不应再次联网")):
                self.assertEqual(store.resolve_local("c018").runtime_version, "4.1")

    def test_runtime_metadata_requires_exact_pixels_and_writes_atomic_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = Image.new("RGBA", (4, 5), (1, 2, 3, 255))
            digest = hashlib.sha256(image.tobytes()).hexdigest()
            store = SpineRuntimeMetadataStore(root)
            record = {
                "render_id": "c018",
                "point": [2.0, 1.0],
                "pixel_sha256": digest,
                "image_size": [4, 5],
                "core_axis": {"available": True},
            }
            path = store.write_record("c018", record, image)
            self.assertTrue(path.is_file())
            self.assertEqual(store.read_records()["c018"]["pixel_sha256"], digest)
            with self.assertRaises(ValueError):
                store.write_record("c018", {**record, "pixel_sha256": "0" * 64}, image)

    def test_portrait_miss_returns_fallback_and_schedules_one_key(self):
        assets = Path(__file__).resolve().parents[1] / "assets"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index").mkdir(parents=True)
            (root / "index" / "l2d.json").write_text(json.dumps([{"id": "c018", "version": 4.1}]), encoding="utf-8")
            renderer = MagicMock()
            renderer.RENDERER_VERSION = "2.0"
            renderer.prerender_dir = root / "rendered"
            renderer.is_available.return_value = True
            renderer.cached_portrait.return_value = None
            seen = set()

            def enqueue(job):
                if job.cache_key in seen:
                    return False
                seen.add(job.cache_key)
                return True

            renderer.enqueue.side_effect = enqueue
            manager = AssetManager(
                root / "cache",
                assets,
                remote=False,
                spine_renderer=renderer,
                nikke_db_local_root=root,
            )
            try:
                first = manager.get_character_portrait("", "18")
                self.assertEqual(first.size, (600, 900))
                self.assertEqual(len(seen), 1)
                job = renderer.enqueue.call_args_list[0].args[0]
                self.assertEqual(job.character_id, "c018")
                self.assertEqual(job.animation, "idle")
                runtime_version = manager.nikke_db.resolve_spine_version("c018", allow_remote=False)
                source_version = manager.nikke_db.source_version("c018", allow_remote=False)
                cache_key = manager.nikke_db.compute_cache_key(
                    "c018", None, source_version=source_version, runtime_version=str(runtime_version),
                    renderer_version=renderer.RENDERER_VERSION, animation="idle",
                )
                manager.spine_runtime_cache_dir.mkdir(parents=True, exist_ok=True)
                Image.new("RGBA", (31, 41), "purple").save(manager.spine_runtime_cache_dir / f"{cache_key}.png")
                second = manager.get_character_portrait("", "18")
                self.assertEqual(second.size, (31, 41))
                self.assertEqual(renderer.enqueue.call_count, 1)
            finally:
                manager.close()

    def test_background_job_resolves_version_writes_index_and_calls_metadata_hook(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle_root = root / "bundle"
            bundle_root.mkdir()
            skeleton = bundle_root / "c018.skel"
            atlas = bundle_root / "c018.atlas"
            texture = bundle_root / "c018.png"
            skeleton.write_bytes(b"skeleton")
            atlas.write_text("c018.png\n", encoding="utf-8")
            Image.new("RGBA", (2, 2), "red").save(texture)
            bundle = SpineBundle(skeleton, atlas, (texture,))

            class Runtime:
                version = "4.1"

            resolved = type("Resolved", (), {"runtime_version": "4.1", "as_spine_bundle": lambda self: bundle})()
            written: list[str] = []
            renderer = SpinePreRenderer(root / "cache", runtime=Runtime())
            renderer.bundle_resolver = lambda job: resolved
            renderer.render_full_body = lambda *args, **kwargs: Image.new("RGBA", (3, 4), "blue")
            renderer.metadata_writer = lambda job, actual_bundle, image: written.append(job.character_id)
            job = SpineJob(
                cache_key="c018_default_4.1_4.1_2.0_idle",
                character_id="c018",
                runtime_version=None,
                bundle_urls={"skel": "https://example.invalid/s", "atlas": "https://example.invalid/a", "png": "https://example.invalid/p"},
            )
            self.assertTrue(renderer.enqueue(job))
            self.assertTrue(renderer.queue.wait_idle(2.0))
            renderer.close()
            self.assertEqual(written, ["c018"])
            index = json.loads((root / "cache" / "portraits" / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(index["c018"]["runtime_version"], "4.1")


if __name__ == "__main__":
    unittest.main()

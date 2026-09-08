"""官方 worker 适配器的边界测试；不要求本机安装 Spine runtime。"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from PIL import Image

from astrbot_plugin_nikke import spine_runtime_worker as worker_module
from astrbot_plugin_nikke.spine_prerenderer import SpineBundle, SpineRenderError
from astrbot_plugin_nikke.spine_runtime_worker import SpineWorkerConfig, SpineWorkerRuntime


class SpineWorkerRuntimeTests(TestCase):
    def _bundle(self, root: Path) -> SpineBundle:
        skeleton = root / "c191.skel"
        atlas = root / "c191.atlas"
        texture = root / "c191.png"
        skeleton.write_bytes(b"skeleton")
        atlas.write_text("c191.png\n", encoding="utf-8")
        Image.new("RGBA", (2, 2), (255, 0, 0, 255)).save(texture)
        return SpineBundle(skeleton=skeleton, atlas=atlas, textures=(texture,))

    def test_worker_reads_bounded_rgba_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self._bundle(root)
            config = SpineWorkerConfig(Path("worker"), root, width=2, height=2)
            runtime = SpineWorkerRuntime(config)

            def run(command, **kwargs):
                output = Path(command[command.index("--output") + 1])
                output.write_bytes((2).to_bytes(4, "little") + (1).to_bytes(4, "little") + bytes([1, 2, 3, 255] * 2))
                return type("Completed", (), {"returncode": 0, "stdout": json.dumps({"status": "ok"})})()

            with patch.object(worker_module.subprocess, "run", side_effect=run):
                image = runtime.render(bundle, animation="idle", skin="default")
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.size, (2, 1))

    def test_worker_rejects_bundle_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root.parent / "outside.skel"
            outside.write_bytes(b"x")
            bundle = SpineBundle(outside, root / "a.atlas", (root / "a.png",))
            runtime = SpineWorkerRuntime(SpineWorkerConfig(Path("worker"), root))
            with self.assertRaises(SpineRenderError):
                runtime.render(bundle, animation="idle")

    def test_worker_rejects_malformed_rgba(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self._bundle(root)
            runtime = SpineWorkerRuntime(SpineWorkerConfig(Path("worker"), root))

            def run(command, **kwargs):
                output = Path(command[command.index("--output") + 1])
                output.write_bytes(b"bad")
                return type("Completed", (), {"returncode": 0, "stdout": json.dumps({"status": "ok"})})()

            with patch.object(worker_module.subprocess, "run", side_effect=run):
                with self.assertRaises(SpineRenderError):
                    runtime.render(bundle, animation="idle")

    def test_worker_timeout_is_a_render_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self._bundle(root)
            runtime = SpineWorkerRuntime(SpineWorkerConfig(Path("worker"), root))

            from subprocess import TimeoutExpired

            with patch.object(worker_module.subprocess, "run", side_effect=TimeoutExpired("worker", 1)):
                with self.assertRaisesRegex(SpineRenderError, "超时"):
                    runtime.render(bundle, animation="idle")

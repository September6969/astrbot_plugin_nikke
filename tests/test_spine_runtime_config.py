"""Spine worker 配置接线测试。"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from unittest import TestCase

from astrbot_plugin_nikke.integrations.spine.config import build_spine_renderer


class SpineRuntimeConfigTests(TestCase):
    def test_readme_documents_the_pinned_four_zero_worker_commit(self) -> None:
        root = Path(__file__).resolve().parents[1] / "runtime" / "spine_worker"
        dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
        readme = (root / "README.md").read_text(encoding="utf-8")
        docker_commit = re.search(r"ARG SPINE_COMMIT=([0-9a-f]{40})", dockerfile)
        readme_commit = re.search(r"runtime commit `([0-9a-f]{40})`", readme)
        self.assertIsNotNone(docker_commit)
        self.assertIsNotNone(readme_commit)
        self.assertEqual(docker_commit.group(1), readme_commit.group(1))

    def test_empty_path_keeps_static_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            renderer = build_spine_renderer(directory, {})
            self.assertIsNone(renderer.runtime)
            renderer.close()

    def test_missing_worker_keeps_static_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            renderer = build_spine_renderer(directory, {"spine_worker_path": str(Path(directory) / "missing")})
            self.assertIsNone(renderer.runtime)
            renderer.close()

    def test_existing_worker_uses_shared_bundle_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            worker = Path(directory) / "worker"
            worker.write_bytes(b"worker")
            renderer = build_spine_renderer(
                directory,
                {"spine_worker_path": str(worker), "spine_runtime_version": "4.1", "spine_worker_timeout": 5},
            )
            self.assertIsNotNone(renderer.runtime)
            self.assertEqual(renderer.runtime.version, "4.1")
            self.assertEqual(renderer.fetcher.cache_dir, Path(directory) / "spine-bundles")
            renderer.close()

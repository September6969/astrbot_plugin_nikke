"""Spine 技术预研的队列、预算和证据边界行为测试。"""

import tempfile
import threading
from pathlib import Path
from unittest import TestCase

from astrbot_plugin_nikke.spine_prerenderer import (
    SPINE_VERSION_UNKNOWN,
    SpineJob,
    SpinePreRenderer,
    SpineTaskQueue,
)


class SpineTaskQueueTests(TestCase):
    def test_deduplicates_and_runs_a_job(self):
        queue = SpineTaskQueue(max_workers=1, max_queue_size=2)
        entered = threading.Event()
        release = threading.Event()
        completed: list[str] = []

        def runner(job: SpineJob) -> None:
            entered.set()
            release.wait(timeout=2)
            completed.append(job.cache_key)

        queue.start(runner)
        try:
            job = SpineJob("same", "c101", "4.1")
            self.assertTrue(queue.enqueue(job))
            self.assertTrue(entered.wait(timeout=2))
            self.assertFalse(queue.enqueue(SpineJob("same", "c101", "4.1")))
            release.set()
            self.assertTrue(queue.wait_idle(timeout=2))
            self.assertEqual(completed, ["same"])
            self.assertEqual(queue.pending_count, 0)
        finally:
            queue.stop()
        self.assertFalse(queue.is_running)

    def test_rejects_when_the_bounded_queue_is_full(self):
        queue = SpineTaskQueue(max_workers=1, max_queue_size=1)
        entered = threading.Event()
        release = threading.Event()

        def runner(_job: SpineJob) -> None:
            entered.set()
            release.wait(timeout=2)

        queue.start(runner)
        try:
            self.assertTrue(queue.enqueue(SpineJob("running", "c1", "4.1")))
            self.assertTrue(entered.wait(timeout=2))
            self.assertTrue(queue.enqueue(SpineJob("queued", "c2", "4.1")))
            self.assertFalse(queue.enqueue(SpineJob("overflow", "c3", "4.1")))
            release.set()
            self.assertTrue(queue.wait_idle(timeout=2))
        finally:
            queue.stop()

    def test_total_budget_includes_queue_wait(self):
        queue = SpineTaskQueue(max_workers=1)
        executed: list[str] = []
        callbacks: list[object] = []

        queue.start(lambda job: executed.append(job.cache_key))
        try:
            job = SpineJob(
                "expired",
                "c101",
                "4.1",
                callback=lambda image: callbacks.append(image),
                budget_seconds=0.1,
            )
            # 不使用 sleep 制造竞态，直接模拟任务已在队列中等待了一段时间。
            job.enqueued_at -= 1
            self.assertTrue(queue.enqueue(job))
            self.assertTrue(queue.wait_idle(timeout=2))
            self.assertEqual(executed, [])
            self.assertEqual(callbacks, [None])
        finally:
            queue.stop()

    def test_rejects_invalid_budget(self):
        with self.assertRaises(ValueError):
            SpineJob("bad", "c101", "4.1", budget_seconds=0)
        with self.assertRaises(ValueError):
            SpineJob("bad", "c101", "4.1", budget_seconds=True)
        with self.assertRaises(ValueError):
            SpineJob("bad", "c101", "4.1", budget_seconds="1")

    def test_rejects_invalid_job_identity_and_cache_path(self):
        for cache_key in ("", "  ", "../escape", "nested/key", "nested\\key", "C:escape"):
            with self.subTest(cache_key=cache_key):
                with self.assertRaises(ValueError):
                    SpineJob(cache_key, "c101", "4.1")
        with self.assertRaises(ValueError):
            SpineJob("safe", "", "4.1")
        with self.assertRaises(ValueError):
            SpineJob("safe", "c101", True)

    def test_rejects_non_integer_queue_limits(self):
        for kwargs in (
            {"max_workers": True},
            {"max_workers": 1.5},
            {"max_queue_size": False},
            {"max_queue_size": 2.5},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    SpineTaskQueue(**kwargs)


class SpineEvidenceTests(TestCase):
    def test_preflight_keeps_unverified_evidence_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            atlas = root / "sample.atlas"
            skeleton = root / "sample.json"
            atlas.write_text("page.png\nsize: 10, 20\n", encoding="utf-8")
            skeleton.write_text('{"skeleton":{"spine":"4.1.24"}}', encoding="utf-8")

            renderer = SpinePreRenderer(root / "cache")
            report = renderer.inspect_bundle(atlas, skeleton, "4.1")

            self.assertEqual(report.status, "VERSION_MATCH")
            self.assertEqual(report.resource_discovery, "LOCAL_INPUT_ONLY")
            self.assertEqual(report.bundle_integrity, "PASS")
            self.assertEqual(report.spine_version, "4.1")
            self.assertEqual(report.runtime_compatibility, "NOT_EXECUTED")
            self.assertEqual(report.legal_test_asset, "NOT_VERIFIED")
            self.assertEqual(report.render_verified, "NOT_EXECUTED")
            self.assertEqual(report.benchmark, "NOT_EXECUTED")
            self.assertEqual(report.as_dict()["render_verified"], "NOT_EXECUTED")

    def test_invalid_preflight_is_not_a_runtime_failure_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            atlas = root / "sample.atlas"
            skeleton = root / "sample.json"
            atlas.write_text("page.png\nsize: 10, 20\n", encoding="utf-8")
            skeleton.write_text("{}", encoding="utf-8")

            report = SpinePreRenderer(root / "cache").inspect_bundle(atlas, skeleton, "4")

            self.assertEqual(report.status, "INSPECTION_FAILED")
            self.assertEqual(report.bundle_integrity, "FAIL")
            self.assertEqual(report.runtime_compatibility, "NOT_EXECUTED")
            self.assertEqual(report.render_verified, "NOT_EXECUTED")

    def test_explicit_start_handles_unknown_version_with_fallback_callback(self):
        with tempfile.TemporaryDirectory() as directory:
            renderer = SpinePreRenderer(directory)
            callbacks: list[object] = []
            renderer.start()
            try:
                self.assertTrue(
                    renderer.queue.enqueue(
                        SpineJob(
                            "unknown",
                            "c101",
                            SPINE_VERSION_UNKNOWN,
                            callback=lambda image: callbacks.append(image),
                        )
                    )
                )
                self.assertTrue(renderer.queue.wait_idle(timeout=2))
                self.assertEqual(callbacks, [None])
            finally:
                renderer.close()
            self.assertFalse(renderer.queue.is_running)

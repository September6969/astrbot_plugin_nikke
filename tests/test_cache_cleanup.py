# SPDX-License-Identifier: GPL-3.0-or-later

import os
import tempfile
import time
import unittest
from pathlib import Path

from astrbot_plugin_nikke.scripts.operations.cleanup_cache import (
    CacheCandidate,
    CleanupPlan,
    apply_cleanup,
    build_cleanup_plan,
)


class CacheCleanupTests(unittest.TestCase):
    def _write_file(self, path: Path, age_hours: float, content: bytes = b"cache") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        stamp = time.time() - age_hours * 3600
        os.utime(path, (stamp, stamp))

    def test_plan_is_read_only_and_only_scans_known_cache_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_file(root / "cache" / "old.png", 48)
            self._write_file(root / "cache" / "new.png", 1)
            self._write_file(root / "voice_cache" / "old.mp3", 48)
            self._write_file(root / "announcements" / "announcements_cache.json", 48)
            self._write_file(root / "cards" / "old.png", 48)
            self._write_file(root / "nikke.sqlite3", 48)
            self._write_file(root / "secret.key", 48)

            plan = build_cleanup_plan(root, older_than_hours=24, temp_older_than_hours=1)

            # PR-6B G7-misc-dead-f1：announcements_cache.json 保存公告版本状态，不再属于默认清理。
            self.assertEqual(
                [item.relative_path for item in plan.candidates],
                [
                    "cache/old.png",
                    "voice_cache/old.mp3",
                ],
            )
            opt_in = build_cleanup_plan(
                root, older_than_hours=24, temp_older_than_hours=1, include_announcement_state=True
            )
            self.assertIn(
                "announcements/announcements_cache.json",
                [item.relative_path for item in opt_in.candidates],
            )
            self.assertTrue((root / "cache" / "old.png").is_file())
            self.assertTrue((root / "cards" / "old.png").is_file())
            self.assertTrue((root / "nikke.sqlite3").is_file())
            self.assertTrue((root / "secret.key").is_file())

    def test_apply_removes_stale_cache_and_temporary_files_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_file(root / "cache" / "stale.png", 48)
            self._write_file(root / "cache" / "orphan.tmp", 2)
            self._write_file(root / "cache" / "fresh.png", 0)
            self._write_file(root / "cards" / "stale.png", 48)
            self._write_file(root / "nikke.sqlite3", 48)
            self._write_file(root / "secret.key", 48)

            result = apply_cleanup(build_cleanup_plan(root, older_than_hours=24, temp_older_than_hours=1))

            self.assertEqual(result["removed_count"], 2)
            self.assertFalse((root / "cache" / "stale.png").exists())
            self.assertFalse((root / "cache" / "orphan.tmp").exists())
            self.assertTrue((root / "cache" / "fresh.png").is_file())
            self.assertTrue((root / "cards" / "stale.png").is_file())
            self.assertTrue((root / "nikke.sqlite3").is_file())
            self.assertTrue((root / "secret.key").is_file())

    def test_symlinked_cache_entries_are_not_followed(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside:
            root = Path(td)
            external = Path(outside) / "external.png"
            self._write_file(external, 48)
            link = root / "cache" / "external.png"
            link.parent.mkdir(parents=True)
            try:
                link.symlink_to(external)
            except (OSError, NotImplementedError):
                self.skipTest("当前 Windows 环境不允许创建符号链接")

            plan = build_cleanup_plan(root, older_than_hours=24)
            result = apply_cleanup(plan)

            self.assertEqual(plan.candidates, ())
            self.assertEqual(result["removed_count"], 0)
            self.assertTrue(external.is_file())

    def test_symlinked_data_root_is_not_followed(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside:
            target = Path(outside)
            self._write_file(target / "cache" / "external.png", 48)
            link = Path(td) / "data-link"
            try:
                link.symlink_to(target, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("当前 Windows 环境不允许创建目录符号链接")

            plan = build_cleanup_plan(link, older_than_hours=24)
            result = apply_cleanup(plan)

            self.assertEqual(plan.candidates, ())
            self.assertEqual(plan.skipped_symlinks, 1)
            self.assertEqual(result["removed_count"], 0)
            self.assertTrue((target / "cache" / "external.png").is_file())

            synthetic_plan = CleanupPlan(
                link,
                (CacheCandidate("cache/external.png", 48, "synthetic"),),
            )
            synthetic_result = apply_cleanup(synthetic_plan)
            self.assertEqual(synthetic_result["removed_count"], 0)
            self.assertEqual(synthetic_result["skipped"], ["cache/external.png"])
            self.assertTrue((target / "cache" / "external.png").is_file())

    def test_apply_rechecks_whitelist_and_protected_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_file(root / "nikke.sqlite3", 48)
            self._write_file(root / "other.txt", 48)
            plan = CleanupPlan(
                root,
                (
                    CacheCandidate("nikke.sqlite3", 1, "synthetic"),
                    CacheCandidate("other.txt", 1, "synthetic"),
                    CacheCandidate("cache/../other.txt", 1, "synthetic"),
                ),
            )

            result = apply_cleanup(plan)

            self.assertEqual(result["removed_count"], 0)
            self.assertEqual(len(result["skipped"]), 3)
            self.assertTrue((root / "nikke.sqlite3").is_file())
            self.assertTrue((root / "other.txt").is_file())

    def test_non_finite_retention_values_are_rejected(self):
        for value in (-1, float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    build_cleanup_plan(tempfile.gettempdir(), older_than_hours=value)


if __name__ == "__main__":
    unittest.main()


class CacheCleanupHardeningTests(unittest.TestCase):
    """PR-6B G7-misc-dead-f1：塔罗倒置图、临时文件模式、回退缓存与状态文件边界。"""

    def _write_file(self, path: Path, age_hours: float, content: bytes = b"cache") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        stamp = time.time() - age_hours * 3600
        os.utime(path, (stamp, stamp))

    def _plan(self, root: Path, **kwargs):
        return [item.relative_path for item in build_cleanup_plan(
            root, older_than_hours=24, temp_older_than_hours=1, **kwargs
        ).candidates]

    def test_tarot_reversed_cache_is_pattern_gated_and_daily_state_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_file(root / "tarot" / "reversed_cache" / "major_00_reversed_0123456789ab.png", 48)
            self._write_file(root / "tarot" / "reversed_cache" / "major_01_reversed_0123456789ab.tmp.png", 2)
            self._write_file(root / "tarot" / "reversed_cache" / "unexpected.png", 48)
            self._write_file(root / "tarot" / "reversed_cache" / "nested" / "x_reversed_0123456789ab.png", 48)
            self._write_file(root / "tarot" / "daily_draws.json", 48)

            self.assertEqual(self._plan(root), [
                "tarot/reversed_cache/major_00_reversed_0123456789ab.png",
                "tarot/reversed_cache/major_01_reversed_0123456789ab.tmp.png",
            ])
            apply_cleanup(build_cleanup_plan(root, older_than_hours=24, temp_older_than_hours=1))
            self.assertTrue((root / "tarot" / "daily_draws.json").is_file())
            self.assertTrue((root / "tarot" / "reversed_cache" / "unexpected.png").is_file())

    def test_temporary_name_patterns_use_short_retention(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in (".tmp.0a1b.wav", ".tmp-download", "file.tmp", "worker.tmp.json"):
                self._write_file(root / "voice_cache" / name, 2)
            self._write_file(root / "cache" / ".spine-worker-abc.rgba", 2)
            self._write_file(root / "cache" / "fresh-normal.png", 2)
            plan = build_cleanup_plan(root, older_than_hours=24, temp_older_than_hours=1)
            reasons = {item.relative_path: item.reason for item in plan.candidates}
            self.assertEqual(set(reasons.values()), {"stale_temporary"})
            self.assertIn("cache/.spine-worker-abc.rgba", reasons)
            self.assertNotIn("cache/fresh-normal.png", reasons)
            self.assertEqual(len(reasons), 5)

    def test_fallback_caches_are_protected_unless_opted_in(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fallback = [
                "cache/character-stats/stats.json",
                "cache/nikke-db/index/l2d.json",
                "cache/spine-manifest.json",
                "cache/spine_manifest.json",
                "cache/portraits/c010.png",
                "cache/spine-bundles/c010/c010_00.skel",
            ]
            for relative in fallback:
                self._write_file(root / relative, 48)
            self._write_file(root / "cache" / "images" / "old.webp", 48)

            self.assertEqual(self._plan(root), ["cache/images/old.webp"])
            self.assertEqual(
                self._plan(root, include_fallback_caches=True),
                sorted(fallback + ["cache/images/old.webp"]),
            )
            # 默认计划下应用阶段同样拒绝回退缓存，即使伪造进计划。
            forged = CleanupPlan(root, tuple(CacheCandidate(path, 1, "synthetic") for path in fallback))
            result = apply_cleanup(forged)
            self.assertEqual(result["removed_count"], 0)
            self.assertTrue(all((root / path).is_file() for path in fallback))

    def test_state_files_outside_cache_directories_are_never_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for relative in (
                "calendar/schedule_events.json",
                "calendar/visual_cache.json",
                "spine-manifest.json",
                "spine-rendered/c010.png",
                "arena-history.json",
            ):
                self._write_file(root / relative, 480)
            self.assertEqual(self._plan(root, include_fallback_caches=True, include_announcement_state=True), [])


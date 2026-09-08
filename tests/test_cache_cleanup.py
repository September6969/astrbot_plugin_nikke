# SPDX-License-Identifier: GPL-3.0-or-later

import os
import tempfile
import time
import unittest
from pathlib import Path

from astrbot_plugin_nikke.scripts.cleanup_cache import (
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

            self.assertEqual(
                [item.relative_path for item in plan.candidates],
                [
                    "announcements/announcements_cache.json",
                    "cache/old.png",
                    "voice_cache/old.mp3",
                ],
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

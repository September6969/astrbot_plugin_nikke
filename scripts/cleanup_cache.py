# SPDX-License-Identifier: GPL-3.0-or-later
"""安全清理 NIKKE 本地缓存；默认只生成清理计划，不删除文件。"""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path


CACHE_DIRECTORIES = ("cache", "voice_cache")
ANNOUNCEMENT_CACHE = Path("announcements") / "announcements_cache.json"
ANNOUNCEMENT_TEMP = Path("announcements") / "announcements_cache.tmp"
PROTECTED_PATHS = {
    Path("nikke.sqlite3"),
    Path("secret.key"),
    Path("cards"),
    Path("nikke-bind-extension.zip"),
}


@dataclass(frozen=True)
class CacheCandidate:
    relative_path: str
    size: int
    reason: str


@dataclass(frozen=True)
class CleanupPlan:
    data_dir: Path
    candidates: tuple[CacheCandidate, ...]
    skipped_symlinks: int = 0

    def as_dict(self) -> dict:
        return {
            "mode": "PLAN",
            "data_dir": str(self.data_dir),
            "candidate_count": len(self.candidates),
            "candidate_bytes": sum(item.size for item in self.candidates),
            "skipped_symlinks": self.skipped_symlinks,
            "candidates": [asdict(item) for item in self.candidates],
        }


def _resolved_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def _is_protected(relative_path: Path) -> bool:
    return relative_path == Path("nikke.sqlite3") or relative_path == Path("secret.key") or any(
        relative_path == protected or protected in relative_path.parents
        for protected in PROTECTED_PATHS
    )


def _is_allowed_target(relative_path: Path) -> bool:
    """只允许白名单缓存目录中的文件或两个公告缓存文件。"""
    if relative_path.is_absolute() or any(part in {"", ".", ".."} for part in relative_path.parts):
        return False
    if relative_path in {ANNOUNCEMENT_CACHE, ANNOUNCEMENT_TEMP}:
        return True
    return len(relative_path.parts) >= 2 and relative_path.parts[0] in CACHE_DIRECTORIES


def _finite_nonnegative(value: object, label: str) -> float:
    """校验保留时长等数值，拒绝负数、NaN 和无穷大。"""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label}必须是有限非负数") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{label}必须是有限非负数")
    return number


def _candidate(path: Path, data_dir: Path, cutoff: float, reason: str) -> CacheCandidate | None:
    if path.is_symlink() or not path.is_file():
        return None
    relative = path.relative_to(data_dir)
    if not _is_allowed_target(relative) or _is_protected(relative) or not _resolved_inside(path, data_dir):
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    if stat.st_mtime >= cutoff:
        return None
    return CacheCandidate(relative.as_posix(), stat.st_size, reason)


def build_cleanup_plan(
    data_dir: str | Path,
    *,
    now: float | None = None,
    older_than_hours: float = 30 * 24,
    temp_older_than_hours: float = 1,
) -> CleanupPlan:
    """扫描白名单缓存，返回只读清理计划。"""

    cache_hours = _finite_nonnegative(older_than_hours, "普通缓存保留时长")
    temp_hours = _finite_nonnegative(temp_older_than_hours, "临时文件保留时长")
    base = Path(data_dir).expanduser()
    if base.is_symlink():
        return CleanupPlan(base, (), skipped_symlinks=1)
    current = time.time() if now is None else _finite_nonnegative(now, "当前时间")
    cache_cutoff = current - cache_hours * 3600
    temp_cutoff = current - temp_hours * 3600
    candidates: list[CacheCandidate] = []
    skipped_symlinks = 0

    for directory in CACHE_DIRECTORIES:
        root = base / directory
        if root.is_symlink():
            skipped_symlinks += 1
            continue
        if not root.is_dir() or not _resolved_inside(root, base):
            continue
        for path in root.rglob("*"):
            if path.is_symlink():
                skipped_symlinks += 1
                continue
            is_temporary = path.suffix.lower() == ".tmp"
            cutoff = temp_cutoff if is_temporary else cache_cutoff
            reason = "stale_temporary" if is_temporary else "stale_cache"
            item = _candidate(path, base, cutoff, reason)
            if item is not None:
                candidates.append(item)

    for relative, reason in (
        (ANNOUNCEMENT_CACHE, "stale_announcement_cache"),
        (ANNOUNCEMENT_TEMP, "stale_temporary"),
    ):
        path = base / relative
        item = _candidate(path, base, temp_cutoff if relative == ANNOUNCEMENT_TEMP else cache_cutoff, reason)
        if item is not None:
            candidates.append(item)

    candidates.sort(key=lambda item: item.relative_path)
    return CleanupPlan(base, tuple(candidates), skipped_symlinks)


def apply_cleanup(plan: CleanupPlan) -> dict:
    """按已生成计划逐文件清理；竞态、符号链接和越界路径均跳过。"""

    removed: list[str] = []
    skipped: list[str] = []
    errors: list[dict[str, str]] = []
    if plan.data_dir.is_symlink():
        skipped.extend(item.relative_path for item in plan.candidates)
        return {
            "mode": "APPLY",
            "data_dir": str(plan.data_dir),
            "planned_count": len(plan.candidates),
            "planned_bytes": sum(item.size for item in plan.candidates),
            "removed_count": 0,
            "removed_bytes": 0,
            "skipped": skipped,
            "errors": errors,
        }
    for item in plan.candidates:
        relative = Path(item.relative_path)
        if not _is_allowed_target(relative) or _is_protected(relative):
            skipped.append(item.relative_path)
            continue
        path = plan.data_dir / relative
        if path.is_symlink() or not path.is_file() or not _resolved_inside(path, plan.data_dir):
            skipped.append(item.relative_path)
            continue
        try:
            path.unlink()
            removed.append(item.relative_path)
        except OSError as exc:
            errors.append({"path": item.relative_path, "error_type": type(exc).__name__})
    return {
        "mode": "APPLY",
        "data_dir": str(plan.data_dir),
        "planned_count": len(plan.candidates),
        "planned_bytes": sum(item.size for item in plan.candidates),
        "removed_count": len(removed),
        "removed_bytes": sum(item.size for item in plan.candidates if item.relative_path in removed),
        "skipped": skipped,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True, help="AstrBot 的 data/nikke 目录")
    parser.add_argument("--older-than-hours", type=float, default=30 * 24)
    parser.add_argument("--temp-older-than-hours", type=float, default=1)
    parser.add_argument("--apply", action="store_true", help="确认后删除计划内文件；默认只预览")
    args = parser.parse_args()
    try:
        plan = build_cleanup_plan(
            args.data_dir,
            older_than_hours=args.older_than_hours,
            temp_older_than_hours=args.temp_older_than_hours,
        )
        result = apply_cleanup(plan) if args.apply else plan.as_dict()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get("errors"):
            raise SystemExit(1)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""安全清理 NIKKE 本地缓存；默认只生成清理计划，不删除文件。

离线运维工具：--apply 前须停止插件。PR-6B（G7-misc-dead-f1）加固：
- 默认范围：cache/、voice_cache/ 中的陈旧缓存与临时文件，tarot/reversed_cache 中
  严格命名的倒置图缓存（*_reversed_<12位十六进制>.png）及其临时文件，以及公告缓存的 .tmp；
- 回退缓存（角色统计离线回退、Nikke-DB 索引、旧 Spine 清单、运行时 Spine 立绘与
  bundle 下载）默认受保护，只有 --include-fallback-caches 才纳入；
- announcements_cache.json 保存公告版本历史与去重状态，不再属于默认清理，只有
  --include-announcement-state 才纳入（删除可能导致合法的公告更新提醒被抑制）；
- tarot/daily_draws.json、calendar/、spine-rendered/、spine-manifest.json 等状态文件
  永不纳入。
"""

from __future__ import annotations

# 支持直接执行、模块导入及从其他工作目录调用。
import sys as _bootstrap_sys
from pathlib import Path as _BootstrapPath
_bootstrap_root = _BootstrapPath(__file__).resolve().parents[2]
for _bootstrap_path in (_bootstrap_root.parent, _bootstrap_root):
    if str(_bootstrap_path) not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, str(_bootstrap_path))


import argparse
import json
import math
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path


CACHE_DIRECTORIES = ("cache", "voice_cache")
TAROT_REVERSED_CACHE = Path("tarot") / "reversed_cache"
# integrations/tarot/images.py：<card>_reversed_<sha256[:12]>.png，临时文件为 .tmp.png。
TAROT_REVERSED_NAME = re.compile(r"[A-Za-z0-9_.-]+_reversed_[0-9a-f]{12}(?:\.tmp)?\.png")
ANNOUNCEMENT_CACHE = Path("announcements") / "announcements_cache.json"
ANNOUNCEMENT_TEMP = Path("announcements") / "announcements_cache.tmp"
# 离线回退或运行中可能被使用的缓存：默认保护，--include-fallback-caches 才纳入。
FALLBACK_CACHE_PATHS = (
    Path("cache") / "character-stats",
    Path("cache") / "nikke-db" / "index",
    Path("cache") / "spine-manifest.json",
    Path("cache") / "spine_manifest.json",
    Path("cache") / "portraits",
    Path("cache") / "spine-bundles",
)
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
    include_fallback_caches: bool = False
    include_announcement_state: bool = False

    def as_dict(self) -> dict:
        return {
            "mode": "PLAN",
            "data_dir": str(self.data_dir),
            "candidate_count": len(self.candidates),
            "candidate_bytes": sum(item.size for item in self.candidates),
            "skipped_symlinks": self.skipped_symlinks,
            "include_fallback_caches": self.include_fallback_caches,
            "include_announcement_state": self.include_announcement_state,
            "candidates": [asdict(item) for item in self.candidates],
        }


def _resolved_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def _is_temporary_name(name: str) -> bool:
    """与 core/health.py 的临时文件判定一致，并补充 Spine worker 的 RGBA 临时输出。"""
    return (
        name.endswith(".tmp")
        or name.startswith(".tmp-")
        or ".tmp." in name
        or (name.startswith(".spine-worker-") and name.endswith(".rgba"))
    )


def _is_fallback_cache(relative_path: Path) -> bool:
    return any(
        relative_path == fallback or fallback in relative_path.parents
        for fallback in FALLBACK_CACHE_PATHS
    )


def _is_tarot_reversed(relative_path: Path) -> bool:
    return (
        relative_path.parent == TAROT_REVERSED_CACHE
        and TAROT_REVERSED_NAME.fullmatch(relative_path.name) is not None
    )


def _is_protected(relative_path: Path) -> bool:
    return relative_path == Path("nikke.sqlite3") or relative_path == Path("secret.key") or any(
        relative_path == protected or protected in relative_path.parents
        for protected in PROTECTED_PATHS
    )


def _is_allowed_target(
    relative_path: Path,
    *,
    include_fallback_caches: bool = False,
    include_announcement_state: bool = False,
) -> bool:
    """只允许白名单缓存目录、严格命名的塔罗倒置图与公告缓存临时文件。"""
    if relative_path.is_absolute() or any(part in {"", ".", ".."} for part in relative_path.parts):
        return False
    if relative_path == ANNOUNCEMENT_TEMP:
        return True
    if relative_path == ANNOUNCEMENT_CACHE:
        return include_announcement_state
    if _is_tarot_reversed(relative_path):
        return True
    if len(relative_path.parts) < 2 or relative_path.parts[0] not in CACHE_DIRECTORIES:
        return False
    return include_fallback_caches or not _is_fallback_cache(relative_path)


def _finite_nonnegative(value: object, label: str) -> float:
    """校验保留时长等数值，拒绝负数、NaN 和无穷大。"""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label}必须是有限非负数") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{label}必须是有限非负数")
    return number


def _candidate(
    path: Path, data_dir: Path, cutoff: float, reason: str, **scope: bool
) -> CacheCandidate | None:
    if path.is_symlink() or not path.is_file():
        return None
    relative = path.relative_to(data_dir)
    if not _is_allowed_target(relative, **scope) or _is_protected(relative) or not _resolved_inside(path, data_dir):
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
    include_fallback_caches: bool = False,
    include_announcement_state: bool = False,
) -> CleanupPlan:
    """扫描白名单缓存，返回只读清理计划。"""
    scope = {
        "include_fallback_caches": bool(include_fallback_caches),
        "include_announcement_state": bool(include_announcement_state),
    }

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

    for directory in (*CACHE_DIRECTORIES, TAROT_REVERSED_CACHE):
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
            is_temporary = _is_temporary_name(path.name)
            cutoff = temp_cutoff if is_temporary else cache_cutoff
            reason = "stale_temporary" if is_temporary else "stale_cache"
            item = _candidate(path, base, cutoff, reason, **scope)
            if item is not None:
                candidates.append(item)

    for relative, reason in (
        (ANNOUNCEMENT_CACHE, "stale_announcement_cache"),
        (ANNOUNCEMENT_TEMP, "stale_temporary"),
    ):
        path = base / relative
        item = _candidate(
            path, base, temp_cutoff if relative == ANNOUNCEMENT_TEMP else cache_cutoff, reason, **scope
        )
        if item is not None:
            candidates.append(item)

    candidates.sort(key=lambda item: item.relative_path)
    return CleanupPlan(base, tuple(candidates), skipped_symlinks, **scope)


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
        allowed = _is_allowed_target(
            relative,
            include_fallback_caches=plan.include_fallback_caches,
            include_announcement_state=plan.include_announcement_state,
        )
        if not allowed or _is_protected(relative):
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
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, required=True, help="AstrBot 的 data/nikke 目录")
    parser.add_argument("--older-than-hours", type=float, default=30 * 24)
    parser.add_argument("--temp-older-than-hours", type=float, default=1)
    parser.add_argument(
        "--include-fallback-caches",
        action="store_true",
        help="同时纳入角色统计离线回退、Nikke-DB 索引、旧 Spine 清单与运行时 Spine 缓存",
    )
    parser.add_argument(
        "--include-announcement-state",
        action="store_true",
        help="同时纳入 announcements_cache.json（含版本历史与去重状态，删除可能抑制公告更新提醒）",
    )
    parser.add_argument("--apply", action="store_true", help="停止插件后确认删除计划内文件；默认只预览")
    args = parser.parse_args()
    try:
        plan = build_cleanup_plan(
            args.data_dir,
            older_than_hours=args.older_than_hours,
            temp_older_than_hours=args.temp_older_than_hours,
            include_fallback_caches=args.include_fallback_caches,
            include_announcement_state=args.include_announcement_state,
        )
        result = apply_cleanup(plan) if args.apply else plan.as_dict()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get("errors"):
            raise SystemExit(1)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""从本地 Nikke-db checkout 维护 Spine idle@t=0 PNG 与 manifest v2。

本脚本是维护期工具：它不下载 raw GitHub 文件，也不应由 QQ 命令调用。
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT.parent))
try:
    from astrbot_plugin_nikke.local_spine_resolver import (
        LocalSpineBundle,
        LocalSpineBundleResolver,
        LocalSpineResolveError,
    )
except ImportError:
    from local_spine_resolver import (  # type: ignore[no-redef]
        LocalSpineBundle,
        LocalSpineBundleResolver,
        LocalSpineResolveError,
    )


DEFAULT_TARGETS = [
    "c010",
    "c010_02",
    "c010_03",
    "c330",
    "c017",
    "c471",
    "c234",
    "c352",
]
SOURCE_REPO = "https://github.com/Nikke-db/Nikke-db.github.io.git"
MANIFEST_SCHEMA_VERSION = 2
_ASSET_ID = re.compile(r"^c[0-9]+(?:_[0-9]+)?$", re.ASCII)


def detect_spine_version(skel_path: Path) -> str:
    """通过 skeleton 真实头部识别 4.0/4.1，不按角色或服装猜测。"""
    return LocalSpineBundleResolver.detect_runtime_version(skel_path)


def parse_atlas_texture_pages(atlas_path: Path) -> list[str]:
    """复用本地 resolver 的 UTF-8-SIG atlas 页面解析合同。"""
    return LocalSpineBundleResolver._atlas_pages(atlas_path)


def ensure_bundle(char_id: str, bundle_root: Path) -> tuple[Path, Path, list[Path]]:
    """确保本地 bundle 完整，返回旧脚本兼容的三元组。"""
    bundle = LocalSpineBundleResolver(bundle_root).resolve(char_id)
    return bundle.skel_path, bundle.atlas_path, list(bundle.texture_paths)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(path: Path, root: Path, label: str) -> Path:
    resolved_root = root.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise LocalSpineResolveError(f"{label} 路径越界")
    return resolved


def _run_git_commit(root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and re.fullmatch(r"[0-9a-fA-F]{7,64}", value) else "unknown"


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return default


def _unique_asset_ids(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        asset_id = value.strip().lower()
        if not _ASSET_ID.fullmatch(asset_id) or asset_id in seen:
            continue
        seen.add(asset_id)
        result.append(asset_id)
    return result


def _verified_costume_asset_ids(value: Any) -> list[str]:
    """只读取带来源、哈希和日期的已核验服装映射。"""
    if not isinstance(value, dict) or value.get("schema_version") != 2:
        return []
    rows = value.get("entries")
    if not isinstance(rows, list):
        return []
    candidates: list[Any] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        source_hash = row.get("source_sha256")
        if (
            not isinstance(row.get("source"), str)
            or not row["source"].strip()
            or not isinstance(source_hash, str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", source_hash)
            or not isinstance(row.get("verified_at"), str)
            or not row["verified_at"].strip()
        ):
            continue
        candidates.append(row.get("spine_asset_id"))
    return _unique_asset_ids(candidates)


def enumerate_targets(repo_root: Path, *, all_targets: bool) -> tuple[list[str], list[str], list[str]]:
    """返回 (待处理目标, default 目标, verified costume 目标)。"""
    if not all_targets:
        defaults = _unique_asset_ids(DEFAULT_TARGETS)
        return defaults, defaults, []

    master = _read_json(repo_root / "assets" / "character_master.json", {})
    default_values = [
        row.get("spine_asset_id")
        for row in (master.get("characters", []) if isinstance(master, dict) else [])
        if isinstance(row, dict)
    ]
    defaults = _unique_asset_ids(default_values)
    if not defaults:
        defaults = _unique_asset_ids(DEFAULT_TARGETS)

    costumes = _read_json(repo_root / "assets" / "costumes.json", {})
    costume_targets = _verified_costume_asset_ids(costumes)
    combined = _unique_asset_ids([*defaults, *costume_targets])
    return combined, defaults, costume_targets


def _manifest_entry(
    bundle: LocalSpineBundle,
    rendered_png: Path,
    *,
    source_commit: str,
    output_root: Path,
    nikke_db_root: Path,
    animation: str,
    alpha_bbox: list[int],
) -> dict[str, Any]:
    with Image.open(rendered_png) as image:
        width, height = image.size
    return {
        "asset_id": bundle.skel_path.parent.name,
        "source_repo": SOURCE_REPO,
        "source_commit": source_commit,
        "runtime_version": bundle.runtime_version,
        "skel_relative_path": bundle.skel_path.relative_to(nikke_db_root.resolve()).as_posix(),
        "atlas_relative_path": bundle.atlas_path.relative_to(nikke_db_root.resolve()).as_posix(),
        "texture_count": len(bundle.texture_paths),
        "animation": animation,
        "rendered_png": rendered_png.relative_to(output_root.resolve()).as_posix(),
        "width": width,
        "height": height,
        "alpha_bbox": alpha_bbox,
        "sha256": _sha256(rendered_png),
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def render_spine_portrait(
    char_id: str,
    skel_path: Path,
    atlas_path: Path,
    textures: list[Path],
    out_png: Path,
    worker_40: str,
    worker_41: str,
    animation: str = "idle",
) -> dict[str, Any]:
    """调用已匹配版本 worker，使用 worker 的初始时间 0 渲染透明 PNG。"""
    version = detect_spine_version(skel_path)
    worker_bin = worker_40 if version == "4.0" else worker_41
    if not shutil.which(worker_bin) and not Path(worker_bin).exists():
        raise FileNotFoundError(f"找不到 Spine {version} worker")

    bundle_root = skel_path.parent.resolve()
    for path, label in ((skel_path, "skeleton"), (atlas_path, "atlas"), *[(item, "纹理") for item in textures]):
        _inside(path, bundle_root, label)
    if not textures:
        raise LocalSpineResolveError("Spine bundle 缺少纹理页")

    fd, tmp_name = tempfile.mkstemp(prefix=f".spine-{char_id}-", suffix=".rgba", dir=bundle_root)
    os.close(fd)
    rgba_path = Path(tmp_name)
    command = [
        worker_bin,
        "--skeleton", str(skel_path.resolve()),
        "--atlas", str(atlas_path.resolve()),
        "--output", str(rgba_path.resolve()),
        "--animation", animation,
        "--width", "1024",
        "--height", "1024",
    ]
    environment = os.environ.copy()
    environment.update({"SDL_VIDEODRIVER": "dummy", "SDL_RENDER_DRIVER": "software"})
    try:
        completed = subprocess.run(
            command,
            cwd=str(bundle_root),
            env=environment,
            capture_output=True,
            timeout=30,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode != 0:
            raise RuntimeError("Spine worker 执行失败")
        raw = rgba_path.read_bytes()
        if len(raw) < 8:
            raise RuntimeError("Spine worker 输出 RGBA 不完整")
        width = int.from_bytes(raw[0:4], "little")
        height = int.from_bytes(raw[4:8], "little")
        expected = 8 + width * height * 4
        if not 1 <= width <= 4096 or not 1 <= height <= 4096 or len(raw) != expected:
            raise RuntimeError("Spine worker RGBA 尺寸或长度无效")
        image = Image.frombytes("RGBA", (width, height), raw[8:]).copy()
        bbox = image.getbbox()
        if bbox is None:
            raise RuntimeError("Spine worker 输出全透明")
        padding = 16
        cropped = image.crop(
            (
                max(0, bbox[0] - padding),
                max(0, bbox[1] - padding),
                min(image.width, bbox[2] + padding),
                min(image.height, bbox[3] + padding),
            )
        )
        out_png.parent.mkdir(parents=True, exist_ok=True)
        cropped.save(out_png, "PNG", optimize=True)
        return {
            "runtime_version": version,
            "width": cropped.width,
            "height": cropped.height,
            "alpha_bbox": list(bbox),
        }
    finally:
        rgba_path.unlink(missing_ok=True)


def _cached_entry_is_valid(entry: Any, png: Path, asset_id: str, output_root: Path) -> bool:
    if not isinstance(entry, dict) or entry.get("asset_id") != asset_id:
        return False
    try:
        rendered = _inside(output_root / str(entry["rendered_png"]), output_root, "manifest PNG")
        if rendered != png.resolve() or not rendered.is_file() or _sha256(rendered) != entry.get("sha256"):
            return False
        with Image.open(rendered) as image:
            if image.mode != "RGBA" or image.width * image.height > 20_000_000:
                return False
            image.load()
        return True
    except (KeyError, OSError, TypeError, ValueError, Image.DecompressionBombError):
        return False


def _write_manifest(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _coverage_report(
    *,
    defaults: list[str],
    costumes: list[str],
    targets: list[str],
    success: list[str],
    bundle_found: list[str],
    failed: list[str],
    missing: list[str],
    invalid: list[str] | None = None,
) -> dict[str, Any]:
    """生成按 default/costume/overall 分母计算的覆盖率，而不是示例通过即 PASS。"""
    success_set = set(success)
    default_set = set(defaults)
    costume_set = set(costumes)

    def percent(numerator: int, denominator: int) -> float | None:
        return round(numerator * 100 / denominator, 2) if denominator else None

    invalid_ids = sorted(set(invalid or []))
    return {
        "schema_version": 1,
        "character_master_count": len(defaults),
        "default_spine_target_count": len(defaults),
        "verified_costume_target_count": len(costumes),
        "total_unique_targets": len(targets),
        "local_bundle_found": len(bundle_found),
        "local_bundle_missing": len(missing),
        "runtime_40_count": 0,
        "runtime_41_count": 0,
        "render_success": len(success),
        "render_invalid": len(invalid_ids),
        "render_failed": len(failed),
        "render_missing": len(missing),
        "default_success_count": len(success_set & default_set),
        "costume_success_count": len(success_set & costume_set),
        "default_coverage_percent": percent(len(success_set & default_set), len(defaults)),
        "costume_coverage_percent": percent(len(success_set & costume_set), len(costumes)),
        "overall_coverage_percent": percent(len(success_set & set(targets)), len(targets)),
        "failed_ids": sorted(set(failed)),
        "missing_ids": sorted(set(missing)),
        "render_invalid_ids": invalid_ids,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="本地 Nikke-db Spine 维护期预渲染工具")
    parser.add_argument("--assets", nargs="+", default=None, help="明确的 canonical Spine asset ID")
    parser.add_argument("--all", action="store_true", help="处理 character master 默认资产与 verified costume 资产")
    parser.add_argument("--nikke-db-root", default="", help="本地 Nikke-db checkout 根目录")
    parser.add_argument("--out-dir", default="", help="PNG 输出目录")
    parser.add_argument("--manifest-path", "--manifest", dest="manifest_path", default="", help="manifest v2 输出路径")
    parser.add_argument("--coverage-report", default="", help="可选的 JSON 覆盖率报告路径")
    parser.add_argument("--worker-40", default="/usr/local/bin/entrypoint-xvfb.sh")
    parser.add_argument("--worker-41", default="/usr/local/bin/entrypoint-xvfb-4.1.sh")
    parser.add_argument("--force", action="store_true", help="重新渲染已有 PNG")
    args = parser.parse_args(argv)

    nikke_db_root = Path(args.nikke_db_root) if args.nikke_db_root else Path("/AstrBot/data/vendor/nikke-db")
    output_root = Path(args.out_dir) if args.out_dir else REPO_ROOT / "assets" / "spine-rendered"
    manifest_path = Path(args.manifest_path) if args.manifest_path else REPO_ROOT / "assets" / "spine_manifest.json"
    output_root.mkdir(parents=True, exist_ok=True)
    targets, defaults, costumes = enumerate_targets(REPO_ROOT, all_targets=args.all)
    if args.assets:
        targets = _unique_asset_ids(args.assets)
        default_set = set(defaults)
        costume_set = set(costumes)
        defaults = [item for item in targets if item in default_set]
        costumes = [item for item in targets if item in costume_set and item not in default_set]

    source_commit = _run_git_commit(nikke_db_root)
    started_at = dt.datetime.now(dt.timezone.utc).isoformat()
    old = _read_json(manifest_path, {})
    old_entries = old.get("assets", {}) if isinstance(old, dict) else {}
    if not isinstance(old_entries, dict):
        old_entries = {}
    target_set = set(targets)
    # 非 force 的局部运行保留其它目标的已验证条目；当前目标失败时不保留旧 PNG，避免陈旧成功状态。
    entries: dict[str, Any] = {
        key: value for key, value in old_entries.items() if key not in target_set
    }
    success: list[str] = []
    failed: list[str] = []
    missing: list[str] = []
    render_invalid: list[str] = []
    bundle_found: list[str] = []
    runtime_versions: dict[str, str] = {}

    print(f"=== 本地 Spine 预渲染 {len(targets)} 项 ===")
    for asset_id in targets:
        target_png = output_root / f"{asset_id}.png"
        cached = old_entries.get(asset_id)
        if isinstance(cached, dict) and not _cached_entry_is_valid(cached, target_png, asset_id, output_root):
            # 旧 manifest 的坏条目是独立的 invalid 证据，不能被 fallback 当作成功。
            render_invalid.append(asset_id)
        if not args.force and _cached_entry_is_valid(cached, target_png, asset_id, output_root):
            entries[asset_id] = cached
            success.append(asset_id)
            bundle_found.append(asset_id)
            if isinstance(cached.get("runtime_version"), str):
                runtime_versions[asset_id] = cached["runtime_version"]
            print(f"[{asset_id}] 命中 manifest v2，跳过")
            continue
        try:
            bundle = LocalSpineBundleResolver(nikke_db_root).resolve(asset_id)
        except (LocalSpineResolveError, OSError) as exc:
            print(f"[{asset_id}] bundle 缺失/无效: {exc}", file=sys.stderr)
            missing.append(asset_id)
            continue
        bundle_found.append(asset_id)
        runtime_versions[asset_id] = bundle.runtime_version
        try:
            render_spine_portrait(
                asset_id,
                bundle.skel_path,
                bundle.atlas_path,
                list(bundle.texture_paths),
                target_png,
                args.worker_40,
                args.worker_41,
                animation="idle",
            )
            with Image.open(target_png) as image:
                bbox = image.getbbox()
                if image.mode != "RGBA" or bbox is None:
                    raise RuntimeError("渲染 PNG 不是非空 RGBA")
                alpha_bbox = list(bbox)
            entries[asset_id] = _manifest_entry(
                bundle,
                target_png,
                source_commit=source_commit,
                output_root=output_root,
                nikke_db_root=nikke_db_root,
                animation="idle",
                alpha_bbox=alpha_bbox,
            )
            success.append(asset_id)
            print(f"[{asset_id}] 成功 {target_png}")
        except (FileNotFoundError, LocalSpineResolveError, OSError, RuntimeError, ValueError) as exc:
            print(f"[{asset_id}] 渲染失败: {exc}", file=sys.stderr)
            failed.append(asset_id)

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "source_repo": SOURCE_REPO,
        "source_commit": source_commit,
        "generated_at": started_at,
        "default_target_count": len(defaults),
        "costume_target_count": len(costumes),
        "unique_target_count": len(targets),
        "render_success": len(success),
        "render_invalid": len(render_invalid),
        "render_failed": len(failed),
        "render_missing": len(missing),
        "local_bundle_found": len(bundle_found),
        "local_bundle_missing": len(missing),
        "runtime_40_count": sum(version == "4.0" for version in runtime_versions.values()),
        "runtime_41_count": sum(version == "4.1" for version in runtime_versions.values()),
        "failed_ids": failed,
        "missing_ids": missing,
        "assets": entries,
    }
    coverage = _coverage_report(
        defaults=defaults,
        costumes=costumes,
        targets=targets,
        success=success,
        invalid=render_invalid,
        bundle_found=bundle_found,
        failed=failed,
        missing=missing,
    )
    coverage["runtime_40_count"] = manifest["runtime_40_count"]
    coverage["runtime_41_count"] = manifest["runtime_41_count"]
    manifest["coverage"] = coverage
    _write_manifest(manifest_path, manifest)
    if args.coverage_report:
        _write_manifest(Path(args.coverage_report), coverage)
    print(f"Manifest 已写入 {manifest_path}")
    print(json.dumps({
        "default_target_count": len(defaults),
        "costume_target_count": len(costumes),
        "unique_target_count": len(targets),
        "render_success": len(success),
        "render_invalid": len(render_invalid),
        "render_failed": len(failed),
        "render_missing": len(missing),
    }, ensure_ascii=False))
    return 0 if not failed and not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""按固定 Nikke-db commit 只取指定默认角色的 Spine bundle 与 atlas 纹理页。"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from PIL import Image, ImageFile


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPOSITORY = "https://github.com/Nikke-db/Nikke-db.github.io"
SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
RENDER_ID_RE = re.compile(r"^c[0-9]+$", re.ASCII)
RUNTIME_RE = re.compile(rb"(?<![0-9])4\.[01](?:\.[0-9]+)?(?![0-9])")
MAX_TOTAL_BYTES = 300 * 1024 * 1024
MAX_ATLAS_BYTES = 2 * 1024 * 1024
MAX_SKELETON_BYTES = 16 * 1024 * 1024
MAX_TEXTURE_BYTES = 12 * 1024 * 1024


class BatchFetchError(ValueError):
    """候选来源、固定快照或 bundle 完整性校验失败。"""


def _run_git(root: Path, *arguments: str, check: bool = True) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BatchFetchError("执行本地 Git 只读提取失败") from exc
    if check and result.returncode != 0:
        raise BatchFetchError("Git 仓库无法提供固定 commit 中的指定对象")
    return result.stdout


def _prepare_checkout(checkout_dir: Path, repository_url: str, commit_sha: str) -> None:
    checkout = checkout_dir.resolve(strict=False)
    if checkout.is_relative_to(REPO_ROOT.resolve()):
        raise BatchFetchError("Nikke-db checkout 必须位于插件仓库之外")
    if checkout.exists():
        if not checkout.is_dir() or not (checkout / ".git").exists():
            raise BatchFetchError("checkout 目标已存在但不是受管 Git 仓库；拒绝覆盖")
        owner = _run_git(checkout, "config", "--local", "--get", "nikkeBatchCache.owner", check=False)
        if owner.decode("utf-8", "replace").strip() != "phase3a":
            raise BatchFetchError("checkout 缺少 Phase 3A 所有权标记；拒绝复用")
        remote = _run_git(checkout, "remote", "get-url", "origin").decode("utf-8", "replace").strip()
        if remote != repository_url:
            raise BatchFetchError("checkout origin 与固定 Nikke-db 仓库不一致")
        unexpected = [item.name for item in checkout.iterdir() if item.name != ".git"]
        if unexpected:
            raise BatchFetchError("无 checkout 的对象缓存出现工作树文件；拒绝复用")
    else:
        checkout.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = subprocess.run(
                [
                    "git", "clone", "--filter=blob:none", "--no-checkout", "--depth=1",
                    "--single-branch", repository_url, str(checkout),
                ],
                capture_output=True,
                timeout=300,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise BatchFetchError("创建 Nikke-db partial clone 失败") from exc
        if result.returncode != 0:
            raise BatchFetchError("创建 Nikke-db partial clone 失败")
        _run_git(checkout, "config", "--local", "nikkeBatchCache.owner", "phase3a")

    try:
        result = subprocess.run(
            ["git", "-C", str(checkout), "fetch", "--filter=blob:none", "--no-tags", "--depth=1", "origin", commit_sha],
            capture_output=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BatchFetchError("获取固定 Nikke-db commit 失败") from exc
    if result.returncode != 0:
        raise BatchFetchError("获取固定 Nikke-db commit 失败")
    actual = _run_git(checkout, "rev-parse", "FETCH_HEAD").decode("ascii", "replace").strip().lower()
    if actual != commit_sha:
        raise BatchFetchError("partial clone 未到达 coverage snapshot 固定 commit")
    _run_git(checkout, "update-ref", "refs/heads/phase3a-cache", commit_sha)
    _run_git(checkout, "symbolic-ref", "HEAD", "refs/heads/phase3a-cache")
    _run_git(checkout, "read-tree", "--empty")
    head = _run_git(checkout, "rev-parse", "HEAD").decode("ascii", "replace").strip().lower()
    if head != commit_sha:
        raise BatchFetchError("对象缓存 HEAD 未绑定固定 upstream commit")


def _safe_atlas_pages(atlas: bytes, bundle_dir: PurePosixPath) -> list[str]:
    try:
        text = atlas.decode("utf-8-sig")
    except UnicodeError as exc:
        raise BatchFetchError("atlas 不是 UTF-8-SIG 文本") from exc
    pages: set[str] = set()
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [line.strip().lstrip("\ufeff") for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        name = lines[0]
        if PurePosixPath(name).suffix.lower() not in {".png", ".webp"}:
            continue
        relative = PurePosixPath(name)
        if (
            not name
            or "\\" in name
            or relative.is_absolute()
            or ":" in name
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise BatchFetchError(f"atlas 纹理页路径非法: {name}")
        target = bundle_dir / relative
        if target.is_absolute() or any(part == ".." for part in target.parts):
            raise BatchFetchError(f"atlas 纹理页路径越界: {name}")
        pages.add(target.as_posix())
    if not pages:
        raise BatchFetchError("atlas 未声明可用 PNG/WebP 纹理页")
    return sorted(pages)


def _git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def _snapshot_file_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = snapshot.get("l2d_files")
    if not isinstance(rows, list):
        raise BatchFetchError("upstream snapshot 缺少 l2d_files")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            continue
        path = row["path"]
        if path in result:
            raise BatchFetchError(f"upstream snapshot 路径重复: {path}")
        result[path] = row
    return result


def _load_pinned_file(
    checkout: Path,
    commit_sha: str,
    relative: str,
    row: dict[str, Any],
    *,
    max_bytes: int,
) -> bytes:
    expected_sha = row.get("sha")
    expected_size = row.get("size")
    if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", expected_sha):
        raise BatchFetchError(f"snapshot 缺少有效 Git blob SHA: {relative}")
    if type(expected_size) is not int or not 0 < expected_size <= max_bytes:
        raise BatchFetchError(f"snapshot 文件大小超限或无效: {relative}")
    tree_blob = _run_git(checkout, "rev-parse", f"{commit_sha}:{relative}").decode("ascii", "replace").strip().lower()
    if tree_blob != expected_sha:
        raise BatchFetchError(f"snapshot blob SHA 不匹配: {relative}")
    data = _run_git(checkout, "show", f"{commit_sha}:{relative}")
    if len(data) != expected_size or _git_blob_sha(data) != expected_sha:
        raise BatchFetchError(f"固定 bundle 字节与 snapshot 不匹配: {relative}")
    return data


def _validate_batch(batch: dict[str, Any], snapshot: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    commit_sha = snapshot.get("commit_sha")
    source_repo = snapshot.get("source_repo")
    if not isinstance(commit_sha, str) or not SHA_RE.fullmatch(commit_sha):
        raise BatchFetchError("upstream snapshot commit SHA 无效")
    if source_repo != DEFAULT_REPOSITORY:
        raise BatchFetchError("upstream snapshot 不是固定 Nikke-db 来源")
    if batch.get("upstream_snapshot_sha") != commit_sha:
        raise BatchFetchError("候选 batch 和 upstream snapshot commit 不一致")
    if not isinstance(batch.get("generated_from_head"), str) or not re.fullmatch(
        r"[0-9a-f]{40,64}", batch["generated_from_head"]
    ):
        raise BatchFetchError("候选 batch 缺少生成 HEAD")
    rows = batch.get("candidates")
    ids = batch.get("render_ids")
    if not isinstance(rows, list) or not isinstance(ids, list) or not rows or len(rows) > 50:
        raise BatchFetchError("候选 batch 项目数或结构无效")
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in rows:
        if not isinstance(candidate, dict):
            raise BatchFetchError("候选 batch 中存在无效项目")
        render_id = candidate.get("render_id")
        resource_id = candidate.get("resource_id")
        if (
            not isinstance(render_id, str)
            or not RENDER_ID_RE.fullmatch(render_id)
            or render_id in seen
            or candidate.get("consumer_type") != "default_character"
            or candidate.get("costume_id") is not None
            or candidate.get("upstream_bundle_complete") is not True
            or not isinstance(resource_id, str)
            or not resource_id.isdigit()
            or int(render_id[1:]) != int(resource_id)
        ):
            raise BatchFetchError("仅允许一一对应的 canonical 默认角色候选")
        seen.add(render_id)
        candidates.append(candidate)
    if ids != [candidate["render_id"] for candidate in candidates] or len(seen) != len(ids):
        raise BatchFetchError("候选 render_ids 和项目列表不一致")
    return commit_sha, candidates


def fetch_candidate_bundles(
    batch: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    checkout_dir: Path,
    output_dir: Path,
    repository_url: str = DEFAULT_REPOSITORY,
) -> dict[str, Any]:
    """用 partial clone + 固定 Git blob 清单物化候选所需的最小文件集。"""
    if repository_url != DEFAULT_REPOSITORY:
        raise BatchFetchError("只允许固定的官方 Nikke-db 仓库来源")
    commit_sha, candidates = _validate_batch(batch, snapshot)
    output_root = output_dir.resolve(strict=False)
    if output_root.is_relative_to(REPO_ROOT.resolve()):
        raise BatchFetchError("候选 bundle 输出必须位于插件仓库之外")
    checkout = checkout_dir.resolve(strict=False)
    if output_root == checkout or output_root.is_relative_to(checkout) or checkout.is_relative_to(output_root):
        raise BatchFetchError("Git object cache 与 bundle 输出目录必须互不包含")
    _prepare_checkout(checkout, repository_url, commit_sha)
    snapshot_rows = _snapshot_file_map(snapshot)

    staged: dict[str, tuple[bytes, str, str]] = {}
    bundles: list[dict[str, Any]] = []
    total_bytes = 0
    for candidate in candidates:
        render_id = candidate["render_id"]
        bundle_dir = PurePosixPath("l2d") / render_id
        stem = f"{render_id}_00"
        skeleton_path = (bundle_dir / f"{stem}.skel").as_posix()
        atlas_path = (bundle_dir / f"{stem}.atlas").as_posix()
        skeleton_row = snapshot_rows.get(skeleton_path)
        atlas_row = snapshot_rows.get(atlas_path)
        if not isinstance(skeleton_row, dict) or not isinstance(atlas_row, dict):
            raise BatchFetchError(f"snapshot 缺少唯一 canonical _00 skeleton/atlas: {render_id}")
        skeleton = _load_pinned_file(checkout, commit_sha, skeleton_path, skeleton_row, max_bytes=MAX_SKELETON_BYTES)
        atlas = _load_pinned_file(checkout, commit_sha, atlas_path, atlas_row, max_bytes=MAX_ATLAS_BYTES)
        runtime_match = RUNTIME_RE.search(skeleton[:512])
        if runtime_match is None:
            raise BatchFetchError(f"无法从 skeleton 头部识别 runtime，拒绝猜测: {render_id}")
        runtime_version = runtime_match.group(0).decode("ascii")[:3]
        bundle_files = [(skeleton_path, skeleton, "skeleton"), (atlas_path, atlas, "atlas")]
        texture_paths = _safe_atlas_pages(atlas, bundle_dir)
        for texture_path in texture_paths:
            texture_row = snapshot_rows.get(texture_path)
            if not isinstance(texture_row, dict):
                raise BatchFetchError(f"固定 snapshot 未包含 atlas 纹理页: {texture_path}")
            texture = _load_pinned_file(
                checkout, commit_sha, texture_path, texture_row, max_bytes=MAX_TEXTURE_BYTES
            )
            previous_truncated = ImageFile.LOAD_TRUNCATED_IMAGES
            try:
                ImageFile.LOAD_TRUNCATED_IMAGES = False
                with Image.open(io.BytesIO(texture)) as image:
                    image.verify()
            except (OSError, ValueError) as exc:
                raise BatchFetchError(f"atlas 纹理不是有效图片: {texture_path}") from exc
            finally:
                ImageFile.LOAD_TRUNCATED_IMAGES = previous_truncated
            bundle_files.append((texture_path, texture, "texture"))
        for path, data, role in bundle_files:
            total_bytes += len(data)
            if total_bytes > MAX_TOTAL_BYTES:
                raise BatchFetchError("候选 bundle 总大小超过 300 MiB 安全上限")
            row = snapshot_rows[path]
            staged[path] = (data, role, row["sha"])
        bundles.append(
            {
                "render_id": render_id,
                "resource_id": candidate["resource_id"],
                "runtime_version": runtime_version,
                "skeleton_path": skeleton_path,
                "atlas_path": atlas_path,
                "texture_paths": texture_paths,
            }
        )

    files = [
        {
            "path": path,
            "role": role,
            "git_blob_sha": blob_sha,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
        for path, (data, role, blob_sha) in sorted(staged.items())
    ]
    provenance = {
        "schema_version": 1,
        "batch_id": batch.get("batch_id"),
        "generated_from_head": batch["generated_from_head"],
        "source_repository": repository_url,
        "source_commit": commit_sha,
        "upstream_snapshot_sha": commit_sha,
        "render_ids": [candidate["render_id"] for candidate in candidates],
        "bundles": bundles,
        "files": files,
        "total_bytes": total_bytes,
    }

    provenance_path = output_root / "fetch-provenance.json"
    if provenance_path.exists():
        try:
            current = json.loads(provenance_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise BatchFetchError("已有 fetch provenance 无法读取；拒绝覆盖") from exc
        if current != provenance:
            raise BatchFetchError("已有 fetch provenance 与本次请求不同；拒绝覆盖")
    for path, (data, _, blob_sha) in sorted(staged.items()):
        target = (output_root / Path(*PurePosixPath(path).parts)).resolve(strict=False)
        if not target.is_relative_to(output_root):
            raise BatchFetchError("候选 bundle 目标路径越界")
        if target.exists():
            if not target.is_file() or _git_blob_sha(target.read_bytes()) != blob_sha:
                raise BatchFetchError(f"候选缓存中已有内容不匹配；拒绝覆盖: {path}")
    for path, (data, _, _) in sorted(staged.items()):
        target = output_root / Path(*PurePosixPath(path).parts)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with target.open("xb") as destination:
                    destination.write(data)
            except FileExistsError:
                if _git_blob_sha(target.read_bytes()) != _git_blob_sha(data):
                    raise BatchFetchError(f"候选缓存写入并发冲突: {path}")

    if str(REPO_ROOT.parent) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT.parent))
    from astrbot_plugin_nikke.integrations.spine.local_resolver import (
        LocalSpineBundleResolver,
        LocalSpineResolveError,
    )

    resolver = LocalSpineBundleResolver(output_root)
    for expected in bundles:
        try:
            resolved = resolver.resolve(expected["render_id"])
        except (LocalSpineResolveError, OSError) as exc:
            raise BatchFetchError(f"落盘 bundle 未通过生产本地解析器: {expected['render_id']}") from exc
        if resolved.runtime_version != expected["runtime_version"]:
            raise BatchFetchError(f"runtime 版本二次核验不一致: {expected['render_id']}")

    output_root.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if not provenance_path.exists():
        try:
            with provenance_path.open("x", encoding="utf-8", newline="\n") as destination:
                destination.write(payload)
        except FileExistsError:
            current = json.loads(provenance_path.read_text(encoding="utf-8"))
            if current != provenance:
                raise BatchFetchError("provenance 并发写入冲突")

    return provenance


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    args = parser.parse_args(argv)
    try:
        batch = json.loads(args.batch.read_text(encoding="utf-8"))
        snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
        result = fetch_candidate_bundles(
            batch, snapshot, checkout_dir=args.checkout, output_dir=args.output,
            repository_url=args.repository,
        )
    except (OSError, UnicodeError, ValueError, BatchFetchError) as exc:
        print(f"候选 bundle 获取失败: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"render_ids": result["render_ids"], "file_count": len(result["files"]), "total_bytes": result["total_bytes"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

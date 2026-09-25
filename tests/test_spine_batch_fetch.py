from __future__ import annotations

import hashlib
import io
import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from scripts import fetch_spine_candidate_bundles as fetch_module
from scripts.fetch_spine_candidate_bundles import BatchFetchError, fetch_candidate_bundles
from scripts.sync_spine_assets import _run_git_commit


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _git_blob_sha(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def _png_bytes() -> bytes:
    target = io.BytesIO()
    Image.new("RGBA", (1, 1), (255, 255, 255, 255)).save(target, format="PNG")
    return target.getvalue()


def _fixture_upstream(tmp_path: Path) -> tuple[Path, str, dict[str, object]]:
    source = tmp_path / "upstream"
    source.mkdir()
    _git(source, "init", "--initial-branch=main")
    _git(source, "config", "user.name", "Test")
    _git(source, "config", "user.email", "test@example.invalid")
    files = {
        "l2d/c020/c020_00.skel": b"skeleton Spine 4.1.24 fixture",
        "l2d/c020/c020_00.atlas": b"c020_00.png\nsize: 1, 1\n\nregion\nbounds: 0, 0, 1, 1\n",
        "l2d/c020/c020_00.png": _png_bytes(),
        "l2d/c020/aim/c020_aim_00.skel": b"must-not-fetch",
    }
    for relative, contents in files.items():
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)
    _git(source, "add", "l2d")
    _git(source, "commit", "-m", "fixture")
    commit = _git(source, "rev-parse", "HEAD")
    rows = []
    for relative, contents in files.items():
        blob = _git(source, "rev-parse", f"{commit}:{relative}")
        rows.append({"path": relative, "sha": blob, "size": len(contents)})
    snapshot: dict[str, object] = {
        "schema_version": 2,
        "source_repo": "fixture://nikke-db",
        "commit_sha": commit,
        "l2d_files": rows,
    }
    return source, commit, snapshot


def _batch(commit: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "generated_from_head": "a" * 40,
        "upstream_snapshot_sha": commit,
        "batch_id": "batch-001",
        "render_ids": ["c020"],
        "candidates": [
            {
                "render_id": "c020",
                "consumer_type": "default_character",
                "resource_id": "20",
                "character_key": "delta",
                "costume_id": None,
                "upstream_bundle_complete": True,
            }
        ],
    }


def test_sparse_fetch_materializes_only_selected_default_bundle_and_atlas_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upstream, commit, snapshot = _fixture_upstream(tmp_path)
    monkeypatch.setattr(fetch_module, "DEFAULT_REPOSITORY", str(upstream))
    snapshot["source_repo"] = str(upstream)
    checkout = tmp_path / "git-cache"
    output = tmp_path / "bundle-cache"

    result = fetch_candidate_bundles(
        _batch(commit), snapshot, checkout_dir=checkout, output_dir=output, repository_url=str(upstream)
    )

    assert result["source_commit"] == commit
    assert result["render_ids"] == ["c020"]
    assert _git(checkout, "rev-parse", "HEAD") == commit
    assert {row["role"] for row in result["files"]} == {"skeleton", "atlas", "texture"}
    assert (output / "l2d/c020/c020_00.skel").is_file()
    assert (output / "l2d/c020/c020_00.atlas").is_file()
    assert (output / "l2d/c020/c020_00.png").is_file()
    assert not (output / "l2d/c020/aim/c020_aim_00.skel").exists()
    assert json.loads((output / "fetch-provenance.json").read_text(encoding="utf-8")) == result

    repeated = fetch_candidate_bundles(
        _batch(commit), snapshot, checkout_dir=checkout, output_dir=output, repository_url=str(upstream)
    )
    assert repeated == result


def test_sparse_fetch_rejects_atlas_path_escape_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upstream, commit, snapshot = _fixture_upstream(tmp_path)
    monkeypatch.setattr(fetch_module, "DEFAULT_REPOSITORY", str(upstream))
    snapshot["source_repo"] = str(upstream)
    atlas = upstream / "l2d/c020/c020_00.atlas"
    atlas.write_bytes(b"../secret.png\nsize: 1, 1\n")
    _git(upstream, "add", "l2d/c020/c020_00.atlas")
    _git(upstream, "commit", "-m", "unsafe atlas")
    commit = _git(upstream, "rev-parse", "HEAD")
    rows = snapshot["l2d_files"]
    assert isinstance(rows, list)
    for row in rows:
        if row["path"] == "l2d/c020/c020_00.atlas":
            row["sha"] = _git(upstream, "rev-parse", f"{commit}:{row['path']}")
            row["size"] = atlas.stat().st_size
    snapshot["commit_sha"] = commit

    output = tmp_path / "unsafe-output"
    with pytest.raises(BatchFetchError, match="atlas 纹理页路径非法"):
        fetch_candidate_bundles(
            _batch(commit), snapshot, checkout_dir=tmp_path / "unsafe-git", output_dir=output,
            repository_url=str(upstream),
        )
    assert not (output / "l2d/c020/c020_00.skel").exists()


def test_sparse_fetch_rejects_snapshot_blob_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upstream, commit, snapshot = _fixture_upstream(tmp_path)
    monkeypatch.setattr(fetch_module, "DEFAULT_REPOSITORY", str(upstream))
    snapshot["source_repo"] = str(upstream)
    rows = snapshot["l2d_files"]
    assert isinstance(rows, list)
    rows[0]["sha"] = "0" * 40

    with pytest.raises(BatchFetchError, match="snapshot blob SHA 不匹配"):
        fetch_candidate_bundles(
            _batch(commit), snapshot, checkout_dir=tmp_path / "bad-git", output_dir=tmp_path / "bad-output",
            repository_url=str(upstream),
        )


def test_sync_renderer_reads_only_hash_verified_fetch_provenance_when_bundle_is_not_a_checkout(
    tmp_path: Path,
) -> None:
    bundle_root = tmp_path / "external-bundle"
    asset = bundle_root / "l2d/c020/c020_00.skel"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"pinned skeleton")
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    provenance = {
        "schema_version": 1,
        "source_repository": "https://github.com/Nikke-db/Nikke-db.github.io",
        "source_commit": "a" * 40,
        "upstream_snapshot_sha": "a" * 40,
        "files": [{
            "path": "l2d/c020/c020_00.skel",
            "sha256": digest,
            "size": asset.stat().st_size,
        }],
    }
    (bundle_root / "fetch-provenance.json").write_text(
        json.dumps(provenance), encoding="utf-8"
    )

    assert _run_git_commit(bundle_root) == "a" * 40

    asset.write_bytes(b"changed skeleton")
    assert _run_git_commit(bundle_root) == "unknown"

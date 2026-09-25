from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

from scripts.spine_batch_review import (
    build_review_queue,
    create_contact_sheet,
    deterministic_pass_sample,
    render_review_markdown,
    validate_candidate_render,
)
from scripts.spine_batch_validation import build_verified_baseline


ROOT = Path(__file__).resolve().parents[1]


def test_review_and_white_card_tools_run_as_repository_scripts() -> None:
    for name in ("spine_batch_review.py", "render_spine_candidate_cards.py"):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / name), "--help"],
            cwd=ROOT,
            check=False,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
        assert b"usage:" in result.stdout


def _fixture(tmp_path: Path):
    bundle_root = tmp_path / "bundle"
    bundle = bundle_root / "l2d" / "c020"
    bundle.mkdir(parents=True)
    skeleton = bundle / "c020_00.skel"
    skeleton.write_bytes(b"fixture Spine 4.1.24")
    atlas = bundle / "c020_00.atlas"
    atlas.write_bytes(b"c020_00.png\nsize: 1, 1\n\nregion\nbounds: 0, 0, 1, 1\n")
    texture = Image.new("RGBA", (1, 1), (255, 255, 255, 255))
    texture.save(bundle / "c020_00.png", format="PNG")
    png_source = ROOT / "assets" / "spine-rendered" / "c018.png"
    render_root = tmp_path / "rendered"
    render_root.mkdir()
    png = render_root / "c020.png"
    png.write_bytes(png_source.read_bytes())
    with Image.open(png) as image:
        dimensions = list(image.size)
    png_sha = hashlib.sha256(png.read_bytes()).hexdigest()
    commit = "a" * 40
    candidate = {
        "render_id": "c020",
        "consumer_type": "default_character",
        "resource_id": "20",
        "character_key": "delta",
        "costume_id": None,
        "upstream_bundle_complete": True,
    }
    fetch_files = []
    for path, role in ((skeleton, "skeleton"), (atlas, "atlas"), (bundle / "c020_00.png", "texture")):
        relative = path.relative_to(bundle_root).as_posix()
        raw = path.read_bytes()
        blob_sha = hashlib.sha1(f"blob {len(raw)}\0".encode("ascii") + raw).hexdigest()
        fetch_files.append({
            "path": relative,
            "role": role,
            "git_blob_sha": blob_sha,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size": len(raw),
        })
    fetch = {
        "schema_version": 1,
        "batch_id": "batch-001",
        "generated_from_head": "b" * 40,
        "source_commit": commit,
        "upstream_snapshot_sha": commit,
        "render_ids": ["c020"],
        "bundles": [{
            "render_id": "c020",
            "runtime_version": "4.1",
            "skeleton_path": "l2d/c020/c020_00.skel",
            "atlas_path": "l2d/c020/c020_00.atlas",
            "texture_paths": ["l2d/c020/c020_00.png"],
        }],
        "files": fetch_files,
    }
    entry = {
        "asset_id": "c020",
        "source_commit": commit,
        "runtime_version": "4.1",
        "skel_relative_path": "l2d/c020/c020_00.skel",
        "atlas_relative_path": "l2d/c020/c020_00.atlas",
        "texture_count": 1,
        "rendered_png": "c020.png",
        "width": dimensions[0],
        "height": dimensions[1],
        "sha256": png_sha,
    }
    manifest = {"source_commit": commit, "assets": {"c020": entry}}
    return bundle_root, render_root, candidate, fetch, manifest, png_sha, dimensions


def test_candidate_render_requires_pinned_bundle_and_output_integrity(tmp_path: Path) -> None:
    bundle_root, render_root, candidate, fetch, manifest, png_sha, dimensions = _fixture(tmp_path)
    baseline = build_verified_baseline(ROOT)
    result = validate_candidate_render(
        candidate, fetch, manifest, bundle_root=bundle_root, render_root=render_root, baseline=baseline
    )

    assert result["machine_status"] in {"PASS", "PASS_WITH_FLAGS"}
    assert result["hard_failures"] == []
    assert result["png_sha256"] == png_sha
    assert result["dimensions"] == dimensions
    assert result["runtime_version"] == "4.1"
    assert result["face_anchor_state"] == "NOT_AUTHORED"

    manifest["assets"]["c020"]["sha256"] = "0" * 64
    rejected = validate_candidate_render(
        candidate, fetch, manifest, bundle_root=bundle_root, render_root=render_root, baseline=baseline
    )
    assert rejected["machine_status"] == "FAIL"
    assert "render_png_sha256_mismatch" in rejected["hard_failures"]


def test_review_queue_and_markdown_are_stable_and_keep_failed_candidates_visible(tmp_path: Path) -> None:
    bundle_root, render_root, candidate, fetch, manifest, _, _ = _fixture(tmp_path)
    batch = {
        "batch_id": "batch-001",
        "generated_from_head": "b" * 40,
        "upstream_snapshot_sha": "a" * 40,
        "render_ids": ["c020", "c022"],
        "candidates": [candidate, {**candidate, "render_id": "c022", "resource_id": "22"}],
    }
    manifest["assets"]["c022"] = None
    baseline = build_verified_baseline(ROOT)

    queue = build_review_queue(
        batch, fetch, manifest, bundle_root=bundle_root, render_root=render_root, baseline=baseline
    )
    markdown = render_review_markdown(queue)

    assert queue["summary"]["candidate_count"] == 2
    assert queue["summary"]["fail_count"] == 1
    assert [row["render_id"] for row in queue["items"]] == ["c020", "c022"]
    assert "c022" in markdown and "FAIL" in markdown and "人工复核" in markdown
    assert render_review_markdown(queue) == markdown


def test_pass_sample_is_deterministic_and_selects_only_machine_pass(tmp_path: Path) -> None:
    records = [
        {"render_id": "c014", "machine_status": "PASS", "png_sha256": "1" * 64},
        {"render_id": "c015", "machine_status": "PASS_WITH_FLAGS", "png_sha256": "2" * 64},
        {"render_id": "c020", "machine_status": "PASS", "png_sha256": "3" * 64},
        {"render_id": "c022", "machine_status": "FAIL", "png_sha256": None},
    ]

    first = deterministic_pass_sample(records, batch_id="batch-001", limit=5)
    second = deterministic_pass_sample(list(reversed(records)), batch_id="batch-001", limit=5)

    assert first == second
    assert {item["render_id"] for item in first} == {"c014", "c020"}


def test_white_card_contact_sheet_is_sorted_and_byte_deterministic(tmp_path: Path) -> None:
    records = []
    for render_id, color in (("c020", (220, 30, 30)), ("c014", (30, 60, 220))):
        path = tmp_path / f"{render_id}.png"
        Image.new("RGB", (1600, 2400), color).save(path, format="PNG")
        records.append({"render_id": render_id, "path": path})

    first = create_contact_sheet(records, tmp_path / "sheet-a.png")
    second = create_contact_sheet(list(reversed(records)), tmp_path / "sheet-b.png")

    assert first["render_ids"] == ["c014", "c020"]
    assert first["sha256"] == second["sha256"]
    assert (tmp_path / "sheet-a.png").read_bytes() == (tmp_path / "sheet-b.png").read_bytes()

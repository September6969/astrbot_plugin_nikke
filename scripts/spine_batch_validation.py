#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Spine 候选批次的本地完整性检查与可解释视觉指标。"""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageFile
from scripts.phase3_output_guard import require_new_external_path

VISUAL_METRICS = (
    "aspect_ratio",
    "alpha_coverage",
    "bbox_width_ratio",
    "bbox_height_ratio",
    "bbox_occupancy",
    "left_margin_ratio",
    "top_margin_ratio",
    "right_margin_ratio",
    "bottom_margin_ratio",
)


class BatchValidationError(ValueError):
    """候选或 baseline 不满足本地验证合同。"""


def _required_finite_number(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise BatchValidationError(f"视觉指标或 baseline 无效: {label}")
    return float(value)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def analyze_png(path: Path) -> dict[str, Any]:
    """严格解码 RGBA PNG 并返回与角色透明图有关的可复现指标。"""
    image_path = path.resolve(strict=True)
    try:
        size_bytes = image_path.stat().st_size
        if size_bytes <= 0:
            raise BatchValidationError("PNG 文件为空")
        previous_truncated = ImageFile.LOAD_TRUNCATED_IMAGES
        ImageFile.LOAD_TRUNCATED_IMAGES = False
        try:
            with Image.open(image_path) as source:
                if source.format != "PNG" or source.mode != "RGBA":
                    raise BatchValidationError("候选 portrait 必须是 RGBA PNG")
                if source.width <= 0 or source.height <= 0 or source.width * source.height > 40_000_000:
                    raise BatchValidationError("PNG 尺寸超出安全范围")
                source.load()
                image = source.copy()
        finally:
            ImageFile.LOAD_TRUNCATED_IMAGES = previous_truncated
    except BatchValidationError:
        raise
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise BatchValidationError("PNG 无法完整解码") from exc

    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        raise BatchValidationError("PNG 全透明")
    width, height = image.size
    alpha_histogram = alpha.histogram()
    visible_pixels = sum(alpha_histogram[1:])
    left, top, right, bottom = bbox
    bbox_width = right - left
    bbox_height = bottom - top
    area = width * height
    rgba_bytes = image.tobytes()
    return {
        "path": image_path.as_posix(),
        "sha256": _sha256_file(image_path),
        "rgba_pixel_sha256": _sha256_bytes(rgba_bytes),
        "file_size": size_bytes,
        "dimensions": [width, height],
        "alpha_bbox": [left, top, right, bottom],
        "aspect_ratio": width / height,
        "alpha_coverage": visible_pixels / area,
        "bbox_width_ratio": bbox_width / width,
        "bbox_height_ratio": bbox_height / height,
        "bbox_occupancy": (bbox_width * bbox_height) / area,
        "left_margin_ratio": left / width,
        "top_margin_ratio": top / height,
        "right_margin_ratio": (width - right) / width,
        "bottom_margin_ratio": (height - bottom) / height,
        "visible_pixels": visible_pixels,
    }


def _quantile(sorted_values: list[float], quantile: float) -> float:
    if not sorted_values:
        raise BatchValidationError("无法从空样本计算分布")
    position = (len(sorted_values) - 1) * quantile
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return sorted_values[low]
    fraction = position - low
    return sorted_values[low] * (1 - fraction) + sorted_values[high] * fraction


def _distribution(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "min": round(ordered[0], 8),
        "p05": round(_quantile(ordered, 0.05), 8),
        "median": round(_quantile(ordered, 0.5), 8),
        "p95": round(_quantile(ordered, 0.95), 8),
        "max": round(ordered[-1], 8),
    }


def score_visual_metrics(metrics: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """用已核验 portrait 的分位区间计算可解释异常分，不做自动视觉审批。"""
    count = baseline.get("verified_portrait_count")
    distributions = baseline.get("distributions")
    if type(count) is not int or count < 20 or not isinstance(distributions, dict):
        raise BatchValidationError("视觉校准 baseline 必须至少含 20 张 verified portrait")

    flags: list[str] = []
    component_scores: dict[str, float] = {}
    for name in VISUAL_METRICS:
        value = _required_finite_number(metrics.get(name), name)
        distribution = distributions.get(name)
        if not isinstance(distribution, dict):
            raise BatchValidationError(f"视觉指标或 baseline 无效: {name}")
        minimum, p05, median, p95, maximum = (
            _required_finite_number(distribution.get(key), f"{name}.{key}")
            for key in ("min", "p05", "median", "p95", "max")
        )
        if not minimum <= p05 <= median <= p95 <= maximum:
            raise BatchValidationError(f"视觉校准分布顺序无效: {name}")

        if value < minimum or value > maximum:
            flags.append(f"outside_verified_range:{name}")
        elif value < p05 or value > p95:
            flags.append(f"outside_central_90:{name}")

        robust_scale = max((p95 - p05) / 3.29, (maximum - minimum) / 6, 1e-6)
        component_scores[name] = abs(value - median) / robust_scale

    flags.sort()
    score = sum(component_scores.values()) / len(component_scores)
    return {
        "status": "PASS_WITH_FLAGS" if flags else "PASS",
        "anomaly_score": round(score, 6),
        "flags": flags,
        "metric_scores": {key: round(value, 6) for key, value in sorted(component_scores.items())},
        "calibration_sample_count": count,
    }


def _trusted_anchor_y_ratio(anchor: Any, metrics: dict[str, Any]) -> float | None:
    if not isinstance(anchor, dict):
        return None
    point = anchor.get("point")
    expected_size = anchor.get("image_size")
    if (
        anchor.get("png_sha256") != metrics["sha256"]
        or anchor.get("pixel_sha256") != metrics["rgba_pixel_sha256"]
        or expected_size != metrics["dimensions"]
        or not isinstance(point, list)
        or len(point) != 2
        or any(type(value) not in (int, float) or not math.isfinite(value) for value in point)
    ):
        return None
    width, height = metrics["dimensions"]
    x, y = point
    left, top, right, bottom = metrics["alpha_bbox"]
    if not (0 <= x < width and 0 <= y < height and left <= x < right and top <= y < bottom):
        return None
    return float(y) / height


def build_verified_baseline(repo_root: Path) -> dict[str, Any]:
    """只用当前 manifest 中逐项通过 hash/尺寸/解码的 PNG 建视觉分布。"""
    root = repo_root.resolve(strict=True)
    manifest_path = root / "assets" / "spine_manifest.json"
    anchors_path = root / "assets" / "data" / "face_anchors.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        anchors = json.loads(anchors_path.read_text(encoding="utf-8"))
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            check=False,
            text=True,
            encoding="ascii",
            timeout=10,
        )
    except (OSError, UnicodeError, ValueError, subprocess.SubprocessError) as exc:
        raise BatchValidationError("无法读取 manifest 或 Face Anchor baseline") from exc
    generated_from_head = completed.stdout.strip().lower()
    if completed.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40,64}", generated_from_head):
        raise BatchValidationError("无法取得校准 baseline 对应的 Git HEAD")
    characters = manifest.get("characters") if isinstance(manifest, dict) else None
    anchor_records = anchors.get("records") if isinstance(anchors, dict) else None
    if not isinstance(characters, dict) or not isinstance(anchor_records, dict):
        raise BatchValidationError("manifest 或 Face Anchor 数据结构无效")

    records: list[tuple[str, dict[str, Any], dict[str, Any], float | None]] = []
    for render_id, entry in sorted(characters.items()):
        if not isinstance(entry, dict):
            raise BatchValidationError(f"manifest entry 无效: {render_id}")
        relative = entry.get("local_relpath")
        expected_hash = entry.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected_hash, str) or not re.fullmatch(
            r"[0-9a-fA-F]{64}", expected_hash
        ):
            raise BatchValidationError(f"manifest 缺少路径或 SHA-256: {render_id}")
        if entry.get("runtime_version") not in {"4.0", "4.1"}:
            raise BatchValidationError(f"manifest Spine runtime 版本无效: {render_id}")
        image_path = (root / relative).resolve(strict=False)
        if not image_path.is_relative_to(root) or not image_path.is_file():
            raise BatchValidationError(f"manifest PNG 缺失或越界: {render_id}")
        metrics = analyze_png(image_path)
        if metrics["sha256"] != expected_hash.lower():
            raise BatchValidationError(f"manifest PNG hash 不匹配: {render_id}")
        if entry.get("width") != metrics["dimensions"][0] or entry.get("height") != metrics["dimensions"][1]:
            raise BatchValidationError(f"manifest PNG 尺寸不匹配: {render_id}")
        # 当前生产 manifest 的 alpha_bbox 是裁切前 Spine 画布坐标；PNG 已裁到本地画布，
        # 因此视觉分布必须从经 SHA-256 绑定的落盘 PNG 重新测量 alpha bbox。
        anchor_ratio = _trusted_anchor_y_ratio(anchor_records.get(render_id), metrics)
        records.append((render_id, entry, metrics, anchor_ratio))
    if not records:
        raise BatchValidationError("manifest 中没有 verified portrait")

    distributions = {
        name: _distribution([float(metrics[name]) for _, _, metrics, _ in records])
        for name in VISUAL_METRICS
    }
    anchor_values = [ratio for _, _, _, ratio in records if ratio is not None]
    distributions["anchor_y_ratio"] = (
        _distribution(anchor_values) if anchor_values else {key: 0.0 for key in ("min", "p05", "median", "p95", "max")}
    )
    return {
        "schema_version": 1,
        "generated_from_head": generated_from_head,
        "source": "current manifest entries with matching PNG hash and dimensions; alpha metrics are recomputed from decoded bundled PNG bytes",
        "alpha_bbox_source": "decoded PNG pixel coordinates; manifest alpha_bbox may use pre-crop Spine canvas coordinates",
        "manifest_sha256": _sha256_file(manifest_path),
        "face_anchor_file_sha256": _sha256_file(anchors_path),
        "verified_portrait_count": len(records),
        "trusted_anchor_count": len(anchor_values),
        "hard_fail_count": 0,
        "render_ids": [render_id for render_id, _, _, _ in records],
        "verified_sources": [
            {
                "render_id": render_id,
                "runtime_version": entry.get("runtime_version"),
                "png_sha256": metrics["sha256"],
                "rgba_pixel_sha256": metrics["rgba_pixel_sha256"],
                "dimensions": metrics["dimensions"],
                "measured_alpha_bbox": metrics["alpha_bbox"],
                "trusted_anchor": anchor_ratio is not None,
            }
            for render_id, entry, metrics, anchor_ratio in records
        ],
        "distributions": distributions,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output_path = require_new_external_path(
            args.output, Path(__file__).resolve().parents[1], label="校准输出"
        )
        baseline = build_verified_baseline(args.repo_root)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("x", encoding="utf-8", newline="\n") as destination:
            destination.write(json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    except (OSError, UnicodeError, ValueError, subprocess.SubprocessError, BatchValidationError) as exc:
        print(f"baseline 生成失败: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"head": baseline["generated_from_head"], "verified_portraits": baseline["verified_portrait_count"], "trusted_anchors": baseline["trusted_anchor_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

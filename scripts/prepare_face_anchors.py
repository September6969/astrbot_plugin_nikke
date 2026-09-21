"""离线构建角色／皮肤锚点，绑定原始 PNG、骨架、atlas 及 idle 帧。"""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import re

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(ROOT))
from inspect_spine_bundle import _binary_spine_version
from features.character.spine_core_axis import (
    select_head_top,
    select_upper_torso_anchor,
    validate_axis_order,
)


def merge_records(old_records, rebuilt_records):
    """只替换本次清单记录，保留清单范围外的已验证 metadata。"""
    old_records = old_records if isinstance(old_records, dict) else {}
    rebuilt_records = rebuilt_records if isinstance(rebuilt_records, dict) else {}
    preserved = {
        key: value for key, value in old_records.items() if key not in rebuilt_records
    }
    merged = dict(old_records)
    merged.update(rebuilt_records)
    return merged, len(preserved)


def _load_entries(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return {}
    entries = raw.get("entries", raw) if isinstance(raw, dict) else {}
    return entries if isinstance(entries, dict) else {}


def _registry_key(render_id: str, manifest_entry: dict) -> str | None:
    """从正式资源身份得到 resource:costume registry key；不按序号猜服装。"""
    if isinstance(manifest_entry, dict):
        resource_id = manifest_entry.get("resource_id") or manifest_entry.get("character_resource_id")
        if resource_id is not None:
            costume_id = manifest_entry.get("costume_id")
            return f"{resource_id}:{costume_id if costume_id is not None else 'default'}"
    match = re.fullmatch(r"c(\d+)(?:_(\d+))?", str(render_id or ""))
    if not match or match.group(2) is not None:
        return None
    return f"{int(match.group(1))}:default"


def _role_override(entry: dict | None):
    if not isinstance(entry, dict):
        return None
    if "upper_torso" in entry:
        return entry["upper_torso"]
    # 兼容旧 schema 的 chest: "bone" 覆盖。
    return entry.get("chest")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--png-dir", type=Path, required=True)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--runtime-40", type=Path, required=True)
    parser.add_argument("--runtime-41", type=Path, required=True)
    parser.add_argument("--download-missing", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "assets/face_anchors.json")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))["characters"]
    args.bundle_dir.mkdir(parents=True, exist_ok=True)
    semantic_entries = _load_entries(ROOT / "assets/mappings/spine_bone_semantics.json")
    override_entries = _load_entries(ROOT / "assets/mappings/spine_bone_overrides.json")

    def one(pair):
        key, entry = pair
        try:
            if not re.fullmatch(r"c\d+(?:_\d+)?", key):
                raise ValueError("不支持的资源标识，不能推测 shared skin 的源骨架")
            for ext in ("skel", "atlas"):
                path = args.bundle_dir / f"{key}.{ext}"
                if not path.is_file() and args.download_missing:
                    response = httpx.get(f"https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/l2d/{key}/{key}_00.{ext}", timeout=20)
                    response.raise_for_status()
                    path.write_bytes(response.content)
            skel, atlas = args.bundle_dir / f"{key}.skel", args.bundle_dir / f"{key}.atlas"
            version = _binary_spine_version(skel)
            if version not in ("4.0", "4.1"):
                raise ValueError("未支持的 Spine 版本")
            runtime = args.runtime_40 if version == "4.0" else args.runtime_41
            sidecar = args.bundle_dir / f"{key}.anchor.json"
            subprocess.run(
                [
                    "node",
                    str(ROOT / "scripts/extract_spine_face_anchor.mjs"),
                    str(runtime),
                    str(skel),
                    str(atlas),
                    key,
                    "idle",
                    str(sidecar),
                ],
                check=True,
                capture_output=True,
                timeout=45,
            )
            record = json.loads(sidecar.read_text(encoding="utf-8"))
            registry_key = _registry_key(key, entry)
            semantic_entry = semantic_entries.get(registry_key) if registry_key else None
            override_entry = override_entries.get(registry_key) if registry_key else None
            torso, torso_reason = select_upper_torso_anchor(
                record.get("anatomy_bones_1024", []),
                existing_override=_role_override(override_entry),
                semantic_entry=semantic_entry,
                attachment_candidates=record.get("attachment_candidates_1024", []),
            )
            head_top, head_reason = select_head_top(
                record.get("head_surface_candidates_1024", [])
            )
            relative = entry.get("png_file") or entry.get("rendered_png")
            png = (args.png_dir / relative).resolve() if relative else (ROOT / entry["local_relpath"]).resolve()
            if not png.is_relative_to(args.png_dir.resolve()):
                raise ValueError("PNG 路径越界")
            with Image.open(png) as image:
                rgba = image.convert("RGBA")
                box = entry["alpha_bbox"]
                padding = entry.get("crop_padding", 16)
                render_width = entry.get("render_width", 1024)
                if (
                    type(padding) is not int
                    or type(render_width) is not int
                    or not 0 <= padding <= 256
                    or not 256 <= render_width <= 8192
                ):
                    raise ValueError("无效的 PNG 变换")
                if rgba.size != (
                    box[2] - box[0] + padding * 2,
                    box[3] - box[1] + padding * 2,
                ):
                    raise ValueError("PNG 裁切变换与清单不一致，拒绝猜测坐标")
                ratio = render_width / 1024

                def crop_point(point_1024):
                    return [
                        point_1024[0] * ratio - box[0] + padding,
                        point_1024[1] * ratio - box[1] + padding,
                    ]

                def crop_y(y_1024):
                    return y_1024 * ratio - box[1] + padding

                record["point"] = crop_point(record["point_1024"])
                record["extent"] = (
                    [value * ratio for value in record["extent_1024"]]
                    if record["extent_1024"]
                    else None
                )
                record.pop("core_axis", None)
                if torso is not None and head_top is not None:
                    torso_point = crop_point(list(torso.point))
                    head_top_y = crop_y(head_top.y)
                    if validate_axis_order(
                        head_top_y=head_top_y,
                        eye_y=record["point"][1],
                        torso_y=torso_point[1],
                    ) and (
                        0 <= head_top_y <= rgba.height
                        and 0 <= torso_point[0] <= rgba.width
                        and 0 <= torso_point[1] <= rgba.height
                    ):
                        record["core_axis"] = {
                            "eye_point": list(record["point"]),
                            "head_top_y": head_top_y,
                            "torso_point": torso_point,
                            "torso_source": torso.source,
                            "torso_confidence": torso.confidence,
                            # 旧 metadata 的读取方保持兼容；新代码使用 torso_point。
                            "breast_point": torso_point,
                            "head_top_source": head_top.source,
                            "breast_source": torso.source,
                        }
                        record["core_axis_reason"] = "ok"
                    else:
                        record["core_axis_reason"] = "invalid_axis_order"
                else:
                    record["core_axis_reason"] = (
                        torso_reason if torso is None else head_reason
                    )
                record["pixel_sha256"] = hashlib.sha256(rgba.tobytes()).hexdigest()
                record["png_sha256"] = hashlib.sha256(png.read_bytes()).hexdigest()
                record["image_size"] = list(rgba.size)
                record["png_transform"] = {
                    "render_size": [render_width, render_width],
                    "render_padding": .08,
                    "alpha_bbox": box,
                    "crop_padding": padding,
                }
                # 仅供 sidecar 发现的字段不进入运行时 metadata。
                record.pop("candidates", None)
                record.pop("anatomy_bones_1024", None)
                record.pop("head_surface_candidates_1024", None)
                record.pop("attachment_candidates_1024", None)
                return key, record
        except (OSError, ValueError, httpx.HTTPError, subprocess.SubprocessError) as exc:
            return key, {"error": type(exc).__name__, "reason": str(exc)[:200]}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        results = dict(executor.map(one, manifest.items()))
    good = {key: value for key, value in results.items() if "error" not in value}
    errors = {key: value for key, value in results.items() if "error" in value}
    # 同一皮肤可以有多个已校验分辨率，不因新增高清 PNG 破坏旧缓存构图。
    old_records = {}
    if args.output.is_file():
        old_records = json.loads(args.output.read_text(encoding="utf-8")).get("records", {})
        for key, record in good.items():
            previous = old_records.get(key, {})
            if isinstance(previous.get("framing"), dict):
                record["framing"] = previous["framing"]
            candidates = [previous, *previous.get("variants", [])]
            variants = {}
            for candidate in candidates:
                digest = candidate.get("pixel_sha256")
                if digest and digest != record["pixel_sha256"]:
                    variants[digest] = {k: v for k, v in candidate.items() if k != "variants"}
            if variants:
                record["variants"] = list(variants.values())
    merged, preserved_count = merge_records(old_records, good)
    args.output.write_text(
        json.dumps(
            {"schema": 1, "records": merged, "unavailable": errors},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({
        "prepared": len(good),
        "preserved": preserved_count,
        "unavailable": errors,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

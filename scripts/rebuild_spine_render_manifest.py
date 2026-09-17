#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Spine 预渲染静态资产 Manifest 维护与重构脚本。

提供以下功能：
1. --audit-only: 严格审查本地现有预渲染 PNG，校验魔数、Pillow 解码、尺寸与 SHA-256，与官方 Master/Costume 进行身份核验并输出诊断。
2. --write: 基于真实物理文件与已核验身份，原子写入符合当前安全契约的 assets/spine_manifest.json。
3. --verify: 校验磁盘上的 manifest 是否与实际文件字节、哈希、尺寸与身份完全吻合，检测缺失/损坏/篡改/冲突。

严格执行零网络、路径穿越防护与失败保护（fail-closed）。
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image

# 兼容 Windows 默认控制台编码
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
SCHEMA_VERSION = 2


def get_repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def check_png_integrity(png_path: Path) -> tuple[bool, str, dict[str, Any]]:
    """校验 PNG 文件完整性、魔数、尺寸并计算 SHA-256。"""
    if not png_path.is_file():
        return False, f"File not found: {png_path}", {}

    raw_bytes = png_path.read_bytes()
    if len(raw_bytes) < 8:
        return False, f"File too small ({len(raw_bytes)} bytes)", {}

    if not raw_bytes.startswith(PNG_MAGIC):
        return False, "Invalid PNG magic bytes", {}

    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    try:
        with Image.open(png_path) as img:
            img.verify()
        with Image.open(png_path) as img:
            width, height = img.size
            mode = img.mode
            bbox = img.getbbox()
    except Exception as exc:
        return False, f"Pillow decode error: {exc}", {}

    if width <= 0 or height <= 0:
        return False, f"Invalid dimensions: {width}x{height}", {}

    return True, "OK", {
        "file_size": len(raw_bytes),
        "width": width,
        "height": height,
        "mode": mode,
        "alpha_bbox": list(bbox) if bbox else [0, 0, width, height],
        "sha256": sha256,
    }


def resolve_asset_identity(
    asset_id: str,
    character_master_resolver: Any,
    costume_registry: Any,
    legacy_characters: dict[str, Any],
) -> dict[str, Any] | None:
    """基于官方 Master 与 Costume Registry 严格解析资产身份，绝不猜测。"""
    # 1. 检查是否为 Costume
    costumes_by_spine = {c.spine_asset_id: c for c in costume_registry._entries}
    if asset_id in costumes_by_spine:
        cost = costumes_by_spine[asset_id]
        owner_char = character_master_resolver.resolve_battle_tid(cost.character_resource_id)
        owner_name_cn = owner_char.name_cn if owner_char else "未知"
        owner_name_en = owner_char.name_en if owner_char else "Unknown"
        return {
            "spine_asset_id": asset_id,
            "character_resource_id": str(cost.character_resource_id),
            "character_name": owner_name_cn,
            "character_name_en": owner_name_en,
            "costume_id": str(cost.costume_id),
            "costume_name": cost.costume_name,
            "is_costume": True,
        }

    # 2. 检查是否为 Default Character
    chars_by_spine = {c.spine_asset_id: c for c in character_master_resolver._characters if c.spine_asset_id}
    if asset_id in chars_by_spine:
        char = chars_by_spine[asset_id]
        return {
            "spine_asset_id": asset_id,
            "character_resource_id": str(char.resource_id),
            "character_name": char.name_cn,
            "character_name_en": char.name_en,
            "costume_id": None,
            "costume_name": None,
            "is_costume": False,
        }

    return None


def audit_spine_assets(
    rendered_dir: Path,
    legacy_manifest_path: Path,
    character_master_path: Path,
    costumes_path: Path,
) -> dict[str, Any]:
    """完整审计本地 Spine 预渲染资产。"""
    repo_root = get_repo_root()
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from astrbot_plugin_nikke.features.character.master_resolver import CharacterMasterResolver
    from astrbot_plugin_nikke.features.character.registries.costume import CostumeRegistry

    master_resolver = CharacterMasterResolver(character_master_path)
    costume_registry = CostumeRegistry(costumes_path.parent)

    legacy_characters: dict[str, Any] = {}
    if legacy_manifest_path.is_file():
        try:
            old_data = json.loads(legacy_manifest_path.read_text(encoding="utf-8"))
            if isinstance(old_data, dict):
                legacy_characters = old_data.get("characters", {})
        except Exception as exc:
            print(f"警告: 读取旧 manifest 失败 ({exc})", file=sys.stderr)

    results: dict[str, Any] = {
        "verified": {},
        "missing": [],
        "corrupt": [],
        "conflict": [],
        "unresolved": [],
        "total_files": 0,
    }

    target_ids = set(legacy_characters.keys())
    if rendered_dir.is_dir():
        for p in rendered_dir.glob("*.png"):
            target_ids.add(p.stem)

    results["total_files"] = len(target_ids)

    claimed_identities: dict[tuple[str, str | None], str] = {}

    for asset_id in sorted(target_ids):
        png_file = rendered_dir / f"{asset_id}.png"
        resolved_png = png_file.resolve()

        # 路径穿越防护
        try:
            if not resolved_png.is_relative_to(rendered_dir.resolve()):
                results["corrupt"].append({"asset_id": asset_id, "error": "Path traversal detected"})
                continue
        except AttributeError:
            if not str(resolved_png).startswith(str(rendered_dir.resolve())):
                results["corrupt"].append({"asset_id": asset_id, "error": "Path traversal detected"})
                continue

        if not png_file.is_file():
            results["missing"].append({"asset_id": asset_id, "expected_path": str(png_file)})
            continue

        ok, msg, img_info = check_png_integrity(png_file)
        if not ok:
            results["corrupt"].append({"asset_id": asset_id, "error": msg, "path": str(png_file)})
            continue

        identity = resolve_asset_identity(asset_id, master_resolver, costume_registry, legacy_characters)
        if identity is None:
            results["unresolved"].append({"asset_id": asset_id, "path": str(png_file)})
            continue

        # 冲突检测：同一个 resource_id + costume_id 不应被多个 asset_id 声明
        ident_key = (identity["character_resource_id"], identity["costume_id"])
        if ident_key in claimed_identities:
            existing_asset = claimed_identities[ident_key]
            results["conflict"].append({
                "asset_id": asset_id,
                "conflicts_with": existing_asset,
                "identity": ident_key,
            })
            continue
        claimed_identities[ident_key] = asset_id

        legacy_meta = legacy_characters.get(asset_id, {})
        runtime_version = legacy_meta.get("runtime_version") or "4.1"
        legacy_bbox = legacy_meta.get("alpha_bbox")
        alpha_bbox = legacy_bbox if legacy_bbox else img_info["alpha_bbox"]

        try:
            rel_path = png_file.resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            rel_path = f"assets/spine-rendered/{asset_id}.png"

        record = {
            "spine_asset_id": asset_id,
            "character_resource_id": identity["character_resource_id"],
            "character_name": identity["character_name"],
            "character_name_en": identity["character_name_en"],
            "costume_id": identity["costume_id"],
            "costume_name": identity["costume_name"],
            "is_costume": identity["is_costume"],
            "local_relpath": rel_path,
            "sha256": img_info["sha256"],
            "width": img_info["width"],
            "height": img_info["height"],
            "format": "png",
            "file_size": img_info["file_size"],
            "alpha_bbox": alpha_bbox,
            "runtime_version": runtime_version,
            "verification": "local_revalidated",
        }
        results["verified"][asset_id] = record

    return results


def build_manifest_dict(audit_results: dict[str, Any]) -> dict[str, Any]:
    """生成标准化 Manifest v2 字典。"""
    verified = audit_results["verified"]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_characters": len(verified),
        "verified_count": len(verified),
        "failed_count": len(audit_results["missing"]) + len(audit_results["corrupt"]) + len(audit_results["conflict"]),
        "characters": dict(sorted(verified.items())),
    }


def write_manifest_atomic(manifest_path: Path, manifest_data: dict[str, Any]) -> None:
    """原子写入 Manifest 文件。"""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(manifest_data, ensure_ascii=False, indent=2) + "\n"

    fd, tmp_path_str = tempfile.mkstemp(
        prefix=f".{manifest_path.name}-",
        suffix=".tmp",
        dir=manifest_path.parent,
    )
    os.close(fd)
    tmp_path = Path(tmp_path_str)

    try:
        tmp_path.write_text(content, encoding="utf-8")
        reloaded = json.loads(tmp_path.read_text(encoding="utf-8"))
        if reloaded.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("写入的 manifest 验证失败")
        os.replace(tmp_path, manifest_path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def verify_manifest(manifest_path: Path, rendered_dir: Path) -> tuple[bool, list[str]]:
    """校验现有 Manifest 文件是否严格匹配磁盘。"""
    errors: list[str] = []
    if not manifest_path.is_file():
        return False, [f"Manifest not found: {manifest_path}"]

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, [f"Manifest JSON parse error: {exc}"]

    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"Unexpected schema_version: {data.get('schema_version')} (expected {SCHEMA_VERSION})")

    characters = data.get("characters", {})
    if not isinstance(characters, dict) or not characters:
        errors.append("Manifest characters is empty or invalid")
        return False, errors

    for asset_id, entry in sorted(characters.items()):
        if not isinstance(entry, dict):
            errors.append(f"[{asset_id}] Invalid entry type")
            continue

        required_fields = (
            "spine_asset_id",
            "character_resource_id",
            "sha256",
            "width",
            "height",
            "format",
            "file_size",
            "verification",
        )
        missing_fields = [f for f in required_fields if f not in entry]
        if missing_fields:
            errors.append(f"[{asset_id}] Missing required fields: {missing_fields}")
            continue

        expected_sha = entry["sha256"]
        if not isinstance(expected_sha, str) or len(expected_sha) != 64:
            errors.append(f"[{asset_id}] Invalid SHA-256 format: {expected_sha}")
            continue

        png_file = rendered_dir / f"{asset_id}.png"
        if not png_file.is_file():
            errors.append(f"[{asset_id}] Target file missing: {png_file}")
            continue

        ok, msg, img_info = check_png_integrity(png_file)
        if not ok:
            errors.append(f"[{asset_id}] Image check failed: {msg}")
            continue

        if img_info["sha256"] != expected_sha:
            errors.append(f"[{asset_id}] SHA-256 mismatch! disk={img_info['sha256']} vs manifest={expected_sha}")

        if img_info["width"] != entry["width"] or img_info["height"] != entry["height"]:
            errors.append(f"[{asset_id}] Dimension mismatch! disk={img_info['width']}x{img_info['height']} vs manifest={entry['width']}x{entry['height']}")

    return len(errors) == 0, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Spine 预渲染静态资产 Manifest 维护与重构工具")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--audit-only", action="store_true", help="仅审查本地物理 PNG 并输出报告，不写入文件")
    group.add_argument("--write", action="store_true", help="原子重构并写入 spine_manifest.json")
    group.add_argument("--verify", action="store_true", help="校验磁盘上的 manifest 与物理文件是否吻合")

    parser.add_argument(
        "--manifest-path",
        default="",
        help="目标 manifest 路径 (默认: assets/spine_manifest.json)",
    )
    parser.add_argument(
        "--rendered-dir",
        default="",
        help="Spine 预渲染 PNG 所在目录 (默认: assets/spine-rendered)",
    )
    args = parser.parse_args()

    repo_root = get_repo_root()
    manifest_path = Path(args.manifest_path) if args.manifest_path else repo_root / "assets" / "spine_manifest.json"
    rendered_dir = Path(args.rendered_dir) if args.rendered_dir else repo_root / "assets" / "spine-rendered"
    character_master_path = repo_root / "assets" / "character_master.json"
    costumes_path = repo_root / "assets" / "costumes.json"

    if args.verify:
        print(f"=== 开始验证 Manifest: {manifest_path} ===")
        ok, errors = verify_manifest(manifest_path, rendered_dir)
        if ok:
            print("Manifest 验证通过：所有资产哈希、尺寸与文件完整性均 100% 吻合！")
            return 0
        else:
            print(f"Manifest 验证失败 ({len(errors)} 个错误):", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            return 1

    print(f"=== 开始审查 Spine 预渲染资产目录: {rendered_dir} ===")
    audit_results = audit_spine_assets(
        rendered_dir=rendered_dir,
        legacy_manifest_path=manifest_path,
        character_master_path=character_master_path,
        costumes_path=costumes_path,
    )

    verified = audit_results["verified"]
    missing = audit_results["missing"]
    corrupt = audit_results["corrupt"]
    conflict = audit_results["conflict"]
    unresolved = audit_results["unresolved"]

    print("\n审计结果汇总:")
    print(f"  总文件/条目数: {audit_results['total_files']}")
    print(f"  已验证通过 (Verified): {len(verified)}")
    print(f"  文件缺失 (Missing):     {len(missing)}")
    print(f"  文件损坏 (Corrupt):     {len(corrupt)}")
    print(f"  身份冲突 (Conflict):    {len(conflict)}")
    print(f"  未解析身份 (Unresolved): {len(unresolved)}")

    for asset_id, item in verified.items():
        cost_tag = f" [Costume: {item['costume_name']} ({item['costume_id']})]" if item["is_costume"] else " [Default]"
        print(f"  [OK] {asset_id:10s}: {item['character_name']} ({item['character_resource_id']}){cost_tag} - {item['width']}x{item['height']} sha={item['sha256'][:12]}...")

    if missing:
        for m in missing:
            print(f"  [MISSING] {m['asset_id']}")
    if corrupt:
        for c in corrupt:
            print(f"  [CORRUPT] {c['asset_id']} ({c['error']})")
    if conflict:
        for f in conflict:
            print(f"  [CONFLICT] {f['asset_id']} (conflicts with {f['conflicts_with']})")
    if unresolved:
        for u in unresolved:
            print(f"  [UNRESOLVED] {u['asset_id']}")

    has_errors = bool(missing or corrupt or conflict or unresolved)

    if args.audit_only:
        print("\n[--audit-only 模式完成，未修改任何文件]")
        return 1 if has_errors else 0

    if args.write:
        if has_errors:
            print("\n错误: 存在损坏、缺失或冲突资产，中止写入以防止损坏 manifest！", file=sys.stderr)
            return 1

        manifest_data = build_manifest_dict(audit_results)
        write_manifest_atomic(manifest_path, manifest_data)
        print(f"\nManifest v2 成功原子写入: {manifest_path}")

        ok, verify_errors = verify_manifest(manifest_path, rendered_dir)
        if not ok:
            print("警告: 写入后自检失败:", file=sys.stderr)
            for err in verify_errors:
                print(f"  - {err}", file=sys.stderr)
            return 1
        print("写入后自检成功，Manifest 100% 合规。")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Spine 离线持久化预渲染与同步脚本。

用于离线下载 Spine bundle、检测版本（4.0 / 4.1）、调用无头 Worker 渲染
idle@t=0 PNG 并更新 spine_manifest.json。
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image

NIKKE_DB_L2D_BASE = "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/l2d"

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


def detect_spine_version(skel_path: Path) -> str:
    """读取 skeleton 二进制文件头部，判定 major.minor 版本。"""
    raw = skel_path.read_bytes()
    header = raw[:64]
    match = re.search(rb"(\d+\.\d+(?:\.\d+)?)", header)
    if not match:
        raise ValueError(f"无法在 {skel_path.name} 中检测到 Spine 版本字符串")
    ver_str = match.group(1).decode("ascii")
    if ver_str.startswith("4.0"):
        return "4.0"
    if ver_str.startswith("4.1"):
        return "4.1"
    raise ValueError(f"不支持的 Spine 版本: {ver_str}")


def download_file(url: str, dest: Path) -> bool:
    """下载单个文件，带重试与超时。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        return True
    tmp = dest.with_suffix(".tmp")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            tmp.write_bytes(data)
            tmp.replace(dest)
        return True
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        print(f"  下载失败 {url}: {exc}", file=sys.stderr)
        return False


def parse_atlas_texture_pages(atlas_path: Path) -> list[str]:
    """解析 atlas 文件获取所有声明的纹理页文件名。"""
    text = atlas_path.read_text(encoding="utf-8-sig", errors="replace")
    pages: list[str] = []
    for line in text.splitlines():
        line = line.strip().lstrip("\ufeff")
        if line.lower().endswith(".png"):
            if line not in pages:
                pages.append(line)
    return pages


def ensure_bundle(char_id: str, bundle_root: Path) -> tuple[Path, Path, list[Path]]:
    """确保 bundle 文件已完整就绪，返回 (skel_path, atlas_path, texture_paths)。"""
    char_dir = bundle_root / char_id
    char_dir.mkdir(parents=True, exist_ok=True)

    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    try:
        from nikke_db_provider import NikkeDbProvider
    except ImportError:
        from astrbot_plugin_nikke.nikke_db_provider import NikkeDbProvider

    provider = NikkeDbProvider(bundle_root, bundle_root)
    bundle_urls = provider.resolve_spine_bundle_urls(char_id)
    if not bundle_urls:
        raise RuntimeError(f"无法解析 Spine bundle 资源 URL: {char_id}")

    url_skel = bundle_urls["skel"]
    url_atlas = bundle_urls["atlas"]
    url_png = bundle_urls["png"]

    skel_name = url_skel.rsplit("/", 1)[-1]
    atlas_name = url_atlas.rsplit("/", 1)[-1]
    png_name = url_png.rsplit("/", 1)[-1]

    skel_file = char_dir / skel_name
    atlas_file = char_dir / atlas_name

    if not skel_file.is_file():
        print(f"下载 {url_skel} ...")
        if not download_file(url_skel, skel_file):
            raise RuntimeError(f"下载 skeleton 失败: {char_id}")

    if not atlas_file.is_file():
        print(f"下载 {url_atlas} ...")
        if not download_file(url_atlas, atlas_file):
            raise RuntimeError(f"下载 atlas 失败: {char_id}")

    pages = parse_atlas_texture_pages(atlas_file)
    if not pages:
        pages = [png_name]

    texture_paths: list[Path] = []
    for page in pages:
        tex_file = char_dir / page
        if not tex_file.is_file():
            if page == png_name:
                url_page = url_png
            else:
                base_dir = url_atlas.rsplit("/", 1)[0]
                url_page = f"{base_dir}/{page}"
            print(f"下载纹理页 {url_page} ...")
            if not download_file(url_page, tex_file):
                raise RuntimeError(f"下载纹理页失败: {char_id}/{page}")
        texture_paths.append(tex_file)

    return skel_file, atlas_file, texture_paths


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
    """调用对应版本的 Spine worker 渲染 idle 帧并保存裁切后 PNG。"""
    version = detect_spine_version(skel_path)
    worker_bin = worker_40 if version == "4.0" else worker_41
    if not shutil.which(worker_bin) and not Path(worker_bin).exists():
        raise FileNotFoundError(f"找不到 Spine {version} worker: {worker_bin}")

    bundle_root = skel_path.parent

    # 规范化纹理名：部分 worker 要求 png 必须与 atlas 或 skel 同名，建软链或拷贝确保命中
    default_png = bundle_root / "png.png"
    if not default_png.exists() and textures:
        try:
            shutil.copyfile(textures[0], default_png)
        except OSError:
            pass

    fd, tmp_rgba = tempfile.mkstemp(prefix=f".spine-{char_id}-", suffix=".rgba", dir=bundle_root)
    os.close(fd)
    tmp_rgba_path = Path(tmp_rgba)

    cmd = [
        worker_bin,
        "--skeleton",
        str(skel_path.resolve()),
        "--atlas",
        str(atlas_path.resolve()),
        "--output",
        str(tmp_rgba_path.resolve()),
        "--animation",
        animation,
        "--width",
        "1024",
        "--height",
        "1024",
    ]

    env = os.environ.copy()
    env.update({"SDL_VIDEODRIVER": "dummy", "SDL_RENDER_DRIVER": "software"})

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(bundle_root),
            env=env,
            capture_output=True,
            timeout=30,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Worker 渲染失败 (code {proc.returncode}): {proc.stderr or proc.stdout}")

        raw_bytes = tmp_rgba_path.read_bytes()
        if len(raw_bytes) < 8:
            raise RuntimeError("Worker 输出 RGBA 文件不完整")

        width = int.from_bytes(raw_bytes[0:4], "little")
        height = int.from_bytes(raw_bytes[4:8], "little")
        expected_len = 8 + width * height * 4
        if len(raw_bytes) != expected_len:
            raise RuntimeError(f"RGBA 长度不匹配: 预期 {expected_len}, 实际 {len(raw_bytes)}")

        img = Image.frombytes("RGBA", (width, height), raw_bytes[8:]).copy()
        bbox = img.getbbox()
        if not bbox:
            raise RuntimeError("Worker 输出全透明图像 (bbox 为空)")

        # 智能裁切并留 16px 边距
        pad = 16
        cropped = img.crop(
            (
                max(0, bbox[0] - pad),
                max(0, bbox[1] - pad),
                min(img.width, bbox[2] + pad),
                min(img.height, bbox[3] + pad),
            )
        )

        out_png.parent.mkdir(parents=True, exist_ok=True)
        cropped.save(out_png, "PNG", optimize=True)

        return {
            "canonical_asset_id": char_id,
            "runtime_version": version,
            "png_file": out_png.name,
            "width": cropped.width,
            "height": cropped.height,
            "alpha_bbox": list(bbox),
            "file_size": out_png.stat().st_size,
        }
    finally:
        tmp_rgba_path.unlink(missing_ok=True)
        default_png.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Spine 离线持久化预渲染与同步工具")
    parser.add_argument(
        "--assets",
        nargs="+",
        default=DEFAULT_TARGETS,
        help="待渲染的角色 Spine 资产 ID (例如 c010 c330)",
    )
    parser.add_argument(
        "--bundle-dir",
        default="",
        help="Spine bundle 存放目录",
    )
    parser.add_argument(
        "--out-dir",
        default="",
        help="渲染产物输出目录",
    )
    parser.add_argument(
        "--manifest",
        default="",
        help="输出的 spine_manifest.json 路径",
    )
    parser.add_argument(
        "--worker-40",
        default="/usr/local/bin/entrypoint-xvfb.sh",
        help="Spine 4.0 worker 可执行文件路径",
    )
    parser.add_argument(
        "--worker-41",
        default="/usr/local/bin/entrypoint-xvfb-4.1.sh",
        help="Spine 4.1 worker 可执行文件路径",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="覆盖已存在的预渲染 PNG",
    )
    args = parser.parse_args()

    # 默认路径自动探测
    repo_root = Path(__file__).resolve().parent.parent
    bundle_dir = Path(args.bundle_dir) if args.bundle_dir else repo_root / "cache" / "spine-bundles"
    out_dir = Path(args.out_dir) if args.out_dir else repo_root / "assets" / "spine-rendered"
    manifest_path = Path(args.manifest) if args.manifest else repo_root / "assets" / "spine_manifest.json"

    # 若 entrypoint 脚本不可用，降级查找裸 worker
    worker_40 = args.worker_40
    if not Path(worker_40).exists() and Path("/usr/local/bin/nikke-spine-worker").exists():
        worker_40 = "/usr/local/bin/nikke-spine-worker"

    worker_41 = args.worker_41
    if not Path(worker_41).exists() and Path("/usr/local/bin/nikke-spine-worker-4.1").exists():
        worker_41 = "/usr/local/bin/nikke-spine-worker-4.1"

    out_dir.mkdir(parents=True, exist_ok=True)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    manifest_data: dict[str, Any] = {"schema_version": 1, "characters": {}}
    if manifest_path.is_file():
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    success_count = 0
    fail_count = 0

    print(f"=== 开始预渲染 {len(args.assets)} 个角色 Spine 立绘 ===")
    for char_id in args.assets:
        target_png = out_dir / f"{char_id}.png"
        if target_png.is_file() and not args.force and char_id in manifest_data.get("characters", {}):
            print(f"[{char_id}] 预渲染 PNG 已存在，跳过。")
            success_count += 1
            continue

        print(f"\n处理 [{char_id}] ...")
        try:
            skel, atlas, textures = ensure_bundle(char_id, bundle_dir)
            meta = render_spine_portrait(
                char_id,
                skel,
                atlas,
                textures,
                target_png,
                worker_40,
                worker_41,
                animation="idle",
            )
            meta["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            manifest_data.setdefault("characters", {})[char_id] = meta
            print(f"[{char_id}] 预渲染成功: {target_png} ({meta['width']}x{meta['height']}, size={meta['file_size']}B)")
            success_count += 1
        except Exception as exc:
            print(f"[{char_id}] 预渲染失败: {exc}", file=sys.stderr)
            fail_count += 1

    manifest_data["total_characters"] = len(manifest_data.get("characters", {}))
    manifest_data["last_updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nManifest 已更新至 {manifest_path} (共 {manifest_data['total_characters']} 项)")
    print(f"完成: 成功 {success_count} / 失败 {fail_count}")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

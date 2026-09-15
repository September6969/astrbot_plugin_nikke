#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Spine 离线持久化预渲染与同步脚本。

支持：
1. --all: 读取 character_master.json 全量 200 个角色的 canonical Spine ID
2. --nikke-db-root: 本地 Nikke-db 仓库检出目录，通过 LocalSpineBundleResolver 严格从本地读取
3. 单一持久化 Xvfb 会话，原生无头调用 4.0 / 4.1 Worker 渲染 idle 帧
4. 生成规范 Manifest v2 与覆盖率报告
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image

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
    if "DISPLAY" not in env:
        env["DISPLAY"] = ":99"
    env.update({"SDL_VIDEODRIVER": "dummy", "SDL_RENDER_DRIVER": "software"})

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(bundle_root),
            env=env,
            capture_output=True,
            timeout=45,
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


def _resolve_worker_bin(preferred: str, candidates: list[str]) -> str:
    if preferred and (shutil.which(preferred) or Path(preferred).exists()):
        return preferred
    for c in candidates:
        if c and (shutil.which(c) or Path(c).exists()):
            return c
    return preferred


def main() -> int:
    parser = argparse.ArgumentParser(description="Spine 离线持久化预渲染与同步工具")
    parser.add_argument(
        "--all",
        action="store_true",
        help="从 character_master.json 读取全部角色的 canonical Spine ID 进行全量预渲染",
    )
    parser.add_argument(
        "--assets",
        nargs="+",
        default=None,
        help="待渲染的角色 Spine 资产 ID (例如 c010 c330)",
    )
    parser.add_argument(
        "--nikke-db-root",
        default="",
        help="本地 Nikke-db 检出目录 (例如 /opt/nikke-bot/vendor/nikke-db)，优先从本地解析 bundle",
    )
    parser.add_argument(
        "--bundle-dir",
        default="",
        help="Spine bundle 存放目录（网络下载时的临时目录）",
    )
    parser.add_argument(
        "--out-dir",
        default="",
        help="渲染产物输出目录",
    )
    parser.add_argument(
        "--manifest",
        default="",
        help="输出的 spine-manifest.json 路径",
    )
    parser.add_argument(
        "--manifest-path",
        default="",
        help="--manifest 的别名",
    )
    parser.add_argument(
        "--worker-40",
        default="",
        help="Spine 4.0 worker 可执行文件路径",
    )
    parser.add_argument(
        "--worker-41",
        default="",
        help="Spine 4.1 worker 可执行文件路径",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="覆盖已存在的预渲染 PNG",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    # 确定目标角色清单
    if args.all:
        master_path = repo_root / "assets" / "character_master.json"
        if not master_path.is_file():
            print(f"错误: 找不到 {master_path}", file=sys.stderr)
            return 1
        master_data = json.loads(master_path.read_text(encoding="utf-8"))
        chars = master_data.get("characters", [])
        char_ids = sorted(list(set(c["spine_asset_id"] for c in chars if c.get("spine_asset_id"))))
        targets = char_ids
    elif args.assets:
        targets = args.assets
    else:
        targets = DEFAULT_TARGETS

    # 确定输出路径
    out_dir = Path(args.out_dir) if args.out_dir else repo_root / "assets" / "spine-rendered"
    manifest_arg = args.manifest_path or args.manifest
    manifest_path = Path(manifest_arg) if manifest_arg else repo_root / "assets" / "spine-manifest.json"
    bundle_dir = Path(args.bundle_dir) if args.bundle_dir else repo_root / "cache" / "spine-bundles"

    out_dir.mkdir(parents=True, exist_ok=True)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    # 自动定位 Worker 二进制：优先直接使用裸二进制，其次使用 wrapper 脚本
    worker_40 = _resolve_worker_bin(
        args.worker_40,
        [
            "/usr/local/bin/nikke-spine-worker",
            "/AstrBot/data/spine-worker/nikke-spine-worker",
            "/opt/nikke-bot/astrbot/data/spine-worker/nikke-spine-worker",
            "/AstrBot/data/spine-worker/entrypoint-xvfb.sh",
            "/opt/nikke-bot/astrbot/data/spine-worker/entrypoint-xvfb.sh",
        ],
    )
    worker_41 = _resolve_worker_bin(
        args.worker_41,
        [
            "/usr/local/bin/nikke-spine-worker-4.1",
            "/AstrBot/data/spine-worker-4.1/nikke-spine-worker-4.1",
            "/opt/nikke-bot/astrbot/data/spine-worker-4.1/nikke-spine-worker-4.1",
            "/AstrBot/data/spine-worker-4.1/entrypoint-xvfb-4.1.sh",
            "/opt/nikke-bot/astrbot/data/spine-worker-4.1/entrypoint-xvfb-4.1.sh",
        ],
    )

    # 本地解析器
    local_resolver = None
    if args.nikke_db_root:
        from local_spine_resolver import LocalSpineBundleResolver
        local_resolver = LocalSpineBundleResolver(args.nikke_db_root)
        print(f"启用本地 Nikke-db 检出解析: {local_resolver.local_root}")

    # 读取已有 manifest (schema v2)
    manifest_data: dict[str, Any] = {
        "schema_version": 2,
        "source": "local_nikke_db" if local_resolver else "remote_nikke_db",
        "characters": {},
    }
    if manifest_path.is_file():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                manifest_data["characters"] = loaded.get("characters", {})
        except (OSError, ValueError):
            pass

    # 若使用裸 worker，且在 Linux 下未运行 X，启动一个持久化的单一 Xvfb 进程
    xvfb_proc = None
    if sys.platform.startswith("linux") and shutil.which("Xvfb"):
        try:
            subprocess.run(["sh", "-c", "killall Xvfb 2>/dev/null || true; rm -f /tmp/.X99-lock /tmp/.X11-unix/X99"], check=False)
            xvfb_proc = subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1024x1024x24", "-nolisten", "tcp"])
            time.sleep(0.3)
            os.environ["DISPLAY"] = ":99"
        except Exception as exc:
            print(f"警告: 启动背景 Xvfb 失败: {exc}", file=sys.stderr)

    success_count = 0
    fail_count = 0
    missing_bundles: list[str] = []
    render_errors: list[tuple[str, str]] = []

    print(f"=== 开始处理 {len(targets)} 个角色的 Spine 立绘 (输出: {out_dir}) ===")
    try:
        for idx, char_id in enumerate(targets, 1):
            target_png = out_dir / f"{char_id}.png"
            if target_png.is_file() and not args.force and char_id in manifest_data["characters"]:
                success_count += 1
                continue

            try:
                if local_resolver is not None:
                    bundle = local_resolver.resolve_bundle(char_id)
                    if bundle is None:
                        missing_bundles.append(char_id)
                        fail_count += 1
                        continue
                    skel, atlas, textures = bundle.skel_path, bundle.atlas_path, bundle.texture_paths
                else:
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
                manifest_data["characters"][char_id] = meta
                print(f"[{idx}/{len(targets)}] [{char_id}] 预渲染成功: {target_png.name} ({meta['width']}x{meta['height']}, size={meta['file_size']}B)")
                success_count += 1
            except Exception as exc:
                print(f"[{idx}/{len(targets)}] [{char_id}] 预渲染失败: {exc}", file=sys.stderr)
                render_errors.append((char_id, str(exc)))
                fail_count += 1
    finally:
        if xvfb_proc is not None:
            try:
                xvfb_proc.terminate()
                xvfb_proc.wait(timeout=2)
            except Exception:
                xvfb_proc.kill()
            subprocess.run(["sh", "-c", "rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null || true"], check=False)

    manifest_data["total_characters"] = len(targets)
    manifest_data["rendered_count"] = success_count
    manifest_data["failed_count"] = fail_count
    manifest_data["last_updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest_data, ensure_ascii=False, indent=2), encoding="utf-8")

    total = len(targets)
    pct = (success_count / total * 100.0) if total > 0 else 0.0
    print("\n" + "=" * 50)
    print("Spine 资产预渲染流水线覆盖报告")
    print("=" * 50)
    print(f"目标角色总数: {total}")
    print(f"成功 / 已就绪: {success_count} ({pct:.1f}%)")
    print(f"失败 / 未就绪: {fail_count}")
    if missing_bundles:
        print(f"本地缺少 bundle ({len(missing_bundles)}): {missing_bundles[:10]}{'...' if len(missing_bundles) > 10 else ''}")
    if render_errors:
        print(f"渲染错误条数: {len(render_errors)}")
    print(f"Manifest v2 已写入: {manifest_path}")
    print("=" * 50 + "\n")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

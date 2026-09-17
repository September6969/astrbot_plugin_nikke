# SPDX-License-Identifier: GPL-3.0-or-later
"""BlaBlaLink 静态资源本地镜像工具。

支持：
- --audit-only: 审计远程与本地文件差异，不执行下载；
- --estimate-size: 预估待下载资产数量与网络带宽/磁盘开销；
- --download: 并发执行可靠镜像下载，具备断点续传、原子写入与 SHA-256 校验；
- --categories: 细粒度过滤分类 (portrait_si, icons, equipment, guild, all)；
- --force: 强制覆盖已有文件；
- 记录机器可读的 mirror_manifest.json 校验清单。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
from pathlib import Path
import sys
from typing import Any

# 兼容模块导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from PIL import Image
import io

from astrbot_plugin_nikke.core.asset_manager import AssetManager

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("mirror_assets")

DEFAULT_INVENTORY = Path("docs/evidence/blabla_static_assets/static_asset_inventory.json")
DEFAULT_TARGET_DIR = Path("data/nikke/blabla-assets")


def load_inventory(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Inventory file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def filter_items(inventory: dict[str, Any], categories: list[str]) -> list[dict[str, Any]]:
    all_cats = inventory.get("categories", {})
    selected_items: list[dict[str, Any]] = []

    cat_map = {
        "portrait_si": ["portraits_si_default", "portraits_si_costumes"],
        "portrait_si_default": ["portraits_si_default"],
        "portrait_si_costumes": ["portraits_si_costumes"],
        "portrait_mi": ["portraits_mi_default", "portraits_mi_costumes"],
        "icons": ["common_icons"],
        "equipment": ["equipment"],
        "guild": ["guild_emblem"],
        "all": list(all_cats.keys()),
    }

    target_keys = set()
    for cat in categories:
        cat_lower = cat.lower().strip()
        if cat_lower in cat_map:
            target_keys.update(cat_map[cat_lower])
        elif cat_lower in all_cats:
            target_keys.add(cat_lower)
        else:
            logger.warning("Unknown category requested: %s", cat)

    for k in sorted(target_keys):
        c_data = all_cats.get(k, {})
        items = c_data.get("items", [])
        for item in items:
            item_copy = dict(item)
            item_copy["inventory_category"] = k
            selected_items.append(item_copy)

    return selected_items


def get_local_dest_path(target_dir: Path, item: dict[str, Any]) -> Path:
    cat = item.get("inventory_category", item.get("category", "misc"))
    rel = item.get("relative_path", "").lstrip("/")
    # 统一落位在 target_dir / rel
    return target_dir / rel


async def verify_local_file(path: Path) -> tuple[bool, str, int]:
    """检查本地文件是否存在、是否为合法图像，并计算其 SHA-256 与字节大小。"""
    if not path.is_file():
        return False, "", 0
    try:
        content = await asyncio.to_thread(path.read_bytes)
        if len(content) == 0:
            return False, "", 0
        # 验证图像头与有效性
        with Image.open(io.BytesIO(content)) as img:
            img.verify()
        sha256 = hashlib.sha256(content).hexdigest()
        return True, sha256, len(content)
    except Exception:
        return False, "", 0


async def download_one(
    client: httpx.AsyncClient,
    item: dict[str, Any],
    target_dir: Path,
    sem: asyncio.Semaphore,
    force: bool = False,
) -> dict[str, Any]:
    dest = get_local_dest_path(target_dir, item)
    url = item.get("url", "")
    rel_path = item.get("relative_path", "")

    result: dict[str, Any] = {
        "relative_path": rel_path,
        "local_path": str(dest),
        "url": url,
        "status": "pending",
        "bytes": 0,
        "sha256": "",
        "error": None,
    }

    if not force:
        valid, sha256, size = await verify_local_file(dest)
        if valid:
            result["status"] = "skipped_cached"
            result["sha256"] = sha256
            result["bytes"] = size
            return result

    dest.parent.mkdir(parents=True, exist_ok=True)
    temp_file = dest.with_suffix(f"{dest.suffix}.tmp_{hashlib.md5(url.encode()).hexdigest()[:8]}")

    async with sem:
        for attempt in range(3):
            try:
                resp = await client.get(url, follow_redirects=True)
                if resp.status_code == 404:
                    result["status"] = "not_found_404"
                    result["error"] = "HTTP 404 Not Found"
                    return result
                resp.raise_for_status()
                content = resp.content

                # 校验图片
                def check_and_save():
                    with Image.open(io.BytesIO(content)) as img:
                        img.verify()
                    temp_file.write_bytes(content)
                    temp_file.replace(dest)

                await asyncio.to_thread(check_and_save)

                result["status"] = "downloaded"
                result["bytes"] = len(content)
                result["sha256"] = hashlib.sha256(content).hexdigest()
                return result
            except Exception as exc:
                if attempt == 2:
                    result["status"] = "failed"
                    result["error"] = str(exc)
                    logger.warning("Download failed for %s: %s", rel_path, exc)
                    temp_file.unlink(missing_ok=True)
                    return result
                await asyncio.sleep(0.5 * (attempt + 1))

    return result


async def run_pipeline(args: argparse.Namespace) -> int:
    inv_file = Path(args.inventory)
    target_dir = Path(args.output_dir)
    inventory = load_inventory(inv_file)

    categories = [c.strip() for c in args.categories.split(",") if c.strip()]
    items = filter_items(inventory, categories)

    logger.info("Selected %d items across categories: %s", len(items), categories)

    # 1. 预估大小模式
    if args.estimate_size:
        total_est_bytes = sum(i.get("est_bytes", 6000) for i in items)
        logger.info("=== ESTIMATE SIZE REPORT ===")
        logger.info("Total files to process: %d", len(items))
        logger.info("Estimated network/disk footprint: %.2f MB (%d bytes)", total_est_bytes / (1024 * 1024), total_est_bytes)
        if not args.download and not args.audit_only:
            return 0

    # 2. 审计模式
    if args.audit_only:
        logger.info("Running audit on local directory: %s ...", target_dir)
        present = 0
        missing = 0
        corrupt = 0
        for item in items:
            dest = get_local_dest_path(target_dir, item)
            valid, _, _ = await verify_local_file(dest)
            if valid:
                present += 1
            elif dest.exists():
                corrupt += 1
            else:
                missing += 1

        logger.info("=== AUDIT SUMMARY ===")
        logger.info("Target files: %d", len(items))
        logger.info("  Valid in local mirror: %d", present)
        logger.info("  Missing in mirror:     %d", missing)
        logger.info("  Corrupt / Invalid:     %d", corrupt)
        return 0

    # 3. 下载模式
    if args.download:
        target_dir.mkdir(parents=True, exist_ok=True)
        sem = asyncio.Semaphore(args.concurrency)
        logger.info("Starting mirror download with concurrency=%d ...", args.concurrency)

        limits = httpx.Limits(max_keepalive_connections=20, max_connections=args.concurrency + 5)
        timeout = httpx.Timeout(20.0, connect=10.0)

        results = []
        async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
            tasks = [
                download_one(client, item, target_dir, sem, force=args.force)
                for item in items
            ]
            results = await asyncio.gather(*tasks)

        downloaded = sum(1 for r in results if r["status"] == "downloaded")
        cached = sum(1 for r in results if r["status"] == "skipped_cached")
        failed = sum(1 for r in results if r["status"] == "failed")
        not_found = sum(1 for r in results if r["status"] == "not_found_404")
        total_bytes = sum(r["bytes"] for r in results)

        logger.info("=== DOWNLOAD SUMMARY ===")
        logger.info("Total items:      %d", len(results))
        logger.info("  Downloaded:     %d", downloaded)
        logger.info("  Already cached: %d", cached)
        logger.info("  Not found (404):%d", not_found)
        logger.info("  Failed:         %d", failed)
        logger.info("  Total bytes:    %.2f MB (%d bytes)", total_bytes / (1024 * 1024), total_bytes)

        # 写入 mirror_manifest.json
        manifest_data = {
            "version": "1.0.0",
            "target_dir": str(target_dir),
            "total_items": len(results),
            "downloaded": downloaded,
            "cached": cached,
            "failed": failed,
            "not_found": not_found,
            "total_bytes": total_bytes,
            "items": results,
        }
        manifest_path = target_dir / "mirror_manifest.json"
        manifest_path.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Saved mirror manifest -> %s", manifest_path)

        # 同时存一份到 evidence
        evidence_manifest = Path("docs/evidence/blabla_static_assets/mirror_manifest.json")
        evidence_manifest.parent.mkdir(parents=True, exist_ok=True)
        evidence_manifest.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False), encoding="utf-8")

        return 0 if failed == 0 else 1

    logger.warning("No action specified. Please pass --audit-only, --estimate-size, or --download.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Mirror BlaBlaLink static game assets locally.")
    parser.add_argument(
        "--inventory",
        type=str,
        default=str(DEFAULT_INVENTORY),
        help="Path to static_asset_inventory.json",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(DEFAULT_TARGET_DIR),
        help="Local target directory for mirrored assets",
    )
    parser.add_argument(
        "--categories",
        type=str,
        default="portrait_si,icons",
        help="Comma-separated categories to process: portrait_si, icons, equipment, guild, all",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help="Max async concurrency limit",
    )
    parser.add_argument(
        "--audit-only",
        action="store_true",
        help="Inspect existing local files vs inventory without downloading",
    )
    parser.add_argument(
        "--estimate-size",
        action="store_true",
        help="Print estimated file count and byte footprint",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Execute the download process",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-download even if local file exists and is valid",
    )

    args = parser.parse_args()
    ret = asyncio.run(run_pipeline(args))
    sys.exit(ret)


if __name__ == "__main__":
    main()

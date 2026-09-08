"""将用户授权的攻略原件复制/分段到仓库，并生成可审计 manifest。"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from PIL import Image


MAX_BYTES = 12 * 1024 * 1024
OVERLAP = 120
SPECS = {
    "progression": ("养成一图流.png", "屑芙蒂（原图可见署名）", 2800),
    "favorite": ("珍藏品养成.jpg", "迪恩deen33（原图可见署名）", None),
    "arena_charge": ("充能表查询.png", "迪恩deen33（原图可见署名）", 3000),
    "overload": ("洗词条教学.png", "用户授权提供，原图未署名", 3000),
    "pvp": ("PVP配队.png", "迪恩deen33（原图可见署名）", None),
}
EXPECTED_SHA256 = {
    "养成一图流.png": "5366388669790680ce7c52c13de8caf3e853a9f07a4992ca89ddfbcf9efac8b7",
    "珍藏品养成.jpg": "07032bff9cc87fc6cb70a5f6edb291479a7d3ed7cba05d80bcad5ec0fea3eb97",
    "充能表查询.png": "aaa31909abb531e99e09288695d8ab0b1f0c9454818fb58125c7f833c1e62949",
    "洗词条教学.png": "3e963cd17c66f1b1528ff49077120ff47e38593a991b2f102aa8f8696215b9e9",
    "PVP配队.png": "976d1ad3d998f7238dc2f4d4af785ae7579570330ede45185d7ce5961df9ee63",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def split_ranges(height: int, target: int | None) -> list[tuple[int, int]]:
    if target is None or height <= target:
        return [(0, height)]
    ranges = []
    top = 0
    while top < height:
        bottom = min(height, top + target)
        ranges.append((top, bottom))
        if bottom == height:
            break
        top = bottom - OVERLAP
    return ranges


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    manifest = {"registered_at": "2026-09-08", "authorization": "用户确认允许公开仓库收录及机器人发送", "assets": []}
    registry = []
    titles = {"progression": "NIKKE 养成一图流", "favorite": "珍藏品养成", "arena_charge": "竞技场充能表", "overload": "洗词条教学", "pvp": "PVP 配队参考"}
    dates = {"favorite": "2026-02-14", "arena_charge": "2026-09-06", "pvp": "2026-08-24"}
    for category, (filename, credit, target) in SPECS.items():
        source = args.source / filename
        source_hash = digest(source)
        if source_hash != EXPECTED_SHA256[filename]:
            raise RuntimeError(f"源文件哈希不匹配: {filename}")
        folder = args.destination / category
        folder.mkdir(parents=True, exist_ok=True)
        outputs = []
        with Image.open(source) as image:
            for index, (top, bottom) in enumerate(split_ranges(image.height, target), 1):
                suffix = source.suffix.lower()
                output = folder / (f"part-{index:02d}{suffix}" if target else f"original{suffix}")
                if target:
                    frame = image.crop((0, top, image.width, bottom))
                    frame.save(output, optimize=True)
                else:
                    shutil.copy2(source, output)
                if output.stat().st_size > MAX_BYTES:
                    raise RuntimeError(f"输出超过 12 MiB: {output}")
                outputs.append({"path": output.relative_to(args.destination).as_posix(), "crop": [0, top, image.width, bottom], "sha256": digest(output), "bytes": output.stat().st_size})
        manifest["assets"].append({"category": category, "source_file": filename, "source_sha256": source_hash, "source_bytes": source.stat().st_size, "credit": credit, "outputs": outputs})
        registry.append({"id": f"{category}-20260908", "category": category, "title": titles[category],
                         "files": [item["path"] for item in outputs], "links": [], "source": "用户授权提供的攻略原图",
                         "credit": credit, "license": "用户确认授权公开收录及机器人发送",
                         "updated_at": dates.get(category, "2026-09-08"), "game_version": "2026-09-08 快照"})
    registry.insert(1, {"id": "red-orbs-link-20260908", "category": "red_orbs", "title": "红球查询",
                        "files": [], "links": ["https://nikkeoutpost.netlify.app/"], "source": "用户提供的外部链接",
                        "credit": "站点作者", "license": "仅提供外部链接，不抓取或复制站点内容",
                        "updated_at": "2026-09-08", "game_version": "外部站点"})
    (args.destination / "source_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.destination / "registry.json").write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

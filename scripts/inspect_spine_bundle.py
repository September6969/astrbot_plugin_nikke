"""无运行时的 Spine 本地预检查；不加载动画、不下载或执行外部代码。"""
import argparse
import json
import re
from pathlib import Path


def inspect(atlas: Path, skeleton: Path, expected_version=None):
    if atlas.stat().st_size > 4 * 1024 * 1024 or skeleton.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("输入超过预检查大小预算")
    root = atlas.parent.resolve()
    pages = []
    # 官方 atlas 格式以空行分隔页；只读取页属性，不解释区域或绘制逻辑。
    for block in re.split(r"\n\s*\n", atlas.read_text(encoding="utf-8").strip()):
        lines = [line.strip() for line in block.splitlines()]
        if not lines:
            continue
        page = (root / lines[0]).resolve()
        if not page.is_relative_to(root):
            raise ValueError("纹理页路径越界")
        size = None
        for line in lines[1:]:
            if ":" not in line:
                break
            if line.startswith("size:"):
                match = re.fullmatch(r"size:\s*(\d+)\s*,\s*(\d+)", line)
                if not match or not all(0 < int(value) <= 16384 for value in match.groups()):
                    raise ValueError("纹理尺寸无效或超限")
                size = tuple(map(int, match.groups()))
        pages.append({"exists": page.is_file(), "size": size})
    if not pages or len(pages) > 32:
        raise ValueError("纹理页数无效或超限")
    version = None
    if skeleton.suffix.lower() == ".json":
        data = json.loads(skeleton.read_text(encoding="utf-8"))
        raw = data.get("skeleton", {}).get("spine") if isinstance(data, dict) else None
        if isinstance(raw, str) and re.fullmatch(r"\d+\.\d+(?:\.\d+)?", raw):
            version = ".".join(raw.split(".")[:2])
    if expected_version is not None and not re.fullmatch(r"\d+\.\d+", expected_version):
        raise ValueError("运行时版本应明确到 major.minor")
    status = "SPINE_VERSION_UNKNOWN" if version is None else "VERSION_OBSERVED"
    if version is not None and expected_version:
        status = "VERSION_MATCH" if version == expected_version else "VERSION_MISMATCH"
    return {"status": status, "major_minor": version, "page_count": len(pages),
        "missing_pages": sum(not page["exists"] for page in pages),
        "rgba_bytes_estimate": sum(page["size"][0] * page["size"][1] * 4 for page in pages) if all(page["size"] for page in pages) else None,
        "runtime_executed": False, "render_verified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--atlas", required=True, type=Path)
    parser.add_argument("--skeleton", required=True, type=Path)
    parser.add_argument("--expected-version")
    args = parser.parse_args()
    try:
        print(json.dumps(inspect(args.atlas, args.skeleton, args.expected_version), ensure_ascii=False, indent=2))
    except (OSError, ValueError, TypeError, AttributeError):
        print(json.dumps({"status": "INSPECTION_FAILED", "runtime_executed": False}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()

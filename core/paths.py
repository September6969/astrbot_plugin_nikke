# SPDX-License-Identifier: GPL-3.0-or-later
"""插件内置资源定位；与宿主运行数据、当前工作目录无关。"""
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = PLUGIN_ROOT / "assets"
OUTPUT_ROOT = PLUGIN_ROOT / "output"


def asset_data_file(filename: str, *, asset_dir: Path | None = None) -> Path:
    assets = Path(asset_dir) if asset_dir is not None else ASSET_ROOT
    paths = (assets / "data" / filename, assets / filename)
    return next((path for path in paths if path.is_file()), paths[0])


def builtin_roots(kind: str, *, asset_dir: Path | None = None) -> tuple[Path, ...]:
    assets = Path(asset_dir) if asset_dir is not None else ASSET_ROOT
    legacy = {
        "fonts": assets.parent / "fonts",
        "blablalink": assets.parent / "data" / "nikke" / "blabla-assets",
        "manifests/blablalink": assets.parent / "data" / "nikke" / "blabla-manifests",
    }
    return (assets / kind, legacy[kind])


def builtin_dir(kind: str, *, asset_dir: Path | None = None) -> Path:
    roots = builtin_roots(kind, asset_dir=asset_dir)
    return next((path for path in roots if path.is_dir()), roots[0])


def builtin_file(kind: str, filename: str, *, asset_dir: Path | None = None) -> Path:
    paths = tuple(root / filename for root in builtin_roots(kind, asset_dir=asset_dir))
    return next((path for path in paths if path.is_file()), paths[0])


def manifest_candidates(filename: str, asset_dir: Path, base_dir: Path) -> tuple[Path, ...]:
    # 显式传入的素材目录仍支持其相邻清单；默认内置目录优先新位置。
    roots = builtin_roots("manifests/blablalink", asset_dir=asset_dir)
    if base_dir not in builtin_roots("blablalink", asset_dir=asset_dir):
        roots = (base_dir.parent / "blabla-manifests", *roots)
    paths = tuple(root / filename for root in roots)
    return tuple(dict.fromkeys(paths))

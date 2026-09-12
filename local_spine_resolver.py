# SPDX-License-Identifier: GPL-3.0-or-later
"""本地 Nikke-db Spine bundle 解析器。

该模块只读取维护期已经 checkout 的文件，不包含 HTTP、Git 或 Worker 调用。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageFile

try:
    from .spine_prerenderer import SpineBundle, SpineRenderError
except ImportError:  # 允许维护脚本直接以文件路径运行
    from spine_prerenderer import SpineBundle, SpineRenderError  # type: ignore[no-redef]


class LocalSpineResolveError(SpineRenderError):
    """本地 bundle 缺失、歧义或完整性校验失败。"""


@dataclass(frozen=True, slots=True)
class LocalSpineBundle:
    """已通过本地路径、atlas 纹理和 skeleton 版本校验的 bundle。"""

    bundle_root: Path
    skel_path: Path
    atlas_path: Path
    texture_paths: tuple[Path, ...]
    runtime_version: str

    def as_spine_bundle(self) -> SpineBundle:
        return SpineBundle(self.skel_path, self.atlas_path, self.texture_paths)


class LocalSpineBundleResolver:
    """按 canonical cXXX[_YY] 解析 vendor/nikke-db/l2d 下的唯一 bundle。"""

    DEFAULT_ROOT = Path("/AstrBot/data/vendor/nikke-db")
    ASSET_ID = re.compile(r"^c[0-9]+(?:_[0-9]+)?$", re.ASCII)
    PAGE_SUFFIXES = {".png", ".webp"}
    MAX_TEXTURE_BYTES = 12 * 1024 * 1024
    MAX_SKELETON_BYTES = 16 * 1024 * 1024
    _VERSION = re.compile(rb"(?<![0-9])4\.[01](?:\.[0-9]+)?(?![0-9])")

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else self.DEFAULT_ROOT
        try:
            self.root = self.root.expanduser().resolve()
        except OSError as exc:
            raise LocalSpineResolveError("Nikke-db 本地根目录无法解析") from exc

    @classmethod
    def _validate_asset_id(cls, asset_id: object) -> str:
        if not isinstance(asset_id, str):
            raise LocalSpineResolveError("Spine asset ID 必须是文本")
        value = asset_id.strip().lower()
        if not cls.ASSET_ID.fullmatch(value):
            raise LocalSpineResolveError("Spine asset ID 含有非法路径字符")
        return value

    def _ensure_inside(self, path: Path, *, label: str) -> Path:
        try:
            resolved = path.resolve()
        except OSError as exc:
            raise LocalSpineResolveError(f"{label} 路径无法解析") from exc
        if not resolved.is_relative_to(self.root):
            raise LocalSpineResolveError(f"{label} 路径越界")
        return resolved

    @staticmethod
    def _choose_named(bundle_root: Path, asset_id: str, suffix: str) -> Path:
        """只接受 canonical_00 或 canonical 两种已记录的命名合同。"""
        exact = bundle_root / f"{asset_id}_00{suffix}"
        legacy = bundle_root / f"{asset_id}{suffix}"
        if exact.is_file() and legacy.is_file():
            raise LocalSpineResolveError(f"存在歧义的 {suffix} bundle 文件: {asset_id}")
        if exact.is_file():
            return exact
        if legacy.is_file():
            return legacy
        raise LocalSpineResolveError(f"缺少唯一 {suffix} bundle 文件: {asset_id}")

    @classmethod
    def _atlas_pages(cls, atlas_path: Path) -> list[str]:
        try:
            text = atlas_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            raise LocalSpineResolveError("atlas 无法按 UTF-8-SIG 读取") from exc
        pages: list[str] = []
        for block in re.split(r"\n\s*\n", text.strip()):
            lines = [line.strip().lstrip("\ufeff") for line in block.splitlines() if line.strip()]
            if not lines:
                continue
            candidate = lines[0]
            if Path(candidate).suffix.lower() in cls.PAGE_SUFFIXES:
                if candidate not in pages:
                    pages.append(candidate)
        if not pages:
            raise LocalSpineResolveError("atlas 未声明纹理页")
        return pages

    def _validate_texture(self, bundle_root: Path, page: str) -> Path:
        page_path = Path(page)
        if (
            page_path.is_absolute()
            or page_path.drive
            or any(part in {"", ".", ".."} for part in page_path.parts)
            or page_path.suffix.lower() not in self.PAGE_SUFFIXES
        ):
            raise LocalSpineResolveError(f"atlas 纹理页路径非法: {page}")
        target = self._ensure_inside(bundle_root / page_path, label="纹理页")
        try:
            size = target.stat().st_size
        except OSError as exc:
            raise LocalSpineResolveError(f"缺少 atlas 纹理页: {page}") from exc
        if not target.is_file() or size <= 0 or size > self.MAX_TEXTURE_BYTES:
            raise LocalSpineResolveError(f"atlas 纹理页大小非法: {page}")
        previous_truncated = ImageFile.LOAD_TRUNCATED_IMAGES
        try:
            ImageFile.LOAD_TRUNCATED_IMAGES = False
            with Image.open(target) as image:
                image.verify()
        except (OSError, ValueError) as exc:
            raise LocalSpineResolveError(f"atlas 纹理页不是有效图片: {page}") from exc
        finally:
            ImageFile.LOAD_TRUNCATED_IMAGES = previous_truncated
        return target

    @classmethod
    def detect_runtime_version(cls, skel_path: Path) -> str:
        try:
            size = skel_path.stat().st_size
            if size <= 0 or size > cls.MAX_SKELETON_BYTES:
                raise LocalSpineResolveError("skeleton 大小非法")
            header = skel_path.read_bytes()[:512]
        except OSError as exc:
            raise LocalSpineResolveError("skeleton 无法读取") from exc
        match = cls._VERSION.search(header)
        if match is None:
            raise LocalSpineResolveError("skeleton 版本未知，拒绝猜测 runtime")
        version = match.group(0).decode("ascii")
        return version[:3]

    def resolve(self, canonical_asset_id: str) -> LocalSpineBundle:
        asset_id = self._validate_asset_id(canonical_asset_id)
        bundle_root = self._ensure_inside(self.root / "l2d" / asset_id, label="bundle")
        if not bundle_root.is_dir():
            raise LocalSpineResolveError(f"本地 bundle 目录不存在: {asset_id}")
        skel_path = self._ensure_inside(self._choose_named(bundle_root, asset_id, ".skel"), label="skeleton")
        atlas_path = self._ensure_inside(self._choose_named(bundle_root, asset_id, ".atlas"), label="atlas")
        pages = self._atlas_pages(atlas_path)
        textures = tuple(self._validate_texture(bundle_root, page) for page in pages)
        runtime_version = self.detect_runtime_version(skel_path)
        return LocalSpineBundle(bundle_root, skel_path, atlas_path, textures, runtime_version)

    resolve_bundle = resolve


__all__ = ["LocalSpineBundle", "LocalSpineBundleResolver", "LocalSpineResolveError"]

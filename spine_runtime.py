# SPDX-License-Identifier: GPL-3.0-or-later
"""Spine/L2D 实时运行时数据结构、骨骼解析器与内存缓存。

提供：
1. SpineBundle：完整性校验、格式与版本识别；
2. RenderedCharacter：透明 RGBA、尺寸、alpha_bbox、骨骼定位点；
3. SpineSkeletonParser：纯 Python 解析 Spine 4.0/4.1 二进制 (.skel) 与 JSON (.json) 骨骼；
4. SpineMemoryCache：线程安全的运行时内存缓存。
"""

from __future__ import annotations

import json
import logging
import math
import re
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image

logger = logging.getLogger("nikke.spine.runtime")


class SpineRenderError(RuntimeError):
    """Spine 实时渲染或 Bundle 处理异常。"""



@dataclass(frozen=True, slots=True)
class SpineBundle:
    """标准 Spine Bundle 数据结构与完整性校验。"""

    skeleton: Path | None
    atlas: Path | None
    textures: tuple[Path, ...] = ()

    skeleton_format: str | None = None  # "skel" | "json"
    spine_version: str | None = None  # "4.0" | "4.1" | etc.

    bone_names: tuple[str, ...] = ()
    slot_names: tuple[str, ...] = ()
    animation_names: tuple[str, ...] = ()

    @classmethod
    def from_files(
        cls,
        skeleton: Path | str | None,
        atlas: Path | str | None,
        textures: Sequence[Path | str] = (),
        *,
        skeleton_format: str | None = None,
        spine_version: str | None = None,
        bone_names: Sequence[str] = (),
        slot_names: Sequence[str] = (),
        animation_names: Sequence[str] = (),
    ) -> "SpineBundle":
        skel_p = Path(skeleton) if skeleton is not None else None
        atlas_p = Path(atlas) if atlas is not None else None
        tex_tuple = tuple(Path(t) for t in textures)
        fmt = skeleton_format or (skel_p.suffix.lstrip(".").lower() if skel_p else None)
        return cls(
            skeleton=skel_p,
            atlas=atlas_p,
            textures=tex_tuple,
            skeleton_format=fmt,
            spine_version=spine_version,
            bone_names=tuple(bone_names),
            slot_names=tuple(slot_names),
            animation_names=tuple(animation_names),
        )

    def validate_integrity(self) -> str:
        """检查 bundle 完整性并返回统一状态码。

        状态集：
        - complete
        - missing_skeleton
        - missing_atlas
        - missing_texture
        - atlas_reference_missing
        - parse_failed
        - unsupported_runtime
        """
        if self.skeleton is None or not self.skeleton.is_file():
            return "missing_skeleton"
        if self.atlas is None or not self.atlas.is_file():
            return "missing_atlas"
        if not self.textures or not all(t.is_file() for t in self.textures):
            return "missing_texture"

        # 检查 atlas 中声明的页面是否全部能找到对应纹理
        declared = parse_atlas_pages(self.atlas)
        if declared:
            parent = self.atlas.parent
            for page in declared:
                candidate = parent / page
                if not candidate.is_file() and not any(t.name == page for t in self.textures):
                    return "atlas_reference_missing"

        # 校验 skeleton 版本支持性
        ver = self.spine_version
        if ver is None and self.skeleton:
            ver = detect_spine_version(self.skeleton)
        if ver is None:
            return "parse_failed"
        if ver not in ("4.0", "4.1"):
            return "unsupported_runtime"

        return "complete"

    def is_valid(self) -> bool:
        return self.validate_integrity() == "complete"


@dataclass(slots=True)
class RenderedCharacter:
    """运行时内存中透明 RGBA 渲染结果及几何元数据。"""

    image: Image.Image
    width: int
    height: int

    alpha_bbox: tuple[int, int, int, int] | None = None
    skeleton_points: dict[str, tuple[float, float]] = field(default_factory=dict)
    source_animation: str | None = None
    source_time: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.image is not None and self.alpha_bbox is None:
            self.alpha_bbox = self.image.getbbox()


def parse_atlas_pages(atlas_path: Path) -> list[str]:
    """解析 LibGDX Atlas 文件所声明的纹理页文件名。"""
    try:
        text = atlas_path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    pages = []
    for line in text.splitlines():
        line = line.strip().lstrip("\ufeff")
        if re.search(r"\.(?:png|webp|jpg)$", line, re.IGNORECASE) and not line.startswith("#"):
            if line not in pages:
                pages.append(line)
    return pages


def detect_spine_version(skeleton_path: Path) -> str | None:
    """从二进制或 JSON skeleton 头部提取 major.minor 版本。"""
    if not skeleton_path.is_file():
        return None
    try:
        suffix = skeleton_path.suffix.lower()
        if suffix == ".json":
            data = json.loads(skeleton_path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(data, dict):
                spine_val = data.get("skeleton", {}).get("spine")
                if isinstance(spine_val, str):
                    m = re.match(r"(\d+\.\d+)", spine_val)
                    if m:
                        return m.group(1)
            return None

        # Binary .skel
        prefix = skeleton_path.read_bytes()[:512]
        if len(prefix) < 16:
            return None
        # 固定跳过 8 字节 hash
        offset = 8
        val = 0
        for shift in range(0, 35, 7):
            if offset >= len(prefix):
                return None
            b = prefix[offset]
            offset += 1
            val |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
        if val <= 1:
            return None
        length = val - 1
        end = offset + length
        if end > len(prefix):
            return None
        raw_ver = prefix[offset:end].decode("utf-8", errors="replace")
        m = re.match(r"(\d+\.\d+)", raw_ver)
        return m.group(1) if m else None
    except Exception:
        return None


@dataclass(slots=True)
class ParsedBone:
    index: int
    name: str
    parent_index: int | None
    x: float
    y: float
    rotation: float
    length: float
    scale_x: float = 1.0
    scale_y: float = 1.0


@dataclass(slots=True)
class ParsedSkeleton:
    version: str | None
    bounds: tuple[float, float, float, float]  # (x, y, width, height)
    bones: list[ParsedBone]
    slots: list[str]
    animations: list[str]
    bone_name_map: dict[str, ParsedBone] = field(init=False)

    def __post_init__(self) -> None:
        self.bone_name_map = {b.name: b for b in self.bones}

    def compute_world_transforms(self) -> dict[str, tuple[float, float]]:
        """使用正向运动学 (Forward Kinematics) 计算 setup pose 下所有骨骼的世界坐标。"""
        matrices: dict[int, tuple[float, float, float, float, float, float]] = {}
        world_points: dict[str, tuple[float, float]] = {}

        for b in self.bones:
            idx = b.index
            pidx = b.parent_index
            rot_rad = math.radians(b.rotation)
            cos_r = math.cos(rot_rad)
            sin_r = math.sin(rot_rad)
            la = cos_r * b.scale_x
            lb = -sin_r * b.scale_y
            lc = sin_r * b.scale_x
            ld = cos_r * b.scale_y
            ltx = b.x
            lty = b.y

            if pidx is None or pidx not in matrices:
                matrices[idx] = (la, lb, lc, ld, ltx, lty)
            else:
                pa, pb, pc, pd, ptx, pty = matrices[pidx]
                matrices[idx] = (
                    pa * la + pb * lc,
                    pa * lb + pb * ld,
                    pc * la + pd * lc,
                    pc * lb + pd * ld,
                    pa * ltx + pb * lty + ptx,
                    pc * ltx + pd * lty + pty,
                )
            mat = matrices[idx]
            world_points[b.name] = (mat[4], mat[5])
        return world_points

    def compute_normalized_points(self) -> dict[str, tuple[float, float]]:
        """计算相对于骨骼边界框 [0.0, 1.0] 的归一化坐标。

        Spine 中 Y 向上递增；图像视口中 Y 向下递增，故 norm_y 做翻转。
        """
        bx, by, bw, bh = self.bounds
        if bw <= 0:
            bw = 1.0
        if bh <= 0:
            bh = 1.0

        world = self.compute_world_transforms()
        norm: dict[str, tuple[float, float]] = {}
        for name, (wx, wy) in world.items():
            nx = (wx - bx) / bw
            ny = 1.0 - ((wy - by) / bh)
            # 限制在合理范围内
            nx = max(0.0, min(1.0, nx))
            ny = max(0.0, min(1.0, ny))
            norm[name] = (round(nx, 4), round(ny, 4))
        return norm


class SpineSkeletonParser:
    """解析 Spine 4.0 / 4.1 二进制和 JSON 骨骼的解析器。"""

    @classmethod
    def parse(cls, skeleton_path: Path) -> ParsedSkeleton:
        if not skeleton_path.is_file():
            raise FileNotFoundError(f"Skeleton file not found: {skeleton_path}")
        suffix = skeleton_path.suffix.lower()
        if suffix == ".json":
            return cls.parse_json(skeleton_path)
        return cls.parse_binary(skeleton_path)

    @classmethod
    def parse_json(cls, skeleton_path: Path) -> ParsedSkeleton:
        raw = json.loads(skeleton_path.read_text(encoding="utf-8", errors="replace"))
        skel_meta = raw.get("skeleton", {})
        ver = skel_meta.get("spine")
        if isinstance(ver, str):
            m = re.match(r"(\d+\.\d+)", ver)
            ver = m.group(1) if m else ver

        bx = float(skel_meta.get("x", 0.0))
        by = float(skel_meta.get("y", 0.0))
        bw = float(skel_meta.get("width", 1024.0))
        bh = float(skel_meta.get("height", 1024.0))

        bones_raw = raw.get("bones", [])
        parsed_bones: list[ParsedBone] = []
        name_to_idx: dict[str, int] = {}
        for i, b in enumerate(bones_raw):
            b_name = str(b.get("name", f"bone_{i}"))
            name_to_idx[b_name] = i
            p_name = b.get("parent")
            p_idx = name_to_idx.get(p_name) if p_name else None
            parsed_bones.append(
                ParsedBone(
                    index=i,
                    name=b_name,
                    parent_index=p_idx,
                    x=float(b.get("x", 0.0)),
                    y=float(b.get("y", 0.0)),
                    rotation=float(b.get("rotation", 0.0)),
                    length=float(b.get("length", 0.0)),
                    scale_x=float(b.get("scaleX", 1.0)),
                    scale_y=float(b.get("scaleY", 1.0)),
                )
            )

        slots_raw = raw.get("slots", [])
        slots = [str(s.get("name")) for s in slots_raw if isinstance(s, dict) and "name" in s]

        anims_raw = raw.get("animations", {})
        animations = list(anims_raw.keys()) if isinstance(anims_raw, dict) else []

        return ParsedSkeleton(
            version=ver,
            bounds=(bx, by, bw, bh),
            bones=parsed_bones,
            slots=slots,
            animations=animations,
        )

    @classmethod
    def parse_binary(cls, skeleton_path: Path) -> ParsedSkeleton:
        data = skeleton_path.read_bytes()
        offset = 0

        def read_varint() -> int:
            nonlocal offset
            val = 0
            for shift in range(0, 35, 7):
                if offset >= len(data):
                    raise ValueError("Unexpected end of binary data while reading varint")
                b = data[offset]
                offset += 1
                val |= (b & 0x7F) << shift
                if not (b & 0x80):
                    return val
            return val

        def read_string() -> str | None:
            nonlocal offset
            length = read_varint()
            if length == 0:
                return None
            if length == 1:
                return ""
            length -= 1
            s = data[offset : offset + length].decode("utf-8", errors="replace")
            offset += length
            return s

        if len(data) < 24:
            raise ValueError("Skeleton file too small")

        # 8 bytes hash
        offset = 8
        version_str = read_string()
        m = re.match(r"(\d+\.\d+)", version_str or "")
        ver = m.group(1) if m else version_str

        # x, y, width, height
        bx, by, bw, bh = struct.unpack(">ffff", data[offset : offset + 16])
        offset += 16

        nonessential = data[offset] != 0
        offset += 1

        if nonessential:
            read_string()  # images
            read_string()  # audio

        is_v41 = ver is not None and (ver.startswith("4.1") or ver.startswith("4.2"))
        if is_v41:
            num_strings = read_varint()
            for _ in range(num_strings):
                read_string()

        # Bones
        num_bones = read_varint()
        bones: list[ParsedBone] = []
        for i in range(num_bones):
            bone_name = read_string()
            p_idx = None
            if i > 0:
                p_idx = read_varint()
            rot, x, y, sx, sy, shx, shy, length = struct.unpack(">ffffffff", data[offset : offset + 32])
            offset += 32
            offset += 2  # transform mode, skin required
            if nonessential:
                offset += 4  # color

            bones.append(
                ParsedBone(
                    index=i,
                    name=bone_name or f"bone_{i}",
                    parent_index=p_idx,
                    x=x,
                    y=y,
                    rotation=rot,
                    length=length,
                    scale_x=sx,
                    scale_y=sy,
                )
            )

        # Slots parsing is best-effort
        slots: list[str] = []
        try:
            num_slots = read_varint()
            for _ in range(num_slots):
                s_name = read_string()
                if s_name:
                    slots.append(s_name)
                read_varint()  # bone index
                offset += 4  # color
                read_varint()  # dark color
                read_string()  # attachment name
                read_varint()  # blend mode
        except Exception:
            pass

        return ParsedSkeleton(
            version=ver,
            bounds=(bx, by, bw, bh),
            bones=bones,
            slots=slots,
            animations=[],
        )


class SpineMemoryCache:
    """线程安全的 Spine 解析与运行时内存缓存。"""

    def __init__(self, max_entries: int = 64, ttl_seconds: float = 300.0) -> None:
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            ts, value = entry
            if time.monotonic() - ts > self.ttl_seconds:
                del self._cache[key]
                return None
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if len(self._cache) >= self.max_entries:
                oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][0])
                del self._cache[oldest_key]
            self._cache[key] = (time.monotonic(), value)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

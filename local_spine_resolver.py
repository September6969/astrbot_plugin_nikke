# SPDX-License-Identifier: GPL-3.0-or-later
"""本地 Nikke-db Spine bundle 解析器。

负责从本地检出的 Nikke-db 仓库中定位 Spine 骨骼、图集与纹理文件，
执行路径穿越防护、UTF-8-SIG 图集校验、多纹理页完整性检查与 4.0/4.1 版本探测。
严格保证零网络、零外部进程。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("nikke.spine_resolver")

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_VERSION_RE = re.compile(rb"(\d+\.\d+(?:\.\d+)?)")


@dataclass(slots=True)
class SpineBundle:
    asset_id: str
    bundle_dir: Path
    skel_path: Path
    atlas_path: Path
    texture_paths: list[Path]
    version: str


class LocalSpineBundleResolver:
    """本地 Spine Bundle 解析器，严格只读本地文件，绝不发起网络调用。"""

    def __init__(self, local_root: str | Path):
        self.local_root = Path(local_root).resolve()

    def resolve_bundle(self, char_id: str) -> SpineBundle | None:
        """解析指定角色的本地 Spine bundle。若文件缺失或不合规，返回 None。"""
        if not char_id or not _SAFE_ID_RE.fullmatch(char_id):
            logger.debug("非法 Spine 资产 ID: %r", char_id)
            return None

        # 检查候选目录（支持 l2d/{char_id} 或直接 {char_id}）
        candidate_dirs = [
            self.local_root / "l2d" / char_id,
            self.local_root / char_id,
        ]
        target_dir: Path | None = None
        for cd in candidate_dirs:
            resolved_cd = cd.resolve()
            # 严格路径穿越防护
            try:
                if not resolved_cd.is_relative_to(self.local_root):
                    raise ValueError(f"Path traversal detected: {char_id}")
            except AttributeError:
                # Python < 3.9 compatibility
                if not str(resolved_cd).startswith(str(self.local_root)):
                    raise ValueError(f"Path traversal detected: {char_id}")
            if resolved_cd.is_dir():
                target_dir = resolved_cd
                break

        if target_dir is None:
            return None

        # 1. 动态定位 .skel 文件
        skel_candidates = list(target_dir.glob("*.skel"))
        if not skel_candidates:
            logger.debug("[%s] 缺少 .skel 文件", char_id)
            return None

        # 优先匹配同名或 _00.skel
        skel_path: Path | None = None
        for name in (f"{char_id}.skel", f"{char_id}_00.skel"):
            p = target_dir / name
            if p.is_file():
                skel_path = p
                break
        if skel_path is None:
            skel_path = skel_candidates[0]

        # 2. 动态定位 .atlas 文件
        atlas_candidates = list(target_dir.glob("*.atlas"))
        if not atlas_candidates:
            logger.debug("[%s] 缺少 .atlas 文件", char_id)
            return None

        atlas_path: Path | None = None
        for name in (f"{char_id}.atlas", f"{char_id}_00.atlas"):
            p = target_dir / name
            if p.is_file():
                atlas_path = p
                break
        if atlas_path is None:
            atlas_path = atlas_candidates[0]

        # 3. 解析 atlas 文件（以 utf-8-sig 编码处理 BOM），提取并检查所有纹理页
        try:
            atlas_text = atlas_path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            logger.debug("[%s] 读取 atlas 失败: %s", char_id, exc)
            return None

        declared_pages: list[str] = []
        for line in atlas_text.splitlines():
            line = line.strip().lstrip("\ufeff")
            if line.lower().endswith(".png"):
                if line not in declared_pages:
                    declared_pages.append(line)

        # 若 atlas 未显式声明纹理页，退化为同名或目录下的 png
        if not declared_pages:
            png_candidates = list(target_dir.glob("*.png"))
            if not png_candidates:
                logger.debug("[%s] 缺少 .png 纹理", char_id)
                return None
            declared_pages = [p.name for p in png_candidates]

        texture_paths: list[Path] = []
        for page_name in declared_pages:
            tex_file = target_dir / page_name
            if not tex_file.is_file() or tex_file.stat().st_size == 0:
                logger.debug("[%s] 声明的纹理页不存在或为空: %s", char_id, page_name)
                return None
            texture_paths.append(tex_file)

        # 4. 二进制头部版本探测 (4.0 vs 4.1)
        try:
            header_bytes = skel_path.read_bytes()[:64]
            match = _VERSION_RE.search(header_bytes)
            if not match:
                logger.debug("[%s] 无法在 skel 头部探测到版本", char_id)
                return None
            ver_str = match.group(1).decode("ascii", errors="replace")
            if ver_str.startswith("4.0"):
                version = "4.0"
            elif ver_str.startswith("4.1"):
                version = "4.1"
            else:
                logger.debug("[%s] 不受支持的 Spine 版本: %s", char_id, ver_str)
                return None
        except Exception as exc:
            logger.debug("[%s] 读取 skel 头部失败: %s", char_id, exc)
            return None

        return SpineBundle(
            asset_id=char_id,
            bundle_dir=target_dir,
            skel_path=skel_path,
            atlas_path=atlas_path,
            texture_paths=texture_paths,
            version=version,
        )

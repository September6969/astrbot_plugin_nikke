# SPDX-License-Identifier: GPL-3.0-or-later
"""Spine bundle 的唯一数据结构与渲染异常（无第三方依赖的叶子模块）。

PR-6B（G6-character-spine-c1/c2）起 SpineRenderError 与可供 runtime 消费的
SpineBundle 只在此定义一次；prerenderer、runtime、worker_caller 与 local_resolver
均从这里导入，prerenderer 继续再导出这两个名称以兼容既有调用方。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


class SpineRenderError(RuntimeError):
    """Spine bundle 或 runtime 渲染失败。"""


@dataclass(frozen=True, slots=True)
class SpineBundle:
    """一个可供 runtime 消费的完整 Spine bundle。"""

    skeleton: Path
    atlas: Path
    textures: tuple[Path, ...]

    @classmethod
    def from_mapping(cls, paths: Mapping[str, object]) -> "SpineBundle":
        skeleton_value = paths.get("skel") or paths.get("skeleton")
        atlas_value = paths.get("atlas")
        texture_value = paths.get("png") or paths.get("texture") or paths.get("textures")
        textures: tuple[Path, ...]
        if not isinstance(skeleton_value, (str, Path)) or not isinstance(atlas_value, (str, Path)):
            raise SpineRenderError("Spine bundle 缺少 skeleton 或 atlas")
        if isinstance(texture_value, (str, Path)):
            textures = (Path(texture_value),)
        elif isinstance(texture_value, Sequence) and not isinstance(texture_value, (str, bytes, bytearray)):
            if not all(isinstance(item, (str, Path)) for item in texture_value):
                raise SpineRenderError("Spine bundle 纹理页路径类型无效")
            textures = tuple(Path(item) for item in texture_value)
        else:
            textures = ()
        if not textures:
            raise SpineRenderError("Spine bundle 缺少纹理页")
        return cls(Path(skeleton_value), Path(atlas_value), textures)

    def all_files(self) -> tuple[Path, ...]:
        return (self.skeleton, self.atlas, *self.textures)


__all__ = ["SpineBundle", "SpineRenderError"]

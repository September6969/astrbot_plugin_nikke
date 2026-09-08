# SPDX-License-Identifier: GPL-3.0-or-later
"""受限的官方 Spine SDL worker 适配器。

该模块不内置 Spine 源码或二进制，只调用部署方按 ``runtime/spine_worker``
构建的 worker。输入 bundle 必须位于指定 cache root 内，输出在读取后立即清理。
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from .spine_prerenderer import SpineBundle, SpineRenderError


@dataclass(frozen=True, slots=True)
class SpineWorkerConfig:
    """worker 进程的资源与时间边界。"""

    executable: Path
    bundle_root: Path
    timeout_seconds: float = 4.0
    width: int = 1024
    height: int = 1024
    max_output_bytes: int = 4096 * 4096 * 4 + 8

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.timeout_seconds > 5:
            raise ValueError("Spine worker timeout 必须在 0 到 5 秒之间")
        if self.width < 1 or self.width > 4096 or self.height < 1 or self.height > 4096:
            raise ValueError("Spine worker 画布必须在 1 到 4096 之间")
        if self.max_output_bytes < 16 or self.max_output_bytes > 4096 * 4096 * 4 + 8:
            raise ValueError("Spine worker 输出上限无效")


class SpineWorkerRuntime:
    """实现 ``SpineRuntimeBackend`` 的进程边界适配器。"""

    def __init__(self, config: SpineWorkerConfig, *, version: str = "4.1") -> None:
        self.config = config
        self.version = version

    def _inside_root(self, path: Path) -> Path:
        root = self.config.bundle_root.resolve()
        candidate = path.resolve()
        if not candidate.is_relative_to(root):
            raise SpineRenderError("Spine worker 路径越界")
        if not candidate.is_file():
            raise SpineRenderError("Spine worker 输入文件不存在")
        return candidate

    @staticmethod
    def _read_rgba(path: Path, maximum: int) -> Image.Image:
        try:
            size = path.stat().st_size
            if size < 8 or size > maximum:
                raise SpineRenderError("Spine worker 输出大小越界")
            raw = path.read_bytes()
        except OSError as exc:
            raise SpineRenderError("Spine worker 输出读取失败") from exc
        width = int.from_bytes(raw[0:4], "little")
        height = int.from_bytes(raw[4:8], "little")
        if not 1 <= width <= 4096 or not 1 <= height <= 4096:
            raise SpineRenderError("Spine worker 输出尺寸无效")
        expected = 8 + width * height * 4
        if expected != len(raw):
            raise SpineRenderError("Spine worker RGBA 长度不匹配")
        return Image.frombytes("RGBA", (width, height), raw[8:]).copy()

    def render(
        self,
        bundle: SpineBundle,
        *,
        animation: str,
        skin: str | None = None,
    ) -> Image.Image:
        skeleton = self._inside_root(bundle.skeleton)
        atlas = self._inside_root(bundle.atlas)
        for texture in bundle.textures:
            self._inside_root(texture)
        if skeleton.suffix.lower() not in {".skel", ".json"}:
            raise SpineRenderError("Spine worker skeleton 后缀无效")
        if not animation or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for char in animation):
            raise SpineRenderError("Spine worker animation 标识无效")
        if skin is not None and (
            not skin
            or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for char in skin)
        ):
            raise SpineRenderError("Spine worker skin 标识无效")

        fd, output_name = tempfile.mkstemp(prefix=".spine-worker-", suffix=".rgba", dir=self.config.bundle_root)
        os.close(fd)
        output = Path(output_name)
        command = [
            str(self.config.executable),
            "--skeleton",
            str(skeleton),
            "--atlas",
            str(atlas),
            "--output",
            str(output),
            "--animation",
            animation,
            "--width",
            str(self.config.width),
            "--height",
            str(self.config.height),
        ]
        if skin is not None:
            command.extend(("--skin", skin))

        environment = os.environ.copy()
        environment.update({"SDL_VIDEODRIVER": "dummy", "SDL_RENDER_DRIVER": "software"})
        try:
            try:
                completed = subprocess.run(
                    command,
                    cwd=str(self.config.bundle_root),
                    env=environment,
                    capture_output=True,
                    timeout=self.config.timeout_seconds,
                    check=False,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            except subprocess.TimeoutExpired as exc:
                raise SpineRenderError("Spine worker 超时") from exc
            if completed.returncode != 0:
                # 只返回固定分类，避免把服务器绝对路径或 bundle 内容写入日志。
                raise SpineRenderError("Spine worker 执行失败")
            try:
                report: Any = json.loads(completed.stdout.strip() or "{}")
            except json.JSONDecodeError as exc:
                raise SpineRenderError("Spine worker 响应不是 JSON") from exc
            if not isinstance(report, dict) or report.get("status") != "ok":
                raise SpineRenderError("Spine worker 未报告成功")
            return self._read_rgba(output, self.config.max_output_bytes)
        finally:
            output.unlink(missing_ok=True)

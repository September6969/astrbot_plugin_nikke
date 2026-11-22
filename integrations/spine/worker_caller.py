# SPDX-License-Identifier: GPL-3.0-or-later
"""受限的官方 Spine SDL worker 适配器。

该模块不内置 Spine 源码或二进制，只调用部署方按 ``runtime/spine_worker``
构建的 worker。输入 bundle 必须位于指定 cache root 内，输出在读取后立即清理。
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from PIL import Image

from .prerenderer import SpineBundle, SpineRenderError
from .deadline import remaining


# worker 是部署方构建的外部进程，只透传运行所需的非敏感变量；插件密钥（如
# NIKKE_ENCRYPTION_KEY）、代理凭据与宿主其余环境一律不下发（AUD-016）。
WORKER_ENVIRONMENT_ALLOWLIST: frozenset[str] = frozenset(
    {
        # 进程启动、动态库与区域设置。
        "PATH", "HOME", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "TZ", "LD_LIBRARY_PATH",
        "TMPDIR", "TMP", "TEMP",
        # 宿主直接运行 SFML worker 时的 X11/GL 上下文。
        "DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR", "LIBGL_ALWAYS_SOFTWARE", "GALLIUM_DRIVER",
        # 经 Docker CLI 桥接官方 worker 镜像时的连接配置。
        "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_CERT_PATH", "DOCKER_TLS_VERIFY",
        # Windows 进程启动所需的系统变量。
        "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT",
    }
)
WORKER_FIXED_ENVIRONMENT: dict[str, str] = {"SDL_VIDEODRIVER": "dummy", "SDL_RENDER_DRIVER": "software"}
# 超时后先向整个进程组发 SIGTERM，让 entrypoint 的 trap 回收 Xvfb 与临时目录，再强杀残留。
WORKER_TERMINATE_GRACE_SECONDS = 0.2


def worker_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """按白名单构造 worker 环境，并固定无桌面 SDL 驱动。"""
    values = os.environ if source is None else source
    environment = {key: value for key, value in values.items() if key in WORKER_ENVIRONMENT_ALLOWLIST}
    environment.update(WORKER_FIXED_ENVIRONMENT)
    return environment


def _signal_process_group(process: subprocess.Popen[str], signum: int) -> None:
    try:
        os.killpg(process.pid, signum)
    except OSError:  # 进程组已全部退出或无权限时无需再处理。
        pass


def _terminate_worker(process: subprocess.Popen[str]) -> None:
    """结束 worker 及其整个进程组，避免 Xvfb 等孙进程成为孤儿。"""
    if os.name == "posix":
        _signal_process_group(process, signal.SIGTERM)
        try:
            process.wait(timeout=WORKER_TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        _signal_process_group(process, signal.SIGKILL)
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        pass


def _run_worker(command: list[str], *, cwd: Path, timeout: float | None) -> subprocess.CompletedProcess[str]:
    """在独立进程组运行 worker；超时或中断时整组回收后再抛出原异常。"""
    group_options: dict[str, Any] = (
        {"start_new_session": True}
        if os.name == "posix"
        else {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    )
    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=worker_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **group_options,
        )
    except OSError as exc:
        raise SpineRenderError("Spine worker 启动失败") from exc
    with process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except BaseException:
            _terminate_worker(process)
            raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


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

    def __init__(self, config: SpineWorkerConfig, *, version: str = "4.0") -> None:
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
        deadline: float | None = None,
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

        try:
            try:
                completed = _run_worker(
                    command,
                    cwd=self.config.bundle_root,
                    timeout=remaining(deadline, self.config.timeout_seconds),
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
            remaining(deadline)
            image = self._read_rgba(output, self.config.max_output_bytes)
            geometry = report.get("geometry")
            if isinstance(geometry, dict) and geometry.get("schema") == 1:
                image.info["spine_geometry"] = geometry
            remaining(deadline)
            return image
        except TimeoutError as exc:
            raise SpineRenderError("Spine worker 超过总预算") from exc
        finally:
            output.unlink(missing_ok=True)

    def list_animations(self, bundle: SpineBundle) -> list[str]:
        skeleton = self._inside_root(bundle.skeleton)
        atlas = self._inside_root(bundle.atlas)
        for texture in bundle.textures:
            self._inside_root(texture)
        if skeleton.suffix.lower() not in {".skel", ".json"}:
            raise SpineRenderError("Spine worker skeleton 后缀无效")
        command = [
            str(self.config.executable),
            "--skeleton",
            str(skeleton),
            "--atlas",
            str(atlas),
            "--list-animations",
        ]
        try:
            completed = _run_worker(command, cwd=self.config.bundle_root, timeout=self.config.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            raise SpineRenderError("Spine worker 超时") from exc
        if completed.returncode != 0:
            raise SpineRenderError("Spine worker 获取动画列表失败")
        try:
            report: Any = json.loads(completed.stdout.strip() or "{}")
        except json.JSONDecodeError as exc:
            raise SpineRenderError("Spine worker 响应不是 JSON") from exc
        if not isinstance(report, dict) or report.get("status") != "ok":
            raise SpineRenderError("Spine worker 获取动画列表未报告成功")
        anims = report.get("animations")
        if not isinstance(anims, list):
            raise SpineRenderError("Spine worker 返回的动画列表格式无效")
        return [str(a) for a in anims]

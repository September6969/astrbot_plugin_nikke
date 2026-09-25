#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""将现有维护 renderer 的 worker 参数安全转接给已构建的官方 Docker worker。"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Sequence


IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,254}$", re.ASCII)
PATH_OPTIONS = {"--skeleton", "--atlas", "--output"}
VALUE_OPTIONS = {"--animation", "--width", "--height"}


class DockerBridgeError(ValueError):
    """Docker worker 输入参数或路径不符合安全合同。"""


def _container_path(root: Path, value: str, *, must_exist: bool) -> str:
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    try:
        resolved = path.resolve(strict=must_exist)
    except (OSError, RuntimeError) as exc:
        raise DockerBridgeError("worker 文件路径无法解析") from exc
    if not resolved.is_relative_to(root):
        raise DockerBridgeError("worker 文件路径越界")
    if must_exist and not resolved.is_file():
        raise DockerBridgeError("worker 输入文件不存在")
    return "/bundle/" + resolved.relative_to(root).as_posix()


def build_docker_command(image: str, bundle_root: Path, worker_args: Sequence[str]) -> list[str]:
    """验证所有输入只落在单个候选 bundle 后构造无 shell 的 Docker argv。"""
    if not isinstance(image, str) or not IMAGE_RE.fullmatch(image):
        raise DockerBridgeError("worker 镜像名称无效")
    root = bundle_root.resolve(strict=True)
    if not root.is_dir():
        raise DockerBridgeError("bundle root 不是目录")

    mapped: list[str] = []
    seen: set[str] = set()
    index = 0
    while index < len(worker_args):
        option = worker_args[index]
        if option not in PATH_OPTIONS | VALUE_OPTIONS or option in seen:
            raise DockerBridgeError(f"不支持的 worker 参数: {option}")
        if index + 1 >= len(worker_args):
            raise DockerBridgeError(f"worker 参数缺少值: {option}")
        value = worker_args[index + 1]
        seen.add(option)
        if option in PATH_OPTIONS:
            mapped.extend((option, _container_path(root, value, must_exist=option != "--output")))
        elif option in {"--width", "--height"}:
            if not value.isdigit() or not 1 <= int(value) <= 4096:
                raise DockerBridgeError(f"worker 画布参数无效: {option}")
            mapped.extend((option, value))
        elif option == "--animation":
            if value not in {"idle", "setup"}:
                raise DockerBridgeError("worker animation 不在维护期白名单")
            mapped.extend((option, value))
        index += 2
    if not PATH_OPTIONS <= seen or not VALUE_OPTIONS <= seen:
        raise DockerBridgeError("worker 参数缺少必需项")

    return [
        "docker", "run", "--rm",
        "--env", "LIBGL_ALWAYS_SOFTWARE=1",
        "--mount", f"type=bind,source={root.as_posix()},target=/bundle",
        image,
        *mapped,
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("worker_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    worker_args = args.worker_args[1:] if args.worker_args[:1] == ["--"] else args.worker_args
    try:
        command = build_docker_command(args.image, args.bundle_root, worker_args)
        completed = subprocess.run(command, check=False, timeout=90)
    except (OSError, subprocess.SubprocessError, DockerBridgeError) as exc:
        print(f"Docker Spine worker 执行失败: {exc}", file=sys.stderr)
        return 2
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())

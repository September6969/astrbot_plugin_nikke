#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""为 Phase 3 维护工具约束外部输出路径，避免写入仓库或覆盖已有 evidence。"""

from __future__ import annotations

from pathlib import Path


def require_new_external_path(path: Path, repository_root: Path, *, label: str) -> Path:
    """返回一个尚不存在且位于仓库外的绝对目标路径。"""
    target = path.resolve(strict=False)
    root = repository_root.resolve(strict=True)
    if target.is_relative_to(root):
        raise ValueError(f"{label}必须写到仓库外")
    if target.exists():
        raise ValueError(f"{label}目标已存在；拒绝覆盖")
    return target

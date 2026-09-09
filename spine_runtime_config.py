# SPDX-License-Identifier: GPL-3.0-or-later
"""根据插件配置创建可选的 Spine runtime 编排器。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping

from .spine_prerenderer import SpineBundleFetcher, SpinePreRenderer
from .spine_runtime_worker import SpineWorkerConfig, SpineWorkerRuntime

logger = logging.getLogger("nikke.spine.config")


def build_spine_renderer(cache_dir: str | Path, config: Mapping[str, Any] | None = None) -> SpinePreRenderer:
    """只有明确配置且存在 worker 时启用 runtime，否则使用中性占位图。"""

    values = config if isinstance(config, Mapping) else {}
    worker_value = values.get("spine_worker_path", "")
    worker_path = Path(worker_value).expanduser() if isinstance(worker_value, str) and worker_value.strip() else None
    root = Path(cache_dir)
    bundle_root = root / "spine-bundles"
    if worker_path is None:
        return SpinePreRenderer(root)
    try:
        worker_path = worker_path.resolve()
    except OSError:
        logger.warning("Spine worker 路径无法解析，使用中性占位图")
        return SpinePreRenderer(root)
    if not worker_path.is_file():
        logger.warning("Spine worker 不存在，使用中性占位图")
        return SpinePreRenderer(root)
    version = str(values.get("spine_runtime_version", "4.0")).strip() or "4.0"
    timeout = values.get("spine_worker_timeout", 4)
    try:
        runtime = SpineWorkerRuntime(
            SpineWorkerConfig(
                executable=worker_path,
                bundle_root=bundle_root,
                timeout_seconds=float(timeout),
            ),
            version=version,
        )
    except (TypeError, ValueError, OSError):
        logger.warning("Spine worker 配置无效，使用中性占位图")
        return SpinePreRenderer(root)
    return SpinePreRenderer(
        root,
        runtime=runtime,
        fetcher=SpineBundleFetcher(bundle_root),
    )

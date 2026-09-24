# SPDX-License-Identifier: GPL-3.0-or-later
"""跨领域共享资源的唯一 provider。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...core.asset_manager import AssetManager
from ...core.storage import NikkeStore
from ...features.voice.audio import VoiceAudioCache
from ...integrations.blablalink.client import BlaBlaClient
from ...integrations.spine.config import build_spine_renderer
from ...ui.primitives import CardRenderer
from ..lifecycle.coordinator import RuntimeCoordinator
from .storage import create_nikke_store

logger = logging.getLogger("astrbot_plugin_nikke")


@dataclass(frozen=True)
class SharedResources:
    """每个容器唯一持有的基础资源实例。"""

    extension_zip: Path
    store: NikkeStore
    client: BlaBlaClient
    renderer: CardRenderer
    asset_manager: AssetManager
    runtime_coordinator: RuntimeCoordinator


def create_shared_resources(
    plugin_dir: Path, data_dir: Path, config: dict[str, Any]
) -> SharedResources:
    """只创建一次存储、网关、共享绘制资源和运行时协调器。"""
    extension_zip = data_dir / "nikke-bind-extension.zip"
    store = create_nikke_store(data_dir)
    client = BlaBlaClient(
        int(config.get("request_timeout", 20)),
        lambda message: logger.info(f"[NIKKE诊断] {message}"),
    )
    renderer = CardRenderer(data_dir / "cards", plugin_dir / "fonts")
    spine_budget = config.get("spine_budget_seconds", 20.0)
    asset_manager = AssetManager(
        data_dir / "cache",
        plugin_dir / "assets",
        remote=True,
        spine_renderer=build_spine_renderer(data_dir / "cache", config),
        spine_budget_seconds=(
            float(spine_budget)
            if isinstance(spine_budget, (int, float)) and spine_budget > 0
            else 20.0
        ),
        spine_manifest_path=data_dir / "spine-manifest.json",
        spine_rendered_dir=data_dir / "spine-rendered",
    )
    runtime_coordinator = RuntimeCoordinator()
    return SharedResources(
        extension_zip=extension_zip,
        store=store,
        client=client,
        renderer=renderer,
        asset_manager=asset_manager,
        runtime_coordinator=runtime_coordinator,
    )

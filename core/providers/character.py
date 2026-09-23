# SPDX-License-Identifier: GPL-3.0-or-later
"""Character 查询与绘制资源 provider。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ..._version import PLUGIN_VERSION
from ...features.account.ports import AccountStorePort
from ...features.character.application import CharacterApplication
from ...features.character.composition import create_character_card_builder
from ...features.character.identity import CharacterDirectoryResolver
from ...integrations.character.stat_resources import CharacterStatResourceLoader
from ...integrations.blablalink.client import BlaBlaClient
from ...ui.renderers import CharacterCardRenderer

logger = logging.getLogger("astrbot_plugin_nikke")


@dataclass(frozen=True)
class CharacterResources:
    """Character 应用和绘制所需的共享对象。"""

    application: CharacterApplication
    stat_resources: CharacterStatResourceLoader
    builder: Any
    identity: CharacterDirectoryResolver
    renderer: CharacterCardRenderer


def create_character_resources(
    plugin_dir: Path,
    data_dir: Path,
    *,
    account_reader: AccountStorePort,
    gateway: BlaBlaClient,
    clock: Callable[[], datetime],
    config: dict[str, Any],
    plugin_version: str = PLUGIN_VERSION,
) -> CharacterResources:
    """创建 Character application 与绘制资源；不持有共享 AssetManager。"""
    stat_resources = CharacterStatResourceLoader(
        data_dir / "cache" / "character-stats"
    )
    builder = create_character_card_builder(
        plugin_dir,
        unknown_ol_inventory_path=data_dir / "ol_unknown_inventory.json",
    )
    aliases = config.get("custom_character_aliases")
    alias_path = plugin_dir / "assets" / "character_aliases.json"
    try:
        identity = CharacterDirectoryResolver(alias_path, user_aliases=aliases)
    except ValueError as err:
        logger.error("[NIKKE] 用户自定义别名配置错误，已忽略自定义别名：%s", err)
        identity = CharacterDirectoryResolver(alias_path)
    application = CharacterApplication(
        account_reader=account_reader,
        gateway=gateway,
        identity=identity,
        stat_resources=stat_resources,
        card_builder=builder,
        clock=clock,
        plugin_version=plugin_version,
    )
    renderer = CharacterCardRenderer(data_dir / "cards", plugin_dir / "fonts")
    return CharacterResources(application, stat_resources, builder, identity, renderer)

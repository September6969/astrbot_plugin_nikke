# SPDX-License-Identifier: GPL-3.0-or-later
"""共享持久化资源 provider。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from ...core.storage import NikkeStore

StoreT = TypeVar("StoreT")


def create_nikke_store(
    data_dir: Path,
    *,
    store_factory: Callable[[Path], StoreT] = NikkeStore,
) -> StoreT:
    """为当前容器创建唯一 store；测试可注入满足消费者端口的 fake。"""
    data_dir.mkdir(parents=True, exist_ok=True)
    return store_factory(data_dir)

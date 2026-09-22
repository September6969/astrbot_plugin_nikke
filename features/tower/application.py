"""公开塔层速查用例，惰性加载并复用已核验快照。"""

import asyncio
import threading
from pathlib import Path
from typing import Callable

from .registry import TowerRegistry


class TowerApplication:
    UNAVAILABLE = "塔层静态资料暂不可用。"

    def __init__(
        self,
        snapshot_path: Path,
        *,
        registry_factory: Callable[[Path], TowerRegistry] | None = None,
    ) -> None:
        self.snapshot_path = Path(snapshot_path)
        self._registry_factory = registry_factory or TowerRegistry
        self._registry: TowerRegistry | None = None
        self._lock = threading.Lock()

    def _get_registry(self) -> TowerRegistry:
        if self._registry is None:
            with self._lock:
                if self._registry is None:
                    self._registry = self._registry_factory(self.snapshot_path)
        return self._registry

    async def preload(self) -> None:
        await asyncio.to_thread(self._get_registry)

    async def describe(self, tower: str, floor: str) -> str:
        try:
            registry = await asyncio.to_thread(self._get_registry)
            return registry.describe(tower, floor)
        except Exception:
            return self.UNAVAILABLE

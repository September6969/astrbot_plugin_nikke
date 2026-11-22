"""授权攻略分页用例与可复现展示日期。"""

import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from .registry import GuideEntry, GuideRegistry


@dataclass(frozen=True)
class GuidePage:
    entries: tuple[GuideEntry, ...]
    page_number: int
    total_entries: int
    total_pages: int
    current_date: date


RegistrySignature = tuple[int, int, int]


class GuideApplication:
    """攻略分页用例；已校验的索引按 registry.json 的 stat 签名缓存并热重载。

    PR-6B（G7-misc-dead-e）：不再每次命令都重新解析索引并 stat 全部图片。
    - 签名为 (st_mtime_ns, st_size, st_ino)；变化即重建。注意导入脚本以
      Path.write_text 原位改写时 inode 不变，有效签名是 mtime_ns + size，
      同尺寸且在 mtime 精度内的重写是已知的残余窗口；
    - registry.json 缺失时不缓存（签名为 None），之后新增的索引会被立即读取；
    - 加载失败（ValueError/OSError）永不缓存，下次调用重新校验并继续失败关闭；
    - 命中缓存时对本页返回的每张图片重新做与注册表相同的廉价校验（非符号链接、
      仍在根目录内、扩展名、大小上限）；任一不通过则丢弃缓存完整重建一次，由注册表
      校验失败关闭——缓存后被删除或被替换成越界符号链接的图片都不会被发送。
    """

    _IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
    _MAX_IMAGE_BYTES = 12 * 1024 * 1024

    def _image_still_valid(self, image: Path) -> bool:
        """与 GuideRegistry 加载时相同的单文件边界，命中缓存时逐页复核。"""
        try:
            root = self.registry_root.resolve()
            return (
                not image.is_symlink()
                and image.resolve().is_relative_to(root)
                and image.is_file()
                and image.suffix.lower() in self._IMAGE_SUFFIXES
                and image.stat().st_size <= self._MAX_IMAGE_BYTES
            )
        except OSError:
            return False

    def __init__(
        self,
        registry_root: Path,
        *,
        page_size: int = 3,
        clock: Callable[[], date] | None = None,
        registry_factory: Callable[[Path], GuideRegistry] | None = None,
    ) -> None:
        if not 1 <= page_size <= 10:
            raise ValueError("攻略分页大小必须为 1 到 10")
        self.registry_root = Path(registry_root)
        self.page_size = page_size
        self._clock = clock if clock is not None else date.today
        self._registry_factory = registry_factory if registry_factory is not None else GuideRegistry
        self._registry: GuideRegistry | None = None
        self._signature: RegistrySignature | None = None
        self._lock = threading.Lock()

    def _current_signature(self) -> RegistrySignature | None:
        try:
            stat = (self.registry_root / "registry.json").stat()
        except FileNotFoundError:
            return None
        return (stat.st_mtime_ns, stat.st_size, stat.st_ino)

    def _load_registry(self, *, force: bool = False) -> GuideRegistry:
        signature = self._current_signature()
        with self._lock:
            cached = self._registry
            if not force and cached is not None and signature is not None and signature == self._signature:
                return cached
        registry = self._registry_factory(self.registry_root)
        with self._lock:
            if signature is None:
                self._registry, self._signature = None, None
            else:
                self._registry, self._signature = registry, signature
        return registry

    def invalidate(self) -> None:
        """丢弃已缓存的索引，下次查询重新读取并校验。"""
        with self._lock:
            self._registry, self._signature = None, None

    def page(self, category: str, page_number: int = 1) -> GuidePage:
        registry = self._load_registry()
        entries = registry.page(category, page=page_number, size=self.page_size)
        if any(not self._image_still_valid(image) for entry in entries for image in entry.files):
            # 缓存后图片被删除、越界或超限：完整重建一次，由注册表校验失败关闭。
            self.invalidate()
            registry = self._load_registry(force=True)
            entries = registry.page(category, page=page_number, size=self.page_size)
        matching = tuple(
            entry for entry in registry.entries if entry.category == category
        )
        total_entries = len(matching)
        total_pages = (total_entries + self.page_size - 1) // self.page_size
        return GuidePage(
            entries=tuple(entries),
            page_number=page_number,
            total_entries=total_entries,
            total_pages=total_pages,
            current_date=self._clock(),
        )

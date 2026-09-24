"""授权攻略分页用例与可复现展示日期。"""

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


class GuideApplication:
    def __init__(
        self,
        registry_root: Path,
        *,
        page_size: int = 3,
        clock: Callable[[], date] | None = None,
    ) -> None:
        if not 1 <= page_size <= 10:
            raise ValueError("攻略分页大小必须为 1 到 10")
        self.registry_root = Path(registry_root)
        self.page_size = page_size
        self._clock = clock if clock is not None else date.today

    def page(self, category: str, page_number: int = 1) -> GuidePage:
        registry = GuideRegistry(self.registry_root)
        matching = tuple(
            entry for entry in registry.entries if entry.category == category
        )
        total_entries = len(matching)
        total_pages = (total_entries + self.page_size - 1) // self.page_size
        entries = registry.page(category, page=page_number, size=self.page_size)
        return GuidePage(
            entries=tuple(entries),
            page_number=page_number,
            total_entries=total_entries,
            total_pages=total_pages,
            current_date=self._clock(),
        )

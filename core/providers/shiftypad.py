# SPDX-License-Identifier: GPL-3.0-or-later
"""ShiftyPad 只读导入资源装配。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from ...integrations.shiftypad.official import OfficialPublicProfileFetcher
from ...features.shiftypad.identity import UidMappingResolver
from ...features.shiftypad.storage import ShiftypadReadOnlyStore
from ...integrations.web.shiftypad_service import ShiftypadWebService


@dataclass(frozen=True)
class ShiftypadResources:
    resolver: UidMappingResolver
    fetcher: Any
    readonly: ShiftypadReadOnlyStore
    web: ShiftypadWebService


def create_shiftypad_resources(
    *,
    data_dir: Path,
    store: Any,
    site_origin: str,
    config: Mapping[str, Any] | None = None,
    clock: Callable[[], Any] | None = None,
) -> ShiftypadResources:
    """默认只用官方公开档案；UID 映射缺失时保持不可用而不是猜测。"""
    config = config or {}
    raw = str(config.get("shiftypad_uid_map_path") or "").strip()
    mapping_path = Path(raw) if raw else data_dir / "shiftypad-uid-map.json"
    resolver = UidMappingResolver.from_file(mapping_path)
    fetcher = OfficialPublicProfileFetcher()
    readonly = ShiftypadReadOnlyStore(store, clock=clock)
    web = ShiftypadWebService(
        store=store,
        readonly=readonly,
        resolver=resolver,
        fetcher=fetcher,
        site_origin=site_origin,
        clock=clock,
    )
    return ShiftypadResources(resolver=resolver, fetcher=fetcher, readonly=readonly, web=web)


__all__ = ["ShiftypadResources", "create_shiftypad_resources"]

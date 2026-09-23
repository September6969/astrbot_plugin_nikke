# SPDX-License-Identifier: GPL-3.0-or-later
"""资源服务的稳定返回类型。"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from ...features.character.models import SpineBundle


@dataclass(slots=True)
class AssetResult:
    """角色与皮肤视觉资源定位结果，严格区分精确匹配与降级。"""

    image: Image.Image | None = None
    exact_match: bool = True
    fallback_reason: str | None = None
    asset_key: str | None = None
    resource_id: str | None = None
    costume_id: str | None = None
    requested_kind: str | None = None
    resolved_kind: str | None = None
    source: str | None = None
    logical_key: str | None = None
    bundle: SpineBundle | None = None

    @property
    def asset(self) -> object | None:
        """统一资源实体访问：Spine 返回 bundle，图像返回 image。"""
        return self.bundle if self.bundle is not None else self.image

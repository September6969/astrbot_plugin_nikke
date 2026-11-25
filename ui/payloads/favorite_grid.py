# SPDX-License-Identifier: GPL-3.0-or-later
"""本命九宫格 payload（29）；顺序与输入一致，缺失立绘保留稳定占位。"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from ..t2i_assets import T2IAssetResolver

CANVAS_SIZE = 1080


class FavoriteGridPayloadBuilder:
    def __init__(self, assets=None, resolver=None) -> None:
        self.assets = assets
        self.resolver = resolver or T2IAssetResolver()

    def _portrait(self, cell: Mapping[str, Any]) -> str | None:
        if not self.assets:
            return None
        resource_id = str(cell.get("resource_id") or "")
        if not resource_id:
            return None
        try:
            image, fallback = self.assets.get_lineup_portrait_by_resource_id(resource_id)
            if fallback:
                return None
            return self.resolver.encode(image, (320, 320))
        except Exception:
            return None

    @staticmethod
    def _as_dict(cell: Any) -> dict[str, Any]:
        if isinstance(cell, Mapping):
            return dict(cell)
        to_dict = getattr(cell, "to_dict", None)
        if callable(to_dict):
            return dict(to_dict())
        return {
            key: getattr(cell, key, "")
            for key in ("index", "name", "name_code", "resource_id", "burst", "element")
        }

    def build(self, cells: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        items = [self._as_dict(cell) for cell in cells]
        rows = []
        for position, cell in enumerate(items, 1):
            rows.append(
                {
                    "index": position,
                    "name": str(cell.get("name") or "未知妮姬"),
                    "name_code": str(cell.get("name_code") or ""),
                    "burst": str(cell.get("burst") or ""),
                    "element": str(cell.get("element") or ""),
                    "portrait": self._portrait(cell),
                }
            )
        return {
            "title": "本命九宫格",
            "cells": rows,
            "canvas": {"width": CANVAS_SIZE, "height": CANVAS_SIZE},
        }


__all__ = ["FavoriteGridPayloadBuilder"]

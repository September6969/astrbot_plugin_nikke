# SPDX-License-Identifier: GPL-3.0-or-later
"""Spine 后台运行时 metadata 的校验、原子落盘和读取。"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any


class SpineRuntimeMetadataStore:
    """按 render_id 保存单条 metadata，拒绝不完整或不匹配的记录。"""

    ASSET_ID = re.compile(r"^c[0-9]+(?:_[0-9]+)?$", re.ASCII)

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def _render_id(cls, value: object) -> str:
        if not isinstance(value, str) or not cls.ASSET_ID.fullmatch(value.strip().lower()):
            raise ValueError("runtime metadata render_id 无效")
        return value.strip().lower()

    @staticmethod
    def _finite(value: object) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))

    @classmethod
    def validate_record(cls, render_id: str, record: dict[str, Any], image) -> dict[str, Any]:
        key = cls._render_id(render_id)
        if not isinstance(record, dict) or record.get("render_id", key) != key:
            raise ValueError("runtime metadata 身份不匹配")
        size = record.get("image_size")
        point = record.get("point")
        digest = record.get("pixel_sha256")
        if size != list(image.size) or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("runtime metadata 缺少图像绑定字段")
        actual = hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest()
        if actual != digest:
            raise ValueError("runtime metadata pixel_sha256 不匹配")
        if not isinstance(point, list) or len(point) != 2 or not all(cls._finite(item) for item in point):
            raise ValueError("runtime metadata point 无效")
        result = dict(record)
        result["render_id"] = key
        return result

    def write_record(self, render_id: str, record: dict[str, Any], image) -> Path:
        key = self._render_id(render_id)
        validated = self.validate_record(key, record, image)
        target = self.root / f"{key}.json"
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(json.dumps(validated, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def read_records(self) -> dict[str, dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        try:
            paths = sorted(self.root.glob("c*.json"))
        except OSError:
            return records
        for path in paths:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                key = self._render_id(raw.get("render_id", path.stem)) if isinstance(raw, dict) else ""
                if key and isinstance(raw, dict):
                    records[key] = raw
            except (OSError, UnicodeError, ValueError, AttributeError):
                continue
        return records


__all__ = ["SpineRuntimeMetadataStore"]

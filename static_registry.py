# SPDX-License-Identifier: GPL-3.0-or-later
"""带来源和内容 hash 的静态 NIKKE 资源标识 registry。

这里只登记已确认的资源标识，不从 ID 连续性或 combat 数据推导角色属性。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path


class RegistryValidationError(ValueError):
    """静态 registry 或其来源清单不符合合同。"""


@dataclass(frozen=True, slots=True)
class RegistryMetadata:
    kind: str
    path: str
    source: str
    source_ref: str
    checked_at: str
    sha256: str
    license_boundary: str


class StaticDataRegistry:
    """加载并校验 Equipment/Cube/Favorite Item 的只读标识映射。"""

    MANIFEST = "registry_manifest.json"
    FILES = {
        "equipment": "equipment.json",
        "cube": "cubes.json",
        "favorite_item": "favorite_items.json",
    }
    ID_PATTERN = re.compile(r"^\d+$")
    VALUE_PATTERNS = {
        "equipment": re.compile(
            r"^icn_equipment_(head|body|arm|leg)_(attacker|defender|supporter)_t[1-9]\d*(?:_\d+)?$"
        ),
        "cube": re.compile(r"^harmony_cube_\d+$"),
        "favorite_item": re.compile(r"^favorite_item_\d+$"),
    }

    def __init__(self, asset_dir: str | Path):
        self.asset_dir = Path(asset_dir).resolve()
        self.errors: list[str] = []
        self._maps: dict[str, dict[str, str]] = {}
        self._metadata: dict[str, RegistryMetadata] = {}
        self._load()

    @property
    def is_valid(self) -> bool:
        return not self.errors and set(self._maps) == set(self.FILES)

    def mapping(self, kind: str) -> dict[str, str]:
        """返回指定 registry 的副本，未知 kind 不产生猜测。"""
        return dict(self._maps.get(kind, {}))

    def metadata(self, kind: str) -> RegistryMetadata | None:
        return self._metadata.get(kind)

    def resolve(self, kind: str, resource_id: str | int | None) -> str | None:
        """按精确 ID 查找资源，未知 ID 返回 None。"""
        key = str(resource_id or "").strip()
        if not self.ID_PATTERN.fullmatch(key):
            return None
        return self._maps.get(kind, {}).get(key)

    def _load(self) -> None:
        try:
            manifest_bytes = (self.asset_dir / self.MANIFEST).read_bytes()
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
                raise RegistryValidationError("registry manifest schema_version 无效")
            rows = manifest.get("registries")
            if not isinstance(rows, dict):
                raise RegistryValidationError("registry manifest 缺少 registries")
        except (OSError, UnicodeError, json.JSONDecodeError, RegistryValidationError) as exc:
            self.errors.append(str(exc))
            return

        for kind, expected_path in self.FILES.items():
            try:
                entry = rows[kind]
                metadata = self._parse_metadata(kind, entry, expected_path)
                path = (self.asset_dir / metadata.path).resolve()
                if not path.is_relative_to(self.asset_dir):
                    raise RegistryValidationError(f"{kind} path 越界")
                content = path.read_bytes()
                # Git 在不同平台可能检出 CRLF；hash 合同统一使用 LF canonical bytes。
                canonical_content = content.replace(b"\r\n", b"\n")
                digest = hashlib.sha256(canonical_content).hexdigest()
                if digest != metadata.sha256:
                    raise RegistryValidationError(f"{kind} sha256 不匹配")
                data = json.loads(content.decode("utf-8"))
                self._maps[kind] = self._parse_mapping(kind, data)
                self._metadata[kind] = metadata
            except (KeyError, OSError, UnicodeError, json.JSONDecodeError, RegistryValidationError) as exc:
                self.errors.append(f"{kind}: {exc}")

    @classmethod
    def _parse_metadata(cls, kind: str, entry, expected_path: str) -> RegistryMetadata:
        if not isinstance(entry, dict):
            raise RegistryValidationError("来源条目无效")
        fields = ("path", "source", "source_ref", "checked_at", "sha256", "license_boundary")
        if any(not isinstance(entry.get(field), str) or not entry[field].strip() for field in fields):
            raise RegistryValidationError("来源元数据缺失")
        if entry["path"] != expected_path:
            raise RegistryValidationError("registry path 不符合预期")
        sha256 = entry["sha256"].lower()
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise RegistryValidationError("sha256 格式无效")
        return RegistryMetadata(kind, entry["path"], entry["source"], entry["source_ref"],
                                entry["checked_at"], sha256, entry["license_boundary"])

    @classmethod
    def _parse_mapping(cls, kind: str, data) -> dict[str, str]:
        if not isinstance(data, dict) or not data:
            raise RegistryValidationError("映射必须是非空对象")
        pattern = cls.VALUE_PATTERNS[kind]
        result: dict[str, str] = {}
        for resource_id, resource_name in data.items():
            if not isinstance(resource_id, str) or not cls.ID_PATTERN.fullmatch(resource_id):
                raise RegistryValidationError(f"{kind} ID 无效: {resource_id!r}")
            if not isinstance(resource_name, str) or not pattern.fullmatch(resource_name):
                raise RegistryValidationError(f"{kind} resource 标识无效: {resource_name!r}")
            result[resource_id] = resource_name
        return result

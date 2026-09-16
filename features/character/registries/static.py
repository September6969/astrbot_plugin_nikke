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
    """加载并校验资源类型的只读标识映射。"""

    MANIFEST = "registry_manifest.json"
    FILES = {
        "equipment": "equipment.json",
        "cube": "cubes.json",
        "favorite_item": "favorite_items.json",
        "costume": "costumes.json",
    }
    ID_PATTERN = re.compile(r"^\d+$")
    COSTUME_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[_-][a-z0-9]+)*$")
    VALUE_PATTERNS = {
        "equipment": re.compile(
            r"^icn_equipment_(head|body|arm|leg)_(attacker|defender|supporter)_t[1-9]\d*(?:_\d+)?$"
        ),
        "cube": re.compile(r"^(harmony_cube_\d+|ie_\d+)$"),
        "favorite_item": re.compile(r"^(favorite_item_\d+|si_favoriteitem_[a-z0-9_]+)$"),
        "costume": re.compile(r"^c\d+(?:_\d+)?$"),
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
        if isinstance(resource_id, bool) or not isinstance(resource_id, (str, int)):
            return None
        key = str(resource_id)
        id_pattern = self.COSTUME_ID_PATTERN if kind == "costume" else self.ID_PATTERN
        if not id_pattern.fullmatch(key):
            return None
        return self._maps.get(kind, {}).get(key)

    VERIFIED_CUBE_NAMES: dict[str, str] = {
        "1000301": "遗迹突击魔方",
        "1000302": "战术突击魔方",
        "1000303": "遗迹巨熊魔方",
        "1000304": "战术巨熊魔方",
        "1000305": "遗迹促进魔方",
        "1000306": "战术促进魔方",
        "1000307": "遗迹量子魔方",
        "1000308": "体力神器魔方",
        "1000309": "遗迹强韧魔方",
        "1000310": "遗迹治疗魔方",
        "1000311": "遗迹回火魔方",
        "1000312": "遗迹辅助魔方",
        "1000313": "遗迹毁灭魔方",
        "1000314": "遗迹穿透魔方",
    }

    VERIFIED_FAVORITE_ITEM_NAMES: dict[str, str] = {
        # 收藏品 - R
        "100101": "料理指挥官娃娃",
        "100201": "购物指挥官娃娃",
        "100301": "运动指挥官娃娃",
        "100401": "战斗指挥官娃娃",
        "100501": "咖啡指挥官娃娃",
        "100601": "午睡指挥官娃娃",
        # 收藏品 - SR 限量版
        "100102": "料理指挥官娃娃（限量版）",
        "100202": "购物指挥官娃娃（限量版）",
        "100302": "运动指挥官娃娃（限量版）",
        "100402": "战斗指挥官娃娃（限量版）",
        "100502": "咖啡指挥官娃娃（限量版）",
        "100602": "午睡指挥官娃娃（限量版）",
        # 珍藏品 - SSR
        "200101": "玩具火车套组",
        "200201": "Gamekid EVO",
        "200301": "心爱的枕头",
        "200401": "《英雄三部曲》蓝光光盘",
        "200501": "第一支手机和联络人记录簿",
        "200601": "手写信",
        "200701": "老旧的罗盘",
        "200801": "反派模型",
        "200901": "情侣马克杯",
        "201001": "刑警手册",
        "201101": "打火器",
        "201201": "乐谱笔记",
        "201301": "啦啦队鞋",
        "201401": "中央政府特别勋章",
        "201501": "四叶草书签",
        "201601": "金属项链",
        "201701": "牡丹花造型发簪",
        "201801": "珍贵的面具们",
        "201901": "共同制作的花盆",
        "202001": "印章戒指",
        "202101": "纪念钥匙圈",
    }

    @classmethod
    def resolve_display_name(cls, kind: str, resource_id: str | int | None) -> str | None:
        """解析魔方或收藏品/珍藏品的已验证中文名称，未知或未登记录返回 None。"""
        if isinstance(resource_id, bool) or not isinstance(resource_id, (str, int)):
            return None
        key = str(resource_id).strip()
        if not cls.ID_PATTERN.fullmatch(key):
            return None
        if kind == "cube":
            return cls.VERIFIED_CUBE_NAMES.get(key)
        if kind in ("favorite_item", "favorite"):
            return cls.VERIFIED_FAVORITE_ITEM_NAMES.get(key)
        return None

    @staticmethod
    def _reject_duplicate_keys(pairs):
        """拒绝 JSON 重复键，避免歧义映射被静默覆盖。"""
        result = {}
        for key, value in pairs:
            if key in result:
                raise RegistryValidationError(f"JSON 对象包含重复键: {key!r}")
            result[key] = value
        return result

    def _load(self) -> None:
        try:
            manifest_bytes = (self.asset_dir / self.MANIFEST).read_bytes()
            manifest = json.loads(
                manifest_bytes.decode("utf-8"),
                object_pairs_hook=self._reject_duplicate_keys,
            )
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
                data = json.loads(
                    content.decode("utf-8"),
                    object_pairs_hook=self._reject_duplicate_keys,
                )
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
        if kind == "costume":
            return cls._parse_costume_mapping(data)
        if not isinstance(data, dict) or not data:
            raise RegistryValidationError("映射必须是非空对象")
        pattern = cls.VALUE_PATTERNS[kind]
        id_pattern = cls.COSTUME_ID_PATTERN if kind == "costume" else cls.ID_PATTERN
        result: dict[str, str] = {}
        for resource_id, resource_name in data.items():
            if not isinstance(resource_id, str) or not id_pattern.fullmatch(resource_id):
                raise RegistryValidationError(f"{kind} ID 无效: {resource_id!r}")
            if not isinstance(resource_name, str) or not pattern.fullmatch(resource_name):
                raise RegistryValidationError(f"{kind} resource 标识无效: {resource_name!r}")
            result[resource_id] = resource_name
        return result

    @classmethod
    def _parse_costume_mapping(cls, data) -> dict[str, str]:
        """解析 costume_id → canonical Spine identity 的 v2/v3 清单。"""
        if not isinstance(data, dict) or data.get("schema_version") not in {2, 3}:
            raise RegistryValidationError("costume registry schema_version 无效")
        entries = data.get("entries")
        if not isinstance(entries, list):
            raise RegistryValidationError("costume registry 缺少 entries")
        result: dict[str, str] = {}
        for row in entries:
            if not isinstance(row, dict):
                raise RegistryValidationError("costume registry 条目无效")
            required = ("costume_id", "character_resource_id", "source", "source_sha256", "verified_at")
            if any(not isinstance(row.get(field), (str, int)) or not str(row[field]).strip() for field in required):
                raise RegistryValidationError("costume registry 来源字段缺失")
            costume_id = str(row["costume_id"])
            owner = str(row["character_resource_id"])
            spine = row.get("spine")
            if isinstance(spine, dict):
                mode = spine.get("mode")
                asset_id = str(spine.get("asset_id", ""))
                skin_name = spine.get("skin_name")
                if mode not in {"independent_asset", "shared_skin"}:
                    raise RegistryValidationError("costume Spine mode 无效")
                if mode == "independent_asset" and skin_name is not None:
                    raise RegistryValidationError("independent costume 不得提供 skin_name")
                if mode == "shared_skin" and (not isinstance(skin_name, str) or not skin_name.strip()):
                    raise RegistryValidationError("shared costume 缺少 skin_name")
            else:
                asset_id = str(row.get("spine_asset_id", ""))
            if not cls.COSTUME_ID_PATTERN.fullmatch(costume_id):
                raise RegistryValidationError(f"costume ID 无效: {costume_id!r}")
            if not re.fullmatch(r"(?:c\d+|\d+)", owner, re.IGNORECASE):
                raise RegistryValidationError(f"costume character_resource_id 无效: {owner!r}")
            if not cls.VALUE_PATTERNS["costume"].fullmatch(asset_id):
                raise RegistryValidationError(f"costume Spine identity 无效: {asset_id!r}")
            if not re.fullmatch(r"[0-9a-fA-F]{64}", str(row["source_sha256"])):
                raise RegistryValidationError("costume source_sha256 无效")
            if costume_id in result:
                raise RegistryValidationError(f"costume ID 重复: {costume_id!r}")
            result[costume_id] = asset_id
        return result

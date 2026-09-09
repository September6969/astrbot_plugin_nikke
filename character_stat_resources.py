# SPDX-License-Identifier: GPL-3.0-or-later
"""ExiaInvasion/NIKKE 官方静态属性资源的来源、缓存和 single-flight loader。"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import httpx

from .asset_manager import AssetManager
from .character_stat_calculator import CharacterStatTables, StatCalculationError


EXIA_REFERENCE_COMMIT = "a6e653691d6a6d685f89c54694fadbf800e5d4b2"
EXIA_LEVEL_STATS_URL = (
    "https://raw.githubusercontent.com/ExiaProject/ExiaInvasion/"
    f"{EXIA_REFERENCE_COMMIT}/exia-invasion/public/level-stats.json"
)
EXIA_CUBES_URL = (
    "https://raw.githubusercontent.com/ExiaProject/ExiaInvasion/"
    f"{EXIA_REFERENCE_COMMIT}/exia-invasion/public/cubes.json"
)


@dataclass(frozen=True, slots=True)
class StaticResourceSpec:
    key: str
    url: str
    cache_name: str


BASE_RESOURCE_SPECS = (
    StaticResourceSpec("level_stats", EXIA_LEVEL_STATS_URL, "level-stats.json"),
    StaticResourceSpec("cube_catalog", EXIA_CUBES_URL, "cube-catalog.json"),
    StaticResourceSpec(
        "research_table",
        AssetManager.game_resource_url("character/RecycleResearchStatTable.json"),
        "research.json",
    ),
    StaticResourceSpec(
        "attractive_table",
        AssetManager.game_resource_url("character/AttractiveLevelTable.json"),
        "attractive.json",
    ),
    StaticResourceSpec(
        "equipment_table",
        AssetManager.game_resource_url("equip/ItemEquipTable-zh-tw.json"),
        "equipment.json",
    ),
)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def map_research_levels(researches: Any) -> dict[str, int | None]:
    """把 Profile Outpost 的 tid/lv 列表映射为 Exia 计算合同。"""
    result: dict[str, int | None] = {
        "general": None,
        "attacker": None,
        "defender": None,
        "supporter": None,
        "elysion": None,
        "missilis": None,
        "tetra": None,
        "pilgrim": None,
        "abnormal": None,
    }
    key_by_id = {
        1001: "general",
        1101: "attacker",
        1102: "defender",
        1103: "supporter",
        1201: "elysion",
        1202: "missilis",
        1203: "tetra",
        1204: "pilgrim",
        1205: "abnormal",
    }
    if not isinstance(researches, list):
        return result
    for row in researches:
        if not isinstance(row, Mapping):
            continue
        raw_tid, raw_level = row.get("tid"), row.get("lv")
        # 拒绝布尔值、小数和宽松转换，避免异常研究等级进入真实属性计算。
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, str))
            or not str(value).isascii()
            or not str(value).isdigit()
            for value in (raw_tid, raw_level)
        ):
            continue
        tid, level = int(raw_tid), int(raw_level)
        if tid in key_by_id and level >= 0:
            result[key_by_id[tid]] = level
    return result


class CharacterStatResourceLoader:
    """公共静态表加载器；缓存内容不携带账号 Cookie、token 或私有 header。"""

    CACHE_SCHEMA_VERSION = 1

    def __init__(
        self,
        cache_dir: str | Path,
        *,
        fetcher: Callable[[str], bytes] | None = None,
        timeout_seconds: float = 12.0,
    ):
        self.cache_dir = Path(cache_dir)
        self.fetcher = fetcher or self._fetch
        self.timeout_seconds = timeout_seconds
        self._lock = threading.RLock()
        self._payloads: dict[str, Any] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
        self._cube_records: dict[str, Any] = {}
        self._favorite_records: dict[str, Any] = {}

    def _fetch(self, url: str) -> bytes:
        with httpx.Client(timeout=self.timeout_seconds, follow_redirects=False) as client:
            response = client.get(url, headers={"Accept": "application/json"})
            response.raise_for_status()
            return response.content

    @staticmethod
    def _safe_identifier(value: object) -> str:
        text = str(value or "").strip()
        if not text or any(char in text for char in ("/", "\\", ":", "\x00")):
            raise StatCalculationError("静态资源 ID 非法")
        return text

    def _cache_path(self, cache_name: str) -> Path:
        path = self.cache_dir / cache_name
        if not path.resolve().is_relative_to(self.cache_dir.resolve()):
            raise StatCalculationError("静态资源缓存路径越界")
        return path

    def _read_cache(self, spec: StaticResourceSpec) -> Any | None:
        path = self._cache_path(spec.cache_name)
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError):
            return None
        if not isinstance(envelope, Mapping):
            return None
        if (
            envelope.get("schema_version") != self.CACHE_SCHEMA_VERSION
            or envelope.get("source_url") != spec.url
            or not isinstance(envelope.get("payload"), (Mapping, list))
        ):
            return None
        digest = hashlib.sha256(_json_bytes(envelope["payload"])).hexdigest()
        if digest != envelope.get("payload_sha256"):
            return None
        self._metadata[spec.key] = dict(envelope)
        return envelope["payload"]

    def _write_cache(self, spec: StaticResourceSpec, payload: Any, source_sha256: str) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._cache_path(spec.cache_name)
        envelope = {
            "schema_version": self.CACHE_SCHEMA_VERSION,
            "source_url": spec.url,
            "source_sha256": source_sha256,
            "payload_sha256": hashlib.sha256(_json_bytes(payload)).hexdigest(),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        temporary = path.with_name(f".{path.name}.{threading.get_ident()}.tmp")
        temporary.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
        self._metadata[spec.key] = envelope

    def _load_spec(self, spec: StaticResourceSpec, *, refresh: bool = False) -> Any:
        with self._lock:
            if not refresh and spec.key in self._payloads:
                return self._payloads[spec.key]
            if not refresh:
                cached = self._read_cache(spec)
                if cached is not None:
                    self._payloads[spec.key] = cached
                    return cached
            raw = self.fetcher(spec.url)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise StatCalculationError(f"{spec.key} 静态资源不是有效 JSON") from exc
            if not isinstance(payload, (Mapping, list)):
                raise StatCalculationError(f"{spec.key} 静态资源结构无效")
            self._write_cache(spec, payload, hashlib.sha256(raw).hexdigest())
            self._payloads[spec.key] = payload
            return payload

    @staticmethod
    def _records(payload: Any, label: str) -> list[Mapping[str, Any]]:
        records = payload.get("records") if isinstance(payload, Mapping) else None
        if not isinstance(records, list) or not records or not all(isinstance(x, Mapping) for x in records):
            raise StatCalculationError(f"{label} 静态表为空或结构无效")
        return list(records)

    def load_base(self, *, refresh: bool = False) -> CharacterStatTables:
        """一次加载并校验 level/research/attractive/equipment/cube catalog。"""
        with self._lock:
            values = {spec.key: self._load_spec(spec, refresh=refresh) for spec in BASE_RESOURCE_SPECS}
            level_stats = values["level_stats"]
            if not isinstance(level_stats, Mapping) or not isinstance(level_stats.get("curves"), Mapping):
                raise StatCalculationError("Exia level-stats.json 曲线缺失")
            for class_name in ("attacker", "defender", "supporter"):
                curves = level_stats["curves"].get(class_name)
                def_curves = curves.get("defByWeapon") if isinstance(curves, Mapping) else None
                if (
                    not isinstance(curves, Mapping)
                    or not isinstance(curves.get("hp"), list)
                    or len(curves["hp"]) < 525
                    or not isinstance(curves.get("atk"), list)
                    or len(curves["atk"]) < 525
                    or not isinstance(def_curves, Mapping)
                    or not {"RL", "AR", "SMG", "SG", "SR", "MG"}.issubset(def_curves)
                    or any(not isinstance(values, list) or len(values) < 525 for values in def_curves.values())
                ):
                    raise StatCalculationError(f"{class_name} 等级曲线不完整")
            if not isinstance(level_stats.get("statEnhance"), Mapping):
                raise StatCalculationError("Exia statEnhance 缺失")
            cube_catalog = values["cube_catalog"]
            if not isinstance(cube_catalog, Mapping) or not isinstance(cube_catalog.get("cubes"), list):
                raise StatCalculationError("Exia cubes.json 缺失")
            self._records(values["research_table"], "研究")
            self._records(values["attractive_table"], "好感度")
            self._records(values["equipment_table"], "装备")
            return self.tables()

    def _dynamic_spec(self, kind: str, identifier: object) -> StaticResourceSpec:
        safe = self._safe_identifier(identifier)
        if kind == "cube":
            logical = f"equip/zh-tw/cube_{safe}.json"
        elif kind == "favorite":
            logical = f"equip/zh-tw/favorite_{safe}.json"
        else:
            raise StatCalculationError("动态静态资源类型无效")
        return StaticResourceSpec(kind + "_" + safe, AssetManager.game_resource_url(logical), f"{kind}-{safe}.json")

    def ensure_ids(self, *, cube_ids: list[object] | None = None, favorite_ids: list[object] | None = None) -> CharacterStatTables:
        with self._lock:
            for identifier in sorted({str(x) for x in (cube_ids or []) if x not in (None, "", 0, "0")}):
                spec = self._dynamic_spec("cube", identifier)
                self._cube_records[identifier] = self._load_spec(spec)
            for identifier in sorted({str(x) for x in (favorite_ids or []) if x not in (None, "", 0, "0")}):
                spec = self._dynamic_spec("favorite", identifier)
                self._favorite_records[identifier] = self._load_spec(spec)
            return self.tables()

    def prepare_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """为一张卡去重加载对应 cube/favorite，并附加已核验表快照。"""
        detail = payload.get("detail") if isinstance(payload, Mapping) else {}
        detail = detail if isinstance(detail, Mapping) else {}
        self.load_base()
        self.ensure_ids(
            cube_ids=[detail.get("harmony_cube_tid")],
            favorite_ids=[detail.get("favorite_item_tid")],
        )
        prepared = dict(payload)
        prepared["stat_tables"] = self.tables_mapping()
        return prepared

    def tables(self) -> CharacterStatTables:
        values = self._payloads
        return CharacterStatTables(
            level_stats=values.get("level_stats"),
            research_table=values.get("research_table"),
            attractive_table=values.get("attractive_table"),
            equipment_table=values.get("equipment_table"),
            cube_records=dict(self._cube_records),
            favorite_records=dict(self._favorite_records),
            cube_catalog=values.get("cube_catalog"),
            verified=True,
            source_ref=f"ExiaInvasion@{EXIA_REFERENCE_COMMIT};NIKKE-game-CDN-hashed-json",
            checked_at=max(
                (str(meta.get("fetched_at", "")) for meta in self._metadata.values()),
                default="",
            ),
        )

    def tables_mapping(self) -> dict[str, Any]:
        return {
            "status": "VERIFIED_STATIC_RESOURCES",
            "source_ref": self.tables().source_ref,
            "checked_at": self.tables().checked_at,
            "level_stats": self.tables().level_stats,
            "research_table": self.tables().research_table,
            "attractive_table": self.tables().attractive_table,
            "equipment_table": self.tables().equipment_table,
            "cube_catalog": self.tables().cube_catalog,
            "cube_records": self.tables().cube_records,
            "favorite_records": self.tables().favorite_records,
            "verified": True,
        }

    def source_report(self) -> dict[str, Any]:
        return {
            key: {
                "url": meta.get("source_url"),
                "sha256": meta.get("source_sha256"),
                "cache": str(self._cache_path(next(spec.cache_name for spec in BASE_RESOURCE_SPECS if spec.key == key)))
                if any(spec.key == key for spec in BASE_RESOURCE_SPECS)
                else None,
            }
            for key, meta in self._metadata.items()
        }

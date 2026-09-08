"""公开静态塔层速查；不估计玩家进度与通关能力。"""
import json
import re
from datetime import date
from pathlib import Path


class TowerRegistry:
    ALIASES = {"部落": "tribe", "综合": "tribe", "极乐净土": "elysion", "米西利斯": "missilis", "泰特拉": "tetra", "朝圣者": "pilgrim"}
    TOWERS = frozenset({"tribe", "elysion", "missilis", "tetra", "pilgrim"})
    MAX_FLOOR = 10000
    MAX_RECORDS = 20000
    _FLOOR_KEY = re.compile(r"^(tribe|elysion|missilis|tetra|pilgrim):([1-9][0-9]*)$")
    _SHA256 = re.compile(r"^[0-9a-f]{64}$")

    def __init__(self, path: Path):
        data = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=self._reject_duplicate_keys,
        )
        self.source, self.updated_at, self.source_sha256, self.floors = self._parse_snapshot(data)

    @staticmethod
    def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        """拒绝重复 JSON 键，避免静默覆盖造成快照合同歧义。"""

        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("塔层快照 JSON 键重复")
            result[key] = value
        return result

    @classmethod
    def _parse_snapshot(cls, data: object) -> tuple[str, str, str, dict[str, dict[str, int]]]:
        if not isinstance(data, dict):
            raise ValueError("塔层快照必须是对象")

        source = data.get("source")
        retrieved_at = data.get("retrieved_at")
        source_sha256 = data.get("normalized_source_sha256")
        floors = data.get("floors")
        if not isinstance(source, str) or not source or source.strip() != source:
            raise ValueError("塔层快照缺少有效来源")
        if not isinstance(retrieved_at, str):
            raise ValueError("塔层快照日期无效")
        try:
            parsed_date = date.fromisoformat(retrieved_at)
        except ValueError as exc:
            raise ValueError("塔层快照日期无效") from exc
        if parsed_date.isoformat() != retrieved_at:
            raise ValueError("塔层快照日期必须为 YYYY-MM-DD")
        if not isinstance(source_sha256, str) or not cls._SHA256.fullmatch(source_sha256):
            raise ValueError("塔层快照来源哈希无效")
        if not isinstance(floors, dict) or not floors or len(floors) > cls.MAX_RECORDS:
            raise ValueError("塔层快照记录集无效")

        stage_ids = set()
        validated = {}
        for key, record in floors.items():
            match = cls._FLOOR_KEY.fullmatch(key) if isinstance(key, str) else None
            floor_text = match.group(2) if match is not None else ""
            if match is None or len(floor_text) > len(str(cls.MAX_FLOOR)) or int(floor_text) > cls.MAX_FLOOR:
                raise ValueError("塔层快照键无效")
            if not isinstance(record, dict):
                raise ValueError("塔层快照记录无效")
            stage_id = record.get("stage_id")
            battle_power = record.get("standard_battle_power")
            if type(stage_id) is not int or stage_id <= 0:
                raise ValueError("塔层 stage_id 无效")
            if type(battle_power) is not int or battle_power <= 0:
                raise ValueError("塔层标准战力无效")
            if stage_id in stage_ids:
                raise ValueError("塔层 stage_id 重复")
            stage_ids.add(stage_id)
            validated[key] = {"stage_id": stage_id, "standard_battle_power": battle_power}
        return source, retrieved_at, source_sha256, validated

    @classmethod
    def _tower_id(cls, tower: object) -> str | None:
        if not isinstance(tower, str):
            return None
        normalized = tower.strip().casefold()
        tower_id = cls.ALIASES.get(normalized, normalized)
        return tower_id if tower_id in cls.TOWERS else None

    @classmethod
    def _floor_number(cls, floor: object) -> int | None:
        if not isinstance(floor, str) or not floor.isascii() or not floor.isdigit() or not 1 <= len(floor) <= len(str(cls.MAX_FLOOR)):
            return None
        number = int(floor)
        if str(number) != floor or not 1 <= number <= cls.MAX_FLOOR:
            return None
        return number

    def describe(self, tower: str, floor: str):
        tower_id = self._tower_id(tower)
        floor_number = self._floor_number(floor)
        if tower_id is None or floor_number is None:
            return "用法：/妮姬 塔层 部落|极乐净土|米西利斯|泰特拉|朝圣者 <层数>"
        record = self.floors.get(f"{tower_id}:{floor_number}")
        if record is None:
            return "公开快照未收录该塔层，不推测关卡或战力。"
        return (f"【塔层静态速查】{tower_id} · {floor_number} 层\n"
                f"表内标准战力：{record['standard_battle_power']:,}\n"
                f"快照日期：{self.updated_at}\n这是关卡静态值，不是通关保证，也不代表你的进度。")

"""公开静态塔层速查；不估计玩家进度与通关能力。"""
import json
from pathlib import Path


class TowerRegistry:
    ALIASES = {"部落": "tribe", "综合": "tribe", "极乐净土": "elysion", "米西利斯": "missilis", "泰特拉": "tetra", "朝圣者": "pilgrim"}

    def __init__(self, path: Path):
        data = json.loads(path.read_text(encoding="utf-8"))
        self.floors = data["floors"]
        self.updated_at = data["retrieved_at"]

    def describe(self, tower: str, floor: str):
        tower = self.ALIASES.get(tower, tower.casefold())
        if tower not in {"tribe", "elysion", "missilis", "tetra", "pilgrim"} or not floor.isascii() or not floor.isdigit() or not 1 <= int(floor) <= 10000:
            return "用法：/妮姬 塔层 部落|极乐净土|米西利斯|泰特拉|朝圣者 <层数>"
        record = self.floors.get(f"{tower}:{int(floor)}")
        if record is None:
            return "公开快照未收录该塔层，不推测关卡或战力。"
        return (f"【塔层静态速查】{tower} · {int(floor)} 层\n"
                f"表内标准战力：{record['standard_battle_power']:,}\n"
                f"快照日期：{self.updated_at}\n这是关卡静态值，不是通关保证，也不代表你的进度。")

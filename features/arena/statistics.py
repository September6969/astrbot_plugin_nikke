"""授权历史快照的只读适配器，按完整对位保留样本口径。"""

import json
import math
from datetime import datetime, timezone
from pathlib import Path

from .models import MatchupEvidence, Provenance


def wilson_interval(wins: int, losses: int) -> tuple[float, float]:
    total = wins + losses
    if total <= 0:
        return 0.0, 1.0
    z = 1.959963984540054
    mean = wins / total
    denominator = 1 + z * z / total
    center = (mean + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(mean * (1 - mean) / total + z * z / (4 * total * total)) / denominator
    return center - radius, center + radius


class SnapshotStatisticsProvider:
    def __init__(self, path: Path):
        self.status = "unavailable"
        self.metadata = {}
        self.character_usage: dict[str, int] = {}
        self._records = {}
        try:
            if path.stat().st_size > 8 * 1024 * 1024:
                return
            payload = json.loads(path.read_text(encoding="utf-8"))
            required = {"source", "fetched_at", "game_patch", "server", "seasons", "sample_size",
                        "license", "mapping_coverage", "schema_version", "records", "matchup_direction"}
            if (not required <= set(payload) or payload["schema_version"] != 2
                    or payload["matchup_direction"] != "attacker_vs_defender"):
                return
            if payload["source"] != "https://nikkeari.cc" or not payload["license"]:
                return
            if (payload["server"] not in {"GLOBAL", "JP", "KR"}
                    or not isinstance(payload["game_patch"], str)
                    or not isinstance(payload["seasons"], list)
                    or not payload["seasons"]
                    or any(not isinstance(value, str) for value in payload["seasons"])
                    or type(payload["sample_size"]) is not int or payload["sample_size"] < 0):
                return
            if not isinstance(payload["records"], list) or len(payload["records"]) > 50000:
                return
            fetched = datetime.fromisoformat(payload["fetched_at"])
            if fetched.tzinfo is None:
                return
            self.status = "stale" if (datetime.now(timezone.utc) - fetched).days > 30 else "available"
            self.metadata = {key: value for key, value in payload.items() if key != "records"}
            for row in payload["records"]:
                if (not isinstance(row["mine"], list) or not isinstance(row["enemy"], list)
                        or len(row["mine"]) != 5 or len(row["enemy"]) != 5
                        or any(not isinstance(key, str) or not key or len(key) > 100
                               for key in row["mine"] + row["enemy"])
                        or type(row["wins"]) is not int or type(row["losses"]) is not int
                        or min(row["wins"], row["losses"]) < 0):
                    raise ValueError("统计记录格式无效。")
                key = (tuple(row["mine"]), tuple(row["enemy"]))
                if key in self._records:
                    raise ValueError("统计快照存在重复聚合。")
                self._records[key] = (row["wins"], row["losses"])
            if sum(sum(counts) for counts in self._records.values()) != payload["sample_size"]:
                raise ValueError("统计快照样本总数不一致。")
            usage = payload.get("character_usage", {})
            if (isinstance(usage, dict) and len(usage) <= 1000
                    and all(isinstance(key, str) and 0 < len(key) <= 100
                            and type(count) is int and count > 0 for key, count in usage.items())):
                self.character_usage = usage
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            self.status = "unavailable"
            self.metadata = {}
            self.character_usage = {}
            self._records = {}

    def matchup(self, mine, enemy) -> MatchupEvidence | None:
        if self.status == "unavailable":
            return None
        mine_keys, enemy_keys = mine.keys, enemy.keys
        record = self._records.get((mine_keys, enemy_keys))
        scope_text = "5/5 同站位"
        combinations = 1
        if not record or sum(record) == 0:
            record, scope_text, combinations = self._similar_matchup(mine_keys, enemy_keys)
        if not record or not sum(record):
            return None
        wins, losses = record
        lower, upper = wilson_interval(wins, losses)
        patch = self.metadata["game_patch"]
        scope = f'{self.metadata["server"]} / {",".join(self.metadata["seasons"])} / '
        scope += "补丁未知" if patch == "unknown" else patch
        text = (f"历史 {scope_text}进攻对位，{wins} 胜 {losses} 负，样本 {wins + losses}；"
                f"样本胜率的 95% 区间 {lower:.2f}–{upper:.2f}；{scope}。")
        if scope_text != "5/5 同站位":
            # 相似口径把差异位上不同角色的对局合并计数，不能读作本阵容的实测胜率。
            text += (f"样本口径：合并 {combinations} 组差异位角色不同的攻守组合，"
                     "不代表本阵容或本对手的实测胜率。")
        if self.status == "stale":
            text += "快照已超过 30 天。"
        text += "历史样本仅作参考，未用于当前排序。"
        return MatchupEvidence("statistic", text, Provenance(
            self.metadata["source"], patch, "reference",
            ("current_patch_comparability",) if patch == "unknown" else ()))

    def _similar_matchup(self, mine, enemy) -> tuple[tuple[int, int] | None, str, int]:
        # 同时按攻守双方相同角色且同站位的数量分层，只汇总最高一层。
        tier = 2
        wins = losses = combinations = 0
        mine_differences: set[int] = set()
        enemy_differences: set[int] = set()
        for (attacker, defender), (row_wins, row_losses) in self._records.items():
            if not row_wins + row_losses:
                continue
            enemy_changed = {index for index, (left, right) in enumerate(zip(enemy, defender), 1)
                             if left != right}
            if 5 - len(enemy_changed) < max(3, tier):
                continue
            mine_changed = {index for index, (left, right) in enumerate(zip(mine, attacker), 1)
                            if left != right}
            matched = 5 - max(len(mine_changed), len(enemy_changed))
            if matched < max(3, tier):
                continue
            if matched > tier:
                tier = matched
                wins = losses = combinations = 0
                mine_differences.clear()
                enemy_differences.clear()
            wins += row_wins
            losses += row_losses
            combinations += 1
            mine_differences.update(mine_changed)
            enemy_differences.update(enemy_changed)
        if tier < 3:
            return None, "", 0
        mine_slots = "、".join(f"P{index}" for index in sorted(mine_differences)) or "无"
        enemy_slots = "、".join(f"P{index}" for index in sorted(enemy_differences)) or "无"
        return ((wins, losses),
                f"{tier}/5 相似（各方至少 {tier} 个同站位，差异位 我方 {mine_slots}、对方 {enemy_slots}）",
                combinations)

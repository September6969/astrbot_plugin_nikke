"""组装只读竞技场应用，不创建网络同步任务。"""

import json
from pathlib import Path

from ...features.arena.analyzer import ArenaAnalyzer
from ...features.arena.application import ArenaApplication
from ...features.arena.identity import ArenaDirectory
from ...features.arena.models import Provenance
from ...features.arena.roster import ArenaRosterProvider
from ...features.arena.statistics import SnapshotStatisticsProvider
from ...features.character.registries.static import StaticDataRegistry


def create_arena_application(plugin_dir: Path, *, account_reader, gateway, identity, history_path=None):
    path = plugin_dir / "assets" / "data" / "arena" / "rules.json"
    rules = json.loads(path.read_text(encoding="utf-8"))
    directory = ArenaDirectory(plugin_dir / "assets" / "data" / "character_master.json", identity)
    directory.add_rules(rules)
    # 只信任带 SHA-256 清单的珍藏品 registry；校验失败时没有任何官方珍藏确认。
    directory.add_favorite_items(StaticDataRegistry(plugin_dir / "assets").mapping("favorite_item"))
    parameters = {key: {float(tier): value for tier, value in curve.items()}
                  for key, curve in rules["parameters"].items()}
    provenance = Provenance(rules["source"], rules["commit"], rules["confidence"],
                            tuple(rules["missing_fields"]))
    statistics = SnapshotStatisticsProvider(history_path) if history_path is not None else None
    analyzer = ArenaAnalyzer(directory, rules["templates"], parameters, provenance, statistics,
                             snapshot_date=rules["fetched_at"])
    roster = ArenaRosterProvider(account_reader, gateway, directory)
    return ArenaApplication(directory, analyzer, roster)

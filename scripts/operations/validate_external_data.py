# SPDX-License-Identifier: GPL-3.0-or-later
"""可选外部数据导入文件离线 Schema 校验器。

在导入运营者自行准备的数据前校验：
- ``sync_costs``: 同步器升级成本表
- ``solo_raid_seasons``: 单人突袭赛季与首领资料
- ``overload_recommendations``: 超限词条推荐表
- ``counsel_bank``: 带授权许可与来源的咨询题库
- ``wishlist_eligibility``: 愿望单普通招募准入表
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _root = Path(__file__).resolve().parents[2]
    if "astrbot_plugin_nikke" not in sys.modules:
        _spec = importlib.util.spec_from_file_location(
            "astrbot_plugin_nikke",
            _root / "__init__.py",
            submodule_search_locations=[str(_root)],
        )
        assert _spec and _spec.loader
        _pkg = importlib.util.module_from_spec(_spec)
        sys.modules["astrbot_plugin_nikke"] = _pkg
        _spec.loader.exec_module(_pkg)
    __package__ = "astrbot_plugin_nikke.scripts.operations"

from ...features.counsel.bank import CounselBank, CounselBankError
from ...features.overload_advice.advisor import (
    OverloadAdviceError,
    load_character_targets,
    load_default_line_counts,
    load_recommendations,
)
from ...features.solo_raid.seasons import SeasonCatalog, SoloRaidDataError
from ...features.sync.cost_table import SyncCostTable, SyncCostTableError
from ...features.wishlist.advisor import WishlistError, load_pool_eligibility

DATA_KINDS = (
    "sync_costs",
    "solo_raid_seasons",
    "overload_recommendations",
    "counsel_bank",
    "wishlist_eligibility",
)


class ExternalDataValidationError(ValueError):
    """待导入文件不符合对应数据契约。"""


def validate_external_file(kind: str, path: str | Path) -> dict[str, Any]:
    """校验外部 JSON 文件并返回结构化摘要；不合法时抛出 ExternalDataValidationError。"""
    target = Path(path)
    if kind not in DATA_KINDS:
        raise ExternalDataValidationError(
            f"未知数据类型：{kind}（可用：{', '.join(DATA_KINDS)}）"
        )
    if not target.is_file():
        raise ExternalDataValidationError(f"文件不存在：{target}")

    if kind == "sync_costs":
        try:
            table = SyncCostTable.from_file(target)
        except SyncCostTableError as exc:
            raise ExternalDataValidationError(str(exc)) from exc
        levels = table.levels
        return {
            "kind": kind,
            "path": str(target),
            "records": len(levels),
            "min_level": levels[0] if levels else None,
            "max_level": levels[-1] if levels else None,
            "checked_at": table.checked_at,
        }

    if kind == "overload_recommendations":
        try:
            recommendations = load_recommendations(target)
            targets = load_character_targets(target)
            defaults = load_default_line_counts(target)
        except OverloadAdviceError as exc:
            raise ExternalDataValidationError(str(exc)) from exc
        return {
            "kind": kind,
            "path": str(target),
            "recommendation_groups": len(recommendations),
            "character_targets": len(targets),
            "default_line_targets": len(defaults),
        }

    if kind == "wishlist_eligibility":
        try:
            entries = load_pool_eligibility(target)
        except WishlistError as exc:
            raise ExternalDataValidationError(str(exc)) from exc
        return {
            "kind": kind,
            "path": str(target),
            "entries": len(entries),
        }

    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExternalDataValidationError(f"无法解析 UTF-8 JSON：{target.name}") from exc

    if kind == "solo_raid_seasons":
        try:
            catalog = SeasonCatalog.from_payload(payload)
        except SoloRaidDataError as exc:
            raise ExternalDataValidationError(str(exc)) from exc
        if not catalog.seasons:
            raise ExternalDataValidationError("seasons 不能为空")
        return {
            "kind": kind,
            "path": str(target),
            "seasons": len(catalog.seasons),
            "bosses": sum(len(season.bosses) for season in catalog.seasons),
        }

    try:
        bank = CounselBank.from_payload(payload)
    except CounselBankError as exc:
        raise ExternalDataValidationError(str(exc)) from exc
    return {
        "kind": kind,
        "path": str(target),
        "entries": len(bank.entries),
        "license": bank.license_note,
        "checked_at": bank.checked_at,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验可选外部 NIKKE 数据导入文件 Schema。")
    parser.add_argument("kind", choices=DATA_KINDS, help="数据类型")
    parser.add_argument("path", type=Path, help="待校验的 JSON 文件路径")
    args = parser.parse_args(argv)
    try:
        summary = validate_external_file(args.kind, args.path)
    except ExternalDataValidationError as exc:
        print(f"校验失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

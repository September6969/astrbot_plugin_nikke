# SPDX-License-Identifier: GPL-3.0-or-later
"""可选外部数据校验脚本与仓库准入表契约测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from astrbot_plugin_nikke.scripts.operations.validate_external_data import (
    ExternalDataValidationError,
    main as validator_main,
    validate_external_file,
)

SOURCE = "https://example.invalid/source.json"


def test_validate_all_five_external_schemas_and_reject_invalid(tmp_path: Path, capsys) -> None:
    root = Path(__file__).resolve().parents[1]
    real_summary = validate_external_file(
        "wishlist_eligibility", root / "assets" / "data" / "wishlist_pool_eligibility.json"
    )
    assert real_summary["entries"] >= 170

    sync_path = tmp_path / "sync.json"
    sync_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_url": SOURCE,
                "checked_at": "2026-11-24",
                "levels": [
                    {"level": 200, "core_dust": 1000, "credits": 2000, "battle_data": 300},
                    {"level": 201, "core_dust": 1100, "credits": 2200, "battle_data": 330},
                ],
            }
        ),
        encoding="utf-8",
    )
    assert validate_external_file("sync_costs", sync_path)["records"] == 2

    seasons_path = tmp_path / "seasons.json"
    seasons_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "seasons": [
                    {
                        "id": "s45",
                        "name": "第45赛季",
                        "source_url": SOURCE,
                        "checked_at": "2026-11-24",
                        "bosses": [{"id": "b1", "name": "boss", "weakness": "风压", "element": "Wind"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert validate_external_file("solo_raid_seasons", seasons_path)["bosses"] == 1

    ol_path = tmp_path / "overload.json"
    ol_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_url": SOURCE,
                "checked_at": "2026-11-24",
                "recommendations": {"__default__": ["攻击力增加"]},
                "characters": {"拉毗": {"targets": ["攻击力增加"], "min_lines": 2}},
            }
        ),
        encoding="utf-8",
    )
    assert validate_external_file("overload_recommendations", ol_path)["character_targets"] == 1

    counsel_path = tmp_path / "counsel.json"
    counsel_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_url": SOURCE,
                "license": "CC-BY-4.0",
                "checked_at": "2026-11-24",
                "entries": [
                    {
                        "id": "q1",
                        "nikke": "拉毗",
                        "question": "如何指挥？",
                        "keywords": ["指挥"],
                        "options": [{"id": "a", "label": "稳步推进"}, {"id": "b", "label": "冒进"}],
                        "answer_id": "a",
                        "source_url": SOURCE,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert validate_external_file("counsel_bank", counsel_path)["license"] == "CC-BY-4.0"
    assert validator_main(["counsel_bank", str(counsel_path)]) == 0
    assert "CC-BY-4.0" in capsys.readouterr().out

    # 缺少许可字段或无效 schema 必须拒绝。
    bad_counsel = tmp_path / "bad_counsel.json"
    bad_counsel.write_text(json.dumps({"schema_version": 1, "entries": []}), encoding="utf-8")
    with pytest.raises(ExternalDataValidationError):
        validate_external_file("counsel_bank", bad_counsel)
    assert validator_main(["counsel_bank", str(bad_counsel)]) == 1

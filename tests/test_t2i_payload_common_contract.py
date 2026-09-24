"""共享 T2I payload helper 的身份、格式及兼容边界合同。"""

from __future__ import annotations

import ast
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from astrbot_plugin_nikke.ui.payloads.common import (
    boss_presentation,
    display_number,
    display_remaining,
    format_compact_number,
)
ROOT = Path(__file__).resolve().parents[1]


def test_legacy_shared_helper_module_is_removed_after_consumer_migration():
    assert not (ROOT / "ui" / "t2i_payloads.py").exists()
    assert importlib.util.find_spec("astrbot_plugin_nikke.ui.t2i_payloads") is None


def test_common_display_formatters_keep_missing_and_compact_semantics():
    assert display_number(None) == "Unknown"
    assert display_number(1286600) == "1,286,600"
    assert format_compact_number(0) == "0"
    assert format_compact_number(12345) == "12.3K"
    assert format_compact_number(None) == "Unknown"
    assert format_compact_number("invalid") == "invalid"


def test_remaining_formatter_requires_timezone_and_never_guesses_naive_time():
    now = datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc)
    assert display_remaining("2026-09-23T01:01:00+00:00", now) == "1小时 1分钟"
    assert display_remaining("2026-09-22T23:59:00+00:00", now) == "已结束"
    assert display_remaining("2026-09-23T01:00:00", now) == "Unknown"
    assert display_remaining("not-a-date", now) == "Unknown"


def test_boss_presentation_preserves_unresolved_fallback_and_local_identity():
    asset = SimpleNamespace(
        is_fallback=False,
        local_path=Path("synthetic-boss.png"),
        boss_name="synthetic boss",
    )
    assets = SimpleNamespace(resolve_boss_asset=lambda **_kwargs: asset)
    resolver = SimpleNamespace(encode=lambda path, _size: f"local:{path}")

    resolved = boss_presentation(
        assets,
        resolver,
        10,
        icon_id=20,
        monster_model_id=30,
        name="fixture name",
    )
    assert resolved == {
        "name": "synthetic boss",
        "boss_image_data_uri": "local:synthetic-boss.png",
        "asset_state": "resolved",
        "is_fallback": False,
    }
    unresolved = boss_presentation(None, resolver, 999)
    assert unresolved == {
        "name": "Boss ID 999",
        "boss_image_data_uri": None,
        "asset_state": "UNRESOLVED",
        "is_fallback": True,
    }


def test_payload_and_renderer_modules_do_not_import_legacy_helper_module():
    legacy_imports = []
    for package_dir in (ROOT / "scripts", ROOT / "ui", ROOT / "tests"):
        for path in package_dir.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "").endswith(
                    "t2i_payloads"
                ):
                    legacy_imports.append(path.relative_to(ROOT).as_posix())
    assert legacy_imports == []


if __name__ == "__main__":
    import unittest

    unittest.main()

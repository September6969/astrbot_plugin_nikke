# SPDX-License-Identifier: GPL-3.0-or-later
"""统一功能目录（Phase 3）契约测试。"""

from __future__ import annotations

from astrbot_plugin_nikke.features.catalog import (
    CATEGORIES,
    FEATURES,
    all_features,
    filter_features,
    get_feature,
    public_catalog_payload,
    workspace_catalog_payload,
)


def test_unified_catalog_contains_dual_portals_and_core_features() -> None:
    ids = {entry.id for entry in all_features()}
    assert {"portal.hall", "portal.workspace", "calendar.schedule", "tarot.draw"} <= ids
    assert {"account.bind", "profile.me", "solo_raid.planner", "arena.solver"} <= ids
    category_names = {c.name for c in CATEGORIES}
    for entry in FEATURES:
        assert entry.category in category_names, entry.id
        assert entry.example_command.startswith("/妮姬 ")
    assert get_feature("portal.hall") is not None


def test_public_catalog_excludes_personal_and_admin_features() -> None:
    payload = public_catalog_payload({"enable_arena": False, "enable_daily_actions": False})
    assert payload["surface"] == "hall"
    ids = {item["id"] for item in payload["features"]}
    assert "portal.hall" in ids
    assert "calendar.schedule" in ids
    assert "tarot.draw" in ids
    assert "portal.workspace" not in ids
    assert "account.bind" not in ids
    assert "profile.me" not in ids
    assert "admin.ops" not in ids
    assert all(not item["requires_binding"] and not item["admin_only"] for item in payload["features"])


def test_workspace_catalog_respects_feature_flags_and_admin() -> None:
    off_payload = workspace_catalog_payload({"enable_arena": False, "enable_daily_actions": False})
    by_id_off = {item["id"]: item for item in off_payload["features"]}
    assert by_id_off["arena.solver"]["enabled"] is False
    assert by_id_off["daily.routine"]["enabled"] is False
    assert "admin.ops" not in by_id_off

    on_payload = workspace_catalog_payload(
        {"enable_arena": True, "enable_daily_actions": True},
        include_admin=True,
    )
    by_id_on = {item["id"]: item for item in on_payload["features"]}
    assert by_id_on["arena.solver"]["enabled"] is True
    assert by_id_on["daily.routine"]["enabled"] is True
    assert "admin.ops" in by_id_on
    assert len(filter_features(surface="hall")) < len(all_features())

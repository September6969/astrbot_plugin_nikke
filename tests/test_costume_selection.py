# SPDX-License-Identifier: GPL-3.0-or-later
"""Truth-table unit tests for costume selection precedence and semantics."""

import pytest
from astrbot_plugin_nikke.card_builder import resolve_equipped_costume


def test_costume_selection_precedence():
    # Precedence: detail.costume_tid > detail.costume_id > roster.costume_tid > roster.costume_id
    detail = {"costume_tid": 30049, "costume_id": 30001}
    roster = {"costume_tid": 30002, "costume_id": 30003}
    sel = resolve_equipped_costume(95, roster, detail)
    assert sel.costume_id == 30049
    assert sel.source == "detail.costume_tid"
    assert sel.kind == "alternate"

    # Fall back to detail.costume_id if costume_tid is None
    detail = {"costume_tid": None, "costume_id": 30001}
    roster = {"costume_tid": 30002, "costume_id": 30003}
    sel = resolve_equipped_costume(95, roster, detail)
    assert sel.costume_id == 30001
    assert sel.source == "detail.costume_id"
    assert sel.kind == "alternate"

    # Fall back to roster.costume_tid if detail has neither
    detail = {"costume_tid": None, "costume_id": None}
    roster = {"costume_tid": 30002, "costume_id": 30003}
    sel = resolve_equipped_costume(95, roster, detail)
    assert sel.costume_id == 30002
    assert sel.source == "roster.costume_tid"
    assert sel.kind == "alternate"

    # Fall back to roster.costume_id
    detail = {}
    roster = {"costume_id": 30003}
    sel = resolve_equipped_costume(95, roster, detail)
    assert sel.costume_id == 30003
    assert sel.source == "roster.costume_id"
    assert sel.kind == "alternate"


def test_costume_selection_default_indicators():
    # 0, "0", "default" in high priority suppresses lower priority alternate
    for default_val in (0, "0", "default"):
        detail = {"costume_tid": default_val}
        roster = {"costume_id": 30049}
        sel = resolve_equipped_costume(95, roster, detail)
        assert sel.costume_id == 0
        assert sel.source == "detail.costume_tid"
        assert sel.kind == "default"


def test_costume_selection_none_empty_and_bool():
    # None, empty string, and bool should be skipped and let lower priority take over
    for empty_val in (None, "", True, False):
        detail = {"costume_tid": empty_val, "costume_id": 30049}
        sel = resolve_equipped_costume(95, {}, detail)
        assert sel.costume_id == 30049
        assert sel.source == "detail.costume_id"
        assert sel.kind == "alternate"


def test_costume_selection_negative_and_invalid():
    # Negative number should be marked unknown, not alternate
    sel = resolve_equipped_costume(95, {}, {"costume_tid": -1})
    assert sel.costume_id == -1
    assert sel.kind == "unknown"

    # Non-numeric string should be marked unknown
    sel = resolve_equipped_costume(95, {}, {"costume_tid": "invalid_skin_id"})
    assert sel.costume_id == "invalid_skin_id"
    assert sel.kind == "unknown"


def test_costume_selection_numeric_string():
    # String representation of positive integer
    sel = resolve_equipped_costume(95, {}, {"costume_tid": "30049"})
    assert sel.costume_id == 30049
    assert sel.kind == "alternate"


def test_costume_selection_all_none():
    sel = resolve_equipped_costume(95, None, None)
    assert sel.costume_id == 0
    assert sel.source == "default"
    assert sel.kind == "default"

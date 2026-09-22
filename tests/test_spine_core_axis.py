import json
from pathlib import Path

from astrbot_plugin_nikke.features.character.spine_core_axis import (
    select_breast_anchor,
    select_head_top,
    select_upper_torso_anchor,
    validate_axis_order,
)


def bone(name, x, y, parent="torso"):
    return {"name": name, "x": x, "y": y, "parent": parent}


def test_breast_pair_requires_same_parent():
    selected, reason = select_breast_anchor([
        bone("breast_l", 40, 100, "chest"),
        bone("breast_r", 60, 100, "chest"),
    ])
    assert reason == "ok"
    assert selected.point == (50.0, 100.0)

    rejected, reason = select_breast_anchor([
        bone("breast_l", 40, 100, "left_ctrl"),
        bone("breast_r", 60, 100, "right_ctrl"),
    ])
    assert rejected is None
    assert reason == "breast_unavailable"


def test_auxiliary_bones_do_not_change_exact_selection():
    selected, reason = select_breast_anchor([
        bone("chest", 50, 110),
        bone("breast_ctrl", 999, 999),
        bone("breast_helper", -999, -999),
    ])
    assert reason == "ok"
    assert selected.point == (50.0, 110.0)


def test_ambiguous_single_role_is_rejected():
    selected, reason = select_breast_anchor([
        bone("breast", 45, 100),
        bone("bust", 55, 100),
    ])
    assert selected is None
    assert reason == "ambiguous_breast_single"


def test_head_surface_requires_unique_candidate():
    selected, reason = select_head_top([
        {"name": "head/head", "kind": "head_attachment", "box": [10, 20, 80, 100]},
    ])
    assert reason == "ok"
    assert selected.y == 20.0

    ambiguous, reason = select_head_top([
        {"name": "head/a", "kind": "head_attachment", "box": [10, 20, 80, 100]},
        {"name": "head/b", "kind": "head_attachment", "box": [12, 18, 82, 102]},
    ])
    assert ambiguous is None
    assert reason == "ambiguous_head_attachment"


def test_face_surface_is_fallback_and_axis_order_is_strict():
    selected, reason = select_head_top([
        {"name": "face/main", "kind": "face_attachment", "box": [10, 30, 80, 100]},
    ])
    assert reason == "ok"
    assert selected.y == 30.0
    assert validate_axis_order(head_top_y=20, eye_y=40, breast_y=100)
    assert not validate_axis_order(head_top_y=50, eye_y=40, breast_y=100)


def test_upper_torso_manual_override_has_highest_priority_and_confidence():
    selected, reason = select_upper_torso_anchor(
        [
            bone("body", 50, 120),
            bone("chest", 50, 110),
            bone("upper_l", 40, 100, "body"),
            bone("upper_r", 60, 100, "body"),
        ],
        manual_override={
            "kind": "bone_pair",
            "bones": ["upper_l", "upper_r"],
            "parent": "body",
            "confidence": 0.99,
        },
        existing_override={"bone": "body"},
        semantic_entry={"upper_torso": {"bone": "chest", "confidence": 0.8}},
    )

    assert reason == "ok"
    assert selected is not None
    assert selected.point == (50.0, 100.0)
    assert selected.source == "manual:upper_l+upper_r"
    assert selected.confidence == 0.99


def test_upper_torso_existing_override_rejects_wrong_parent_without_guessing():
    selected, reason = select_upper_torso_anchor(
        [
            bone("body", 50, 120, "root"),
            bone("body", 50, 120, "other"),
        ],
        existing_override={"bone": "body", "parent": "root"},
    )

    assert selected is None
    assert reason == "existing_override_unavailable"


def test_upper_torso_uses_registry_then_verified_attachment_mapping():
    registry_selected, reason = select_upper_torso_anchor(
        [bone("body", 50, 120)],
        semantic_entry={
            "upper_torso": {
                "bone": "body",
                "confidence": 0.88,
                "source": "verified-registry",
            }
        },
    )
    assert reason == "ok"
    assert registry_selected is not None
    assert registry_selected.source == "semantic:body"
    assert registry_selected.confidence == 0.88

    attachment_selected, reason = select_upper_torso_anchor(
        [],
        attachment_candidates=[
            {
                "slot": "torso_surface",
                "attachment": "torso_surface",
                "bone": "move3",
                "parent": "move2",
                "point": [50, 140],
                "verified": True,
            }
        ],
        verified_attachment_mapping={
            "kind": "attachment",
            "slot": "torso_surface",
            "attachment": "torso_surface",
            "bone": "move3",
            "parent": "move2",
            "confidence": 0.84,
            "verified": True,
        },
    )
    assert reason == "ok"
    assert attachment_selected is not None
    assert attachment_selected.point == (50.0, 140.0)
    assert attachment_selected.source == "verified-attachment:torso_surface/torso_surface"
    assert attachment_selected.confidence == 0.84


def test_upper_torso_supports_attachment_pairs_and_surface_specs():
    candidates = [
        {
            "slot": "torso_l",
            "attachment": "torso_l",
            "bone": "chest_l",
            "parent": "body",
            "point": [40, 100],
            "surface": "upper_torso",
        },
        {
            "slot": "torso_r",
            "attachment": "torso_r",
            "bone": "chest_r",
            "parent": "body",
            "point": [60, 100],
            "surface": "upper_torso",
        },
    ]
    pair, reason = select_upper_torso_anchor(
        [],
        attachment_candidates=candidates,
        manual_override={
            "kind": "attachment_pair",
            "attachments": [
                {"slot": "torso_l", "attachment": "torso_l"},
                {"slot": "torso_r", "attachment": "torso_r"},
            ],
            "parent": "body",
        },
    )
    assert reason == "ok"
    assert pair is not None
    assert pair.point == (50.0, 100.0)

    surface, reason = select_upper_torso_anchor(
        [],
        attachment_candidates=[candidates[0]],
        manual_override={
            "kind": "surface",
            "slot": "torso_l",
            "attachment": "torso_l",
            "surface": "upper_torso",
        },
    )
    assert reason == "ok"
    assert surface is not None
    assert surface.source == "manual:torso_l/torso_l"


def test_upper_torso_rejects_ambiguous_candidates_and_op_like_names():
    ambiguous, reason = select_upper_torso_anchor(
        [
            bone("torso_l", 40, 100, "body"),
            bone("torso_l", 42, 100, "body"),
            bone("torso_r", 60, 100, "body"),
        ]
    )
    assert ambiguous is None
    assert reason == "ambiguous_upper_torso_pairs"

    guessed, reason = select_upper_torso_anchor(
        [bone("op1", 50, 100), bone("op2", 50, 100)]
    )
    assert guessed is None
    assert reason == "upper_torso_unavailable"


def test_c401_and_c581_verified_fixture_selection():
    fixture = json.loads(
        (
            Path(__file__).parent
            / "fixtures"
            / "spine_semantics"
            / "c401_c581_idle_t0.json"
        ).read_text(encoding="utf-8")
    )
    mappings = json.loads(
        (
            Path(__file__).parents[1]
            / "assets"
            / "mappings"
            / "spine_bone_semantics.json"
        ).read_text(encoding="utf-8")
    )["entries"]
    overrides = json.loads(
        (
            Path(__file__).parents[1]
            / "assets"
            / "mappings"
            / "spine_bone_overrides.json"
        ).read_text(encoding="utf-8")
    )["entries"]

    c401, reason = select_upper_torso_anchor(
        fixture["c401"]["anatomy_bones_1024"],
        existing_override=overrides["401:default"]["upper_torso"],
        attachment_candidates=fixture["c401"]["attachment_candidates_1024"],
    )
    assert reason == "ok"
    assert c401 is not None
    assert c401.source == "override:body_total/body_total"

    c581, reason = select_upper_torso_anchor(
        fixture["c581"]["anatomy_bones_1024"],
        semantic_entry=mappings["581:default"],
        attachment_candidates=fixture["c581"]["attachment_candidates_1024"],
    )
    assert reason == "ok"
    assert c581 is not None
    assert c581.source == "semantic:chest_l+chest_r"

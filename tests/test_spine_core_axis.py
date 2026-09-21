from astrbot_plugin_nikke.features.character.spine_core_axis import (
    select_breast_anchor,
    select_head_top,
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

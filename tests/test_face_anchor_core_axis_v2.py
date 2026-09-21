import hashlib
from unittest.mock import patch

from PIL import Image

from astrbot_plugin_nikke.features.character.face_anchor import framing
from astrbot_plugin_nikke.features.character.layout import MIN_AUTO_SCALE_RATIO, summary_layout
from astrbot_plugin_nikke.features.character.models import CostumeSelection
from astrbot_plugin_nikke.tests.test_character_replica import example_card


def make_card():
    card = example_card()
    card.resource_id = "471"
    card.costume_id = 0
    card.costume_selection = CostumeSelection(0, "test", "default")
    return card


def make_row(image, *, point, extent, head_top_y=None, breast=None, target=(860, 380)):
    row = {
        "pixel_sha256": hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest(),
        "image_size": list(image.size),
        "point": list(point),
        "extent": list(extent),
        "anchor_kind": "eye_attachment",
        "framing": {"target": list(target), "extent_width": 160},
    }
    if head_top_y is not None and breast is not None:
        row["core_axis"] = {
            "eye_point": list(point),
            "head_top_y": head_top_y,
            "breast_point": list(breast),
            "head_top_source": "test-head",
            "breast_source": "test-breast",
        }
    return row


def test_unknown_summary_count_does_not_change_existing_transform():
    card = make_card()
    image = Image.new("RGBA", (100, 200), "white")
    row = make_row(image, point=(50, 30), extent=(40, 20), head_top_y=5, breast=(50, 100))
    with patch("astrbot_plugin_nikke.features.character.face_anchor.metadata", return_value={"c471": row}):
        unknown = framing(card, image, body_centering=False)
        explicit_zero = framing(card, image, body_centering=False, summary_count=0)

    assert unknown["core_axis"]["reason"] == "summary_count_unknown"
    assert unknown["core_axis"]["summary_count"] is None
    assert unknown["style"] != explicit_zero["style"]


def test_explicit_summary_count_keeps_full_axis_in_safe_corridor():
    card = make_card()
    image = Image.new("RGBA", (100, 200), "white")
    row = make_row(image, point=(50, 30), extent=(40, 20), head_top_y=5, breast=(50, 100))
    with patch("astrbot_plugin_nikke.features.character.face_anchor.metadata", return_value={"c471": row}):
        for count in range(5):
            result = framing(card, image, body_centering=False, summary_count=count)
            diag = result["core_axis"]
            layout = summary_layout(count)
            assert diag["available"] is True
            assert diag["head_top_card_after"] >= layout.safe_top - 1e-6
            assert diag["eye_card_after"] >= diag["head_top_card_after"]
            assert diag["breast_card_after"] <= layout.safe_bottom + 1e-6
            assert diag["scale_after"] == diag["scale_before"]


def test_missing_core_axis_preserves_face_anchor_transform():
    card = make_card()
    image = Image.new("RGBA", (100, 200), "white")
    row = make_row(image, point=(50, 30), extent=(40, 20))
    with patch("astrbot_plugin_nikke.features.character.face_anchor.metadata", return_value={"c471": row}):
        old_path = framing(card, image, body_centering=False)
        explicit = framing(card, image, body_centering=False, summary_count=4)

    assert explicit["style"] == old_path["style"]
    assert explicit["core_axis"]["available"] is False
    assert explicit["core_axis"]["reason"] == "core_axis_unavailable"


def test_fit_within_six_percent_rescales_and_satisfies_both_boundaries():
    card = make_card()
    image = Image.new("RGBA", (100, 300), "white")
    row = make_row(
        image,
        point=(50, 80),
        extent=(40, 20),
        head_top_y=20,
        breast=(50, 270),
        target=(860, 500),
    )
    with patch("astrbot_plugin_nikke.features.character.face_anchor.metadata", return_value={"c471": row}):
        result = framing(card, image, body_centering=False, summary_count=4)

    diag = result["core_axis"]
    assert diag["scaled_for_fit"] is True
    assert diag["scale_after"] < diag["scale_before"]
    assert diag["scale_after"] >= diag["scale_before"] * MIN_AUTO_SCALE_RATIO
    assert diag["head_top_card_after"] >= diag["safe_top"] - 1e-6
    assert diag["breast_card_after"] <= diag["safe_bottom"] + 1e-6


def test_stale_axis_eye_is_rejected_without_moving_card():
    card = make_card()
    image = Image.new("RGBA", (100, 200), "white")
    row = make_row(image, point=(50, 30), extent=(40, 20), head_top_y=5, breast=(50, 100))
    row["core_axis"]["eye_point"] = [51, 30]
    with patch("astrbot_plugin_nikke.features.character.face_anchor.metadata", return_value={"c471": row}):
        prior = framing(card, image, body_centering=False)
        result = framing(card, image, body_centering=False, summary_count=4)

    assert result["style"] == prior["style"]
    assert result["core_axis"]["reason"] == "axis_eye_mismatch"


def test_new_torso_metadata_is_consumed_without_legacy_breast_field():
    card = make_card()
    image = Image.new("RGBA", (100, 200), "white")
    row = make_row(image, point=(50, 30), extent=(40, 20))
    row["core_axis"] = {
        "eye_point": [50, 30],
        "head_top_y": 5,
        "torso_point": [50, 100],
        "torso_source": "verified-test",
        "torso_confidence": 0.91,
        "head_top_source": "test-head",
    }
    with patch("astrbot_plugin_nikke.features.character.face_anchor.metadata", return_value={"c471": row}):
        result = framing(card, image, body_centering=False, summary_count=4)

    assert result["core_axis"]["torso_source"] == "verified-test"
    assert result["core_axis"]["torso_confidence"] == 0.91
    assert result["core_axis"]["torso_card_after"] <= result["core_axis"]["safe_bottom"]

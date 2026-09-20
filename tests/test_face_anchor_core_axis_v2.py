import hashlib
import re
from unittest.mock import patch

from PIL import Image

from astrbot_plugin_nikke.card_models import CostumeSelection
from astrbot_plugin_nikke.character_card_layout import MIN_AUTO_SCALE_RATIO, summary_layout
from astrbot_plugin_nikke.face_anchor import framing
from astrbot_plugin_nikke.face_guided_centering import DEFAULT_CENTERING_CONFIG
from astrbot_plugin_nikke.tests.test_character_replica import example_card


def parse_style(style):
    return {
        key: float(re.search(rf"{key}:([-\d.]+)px", style).group(1))
        for key in ("width", "height", "left", "top")
    }


def make_card():
    card = example_card()
    card.resource_id, card.costume_id = "471", 0
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


def test_vertical_body_centering_remains_disabled():
    assert DEFAULT_CENTERING_CONFIG.vertical_gain == 0.0


def test_summary_count_is_explicit_and_unknown_does_not_expand_corridor():
    card = make_card()
    image = Image.new("RGBA", (100, 200), "white")
    row = make_row(
        image,
        point=(50, 30),
        extent=(40, 20),
        head_top_y=5,
        breast=(50, 100),
    )
    with patch("astrbot_plugin_nikke.face_anchor.metadata", return_value={"c471": row}):
        unknown = framing(card, image, body_centering=False)
        explicit_zero = framing(card, image, body_centering=False, summary_count=0)

    assert unknown["core_axis"]["reason"] == "summary_count_unknown"
    assert unknown["core_axis"]["summary_count"] is None
    # Explicit 0 may apply the safe clamp; unknown must preserve the prior transform.
    assert unknown["style"] != explicit_zero["style"]


def test_full_head_eye_breast_axis_is_inside_safe_corridor_for_0_to_4_rows():
    card = make_card()
    image = Image.new("RGBA", (100, 200), "white")
    row = make_row(
        image,
        point=(50, 30),
        extent=(40, 20),
        head_top_y=5,
        breast=(50, 100),
    )

    with patch("astrbot_plugin_nikke.face_anchor.metadata", return_value={"c471": row}):
        for count in range(5):
            result = framing(card, image, body_centering=False, summary_count=count)
            diag = result["core_axis"]
            layout = summary_layout(count)
            assert diag["available"] is True
            assert diag["head_top_card_after"] >= layout.safe_top - 1e-6
            assert diag["eye_card_after"] >= diag["head_top_card_after"]
            assert diag["breast_card_after"] <= layout.safe_bottom + 1e-6
            assert diag["scale_after"] == diag["scale_before"]


def test_missing_core_axis_preserves_existing_face_anchor_behavior():
    card = make_card()
    image = Image.new("RGBA", (100, 200), "white")
    row = make_row(image, point=(50, 30), extent=(40, 20))
    with patch("astrbot_plugin_nikke.face_anchor.metadata", return_value={"c471": row}):
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
    with patch("astrbot_plugin_nikke.face_anchor.metadata", return_value={"c471": row}):
        result = framing(card, image, body_centering=False, summary_count=4)

    diag = result["core_axis"]
    assert diag["scaled_for_fit"] is True
    assert diag["scale_after"] < diag["scale_before"]
    assert diag["scale_after"] >= diag["scale_before"] * MIN_AUTO_SCALE_RATIO
    assert diag["head_top_card_after"] >= diag["safe_top"] - 1e-6
    assert diag["breast_card_after"] <= diag["safe_bottom"] + 1e-6


def test_over_six_percent_no_solution_preserves_previous_transform():
    card = make_card()
    image = Image.new("RGBA", (100, 320), "white")
    row = make_row(
        image,
        point=(50, 80),
        extent=(40, 20),
        head_top_y=0,
        breast=(50, 300),
        target=(860, 500),
    )
    with patch("astrbot_plugin_nikke.face_anchor.metadata", return_value={"c471": row}):
        prior = framing(card, image, body_centering=False)
        limited = framing(card, image, body_centering=False, summary_count=4)

    assert limited["core_axis"]["reason"] == "scale_limited"
    assert limited["core_axis"]["scaled_for_fit"] is False
    assert limited["style"] == prior["style"]


def test_stale_axis_eye_is_rejected_and_does_not_move_card():
    card = make_card()
    image = Image.new("RGBA", (100, 200), "white")
    row = make_row(
        image,
        point=(50, 30),
        extent=(40, 20),
        head_top_y=5,
        breast=(50, 100),
    )
    row["core_axis"]["eye_point"] = [51, 30]
    with patch("astrbot_plugin_nikke.face_anchor.metadata", return_value={"c471": row}):
        prior = framing(card, image, body_centering=False)
        result = framing(card, image, body_centering=False, summary_count=4)

    assert result["style"] == prior["style"]
    assert result["core_axis"]["reason"] == "axis_eye_mismatch"

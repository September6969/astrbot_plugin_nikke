import hashlib
import json
import math
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from astrbot_plugin_nikke.features.character.face_anchor import (
    FACE_Y_OFFSET_OVERRIDES,
    framing as _framing,
)
from astrbot_plugin_nikke.integrations.nikke_db.provider import NikkeDbProvider
from astrbot_plugin_nikke.features.character.layout import MIN_AUTO_SCALE_RATIO, summary_layout
from astrbot_plugin_nikke.features.character.models import CostumeSelection
from astrbot_plugin_nikke.tests.test_character_replica import example_card


ROOT = Path(__file__).resolve().parents[1]
_IDENTITY = NikkeDbProvider(ROOT / "assets", ROOT / "assets", remote=False)


def framing(data, portrait, **kwargs):
    return _framing(data, portrait, identity_resolver=_IDENTITY, **kwargs)


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


def test_unknown_summary_count_disables_core_corridor_but_keeps_face_safety():
    card = make_card()
    image = Image.new("RGBA", (100, 200), "white")
    row = make_row(image, point=(50, 30), extent=(40, 20), head_top_y=5, breast=(50, 100))
    with patch("astrbot_plugin_nikke.features.character.face_anchor.metadata", return_value={"c471": row}):
        unknown = framing(card, image, body_centering=False)
        explicit_zero = framing(card, image, body_centering=False, summary_count=0)

    assert unknown["core_axis"]["reason"] == "summary_count_unknown"
    assert unknown["core_axis"]["summary_count"] is None
    assert explicit_zero["core_axis"]["summary_count"] == 0
    assert unknown["guard_top_card_after"] >= 393.0
    assert explicit_zero["guard_top_card_after"] >= 393.0


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
            assert result["vertical_guard_source"] == "core_head_top"
            assert result["guard_top_card_after"] >= result["safe_top"] - 1.0
            assert diag["combined_min_top"] == max(
                diag["min_top"],
                result["safe_top"] - result["guard_top_source_y"] * diag["scale_after"],
            )


def test_missing_core_axis_uses_face_guard_without_core_interval():
    card = make_card()
    image = Image.new("RGBA", (100, 200), "white")
    row = make_row(image, point=(50, 30), extent=(40, 20))
    with patch("astrbot_plugin_nikke.features.character.face_anchor.metadata", return_value={"c471": row}):
        old_path = framing(card, image, body_centering=False)
        explicit = framing(card, image, body_centering=False, summary_count=4)

    assert explicit["style"] == old_path["style"]
    assert explicit["core_axis"]["available"] is False
    assert explicit["core_axis"]["reason"] == "core_axis_unavailable"
    assert explicit["vertical_guard_source"] == "face_local_alpha"
    assert explicit["guard_top_card_after"] >= explicit["safe_top"] - 1.0


def test_face_anchor_without_core_axis_keeps_head_below_identity_panel():
    from PIL import ImageDraw

    card = make_card()
    image = Image.new("RGBA", (100, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((34, 0, 66, 43), fill=(255, 255, 255, 255))
    draw.rectangle((28, 32, 72, 190), fill=(255, 255, 255, 255))
    row = make_row(image, point=(50, 24), extent=(40, 20), target=(860, 380))

    with patch("astrbot_plugin_nikke.features.character.face_anchor.metadata", return_value={"c471": row}):
        result = framing(card, image, body_centering=False, summary_count=4)

    assert result["vertical_guard_source"] == "face_local_alpha"
    assert result["safe_top"] == summary_layout(4).safe_top
    assert result["guard_top_card_after"] >= result["safe_top"] - 1.0
    assert result["core_axis"]["available"] is False


def test_face_local_head_scan_ignores_distant_alpha_speck():
    from PIL import ImageDraw

    card = make_card()
    image = Image.new("RGBA", (200, 300), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 20, 10), fill=(255, 255, 255, 255))
    draw.ellipse((82, 40, 118, 102), fill=(255, 255, 255, 255))
    draw.rectangle((78, 96, 122, 280), fill=(255, 255, 255, 255))
    row = make_row(image, point=(100, 75), extent=(20, 20), target=(860, 380))

    with patch("astrbot_plugin_nikke.features.character.face_anchor.metadata", return_value={"c471": row}):
        result = framing(card, image, body_centering=False, summary_count=4)

    assert result["vertical_guard_source"] == "face_local_alpha"
    assert result["guard_top_source_y"] >= 35.0
    assert result["guard_top_card_after"] >= result["safe_top"] - 1.0


def test_missing_face_anchor_uses_robust_alpha_fallback_and_safe_transform():
    from PIL import ImageDraw

    card = make_card()
    image = Image.new("RGBA", (100, 400), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.point((50, 0), fill=(255, 255, 255, 255))
    draw.rectangle((20, 20, 80, 380), fill=(255, 255, 255, 255))

    with patch("astrbot_plugin_nikke.features.character.face_anchor.metadata", return_value={}):
        result = framing(card, image, body_centering=False, summary_count=4)

    assert result["source"] == "anchor_unavailable"
    assert "object-position:50% 35%" not in result["style"]
    assert result["vertical_guard_source"] == "robust_alpha_top"
    assert result["guard_top_source_y"] > 0
    assert result["guard_top_card_before"] < result["safe_top"]
    assert result["guard_top_card_after"] >= result["safe_top"] - 1.0
    assert result["vertical_correction_y"] > 0


def test_regression_characters_have_no_per_character_face_offsets():
    assert not {"c014", "c018", "c020"}.intersection(FACE_Y_OFFSET_OVERRIDES)


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


def test_production_c401_c581_records_match_portraits_and_safe_corridor():
    records = json.loads(
        (ROOT / "assets/data/face_anchors.json").read_text(encoding="utf-8")
    )["records"]

    for render_id, resource_id in (("c401", "401"), ("c581", "581")):
        portrait_path = ROOT / "assets/spine-rendered" / f"{render_id}.png"
        assert portrait_path.is_file()
        row = records[render_id]
        with Image.open(portrait_path) as opened:
            portrait = opened.convert("RGBA")

        assert row["pixel_sha256"] == hashlib.sha256(portrait.tobytes()).hexdigest()
        assert row["image_size"] == list(portrait.size)
        for point in (row["point"], row["extent"], row["core_axis"]["eye_point"], row["core_axis"]["torso_point"]):
            assert len(point) == 2
            assert all(math.isfinite(value) for value in point)
        assert math.isfinite(row["core_axis"]["head_top_y"])

        card = example_card()
        card.resource_id = resource_id
        card.costume_id = 0
        card.costume_selection = CostumeSelection(0, "test", "default")
        result = framing(card, portrait, body_centering=False, summary_count=4)
        axis = result["core_axis"]

        assert result["source"] not in {"anchor_unavailable", "identity_unknown", "anchor_invalid"}
        assert result["render_id"] == render_id
        assert axis["available"] is True
        assert axis["head_top_card_after"] >= axis["safe_top"] - 1e-6
        assert axis["eye_card_after"] >= axis["head_top_card_after"]
        assert axis["torso_card_after"] <= axis["safe_bottom"] + 1e-6
        assert axis["scale_after"] >= axis["scale_before"] * MIN_AUTO_SCALE_RATIO
        assert result["vertical_guard_source"] == "core_head_top"
        assert result["guard_top_card_after"] >= result["safe_top"] - 1.0

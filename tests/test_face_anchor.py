"""构图只消费经过图像绑定校验的离线锚点。"""
import hashlib
from unittest.mock import patch
from PIL import Image

from astrbot_plugin_nikke.face_anchor import framing
from astrbot_plugin_nikke.card_models import CostumeSelection
from astrbot_plugin_nikke.tests.test_character_replica import example_card


def test_anchor_binding_and_no_default_costume_fallback():
    card = example_card()
    card.resource_id, card.costume_id, card.costume_selection = "471", 0, CostumeSelection(0, "test", "default")
    image = Image.new("RGBA", (100, 200), "white")
    row = {"pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(), "point": [60, 40],
           "extent": [20, 10], "anchor_kind": "eye_attachment"}
    with patch("astrbot_plugin_nikke.face_anchor.metadata", return_value={"c471": row}):
        assert framing(card, image)["source"] == "eye_attachment"
        assert "left:-8.000px" in framing(card, image)["style"]
        assert framing(card, Image.new("RGBA", (100, 200), "black"))["source"] == "anchor_unavailable"
        card.costume_id = "unknown"
        card.costume_selection = CostumeSelection("unknown", "test", "unknown")
        assert framing(card, image)["source"] == "identity_unknown"


def test_missing_anchor_does_not_use_manual_character_offsets():
    card = example_card()
    with patch("astrbot_plugin_nikke.face_anchor.metadata", return_value={}):
        result = framing(card, Image.new("RGBA", (20, 30)))
        assert result["source"] == "anchor_unavailable"
        assert "object-fit:contain" in result["style"]


def test_resolution_variant_and_head_fallback():
    card = example_card()
    card.resource_id, card.costume_id = "471", 0
    card.costume_selection = CostumeSelection(0, "test", "default")
    image = Image.new("RGBA", (100, 200), "white")
    variant = {"pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(), "image_size": [100, 200],
               "point": [50, 50], "extent": None, "anchor_kind": "head_bone",
               "framing": {"target": [800, 600], "extent_width": 430}}
    with patch("astrbot_plugin_nikke.face_anchor.metadata", return_value={"c471": {"variants": [variant]}}):
        result = framing(card, image)
        assert result["source"] == "head_bone" and "left:200.000px" in result["style"]
        variant["image_size"] = [200, 100]
        assert framing(card, image)["source"] == "anchor_unavailable"


def test_body_centering_activation_and_contracts():
    card = example_card()
    card.resource_id, card.costume_id = "471", 0
    card.costume_selection = CostumeSelection(0, "test", "default")

    image = Image.new("RGBA", (100, 200), (0, 0, 0, 0))
    from PIL import ImageDraw
    draw = ImageDraw.Draw(image)
    draw.rectangle((50, 35, 82, 185), fill=(255, 255, 255, 255))
    cx = (50 + 82) // 2
    draw.ellipse((cx - 10, 15, cx + 10, 45), fill=(255, 255, 255, 255))
    face = [61, 30]

    digest = hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest()
    row = {
        "pixel_sha256": digest,
        "image_size": [100, 200],
        "point": face,
        "extent": [40, 20],
        "anchor_kind": "eye_attachment",
        "framing": {"target": [860, 500], "extent_width": 160},
    }

    with patch("astrbot_plugin_nikke.face_anchor.metadata", return_value={"c471": row}):
        # 1. No flag / environment => byte-equivalent base style (default OFF)
        with patch.dict("os.environ", {}, clear=True):
            base_result = framing(card, image)
            assert "body_centering" not in base_result
            assert base_result["source"] == "eye_attachment"
            assert base_result["render_id"] == "c471"

        # 2. body_centering=False overrides a truthy environment flag
        for truthy in ("1", "true", "yes", "on", "preview", "TRUE", "Yes"):
            with patch.dict("os.environ", {"NIKKE_FACE_GUIDED_CENTERING": truthy}):
                forced_off = framing(card, image, body_centering=False)
                assert forced_off["style"] == base_result["style"]
                assert "body_centering" not in forced_off

        # 3. body_centering=True can apply an accepted horizontal correction
        explicit_on = framing(card, image, body_centering=True)
        assert "body_centering" in explicit_on
        diag = explicit_on["body_centering"]
        assert diag["mode"] == "face_guided_v5"
        # 6. source and render_id contracts are unchanged
        assert explicit_on["source"] == "eye_attachment"
        assert explicit_on["render_id"] == "c471"
        # 5. scale is unchanged (width and height in style match base_result exactly)
        import re
        w_base = re.search(r"width:([\d.]+)px", base_result["style"]).group(1)
        h_base = re.search(r"height:([\d.]+)px", base_result["style"]).group(1)
        w_on = re.search(r"width:([\d.]+)px", explicit_on["style"]).group(1)
        h_on = re.search(r"height:([\d.]+)px", explicit_on["style"]).group(1)
        assert w_base == w_on
        assert h_base == h_on
        # Vertical position top is unchanged (horizontal only)
        top_base = re.search(r"top:([\d.]+)px", base_result["style"]).group(1)
        top_on = re.search(r"top:([\d.]+)px", explicit_on["style"]).group(1)
        assert top_base == top_on
        # Horizontal shift was applied
        left_base = float(re.search(r"left:([-\d.]+)px", base_result["style"]).group(1))
        left_on = float(re.search(r"left:([-\d.]+)px", explicit_on["style"]).group(1))
        assert left_on != left_base
        assert diag["shift_x"] != 0.0
        assert diag["shift_y"] == 0.0

        # Truthy env var activates preview pass
        with patch.dict("os.environ", {"NIKKE_FACE_GUIDED_CENTERING": "preview"}):
            env_on = framing(card, image)
            assert env_on["style"] == explicit_on["style"]
            assert env_on["body_centering"] == diag

        # 4. Low confidence & insufficient silhouette => identical base transform
        blank_image = Image.new("RGBA", (100, 200), (0, 0, 0, 0))
        blank_digest = hashlib.sha256(blank_image.convert("RGBA").tobytes()).hexdigest()
        blank_row = dict(row, pixel_sha256=blank_digest, point=[50, 30])
        with patch("astrbot_plugin_nikke.face_anchor.metadata", return_value={"c471": blank_row}):
            blank_base = framing(card, blank_image, body_centering=False)
            blank_preview = framing(card, blank_image, body_centering=True)
            assert blank_preview["style"] == blank_base["style"]
            assert blank_preview["body_centering"]["shift_x"] == 0.0
            assert blank_preview["body_centering"]["reason"] == "insufficient_silhouette"

        # Early one-sided growth without clean neck evidence fails closed with low_confidence
        low_conf_image = Image.new("RGBA", (140, 210), (0, 0, 0, 0))
        lc_draw = ImageDraw.Draw(low_conf_image)
        lc_draw.ellipse((40, 10, 60, 40), fill="white")
        lc_draw.rectangle((40, 35, 60, 195), fill="white")
        lc_draw.rectangle((60, 20, 75, 195), fill="white")
        lc_digest = hashlib.sha256(low_conf_image.convert("RGBA").tobytes()).hexdigest()
        lc_row = dict(row, pixel_sha256=lc_digest, image_size=[140, 210], point=[50, 28])
        with patch("astrbot_plugin_nikke.face_anchor.metadata", return_value={"c471": lc_row}):
            lc_base = framing(card, low_conf_image, body_centering=False)
            lc_preview = framing(card, low_conf_image, body_centering=True)
            assert lc_preview["style"] == lc_base["style"]
            assert lc_preview["body_centering"]["shift_x"] == 0.0
            assert lc_preview["body_centering"]["reason"] == "low_confidence"

        # 7. Unknown costume and pixel-hash mismatch still stop before candidate analysis
        card.costume_selection = CostumeSelection("unknown", "test", "unknown")
        unknown_costume = framing(card, image, body_centering=True)
        assert unknown_costume["source"] == "identity_unknown"
        assert "body_centering" not in unknown_costume

        card.costume_selection = CostumeSelection(0, "test", "default")
        wrong_image = Image.new("RGBA", (100, 200), (1, 2, 3, 4))
        mismatch = framing(card, wrong_image, body_centering=True)
        assert mismatch["source"] == "anchor_unavailable"
        assert "body_centering" not in mismatch


def test_ambiguity_band_scale_sweep_obeys_only_global_safety():
    # 8. Ambiguity-band scale sweep (4, 8, 12) does not assert <20px;
    # it asserts that shift stays within global max_shift_x and face stays in safe box.
    from astrbot_plugin_nikke.face_guided_centering import (
        CenteringConfig,
        FrameTransform,
        center_after_face_anchor,
    )
    from PIL import ImageDraw

    image = Image.new("RGBA", (140, 210), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((40, 10, 60, 40), fill="white")
    draw.rectangle((40, 35, 60, 195), fill="white")
    draw.rectangle((60, 20, 71, 195), fill="white")
    face = (50, 28)

    config = CenteringConfig(
        body_target_x=800,
        body_target_y=850,
        face_safe_left=520,
        face_safe_right=1080,
        face_safe_top=320,
        face_safe_bottom=760,
        max_shift_x=160,
    )

    shifts = []
    for scale in (4.0, 8.0, 12.0):
        base = FrameTransform(scale=scale, left=800 - face[0] * scale, top=500 - face[1] * scale)
        res = center_after_face_anchor(image, face_point=face, base=base, config=config)
        assert res.reason == "ok"
        assert abs(res.applied_shift[0]) <= config.max_shift_x
        assert config.face_safe_left <= res.face_after[0] <= config.face_safe_right
        shifts.append(abs(res.applied_shift[0]))

    assert shifts[0] < shifts[1] < shifts[2]



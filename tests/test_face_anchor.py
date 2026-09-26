"""构图只消费经过图像绑定校验的离线锚点。"""
import hashlib
from pathlib import Path
from unittest.mock import patch
from PIL import Image

from astrbot_plugin_nikke.features.character.face_anchor import framing as _framing
from astrbot_plugin_nikke.integrations.nikke_db.provider import NikkeDbProvider
from astrbot_plugin_nikke.features.character.models import CostumeSelection
from astrbot_plugin_nikke.tests.test_character_replica import example_card

_ASSETS = Path(__file__).resolve().parents[1] / "assets"
_IDENTITY = NikkeDbProvider(_ASSETS, _ASSETS, remote=False)


def framing(data, portrait, **kwargs):
    return _framing(data, portrait, identity_resolver=_IDENTITY, **kwargs)


def test_anchor_binding_and_no_default_costume_fallback():
    card = example_card()
    card.resource_id, card.costume_id, card.costume_selection = "471", 0, CostumeSelection(0, "test", "default")
    image = Image.new("RGBA", (100, 200), "white")
    row = {"pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(), "point": [60, 40],
           "extent": [20, 10], "anchor_kind": "eye_attachment"}
    with patch("astrbot_plugin_nikke.features.character.face_anchor.metadata", return_value={"c471": row}):
        result = framing(card, image)
        assert result["source"] == "eye_attachment"
        assert result["framing_mode"] == "head_only_anchor"
        left = float(result["style"].split("left:", 1)[1].split("px", 1)[0])
        width = float(result["style"].split("width:", 1)[1].split("px", 1)[0])
        scale = width / image.width
        assert abs(left + 60 * scale - result["target_face"][0]) < 0.01
        assert framing(card, Image.new("RGBA", (100, 200), "black"))["source"] == "anchor_unavailable"
        card.costume_id = "unknown"
        card.costume_selection = CostumeSelection("unknown", "test", "unknown")
        assert framing(card, image)["source"] == "identity_unknown"


def test_missing_anchor_does_not_use_manual_character_offsets():
    card = example_card()
    with patch("astrbot_plugin_nikke.features.character.face_anchor.metadata", return_value={}):
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
    with patch("astrbot_plugin_nikke.features.character.face_anchor.metadata", return_value={"c471": {"variants": [variant]}}):
        result = framing(card, image)
        assert result["source"] == "head_bone"
        assert result["framing_mode"] == "head_only_anchor"
        left = float(result["style"].split("left:", 1)[1].split("px", 1)[0])
        width = float(result["style"].split("width:", 1)[1].split("px", 1)[0])
        scale = width / image.width
        assert abs(left + 50 * scale - result["target_face"][0]) < 0.01
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

    with patch("astrbot_plugin_nikke.features.character.face_anchor.metadata", return_value={"c471": row}):
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
        with patch("astrbot_plugin_nikke.features.character.face_anchor.metadata", return_value={"c471": blank_row}):
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
        with patch("astrbot_plugin_nikke.features.character.face_anchor.metadata", return_value={"c471": lc_row}):
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
    from astrbot_plugin_nikke.features.character.face_guided_centering import (
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


def test_c016_and_c191_real_anchors():
    """Verify authentic Spine offline anchors for c016 and c191."""
    from pathlib import Path
    plugin_root = Path(__file__).parent.parent
    c016_path = plugin_root / "assets" / "spine-rendered" / "c016.png"
    c191_path = plugin_root / "assets" / "spine-rendered" / "c191.png"

    assert c016_path.exists(), f"Missing {c016_path}"
    assert c191_path.exists(), f"Missing {c191_path}"

    c016_img = Image.open(c016_path)
    c191_img = Image.open(c191_path)

    card_c016 = example_card()
    card_c016.resource_id = "16"
    card_c016.costume_id = 0
    card_c016.costume_selection = CostumeSelection(0, "default", "default")

    card_c191 = example_card()
    card_c191.resource_id = "191"
    card_c191.costume_id = 0
    card_c191.costume_selection = CostumeSelection(0, "default", "default")

    # c016: Rapi: Red Hood
    off_c016 = framing(card_c016, c016_img, body_centering=False)
    assert off_c016["source"] == "eye_attachment"
    assert off_c016["render_id"] == "c016"
    assert "body_centering" not in off_c016

    on_c016 = framing(card_c016, c016_img, body_centering=True)
    assert on_c016["source"] == "eye_attachment"
    assert on_c016["render_id"] == "c016"
    assert "body_centering" in on_c016
    bc_c016 = on_c016["body_centering"]
    assert bc_c016["reason"] == "ok"
    assert bc_c016["bootstrap_reliable"] is True
    # Cape and heavy weapon shift silhouette right, pulling body centering left by > 40px
    assert bc_c016["shift_x"] < -40.0
    assert abs(bc_c016["shift_x"]) > 40.0

    # c191: Alice
    off_c191 = framing(card_c191, c191_img, body_centering=False)
    assert off_c191["source"] == "eye_attachment"
    assert off_c191["render_id"] == "c191"
    assert "body_centering" not in off_c191

    on_c191 = framing(card_c191, c191_img, body_centering=True)
    assert on_c191["source"] == "eye_attachment"
    assert on_c191["render_id"] == "c191"
    assert "body_centering" in on_c191
    bc_c191 = on_c191["body_centering"]
    assert bc_c191["reason"] == "ok"
    assert bc_c191["bootstrap_reliable"] is True
    # Alice has relatively balanced silhouette, shift is small (< 40px)
    assert abs(bc_c191["shift_x"]) < 40.0


def test_face_y_offset_behavior_and_contracts():
    """验证人脸偏移、水平居中和统一顶部安全线合同。"""
    import re
    from unittest.mock import patch
    from astrbot_plugin_nikke.features.character.face_anchor import (
        DEFAULT_FACE_Y_OFFSET,
        FACE_Y_OFFSET_OVERRIDES,
    )
    from astrbot_plugin_nikke.features.character.face_guided_centering import DEFAULT_CENTERING_CONFIG

    assert DEFAULT_CENTERING_CONFIG.vertical_gain == 0.0
    assert DEFAULT_FACE_Y_OFFSET == 16.0

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

    def parse_style(s):
        w = float(re.search(r"width:([\d.]+)px", s).group(1))
        h = float(re.search(r"height:([\d.]+)px", s).group(1))
        l = float(re.search(r"left:([-\d.]+)px", s).group(1))
        t = float(re.search(r"top:([-\d.]+)px", s).group(1))
        return l, t, w, h

    with patch("astrbot_plugin_nikke.features.character.face_anchor.metadata", return_value={"c471": row}):
        # Baseline with zero Y offset
        with patch("astrbot_plugin_nikke.features.character.face_anchor.DEFAULT_FACE_Y_OFFSET", 0.0), \
             patch.dict("astrbot_plugin_nikke.features.character.face_anchor.FACE_Y_OFFSET_OVERRIDES", {}, clear=True):
            res_zero_off = framing(card, image, body_centering=False)
            res_zero_on = framing(card, image, body_centering=True)
            l0_off, t0_off, w0_off, h0_off = parse_style(res_zero_off["style"])
            l0_on, t0_on, w0_on, h0_on = parse_style(res_zero_on["style"])

        # Default (+16px Y offset)
        with patch.dict("astrbot_plugin_nikke.features.character.face_anchor.FACE_Y_OFFSET_OVERRIDES", {}, clear=True):
            res_def_off = framing(card, image, body_centering=False)
            res_def_on = framing(card, image, body_centering=True)
            l_off, t_off, w_off, h_off = parse_style(res_def_off["style"])
            l_on, t_on, w_on, h_on = parse_style(res_def_on["style"])

        # 1. Top is shifted by exactly +16px compared to baseline
        assert round(t_off - t0_off, 3) == 16.0
        assert round(t_on - t0_on, 3) == 16.0

        # 2. Left, Width, Height are strictly unchanged
        assert l_off == l0_off
        assert l_on == l0_on
        assert w_off == w0_off
        assert h_off == h0_off
        assert w_on == w0_on
        assert h_on == h0_on

        # 3. body-centering ON/OFF both maintain identical +16px Y offset
        assert t_off == t_on
        assert round(t_off - t0_off, 3) == round(t_on - t0_on, 3) == 16.0
        assert res_def_on["body_centering"]["shift_y"] == 0.0

        # 4. 未知身份与锚点校验失败时，仍使用透明度边界执行顶部保护。
        card_unknown = example_card()
        card_unknown.costume_selection = CostumeSelection("unknown", "test", "unknown")
        unknown_result = framing(card_unknown, image)
        assert unknown_result["style"].startswith("width:")
        assert unknown_result["source"] == "identity_unknown"
        assert unknown_result["guard_top_card_after"] >= 393.0

        wrong_img = Image.new("RGBA", (100, 200), (99, 99, 99, 255))
        missing_anchor = framing(card, wrong_img)
        assert missing_anchor["style"].startswith("width:")
        assert "object-position:50% 35%" not in missing_anchor["style"]
        assert missing_anchor["source"] == "anchor_unavailable"
        assert missing_anchor["guard_top_card_after"] >= 393.0

        # 5. Render-specific override overrides global default
        with patch.dict("astrbot_plugin_nikke.features.character.face_anchor.FACE_Y_OFFSET_OVERRIDES", {"c471": 24.0}):
            res_custom = framing(card, image, body_centering=False)
            _, t_custom, _, _ = parse_style(res_custom["style"])
            assert round(t_custom - t0_off, 3) == 24.0

        # Dict style override
        with patch.dict("astrbot_plugin_nikke.features.character.face_anchor.FACE_Y_OFFSET_OVERRIDES", {"c471": {"face_y_offset_px": 8.0}}):
            res_custom8 = framing(card, image, body_centering=False)
            _, t_custom8, _, _ = parse_style(res_custom8["style"])
            assert round(t_custom8 - t0_off, 3) == 8.0

        # 6. Metadata row override takes priority as render-specific
        row_with_override = dict(row, framing=dict(row["framing"], face_y_offset_px=12.0))
        with patch("astrbot_plugin_nikke.features.character.face_anchor.metadata", return_value={"c471": row_with_override}):
            res_meta = framing(card, image, body_centering=False)
            _, t_meta, _, _ = parse_style(res_meta["style"])
            assert round(t_meta - t0_off, 3) == 12.0




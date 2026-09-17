from io import BytesIO
import base64

from PIL import Image
from jinja2 import Environment

from astrbot_plugin_nikke.t2i_payloads import _normalize_equipment_icon
from astrbot_plugin_nikke.t2i_templates import T2ITemplateLoader


def test_equipment_icon_normalization_trims_transparent_padding():
    source = Image.new("RGBA", (240, 240), (0, 0, 0, 0))
    visible = Image.new("RGBA", (20, 60), (255, 255, 255, 255))
    source.alpha_composite(visible, (205, 165))

    normalized = _normalize_equipment_icon(source)
    assert normalized.size == (180, 180)
    bbox = normalized.getchannel("A").getbbox()
    assert bbox is not None
    left, top, right, bottom = bbox

    # 172 px safe box, centered; art must no longer inherit original off-center padding.
    assert right - left <= 172
    assert bottom - top <= 172
    assert abs((left + right) / 2 - 90) <= 1
    assert abs((top + bottom) / 2 - 90) <= 1


def test_character_template_has_calibrated_typography_and_badges():
    template = T2ITemplateLoader().load("character")
    assert "--type-summary-label" in template
    assert "font-variant-numeric:tabular-nums" in template
    assert 'class="tier-badge summary-tier"' in template
    assert 'class="tier-badge option-tier"' in template
    assert 'class="gear-status-badge"' in template
    assert "grid-template-columns:620px 470px 190px" in template
    assert "grid-template-columns:minmax(0,1fr) 132px 82px" in template
    assert "radial-gradient(" in template
    assert "backdrop-filter:blur(22px)" in template
    assert 'class="ol-row empty empty-row"' in template
    assert ".ol-row.empty .placeholder-label" in template
    assert "grid-column:1 / 3" in template


def test_rapi_red_hood_golden_sample_face_anchor_is_calibrated():
    from astrbot_plugin_nikke.face_anchor import metadata
    c010 = metadata().get("c010")
    assert c010 is not None
    assert "framing" in c010
    assert c010["framing"]["target"] == [860, 610]
    assert c010["framing"]["extent_width"] == 230.0


def test_snow_white_face_anchor_is_calibrated():
    from astrbot_plugin_nikke.face_anchor import metadata
    c471 = metadata().get("c471")
    assert c471 is not None
    assert "framing" in c471
    assert c471["framing"]["target"] == [742, 540]
    assert c471["framing"]["extent_width"] == 248.4


def test_custom_webfonts_and_slot_geometry_in_template():
    from astrbot_plugin_nikke.character_replica import barlow_font, rajdhani_font
    barlow_uri = barlow_font()
    rajdhani_uri = rajdhani_font()
    assert barlow_uri is not None and barlow_uri.startswith("data:font/ttf;base64,")
    assert rajdhani_uri is not None and rajdhani_uri.startswith("data:font/ttf;base64,")

    template = T2ITemplateLoader().load("character")
    assert "font-family:'NikkeBarlowCondensed'" in template
    assert "font-family:'NikkeRajdhani'" in template
    assert "--font-number:'NikkeBarlowCondensed'" in template
    assert "--font-tech:'NikkeRajdhani'" in template
    assert ".character.typo-set-b" in template
    assert ".character.typo-set-c" in template
    assert ".character.typo-current" in template

    # Header slot geometry
    assert 'class="lv-prefix"' in template
    assert 'class="identity-bottom"' in template
    assert 'class="combat"' in template
    assert 'class="stars"' in template
    assert 'class="item-badge"' in template
    assert 'class="identity-icon' in template
    assert "right:50px" in template

    # Equipment icon size & placeholder grid
    assert "width:168px;height:168px" in template
    assert "height:57px" in template
    assert "grid-column:1 / 3" in template


def test_face_anchor_eight_real_samples_and_three_fallbacks():
    from astrbot_plugin_nikke.face_anchor import metadata, framing, identity_resolver
    from astrbot_plugin_nikke.card_models import CostumeSelection
    from astrbot_plugin_nikke.tests.test_character_replica import example_card
    from PIL import Image

    meta = metadata()
    assert len(meta) >= 8

    eight_samples = [
        ("rapi", "10", 0, "c010"),
        ("snow-white", "471", 0, "c471"),
        ("rapi-vacation", "10", 10005, "c010_03"),
        ("rapi-promise", "10", 20001, "c010_02"),
        ("wide", "330", 0, "c330"),
        ("tall", "234", 0, "c234"),
        ("elysion", "17", 0, "c017"),
        ("tetra", "352", 0, "c352"),
    ]

    for name, rid, costume, expected_render_id in eight_samples:
        render_id = identity_resolver().resolve_render_id(rid, costume)
        assert render_id == expected_render_id, f"{name} render_id mismatch"
        record = meta.get(render_id)
        assert record is not None, f"{name} missing in metadata"
        assert record.get("anchor_kind") == "eye_attachment"
        assert isinstance(record.get("point"), list) and len(record["point"]) == 2
        assert isinstance(record.get("extent"), list) and len(record["extent"]) == 2

    # 3 Separate layout/fallback cases
    card = example_card()
    card.resource_id, card.costume_id = "10", 0
    card.costume_selection = CostumeSelection(0, "test", "default")
    dummy_img = Image.new("RGBA", (100, 100), "white")

    # 1. long-name layout case
    long_name_card = example_card()
    long_name_card.name_cn = "这是用于验证中英文超长角色名称的练度卡 Long Character Name"
    assert len(long_name_card.name_cn) > 16

    # 2. empty equipment layout case
    empty_card = example_card()
    empty_card.equipment = {}
    assert len(empty_card.equipment) == 0

    # 3. unknown-costume fallback case
    unknown_costume_card = example_card()
    unknown_costume_card.costume_id = "unknown"
    unknown_costume_card.costume_selection = CostumeSelection("unknown", "test", "unknown")
    result = framing(unknown_costume_card, dummy_img)
    assert result["source"] == "identity_unknown"
    assert result["style"] == "object-fit:contain"




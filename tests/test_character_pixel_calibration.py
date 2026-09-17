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
    from astrbot_plugin_nikke.character_replica import barlow_font, rajdhani_font, noto_font
    barlow_uri = barlow_font()
    rajdhani_uri = rajdhani_font()
    noto_uri = noto_font()
    assert barlow_uri is not None and barlow_uri.startswith("data:font/ttf;base64,")
    assert rajdhani_uri is not None and rajdhani_uri.startswith("data:font/ttf;base64,")
    assert noto_uri is not None and noto_uri.startswith("data:font/ttf;base64,")

    template = T2ITemplateLoader().load("character")
    # Registered @font-face families
    assert "font-family:'NikkeNotoSC'" in template
    assert "font-family:'NikkeBarlowCondensed'" in template
    assert "font-family:'NikkeRajdhani'" in template

    # Calibrated typography tokens
    assert "--font-cn-title:" in template
    assert "--font-cn-body:" in template
    assert "--font-num-display:" in template
    assert "--font-tech-label:" in template
    assert "--size-character-name:67px;" in template
    assert "--size-level-value:69px;" in template
    assert "--size-battle-power:84px;" in template

    # Typography candidate profiles (A/B/C/D)
    assert ".character.header-font-a" in template
    assert ".character.header-font-b" in template
    assert ".character.header-font-c" in template
    assert ".character.header-font-d" in template

    # Header fixed slot geometry
    assert 'class="slot-character-name title-line"' in template
    assert 'class="slot-level level"' in template
    assert 'class="slot-total-pill total' in template
    assert 'class="slot-battle-power combat"' in template
    assert 'class="slot-rarity-stars stars"' in template
    assert 'class="icon-slot icon-slot-1' in template
    assert 'class="icon-slot icon-slot-2' in template
    assert 'class="icon-slot icon-slot-{{ loop.index + 2 }}' in template
    assert ".slot-character-name{position:absolute;left:52px;" in template
    assert ".slot-level{position:absolute;left:715px;" in template
    assert ".slot-total-pill{position:absolute;right:50px;" in template
    assert ".slot-battle-power{position:absolute;left:50px;" in template
    assert ".slot-rarity-stars{position:absolute;left:275px;" in template
    assert ".icon-slot-1{left:420px}" in template
    assert ".icon-slot-6{left:1110px}" in template

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

def test_character_font_audit_and_fallback():
    from pathlib import Path
    from jinja2 import Environment
    from astrbot_plugin_nikke.t2i_assets import T2IAssetResolver
    from astrbot_plugin_nikke.t2i_payloads import CharacterT2IPayloadBuilder
    from astrbot_plugin_nikke.tests.test_character_replica import example_card
    from astrbot_plugin_nikke.character_replica import (
        noto_font, barlow_font, barlow_semibold_font,
        rajdhani_font, rajdhani_semibold_font, replica_font
    )

    fonts_dir = Path(__file__).resolve().parents[1] / "fonts"
    assert (fonts_dir / "NotoSansSC-wght.ttf").exists()
    assert (fonts_dir / "BarlowCondensed-Bold.ttf").exists()
    assert (fonts_dir / "BarlowCondensed-SemiBold.ttf").exists()
    assert (fonts_dir / "Rajdhani-Bold.ttf").exists()
    assert (fonts_dir / "Rajdhani-SemiBold.ttf").exists()

    # Base64 cache resolution
    assert noto_font().startswith("data:font/ttf;base64,")
    assert barlow_font().startswith("data:font/ttf;base64,")
    assert barlow_semibold_font().startswith("data:font/ttf;base64,")
    assert rajdhani_font().startswith("data:font/ttf;base64,")
    assert rajdhani_semibold_font().startswith("data:font/ttf;base64,")

    # Payload building includes all font URIs
    import types
    card = example_card()
    dummy_assets = types.SimpleNamespace(
        portrait=None, equipment={}, corporation=None, element=None, weapon=None, burst=None,
        skills={}, favorite_item=None, cube=None
    )
    payload = CharacterT2IPayloadBuilder(T2IAssetResolver()).build(card, dummy_assets)
    for font_key in ("font_noto", "font_barlow", "font_barlow_sb", "font_rajdhani", "font_rajdhani_sb"):
        assert font_key in payload
        assert payload[font_key].startswith("data:font/ttf;base64,")

    # Rendered HTML audit
    rendered = Environment().from_string(T2ITemplateLoader().load("character")).render(**payload)
    assert "@font-face{font-family:'NikkeNotoSC'" in rendered
    assert "@font-face{font-family:'NikkeBarlowCondensed'" in rendered
    assert "@font-face{font-family:'NikkeBarlowCondensedSemiBold'" in rendered
    assert "@font-face{font-family:'NikkeRajdhani'" in rendered
    assert "@font-face{font-family:'NikkeRajdhaniSemiBold'" in rendered
    assert "--font-cn-title:'NikkeNotoSC'" in rendered


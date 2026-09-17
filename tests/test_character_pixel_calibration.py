from io import BytesIO
import base64

from PIL import Image
from jinja2 import Environment

from astrbot_plugin_nikke.ui.t2i_payloads import _normalize_equipment_icon
from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader


def test_equipment_icon_normalization_trims_transparent_padding():
    source = Image.new("RGBA", (240, 240), (0, 0, 0, 0))
    visible = Image.new("RGBA", (20, 60), (255, 255, 255, 255))
    source.alpha_composite(visible, (205, 165))

    normalized = _normalize_equipment_icon(source)
    assert normalized.size == (180, 180)
    bbox = normalized.getchannel("A").getbbox()
    assert bbox is not None
    left, top, right, bottom = bbox

    # 150 px safe box, centered; art must no longer inherit original off-center padding.
    assert right - left <= 150
    assert bottom - top <= 150
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

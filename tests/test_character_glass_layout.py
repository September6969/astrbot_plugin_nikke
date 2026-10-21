"""角色卡毛玻璃随词条数量收缩，装备位置保持稳定。"""
import pytest
from astrbot_plugin_nikke.tests.test_character_replica import example_card
from astrbot_plugin_nikke.core.assets.fallback_provider import FallbackAssetProvider
from astrbot_plugin_nikke.ui.payloads.character import CharacterT2IPayloadBuilder
from astrbot_plugin_nikke.ui.t2i_assets import T2IAssetResolver
from astrbot_plugin_nikke.features.character.face_anchor import metadata

@pytest.mark.parametrize('count', range(5))
def test_glass_tracks_content_without_moving_equipment(count):
    card = example_card()
    keys = list(dict.fromkeys(o.effect_group_id for e in card.equipment.values() for o in e.options))[:count]
    for item in card.equipment.values():
        item.options = [o for o in item.options if o.effect_group_id in keys]
    if not count:
        card.equipment = {}
    assets = FallbackAssetProvider().resolve_character_assets(card)
    payload = CharacterT2IPayloadBuilder(T2IAssetResolver()).build(card, assets)
    layout = payload['character_layout']
    assert layout['summary_count'] == count
    assert layout['equipment_top'] + layout['equipment_height'] == 2340
    assert layout['equipment_top'] + layout['gear_local_top'] == 1859
    content_top = layout['summary_top'] if count else layout['gear_top']
    assert content_top - layout['equipment_top'] == 50
    if not count:
        assert layout['equipment_height'] == 531
        assert payload['summary_panel_style'] == ''

def test_harran_anchor_is_pixel_bound_and_excludes_bird_eyes():
    row = metadata()['c230']
    assert row['image_size'] == [944, 979]
    assert row['pixel_sha256'] == '25ad13abb568adbbf01decec83334a0a4dfcbc9a61dec23a6506472de7b938a8'
    assert row['anchor_kind'] == 'eye_attachment'
    assert row['core_axis_reason'] == 'upper_torso_unavailable'
    assert 'karas' not in str(row).lower()

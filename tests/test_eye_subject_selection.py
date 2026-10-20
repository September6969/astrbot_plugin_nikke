"""真实哈兰眼部几何及多主体歧义回归。"""
import json
from pathlib import Path
import pytest
from PIL import Image
from astrbot_plugin_nikke.integrations.spine.portrait_anchor import attach_anchor
from astrbot_plugin_nikke.features.character.portrait_anchor import read_anchor


def anchor(attachments):
    image = Image.new('RGBA', (1024, 1024))
    return read_anchor(attach_anchor(image, {'schema': 1, 'bones': [], 'attachments': attachments}, (0, 0, 1024, 1024)))


def test_harran_actual_geometry_excludes_crow_and_glints():
    geometry = json.loads((Path(__file__).parent / 'fixtures/harran_eye_geometry.json').read_text(encoding='utf-8'))
    row = anchor(geometry['attachments'])
    assert row['status'] == 'ready'
    assert row['point'] == pytest.approx([604.1978358283856, 226.6509413073598])
    assert row['extent'] == pytest.approx([51.00411910059324, 24.862238885371085])
    assert anchor(list(reversed(geometry['attachments'])))['point'] == row['point']


def eye(name, parent, x):
    return {'slot': name, 'attachment': name, 'parent': parent, 'box': [x, 100, x+10, 110]}


def test_two_bilateral_subjects_are_ambiguous_not_averaged():
    row = anchor([eye('eye_l','head_a',100),eye('eye_r','head_a',120),
                  eye('eye_l','head_b',500),eye('eye_r','head_b',520)])
    assert row['status'] == 'unavailable'
    assert row['reason'] == 'ambiguous_eye_subjects'


def test_single_eye_remains_supported_but_two_unproven_subjects_do_not_merge():
    assert anchor([eye('eye','head',100)])['status'] == 'ready'
    assert anchor([eye('eye','head_a',100),eye('eye','head_b',500)])['status'] == 'unavailable'


def test_glint_cannot_expand_eye_bounds():
    base = [eye('eye_l','head',100),eye('eye_r','head',120)]
    assert anchor(base + [eye('eye_hl','head',900)])['extent'] == anchor(base)['extent']

@pytest.mark.parametrize('parent', ['', 'root'])
def test_distant_eyes_sharing_root_are_not_merged(parent):
    assert anchor([eye('eye_l',parent,100),eye('eye_r',parent,900)])['status'] == 'unavailable'


def test_numbered_rig_with_single_bilateral_group_keeps_both_eyes():
    row = anchor([eye('idle_eyehole_l','bone2',100),eye('idle_eyehole_r','bone2',130),eye('pet_eye','pet_head',600)])
    assert row['point'] == [120,105]


def test_malformed_optional_owner_does_not_discard_portrait():
    item = eye('eye', [], 100)
    item['bone'] = {}
    assert anchor([item])['status'] == 'ready'

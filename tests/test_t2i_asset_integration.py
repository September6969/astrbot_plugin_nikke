"""用已交付公开镜像验证生产展示链；不发起接口或网络请求。"""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from jinja2 import Environment

from astrbot_plugin_nikke.core.asset_manager import AssetManager
from astrbot_plugin_nikke.scripts.preview_t2i_ui import fixture_record
from astrbot_plugin_nikke.scripts.t2i_preview_fixtures import get_cases
from astrbot_plugin_nikke.ui.t2i_assets import T2IAssetResolver
from astrbot_plugin_nikke.ui.payloads.campaign import CampaignT2IPayloadBuilder
from astrbot_plugin_nikke.ui.t2i_payloads import (
    CampaignT2IPayloadBuilder as LegacyCampaignT2IPayloadBuilder,
    ProfileT2IPayloadBuilder,
)
from astrbot_plugin_nikke.ui.payloads.character import CharacterT2IPayloadBuilder
from astrbot_plugin_nikke.ui.payloads.raid_member import UnionMemberT2IPayloadBuilder
from astrbot_plugin_nikke.ui.payloads.raid_overview import UnionOverviewT2IPayloadBuilder
from astrbot_plugin_nikke.ui.payloads.raid_records import UnionRecordsT2IPayloadBuilder
from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader

ROOT = Path(__file__).resolve().parents[1]


def test_campaign_payload_legacy_import_points_to_canonical_module():
    assert LegacyCampaignT2IPayloadBuilder is CampaignT2IPayloadBuilder


def test_union_payload_builders_are_owned_by_page_modules():
    import ast

    assert UnionMemberT2IPayloadBuilder.__module__ == "astrbot_plugin_nikke.ui.payloads.raid_member"
    assert UnionOverviewT2IPayloadBuilder.__module__ == "astrbot_plugin_nikke.ui.payloads.raid_overview"
    assert UnionRecordsT2IPayloadBuilder.__module__ == "astrbot_plugin_nikke.ui.payloads.raid_records"

    source = (ROOT / "ui" / "t2i_payloads.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert not any(
        isinstance(node, ast.ClassDef)
        and node.name in {
            "UnionMemberT2IPayloadBuilder",
            "UnionOverviewT2IPayloadBuilder",
            "UnionRecordsT2IPayloadBuilder",
        }
        for node in ast.walk(tree)
    )


@pytest.fixture
def assets(tmp_path):
    manager = AssetManager(tmp_path / "cache", ROOT / "assets", remote=False)
    yield manager
    manager.close()


def rendered(page, payload):
    assert json.loads(json.dumps(payload)) == payload
    html = Environment().from_string(T2ITemplateLoader().load(page)).render(**payload)
    for forbidden in ("http://", "https://", "file://", "fetch(", "XMLHttpRequest", "@import"):
        assert forbidden not in html
    return html


def test_entire_prepared_compact_and_boss_inventory_is_local(assets):
    inventory = json.loads((ROOT / "data/nikke/blabla-manifests/character_zh-tw_nikke_list_zh-TW_v2.json").read_text(encoding="utf-8"))
    costumes = 0
    for character in inventory:
        result = assets.resolve_lineup_portrait(character_id=character["id"])
        assert not result.is_fallback and result.resource_id == character["resource_id"]
        assert result.local_path.is_file()
        for costume in character.get("costumes", []):
            result = assets.resolve_lineup_portrait(character_id=character["id"], costume_id=costume["id"])
            assert not result.is_fallback and result.resource_id == character["resource_id"]
            assert result.local_path.is_file()
            costumes += 1
    assert len(inventory) == 200 and costumes == 178
    paths = set()
    for record in assets.boss_asset_resolver.manifest_records:
        result = assets.resolve_boss_asset(boss_id=record["boss_id"], icon_id=record["icon_id"])
        assert not result.is_fallback and result.local_path.is_file()
        paths.add(result.local_path)
    assert len(paths) == 23


@pytest.mark.parametrize("name", ["normal", "hard"])
def test_campaign_five_real_compact_portraits(assets, name):
    assets.get_character_portrait = Mock(side_effect=AssertionError("禁止 Spine 裁剪"))
    original = assets.resolve_lineup_portrait
    assets.resolve_lineup_portrait = Mock(wraps=original)
    record = fixture_record(name)
    payload = CampaignT2IPayloadBuilder(assets, T2IAssetResolver()).build(record)
    assert len(payload["members"]) == 5
    assert all(m["portrait_data_uri"].startswith("data:image/png;base64,") for m in payload["members"])
    assert [m["slot"] for m in payload["members"]] == [str(m.slot) for m in record.members]
    assert payload["total_combat"] == f"{record.total_combat:,}"
    assert assets.resolve_lineup_portrait.call_count == 5
    assets.get_character_portrait.assert_not_called()
    rendered("campaign", payload)


def test_compact_corrupt_and_wrong_costume_affect_only_one(assets, tmp_path):
    record = fixture_record("normal")
    builder = CampaignT2IPayloadBuilder(assets, T2IAssetResolver())
    original = assets.resolve_lineup_portrait
    corrupt = tmp_path / "corrupt.webp"
    corrupt.write_bytes(b"not an image")
    def resolve(**kwargs):
        result = original(**kwargs)
        if result.resource_id == 330:
            result.local_path = corrupt
        return result
    assets.resolve_lineup_portrait = resolve
    payload = builder.build(record)
    assert payload["members"][0]["portrait_data_uri"] is None
    assert all(m["portrait_data_uri"] for m in payload["members"][1:])
    assert payload["members"][0]["combat"] == f"{record.members[0].combat:,}"
    assets.resolve_lineup_portrait = original
    record.members[0].costume_id = 10005
    assert builder.build(record)["members"][0]["portrait_data_uri"] is None


def test_known_bosses_and_future_unresolved(assets, tmp_path):
    builder = UnionOverviewT2IPayloadBuilder(assets)
    cases = get_cases("union_overview", tmp_path)
    payload = builder.build(cases["with-boss-assets"])
    assert len(payload["bosses"]) == 5
    assert all(b["boss_image_data_uri"] and b["asset_state"] == "resolved" and not b["is_fallback"] for b in payload["bosses"])
    assert "default_boss" not in rendered("union_overview", payload)
    unknown = builder.build(cases["missing-asset"])
    assert all(b["asset_state"] == "UNRESOLVED" and b["is_fallback"] and b["boss_image_data_uri"] is None for b in unknown["bosses"])


def test_member_costume_and_boss(assets, tmp_path):
    case = get_cases("union_member", tmp_path)["with-portraits"]
    payload = UnionMemberT2IPayloadBuilder(assets, T2IAssetResolver()).build(case)
    rows = payload["participants"][0]["rows"]
    assert rows
    costume = assets.resolve_lineup_portrait(character_id=10, costume_id=10005)
    # compact 清单索引为 2；Spine 同一皮肤为 c010_03，不能混用两个索引。
    assert not costume.is_fallback and costume.costume_index == 2
    uri = T2IAssetResolver().encode(costume.local_path)
    for row in rows:
        assert len(row["members"]) == 5
        assert all(m["portrait_data_uri"] for m in row["members"])
        assert row["members"][0]["portrait_data_uri"] == uri
        assert row["boss_image_data_uri"] and not row["is_fallback"]
    rendered("union_member", payload)


@pytest.mark.parametrize("name", ["c010", "c010_02", "c010_03", "c017", "c234", "c330", "c352", "c471"])
def test_character_verified_art(assets, tmp_path, name):
    case = get_cases("character", tmp_path)[name]
    images = assets.resolve_character_assets(case)
    manifest = json.loads((ROOT / "assets/spine_manifest.json").read_text(encoding="utf-8"))["characters"][name]
    assert images.portrait.size == (manifest["width"], manifest["height"])
    payload = CharacterT2IPayloadBuilder(T2IAssetResolver()).build(case, images)
    assert payload["character_art_data_uri"].startswith("data:image/png;base64,")
    assert len(payload["equipment"]) == 4 and all(len(g["options"]) == 3 for g in payload["equipment"])
    rendered("character", payload)


def test_profile_current_model_progress_icons_and_fields(assets, tmp_path):
    case = get_cases("profile", tmp_path)["full-current-model"]
    builder = ProfileT2IPayloadBuilder(assets)
    payload = builder.build(case)
    assert payload["storage"] == {"value": "72.0%", "bar": 72.0, "semantic": "normal", "scope": "AVAILABLE"}
    assert len(payload["resources"]) == 8
    assert all(item["icon_data_uri"] for item in payload["resources"])
    assert dict((v["label"], v["value"]) for v in payload["outpost"])["基础核心"] == "20"
    html = rendered("profile", payload)
    assert '<meta name="viewport" content="width=1200">' in html
    assert "storage-track" in html and "72.0%" in html
    for forbidden in ("战术学院", "tactic_academy", "EXP 0"):
        assert forbidden not in html
    assert "46-40" in html and "35-36" in html
    assert "12,345" in html
    for ratio, state in ((.8, "warning"), (.95, "strong-warning"), (None, "normal")):
        case.storage_fullness = ratio
        storage = builder.build(case)["storage"]
        assert storage["semantic"] == state
        if ratio is None:
            assert storage["bar"] is None and storage["value"] == "Unknown"
    original = assets.get_currency_icon
    assets.get_currency_icon = lambda kind: None if kind == 99 else original(kind)
    resources = builder.build(case)["resources"]
    assert resources[0]["icon_data_uri"] is None
    assert all(item["icon_data_uri"] for item in resources[1:])

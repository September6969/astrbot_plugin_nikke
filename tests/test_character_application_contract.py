import ast
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from astrbot_plugin_nikke.features.character.application import (
    CharacterAmbiguousMatch,
    CharacterApplication,
    CharacterIdentityMismatch,
    CharacterNotOwned,
)
from astrbot_plugin_nikke.features.character.identity import CharacterDirectoryResolver
from astrbot_plugin_nikke.features.character.models import CharacterCardRequest, CharacterCardResult


DISPLAY_TZ = timezone(timedelta(hours=8))


def directory():
    return [
        {
            "name_code": "alice",
            "name_cn": "爱丽丝",
            "name_zh_cn": "爱丽丝",
            "name_zh_tw": "愛麗絲",
            "name_en": "Alice",
            "resource_id": 5065,
            "rare": "SSR",
            "element": "Iron",
            "weapon": "SR",
            "burst": "Step3",
            "corporation": "Pilgrim",
        },
        {
            "name_code": "alice_bunny",
            "name_cn": "爱丽丝：仙境兔女郎",
            "name_zh_cn": "爱丽丝：仙境兔女郎",
            "name_zh_tw": "愛麗絲：仙境兔女郎",
            "name_en": "Alice: Wonderland Bunny",
            "resource_id": 5066,
        },
    ]


def detail_payload(code="alice", costume_id=30049):
    return {
        "roster_item": {"name_code": code, "lv": 200, "costume_id": costume_id},
        "detail": {"name_code": code, "costume_tid": costume_id, "attractive_lv": 20},
        "state_effects": [],
    }


class FakeAccountReader:
    def get_account(self, qq_id):
        return {
            "qq_id": qq_id,
            "game_uid": "game-1",
            "nickname": "测试指挥官",
            "cookie": "synthetic-cookie",
        }


class FakeGateway:
    def __init__(self, payload=None):
        self.payload = payload if payload is not None else detail_payload()
        self.detail_requests = []
        self.roster_requests = []
        self.profile_requests = []

    async def get_roster(self, account, include_details=True):
        self.roster_requests.append((account, include_details))
        return [self.payload["roster_item"]]

    async def get_character_detail(self, account, name_code):
        self.detail_requests.append((account, name_code))
        return self.payload

    async def get_profile(self, account):
        self.profile_requests.append(account)
        return {"outpost": {"recycle_room_researches": [{"tid": 1001, "lv": 7}]}}


def make_application(*, gateway=None, directory_resolver=None, monotonic=None):
    builder = Mock()
    builder.build.return_value = object()
    resources = Mock()
    resources.prepare_payload.side_effect = lambda payload: payload
    application = CharacterApplication(
        account_reader=FakeAccountReader(),
        gateway=gateway or FakeGateway(),
        identity=directory_resolver or CharacterDirectoryResolver(),
        stat_resources=resources,
        card_builder=builder,
        clock=lambda: datetime(2026, 9, 22, 12, 30, tzinfo=timezone.utc),
        monotonic=monotonic,
        plugin_version="test-version",
    )
    return application, builder, resources


@pytest.mark.asyncio
async def test_character_application_rejects_ambiguous_identity_without_fetching_details():
    gateway = FakeGateway()
    application, _, _ = make_application(gateway=gateway)

    with pytest.raises(CharacterAmbiguousMatch) as caught:
        await application.character_card("qq-1", "丽丝", directory())

    assert "爱丽丝" in caught.value.candidates
    assert gateway.detail_requests == []


@pytest.mark.asyncio
async def test_character_application_rejects_wrong_response_identity_before_stats_or_rendering():
    gateway = FakeGateway(detail_payload(code="another-character"))
    application, builder, resources = make_application(gateway=gateway)

    with pytest.raises(CharacterIdentityMismatch):
        await application.character_card("qq-1", "Alice", directory())

    assert gateway.detail_requests[0][1] == "alice"
    assert gateway.profile_requests == []
    resources.prepare_payload.assert_not_called()
    builder.build.assert_not_called()


@pytest.mark.asyncio
async def test_unowned_character_is_distinct_and_never_builds_a_card():
    class UnownedGateway(FakeGateway):
        async def get_character_detail(self, account, name_code):
            raise ValueError("该账号未持有这名妮姬")

    gateway = UnownedGateway()
    application, builder, resources = make_application(gateway=gateway)

    with pytest.raises(CharacterNotOwned) as caught:
        await application.character_card("qq-1", "Alice", directory())

    assert caught.value.display_name == "爱丽丝"
    assert gateway.profile_requests == []
    resources.prepare_payload.assert_not_called()
    builder.build.assert_not_called()


@pytest.mark.asyncio
async def test_character_card_uses_exact_identity_costume_research_and_injected_clock():
    gateway = FakeGateway()
    application, builder, resources = make_application(gateway=gateway)

    result = await application.build_card(
        CharacterCardRequest(qq_id="qq-1", query="Alice", directory=directory())
    )
    assert isinstance(result, CharacterCardResult)
    card = result.card

    assert gateway.detail_requests[0][1] == "alice"
    assert gateway.roster_requests == []
    assert builder.build.call_args.kwargs["directory"]["resource_id"] == 5065
    assert builder.build.call_args.kwargs["display_name"] == "爱丽丝"
    assert builder.build.call_args.kwargs["account"]["research_levels"]["general"] == 7
    assert set(builder.build.call_args.kwargs["account"]) == {
        "nickname", "role_name", "research_levels"
    }
    assert "cookie" not in builder.build.call_args.kwargs["account"]
    assert builder.build.call_args.kwargs["payload"]["detail"]["costume_tid"] == 30049
    assert builder.build.call_args.kwargs["fetched_at"] == "2026-09-22 20:30"
    assert builder.build.call_args.kwargs["plugin_version"] == "test-version"
    resources.prepare_payload.assert_called_once()
    assert card is builder.build.return_value


@pytest.mark.asyncio
async def test_legacy_character_card_method_wraps_the_request_result_contract():
    application, builder, _ = make_application()

    card = await application.character_card("qq-1", "Alice", directory())

    assert card is builder.build.return_value


def test_character_application_import_does_not_load_render_network_or_database_modules():
    root = Path(__file__).resolve().parents[1]
    source = (
        "import importlib, sys; "
        "importlib.import_module('astrbot_plugin_nikke.features.character.application'); "
        "loaded = sorted(name for name in ('PIL', 'httpx', 'aiohttp', 'requests', 'sqlite3') "
        "if name in sys.modules); "
        "print(','.join(loaded)); "
        "raise SystemExit(bool(loaded))"
    )
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", source],
        cwd=root.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio
async def test_roster_application_owns_account_query_and_directory_name_mapping():
    gateway = FakeGateway()
    application, _, _ = make_application(gateway=gateway)

    roster = await application.roster("qq-1", directory())

    assert gateway.roster_requests[0][1] is True
    assert roster.commander_name == "测试指挥官"
    assert roster.name_map["alice"] == "爱丽丝"
    assert roster.characters == (gateway.payload["roster_item"],)


@pytest.mark.asyncio
async def test_character_info_rejects_ambiguous_match_instead_of_selecting_first():
    application, _, _ = make_application()

    with pytest.raises(CharacterAmbiguousMatch):
        application.info("丽丝", directory())


@pytest.mark.asyncio
async def test_profile_snapshot_cache_remains_bounded_and_reuses_five_minute_entries():
    gateway = FakeGateway()
    ticks = iter(float(index) for index in range(1000))
    application, _, _ = make_application(gateway=gateway, monotonic=lambda: next(ticks))

    first_account = {"game_uid": "stable-1", "qq_id": "qq-1"}
    first = await application.profile_for_stat_calculation(first_account)
    cached = await application.profile_for_stat_calculation(first_account)
    assert cached is first
    assert len(gateway.profile_requests) == 1

    for index in range(60):
        await application.profile_for_stat_calculation({"game_uid": f"uid-{index}"})

    assert len(application._stats_profile_cache) <= 50
    assert "uid-0" not in application._stats_profile_cache
    assert "uid-59" in application._stats_profile_cache


@pytest.mark.asyncio
async def test_profile_snapshot_cache_expires_at_five_minutes():
    gateway = FakeGateway()
    ticks = [0.0]
    application, _, _ = make_application(
        gateway=gateway, monotonic=lambda: ticks[0]
    )
    account = {"game_uid": "stable-1"}

    await application.profile_for_stat_calculation(account)
    ticks[0] = 299.9
    await application.profile_for_stat_calculation(account)
    assert len(gateway.profile_requests) == 1

    ticks[0] = 300.0
    await application.profile_for_stat_calculation(account)
    assert len(gateway.profile_requests) == 2


def test_main_character_handlers_are_transport_adapters_only():
    root = Path(__file__).resolve().parents[1]
    source = (root / "main.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    plugin = next(
        node for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "NikkePlugin"
    )
    methods = {
        node.name: node
        for node in plugin.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    forbidden = {
        "CharacterDirectoryResolver",
        "map_research_levels",
        "character_stat_resources",
        "character_builder",
        "_find_directory",
        "_name_map",
        "get_character_detail",
        "get_roster",
        "map_research_levels",
        "resolve_character_assets",
        "get_character_portrait",
        "calculate_from_payload",
    }
    for name in ("roster", "character", "info"):
        identifiers = {
            node.id for node in ast.walk(methods[name]) if isinstance(node, ast.Name)
        }
        attributes = {
            node.attr for node in ast.walk(methods[name]) if isinstance(node, ast.Attribute)
        }
        assert not (identifiers | attributes) & forbidden


def test_character_t2i_payload_has_a_canonical_independent_module():
    from astrbot_plugin_nikke.ui.payloads.character import CharacterT2IPayloadBuilder

    root = Path(__file__).resolve().parents[1]
    renderer = (root / "ui" / "renderers" / "t2i.py").read_text(encoding="utf-8")
    assert not (root / "ui" / "t2i_payloads.py").exists()
    assert "ui.payloads.character import CharacterT2IPayloadBuilder" in renderer
    assert CharacterT2IPayloadBuilder.__module__ == "astrbot_plugin_nikke.ui.payloads.character"
    stale_imports = []
    for root_dir in (root / "scripts", root / "ui", root / "tests"):
        for path in root_dir.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                module = node.module or ""
                if module.endswith("t2i_payloads") and any(
                    alias.name == "CharacterT2IPayloadBuilder"
                    for alias in node.names
                ):
                    stale_imports.append(path.relative_to(root).as_posix())
    assert stale_imports == []


def test_roster_name_map_cache_tracks_all_identity_fields_and_field_boundaries():
    application, _, _ = make_application()
    dir_a = [
        {"name_code": 101, "name_cn": "拉毗", "name_en": "Rapi"},
        {"name_code": 102, "name_cn": "阿尼斯", "name_en": "Anis"},
    ]
    dir_b = [
        {"name_code": 101, "name_cn": "红莲", "name_en": "Scarlet"},
        {"name_code": 102, "name_cn": "神罚", "name_en": "Modernia"},
    ]

    map_a = application.name_map(dir_a)
    assert application.name_map(dir_a) is map_a
    map_b = application.name_map(dir_b)
    assert "红莲" in map_b["101"]
    assert "拉毗" not in map_b["101"]

    before = [{"name_code": 103, "name_zh_cn": "a:b", "name_zh_tw": "c"}]
    after = [{"name_code": 103, "name_zh_cn": "a", "name_zh_tw": "b:c"}]
    before_map = application.name_map(before)
    after_map = application.name_map(after)
    assert before_map != after_map


def test_character_info_returns_only_exactly_resolved_public_fields():
    application, _, _ = make_application()

    info = application.info("Alice", directory())

    assert info.name == "爱丽丝"
    assert info.title == "妮姬基础资料"
    assert info.rows[0][0] == "名称（简体别名 / 繁中 / 英文）"
    assert "Alice" in info.rows[0][1]
    assert dict(info.rows)["稀有度"] == "SSR"

# SPDX-License-Identifier: GPL-3.0-or-later
"""练度总览每名角色合并前三类词条的回归测试。

覆盖：共享排序、稳定身份、最多 20 次详情、并发 3、失败降级、详情不覆盖总表数值、
图片与文本复用同一 DTO、渲染失败不重复查询，以及“缺失详情不得当作无词条”
与“前三名绝不向后补位”两条独立复核边界。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from astrbot_plugin_nikke.application.commands.character import CharacterCommandHandler
from astrbot_plugin_nikke.application.commands.contracts import CommandContext, TextReply
from astrbot_plugin_nikke.features.account.errors import CredentialExpiredError
from astrbot_plugin_nikke.features.character.application import CharacterApplication
from astrbot_plugin_nikke.features.character.identity import CharacterDirectoryResolver
from astrbot_plugin_nikke.features.character.roster_ranking import select_top_codes
from astrbot_plugin_nikke.tests.test_card_builder import make_builder
from astrbot_plugin_nikke.ui.payloads.roster import RosterT2IPayloadBuilder


FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "character_details_sanitized.json").read_text(
        encoding="utf-8"
    )
)
ACCOUNT = {
    "qq_id": "10001",
    "game_uid": "uid-10001",
    "game_openid": "openid-10001",
    "area_id": "1",
    "binding_revision": "rev-1",
    "cookie": "synthetic-cookie",
    "cookie_valid": 1,
    "nickname": "测试指挥官",
}


def base_detail(code: str) -> dict:
    roster_item = dict(FIXTURE["roster_item"])
    roster_item["name_code"] = code
    detail = dict(FIXTURE["character_details"][0])
    detail["name_code"] = code
    return {
        "roster_item": roster_item,
        "detail": detail,
        "state_effects": list(FIXTURE["state_effects"]),
    }


def no_equipment_detail(code: str) -> dict:
    payload = base_detail(code)
    for key in list(payload["detail"]):
        if key.endswith("_equip_tid"):
            payload["detail"][key] = 0
    return payload


def unknown_options_detail(code: str) -> dict:
    payload = base_detail(code)
    detail = payload["detail"]
    for slot in ("head", "torso", "arm", "leg"):
        for index in (1, 2, 3):
            key = f"{slot}_equip_option{index}_id"
            if detail.get(key) not in (None, 0, "0"):
                detail[key] = 999999999
    return payload


def equipped_all_option_fields_missing(code: str) -> dict:
    """四个装备槽 ID 齐全，但已装备槽位的词条字段全部缺失。"""
    payload = base_detail(code)
    detail = payload["detail"]
    for slot in ("head", "torso", "arm", "leg"):
        for index in (1, 2, 3):
            detail.pop(f"{slot}_equip_option{index}_id", None)
    return payload


def equipped_some_option_fields_missing(code: str) -> dict:
    """四个装备槽 ID 齐全，但词条字段部分缺失，仍保留一个已识别词条。"""
    payload = base_detail(code)
    detail = payload["detail"]
    keep = "head_equip_option1_id"
    for slot in ("head", "torso", "arm", "leg"):
        for index in (1, 2, 3):
            key = f"{slot}_equip_option{index}_id"
            if key != keep:
                detail.pop(key, None)
    return payload


def equipped_all_option_fields_empty(code: str) -> dict:
    """四个装备槽 ID 齐全，但所有词条字段明确为 0（明确无词条）。"""
    payload = base_detail(code)
    detail = payload["detail"]
    for slot in ("head", "torso", "arm", "leg"):
        for index in (1, 2, 3):
            key = f"{slot}_equip_option{index}_id"
            if key in detail:
                detail[key] = 0
    return payload


def directory_for(codes: list[str]) -> list[dict]:
    return [
        {
            "name_code": code,
            "name_cn": f"角色{code}",
            "name_zh_cn": f"角色{code}",
            "name_zh_tw": f"角色{code}",
            "name_en": f"Unit {code}",
            "resource_id": 470,
        }
        for code in codes
    ]


class FakeAccountReader:
    def get_account(self, qq_id):
        return ACCOUNT


class FakeGateway:
    def __init__(self, characters, details=None, failures=(), expired=()):
        self.characters = list(characters)
        self.details = dict(details or {})
        self.failures = set(failures)
        self.expired = set(expired)
        self.roster_calls: list[bool] = []
        self.detail_calls: list[str] = []

    async def get_roster(self, account, include_details=True):
        self.roster_calls.append(include_details)
        return [dict(item) for item in self.characters]

    async def get_character_detail(self, account, name_code):
        self.detail_calls.append(name_code)
        if name_code in self.expired:
            raise CredentialExpiredError("账号凭据已失效，请重新绑定")
        if name_code in self.failures:
            raise RuntimeError("synthetic detail failure")
        if name_code in self.details:
            return self.details[name_code]
        raise RuntimeError("synthetic missing detail")

    async def get_profile(self, account):
        return {}


def make_app(gateway) -> CharacterApplication:
    return CharacterApplication(
        account_reader=FakeAccountReader(),
        gateway=gateway,
        identity=CharacterDirectoryResolver(),
        stat_resources=Mock(),
        card_builder=make_builder(),
        clock=lambda: datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc),
        plugin_version="test-version",
    )


def roster_entry(code: str, *, combat: int, lv: int = 200, **extra) -> dict:
    item = {
        "name_code": code,
        "lv": lv,
        "combat": combat,
        "grade": 1,
        "core": 2,
        "skill1_lv": 10,
        "skill2_lv": 10,
        "ulti_skill_lv": 10,
    }
    item.update(extra)
    return item


@pytest.mark.asyncio
async def test_roster_fetches_only_twenty_displayed_details():
    codes = [f"51{i:02d}" for i in range(21)]
    characters = [
        roster_entry(code, combat=1000 - index) for index, code in enumerate(codes)
    ]
    details = {code: base_detail(code) for code in codes}
    gateway = FakeGateway(characters, details)
    app = make_app(gateway)

    data = await app.roster("10001", directory_for(codes))

    assert gateway.roster_calls == [True]
    # 仅查询实际展示的前二十行，不请求第二十一名。
    assert gateway.detail_calls == codes[:20]
    assert set(data.option_summaries) == set(codes[:20])
    assert all(summary.status == "ok" for summary in data.option_summaries.values())


@pytest.mark.asyncio
async def test_roster_follows_shared_sort_for_equal_combat_and_same_name():
    characters = [
        roster_entry("5101", combat=900, lv=200),
        roster_entry("5102", combat=900, lv=201),
        roster_entry("5103", combat=900, lv=199),
        roster_entry("5104", combat=800),
    ]
    details = {code: base_detail(code) for code in ("5101", "5102", "5103")}
    gateway = FakeGateway(characters, details)
    app = make_app(gateway)
    # 同名的不同 name_code 绝不能合并。
    directory = directory_for(["5101", "5102", "5103", "5104"])
    for row in directory:
        row["name_cn"] = "同名妮姬"

    data = await app.roster("10001", directory)
    payload = RosterT2IPayloadBuilder().build(data)

    # 战力相同按等级降序：5102(201) > 5101(200) > 5103(199)。
    assert gateway.detail_calls == ["5102", "5101", "5103", "5104"]
    assert [row["name_code"] for row in payload["rows"][:3]] == ["5102", "5101", "5103"]
    assert [row["rank"] for row in payload["rows"][:3]] == [1, 2, 3]
    # 同名角色仍按稳定标识展示，第四名失败状态也保留。
    assert all(row["options"] is not None for row in payload["rows"][:3])
    assert payload["rows"][3]["options"]["status"] == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 1, 2, 3])
async def test_roster_small_rosters_fetch_exactly_available_details(count):
    codes = [f"51{i:02d}" for i in range(count)]
    characters = [roster_entry(code, combat=500 - index) for index, code in enumerate(codes)]
    details = {code: base_detail(code) for code in codes}
    gateway = FakeGateway(characters, details)
    app = make_app(gateway)

    data = await app.roster("10001", directory_for(codes))

    assert gateway.detail_calls == codes
    assert set(data.option_summaries) == set(codes)


@pytest.mark.asyncio
async def test_roster_top3_option_states_are_distinguishable():
    characters = [
        roster_entry("5101", combat=900),
        roster_entry("5102", combat=800),
        roster_entry("5103", combat=700),
        roster_entry("5104", combat=600),
    ]
    details = {
        "5101": base_detail("5101"),
        "5102": no_equipment_detail("5102"),
        "5103": unknown_options_detail("5103"),
        # 额外展示角色缺少测试详情时降级，不影响其他有效结果。
    }
    gateway = FakeGateway(characters, details, failures={"5105"})
    app = make_app(gateway)

    data = await app.roster("10001", directory_for([c["name_code"] for c in characters]))

    assert data.option_summaries["5101"].status == "ok"
    assert data.option_summaries["5101"].rows
    assert data.option_summaries["5102"].status == "none"
    assert data.option_summaries["5102"].message == "无装备词条"
    assert data.option_summaries["5103"].status == "unknown"
    assert data.option_summaries["5103"].message == "词条字段未识别"
    # 未知绝不能显示为 0 阶或“无词条”。
    assert data.option_summaries["5103"].total == 0
    assert data.option_summaries["5103"].rows == ()


@pytest.mark.asyncio
async def test_roster_partial_detail_failure_preserves_other_characters():
    characters = [
        roster_entry("5101", combat=900),
        roster_entry("5102", combat=800),
        roster_entry("5103", combat=700),
    ]
    details = {"5101": base_detail("5101"), "5103": base_detail("5103")}
    gateway = FakeGateway(characters, details, failures={"5102"})
    app = make_app(gateway)

    data = await app.roster("10001", directory_for([c["name_code"] for c in characters]))

    assert data.option_summaries["5101"].status == "ok"
    assert data.option_summaries["5103"].status == "ok"
    assert data.option_summaries["5102"].status == "failed"
    assert data.option_summaries["5102"].message == "详情读取失败"
    # 名单本身不受详情失败影响。
    assert len(data.characters) == 3


@pytest.mark.asyncio
async def test_roster_missing_detail_payload_is_not_reported_as_no_options():
    characters = [roster_entry("5101", combat=900)]
    gateway = FakeGateway(characters, details={"5101": {"roster_item": {"name_code": "5101"}}})
    app = make_app(gateway)

    data = await app.roster("10001", directory_for(["5101"]))

    assert data.option_summaries["5101"].status == "unreturned"
    assert data.option_summaries["5101"].message == "详情未返回"


@pytest.mark.asyncio
async def test_roster_detail_never_overwrites_roster_metrics():
    characters = [roster_entry("5101", combat=123_456, lv=210, grade=4, core=7)]
    payload_detail = base_detail("5101")
    payload_detail["roster_item"].update({"lv": 1, "combat": 1, "grade": 0, "core": 0})
    payload_detail["detail"].update({"lv": 1, "combat": 1, "grade": 0, "core": 0})
    gateway = FakeGateway(characters, details={"5101": payload_detail})
    app = make_app(gateway)

    data = await app.roster("10001", directory_for(["5101"]))
    payload = RosterT2IPayloadBuilder().build(data)
    row = payload["rows"][0]

    assert row["level"] == "210"
    assert row["combat"] == "123,456"
    assert row["grade"] == "突破 4"
    assert row["core"] == "核心 +7"


@pytest.mark.asyncio
async def test_roster_credential_expiry_propagates():
    characters = [roster_entry("5101", combat=900)]
    gateway = FakeGateway(characters, details={"5101": base_detail("5101")}, expired={"5101"})
    app = make_app(gateway)

    with pytest.raises(CredentialExpiredError):
        await app.roster("10001", directory_for(["5101"]))


@pytest.mark.asyncio
async def test_image_and_text_fallback_use_same_dto_options_without_requery():
    characters = [roster_entry("5101", combat=900)]
    gateway = FakeGateway(characters, details={"5101": base_detail("5101")})
    app = make_app(gateway)

    render_calls = {"count": 0}

    async def failing_render(_data):
        render_calls["count"] += 1
        raise RuntimeError("synthetic render failure")

    handler = CharacterCommandHandler(
        application=app,
        directory=lambda: tuple(directory_for(["5101"])),
        render_roster=failing_render,
        render_card=AsyncMock(return_value=None),
        invalidate_cookie=lambda _actor: None,
    )
    context = CommandContext(actor_id="10001", parameters={})
    result = await handler.handle(context)

    assert isinstance(result.messages[0], TextReply)
    text = result.messages[0].text
    assert "词条合计" in text
    assert "【" in text
    # 渲染失败后文本回退使用同一查询快照，不重复抓取详情。
    assert gateway.detail_calls == ["5101"]
    assert render_calls["count"] == 1

    # 同一 DTO 的 T2I 载荷包含同样的词条标签。
    data = await app.roster("10001", directory_for(["5101"]))
    payload = RosterT2IPayloadBuilder().build(data)
    option_labels = [row["label"] for row in payload["rows"][0]["options"]["rows"]]
    for label in option_labels:
        assert f"【{label}】" in text


def test_select_top_codes_does_not_backfill_past_rank_limit():
    """第 1 名缺少稳定标识时，不得让第 4 名补位产生无用详情请求。"""
    characters = [
        {"lv": 200, "combat": 900},  # 缺少 name_code
        roster_entry("5102", combat=800),
        roster_entry("5103", combat=700),
        roster_entry("5104", combat=600),
    ]

    assert select_top_codes(characters, 3) == ["5102", "5103"]


def test_select_top_codes_dedupes_within_limit_without_backfill():
    """前 3 行内出现重复标识时只保留一个，也不向后补位。"""
    characters = [
        roster_entry("5101", combat=900),
        roster_entry("5101", combat=890),
        roster_entry("5102", combat=880),
        roster_entry("5103", combat=870),
    ]

    assert select_top_codes(characters, 3) == ["5101", "5102"]


@pytest.mark.asyncio
async def test_roster_missing_identity_preserves_other_displayed_characters():
    """缺标识行不查询，其他展示角色仍应正常查询。"""
    characters = [
        {"lv": 200, "combat": 900},
        roster_entry("5102", combat=800),
        roster_entry("5103", combat=700),
        roster_entry("5104", combat=600),
    ]
    details = {code: base_detail(code) for code in ("5102", "5103", "5104")}
    gateway = FakeGateway(characters, details)
    app = make_app(gateway)

    data = await app.roster("10001", directory_for(["5102", "5103", "5104"]))

    assert gateway.detail_calls == ["5102", "5103", "5104"]
    assert "" not in gateway.detail_calls
    assert len(gateway.detail_calls) <= 3
    assert set(data.option_summaries) == {"5102", "5103", "5104"}


@pytest.mark.asyncio
async def test_roster_empty_detail_object_is_unknown_not_no_options():
    """独立复核缺陷：{"detail": {}} 曾被误判为“无装备词条”且标记完整。"""
    characters = [roster_entry("5101", combat=900)]
    gateway = FakeGateway(characters, details={"5101": {"detail": {}}})
    app = make_app(gateway)

    data = await app.roster("10001", directory_for(["5101"]))
    summary = data.option_summaries["5101"]

    assert summary.status == "unknown"
    assert summary.message == "词条字段未识别"
    assert summary.status != "none"
    assert summary.complete is False
    # 未知绝不能伪装成 0 阶或“无词条”。
    assert summary.rows == ()
    assert summary.total == 0


@pytest.mark.asyncio
async def test_roster_all_equipment_fields_missing_are_unknown_not_none():
    """详情没有任何装备槽字段时只能是未知，不得当作“无词条”。"""
    characters = [roster_entry("5101", combat=900)]
    gateway = FakeGateway(
        characters, details={"5101": {"detail": {"name_code": "5101", "lv": 200}}}
    )
    app = make_app(gateway)

    data = await app.roster("10001", directory_for(["5101"]))
    summary = data.option_summaries["5101"]

    assert summary.status == "unknown"
    assert summary.message == "词条字段未识别"
    assert summary.complete is False


@pytest.mark.asyncio
async def test_roster_partial_equipment_fields_keep_known_rows_as_partial():
    """只缺部分装备槽字段时保留已知词条，但必须标记为不完整。"""
    characters = [roster_entry("5101", combat=900)]
    payload = base_detail("5101")
    for slot in ("torso", "arm", "leg"):
        payload["detail"].pop(f"{slot}_equip_tid", None)
        payload["detail"].pop(f"{slot}_equip_lv", None)
    gateway = FakeGateway(characters, details={"5101": payload})
    app = make_app(gateway)

    data = await app.roster("10001", directory_for(["5101"]))
    summary = data.option_summaries["5101"]

    assert summary.status == "partial"
    assert summary.message == "部分词条未识别"
    assert summary.complete is False
    assert summary.rows  # 已知的头部词条不得被丢弃


@pytest.mark.asyncio
async def test_roster_explicit_equipment_section_without_options_is_none():
    """只有上游明确返回四个装备槽且无词条时，才判定为“无装备词条”。"""
    characters = [roster_entry("5101", combat=900)]
    gateway = FakeGateway(characters, details={"5101": no_equipment_detail("5101")})
    app = make_app(gateway)

    data = await app.roster("10001", directory_for(["5101"]))
    summary = data.option_summaries["5101"]

    assert summary.status == "none"
    assert summary.message == "无装备词条"
    assert summary.complete is True


def test_option_summary_flags_missing_equipment_fields():
    """构建层必须把“是否返回装备槽字段”作为明确信号交给上层判定。"""
    builder = make_builder()

    empty = builder.option_summary(resource_id=470, payload={"detail": {}})
    present = builder.option_summary(
        resource_id=470, payload=no_equipment_detail("5101")
    )

    assert empty["equipment_present"] is False
    assert present["equipment_present"] is True


@pytest.mark.asyncio
async def test_roster_equipped_slots_all_option_fields_missing_is_unknown():
    """装备 ID 齐全但词条字段全缺且无有效词条 → 未知，绝不是“无词条”。"""
    characters = [roster_entry("5101", combat=900)]
    gateway = FakeGateway(
        characters, details={"5101": equipped_all_option_fields_missing("5101")}
    )
    app = make_app(gateway)

    data = await app.roster("10001", directory_for(["5101"]))
    summary = data.option_summaries["5101"]

    assert summary.status == "unknown"
    assert summary.message == "词条字段未识别"
    assert summary.complete is False
    assert summary.rows == ()
    assert summary.total == 0


@pytest.mark.asyncio
async def test_roster_equipped_slots_partial_option_fields_keep_known_rows():
    """装备 ID 齐全但词条字段部分缺失：保留已识别词条并标记为部分。"""
    characters = [roster_entry("5101", combat=900)]
    gateway = FakeGateway(
        characters, details={"5101": equipped_some_option_fields_missing("5101")}
    )
    app = make_app(gateway)

    data = await app.roster("10001", directory_for(["5101"]))
    summary = data.option_summaries["5101"]

    assert summary.status == "partial"
    assert summary.message == "部分词条未识别"
    assert summary.complete is False
    assert summary.rows  # 已识别词条不得被丢弃


@pytest.mark.asyncio
async def test_roster_equipped_slots_explicit_empty_option_fields_is_none():
    """装备 ID 齐全且词条字段明确为空（全 0）时才判定为“无词条”。"""
    characters = [roster_entry("5101", combat=900)]
    gateway = FakeGateway(
        characters, details={"5101": equipped_all_option_fields_empty("5101")}
    )
    app = make_app(gateway)

    data = await app.roster("10001", directory_for(["5101"]))
    summary = data.option_summaries["5101"]

    assert summary.status == "none"
    assert summary.message == "无装备词条"
    assert summary.complete is True


def test_option_summary_flags_incomplete_option_fields_for_equipped_slots():
    """构建层需区分“词条字段全缺/部分缺失/明确为空”三种信号。"""
    builder = make_builder()

    missing = builder.option_summary(
        resource_id=470, payload=equipped_all_option_fields_missing("5101")
    )
    some = builder.option_summary(
        resource_id=470, payload=equipped_some_option_fields_missing("5101")
    )
    empty = builder.option_summary(
        resource_id=470, payload=equipped_all_option_fields_empty("5101")
    )

    assert missing["equipment_present"] is True
    assert missing["options_fields_present"] is False
    assert some["equipment_present"] is True
    assert some["options_fields_present"] is False
    assert empty["equipment_present"] is True
    assert empty["options_fields_present"] is True


@pytest.mark.asyncio
async def test_every_displayed_character_has_three_merged_options_and_bounded_concurrency():
    import asyncio
    codes = [f"51{i:02d}" for i in range(20)]
    class ConcurrentGateway(FakeGateway):
        active = 0
        peak = 0
        async def get_character_detail(self, account, code):
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.sleep(0.001)
                return await super().get_character_detail(account, code)
            finally:
                self.active -= 1
    gateway = ConcurrentGateway(
        [roster_entry(c, combat=1000-i) for i,c in enumerate(codes)],
        {c: base_detail(c) for c in codes},
    )
    data = await make_app(gateway).roster("10001", directory_for(codes))
    payload = RosterT2IPayloadBuilder().build(data)
    assert gateway.peak == 3
    for row in payload["rows"]:
        assert row["options"] is not None
        assert len(row["options"]["rows"]) == 3
    assert len(data.option_summaries) == 20
    text = CharacterCommandHandler._format_roster(data)
    assert text.count("词条合计") == 20


def test_merged_tier_color_uses_average_not_sum():
    from types import SimpleNamespace
    from astrbot_plugin_nikke.features.character.replica import build_summary
    def summary(tiers):
        options = [SimpleNamespace(tier=t, unit="percent", raw_value=100, value=0.01,
                   effect_group_id="test",raw_type="attack",display_name="攻击") for t in tiers]
        data = SimpleNamespace(equipment={"head":SimpleNamespace(equipped=True,options=options)},
                               weapon_base_source=None)
        return build_summary(data)["rows"][0]
    assert summary([6,6,6])["semantic"] == "neutral"
    assert summary([12,13,14])["semantic"] == "high"
    assert summary([15,15])["semantic"] == "max"
    assert summary([15,None])["semantic"] == "neutral"

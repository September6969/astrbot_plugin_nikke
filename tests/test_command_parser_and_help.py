# SPDX-License-Identifier: GPL-3.0-or-later
"""PR-2：统一命令解析、#妮姬 插件级入口、凭据失效处理与帮助单一数据源。"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot_plugin_nikke.adapters.astrbot.command_parser import (
    HASH_PREFIX_PATTERN,
    normalize_nikke_prefix,
    parse_nikke_message,
)
from astrbot_plugin_nikke.application.commands.campaign import CampaignCommandHandler
from astrbot_plugin_nikke.application.commands.character import CharacterCommandHandler
from astrbot_plugin_nikke.application.commands.contracts import CommandContext
from astrbot_plugin_nikke.application.commands.errors import CREDENTIAL_EXPIRED_TEXT
from astrbot_plugin_nikke.application.commands.profile import ProfileCommandHandler
from astrbot_plugin_nikke.application.commands.raid import RaidCommandHandler
from astrbot_plugin_nikke.application.commands.help import help_category
from astrbot_plugin_nikke.features.account.errors import CredentialExpiredError
from astrbot_plugin_nikke.features.help.catalog import CATEGORY_ALIASES
from astrbot_plugin_nikke.main import NikkePlugin
from test_command_routing_contract import Event, _plugin_with_recorders

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ 解析器

@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("/妮姬 查询 练度 Red Hood", ("查询", "练度", "Red Hood")),
        ("妮姬 兑换 批量 A1 B2  C3", ("兑换", "批量", "A1 B2  C3")),
        ("#NIKKE character Rapi", ("character", "Rapi", "")),
        ("  /nikke  help ", ("help", "", "")),
        ("/妮姬 竞技场 三队导入\nA/B/C/D/E\nF/G/H/I/J\nK/L/M/N/O",
         ("竞技场", "三队导入", "A/B/C/D/E\nF/G/H/I/J\nK/L/M/N/O")),
        ("/妮姬", ("", "", "")),
    ],
)
def test_parse_keeps_tail_whitespace_and_newlines(message, expected) -> None:
    parsed = parse_nikke_message(message)
    assert parsed is not None
    assert (parsed.command, parsed.arg1, parsed.tail) == expected


@pytest.mark.parametrize("message", ["#妮姬我的", "/nikkeX 帮助", "妮姬们 你好", "#其他 命令", ""])
def test_parse_rejects_non_plugin_prefixes(message) -> None:
    assert parse_nikke_message(message) is None


def test_hash_pattern_only_matches_this_plugin() -> None:
    assert HASH_PREFIX_PATTERN.search("#妮姬 我的")
    assert HASH_PREFIX_PATTERN.search("  #NikKe help")
    assert HASH_PREFIX_PATTERN.search("#妮姬")
    for text in ("#妮姬我的", "/妮姬 我的", "#help", "妮姬 我的", "#nikkei"):
        assert not HASH_PREFIX_PATTERN.search(text), text


def test_normalize_prefix_no_longer_swallows_adjacent_text() -> None:
    assert normalize_nikke_prefix("#妮姬 突袭") == "/妮姬 突袭"
    assert normalize_nikke_prefix("#NIKKE raid") == "/nikke raid"
    assert normalize_nikke_prefix("#妮姬我的") == "#妮姬我的"


# ------------------------------------------------------------------ 原始消息尾参路由

class _RawEvent(Event):
    def __init__(self, message: str, *, woken: bool = True) -> None:
        self.message_str = message
        self.is_at_or_wake_command = woken


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "positional", "handler", "parameters"),
    [
        ("妮姬 查询 资料 Snow White", ("查询", "资料", "Snow", "White"), "character",
         {"operation": "info", "name": "Snow White"}),
        ("妮姬 日程 订阅 协同, 签到", ("日程", "订阅", "协同,", "签到"), "calendar",
         {"horizon": "订阅", "page": "协同, 签到"}),
        ("妮姬 日常 任务 自动 开", ("日常", "任务", "自动", "开"), "daily",
         {"action": "任务", "value": "自动 开"}),
        ("妮姬 兑换 批量\nAAA1\nBBB2", ("兑换", "批量", "AAA1", "BBB2"), "cdk",
         {"operation": "batch", "codes": "AAA1\nBBB2"}),
    ],
)
async def test_raw_message_tail_reaches_handlers(message, positional, handler, parameters) -> None:
    plugin, recorders = _plugin_with_recorders()
    replies = [item async for item in NikkePlugin.nikke(plugin, _RawEvent(message), *positional)]
    assert replies == [("plain", handler)]
    actual = dict(recorders[handler].contexts[-1].parameters)
    for key, value in parameters.items():
        assert actual[key] == value, actual


@pytest.mark.asyncio
async def test_positional_calls_without_message_merge_extra_argument() -> None:
    plugin, recorders = _plugin_with_recorders()
    replies = [item async for item in NikkePlugin.nikke(plugin, Event(), "日常", "任务", "自动", "开")]
    assert replies == [("plain", "daily")]
    assert recorders["daily"].contexts[-1].parameters["value"] == "自动 开"


# ------------------------------------------------------------------ #妮姬 插件级入口

@pytest.mark.asyncio
async def test_hash_entry_handles_unwoken_group_messages() -> None:
    plugin, recorders = _plugin_with_recorders()
    event = _RawEvent("#妮姬 查询 练度 Red Hood", woken=False)
    replies = [item async for item in NikkePlugin.nikke_hash_prefix(plugin, event)]
    assert replies == [("plain", "character")]
    assert recorders["character"].contexts[-1].parameters["name"] == "Red Hood"


@pytest.mark.asyncio
async def test_hash_entry_defers_to_command_handler_when_already_woken() -> None:
    plugin, recorders = _plugin_with_recorders()
    event = _RawEvent("#妮姬 我的", woken=True)
    assert [item async for item in NikkePlugin.nikke_hash_prefix(plugin, event)] == []
    assert not recorders["profile"].contexts


def test_plugin_no_longer_mutates_host_wake_prefix() -> None:
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    init = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )
    assert "wake_prefix" not in ast.unparse(init)
    assert "@filter.regex(HASH_PREFIX_PATTERN)" in source


# ------------------------------------------------------------------ AUD-009 凭据失效

def _context(name: str) -> CommandContext:
    operation = "overview" if name == "raid" else "character"
    return CommandContext(actor_id="qq-1", parameters={"stage": "1-1", "name": "Rapi", "operation": operation})


def _handlers(invalidated: list[str]):
    expired = AsyncMock(side_effect=CredentialExpiredError("账号凭据已失效，请重新绑定"))
    invalidate = invalidated.append
    account_reader = SimpleNamespace(get_account=lambda actor_id: {"qq_id": actor_id})
    return {
        "campaign": CampaignCommandHandler(
            application=SimpleNamespace(resolve=lambda query: object(), lookup=expired),
            present=AsyncMock(), invalidate_cookie=invalidate),
        "character": CharacterCommandHandler(
            application=SimpleNamespace(build_card=expired, roster=expired), directory=lambda: [],
            render_roster=AsyncMock(), render_card=AsyncMock(), invalidate_cookie=invalidate),
        "profile": ProfileCommandHandler(
            account_reader=account_reader, application=SimpleNamespace(build_dashboard=expired),
            present=AsyncMock(), invalidate_cookie=invalidate),
        "raid": RaidCommandHandler(
            application=SimpleNamespace(dashboard=expired), render_overview=AsyncMock(),
            render_ranking=AsyncMock(), invalidate_cookie=invalidate),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["campaign", "character", "profile", "raid"])
async def test_parent_credential_error_invalidates_and_hides_class_name(name) -> None:
    invalidated: list[str] = []
    handler = _handlers(invalidated)[name]
    result = await handler.handle(_context(name))
    text = " ".join(getattr(message, "text", "") for message in result.messages)
    assert text == CREDENTIAL_EXPIRED_TEXT
    assert "CredentialExpiredError" not in text
    assert invalidated == ["qq-1"]


def test_application_layer_no_longer_imports_blablalink_client() -> None:
    for path in (ROOT / "application" / "commands").glob("*.py"):
        assert "integrations.blablalink" not in path.read_text(encoding="utf-8"), path.name


# ------------------------------------------------------------------ AUD-027 / 帮助

@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_help_detail_follows_real_write_switch(enabled) -> None:
    plugin, _ = _plugin_with_recorders()
    plugin.config = {"enable_daily_actions": enabled}
    plugin.handlers.daily._extra_automation = object()
    plugin.handlers.account._session_handler = object()
    replies = [item async for item in plugin.nikke(Event(), "帮助", "详解", "")]
    index = replies[0][1]
    assert ("日常任务" in index) is enabled
    assert ("账号续期" in index) is enabled


def test_push_alias_points_to_account_category() -> None:
    assert CATEGORY_ALIASES["push"] == "账号"
    assert "汇总" in help_category("push", "test", include_admin=False)


def test_command_runtime_stays_well_below_size_gate() -> None:
    lines = (ROOT / "adapters" / "astrbot" / "command_runtime.py").read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 330

"""先验证非 Profile 入口能否收敛到 AstrBot 适配边界。"""

from __future__ import annotations

import ast
import inspect
import json
import shutil
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _plugin_methods() -> dict[str, ast.AsyncFunctionDef]:
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    plugin = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "NikkePlugin"
    )
    return {
        node.name: node
        for node in plugin.body
        if isinstance(node, ast.AsyncFunctionDef)
    }


def test_guide_and_tarot_entries_are_thin_adapter_delegates() -> None:
    methods = _plugin_methods()
    for name in ("guide", "tarot_command", "me"):
        method = methods[name]
        logical_statements = sum(isinstance(node, ast.stmt) for node in ast.walk(method))
        assert logical_statements <= 20, (name, logical_statements)
        called_attributes = {
            node.func.attr
            for node in ast.walk(method)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert "dispatch" in called_attributes, (name, called_attributes)


def test_application_command_handlers_do_not_import_astrbot() -> None:
    for relative in (
        "application/commands/contracts.py",
        "application/commands/guide.py",
        "application/commands/profile.py",
        "application/commands/tarot.py",
    ):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        imported_modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported_modules.append(node.module or "")
        assert not any(name == "astrbot" or name.startswith("astrbot.") for name in imported_modules), relative


@pytest.mark.asyncio
async def test_actual_registered_nikke_handler_dispatches_guide_and_tarot(tmp_path: Path) -> None:
    from astrbot.api.event import AstrMessageEvent
    from astrbot.api.message_components import Image, Plain
    from astrbot.core.message.message_event_result import MessageEventResult
    from astrbot.core.star.star_handler import star_handlers_registry

    from astrbot_plugin_nikke.features.tarot.service import TarotService
    from astrbot_plugin_nikke.adapters.astrbot.command_adapter import AstrBotCommandAdapter
    from astrbot_plugin_nikke.application.commands.guide import GuideCommandHandler
    from astrbot_plugin_nikke.features.guide.application import GuideApplication
    from astrbot_plugin_nikke.application.commands.profile import ProfileCommandHandler
    from astrbot_plugin_nikke.main import NikkePlugin

    class Event:
        def get_platform_name(self) -> str:
            return "fake-platform"

        def get_sender_id(self) -> str:
            return "fake-user"

        def is_admin(self) -> bool:
            return False

        def is_private_chat(self) -> bool:
            return True

        def plain_result(self, text: str) -> MessageEventResult:
            return AstrMessageEvent.plain_result(self, text)

        def image_result(self, path: str) -> MessageEventResult:
            return AstrMessageEvent.image_result(self, path)

    tarot_assets = tmp_path / "assets" / "tarot"
    tarot_assets.mkdir(parents=True)
    shutil.copy2(ROOT / "assets" / "tarot" / "tarot_cards.json", tarot_assets / "tarot_cards.json")
    guide_root = tmp_path / "assets" / "guides"
    guide_root.mkdir(parents=True)
    (guide_root / "guide.png").write_bytes(b"synthetic image fixture")
    (guide_root / "registry.json").write_text(
        json.dumps(
            [
                {
                    "id": "guide-fixture",
                    "category": "progression",
                    "title": "fixture guide",
                    "files": ["guide.png"],
                    "source": "synthetic",
                    "credit": "test",
                    "license": "self",
                    "updated_at": "2026-09-22",
                    "game_version": "test",
                }
            ]
        ),
        encoding="utf-8",
    )

    plugin = NikkePlugin.__new__(NikkePlugin)
    plugin.plugin_dir = tmp_path
    plugin.data_dir = tmp_path / "runtime"
    plugin.tarot = TarotService(tmp_path, plugin.data_dir / "tarot")
    plugin.guide_application = GuideApplication(guide_root)
    plugin.guide_command_handler = GuideCommandHandler(plugin.guide_application)

    class AccountReader:
        @staticmethod
        def get_account(qq_id):
            return {"qq_id": qq_id, "cookie": "synthetic-cookie"}

    class ProfileApplication:
        def __init__(self):
            self.calls = []

        async def build_dashboard(self, account):
            self.calls.append(account)
            return object()

    class ProfileRenderer:
        @staticmethod
        def render_profile(dashboard):
            return "synthetic-profile.png"

    async def no_t2i(page, dashboard):
        assert page == "profile"
        return None

    plugin.store = AccountReader()
    plugin.profile_application = ProfileApplication()
    plugin.profile_renderer = ProfileRenderer()
    plugin.feedback_manager = None
    plugin.command_adapter = AstrBotCommandAdapter()
    plugin._try_t2i = no_t2i
    plugin.profile_command_handler = ProfileCommandHandler(
        account_reader=plugin.store,
        application=plugin.profile_application,
        present=plugin._render_profile_dashboard,
    )
    registered = next(
        handler
        for handler in star_handlers_registry.get_handlers_by_module_name(
            NikkePlugin.__module__
        )
        if handler.handler_name == "nikke"
    )
    assert inspect.isasyncgenfunction(registered.handler)

    tarot_results = [
        result
        async for result in registered.handler(
            plugin, Event(), "塔罗", "帮助", ""
        )
    ]
    assert len(tarot_results) == 1
    assert isinstance(tarot_results[0], MessageEventResult)
    assert isinstance(tarot_results[0].chain[0], Plain)
    assert "【NIKKE 塔罗】" in tarot_results[0].get_plain_text()

    guide_results = [
        result
        async for result in registered.handler(
            plugin, Event(), "攻略", "练度", "1"
        )
    ]
    assert all(isinstance(result, MessageEventResult) for result in guide_results)
    components = [component for result in guide_results for component in result.chain]
    assert any(isinstance(component, Plain) and "第 1/1 页" in component.text for component in components)
    assert sum(isinstance(component, Image) for component in components) == 1

    profile_results = [
        result
        async for result in registered.handler(plugin, Event(), "我的", "", "")
    ]
    assert len(profile_results) == 1
    assert isinstance(profile_results[0], MessageEventResult)
    assert isinstance(profile_results[0].chain[0], Image)
    assert len(plugin.profile_application.calls) == 1


@pytest.mark.asyncio
async def test_real_astrbot_filters_adapter_context_and_message_types() -> None:
    from astrbot.api.event import AstrMessageEvent, filter
    from astrbot.api.message_components import Image, Plain
    from astrbot.core.message.message_event_result import MessageEventResult
    from astrbot.core.platform.message_type import MessageType
    from astrbot.core.star.filter.command import CommandFilter
    from astrbot.core.star.filter.event_message_type import EventMessageTypeFilter
    from astrbot.core.star.filter.permission import PermissionTypeFilter
    from astrbot.core.star.star_handler import star_handlers_registry

    from astrbot_plugin_nikke.adapters.astrbot.command_adapter import AstrBotCommandAdapter
    from astrbot_plugin_nikke.application.commands.contracts import (
        CommandContext,
        CommandResult,
        ImageReply,
        TextReply,
    )

    class Event:
        def __init__(self, *, admin: bool, message_type: MessageType):
            self.admin = admin
            self.message_type = message_type

        def get_platform_name(self) -> str:
            return "fake-platform"

        def get_sender_id(self) -> str:
            return "12345"

        def is_admin(self) -> bool:
            return self.admin

        def is_private_chat(self) -> bool:
            return self.message_type == MessageType.FRIEND_MESSAGE

        def get_message_type(self) -> MessageType:
            return self.message_type

        def plain_result(self, text: str) -> MessageEventResult:
            return AstrMessageEvent.plain_result(self, text)

        def image_result(self, path: str) -> MessageEventResult:
            return AstrMessageEvent.image_result(self, path)

    class Handler:
        async def handle(self, context: CommandContext) -> CommandResult:
            label = "admin" if context.is_admin else "member"
            return CommandResult(
                (
                    TextReply(
                        f"{label}:{context.platform_name}:{context.actor_id}:"
                        f"{context.parameters['probe']}"
                    ),
                    ImageReply("https://example.invalid/fixture.png"),
                )
            )

    adapter = AstrBotCommandAdapter()

    @filter.command("adapter-contract")
    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def registered_probe(event):
        async for result in adapter.dispatch(event, Handler(), probe="ok"):
            yield result

    metadata = star_handlers_registry.get_handler_by_full_name(
        f"{registered_probe.__module__}_{registered_probe.__name__}"
    )
    assert metadata is not None
    try:
        command_filter = next(item for item in metadata.event_filters if isinstance(item, CommandFilter))
        permission_filter = next(item for item in metadata.event_filters if isinstance(item, PermissionTypeFilter))
        message_filter = next(item for item in metadata.event_filters if isinstance(item, EventMessageTypeFilter))
        assert command_filter.command_name == "adapter-contract"
        assert permission_filter.permission_type == filter.PermissionType.ADMIN
        assert message_filter.event_message_type == filter.EventMessageType.GROUP_MESSAGE
        assert inspect.isasyncgenfunction(metadata.handler)

        group_event = Event(admin=True, message_type=MessageType.GROUP_MESSAGE)
        member_event = Event(admin=False, message_type=MessageType.GROUP_MESSAGE)
        private_event = Event(admin=True, message_type=MessageType.FRIEND_MESSAGE)
        assert permission_filter.filter(group_event, None)
        assert not permission_filter.filter(member_event, None)
        assert message_filter.filter(group_event, None)
        assert not message_filter.filter(private_event, None)

        results = [result async for result in metadata.handler(group_event)]
        assert len(results) == 2
        assert all(isinstance(result, MessageEventResult) for result in results)
        assert isinstance(results[0].chain[0], Plain)
        assert results[0].chain[0].text == "admin:fake-platform:12345:ok"
        assert isinstance(results[1].chain[0], Image)
    finally:
        star_handlers_registry.remove(metadata)


@pytest.mark.asyncio
async def test_adapter_rejects_untyped_business_response_fields() -> None:
    from astrbot.api.event import AstrMessageEvent

    from astrbot_plugin_nikke.adapters.astrbot.command_adapter import AstrBotCommandAdapter

    class Event:
        def plain_result(self, text: str):
            return AstrMessageEvent.plain_result(self, text)

        def image_result(self, path: str):
            return AstrMessageEvent.image_result(self, path)

    class InvalidHandler:
        async def handle(self, context):
            return {"success": True, "text": "不应由适配器猜字段"}

    with pytest.raises(TypeError, match="CommandResult"):
        [
            result
            async for result in AstrBotCommandAdapter().dispatch(
                Event(), InvalidHandler()
            )
        ]

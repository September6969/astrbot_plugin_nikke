from __future__ import annotations

import tempfile
from datetime import datetime, timezone
import ast
import inspect
import textwrap
from types import SimpleNamespace

import pytest

from astrbot_plugin_nikke.adapters.astrbot.command_adapter import AstrBotCommandAdapter
from astrbot_plugin_nikke.application.commands.announcement import (
    AnnouncementCommandHandler,
)
from astrbot_plugin_nikke.application.commands.contracts import CommandContext
from astrbot_plugin_nikke.core.storage import NikkeStore
from astrbot_plugin_nikke.features.announcement.application import AnnouncementApplication
from astrbot_plugin_nikke.features.announcement.delivery import AnnouncementDelivery
from astrbot_plugin_nikke.features.announcement.models import AnnouncementRecord
from astrbot_plugin_nikke.features.announcement.service import AnnouncementService
from astrbot_plugin_nikke.main import NikkePlugin


def _event(*, admin: bool, target: str):
    return SimpleNamespace(
        get_platform_name=lambda: "fake",
        get_sender_id=lambda: "actor-1",
        is_admin=lambda: admin,
        is_private_chat=lambda: False,
        plain_result=lambda text: text,
        unified_msg_origin=target,
    )


@pytest.mark.asyncio
async def test_non_admin_cannot_create_announcement_subscription():
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    announcements = AnnouncementService(clock=lambda: now)
    record = AnnouncementRecord(
        "item-1",
        "Official notice",
        "body",
        now.isoformat(),
    )
    announcements.add_or_update(record)

    with tempfile.TemporaryDirectory() as directory:
        delivery = AnnouncementDelivery(NikkeStore(directory))
        application = AnnouncementApplication(
            announcements=announcements,
            delivery=delivery,
        )
        handler = AnnouncementCommandHandler(
            application=application,
            push_enabled=lambda: False,
        )
        replies = [
            reply
            async for reply in AstrBotCommandAdapter().dispatch(
                _event(admin=False, target="fake:group:foreign"),
                handler,
                operation="subscribe",
                target="fake:group:foreign",
            )
        ]

        assert "仅机器人管理员" in replies[0]
        assert delivery.plan([record], now=now) == []


@pytest.mark.asyncio
async def test_unsupported_announcement_action_uses_the_shared_prompt():
    handler = AnnouncementCommandHandler(
        application=None,
        push_enabled=lambda: False,
    )

    result = await handler.handle(
        CommandContext(parameters={"operation": "unsupported"})
    )

    assert result.messages[0].text == "公告命令已简化，请使用：\n\n/妮姬 公告"


def test_announcement_runtime_routes_do_not_read_delivery_or_sync_state():
    from astrbot_plugin_nikke.adapters.astrbot.command_runtime import NikkeCommandRuntime

    forbidden = {
        "announcement_delivery",
        "sync_from_source",
        "format_announcements_text",
        "list_announcements",
        "subscribe",
        "unsubscribe",
        "record_count",
    }
    route_names = (
        "announcements_view",
        "announcement_deep_rescan",
        "announcement_subscription",
    )

    for name in route_names:
        method = getattr(NikkeCommandRuntime, name)
        tree = ast.parse(textwrap.dedent(inspect.getsource(method)))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        names.update(
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        )
        assert not (names & forbidden), f"{name} bypasses AnnouncementApplication"

    assert not hasattr(NikkePlugin, "_sync_announcements_background")
    assert not hasattr(NikkePlugin, "_dispatch_announcements")

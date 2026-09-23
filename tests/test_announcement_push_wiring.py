"""验证真实接线的开关和权限，发送器始终使用 mock。"""
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock
from astrbot_plugin_nikke.main import NikkePlugin
from astrbot_plugin_nikke.features.announcement.delivery import AnnouncementDelivery
from astrbot_plugin_nikke.features.announcement.application import AnnouncementApplication
from astrbot_plugin_nikke.features.announcement.models import AnnouncementRecord
from astrbot_plugin_nikke.features.announcement.service import AnnouncementService
from astrbot_plugin_nikke.application.commands.announcement import AnnouncementCommandHandler
from astrbot_plugin_nikke.core.storage import NikkeStore


class PushWiringTests(IsolatedAsyncioTestCase):
    async def test_default_disabled_does_not_call_sender(self):
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.config = {}
        plugin.context = SimpleNamespace(send_message=AsyncMock())
        await plugin._dispatch_announcements()
        plugin.context.send_message.assert_not_awaited()

    async def test_admin_subscription_uses_current_target(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = NikkePlugin.__new__(NikkePlugin)
            plugin.config = {}
            announcements = AnnouncementService()
            delivery = AnnouncementDelivery(NikkeStore(directory))
            application = AnnouncementApplication(
                announcements=announcements,
                delivery=delivery,
            )
            plugin.announcement_application = application
            plugin.announcement_command_handler = AnnouncementCommandHandler(
                application=application,
                push_enabled=lambda: bool(plugin.config.get("enable_announcement_push", False)),
            )
            event = SimpleNamespace(is_admin=lambda: False, unified_msg_origin="fake-session", plain_result=lambda x: x)
            result = [x async for x in plugin.nikke(event, "公告", "订阅")]
            self.assertIn("仅机器人管理员", result[0])
            now = datetime.now(timezone.utc)
            record = AnnouncementRecord("new", "新公告", "正文", now.isoformat())
            announcements.add_or_update(record)
            self.assertEqual(delivery.plan([record], now=now), [])
            event.is_admin = lambda: True
            result = [x async for x in plugin.nikke(event, "公告", "订阅")]
            self.assertIn("开关当前关闭", result[0])
            self.assertEqual(delivery.plan([record], now=now), [])
            later = datetime.now(timezone.utc)
            fresh = AnnouncementRecord("fresh", "更新公告", "正文", later.isoformat())
            announcements.add_or_update(fresh)
            self.assertEqual([item.target for item in delivery.plan([fresh], now=later)], ["fake-session"])
            await anext(plugin.announcement_subscription(event, "取消订阅"))
            self.assertEqual(delivery.plan([fresh], now=later), [])

    async def test_enabled_wiring_uses_injected_dispatch(self):
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.config = {"enable_announcement_push": True}
        plugin.context = SimpleNamespace(send_message=AsyncMock())
        async def dispatch_pushes(sender):
            self.assertTrue(await sender("fake-session", "synthetic"))
        plugin.announcement_application = SimpleNamespace(dispatch_pushes=dispatch_pushes)
        await plugin._dispatch_announcements()
        plugin.context.send_message.assert_awaited_once()

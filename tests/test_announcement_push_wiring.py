"""验证真实接线的开关和权限，发送器始终使用 mock。"""
import tempfile
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock
from astrbot_plugin_nikke.main import NikkePlugin
from astrbot_plugin_nikke.announcement_delivery import AnnouncementDelivery
from astrbot_plugin_nikke.announcement_service import AnnouncementService
from astrbot_plugin_nikke.storage import NikkeStore


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
            plugin.announcements = AnnouncementService()
            plugin.announcement_delivery = AnnouncementDelivery(NikkeStore(directory))
            event = SimpleNamespace(is_admin=lambda: False, unified_msg_origin="fake-session", plain_result=lambda x: x)
            result = [x async for x in plugin.nikke(event, "公告", "订阅")]
            self.assertIn("仅机器人管理员", result[0])
            self.assertEqual(plugin.announcement_delivery._state()["targets"], {})
            event.is_admin = lambda: True
            result = [x async for x in plugin.nikke(event, "公告", "订阅")]
            self.assertIn("开关当前关闭", result[0])
            self.assertIn("fake-session", plugin.announcement_delivery._state()["targets"])
            await anext(plugin.announcement_subscription(event, "取消订阅"))
            self.assertFalse(plugin.announcement_delivery._state()["targets"]["fake-session"]["enabled"])

    async def test_enabled_wiring_uses_injected_dispatch(self):
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.config = {"enable_announcement_push": True}
        plugin.announcements = AnnouncementService()
        plugin.context = SimpleNamespace(send_message=AsyncMock())
        async def dispatch(records, deadlines, sender):
            self.assertTrue(await sender("fake-session", "synthetic"))
        plugin.announcement_delivery = SimpleNamespace(dispatch=dispatch)
        await plugin._dispatch_announcements()
        plugin.context.send_message.assert_awaited_once()

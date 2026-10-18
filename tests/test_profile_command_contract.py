"""Profile 命令边界合同：只使用 fake，不访问真实账号或发送真实消息。"""

from __future__ import annotations
from plugin_fixtures import make_plugin_shell

import unittest
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, Mock

from astrbot_plugin_nikke.adapters.astrbot.command_adapter import AstrBotCommandAdapter
from astrbot_plugin_nikke.application.commands.profile import ProfileCommandHandler
from astrbot_plugin_nikke.features.profile.application import ProfileApplication
from astrbot_plugin_nikke.features.profile.models import CurrencyItem, ProfileDashboardData
from astrbot_plugin_nikke.integrations.blablalink.client import BlaBlaError, CookieExpired
from astrbot_plugin_nikke.main import NikkePlugin


@dataclass
class _FakeEvent:
    """提供 Profile 命令需要的最小事件能力。"""

    sender_id: str = "synthetic-qq"

    def get_sender_id(self) -> str:
        return self.sender_id

    @staticmethod
    def image_result(path: str) -> dict[str, str]:
        return {"kind": "image", "path": path}

    @staticmethod
    def plain_result(text: str) -> dict[str, str]:
        return {"kind": "plain", "text": text}


class _FakeStore:
    """记录查询和失效标记次数，防止测试只检查用户文案。"""

    def __init__(self, account: dict[str, Any] | None):
        self.account = account
        self.invalidated: list[str] = []
        self.lookup_ids: list[str] = []

    def get_account(self, qq_id: str, with_cookie: bool = True) -> dict[str, Any] | None:
        self.lookup_ids.append(qq_id)
        return self.account

    def mark_cookie_invalid(self, qq_id: str) -> None:
        self.invalidated.append(qq_id)


class _FakeClient:
    """可控的 dashboard 网关，默认只采集一次。"""

    def __init__(self, result: dict[str, Any] | None = None, error: Exception | None = None):
        self.result = result or {
            "basic": {"nickname": "合成指挥官"},
            "outpost": {},
            "roster": [],
            "outpost_available": True,
            "roster_available": True,
        }
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def get_profile_dashboard(self, account: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(account)
        if self.error is not None:
            raise self.error
        return self.result


class _FakeBuilder:
    """记录一次 DTO 构建，并返回稳定的最小 Profile 数据。"""

    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    def build(self, **kwargs: Any) -> ProfileDashboardData:
        self.calls.append(kwargs)
        return ProfileDashboardData(
            commander_name="合成指挥官",
            area_id="3",
            synchro_level=None,
            outpost_battle_level=None,
            normal_campaign=None,
            hard_campaign=None,
            character_count=None,
            max_level=None,
            max_combat=None,
            fetched_at=str(kwargs["fetched_at"]),
            plugin_version=str(kwargs["plugin_version"]),
        )


class _FakePresenter:
    """记录 T2I 展示端口调用而不产生真实文件。"""

    def __init__(self):
        self.calls: list[ProfileDashboardData] = []

    async def render_profile(self, dashboard: ProfileDashboardData) -> str:
        self.calls.append(dashboard)
        return "synthetic-profile.png"


class _FakeFeedbackHandle:
    def __init__(self):
        self.cancel_count = 0

    async def cancel(self) -> None:
        self.cancel_count += 1


class _FakeFeedbackManager:
    """不启动延迟任务，只验证入口最终释放 handle。"""

    def __init__(self):
        self.handles: list[_FakeFeedbackHandle] = []

    def start_delayed_feedback(self, callback):
        del callback
        handle = _FakeFeedbackHandle()
        self.handles.append(handle)
        return handle


def _plugin(*, account: dict[str, Any] | None, client: _FakeClient) -> tuple[NikkePlugin, _FakeStore, _FakeBuilder, _FakeRenderer, _FakeFeedbackManager]:
    """构造不触发容器、Web 服务或后台网络任务的插件门面。"""
    plugin = make_plugin_shell()
    store = _FakeStore(account)
    builder = _FakeBuilder()
    renderer = _FakePresenter()
    feedback = _FakeFeedbackManager()
    plugin.services.store = store
    plugin.services.profile_application = ProfileApplication(
        gateway=client,
        builder=builder,
        clock=lambda: datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc),
        plugin_version="test-version",
    )
    plugin.services.feedback_manager = feedback
    plugin.adapters.command = AstrBotCommandAdapter()
    plugin.handlers.profile = ProfileCommandHandler(
        account_reader=store,
        application=plugin.services.profile_application,
        present=plugin.presentation.render_profile,
        invalidate_cookie=store.mark_cookie_invalid,
        start_feedback=lambda _context, _message: feedback.start_delayed_feedback(
            lambda: None
        ),
    )
    return plugin, store, builder, renderer, feedback


class ProfileCommandContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_unbound_does_not_call_gateway_or_mark_cookie_and_cancels_feedback(self):
        client = _FakeClient()
        plugin, store, builder, renderer, feedback = _plugin(account=None, client=client)

        results = [item async for item in plugin.me(_FakeEvent())]

        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0]["text"],
            "查询失败：尚未绑定账号，请先私聊发送 /妮姬 账号 绑定",
        )
        self.assertEqual(client.calls, [])
        self.assertEqual(store.invalidated, [])
        self.assertEqual(builder.calls, [])
        self.assertEqual(renderer.calls, [])
        self.assertEqual(feedback.handles[0].cancel_count, 1)

    async def test_cookie_expired_marks_only_once_and_cancels_feedback(self):
        client = _FakeClient(error=CookieExpired("synthetic cookie expired", endpoint="profile"))
        plugin, store, builder, renderer, feedback = _plugin(
            account={"qq_id": "synthetic-qq", "cookie": "synthetic", "area_id": "3"},
            client=client,
        )

        results = [item async for item in plugin.me(_FakeEvent())]

        self.assertEqual(len(results), 1)
        self.assertIn("登录状态已失效", results[0]["text"])
        self.assertEqual(store.invalidated, ["synthetic-qq"])
        self.assertEqual(builder.calls, [])
        self.assertEqual(renderer.calls, [])
        self.assertEqual(feedback.handles[0].cancel_count, 1)

    async def test_gateway_failure_is_visible_without_cookie_invalidation(self):
        client = _FakeClient(error=BlaBlaError("synthetic upstream failure", endpoint="profile"))
        plugin, store, builder, renderer, feedback = _plugin(
            account={"qq_id": "synthetic-qq", "cookie": "synthetic", "area_id": "3"},
            client=client,
        )

        results = [item async for item in plugin.me(_FakeEvent())]

        self.assertEqual(len(results), 1)
        self.assertIn("查询失败", results[0]["text"])
        self.assertEqual(store.invalidated, [])
        self.assertEqual(builder.calls, [])
        self.assertEqual(renderer.calls, [])
        self.assertEqual(feedback.handles[0].cancel_count, 1)

    async def test_t2i_failure_falls_back_to_text_without_recollecting(self):
        client = _FakeClient()
        plugin, store, builder, renderer, feedback = _plugin(
            account={"qq_id": "synthetic-qq", "cookie": "synthetic", "area_id": "3"},
            client=client,
        )

        async def failed_t2i(page: str, dashboard: ProfileDashboardData):
            self.assertEqual(page, "profile")
            self.assertEqual(dashboard.commander_name, "合成指挥官")
            return None

        plugin.presentation.try_t2i = failed_t2i
        results = [item async for item in plugin.me(_FakeEvent())]

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["kind"], "plain")
        self.assertIn("个人资料 · 合成指挥官", results[0]["text"])
        self.assertIn("图片生成失败", results[0]["text"])
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(builder.calls), 1)
        self.assertEqual(len(renderer.calls), 0)
        self.assertEqual(store.invalidated, [])
        self.assertEqual(feedback.handles[0].cancel_count, 1)

    async def test_image_failure_text_fallback_keeps_missing_zero_and_unknown_resources(self):
        client = _FakeClient()
        plugin, _store, _builder, renderer, _feedback = _plugin(
            account={"qq_id": "synthetic-qq", "cookie": "synthetic", "area_id": "3"},
            client=client,
        )
        dashboard = ProfileDashboardData(
            commander_name="资源回退样例",
            area_id="3",
            synchro_level=None,
            outpost_battle_level=None,
            normal_campaign=None,
            hard_campaign=None,
            character_count=None,
            max_level=None,
            max_combat=None,
            fetched_at="2026-09-13 12:00",
            plugin_version="test-version",
            commander_level=382,
            team_combat=1_286_600,
            currencies=[
                CurrencyItem(99, 0, "珠宝", "gem", "0"),
                CurrencyItem(99001, 12_345, "未知资源", None, "12.3K"),
            ],
        )
        plugin.services.profile_application.build_dashboard = AsyncMock(
            return_value=dashboard
        )
        plugin.presentation.try_t2i = AsyncMock(return_value=None)

        results = [item async for item in plugin.me(_FakeEvent())]

        assert len(results) == 1
        text = results[0]["text"]
        assert "珠宝：0" in text
        assert "战斗数据辑：未返回" in text
        assert "未识别资源（类型 99001）：12,345" in text
        assert "图片生成失败" in text
        assert client.calls == []
        plugin.services.profile_application.build_dashboard.assert_awaited_once()
        plugin.presentation.try_t2i.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()

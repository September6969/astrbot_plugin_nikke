# SPDX-License-Identifier: GPL-3.0-or-later
"""宿主侧图片展示桥；只渲染已取得的 DTO，不触发领域查询。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.message_components import Image, Plain

from ...application.commands.contracts import CommandReply, ImageReply, TextReply
from ...features.daily.presentation import format_daily_summary_text
from ...ui.payloads.calendar import CalendarT2IPayloadBuilder
from ...ui.renderers import T2IRenderer


class AstrBotCommandPresentation:
    """聚合统一 T2I 展示，并保证 fallback 复用现有 DTO。"""

    def __init__(
        self,
        *,
        services: Any,
        html_render: Callable[[], Any],
        context: Any,
    ) -> None:
        self._services = services
        self._html_render = html_render
        self._context = context
        self._t2i_renderer: T2IRenderer | None = None
        self.calendar_payload_builder = CalendarT2IPayloadBuilder()

    async def try_t2i(self, page: str, data: Any, **kwargs: Any) -> str | list[str] | None:
        """所有图片页面统一尝试 T2I；失败信号由命令层用当前 DTO 回退。"""
        try:
            rendered = await self._renderer().render_view(page, data, **kwargs)
        except Exception as exc:
            logger.warning(
                "[NIKKE] %s T2I 失败，使用同一 DTO 文本回退: %s",
                page,
                type(exc).__name__,
            )
            return None
        if isinstance(rendered, str):
            return rendered if rendered.strip() else None
        if isinstance(rendered, (list, tuple)):
            paths = [
                path for path in rendered if isinstance(path, str) and path.strip()
            ]
            return paths or None
        return None

    async def render_profile(self, dashboard: Any) -> str | None:
        return await self.try_t2i("profile", dashboard)

    async def render_roster(self, data: Any) -> str | None:
        return await self.try_t2i("roster", data)

    async def render_character_card(self, card: Any) -> str | None:
        return await self.try_t2i("character", card)

    async def render_campaign_record(self, record: Any) -> str | None:
        try:
            path = await self._renderer().render_campaign_history(record)
        except Exception as exc:
            logger.warning(
                "[NIKKE] campaign T2I 失败，使用同一 DTO 文本回退: %s",
                type(exc).__name__,
            )
            return None
        return path if isinstance(path, str) and path.strip() else None

    async def render_raid_overview(self, data: Any) -> str | None:
        path = await self.try_t2i("union_overview", data)
        if path:
            return path
        return None

    async def render_raid_ranking(self, page: str, data: Any) -> str | None:
        return await self.try_t2i(page, data)

    async def send_daily_notice(self, target: str, text: str) -> Any:
        """向业务层确认过的本人私聊会话发送异常摘要。"""
        return await self._context.send_message(target, MessageChain([Plain(text)]))

    @staticmethod
    def format_daily_summary(results, *, scope: str) -> tuple[str, ...]:
        """用同一批结构化结果生成文本分页；不再经过图片渲染。"""
        return format_daily_summary_text(results, scope=scope)

    async def send_summary(self, target: str, replies: list[CommandReply] | tuple[CommandReply, ...]) -> None:
        """在原目标会话的一条消息链中发送所有摘要页或文本块。"""
        components = []
        for reply in replies:
            if isinstance(reply, ImageReply):
                components.append(Image.fromFileSystem(reply.path_or_url))
            elif isinstance(reply, TextReply):
                components.append(Plain(reply.text))
        if not components:
            return
        await self._context.send_message(
            target,
            MessageChain(components),
        )

    def _renderer(self) -> T2IRenderer:
        if self._t2i_renderer is None:
            self._t2i_renderer = T2IRenderer(
                html_render=self._html_render(),
                assets=self._services.asset_manager,
            )
        return self._t2i_renderer

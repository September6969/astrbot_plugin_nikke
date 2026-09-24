# SPDX-License-Identifier: GPL-3.0-or-later
"""宿主侧图片展示桥；只渲染已取得的 DTO，不触发领域查询。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any

from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.message_components import Image

from ...application.commands.character import CharacterRenderFailure
from ...ui.payloads.calendar import CalendarT2IPayloadBuilder
from ...ui.renderers import T2IRenderer


class AstrBotCommandPresentation:
    """聚合 T2I/Pillow 选择，并保证 fallback 复用现有 DTO。"""

    def __init__(
        self,
        *,
        services: Any,
        config: Callable[[], Mapping[str, Any]],
        html_render: Callable[[], Any],
        context: Any,
    ) -> None:
        self._services = services
        self._config = config
        self._html_render = html_render
        self._context = context
        self._t2i_renderer: T2IRenderer | None = None
        self.calendar_payload_builder = CalendarT2IPayloadBuilder()

    async def try_t2i(self, page: str, data: Any, **kwargs: Any) -> str | None:
        """普通页面失败时返回回退信号；单角色卡失败时显式报错。"""
        if page == "character":
            try:
                path = await self._renderer().render_view(page, data, **kwargs)
            except Exception as exc:
                logger.warning(
                    "[NIKKE] 单角色白色 replica 渲染失败: %s",
                    type(exc).__name__,
                )
                raise CharacterRenderFailure from exc
            if not isinstance(path, str) or not path.strip():
                raise CharacterRenderFailure
            return path
        if self._config().get("ui_renderer", "pillow") != "t2i":
            return None
        try:
            return await self._renderer().render_view(page, data, **kwargs)
        except Exception as exc:
            logger.warning(
                "[NIKKE] %s T2I 失败，使用已有数据回退: %s",
                page,
                type(exc).__name__,
            )
            return None

    async def render_profile(self, dashboard: Any) -> str:
        path = await self.try_t2i("profile", dashboard)
        if not path:
            path = await asyncio.to_thread(
                self._services.profile_renderer.render_profile, dashboard
            )
        return path

    async def render_roster(self, data: Any) -> str:
        return await asyncio.to_thread(
            self._services.renderer.render_roster,
            data.commander_name,
            data.characters,
            data.name_map,
        )

    async def render_character_card(self, card: Any) -> str:
        path = await self.try_t2i("character", card)
        if path is None:
            raise CharacterRenderFailure
        return path

    async def render_character_info(self, data: Any) -> str:
        return await asyncio.to_thread(
            self._services.renderer.render,
            data.name,
            data.title,
            data.rows,
        )

    async def render_campaign_record(self, record: Any) -> str:
        if self._config().get("ui_renderer", "pillow") == "t2i":
            try:
                path = await self._renderer().render_campaign_history(record)
                if path:
                    return path
            except Exception as exc:
                logger.warning(
                    "[NIKKE] Campaign T2I 失败，回退 Pillow: %s",
                    type(exc).__name__,
                )
        return await asyncio.to_thread(
            self._services.campaign_renderer.render_campaign_history,
            record,
        )

    async def render_raid_overview(self, data: Any) -> str:
        path = await self.try_t2i("union_overview", data)
        if path:
            return path
        return await asyncio.to_thread(
            self._services.raid_renderer.render_raid_overview,
            data,
        )

    async def render_raid_ranking(self, page: str, data: Any) -> str | None:
        return await self.try_t2i(page, data)

    async def send_summary_image(self, target: str, path: str) -> None:
        """在 AstrBot 宿主中发送已生成的汇总图片。"""
        await self._context.send_message(
            target,
            MessageChain([Image.fromFileSystem(path)]),
        )

    def _renderer(self) -> T2IRenderer:
        if self._t2i_renderer is None:
            self._t2i_renderer = T2IRenderer(
                html_render=self._html_render(),
                assets=self._services.asset_manager,
            )
        return self._t2i_renderer

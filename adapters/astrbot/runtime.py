# SPDX-License-Identifier: GPL-3.0-or-later
"""将应用服务接入 AstrBot，并把任务与清理交给统一运行时。"""

from __future__ import annotations

import asyncio
import json
import logging
import zipfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from astrbot.api.event import MessageChain
from astrbot.api.message_components import Plain

from ...core.lifecycle.coordinator import RuntimeCoordinator
from ...core.lifecycle.scheduler import RuntimeScheduler
from ...core.privacy import safe_exception_message

logger = logging.getLogger("astrbot_plugin_nikke.runtime")


class AstrBotRuntimeAdapter:
    """宿主生命周期、启动预热与周期任务的唯一 AstrBot 接入点。"""

    def __init__(
        self,
        *,
        coordinator: RuntimeCoordinator,
        services: Any,
        context: Any,
        plugin_dir: Path,
        config: dict[str, Any],
        web_host: str,
        web_port: int,
        run_daily: Callable[..., Awaitable[Any]],
        send_summary: Callable[[str], Awaitable[Any]],
        on_directory_loaded: Callable[[list[dict[str, Any]]], Any],
    ) -> None:
        self._coordinator = coordinator
        self._services = services
        self._context = context
        self._plugin_dir = plugin_dir
        self._config = config
        self._web_host = web_host
        self._web_port = web_port
        self._on_directory_loaded = on_directory_loaded
        self._register_cleanup()
        self.scheduler = RuntimeScheduler(
            coordinator=coordinator,
            store=services.store,
            config=config,
            run_daily=run_daily,
            send_summary=send_summary,
            sync_announcements=self._sync_announcements,
            sync_calendar=self._sync_calendar,
            dispatch_announcements=self._dispatch_announcements,
        )

    @property
    def closing(self) -> bool:
        return self._coordinator.closing

    def start(self) -> asyncio.Task:
        """委托协调器只启动一次初始化与调度循环。"""
        return self._coordinator.start(self._initialize_services, self.scheduler.run)

    async def close(self) -> None:
        """委托协调器取消后台工作并逆序关闭依赖。"""
        await self._coordinator.close()

    def request_calendar_refresh(self) -> asyncio.Task | None:
        """通过协调器登记命令触发的日程刷新。"""
        return self._coordinator.create_task(self._sync_calendar())

    async def send_delayed_notice(self, event: Any, text: str) -> None:
        """在宿主边界发送延迟提示，不向应用层泄漏 AstrBot 消息类型。"""
        try:
            target = getattr(event, "unified_msg_origin", None)
            sender = getattr(self._context, "send_message", None)
            if not self.closing and target and callable(sender):
                await sender(target, MessageChain([Plain(text)]))
        except Exception as exc:
            logger.debug("[NIKKE] 延迟提示发送跳过: %s", safe_exception_message(exc))

    def _register_cleanup(self) -> None:
        """按依赖创建顺序登记，协调器会以逆序执行。"""
        self._coordinator.register_cleanup("web", self._services.web.stop)
        self._coordinator.register_cleanup("assets", self._services.asset_manager.close)
        self._coordinator.register_cleanup(
            "voice", self._services.voice_application.close
        )
        self._coordinator.register_cleanup(
            "feedback", self._services.feedback_manager.close
        )

    async def _initialize_services(self) -> None:
        await self._best_effort(
            "浏览器扩展打包跳过",
            asyncio.to_thread(self._pack_extension),
            level="warning",
        )
        await self._best_effort(
            "塔层静态资料预热失败", self._services.tower_application.preload()
        )
        try:
            await self._services.web.start(self._web_host, self._web_port)
            logger.info(
                "[NIKKE] 绑定服务已监听 %s:%s", self._web_host, self._web_port
            )
        except Exception as exc:
            logger.error(
                "[NIKKE] 绑定服务启动失败: %s", safe_exception_message(exc)
            )
        try:
            directory = await self._services.client.get_directory()
            self._on_directory_loaded(directory)
            logger.info("[NIKKE] 已载入 %s 条妮姬目录", len(directory))
        except Exception as exc:
            logger.warning(
                "[NIKKE] 妮姬目录载入失败: %s", safe_exception_message(exc)
            )
        await self._best_effort(
            "L2D 索引预热跳过",
            asyncio.to_thread(
                self._services.asset_manager.nikke_db.get_l2d_index,
                allow_remote=True,
            ),
            level="debug",
        )
        try:
            await self._services.character_application.preload_stat_resources()
            logger.info("[NIKKE] Exia/NIKKE 静态属性表已载入并缓存")
        except Exception as exc:
            logger.warning(
                "[NIKKE] 静态属性表预热失败，角色卡将保留 —：%s",
                safe_exception_message(exc),
            )
    async def _best_effort(
        self,
        message: str,
        operation: Awaitable[Any],
        *,
        level: str = "warning",
    ) -> None:
        try:
            await operation
        except Exception as exc:
            log = getattr(logger, level)
            log("[NIKKE] %s: %s", message, safe_exception_message(exc))

    async def _sync_announcements(self) -> None:
        try:
            await self._services.announcement_application.sync_announcements()
        except Exception as exc:
            logger.debug(
                "[NIKKE] 后台公告同步跳过: %s", safe_exception_message(exc)
            )

    async def _sync_calendar(self) -> None:
        try:
            application = self._services.calendar_application
            if application is not None:
                await application.refresh_schedule()
        except Exception as exc:
            logger.debug("[NIKKE] 后台日程同步跳过: %s", safe_exception_message(exc))

    async def _dispatch_announcements(self) -> None:
        """沿用默认关闭及订阅目标限制，仅由周期调度器触发。"""
        if self.closing or not self._config.get("enable_announcement_push", False):
            return

        async def sender(target: str, text: str) -> bool:
            await asyncio.wait_for(
                self._context.send_message(target, MessageChain([Plain(text)])),
                timeout=10,
            )
            return True

        await self._services.announcement_application.dispatch_pushes(sender)

    def _pack_extension(self) -> None:
        """构建本地绑定扩展包，保留原有宿主权限策略。"""
        extension_dir = self._plugin_dir / "extension"
        with zipfile.ZipFile(
            self._services.extension_zip, "w", zipfile.ZIP_DEFLATED
        ) as archive:
            for path in extension_dir.rglob("*"):
                if not path.is_file():
                    continue
                if path.name == "manifest.json":
                    manifest = json.loads(path.read_text(encoding="utf-8"))
                    manifest["host_permissions"] = [
                        "https://*.blablalink.com/*",
                        self._services.web.site_origin + "/*",
                    ]
                    archive.writestr(
                        "manifest.json",
                        json.dumps(manifest, ensure_ascii=False, indent=2),
                    )
                else:
                    archive.write(path, path.relative_to(extension_dir))

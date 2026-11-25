# SPDX-License-Identifier: GPL-3.0-or-later
"""双入口 Web 服务（公共功能大厅 /hall 与指挥官工作台 /workspace）组合工厂。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from ...features.web_portal import PortalSessionStore
from ...integrations.web.hall_service import HallWebService
from ...integrations.web.portal_bridge import PortalHostBridge
from ...integrations.web.workspace_service import WorkspaceWebService


@dataclass(frozen=True)
class PortalResources:
    sessions: PortalSessionStore
    bridge: PortalHostBridge
    hall: HallWebService
    workspace: WorkspaceWebService
    public_base_url: str

    def hall_public_url(self) -> str:
        return self.hall.public_url()

    def create_hall_group_url(
        self, actor_id: str, conversation_id: str, group_label: str = ""
    ) -> str:
        return self.hall.create_group_link(actor_id, conversation_id, group_label)

    def create_workspace_url(
        self, actor_id: str, *, conversation_id: str = "", group_label: str = ""
    ) -> str:
        return self.workspace.create_link(
            actor_id, conversation_id=conversation_id, group_label=group_label
        )


def create_portal_resources(
    *,
    site_origin: str,
    store: Any,
    config: Mapping[str, Any],
    calendar: Any = None,
    announcements: Any = None,
    guide: Any = None,
    tower: Any = None,
    tarot: Any = None,
    toolbox: Any = None,
    profile_application: Any = None,
    character_application: Any = None,
    arena_application: Any = None,
    arena_web: Any = None,
    voice_application: Any = None,
    grid_resolver: Any = None,
    directory_provider: Callable[[], Any] | None = None,
    clock: Callable[[], Any] | None = None,
) -> PortalResources:
    sessions = PortalSessionStore()
    bridge = PortalHostBridge()
    flags = lambda: {
        "enable_arena": config.get("enable_arena") is True,
        "arena_web_enabled": config.get("arena_web_enabled") is True,
        "enable_daily_actions": config.get("enable_daily_actions") is True,
        "enable_cdk_redemption": config.get("enable_cdk_redemption") is True,
        "enable_announcement_push": config.get("enable_announcement_push") is True,
        "counsel_available": bool(getattr(getattr(toolbox, "counsel", None), "available", False)),
    }
    hall = HallWebService(
        site_origin=site_origin,
        sessions=sessions,
        bridge=bridge,
        feature_flags=flags,
        calendar=calendar,
        announcements=announcements,
        guide=guide,
        tower=tower,
        tarot=tarot,
        toolbox=toolbox,
        grid_resolver=grid_resolver,
        clock=clock,
    )
    workspace = WorkspaceWebService(
        site_origin=site_origin,
        sessions=sessions,
        bridge=bridge,
        store=store,
        feature_flags=flags,
        profile_application=profile_application,
        character_application=character_application,
        toolbox=toolbox,
        arena_application=arena_application,
        arena_web=arena_web,
        voice_application=voice_application,
        directory_provider=directory_provider,
        clock=clock,
    )
    return PortalResources(
        sessions=sessions,
        bridge=bridge,
        hall=hall,
        workspace=workspace,
        public_base_url=site_origin.rstrip("/"),
    )


__all__ = ["PortalResources", "create_portal_resources"]

# SPDX-License-Identifier: GPL-3.0-or-later
"""角色展示计算所需的轻量身份端口。"""

from __future__ import annotations

from typing import Protocol


class CharacterRenderIdentity(Protocol):
    """把角色与服装身份映射到已核验渲染资源键。"""

    def resolve_render_id(
        self, resource_id: int | str, costume_id: int | str | None = None
    ) -> str:
        """返回规范资源 ID；无法确认时返回实现定义的缺失标记。"""

    def resolve_character_id(
        self, resource_id: int | str, costume_id: int | str | None = None
    ) -> str:
        """返回角色级身份，用于应用角色级展示配置。"""

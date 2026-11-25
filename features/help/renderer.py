# SPDX-License-Identifier: GPL-3.0-or-later
"""渲染无需账号和网络的 QQ 帮助。"""

from .catalog import ALIASES, CATEGORIES, CATEGORY_ALIASES, LEGACY_CATEGORIES, TOPICS, Topic


def _visible_topics(*, include_admin: bool, arena: Topic | None = None,
                    unavailable: set[str] | None = None) -> dict[str, Topic]:
    return {item.name: item for item in TOPICS + ((arena,) if arena else ())
            if (include_admin or not item.admin) and item.name not in (unavailable or set())}


def _commands(item: Topic, visible: dict[str, Topic]) -> list[str]:
    return [f"/妮姬 {command}" for command in item.commands
            if not command.startswith("帮助 详解 ")
            or command.removeprefix("帮助 详解 ") in visible]


def detail(topic: str, *, include_admin: bool, arena: Topic | None = None,
           unavailable: set[str] | None = None) -> str:
    visible = _visible_topics(include_admin=include_admin, arena=arena, unavailable=unavailable)
    name = ALIASES.get(topic.strip().casefold(), topic.strip())
    selected = visible.get(name)
    if selected:
        lines = [f"【{selected.name}详解】", selected.purpose, ""]
        lines.extend(_commands(selected, visible))
        if selected.note:
            lines.extend(("", selected.note))
        return "\n".join(lines)
    index = "【功能详解】\n" + "｜".join(visible) + "\n\n例如 /妮姬 帮助 详解 日程"
    return f"没有这个可用的教学主题。\n\n{index}" if name else index


def category(name: str, *, include_admin: bool, arena: Topic | None = None,
             unavailable: set[str] | None = None) -> str | None:
    """分类帮助；未知分类返回 None，由调用方回到主菜单。"""
    selected = CATEGORY_ALIASES.get(name.strip().casefold(), name.strip())
    group = next((item for item in CATEGORIES + LEGACY_CATEGORIES if item.name == selected), None)
    if group is None:
        return None
    if selected == "管理" and not include_admin:
        return "管理指令仅对管理员显示。"
    visible = _visible_topics(include_admin=include_admin, arena=arena, unavailable=unavailable)
    topics = [visible[key] for key in group.topics if key in visible]
    if not topics:
        return "该分类当前未启用。发送 /妮姬 帮助 查看可用功能。"
    lines = [f"【{'管理员' if selected == '管理' else selected}】", group.summary]
    for item in topics:
        lines.extend(("", f"· {item.name}：{item.purpose}"))
        lines.extend(command for command in _commands(item, visible)
                     if not command.startswith("/妮姬 帮助 详解 "))
        lines.append(f"教程：/妮姬 帮助 详解 {item.name}")
    lines.extend(("", "发送 /妮姬 帮助 查看主菜单。"))
    return "\n".join(lines)


def home(version: str, *, include_admin: bool, arena: bool = False) -> str:
    lines = [f"NIKKE 综合助手 {version}", "", "发送 /妮姬 帮助 分类名 查看命令："]
    lines.extend(f"{item.name} — {item.summary}" for item in CATEGORIES
                 if (item.name != "管理" or include_admin) and (item.name != "竞技场" or arena))
    lines.extend(("", "快捷：/妮姬 大厅｜/妮姬 工作台｜/妮姬 日程",
                  "新手：/妮姬 帮助 详解 入门"))
    return "\n".join(lines)

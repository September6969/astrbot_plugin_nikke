# SPDX-License-Identifier: GPL-3.0-or-later
"""渲染无需账号和网络的 QQ 帮助。"""

from .catalog import ALIASES, TOPICS, Topic


def detail(topic: str, *, include_admin: bool, arena: Topic | None = None,
           unavailable: set[str] | None = None) -> str:
    topics = TOPICS + ((arena,) if arena else ())
    unavailable = unavailable or set()
    visible = {item.name: item for item in topics
               if (include_admin or not item.admin) and item.name not in unavailable}
    name = ALIASES.get(topic.strip().casefold(), topic.strip())
    selected = visible.get(name)
    if selected:
        lines = [f"【{selected.name}详解】", selected.purpose, ""]
        lines.extend(f"/妮姬 {command}" for command in selected.commands
                     if command.removeprefix("帮助 详解 ") not in unavailable)
        if selected.note:
            lines.extend(("", selected.note))
        return "\n".join(lines)
    index = "【功能详解】\n" + "｜".join(visible) + "\n\n例如 /妮姬 帮助 详解 日程"
    return f"没有这个可用的教学主题。\n\n{index}" if name else index


def home(version: str, *, include_admin: bool, arena: bool = False) -> str:
    categories = "账号｜查询｜日常" + ("｜管理" if include_admin else "")
    lines = [
        f"NIKKE 综合助手 {version}", "",
        "/妮姬 日程　查看近期活动",
        "/妮姬 攻略　浏览攻略分类",
        "/妮姬 我的　查看个人进度", "",
        f"分类帮助 /妮姬 帮助 <{categories}>",
        "新手教程 /妮姬 帮助 详解 入门",
    ]
    if arena:
        lines.append("竞技场 /妮姬 帮助 详解 竞技场")
    return "\n".join(lines)

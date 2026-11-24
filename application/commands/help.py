"""为宿主路由提供静态帮助展示与发布门禁。"""

from ...features.help.catalog import Topic
from ...features.help.renderer import category, detail, home


def _arena_topic(enabled: bool, web_enabled: bool) -> Topic | None:
    if not enabled:
        return None
    commands = ("竞技场 帮助", "竞技场 解队 <五人>", "竞技场 沙盒 <五人>",
                "竞技场 数据状态", "竞技场 我的")
    if web_enabled:
        commands += ("竞技场 编辑", "竞技场 三队", "竞技场 结果")
    return Topic("竞技场", "按 P1–P5 输入敌方五人进行离线分析。", commands,
                 "群聊使用公开沙盒；私聊持有过滤需要已确认角色库。网页入口仅限私聊。")


def _unavailable(community_enabled: bool, renewal_enabled: bool) -> set[str]:
    return {name for name, enabled in (("日常任务", community_enabled),
                                       ("账号续期", renewal_enabled)) if not enabled}


def help_home(version: str, *, include_admin: bool, arena: bool = False) -> str:
    return home(version, include_admin=include_admin, arena=arena)


def help_category(name: str, version: str, *, include_admin: bool, arena: bool = False,
                  web_enabled: bool = False, community_enabled: bool = False,
                  renewal_enabled: bool = False) -> str:
    return category(name, include_admin=include_admin, arena=_arena_topic(arena, web_enabled),
                    unavailable=_unavailable(community_enabled, renewal_enabled)) or home(
        version, include_admin=include_admin, arena=arena
    )


def help_detail(topic: str, *, include_admin: bool, arena_enabled: bool, web_enabled: bool,
                community_enabled: bool, renewal_enabled: bool) -> str:
    return detail(topic, include_admin=include_admin, arena=_arena_topic(arena_enabled, web_enabled),
                  unavailable=_unavailable(community_enabled, renewal_enabled))

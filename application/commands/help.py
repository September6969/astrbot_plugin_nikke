"""为宿主路由提供静态帮助展示与发布门禁。"""

from ...features.help.catalog import Topic
from ...features.help.renderer import detail, home


def help_home(version: str, *, include_admin: bool, arena: bool = False) -> str:
    return home(version, include_admin=include_admin, arena=arena)


def help_detail(topic: str, *, include_admin: bool, arena_enabled: bool, web_enabled: bool,
                community_enabled: bool, renewal_enabled: bool) -> str:
    arena = None
    if arena_enabled:
        commands = ("竞技场 帮助", "竞技场 数据状态", "竞技场 我的")
        if web_enabled:
            commands += ("竞技场 编辑", "竞技场 三队", "竞技场 结果")
        arena = Topic("竞技场", "按 P1–P5 粘贴敌方五人进行离线分析。", commands)
    unavailable = set()
    if not community_enabled:
        unavailable.add("日常任务")
    if not renewal_enabled:
        unavailable.add("账号续期")
    return detail(topic, include_admin=include_admin, arena=arena, unavailable=unavailable)

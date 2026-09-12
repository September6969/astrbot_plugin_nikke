"""循环研究 ID 映射，官网 QueryKeys 与公开静态表交叉确认。"""

# 来源与固定快照见 docs/evidence/overnight.md，未知 ID 不推断名称。
RESEARCH_TYPES = {
    "1001": ("General", "Personal"),
    "1101": ("Attacker", "Class"),
    "1102": ("Defender", "Class"),
    "1103": ("Supporter", "Class"),
    "1201": ("Elysion", "Corporation"),
    "1202": ("Missilis", "Corporation"),
    "1203": ("Tetra", "Corporation"),
    "1204": ("Pilgrim", "Corporation"),
    "1205": ("Abnormal", "Corporation"),
}

RESEARCH_PRESENTATION_NAMES = {
    "general": "通用研究",
    "attacker": "火力型",
    "defender": "防御型",
    "supporter": "辅助型",
    "elysion": "极乐净土",
    "missilis": "米西里斯",
    "tetra": "泰特拉",
    "pilgrim": "朝圣者",
    "abnormal": "反常",
}


def research_labels(tid):
    return RESEARCH_TYPES.get(str(tid), (None, None))


def research_presentation_label(tid):
    """把已确认的内部研究名转换为 UI 文案；未知 ID 不猜测。"""
    display_name, _ = research_labels(tid)
    return RESEARCH_PRESENTATION_NAMES.get(str(display_name or "").casefold())

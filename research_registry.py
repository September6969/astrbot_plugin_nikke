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


RESEARCH_ZH_NAMES = {
    "General": "通用研究",
    "Attacker": "火力型",
    "Defender": "防御型",
    "Supporter": "辅助型",
    "Elysion": "极乐净土",
    "Missilis": "米西里斯",
    "Tetra": "泰特拉",
    "Pilgrim": "朝圣者",
    "Abnormal": "反常",
}

RESEARCH_ZH_CATEGORIES = {
    "Personal": "通用",
    "Class": "职业",
    "Corporation": "企业",
}


def research_labels(tid):
    return RESEARCH_TYPES.get(str(tid), (None, None))


def research_zh_name(display_name: str | None) -> str | None:
    if not display_name:
        return None
    return RESEARCH_ZH_NAMES.get(display_name, display_name)

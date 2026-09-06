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


def research_labels(tid):
    return RESEARCH_TYPES.get(str(tid), (None, None))

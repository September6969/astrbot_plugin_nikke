"""联盟贡献卡：范围内排名，不根据昵称推断出刀。"""
from ...features.raid.experience import scope_label
from .common import display_number


def _share_fields(damage, total):
    ratio = damage / total if total > 0 else None
    return {
        "share": f"{ratio:.1%}" if ratio is not None else "—",
        "share_ratio": ratio,
        "share_bar": round(ratio * 100, 2) if ratio is not None else None,
    }


class UnionRecordsT2IPayloadBuilder:
    def build(self, data, union_members=None, **kwargs):
        total = data.total_damage or sum(p.total_damage for p in data.participants)
        status = data.attendance_status
        no_attack = {"status": status, "count": len(data.unattacked) if status != "UNKNOWN" else None,
            "label": {"UNKNOWN": "当前数据无法确认", "ALL_ATTACKED": "全员已有记录", "HAS_UNATTACKED": "已确认未出刀"}[status],
            "detail": "需要同一赛季及游戏日的完整成员名单与攻击记录" if status == "UNKNOWN" else "仅适用于已确认的完整范围",
            "members": data.unattacked}
        return {"scope": scope_label(data), "guild": data.guild_name, "updated": data.fetched_at,
            "page": data.page, "pages": data.total_pages, "total_damage": "未知" if data.incomplete and not data.total_records else display_number(total),
            "excluded": data.excluded_records, "incomplete": data.incomplete,
            "rows": [{"rank": str(p.rank), "nickname": p.nickname, "damage": display_number(p.total_damage),
                **_share_fields(p.total_damage, total), "records": str(len(p.attacks))}
                for p in data.participants], "no_attack": no_attack,
            "canvas": {"width": 1080, "height": 800}}

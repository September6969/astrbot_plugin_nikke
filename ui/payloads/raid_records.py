"""联盟突袭排名卡片的展示数据组装。"""


class UnionRecordsT2IPayloadBuilder:
    def build(self, data, union_members=None, **kwargs):
        from astrbot_plugin_nikke.ui.t2i_payloads import display_number

        if union_members is None:
            union_members = getattr(data, "union_members", None)
        if union_members is None and isinstance(data, dict):
            union_members = data.get("union_members") or data.get("guild_members")
        participants = getattr(data, "participants", None)
        if participants is None and isinstance(data, dict):
            participants = data.get("participants", [])
        participants = participants or []
        attacked_nicknames = {
            item.nickname for item in participants if hasattr(item, "nickname")
        }

        if union_members is None:
            no_attack = {
                "status": "UNKNOWN",
                "count": None,
                "label": "无法确认",
                "detail": "缺少全员名单数据，无法确认",
                "members": [],
            }
        else:
            clean_members = []
            for member in union_members:
                if isinstance(member, str) and member.strip():
                    clean_members.append(member.strip())
                elif isinstance(member, dict) and member.get("nickname"):
                    clean_members.append(str(member["nickname"]).strip())
            unattacked = [
                name for name in clean_members if name not in attacked_nicknames
            ]
            if not unattacked:
                no_attack = {
                    "status": "ALL_ATTACKED",
                    "count": 0,
                    "label": "全员已出刀",
                    "detail": "当前已知联盟成员均已有出刀记录",
                    "members": [],
                }
            else:
                no_attack = {
                    "status": "HAS_UNATTACKED",
                    "count": len(unattacked),
                    "label": f"未出刀 {len(unattacked)} 人",
                    "detail": "",
                    "members": unattacked,
                }
        return {
            "scope": (
                getattr(data, "scope", "CURRENT_RESPONSE")
                if not isinstance(data, dict)
                else data.get("scope", "CURRENT_RESPONSE")
            ),
            "rows": [
                {
                    "rank": str(item.rank),
                    "nickname": item.nickname,
                    "damage": display_number(item.total_damage),
                    "records": str(len(item.attacks)),
                }
                for item in participants
            ],
            "no_attack": no_attack,
        }

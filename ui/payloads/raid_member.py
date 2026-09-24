"""联盟突袭个人报告卡片的展示数据组装。"""


class UnionMemberT2IPayloadBuilder:
    def __init__(self, assets, resolver):
        self.assets, self.resolver = assets, resolver

    def build(self, data):
        from astrbot_plugin_nikke.features.campaign.models import StageClearMember
        from astrbot_plugin_nikke.features.character.master_resolver import CharacterMasterResolver
        from astrbot_plugin_nikke.ui.payloads.common import boss_presentation, display_number

        if data.scope != "CURRENT_RESPONSE_MEMBER":
            raise ValueError("个人报告要求明确的当前成员响应范围")
        master = CharacterMasterResolver()
        participants = []
        for participant in data.participants:
            rows = []
            for index, attack in enumerate(participant.attacks, 1):
                members = []
                for member in sorted(attack.squad, key=lambda item: item.slot):
                    canonical = master.resolve_battle_tid(member.tid)
                    name = canonical.name_cn if canonical else "身份未确认"
                    source = None
                    if canonical:
                        identity = StageClearMember(
                            tid=int(member.tid),
                            level=member.level,
                            combat=member.combat,
                            slot=member.slot,
                            name_cn=name,
                            resource_id=str(canonical.resource_id),
                            name_code=canonical.name_code,
                            costume_id=member.costume_id,
                        )
                        try:
                            source = self.assets.get_lineup_portrait(identity)
                        except Exception:
                            pass
                    members.append(
                        {
                            "name": name,
                            "level": f"LV.{member.level}",
                            "combat": display_number(member.combat),
                            "slot": str(member.slot),
                            "long_name": len(name) > 22,
                            "portrait_data_uri": self.resolver.encode(source),
                        }
                    )
                boss = boss_presentation(self.assets, self.resolver, attack.boss_id)
                rows.append(
                    {
                        **boss,
                        "label": f"RECORD {index:02}",
                        "boss": boss["name"],
                        "day": str(attack.day),
                        "difficulty": str(attack.difficulty),
                        "level": str(attack.level),
                        "step": str(attack.step),
                        "final_hit": attack.is_final_hit,
                        "damage": display_number(attack.total_damage),
                        "members": members,
                    }
                )
            participants.append(
                {
                    "name": participant.nickname,
                    "damage": display_number(participant.total_damage),
                    "returned": str(len(participant.attacks)),
                    "rows": rows,
                }
            )
        return {"scope": data.scope, "participants": participants}

"""战役历史卡片的独立 T2I payload 投影。"""

from ...features.campaign.models import ClearLineupStatus, StageClearRecord
from ..t2i_assets import T2IAssetResolver


class CampaignT2IPayloadBuilder:
    def __init__(self, assets, resolver: T2IAssetResolver):
        self.assets = assets
        self.resolver = resolver

    def build(self, record: StageClearRecord) -> dict:
        if len(record.commander_name) > 80:
            raise ValueError("指挥官名称超出单页可读范围，使用备用渲染器")
        available = record.status == ClearLineupStatus.AVAILABLE
        if available and sorted(member.slot for member in record.members) != [1, 2, 3, 4, 5]:
            raise ValueError("可用阵容必须包含五个唯一位置")
        members = []
        if available:
            for member in sorted(record.members, key=lambda item: item.slot):
                source = None
                try:
                    if member.resource_id is not None and member.name_code is not None:
                        source = self.assets.get_lineup_portrait(member)
                except Exception:
                    # 单张资产不可用时保留真实数据，不影响其余阵容。
                    pass
                name = member.name_cn or member.name_en or "身份未确认"
                if name == f"NIKKE {member.tid}":
                    name = "身份未确认"
                if len(name) > 36 or len(str(member.combat)) > 9:
                    raise ValueError("文本超出单页可读范围，使用备用渲染器")
                members.append(
                    {
                        "name": name,
                        "slot": str(member.slot),
                        "long_name": len(name) > 22,
                        "level": f"LV.{member.level}",
                        "combat": f"{member.combat:,}",
                        "portrait_data_uri": self.resolver.encode(source),
                    }
                )
        labels = {
            ClearLineupStatus.AVAILABLE: "历史阵容",
            ClearLineupStatus.UNAVAILABLE: "暂无可查询阵容",
            ClearLineupStatus.RATE_LIMITED: "请求过频",
            ClearLineupStatus.ERROR: "查询不可用",
        }
        return {
            "mode": record.mode if record.mode in ("NORMAL", "HARD") else "UNKNOWN",
            "stage": record.stage_name,
            "available": available,
            "members": members,
            "total_combat": f"{record.total_combat:,}" if available else "—",
            "status": labels[record.status],
            "status_message": record.status_message,
            "commander": record.commander_name,
            "updated": record.fetched_at,
            "version": record.plugin_version,
            "portrait_notice": (
                "头像暂不可用"
                if available and all(not member["portrait_data_uri"] for member in members)
                else "部分头像不可用"
                if any(not member["portrait_data_uri"] for member in members)
                else ""
            ),
        }

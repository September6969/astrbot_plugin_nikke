"""只适配已经建立的领域 DTO，不解析接口或推断身份。"""
from .payloads.profile import ProfileT2IPayloadBuilder, format_compact_number, section_state
# 兼容历史导入路径；实现归属 ui.payloads.campaign。
from .payloads.campaign import CampaignT2IPayloadBuilder
# 兼容历史导入路径；Calendar payload 与分页实现在 ui.payloads.calendar。
from .payloads.calendar import CalendarT2IPayloadBuilder


def display_number(value):
    return "Unknown" if value is None else f"{value:,}"


def display_remaining(value, now=None):
    """只格式化有明确时区的时间；不猜测服务器时间单位或时区。"""
    from datetime import datetime, timezone
    if not value:
        return "Unknown"
    try:
        end = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if end.tzinfo is None:
            return "Unknown"
        seconds = (end - (now or datetime.now(timezone.utc))).total_seconds()
        if seconds <= 0:
            return "已结束"
        minutes = max(1, int(seconds // 60))
        return f"{minutes // 1440}天 {minutes % 1440 // 60}小时" if minutes >= 1440 else f"{minutes // 60}小时 {minutes % 60}分钟"
    except (ValueError, TypeError):
        return "Unknown"


def boss_presentation(assets, resolver, boss_id, icon_id=None, monster_model_id=None, name=None):
    """只消费既有 Boss 解析结果；未确认身份或损坏资产不冒充已解析。"""
    result = {"name": name or f"Boss ID {boss_id}", "boss_image_data_uri": None,
              "asset_state": "UNRESOLVED", "is_fallback": True}
    if assets is None:
        return result
    try:
        asset = assets.resolve_boss_asset(boss_id=boss_id, icon_id=icon_id, monster_model_id=monster_model_id, boss_name=name)
        if not asset.is_fallback:
            image = resolver.encode(asset.local_path, (256, 192))
            if image:
                result.update(name=asset.boss_name or result["name"], boss_image_data_uri=image, asset_state="resolved", is_fallback=False)
    except Exception:
        pass
    return result

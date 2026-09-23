"""Profile 页面表现 payload；只消费已准备的领域数据和本地资产。"""

from astrbot_plugin_nikke.ui.t2i_assets import T2IAssetResolver
from .common import display_number, format_compact_number


def section_state(available=None, partial=False, items=None):
    """保留 Profile payload 的可用、部分、空和未知状态语义。"""
    if available is False:
        return "UNAVAILABLE"
    if partial:
        return "PARTIAL"
    if items == []:
        return "EMPTY"
    return "AVAILABLE" if available is True or items is not None else "UNKNOWN"


class ProfileT2IPayloadBuilder:
    """把 Profile DTO 与已准备资产转换成模板所需 payload。"""

    def __init__(self, assets=None, resolver=None):
        self.assets = assets
        self.resolver = resolver or T2IAssetResolver()

    def build(self, data):
        from ...features.profile.currency_registry import CurrencyRegistry

        def pairs(items, state=""):
            return [{"label": label, "value": "Unknown" if value is None else str(value), "scope": state}
                    for label, value in items]

        today_state = section_state(data.daily_available, data.daily_partial)
        today = pairs([(label, display_number(getattr(data, field))) for label, field in
                       (("拦截剩余", "intercept_remaining"), ("新人竞技场剩余", "rookie_arena_remaining"),
                        ("特殊竞技场剩余", "special_arena_remaining"), ("咨询剩余", "counsel_remaining"),
                        ("派遣完成", "dispatch_completed"), ("派遣进行中", "dispatch_in_progress"))], today_state)
        ratio = data.storage_fullness
        storage = {"value": f"{ratio:.1%}" if ratio is not None else "Unknown", "bar": round(ratio * 100, 2) if ratio is not None else None,
                   "semantic": "strong-warning" if ratio is not None and ratio >= .95 else "warning" if ratio is not None and ratio >= .8 else "normal",
                   "scope": today_state}
        for tower in data.tower_daily_info or []:
            tower_label = tower.display_name or (f"未知塔 · TYPE {tower.tower_type}" if tower.tower_type is not None else "未知塔")
            today.extend(pairs([(tower_label, "未开放" if tower.is_opened is False else
                                 f"剩余 {display_number(tower.remaining)}" if tower.is_opened is True else "开放状态 Unknown")], today_state))
        if data.daily_available is False:
            simulation_state = "UNAVAILABLE"
        elif data.daily_partial or (data.daily_available and data.sim_room_daily_record is None and not (data.sim_room_overclock_subseason or data.sim_room_overclock_season)):
            simulation_state = "PARTIAL"
        elif data.daily_available is True:
            simulation_state = "AVAILABLE"
        else:
            simulation_state = "UNKNOWN"
        roster_state = section_state(data.roster_available, data.roster_partial)
        outpost_state = section_state(data.outpost_available)
        research_state = section_state(partial=data.research_partial, items=data.recycle_room_researches)
        resource_state = section_state(partial=data.currencies_partial, items=data.currencies)
        collection_state = section_state(partial=data.memorial_partial, items=data.memorial_summary)
        resources, used = [], set()
        for definition in CurrencyRegistry.DEFINITIONS.values():
            matches = [item for item in data.currencies or [] if item.type == definition.type]
            item = matches[0] if len(matches) == 1 else None
            if item is not None:
                used.add(id(item))
            icon = None
            if item is not None and item.icon_key and self.assets is not None:
                try:
                    icon = self.resolver.encode(self.assets.get_currency_icon(item.type), (56, 56))
                except Exception:
                    pass
            raw_label = item.display_name if item else definition.display_name
            label = "白银积分券" if raw_label == "躯体标签" else raw_label
            val = format_compact_number(item.value) if item and item.value is not None else "Unknown"
            resources.append({"label": label, "value": val,
                              "scope": resource_state, "icon_data_uri": icon})
        extras = [{"label": "白银积分券" if item.display_name == "躯体标签" else item.display_name, "value": display_number(item.value), "scope": resource_state} for item in data.currencies or [] if id(item) not in used]
        researches = pairs([(item.presentation_name or item.display_name or "研究项目名称 Unknown",
                             "LV." + display_number(item.level) + (f" · EXP {item.exp:,}" if item.exp is not None and item.exp > 0 else ""))
                            for item in data.recycle_room_researches or []], research_state)
        return {"commander": data.commander_name, "updated": data.fetched_at, "version": data.plugin_version,
                "today": today, "today_state": today_state, "storage": storage,
                "simulation": pairs([("模拟室每日最佳", data.sim_room_daily_record.display_label if data.sim_room_daily_record else None),
                                     ("每日最佳分数", display_number(data.sim_room_daily_record.score) if data.sim_room_daily_record else None),
                                     ("双周最高", data.sim_room_overclock_subseason), ("赛季最高", data.sim_room_overclock_season)], simulation_state),
                "simulation_state": simulation_state,
                "outpost": pairs([("同步器等级", display_number(data.synchro_level)), ("前哨战斗等级", display_number(data.outpost_battle_level)),
                                  ("基础核心", data.infra_core_level), ("普通主线", data.normal_campaign), ("困难主线", data.hard_campaign)], outpost_state),
                "outpost_state": outpost_state,
                "roster": pairs([("角色数量", display_number(data.character_count)), ("最高等级", display_number(data.max_level)),
                                 ("最高单体 CP", display_number(data.max_combat)), ("时装数量", display_number(data.character_costume_count))], roster_state),
                "roster_state": roster_state,
                "researches": researches, "research_state": research_state,
                "collection": pairs([(item.display_name or "未知分类", display_number(item.count)) for item in data.memorial_summary or []], collection_state),
                "collection_state": collection_state, "resources": resources, "extra_resources": extras, "resource_state": resource_state,
                "account": pairs([("区服", data.area_id or None), ("指挥官等级", display_number(data.commander_level)), ("部队总战力", display_number(data.team_combat)),
                                  ("普通主线", data.normal_campaign), ("困难主线", data.hard_campaign), ("无限之塔", data.progress_tribe_tower), ("创建日期", data.created_at)])}

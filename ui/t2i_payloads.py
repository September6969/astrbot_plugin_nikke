"""只适配已经建立的领域 DTO，不解析接口或推断身份。"""
from pathlib import Path
from ..features.campaign.models import ClearLineupStatus, StageClearRecord
from astrbot_plugin_nikke.ui.t2i_assets import T2IAssetResolver


def _normalize_equipment_icon(source):
    """Trim transparent padding, then place equipment art into a stable 180×180 safe box.

    This is presentation-only normalization: it never mutates source assets and it does not
    affect equipment identity or game data.
    """
    from PIL import Image, ImageOps

    if not isinstance(source, Image.Image):
        return source
    prepared = source.convert("RGBA")
    bbox = prepared.getchannel("A").getbbox()
    canvas = Image.new("RGBA", (180, 180), (0, 0, 0, 0))
    if bbox is None:
        return canvas
    trimmed = prepared.crop(bbox)
    fitted = ImageOps.contain(trimmed, (172, 172), Image.Resampling.LANCZOS)
    x = (180 - fitted.width) // 2
    y = (180 - fitted.height) // 2
    canvas.alpha_composite(fitted, (x, y))
    return canvas


def display_number(value):
    return "Unknown" if value is None else f"{value:,}"


def format_compact_number(value):
    """仅 Profile Resources 8 项使用的 compact 紧凑数字格式化（约 3 位有效数字）。"""
    if value is None:
        return "Unknown"
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return value
    if value < 0:
        return "-" + format_compact_number(-value)
    if value < 1000:
        return str(int(round(value)))
    for divisor, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if value >= divisor:
            scaled = value / divisor
            if round(scaled, 2) < 10:
                return f"{scaled:.2f}{suffix}"
            elif round(scaled, 1) < 100:
                return f"{scaled:.1f}{suffix}"
            elif round(scaled, 0) < 1000:
                return f"{scaled:.0f}{suffix}"
            else:
                continue
    return f"{value / 1_000_000_000:.0f}B"


def section_state(available=None, partial=False, items=None):
    if available is False:
        return "UNAVAILABLE"
    if partial:
        return "PARTIAL"
    if items == []:
        return "EMPTY"
    return "AVAILABLE" if available is True or items is not None else "UNKNOWN"


class CharacterT2IPayloadBuilder:
    def __init__(self, resolver):
        self.resolver = resolver

    def build(self, data, card_assets):
        from dataclasses import asdict
        from astrbot_plugin_nikke.features.character.models import EquipmentData, EquipmentOption
        from astrbot_plugin_nikke.ui.theme import character_theme, _extract_portrait_palette, _parse
        from astrbot_plugin_nikke.ui.renderers.character import CharacterCardRenderer
        from astrbot_plugin_nikke.features.character.registries.static import StaticDataRegistry
        from PIL import Image
        portrait = card_assets.portrait
        theme = character_theme(data.corporation, data.element, portrait)
        dom, sec, drk, sat = _extract_portrait_palette(portrait)
        if dom and sat:
            dr, dg, db = _parse(dom)
            sr, sg, sb = _parse(sec) if sec else _parse(theme.accent)
            bg_grad = f"radial-gradient(1100px 750px at 24% 42%, rgba({dr},{dg},{db},0.18) 0%, rgba({sr},{sg},{sb},0.07) 45%, transparent 80%), linear-gradient(135deg, rgba({dr},{dg},{db},0.08) 0%, {theme.background} 100%)"
        else:
            ar, ag, ab = _parse(theme.accent)
            bg_grad = f"radial-gradient(1100px 750px at 24% 42%, rgba({ar},{ag},{ab},0.14) 0%, transparent 75%), linear-gradient(135deg, rgba({ar},{ag},{ab},0.06) 0%, {theme.background} 100%)"
        equipment = []
        for slot, label in CharacterCardRenderer.SLOT_NAMES.items():
            item = data.equipment.get(slot, EquipmentData(slot))
            options = item.options if item.equipped else []
            rows = []
            for index in range(3):
                option = options[index] if index < len(options) else EquipmentOption("empty", "空槽", 0, "empty")
                tier = option.tier if type(option.tier) is int and 1 <= option.tier <= 15 else None
                rows.append({"name": option.display_name, "value": CharacterCardRenderer._option_value(option),
                             "tier": f"T{tier}" if tier is not None else "—", "replica_tier": f"{tier}阶" if tier is not None else "—",
                             "semantic": "max" if tier == 15 else "high" if tier is not None and tier >= 12 else "neutral",
                             "state": "EMPTY" if option.unit == "empty" else "UNKNOWN" if option.unit not in ("flat", "percent") else "KNOWN"})
            equipment.append({"label": label, "status": f"LV.{item.level}" if item.equipped and item.level is not None else "已装备" if item.equipped else "未装备",
                              "icon": self.resolver.encode(_normalize_equipment_icon(card_assets.equipment.get(slot)), (180, 180)), "options": rows})
        identities = []
        for key, value in (("corporation", data.corporation), ("element", data.element), ("weapon", data.weapon), ("burst", data.burst)):
            identities.append({"label": str(value) if value is not None else "Unknown", "icon": self.resolver.encode(getattr(card_assets, key), (120, 120))})
        def item_payload(item, image, kind=None):
            fallback_unworn = "未佩戴魔方" if kind == "cube" else "未装配珍藏品/收藏品" if kind in ("favorite", "favorite_item") else "EMPTY / 未装备"
            if not item or not getattr(item, "tid", None) or item.tid in (0, "0"):
                return {"name": fallback_unworn, "level": "—", "icon": self.resolver.encode(image, (100, 100))}
            name = getattr(item, "display_name", None)
            if not name and kind:
                name = StaticDataRegistry.resolve_display_name(kind, item.tid)
            return {"name": name or "已装备 · 名称 Unknown",
                    "level": "LV." + display_number(item.level), "icon": self.resolver.encode(image, (100, 100))}
        corp_asset = getattr(card_assets, "corporation", None)
        watermark = self.resolver.encode(corp_asset, (260, 260)) if corp_asset else None
        from astrbot_plugin_nikke.features.character.replica import (
            build_summary, cache_identity, SHORT_NAMES, VERSION,
            replica_font, barlow_font, barlow_semibold_font,
            rajdhani_font, rajdhani_semibold_font, noto_font,
            noto_font_700, noto_font_800, art_style,
        )
        for gear in equipment:
            for row in gear["options"]:
                row["short_name"] = SHORT_NAMES.get(row["name"].strip("【】"), row["name"])
        replica = build_summary(data)
        skills_assets = getattr(card_assets, "skills", {}) or {}
        return {"replica_summary": replica, "template_version": VERSION, "cache_identity": cache_identity(data),
                "grade": data.grade, "core": data.core,
                "skill_items": [{"label": label, "level": level,
                                  "icon": self.resolver.encode(skills_assets.get(key), (110, 110))}
                                 for key, label, level in (("skill1", "技能1", data.skill1_level),
                                                           ("skill2", "技能2", data.skill2_level),
                                                           ("burst", "爆裂", data.burst_skill_level))],
                "replica_font": replica_font(), "font_noto": noto_font(),
                "font_noto_700": noto_font_700(), "font_noto_800": noto_font_800(),
                "font_barlow": barlow_font(), "font_barlow_sb": barlow_semibold_font(),
                "font_rajdhani": rajdhani_font(), "font_rajdhani_sb": rajdhani_semibold_font(),
                "art_style": art_style(data, portrait),
                "name": data.name_cn, "english": data.name_en, "long_name": len(data.name_cn) > 11,
                "combat": display_number(data.combat), "level": str(data.level), "rarity": data.rarity or "Unknown",
                "character_art_data_uri": self.resolver.encode(portrait, (1600, 2400)), "theme": asdict(theme), "identities": identities,
                "corporation_watermark": watermark, "bg_gradient": bg_grad,
                "summary": [{"label": item.display_name, "value": CharacterCardRenderer._option_value(item), "tier": "—"} for item in data.option_totals],
                "equipment": equipment, "skills": f"{data.skill1_level} / {data.skill2_level} / {data.burst_skill_level}",
                "favorite": item_payload(data.favorite_item, card_assets.favorite_item, kind="favorite"),
                "cube": item_payload(data.cube, card_assets.cube, kind="cube"),
                "stats": [{"label": label, "value": display_number(value), "source": source} for label, value, source in
                          (("HP", data.hp, data.hp_source), ("ATK", data.attack, data.attack_source), ("DEF", data.defense, data.defense_source))],
                "growth": f"突破 {data.grade} 星 · 核心 +{data.core} 阶 · 好感 {display_number(data.bond_level)}",
                "commander": data.commander_name, "updated": data.fetched_at, "version": data.plugin_version}


class ProfileT2IPayloadBuilder:
    def __init__(self, assets=None, resolver=None):
        self.assets = assets
        self.resolver = resolver or T2IAssetResolver()

    def build(self, data):
        from ..features.profile.currency_registry import CurrencyRegistry
        def pairs(items, state=""):
            return [{"label": label, "value": "Unknown" if value is None else str(value), "scope": state} for label, value in items]
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


class UnionOverviewT2IPayloadBuilder:
    def __init__(self, assets=None, resolver=None):
        self.assets, self.resolver = assets, resolver or T2IAssetResolver()

    def build(self, data, now=None):
        from datetime import datetime
        from astrbot_plugin_nikke.ui.renderers.raid import UnionRaidRenderer
        from astrbot_plugin_nikke.features.raid.models import RaidState
        from astrbot_plugin_nikke.features.raid.participants import format_compact_number

        raid_state = getattr(data, "raid_state", RaidState.UNKNOWN)
        if isinstance(raid_state, RaidState):
            state_str = raid_state.value
        elif isinstance(raid_state, str):
            state_str = raid_state
        else:
            state_str = "UNKNOWN"

        previous_season = getattr(data, "previous_season", None)
        prev_dict = None
        if previous_season:
            def _format_date(iso_str: str) -> str:
                if not iso_str:
                    return ""
                try:
                    dt = datetime.fromisoformat(iso_str)
                    return dt.strftime("%m.%d %H:%M")
                except Exception:
                    return iso_str[:16].replace("T", " ")

            start_fmt = _format_date(getattr(previous_season, "start_at", ""))
            end_fmt = _format_date(getattr(previous_season, "end_at", ""))
            date_range = f"{start_fmt} → {end_fmt}" if start_fmt and end_fmt else ""

            total_dmg = getattr(previous_season, "total_damage", 0)
            dmg_str = format_compact_number(total_dmg) if total_dmg else "0"

            s_num = getattr(previous_season, "season_number", None)
            s_name = f"第 {s_num} 季" if s_num is not None else str(getattr(previous_season, "season_id", ""))

            prev_dict = {
                "season_id": getattr(previous_season, "season_id", ""),
                "season_number": s_num,
                "season_name": s_name,
                "date_range": date_range,
                "total_attacks": getattr(previous_season, "total_attacks", 0),
                "total_damage": total_dmg,
                "total_damage_formatted": dmg_str,
                "boss_progress": getattr(previous_season, "boss_progress", None),
            }

        if state_str in ("OFFSEASON", "SETTLEMENT"):
            return {
                "guild": data.guild_name,
                "raid_state": state_str,
                "difficulty": None,
                "level": None,
                "bosses": [],
                "coverage": UnionRaidRenderer._coverage_text(data.response_coverage),
                "partial": data.partial_boss_records,
                "returned": 0,
                "progress": None,
                "remaining": None,
                "updated": data.fetched_at,
                "version": data.plugin_version,
                "previous_season": prev_dict,
                "current_season_name": getattr(data, "current_season_name", None),
            }

        if len(data.bosses) > 5:
            raise ValueError("超过五个 Boss，使用原有完整记录展示")
        bosses = [{**boss_presentation(self.assets, self.resolver, boss.boss_id, boss.icon_id, boss.monster_model_id, boss.name), "hp": f"{display_number(boss.current_hp)} / {display_number(boss.max_hp)}",
                   "percent": f"{boss.hp_percent:.1%}" if boss.hp_percent is not None else "Unknown",
                   "bar": round(boss.hp_percent * 100, 2) if boss.hp_percent is not None else None,
                   "status": boss.status.value, "elements": " / ".join(boss.elements) or "Unknown"} for boss in data.bosses]
        while len(bosses) < 5:
            bosses.append({"name": "未返回 Boss 记录", "hp": "Unknown", "percent": "Unknown", "bar": None, "status": "UNKNOWN", "elements": "Unknown"})
        return {"guild": data.guild_name, "raid_state": state_str, "difficulty": display_number(data.difficulty), "level": display_number(data.level),
                "bosses": bosses, "coverage": UnionRaidRenderer._coverage_text(data.response_coverage),
                "partial": data.partial_boss_records, "returned": len(data.bosses),
                "progress": f"{data.total_progress:.1%}" if data.total_progress is not None else "Unknown",
                "remaining": display_remaining(data.season_end, now), "updated": data.fetched_at, "version": data.plugin_version,
                "previous_season": prev_dict, "current_season_name": getattr(data, "current_season_name", None)}


class UnionRecordsT2IPayloadBuilder:
    def build(self, data, union_members=None, **kwargs):
        if union_members is None:
            union_members = getattr(data, "union_members", None)
        if union_members is None and isinstance(data, dict):
            union_members = data.get("union_members") or data.get("guild_members")
        participants = getattr(data, "participants", None)
        if participants is None and isinstance(data, dict):
            participants = data.get("participants", [])
        participants = participants or []
        attacked_nicknames = {item.nickname for item in participants if hasattr(item, "nickname")}

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
            for m in union_members:
                if isinstance(m, str) and m.strip():
                    clean_members.append(m.strip())
                elif isinstance(m, dict) and m.get("nickname"):
                    clean_members.append(str(m["nickname"]).strip())
            unattacked = [name for name in clean_members if name not in attacked_nicknames]
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
            "scope": getattr(data, "scope", "CURRENT_RESPONSE") if not isinstance(data, dict) else data.get("scope", "CURRENT_RESPONSE"),
            "rows": [{"rank": str(item.rank), "nickname": item.nickname,
                     "damage": display_number(item.total_damage), "records": str(len(item.attacks))} for item in participants],
            "no_attack": no_attack,
        }


class UnionMemberT2IPayloadBuilder:
    def __init__(self, assets, resolver):
        self.assets, self.resolver = assets, resolver

    def build(self, data):
        from astrbot_plugin_nikke.features.character.master_resolver import CharacterMasterResolver
        from astrbot_plugin_nikke.features.campaign.models import StageClearMember
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
                        identity = StageClearMember(tid=int(member.tid), level=member.level, combat=member.combat, slot=member.slot,
                                                    name_cn=name, resource_id=str(canonical.resource_id), name_code=canonical.name_code,
                                                    costume_id=member.costume_id)
                        try:
                            source = self.assets.get_lineup_portrait(identity)
                        except Exception:
                            pass
                    members.append({"name": name, "level": f"LV.{member.level}", "combat": display_number(member.combat),
                                    "slot": str(member.slot), "long_name": len(name) > 22, "portrait_data_uri": self.resolver.encode(source)})
                boss = boss_presentation(self.assets, self.resolver, attack.boss_id)
                rows.append({**boss, "label": f"RECORD {index:02}", "boss": boss["name"], "day": str(attack.day),
                             "difficulty": str(attack.difficulty), "level": str(attack.level), "step": str(attack.step),
                             "final_hit": attack.is_final_hit, "damage": display_number(attack.total_damage), "members": members})
            participants.append({"name": participant.nickname, "damage": display_number(participant.total_damage),
                                 "returned": str(len(participant.attacks)), "rows": rows})
        return {"scope": data.scope, "participants": participants}


class CalendarT2IPayloadBuilder:
    """Operations Feed T2I 渲染数据组装器。

    支持：
    1. 基于 Runtime Status Resolver 与起止时间精度的活动数据分类；
    2. 基于固定宽度 (1600) + 宣传图纵向长度驱动的动态画布高度 (900px ~ 2400px)；
    3. 每次 Query 共享同一背景源文件，按各页实际画布高度做高质量 Cover-Crop；
    4. 单项超页降级与标题视觉截断策略 (保留完整 full_title)；
    5. 全局状态与页面状态分离 (NO ACTIVE OPERATIONS 仅在全局无活动时出现)；
    6. 仅保留基于 EXACT 起止时间的辅助 timeline progress_pct 字段。

    高度预算与动态上限模型（Base-bounded + Source-extended）：
    - CANVAS_W = 1600px（固定宽度）
    - MIN_CANVAS_H = 900px（底线高度）
    - FALLBACK_MAX_CANVAS_H = 1600px（基础最大高度：无KV或横版KV时基础上限均允许生长至 1600px）
    - ABSOLUTE_MAX_CANVAS_H = 2400px（绝对安全上限）
    - scaled_source_h = round(1600 * source_h / source_w)
    - effective_max_canvas_h = min(max(FALLBACK_MAX_CANVAS_H, scaled_source_h), ABSOLUTE_MAX_CANVAS_H)
      即：Calendar 默认允许增长至 1600px；当 KV 提供更多纵向空间时（如竖版图），上限随 KV 延长，最高 2400px；横版图绝不会将上限压至 900px。
    - 垂直外边距: CANVAS_VERTICAL_MARGIN = 170px (上下各 85px 居中)
    - 面板固定开销: PANEL_OVERHEAD = 180px
      （包含 panel 上下 1px 边框，以及 body 的上下 padding；CSS 全部使用 border-box）
    - 动态内容净预算: effective_max_canvas_h - 170 - 180
    """

    CANVAS_W = 1600
    CANVAS_H = 900
    MIN_CANVAS_H = 900
    FALLBACK_MAX_CANVAS_H = 1600
    ABSOLUTE_MAX_CANVAS_H = 2400
    MAX_CANVAS_H = FALLBACK_MAX_CANVAS_H  # 向后兼容

    PANEL_W = 1180
    PANEL_H = 730
    MIN_PANEL_H = 730
    CANVAS_VERTICAL_MARGIN = 170  # panel_h = canvas_h - CANVAS_VERTICAL_MARGIN
    MAX_PANEL_H = ABSOLUTE_MAX_CANVAS_H - CANVAS_VERTICAL_MARGIN  # 2230

    HEADER_H = 70
    FOOTER_H = 44
    PANEL_TOP_PADDING = 28
    PANEL_BOTTOM_PADDING = 20
    BODY_TOP_PADDING = 10
    BODY_BOTTOM_PADDING = 6
    PANEL_BORDER_H = 2
    PANEL_OVERHEAD = (
        PANEL_TOP_PADDING
        + HEADER_H
        + BODY_TOP_PADDING
        + BODY_BOTTOM_PADDING
        + FOOTER_H
        + PANEL_BOTTOM_PADDING
        + PANEL_BORDER_H
    )  # 180

    MAX_CONTENT_BUDGET = FALLBACK_MAX_CANVAS_H - CANVAS_VERTICAL_MARGIN - PANEL_OVERHEAD  # 1250
    CONTENT_BUDGET = MAX_CONTENT_BUDGET

    # 以下常量必须与 calendar_schedule.html 的 border-box 几何保持一一对应。
    SECTION_HEADER_H = 32
    SECTION_HEADER_BOTTOM_GAP = 8
    NEXT_SECTION_TOP_GAP = 12
    ACTIVE_CARD_GAP = 5
    NEXT_ROW_GAP = 7
    ACTIVE_CARD_NORMAL_H = 68
    ACTIVE_CARD_LONG_H = 80
    ACTIVE_CARD_OVERSIZE_H = 92
    NEXT_ROW_NORMAL_H = 44
    NEXT_ROW_LONG_H = 58

    EMPTY_STATE_H = 60

    # 安全上限：防止异常无限增长（单页 Active + Next 总项数安全上限）
    SAFETY_MAX_ITEMS_PER_PAGE = 40

    def __init__(self, resolver: T2IAssetResolver | None = None):
        self.resolver = resolver or T2IAssetResolver()

    @classmethod
    def active_card_height(cls, item: dict) -> int:
        if item.get("is_oversize"):
            return cls.ACTIVE_CARD_OVERSIZE_H
        if item.get("is_long_title"):
            return cls.ACTIVE_CARD_LONG_H
        return cls.ACTIVE_CARD_NORMAL_H

    @classmethod
    def next_row_height(cls, item: dict) -> int:
        if item.get("is_oversize") or item.get("is_long_title"):
            return cls.NEXT_ROW_LONG_H
        return cls.NEXT_ROW_NORMAL_H

    @classmethod
    def measure_active_section(cls, items: list[dict]) -> int:
        """精确测量 Active section，不把相邻 item gap 嵌进 item 高度。"""
        if not items:
            return 0
        return (
            cls.SECTION_HEADER_H
            + cls.SECTION_HEADER_BOTTOM_GAP
            + sum(cls.active_card_height(item) for item in items)
            + max(0, len(items) - 1) * cls.ACTIVE_CARD_GAP
        )

    @classmethod
    def measure_next_section(cls, items: list[dict]) -> int:
        """精确测量 Next section，不把相邻 row gap 嵌进 item 高度。"""
        if not items:
            return 0
        return (
            cls.SECTION_HEADER_H
            + cls.SECTION_HEADER_BOTTOM_GAP
            + sum(cls.next_row_height(item) for item in items)
            + max(0, len(items) - 1) * cls.NEXT_ROW_GAP
        )

    @classmethod
    def measure_page_content(
        cls,
        active_items: list[dict],
        next_items: list[dict],
        global_has_active: bool = True,
        is_first_page: bool = False,
    ) -> int:
        content_h = 0
        if active_items:
            content_h += cls.measure_active_section(active_items)
        elif is_first_page and not global_has_active:
            content_h += cls.SECTION_HEADER_H + cls.SECTION_HEADER_BOTTOM_GAP + cls.EMPTY_STATE_H

        if (active_items or (is_first_page and not global_has_active)) and next_items:
            content_h += cls.NEXT_SECTION_TOP_GAP

        if next_items:
            content_h += cls.measure_next_section(next_items)

        return content_h

    @classmethod
    def compute_max_content_budget(cls, max_canvas_height: int) -> int:
        panel_h = max_canvas_height - cls.CANVAS_VERTICAL_MARGIN
        return panel_h - cls.PANEL_OVERHEAD

    @classmethod
    def compute_canvas_height(cls, content_h: int, max_canvas_height: int | None = None) -> int:
        max_h = max_canvas_height or cls.FALLBACK_MAX_CANVAS_H
        canvas_h_required = cls.PANEL_OVERHEAD + cls.CANVAS_VERTICAL_MARGIN + content_h
        return max(cls.MIN_CANVAS_H, min(max_h, canvas_h_required))

    @classmethod
    def compute_panel_height(cls, canvas_h: int) -> int:
        return canvas_h - cls.CANVAS_VERTICAL_MARGIN

    def _resolve_background_source(
        self, service, active_events, upcoming_events
    ) -> Path | None:
        vc = getattr(service, "visual_cache", None)
        if not vc or not hasattr(vc, "resolve_path"):
            return None

        candidate_ids = []
        # 优先级 1：进行中主活动
        main_categories = {"event", "solo_raid", "union_raid"}
        for ev in active_events:
            if ev.category in main_categories:
                candidate_ids.append(ev.event_id)
        # 优先级 2：其余进行中活动
        for ev in active_events:
            if ev.event_id not in candidate_ids:
                candidate_ids.append(ev.event_id)
        # 优先级 3：预告活动
        for ev in upcoming_events:
            if ev.event_id not in candidate_ids:
                candidate_ids.append(ev.event_id)
        # 优先级 4：本地清单内已有任意 KV
        manifest = getattr(vc, "_manifest", {})
        if isinstance(manifest, dict):
            for eid in manifest:
                if eid not in candidate_ids:
                    candidate_ids.append(str(eid))

        for eid in candidate_ids:
            path = vc.resolve_path(eid)
            if path is not None and isinstance(path, Path) and path.is_file():
                return path
        return None

    @classmethod
    def _get_background_dimensions(cls, path: Path | None) -> tuple[int, int] | None:
        if path is None:
            return None
        try:
            from PIL import Image
            with Image.open(path) as image:
                return image.size  # (width, height)
        except Exception:
            return None

    @classmethod
    def _compute_effective_max_canvas_height(
        cls, dimensions: tuple[int, int] | None
    ) -> tuple[int, int | None, int | None, int | None]:
        """计算有效最大画布高度。

        返回: (effective_max_h, source_w, source_h, scaled_source_h)
        """
        if dimensions is None:
            return cls.FALLBACK_MAX_CANVAS_H, None, None, None
        source_w, source_h = dimensions
        if source_w <= 0 or source_h <= 0:
            return cls.FALLBACK_MAX_CANVAS_H, source_w, source_h, None

        scaled_source_h = round(cls.CANVAS_W * source_h / source_w)
        effective_max_h = min(
            max(cls.FALLBACK_MAX_CANVAS_H, scaled_source_h),
            cls.ABSOLUTE_MAX_CANVAS_H,
        )
        return effective_max_h, source_w, source_h, scaled_source_h

    def _encode_background(
        self, path: Path | None, canvas_height: int = 900
    ) -> str | None:
        if path is None:
            return None
        try:
            return self.resolver.encode(
                path, size=(self.CANVAS_W, canvas_height), cover_crop=True
            )
        except Exception:
            return None

    def _resolve_background(
        self, service, active_events, upcoming_events, canvas_height: int = 900
    ) -> str | None:
        source_path = self._resolve_background_source(service, active_events, upcoming_events)
        return self._encode_background(source_path, canvas_height=canvas_height)

    def _paginate(
        self,
        active_items: list[dict],
        next_items: list[dict],
        global_has_active: bool,
        max_canvas_height: int | None = None,
    ) -> list[dict]:
        max_canvas_h = max_canvas_height or self.FALLBACK_MAX_CANVAS_H
        max_content_budget = self.compute_max_content_budget(max_canvas_h)

        pages = []
        rem_active = list(active_items)
        rem_next = list(next_items)

        if not rem_active and not rem_next:
            canvas_h = self.MIN_CANVAS_H
            panel_h = self.MIN_PANEL_H
            return [{
                "page_number": 1,
                "page_total": 1,
                "active_items": [],
                "next_items": [],
                "page_active_items": [],
                "page_next_items": [],
                "show_active_header": True,
                "show_next_header": False,
                "canvas": {"width": self.CANVAS_W, "height": canvas_h},
                "panel": {"width": self.PANEL_W, "height": panel_h},
            }]

        page_idx = 1
        while rem_active or rem_next:
            p_active = []
            p_next = []
            is_p1 = (page_idx == 1)

            # 1. 优先尝试放入 Active 任务
            while rem_active:
                if len(p_active) + len(p_next) >= self.SAFETY_MAX_ITEMS_PER_PAGE:
                    break
                candidate = rem_active[0]
                tentative = p_active + [candidate]
                tentative_h = self.measure_page_content(
                    tentative,
                    [],
                    global_has_active=global_has_active,
                    is_first_page=is_p1,
                )
                if tentative_h > max_content_budget:
                    if not p_active:
                        # 单项超页处理：独占当前页
                        candidate["is_oversize"] = True
                        p_active.append(rem_active.pop(0))
                    break
                p_active.append(rem_active.pop(0))

            # 2. 尝试放入 Next 预告任务
            while rem_next:
                if len(p_active) + len(p_next) >= self.SAFETY_MAX_ITEMS_PER_PAGE:
                    break
                candidate = rem_next[0]
                tentative = p_next + [candidate]
                tentative_h = self.measure_page_content(
                    p_active,
                    tentative,
                    global_has_active=global_has_active,
                    is_first_page=is_p1,
                )
                if tentative_h > max_content_budget:
                    if not p_active and not p_next:
                        candidate["is_oversize"] = True
                        p_next.append(rem_next.pop(0))
                    break
                p_next.append(rem_next.pop(0))

            # 紧急保底推进
            if not p_active and not p_next:
                if rem_active:
                    rem_active[0]["is_oversize"] = True
                    p_active.append(rem_active.pop(0))
                elif rem_next:
                    rem_next[0]["is_oversize"] = True
                    p_next.append(rem_next.pop(0))

            # 计算本页真实高度（以 max_canvas_h 为上限，按实际内容计算）
            actual_content_h = self.measure_page_content(
                p_active,
                p_next,
                global_has_active=global_has_active,
                is_first_page=is_p1,
            )
            page_canvas_h = self.compute_canvas_height(actual_content_h, max_canvas_height=max_canvas_h)
            page_panel_h = self.compute_panel_height(page_canvas_h)

            pages.append({
                "page_number": page_idx,
                "page_total": 0,
                "active_items": p_active,
                "next_items": p_next,
                "page_active_items": p_active,
                "page_next_items": p_next,
                "show_active_header": bool(p_active or (page_idx == 1 and not global_has_active)),
                "show_next_header": bool(p_next),
                "canvas": {"width": self.CANVAS_W, "height": page_canvas_h},
                "panel": {"width": self.PANEL_W, "height": page_panel_h},
            })
            page_idx += 1

        total_pages = len(pages)
        for p in pages:
            p["page_total"] = total_pages

        return pages

    def build(self, service, days=14, now=None, warning=""):
        from datetime import datetime, timedelta, timezone
        from astrbot_plugin_nikke.features.calendar.models import _aware_utc, TimePrecision
        from astrbot_plugin_nikke.features.calendar.canonical_models import (
            CanonicalEvent,
            resolve_event_status,
            EventStatus,
            Freshness,
            Coverage,
            active_sort_key,
            resolve_next_ending,
        )
        from astrbot_plugin_nikke.features.calendar.schedule_service import CAT_LABELS, CST

        # 1. 冻结 QueryContext
        if hasattr(service, "freeze_query_context"):
            ctx = service.freeze_query_context(now=now)
            current = ctx.now
            events = ctx.events
            snapshot_ver = ctx.snapshot_version
            freshness = ctx.freshness
            coverage = ctx.coverage
            source_health = ctx.source_health
        else:
            current = _aware_utc(now) if now else datetime.now(timezone.utc)
            events = [act.to_canonical() for act in getattr(service, "list_activities", lambda: [])()]
            snapshot_ver = "1.0.0"
            freshness = Freshness.FRESH
            coverage = Coverage.COMPLETE
            source_health = {}

        days = service.normalize_horizon(days) if hasattr(service, "normalize_horizon") else days

        # 2. 运行时状态推导与地平线过滤
        active_canonical: list[CanonicalEvent] = []
        upcoming_canonical: list[CanonicalEvent] = []
        for ev in events:
            st = resolve_event_status(ev, current)
            if st == EventStatus.ACTIVE:
                active_canonical.append(ev)
            elif st == EventStatus.UPCOMING:
                if ev.start_at is None or ev.start_at <= current + timedelta(days=days):
                    upcoming_canonical.append(ev)

        # 稳定排序
        active_canonical.sort(key=active_sort_key)
        upcoming_canonical.sort(key=lambda e: (e.start_at is None, e.start_at, e.identity_key))

        next_ending_ev = resolve_next_ending(active_canonical, now=current)
        next_ending_id = next_ending_ev.event_id if next_ending_ev else None

        # 3. 构造 Active Items
        active_items: list[dict] = []
        for ev in active_canonical:
            is_long = len(ev.title) > 26
            is_oversize = len(ev.title) > 65

            start_prec = ev.start_precision.value if hasattr(ev.start_precision, "value") else str(ev.start_precision)
            end_prec = ev.end_precision.value if hasattr(ev.end_precision, "value") else str(ev.end_precision)

            if ev.start_at and ev.end_at:
                if start_prec == "DATE_ONLY" and end_prec == "DATE_ONLY":
                    time_range = f"{ev.start_at.astimezone(CST).strftime('%m.%d')} → {ev.end_at.astimezone(CST).strftime('%m.%d')} · UTC+8"
                else:
                    s_fmt = "%m.%d %H:%M" if start_prec == "EXACT" else "%m.%d"
                    e_fmt = "%m.%d %H:%M" if end_prec == "EXACT" else "%m.%d"
                    time_range = f"{ev.start_at.astimezone(CST).strftime(s_fmt)} → {ev.end_at.astimezone(CST).strftime(e_fmt)} · UTC+8"
            elif ev.start_at:
                s_fmt = "%m.%d %H:%M" if start_prec == "EXACT" else "%m.%d"
                time_range = f"{ev.start_at.astimezone(CST).strftime(s_fmt)} 起 · UTC+8"
            elif ev.end_at:
                e_fmt = "%m.%d %H:%M" if end_prec == "EXACT" else "%m.%d"
                time_range = f"{ev.end_at.astimezone(CST).strftime(e_fmt)} 截止 · UTC+8"
            else:
                time_range = "时间未定 · UTC+8"

            remaining_str = ev.remaining_display(current)

            # 紧急度：严格限制只有 EXACT precision 参与小时级紧迫度
            urgency = "NORMAL"
            if end_prec == "EXACT" and ev.end_at and ev.end_at > current:
                diff_sec = (ev.end_at - current).total_seconds()
                if diff_sec <= 3600:
                    urgency = "CRITICAL"
                elif diff_sec <= 21600:
                    urgency = "URGENT"
                elif diff_sec <= 86400:
                    urgency = "CLOSING"
            elif end_prec != "EXACT":
                urgency = ""

            display_title = ev.title
            if is_oversize and len(display_title) > 90:
                display_title = display_title[:87] + "..."

            # 进度计算：严格条件，禁止伪造
            progress_pct: float | None = None
            if (
                ev.start_at is not None
                and ev.end_at is not None
                and start_prec == "EXACT"
                and end_prec == "EXACT"
                and ev.end_at > ev.start_at
                and ev.start_at <= current <= ev.end_at
            ):
                span = (ev.end_at - ev.start_at).total_seconds()
                elapsed = (current - ev.start_at).total_seconds()
                progress_pct = max(0.0, min(1.0, elapsed / span))

            card = {
                "event_id": ev.event_id,
                "title": display_title,
                "full_title": ev.title,
                "category": CAT_LABELS.get(ev.category, "活动"),
                "category_code": ev.category,
                "time_range": time_range,
                "start": ev.start_at.astimezone(CST).strftime("%m/%d %H:%M") if ev.start_at else "未知",
                "end": ev.end_at.astimezone(CST).strftime("%m/%d %H:%M") if ev.end_at else "未知",
                "remaining": remaining_str,
                "is_next_ending": (ev.event_id == next_ending_id),
                "urgency": urgency,
                "is_long_title": is_long,
                "is_oversize": is_oversize,
                "end_precision": end_prec,
                "progress_pct": progress_pct,          # None → 不显示进度条
            }
            active_items.append(card)


        # 4. 构造 Next Items
        next_items: list[dict] = []
        for ev in upcoming_canonical:
            is_long = len(ev.title) > 30
            is_oversize = len(ev.title) > 65
            start_prec = ev.start_precision.value if hasattr(ev.start_precision, "value") else str(ev.start_precision)

            if ev.start_at:
                s_fmt = "%m.%d %H:%M" if start_prec == "EXACT" else "%m.%d"
                start_time_display = ev.start_at.astimezone(CST).strftime(s_fmt)
                if start_prec == "EXACT":
                    diff = ev.start_at - current
                    days_diff = diff.days
                    hours_diff = diff.seconds // 3600
                    if days_diff >= 3:
                        starts_in = f"STARTS IN {days_diff}D"
                    elif days_diff > 0:
                        starts_in = f"STARTS IN {days_diff}D {hours_diff}H"
                    elif hours_diff > 0:
                        starts_in = f"STARTS IN {hours_diff}H"
                    else:
                        mins_diff = max(1, diff.seconds // 60)
                        starts_in = f"STARTS IN {mins_diff}M"
                elif start_prec == "DATE_ONLY":
                    diff_days = max(1, (ev.start_at.date() - current.date()).days)
                    starts_in = f"STARTS IN {diff_days}D"
                else:
                    starts_in = "即将开始"
            else:
                start_time_display = "时间待定"
                starts_in = "即将开始"

            display_title = ev.title
            if is_oversize and len(display_title) > 90:
                display_title = display_title[:87] + "..."

            nrow = {
                "event_id": ev.event_id,
                "title": display_title,
                "full_title": ev.title,
                "category": CAT_LABELS.get(ev.category, "活动"),
                "category_code": ev.category,
                "start_time_display": start_time_display,
                "starts_in": starts_in,
                "is_long_title": is_long,
                "is_oversize": is_oversize,
                "start": ev.start_at.astimezone(CST).strftime("%m/%d %H:%M") if ev.start_at else "未知",
                "end": ev.end_at.astimezone(CST).strftime("%m/%d %H:%M") if ev.end_at else "未知",
                "remaining": starts_in,
            }
            next_items.append(nrow)

        global_has_active = bool(active_items)
        active_count_total = len(active_items)

        # 5. 背景源探测与有效最大画布高度推导
        source_path = self._resolve_background_source(service, active_canonical, upcoming_canonical)
        bg_dims = self._get_background_dimensions(source_path)
        effective_max_canvas_h, bg_w, bg_h, scaled_source_h = self._compute_effective_max_canvas_height(bg_dims)

        # 6. 分页计算（以 effective_max_canvas_h 作为最大高度预算）
        pages = self._paginate(
            active_items, next_items, global_has_active, max_canvas_height=effective_max_canvas_h
        )

        # 7. 背景图按每页实际 canvas.height 编码（所有页面共享相同背景源）
        for p in pages:
            p_canvas_h = p["canvas"]["height"]
            p["background_data_uri"] = self._encode_background(
                source_path, canvas_height=p_canvas_h
            )

        top_canvas = pages[0]["canvas"] if pages else {"width": self.CANVAS_W, "height": self.MIN_CANVAS_H}
        top_panel = pages[0]["panel"] if pages else {"width": self.PANEL_W, "height": self.MIN_PANEL_H}
        top_bg = pages[0]["background_data_uri"] if pages else None

        if scaled_source_h is None or scaled_source_h <= self.FALLBACK_MAX_CANVAS_H:
            height_policy = "base"
        elif scaled_source_h < self.ABSOLUTE_MAX_CANVAS_H:
            height_policy = "source_extended"
        else:
            height_policy = "absolute_capped"

        layout_limits = {
            "min_canvas_height": self.MIN_CANVAS_H,
            "effective_max_canvas_height": effective_max_canvas_h,
            "absolute_max_canvas_height": self.ABSOLUTE_MAX_CANVAS_H,
            "fallback_max_canvas_height": self.FALLBACK_MAX_CANVAS_H,
            "background_source_width": bg_w,
            "background_source_height": bg_h,
            "background_scaled_height": scaled_source_h,
            "height_policy": height_policy,
            "background_limited": bool(source_path and effective_max_canvas_h < self.ABSOLUTE_MAX_CANVAS_H),
        }

        # 8. 元数据准备
        updated_str = "Unknown"
        if getattr(service, "last_updated_at", None):
            try:
                updated_str = _aware_utc(service.last_updated_at).astimezone(CST).strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                pass

        fresh_str = freshness.value if hasattr(freshness, "value") else str(freshness)
        cov_str = coverage.value if hasattr(coverage, "value") else str(coverage)

        sync_warning = warning or getattr(service, "last_sync_error", "")
        is_stale = (fresh_str == "STALE") or bool(sync_warning)

        # 直接消费 QueryContext 冻结的健康与来源展示
        if hasattr(service, "freeze_query_context"):
            health_display = ctx.health_display
            source_display = ctx.source_display
            if not source_display or source_display == "UNKNOWN":
                source_display = "LOCAL SNAPSHOT"
        else:
            from astrbot_plugin_nikke.features.calendar.canonical_models import compute_health_badge
            health_display = compute_health_badge(fresh_str, cov_str)
            sources_present = set()
            if source_health:
                for s_name in source_health:
                    sources_present.add(s_name.upper())
            if not sources_present:
                source_display = "LOCAL SNAPSHOT"
            else:
                ordered = [s for s in ("GAMEKEE", "OFFICIAL", "MANUAL_OVERRIDE") if s in sources_present]
                for s in sorted(sources_present):
                    if s not in ordered:
                        ordered.append(s)
                source_display = " + ".join(ordered)

        fallback_text = (
            service.format_schedule_text(days, current, warning)
            if hasattr(service, "format_schedule_text")
            else ""
        )

        bundle = {
            "snapshot_version": snapshot_ver,
            "query_now": current.isoformat(),
            "canvas": top_canvas,
            "panel": top_panel,
            "layout_limits": layout_limits,
            "background_data_uri": top_bg,
            "freshness": fresh_str,
            "coverage": cov_str,
            "health_display": health_display,
            "source_display": source_display,
            "timezone_display": "UTC+8",
            "updated_at_display": updated_str,
            "horizon_days": days,
            "is_stale": is_stale,
            "sync_warning": sync_warning,
            "available": service.has_snapshot() if hasattr(service, "has_snapshot") else bool(events),
            "fallback_text": fallback_text,
            "global_has_active": global_has_active,
            "active_count_total": active_count_total,
            "pages": pages,
            # Top-level direct access (Page 1)
            "page_number": pages[0]["page_number"] if pages else 1,
            "page_total": len(pages),
            "active_items": pages[0]["active_items"] if pages else [],
            "next_items": pages[0]["next_items"] if pages else [],
            "page_active_items": pages[0]["active_items"] if pages else [],
            "page_next_items": pages[0]["next_items"] if pages else [],
            "show_active_header": pages[0]["show_active_header"] if pages else True,
            "show_next_header": pages[0]["show_next_header"] if pages else False,
        }
        return bundle



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
                members.append({"name": name, "slot": str(member.slot), "long_name": len(name) > 22, "level": f"LV.{member.level}",
                                "combat": f"{member.combat:,}", "portrait_data_uri": self.resolver.encode(source)})
        labels = {ClearLineupStatus.AVAILABLE: "历史阵容", ClearLineupStatus.UNAVAILABLE: "暂无可查询阵容",
                  ClearLineupStatus.RATE_LIMITED: "请求过频", ClearLineupStatus.ERROR: "查询不可用"}
        return {"mode": record.mode if record.mode in ("NORMAL", "HARD") else "UNKNOWN",
                "stage": record.stage_name, "available": available, "members": members,
                "total_combat": f"{record.total_combat:,}" if available else "—",
                "status": labels[record.status], "status_message": record.status_message,
                "commander": record.commander_name, "updated": record.fetched_at,
                "version": record.plugin_version,
                "portrait_notice": "头像暂不可用" if available and all(not m["portrait_data_uri"] for m in members)
                else "部分头像不可用" if any(not m["portrait_data_uri"] for m in members) else ""}

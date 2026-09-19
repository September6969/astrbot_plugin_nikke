"""只适配已经建立的领域 DTO，不解析接口或推断身份。"""
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

CATEGORY_DISPLAY_MAP = {
    "coop": "CO-OP",
    "co_op": "CO-OP",
    "story_event": "STORY EVENT",
    "solo_raid": "SOLO RAID",
    "union_raid": "UNION RAID",
    "recruit": "PICKUP",
    "pickup": "PICKUP",
    "login": "LOGIN",
    "event": "EVENT",
    "maintenance": "MAINTENANCE",
    "update": "UPDATE",
    "double_reward": "DOUBLE REWARD",
    "special_arena": "SPECIAL ARENA",
}


class CalendarT2IPayloadBuilder:
    def build(self, service, days=14, now=None, warning=""):
        from datetime import datetime, timedelta, timezone
        from astrbot_plugin_nikke.features.calendar.models import _aware_utc
        from astrbot_plugin_nikke.features.calendar.service import CST
        current = _aware_utc(now) if now else datetime.now(timezone.utc)
        days = service.normalize_horizon(days)

        updated = "—"
        if service.last_updated_at:
            try:
                updated = _aware_utc(service.last_updated_at).astimezone(CST).strftime("%H:%M")
            except (ValueError, TypeError):
                pass

        available = service.has_snapshot()
        sync_warning = warning or getattr(service, "last_sync_error", "")
        if not available:
            data_quality = "UNAVAILABLE"
        elif getattr(service, "data_quality", None) in ("FRESH", "STALE", "PARTIAL", "UNAVAILABLE"):
            data_quality = service.data_quality
        elif sync_warning:
            data_quality = "STALE"
        else:
            data_quality = "FRESH"

        if data_quality == "UNAVAILABLE":
            source_display = "SCHEDULE DATA UNAVAILABLE"
            quality_badge_display = "DATA UNAVAILABLE"
        elif data_quality == "STALE":
            source_display = "GAMEKEE + OFFICIAL"
            quality_badge_display = f"DATA STALE · UPDATED {updated}"
        elif data_quality == "PARTIAL":
            source_display = "GAMEKEE + OFFICIAL"
            quality_badge_display = f"PARTIAL DATA · UPDATED {updated}"
        else:
            source_display = "GAMEKEE + OFFICIAL"
            quality_badge_display = f"DATA OK · UPDATED {updated}"

        if hasattr(service, "list_canonical"):
            all_events = service.list_canonical()
        else:
            all_events = service.list_activities()

        active_events = [act for act in all_events if act.is_active(current)]
        active_events.sort(key=lambda e: e.end_at)

        horizon = timedelta(days=days)
        upcoming_events = [
            act for act in all_events
            if act.is_upcoming(current) and act.start_at <= current + horizon
        ]
        upcoming_events.sort(key=lambda e: e.start_at)

        active_items = []
        for idx, act in enumerate(active_events):
            precision = getattr(act, "time_precision", "EXACT")
            rem_sec = (act.end_at - current).total_seconds()
            if rem_sec <= 3600:
                urgency = "CRITICAL"
            elif rem_sec <= 6 * 3600:
                urgency = "URGENT"
            elif rem_sec <= 24 * 3600:
                urgency = "CLOSING"
            else:
                urgency = "NORMAL"

            start_cst = act.start_at.astimezone(CST)
            end_cst = act.end_at.astimezone(CST)

            if precision == "EXACT":
                start_str = start_cst.strftime("%m.%d %H:%M")
                end_str = end_cst.strftime("%m.%d %H:%M")
                time_range = f"{start_str} → {end_str}"
                total_sec = max(0, int(rem_sec))
                d = total_sec // 86400
                h = (total_sec % 86400) // 3600
                m = (total_sec % 3600) // 60
                if d > 0:
                    remaining = f"{d}D {h:02d}H"
                elif h > 0:
                    remaining = f"{h:02d}H {m:02d}M"
                else:
                    remaining = f"{max(1, m):02d}M"
            else:
                start_str = start_cst.strftime("%m.%d")
                end_str = end_cst.strftime("%m.%d")
                time_range = f"{start_str} → {end_str}"
                remaining = f"{end_str} 截止"

            cat_raw = getattr(act, "event_type", None) or getattr(act, "category", "event")
            cat_key = cat_raw.lower() if isinstance(cat_raw, str) else "event"
            cat_display = CATEGORY_DISPLAY_MAP.get(cat_key, cat_key.upper().replace("_", " "))

            active_items.append({
                "category": cat_display,
                "title": act.title,
                "start": start_str,
                "end": end_str,
                "time_range_display": time_range,
                "remaining": remaining,
                "urgency": urgency,
                "is_next_ending": (idx == 0),
            })

        next_items = []
        for act in upcoming_events:
            precision = getattr(act, "time_precision", "EXACT")
            start_cst = act.start_at.astimezone(CST)
            start_sec = max(0, int((act.start_at - current).total_seconds()))
            if precision == "EXACT":
                start_str = start_cst.strftime("%m.%d %H:%M")
                d = start_sec // 86400
                h = (start_sec % 86400) // 3600
                m = (start_sec % 3600) // 60
                if d > 0:
                    starts_in = f"STARTS IN {d}D"
                elif h > 0:
                    starts_in = f"STARTS IN {h}H"
                else:
                    starts_in = f"STARTS IN {max(1, m)}M"
            else:
                start_str = start_cst.strftime("%m.%d")
                starts_in = f"{start_str} 开始"

            cat_raw = getattr(act, "event_type", None) or getattr(act, "category", "event")
            cat_key = cat_raw.lower() if isinstance(cat_raw, str) else "event"
            cat_display = CATEGORY_DISPLAY_MAP.get(cat_key, cat_key.upper().replace("_", " "))

            next_items.append({
                "category": cat_display,
                "title": act.title,
                "start": start_str,
                "starts_in": starts_in,
            })

        return {
            "active_count": len(active_items),
            "active_items": active_items,
            "next_items": next_items,
            "timezone_display": "UTC+8",
            "updated_at_display": updated,
            "data_quality": data_quality,
            "source_display": source_display,
            "quality_badge_display": quality_badge_display,
            "available": available,
            "has_active": bool(active_items),
            "has_upcoming": bool(next_items),
            "fallback_text": service.format_schedule_text(days, current, warning),
        }


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

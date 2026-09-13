"""只适配已经建立的领域 DTO，不解析接口或推断身份。"""
from .campaign_history_models import ClearLineupStatus, StageClearRecord
from .t2i_assets import T2IAssetResolver


def display_number(value):
    return "Unknown" if value is None else f"{value:,}"


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
        from .card_models import EquipmentData, EquipmentOption
        from .card_theme import character_theme, _extract_portrait_palette, _parse
        from .character_card_renderer import CharacterCardRenderer
        from PIL import Image
        portrait = card_assets.portrait
        if isinstance(portrait, Image.Image):
            # 只移除透明边缘，不裁切立绘实体或延伸武器。
            portrait = portrait.convert("RGBA")
            bounds = portrait.getchannel("A").getbbox()
            if bounds:
                portrait = portrait.crop(bounds)
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
                             "tier": f"T{tier}" if tier is not None else "—",
                             "semantic": "max" if tier == 15 else "high" if tier is not None and tier >= 12 else "neutral",
                             "state": "EMPTY" if option.unit == "empty" else "UNKNOWN" if option.unit not in ("flat", "percent") else "KNOWN"})
            equipment.append({"label": label, "status": f"LV.{item.level}" if item.equipped and item.level is not None else "已装备" if item.equipped else "未装备",
                              "icon": self.resolver.encode(card_assets.equipment.get(slot), (64, 64)), "options": rows})
        identities = []
        for key, value in (("corporation", data.corporation), ("element", data.element), ("weapon", data.weapon), ("burst", data.burst)):
            identities.append({"label": str(value) if value is not None else "Unknown", "icon": self.resolver.encode(getattr(card_assets, key), (40, 40))})
        def item_payload(item, image):
            return {"name": item.display_name or "已装备 · 名称 Unknown" if item else "EMPTY / 未装备",
                    "level": "LV." + display_number(item.level) if item else "—", "icon": self.resolver.encode(image, (48, 48))}
        corp_asset = getattr(card_assets, "corporation", None)
        watermark = self.resolver.encode(corp_asset, (260, 260)) if corp_asset else None
        return {"name": data.name_cn, "english": data.name_en, "long_name": len(data.name_cn) > 16,
                "combat": display_number(data.combat), "level": str(data.level), "rarity": data.rarity or "Unknown",
                "character_art_data_uri": self.resolver.encode(portrait, (700, 744)), "theme": asdict(theme), "identities": identities,
                "corporation_watermark": watermark, "bg_gradient": bg_grad,
                "summary": [{"label": item.display_name, "value": CharacterCardRenderer._option_value(item), "tier": "—"} for item in data.option_totals],
                "equipment": equipment, "skills": f"{data.skill1_level} / {data.skill2_level} / {data.burst_skill_level}",
                "favorite": item_payload(data.favorite_item, card_assets.favorite_item), "cube": item_payload(data.cube, card_assets.cube),
                "stats": [{"label": label, "value": display_number(value), "source": source} for label, value, source in
                          (("HP", data.hp, data.hp_source), ("ATK", data.attack, data.attack_source), ("DEF", data.defense, data.defense_source))],
                "growth": f"突破 {data.grade} · 核心 +{data.core} · 好感 {display_number(data.bond_level)}",
                "commander": data.commander_name, "updated": data.fetched_at, "version": data.plugin_version}


class ProfileT2IPayloadBuilder:
    def __init__(self, assets=None, resolver=None):
        self.assets = assets
        self.resolver = resolver or T2IAssetResolver()

    def build(self, data):
        from .currency_registry import CurrencyRegistry
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
            today.extend(pairs([(tower.display_name or "塔记录", "未开放" if tower.is_opened is False else
                                 f"剩余 {display_number(tower.remaining)}" if tower.is_opened is True else "开放状态 Unknown")], today_state))
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
            resources.append({"label": label, "value": display_number(item.value) if item else "Unknown",
                              "scope": resource_state, "icon_data_uri": icon})
        extras = [{"label": "白银积分券" if item.display_name == "躯体标签" else item.display_name, "value": display_number(item.value), "scope": resource_state} for item in data.currencies or [] if id(item) not in used]
        researches = pairs([(item.presentation_name or item.display_name or "研究项目名称 Unknown",
                             "LV." + display_number(item.level) + (f" · EXP {item.exp:,}" if item.exp is not None and item.exp > 0 else ""))
                            for item in data.recycle_room_researches or []], research_state)
        return {"commander": data.commander_name, "updated": data.fetched_at, "version": data.plugin_version,
                "today": today, "today_state": today_state, "storage": storage,
                "simulation": pairs([("模拟室每日最佳", data.sim_room_daily_record.display_label if data.sim_room_daily_record else None),
                                     ("每日最佳分数", display_number(data.sim_room_daily_record.score) if data.sim_room_daily_record else None),
                                     ("双周最高", data.sim_room_overclock_subseason), ("赛季最高", data.sim_room_overclock_season)], today_state),
                "outpost": pairs([("同步器等级", display_number(data.synchro_level)), ("前哨战斗等级", display_number(data.outpost_battle_level)),
                                  ("基础核心", data.infra_core_level), ("普通主线", data.normal_campaign), ("困难主线", data.hard_campaign)], outpost_state),
                "roster": pairs([("角色数量", display_number(data.character_count)), ("最高等级", display_number(data.max_level)),
                                 ("最高单体 CP", display_number(data.max_combat)), ("时装数量", display_number(data.character_costume_count))], roster_state),
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
        from .union_raid_renderer import UnionRaidRenderer
        if len(data.bosses) > 5:
            raise ValueError("超过五个 Boss，使用原有完整记录展示")
        bosses = [{**boss_presentation(self.assets, self.resolver, boss.boss_id, boss.icon_id, boss.monster_model_id, boss.name), "hp": f"{display_number(boss.current_hp)} / {display_number(boss.max_hp)}",
                   "percent": f"{boss.hp_percent:.1%}" if boss.hp_percent is not None else "Unknown",
                   "bar": round(boss.hp_percent * 100, 2) if boss.hp_percent is not None else None,
                   "status": boss.status.value, "elements": " / ".join(boss.elements) or "Unknown"} for boss in data.bosses]
        while len(bosses) < 5:
            bosses.append({"name": "未返回 Boss 记录", "hp": "Unknown", "percent": "Unknown", "bar": None, "status": "UNKNOWN", "elements": "Unknown"})
        return {"guild": data.guild_name, "difficulty": display_number(data.difficulty), "level": display_number(data.level),
                "bosses": bosses, "coverage": UnionRaidRenderer._coverage_text(data.response_coverage),
                "partial": data.partial_boss_records, "returned": len(data.bosses),
                "progress": f"{data.total_progress:.1%}" if data.total_progress is not None else "Unknown",
                "remaining": display_remaining(data.season_end, now), "updated": data.fetched_at, "version": data.plugin_version}


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
        from .character_master_resolver import CharacterMasterResolver
        from .campaign_history_models import StageClearMember
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
    def build(self, service, days=14, now=None, warning=""):
        from datetime import datetime, timezone
        from .calendar_models import _aware_utc
        from .calendar_service import CAT_LABELS, CST
        current = _aware_utc(now) if now else datetime.now(timezone.utc)
        days = service.normalize_horizon(days)
        groups = service.group_window(days, current)
        updated = "Unknown"
        if service.last_updated_at:
            try:
                updated = _aware_utc(service.last_updated_at).astimezone(CST).strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                pass
        sync_warning = warning or service.last_sync_error
        payload = {"horizon_days": days, "timezone_display": "UTC+8", "updated_at_display": updated,
                   "is_stale": bool(sync_warning), "sync_warning": sync_warning,
                   "available": service.has_snapshot(),
                   "fallback_text": service.format_schedule_text(days, current, warning)}
        for key, activities in groups.items():
            items = []
            for item in activities:
                is_upcoming = (key == "upcoming")
                if not is_upcoming:
                    total_sec = max(1.0, (item.end_at - item.start_at).total_seconds())
                    elapsed_sec = (current - item.start_at).total_seconds()
                    clamped_pct = max(0.0, min(100.0, (elapsed_sec / total_sec) * 100.0))
                    prog_val = round(clamped_pct, 1)
                    if clamped_pct >= 99.5 and clamped_pct < 100.0:
                        int_pct = 99
                    elif clamped_pct > 0.0 and clamped_pct < 0.5:
                        int_pct = 1
                    else:
                        int_pct = int(round(clamped_pct))
                    prog_label = f"{int_pct}%"
                else:
                    prog_val = 0.0
                    prog_label = "未开始"
                items.append({"title": item.title, "category": CAT_LABELS.get(item.category, "活动"),
                              "remaining": item.remaining_display(current),
                              "start": item.start_at.astimezone(CST).strftime("%m/%d %H:%M"),
                              "end": item.end_at.astimezone(CST).strftime("%m/%d %H:%M"),
                              "progress_percent": prog_val, "progress_label": prog_label,
                              "is_upcoming": is_upcoming})
            payload[key] = items
        payload["groups"] = [{"title": title, "items": payload[key]} for key, title in
                             (("ending_soon", "ENDING SOON / 即将结束"), ("active", "ACTIVE / 进行中"), ("upcoming", "UPCOMING / 即将开始"))]
        return payload


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

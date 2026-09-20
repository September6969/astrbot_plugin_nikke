"""供预览和离线测试共用的合成 DTO；不包含真实账号资料。"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

NOW = datetime(2026, 9, 13, 4, tzinfo=timezone.utc)


def calendar_cases(directory):
    from astrbot_plugin_nikke.features.calendar.models import CalendarActivity
    from astrbot_plugin_nikke.features.calendar.service import CalendarService
    from astrbot_plugin_nikke.features.calendar.canonical_models import CanonicalEvent, TimePrecision, SourceHealth, FetchOutcome
    from astrbot_plugin_nikke.ui.t2i_payloads import CalendarT2IPayloadBuilder

    case_names = (
        "normal", "7-days", "30-days", "stale", "long-title", "many-events", "empty", "unavailable",
        "2-active-2-next", "5-active",
        "8-active",              # 单页 8 条
        "8-active-paged",        # 兼容旧测试名
        "9-active",              # 9 条（动态高度单页）
        "12-active-paged",       # 12 条（动态高度单页）
        "16-active",             # 16 条
        "17-active",             # 17 条
        "8-active-with-progress",# 8 条均带 EXACT 精度
        "8-active-mixed-long",   # 含长标题
        "dynamic-short",         # 2 active -> canvas.height == 900
        "dynamic-7-active-4-next",# 7 active + 4 next -> 单页！~1044px
        "dynamic-10-active",     # 10 active -> 单页！~988px
        "dynamic-12-active-6-next",# 12 active + 6 next -> 单页！~1436px
        "dynamic-20-active",     # 20 active -> 多页 (16 + 4)
        "dynamic-long-titles",   # 多条长标题，验证预算不溢出
        "4-active-8-next",
        "next-only", "unknown-end", "date-only", "critical", "partial", "no-background", "oversize-title"
    )
    result = {}
    for name in case_names:
        service = CalendarService(Path(directory) / name)
        service._has_snapshot = name != "unavailable"
        service.last_updated_at = NOW.isoformat()
        service.last_sync_error = "合成同步失败示例" if name == "stale" else ""

        if name == "partial":
            service._source_health["gamekee"] = SourceHealth(source="gamekee", last_attempt_at=NOW, last_success_at=NOW, last_outcome=FetchOutcome.SUCCESS_DATA.value)
            service._source_health["official"] = SourceHealth(source="official", last_attempt_at=NOW, last_success_at=None, last_outcome=FetchOutcome.REQUEST_FAILED.value, last_error_type="502 Bad Gateway")

        if name not in ("empty", "unavailable"):
            if name in ("normal", "7-days", "30-days", "stale", "no-background"):
                for index in range(5):
                    start = NOW - timedelta(days=2) if index < 2 else NOW + timedelta(days=index * 3)
                    end = NOW + timedelta(hours=8) if index == 0 else start + timedelta(days=7)
                    event = CalendarActivity(
                        str(index), f"合成活动 {index + 1}", start, end,
                        category=["coop", "union_raid", "solo_raid", "recruit", "event"][index % 5],
                        banner_url="https://invalid.example/banner.png",
                        start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                    )
                    service._activities[event.event_id] = event
            elif name == "many-events":
                for index in range(24):
                    start, end = NOW - timedelta(days=1), NOW + timedelta(days=index + 1)
                    event = CalendarActivity(
                        str(index), f"合成活动 {index + 1}", start, end,
                        category=["coop", "union_raid", "solo_raid", "recruit", "event"][index % 5],
                        banner_url="https://invalid.example/banner.png",
                        start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                    )
                    service._activities[event.event_id] = event
            elif name == "2-active-2-next":
                # 2 active, 2 next
                for index in range(2):
                    start = NOW - timedelta(days=2)
                    end = NOW + timedelta(days=3 + index * 2)
                    event = CalendarActivity(
                        f"act-{index}", f"进行中任务 {index + 1}", start, end,
                        category="event", banner_url="",
                        start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                    )
                    service._activities[event.event_id] = event
                for index in range(2):
                    start = NOW + timedelta(days=2 + index * 3)
                    end = start + timedelta(days=5)
                    event = CalendarActivity(
                        f"nxt-{index}", f"预告任务 {index + 1}", start, end,
                        category="union_raid", banner_url="",
                        start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                    )
                    service._activities[event.event_id] = event
            elif name == "5-active":
                for index in range(5):
                    start = NOW - timedelta(days=1)
                    end = NOW + timedelta(days=index + 2)
                    event = CalendarActivity(
                        str(index), f"单页进行中作战 {index + 1}", start, end,
                        category=["event", "solo_raid", "coop", "recruit", "event"][index % 5],
                        banner_url="", start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                    )
                    service._activities[event.event_id] = event
            elif name in ("8-active", "8-active-paged"):
                # 新：8 条 normal → 单页 8 个（已更新预算）
                # 8-active-paged 保持同数据供旧测试兼容
                for index in range(8):
                    start = NOW - timedelta(days=1)
                    end = NOW + timedelta(days=index + 2)
                    event = CalendarActivity(
                        str(index), f"单页进行中作战 {index + 1}", start, end,
                        category=["event", "solo_raid", "coop", "recruit", "event"][index % 5],
                        banner_url="", start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                    )
                    service._activities[event.event_id] = event
            elif name == "9-active":
                # 9 条 → 8+1 两页
                for index in range(9):
                    start = NOW - timedelta(days=1)
                    end = NOW + timedelta(days=index + 2)
                    event = CalendarActivity(
                        str(index), f"9条作战 {index + 1}", start, end,
                        category=["event", "solo_raid", "coop", "recruit", "event"][index % 5],
                        banner_url="", start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                    )
                    service._activities[event.event_id] = event
            elif name == "12-active-paged":
                # 12 条 → 8+4 两页（旧 5+5+2，已随预算更新）
                for index in range(12):
                    start = NOW - timedelta(days=1)
                    end = NOW + timedelta(days=index + 2)
                    event = CalendarActivity(
                        str(index), f"多页进行中作战 {index + 1}", start, end,
                        category=["event", "solo_raid", "coop", "recruit", "event"][index % 5],
                        banner_url="", start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                    )
                    service._activities[event.event_id] = event
            elif name == "16-active":
                # 16 条 → 8+8
                for index in range(16):
                    start = NOW - timedelta(days=1)
                    end = NOW + timedelta(days=index + 2)
                    event = CalendarActivity(
                        str(index), f"16条作战 {index + 1}", start, end,
                        category=["event", "solo_raid", "coop", "recruit", "event"][index % 5],
                        banner_url="", start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                    )
                    service._activities[event.event_id] = event
            elif name == "17-active":
                # 17 条 → 8+8+1
                for index in range(17):
                    start = NOW - timedelta(days=1)
                    end = NOW + timedelta(days=index + 2)
                    event = CalendarActivity(
                        str(index), f"17条作战 {index + 1}", start, end,
                        category=["event", "solo_raid", "coop", "recruit", "event"][index % 5],
                        banner_url="", start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                    )
                    service._activities[event.event_id] = event
            elif name == "8-active-with-progress":
                # 8 条均满足 EXACT+now in interval → 全部有 progress_pct
                for index in range(8):
                    start = NOW - timedelta(days=1)
                    end = NOW + timedelta(hours=12 + index * 6)
                    event = CalendarActivity(
                        f"prog-{index}", f"进度可见作战 {index + 1}", start, end,
                        category=["event", "solo_raid", "coop", "recruit", "event"][index % 5],
                        banner_url="", start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                    )
                    service._activities[event.event_id] = event
            elif name == "8-active-mixed-long":
                # 5 normal + 3 long title → 预算仍应容纳（5×60 + 3×72 + 32 = 548 > 516）
                # 实际按高度预算会分成两页；此 fixture 验证预算不溢出
                for index in range(5):
                    start = NOW - timedelta(days=1)
                    end = NOW + timedelta(days=index + 2)
                    event = CalendarActivity(
                        f"norm-{index}", f"普通标题作战 {index + 1}", start, end,
                        category="event", banner_url="",
                        start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                    )
                    service._activities[event.event_id] = event
                for index in range(3):
                    start = NOW - timedelta(days=1)
                    end = NOW + timedelta(days=index + 7)
                    long_title = f"混合测试：较长标题活动验证预算精确度第{index + 1}号"
                    event = CalendarActivity(
                        f"long-{index}", long_title, start, end,
                        category="event", banner_url="",
                        start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                    )
                    service._activities[event.event_id] = event

            elif name == "dynamic-short":
                for index in range(2):
                    start = NOW - timedelta(days=1)
                    end = NOW + timedelta(days=index + 2)
                    event = CalendarActivity(
                        f"act-{index}", f"进行中任务 {index + 1}", start, end,
                        category="event", banner_url="",
                        start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                    )
                    service._activities[event.event_id] = event
            elif name == "dynamic-7-active-4-next":
                for index in range(7):
                    start = NOW - timedelta(days=1)
                    end = NOW + timedelta(days=index + 2)
                    event = CalendarActivity(
                        f"act-{index}", f"进行中任务 {index + 1}", start, end,
                        category=["event", "solo_raid", "coop", "recruit", "event"][index % 5],
                        banner_url="", start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                    )
                    service._activities[event.event_id] = event
                for index in range(4):
                    start = NOW + timedelta(days=1 + index)
                    end = start + timedelta(days=5)
                    event = CalendarActivity(
                        f"nxt-{index}", f"预告任务 {index + 1}", start, end,
                        category="union_raid", banner_url="",
                        start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                    )
                    service._activities[event.event_id] = event
            elif name == "dynamic-10-active":
                for index in range(10):
                    start = NOW - timedelta(days=1)
                    end = NOW + timedelta(days=index + 2)
                    event = CalendarActivity(
                        f"act-{index}", f"进行中任务 {index + 1}", start, end,
                        category=["event", "solo_raid", "coop", "recruit", "event"][index % 5],
                        banner_url="", start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                    )
                    service._activities[event.event_id] = event
            elif name == "dynamic-12-active-6-next":
                for index in range(12):
                    start = NOW - timedelta(days=1)
                    end = NOW + timedelta(days=index + 2)
                    event = CalendarActivity(
                        f"act-{index}", f"进行中任务 {index + 1}", start, end,
                        category=["event", "solo_raid", "coop", "recruit", "event"][index % 5],
                        banner_url="", start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                    )
                    service._activities[event.event_id] = event
                for index in range(6):
                    start = NOW + timedelta(days=1 + index)
                    end = start + timedelta(days=5)
                    event = CalendarActivity(
                        f"nxt-{index}", f"预告任务 {index + 1}", start, end,
                        category="union_raid", banner_url="",
                        start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                    )
                    service._activities[event.event_id] = event
            elif name == "dynamic-20-active":
                for index in range(20):
                    start = NOW - timedelta(days=1)
                    end = NOW + timedelta(days=index + 2)
                    event = CalendarActivity(
                        f"act-{index}", f"进行中任务 {index + 1}", start, end,
                        category=["event", "solo_raid", "coop", "recruit", "event"][index % 5],
                        banner_url="", start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                    )
                    service._activities[event.event_id] = event
            elif name == "dynamic-long-titles":
                for index in range(8):
                    start = NOW - timedelta(days=1)
                    end = NOW + timedelta(days=index + 2)
                    long_title = f"长标题动态测试作战：第{index + 1}号深度调查与重点收缴特别行动项目"
                    event = CalendarActivity(
                        f"long-{index}", long_title, start, end,
                        category="event", banner_url="",
                        start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                    )
                    service._activities[event.event_id] = event

            elif name == "4-active-8-next":
                for index in range(4):
                    start = NOW - timedelta(days=1)
                    end = NOW + timedelta(days=index + 3)
                    event = CalendarActivity(
                        f"act-{index}", f"混合活动-进行中 {index + 1}", start, end,
                        category="event", banner_url="",
                        start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                    )
                    service._activities[event.event_id] = event
                for index in range(8):
                    start = NOW + timedelta(days=1 + index)
                    end = start + timedelta(days=5)
                    event = CalendarActivity(
                        f"nxt-{index}", f"混合活动-预告 {index + 1}", start, end,
                        category="union_raid", banner_url="",
                        start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                    )
                    service._activities[event.event_id] = event
            elif name == "next-only":
                for index in range(5):
                    start = NOW + timedelta(days=2 + index * 2)
                    end = start + timedelta(days=7)
                    event = CalendarActivity(
                        str(index), f"仅预告活动 {index + 1}", start, end,
                        category="recruit", banner_url="",
                        start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                    )
                    service._activities[event.event_id] = event
            elif name == "unknown-end":
                for index in range(3):
                    ev = CanonicalEvent(
                        id=f"unk-{index}",
                        title=f"未知截止活动 {index + 1}",
                        event_type="event",
                        start_at=NOW - timedelta(days=2),
                        end_at=None,
                        start_precision="EXACT",
                        end_precision="UNKNOWN",
                    )
                    service._events[ev.id] = ev
            elif name == "date-only":
                for index in range(3):
                    start = NOW - timedelta(days=2)
                    end = NOW + timedelta(days=3 + index)
                    event = CalendarActivity(
                        str(index), f"日期级活动 {index + 1}", start, end,
                        category="event", banner_url="",
                        start_precision=TimePrecision.DATE_ONLY, end_precision=TimePrecision.DATE_ONLY
                    )
                    service._activities[event.event_id] = event
            elif name == "critical":
                # 1 item ending in 30 minutes (critical urgency)
                event0 = CalendarActivity(
                    "crit-0", "紧急截止突袭任务", NOW - timedelta(days=2), NOW + timedelta(minutes=30),
                    category="solo_raid", banner_url="",
                    start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                )
                service._activities[event0.event_id] = event0
                event1 = CalendarActivity(
                    "norm-1", "普通进行中活动", NOW - timedelta(days=1), NOW + timedelta(days=4),
                    category="event", banner_url="",
                    start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                )
                service._activities[event1.event_id] = event1
            elif name == "long-title":
                for index in range(4):
                    start = NOW - timedelta(days=2) if index < 2 else NOW + timedelta(days=index * 2)
                    end = NOW + timedelta(hours=8) if index == 0 else start + timedelta(days=5)
                    title = f"合成活动：较长标题与完整说明测试文本第{index + 1}号活动"
                    event = CalendarActivity(
                        str(index), title, start, end,
                        category="event", banner_url="",
                        start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                    )
                    service._activities[event.event_id] = event
            elif name == "oversize-title":
                huge_title = "超规格长标题测试作战：这是一个异常超长的活动标题，旨在检验固定高度毛玻璃面板在极端长标题情况下的单项超页与两行视觉截断降级策略，不应该突破固定Panel边框，同时完整标题应当妥善保留在full_title中"
                event0 = CalendarActivity(
                    "over-0", huge_title, NOW - timedelta(days=1), NOW + timedelta(days=3),
                    category="event", banner_url="",
                    start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                )
                service._activities[event0.event_id] = event0
                event1 = CalendarActivity(
                    "norm-1", "常规活动", NOW - timedelta(days=1), NOW + timedelta(days=4),
                    category="event", banner_url="",
                    start_precision=TimePrecision.EXACT, end_precision=TimePrecision.EXACT
                )
                service._activities[event1.event_id] = event1

        days_val = 7 if name == "7-days" else 30 if name == "30-days" else 14
        result[name] = CalendarT2IPayloadBuilder().build(service, days_val, NOW)
    return result


def get_cases(page, directory):
    if page == "calendar_schedule":
        return calendar_cases(directory)
    if page == "union_overview":
        return union_overview_cases()
    if page in ("union_records", "union_member"):
        return union_records_cases(page)
    if page == "profile":
        return profile_cases()
    if page == "character":
        return character_cases()
    raise ValueError(page)


def union_overview_cases():
    from astrbot_plugin_nikke.features.raid.builder import UnionRaidBuilder
    result = {}
    for name in ("normal", "defeated", "missing-asset", "partial-hp", "unknown-coverage", "long-name", "empty"):
        bosses = [{"boss_id": str(index + 1), "name_localvalues": {"zh-cn": "合成测试 Boss " + str(index + 1)},
                   "current_hp": 200000000, "max_hp": 500000000, "element_id": ["UNKNOWN"]} for index in range(5)]
        if name == "defeated":
            bosses[0]["current_hp"] = 0
        if name == "partial-hp":
            bosses[1]["max_hp"] = None
        if name == "long-name":
            bosses[0]["name_localvalues"]["zh-cn"] = "合成测试：长名称的超大型机械目标"
        payload = {"level_info": [{"difficulty": 2, "level": 7, "boss_info": bosses}],
                   "manager_info": {"season_end_date": "2026-09-20T12:00:00+08:00"}}
        if name == "empty":
            payload = {}
        if name == "unknown-coverage":
            payload["level_info"] *= 2
        result[name] = UnionRaidBuilder().build(guild_name="合成联盟 · 非真实数据", level_info_payload=payload,
                                               fetched_at="2026-09-13 12:00", plugin_version="T2I PREVIEW")
    import copy
    from astrbot_plugin_nikke.features.raid.boss_resolver import BossAssetResolver
    records = BossAssetResolver(Path(__file__).resolve().parents[1] / "data/nikke/blabla-assets").manifest_records
    known = copy.deepcopy(result["normal"])
    unique = list({item["icon_id"]: item for item in records if item.get("season_id") == "1000035"}.values())
    assert len(unique) == 5
    for boss, entry in zip(known.bosses, unique):
        boss.boss_id, boss.name = entry["boss_id"], entry["display_name"]
        boss.icon_id, boss.monster_model_id = entry["icon_id"], entry["monster_model_id"]
    result["with-boss-assets"] = known
    return result


def character_cases():
    import json
    import copy
    from astrbot_plugin_nikke.features.character.builder import CharacterCardBuilder
    from astrbot_plugin_nikke.features.character.master_resolver import CharacterMasterResolver
    root = Path(__file__).resolve().parents[1]
    fixture = json.loads((root / "tests" / "fixtures" / "character_details_sanitized.json").read_text(encoding="utf-8"))
    master = CharacterMasterResolver()
    result = {}
    for name, resource in (("c010", 10), ("c010_02", 10), ("c010_03", 10), ("c017", 17), ("c234", 234), ("c330", 330), ("c352", 352), ("c471", 471), ("representative-dark", 10), ("representative-light", 330), ("bright", 330), ("dark", 10), ("low-saturation", 352), ("wide-pose", 471),
                           ("long-name", 330), ("missing-optional", 10), ("missing-art", 470), ("ol-max", 330),
                           ("nayuta", 223), ("low-ol", 10), ("max-ol", 330)):
        canonical = master.resolve_resource_id(resource)
        directory = {"resource_id": canonical.resource_id, "name_code": canonical.name_code, "name_cn": canonical.name_cn,
                     "name_en": canonical.name_en, "element": canonical.element, "weapon": canonical.weapon,
                     "burst": canonical.burst, "corporation": canonical.corporation, "rare": canonical.rare}
        if name == "long-name":
            directory["name_cn"] = "合成长名称边界示例：完整角色名称与身份说明"
        detail, roster = copy.deepcopy(fixture["character_details"][0]), copy.deepcopy(fixture["roster_item"])
        detail["name_code"] = roster["name_code"] = canonical.name_code
        detail.pop("costume_tid", None)
        detail["costume_id"] = {"c010_02": 20001, "c010_03": 10005}.get(name, 0)
        effects = copy.deepcopy(fixture["state_effects"])
        if name == "missing-optional":
            detail["favorite_item_tid"] = detail["harmony_cube_tid"] = 0
        elif name == "low-ol":
            detail["torso_equip_option1_id"] = detail["torso_equip_option2_id"] = detail["torso_equip_option3_id"] = 0
            detail["arm_equip_option1_id"] = detail["arm_equip_option2_id"] = detail["arm_equip_option3_id"] = 0
            detail["leg_equip_option1_id"] = detail["leg_equip_option2_id"] = detail["leg_equip_option3_id"] = 0
            detail["head_equip_option1_id"] = 7000813
            detail["head_equip_option2_id"] = 7000508
            detail["head_equip_option3_id"] = 0
        elif name == "max-ol":
            max_effects = [
                {"id": "80001", "function_details": [{"function_type": "StatAtk", "function_value": 1181, "function_value_type": "Percent", "level": 11}]},
                {"id": "80002", "function_details": [{"function_type": "IncElementDmg", "function_value": 2356, "function_value_type": "Percent", "level": 11}]},
                {"id": "80003", "function_details": [{"function_type": "StatAmmoLoad", "function_value": 6893, "function_value_type": "Percent", "level": 11}]},
                {"id": "80004", "function_details": [{"function_type": "StatCriticalDamage", "function_value": 1422, "function_value_type": "Percent", "level": 11}]},
                {"id": "80005", "function_details": [{"function_type": "StatCriticalRate", "function_value": 560, "function_value_type": "Percent", "level": 11}]},
                {"id": "80006", "function_details": [{"function_type": "StatHitRate", "function_value": 1181, "function_value_type": "Percent", "level": 11}]},
                {"id": "80007", "function_details": [{"function_type": "StatChargeDamage", "function_value": 1181, "function_value_type": "Percent", "level": 11}]},
                {"id": "80008", "function_details": [{"function_type": "StatChargeTime", "function_value": -320, "function_value_type": "Percent", "level": 11}]},
                {"id": "80009", "function_details": [{"function_type": "StatDef", "function_value": 1181, "function_value_type": "Percent", "level": 11}]},
                {"id": "80010", "function_details": [{"function_type": "CustomStatA", "function_value": 1000, "function_value_type": "Percent", "level": 10}]},
                {"id": "80011", "function_details": [{"function_type": "CustomStatB", "function_value": 1200, "function_value_type": "Percent", "level": 10}]},
            ]
            effects.extend(max_effects)
            detail["head_equip_option1_id"] = 80001
            detail["head_equip_option2_id"] = 80002
            detail["head_equip_option3_id"] = 80003
            detail["torso_equip_option1_id"] = 80004
            detail["torso_equip_option2_id"] = 80005
            detail["torso_equip_option3_id"] = 80006
            detail["arm_equip_option1_id"] = 80007
            detail["arm_equip_option2_id"] = 80008
            detail["arm_equip_option3_id"] = 80009
            detail["leg_equip_option1_id"] = 80010
            detail["leg_equip_option2_id"] = 80011
            detail["leg_equip_option3_id"] = 0
        data = CharacterCardBuilder().build(account={"nickname": "合成练度 · 非真实账号"}, directory=directory,
                                            payload={"roster_item": roster, "detail": detail, "state_effects": effects},
                                            fetched_at="2026-09-13 12:00", plugin_version="T2I PREVIEW")
        if name == "max-ol":
            from astrbot_plugin_nikke.features.character.models import OptionSummary
            data.option_totals.extend([
                OptionSummary(display_name="额外装弹数增加", unit="percent", value=20.0),
                OptionSummary(display_name="额外攻击力增加", unit="percent", value=15.0),
            ])
        result[name] = data
    return result


def profile_cases():
    from astrbot_plugin_nikke.features.profile.builder import ProfileBuilder
    from astrbot_plugin_nikke.features.profile.currency_registry import CurrencyRegistry
    result = {}
    for name in ("full", "full-current-model", "today-partial", "resource-partial", "research-long-names", "zero-empty", "unavailable", "long-commander"):
        basic = {"nickname": "合成指挥官 · 非真实账号", "lv": 382, "team_combat": 1286600, "character_count": 187,
                 "progress_normal_campaign": "46-40", "progress_hard_campaign": "35-36", "created_at": "2023-01-16T00:00:00+08:00",
                 "currencies": [{"type": kind, "value": (index + 1) * 12345} for index, kind in enumerate(CurrencyRegistry.DEFINITIONS)]}
        outpost = {"synchro_level": 441, "outpost_battle_level": 318, "infra_core_level": "20", "jukebox_count": 58,
                   "recycle_room_researches": [{"tid": str(tid), "lv": 101, "exp": 0} for tid in (1101, 1102, 1103, 1201, 1202, 1203, 1204)]}
        daily = {"outpost_battle_storage_fullness": 0.72, "intercept_remaining_tickets": 3, "rookie_arena_remaining_count": 5,
                 "special_arena_remaining_count": 0, "counsel_remaining_count": 7, "dispatch_completed_count": 4, "dispatch_in_progress_count": 2,
                 "sim_room_daily_best_record": {"chapter": 3, "difficulty": 5, "score": 12345},
                 "tower_daily_info_list": [
                     {"type": 1, "is_opened": False, "remaining_count": 3},
                     {"type": 2, "is_opened": False, "remaining_count": 3},
                     {"type": 3, "is_opened": True, "remaining_count": 3},
                     {"type": 4, "is_opened": False, "remaining_count": 3},
                 ]}
        if name == "full-current-model":
            # 完整合成示例只使用当前 Builder 已验证的字段，不代表真实账号。
            basic.update(character_costume_count=87, progress_tribe_tower="318",
                         sim_room_overclock_current_sub_season_high_score="12345",
                         sim_room_overclock_latest_season_high_score="23456")
            outpost["memorial_counts"] = [{"category": key, "count": value} for key, value in
                                           (("handwriting", 72), ("calllog", 48), ("data", 120))]
            daily["tower_daily_info_list"] = [
                {"type": 1, "is_opened": False, "remaining_count": 3},
                {"type": 2, "is_opened": False, "remaining_count": 3},
                {"type": 3, "is_opened": True, "remaining_count": 3},
                {"type": 4, "is_opened": False, "remaining_count": 3},
            ]
        if name == "today-partial":
            daily["intercept_remaining_tickets"] = "unverified"
        if name == "resource-partial":
            basic["currencies"][0]["value"] = None
        if name == "zero-empty":
            basic["currencies"] = [{"type": 99, "value": 0}]
            outpost["recycle_room_researches"] = []
            daily["dispatch_completed_count"] = 0
        if name == "unavailable":
            daily, outpost = None, {}
        if name == "long-commander":
            basic["nickname"] = "合成长指挥官名称，用于验证自然换行与信息层级。" * 4
        data = ProfileBuilder().build(account={"area_id": "SYNTHETIC-AREA"} if name == "full-current-model" else {}, basic=basic, outpost=outpost, roster=[{"lv": 441, "combat": 269885}],
                                      fetched_at="2026-09-13 12:00", plugin_version="T2I PREVIEW", daily=daily,
                                      outpost_available=name != "unavailable", daily_available=name != "unavailable", roster_available=True)
        if name == "research-long-names":
            for item in data.recycle_room_researches:
                item.presentation_name = "合成长研究名称：同一行保留完整名称与等级"
        result[name] = data
    result["partial"] = result["today-partial"]
    return result


def union_records_cases(page):
    from astrbot_plugin_nikke.features.raid.participants import build_ranking, build_member_ranking
    result = {}
    cases = ("normal", "long-name", "tie-rank", "many-members", "unattacked-members", "all-attacked", "empty") if page == "union_records" else ("with-portraits", "1-record", "2-records", "3-records", "many-records", "empty")
    for name in cases:
        count = {"1-record": 1, "2-records": 2, "3-records": 3, "many-records": 10, "many-members": 35, "empty": 0}.get(name, 5)
        rows = []
        for index in range(count):
            rows.append({"openid": "synthetic-member" if page == "union_member" else f"synthetic-{index}",
                         "nickname": "合成长名称成员用于验证名称自然换行 " * 4 if name == "long-name" else f"合成成员 {index + 1}",
                         "boss_id": str(100 + index), "day": 1, "difficulty": 2, "level": 7, "step": 3,
                         "total_damage": 123456789 if name == "tie-rank" else 123456789 + index * 10000000,
                         "is_final_hit": index == 0, "squad": [{"tid": tid, "slot": slot, "lv": 441, "combat": 232663 + slot * 1000}
                         for slot, tid in enumerate([433004, 301704, 447105, 423401, 235207], 1)]})
        if name == "with-portraits":
            for row in rows:
                row["boss_id"] = "2420020214"
                row["squad"][0].update(tid=201004, costume_id=10005)
        payload = {"participate_data": rows}
        if name == "unattacked-members":
            payload["union_members"] = [f"合成成员 {i + 1}" for i in range(count)] + ["未出刀队员 Alpha", "未出刀队员 Beta", "未出刀队员 Gamma"]
        elif name == "all-attacked":
            payload["union_members"] = [f"合成成员 {i + 1}" for i in range(count)]
        result[name] = build_member_ranking(payload, "synthetic-member") if page == "union_member" else build_ranking(payload)
    return result

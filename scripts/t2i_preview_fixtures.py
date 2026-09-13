"""供预览和离线测试共用的合成 DTO；不包含真实账号资料。"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

NOW = datetime(2026, 9, 13, 4, tzinfo=timezone.utc)


def calendar_cases(directory):
    from astrbot_plugin_nikke.calendar_models import CalendarActivity
    from astrbot_plugin_nikke.calendar_service import CalendarService
    from astrbot_plugin_nikke.t2i_payloads import CalendarT2IPayloadBuilder
    result = {}
    for name in ("normal", "7-days", "30-days", "stale", "long-title", "many-events", "empty", "unavailable"):
        service = CalendarService(Path(directory) / name)
        service._has_snapshot = name != "unavailable"
        service.last_updated_at = NOW.isoformat()
        service.last_sync_error = "合成同步失败示例" if name == "stale" else ""
        if name not in ("empty", "unavailable"):
            for index in range(24 if name == "many-events" else 5):
                start = NOW - timedelta(days=2) if index < 2 else NOW + timedelta(days=index * 3)
                end = NOW + timedelta(hours=8) if index == 0 else start + timedelta(days=7)
                if name == "many-events":
                    start, end = NOW - timedelta(days=1), NOW + timedelta(days=index + 1)
                event = CalendarActivity(str(index), ("合成活动：长标题与完整说明，不应截断或隐藏活动 " * 4) if name == "long-title" else f"合成活动 {index + 1}", start, end,
                                         category=["coop", "union_raid", "solo_raid", "recruit", "event"][index % 5], banner_url="https://invalid.example/banner.png")
                service._activities[event.event_id] = event
        result[name] = CalendarT2IPayloadBuilder().build(service, 7 if name == "7-days" else 30 if name == "30-days" else 14, NOW)
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
    from astrbot_plugin_nikke.union_raid_builder import UnionRaidBuilder
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
    from astrbot_plugin_nikke.boss_asset_resolver import BossAssetResolver
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
    from astrbot_plugin_nikke.card_builder import CharacterCardBuilder
    from astrbot_plugin_nikke.character_master_resolver import CharacterMasterResolver
    root = Path(__file__).resolve().parents[1]
    fixture = json.loads((root / "tests" / "fixtures" / "character_details_sanitized.json").read_text(encoding="utf-8"))
    master = CharacterMasterResolver()
    result = {}
    for name, resource in (("c010", 10), ("c010_02", 10), ("c010_03", 10), ("c017", 17), ("c234", 234), ("c330", 330), ("c352", 352), ("c471", 471), ("representative-dark", 10), ("representative-light", 330), ("bright", 330), ("dark", 10), ("low-saturation", 352), ("wide-pose", 471),
                           ("long-name", 330), ("missing-optional", 10), ("missing-art", 470), ("ol-max", 330)):
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
        if name == "missing-optional":
            detail["favorite_item_tid"] = detail["harmony_cube_tid"] = 0
        data = CharacterCardBuilder().build(account={"nickname": "合成练度 · 非真实账号"}, directory=directory,
                                            payload={"roster_item": roster, "detail": detail, "state_effects": copy.deepcopy(fixture["state_effects"])},
                                            fetched_at="2026-09-13 12:00", plugin_version="T2I PREVIEW")
        result[name] = data
    return result


def profile_cases():
    from astrbot_plugin_nikke.profile_builder import ProfileBuilder
    from astrbot_plugin_nikke.currency_registry import CurrencyRegistry
    result = {}
    for name in ("full", "full-current-model", "today-partial", "resource-partial", "research-long-names", "zero-empty", "unavailable", "long-commander"):
        basic = {"nickname": "合成指挥官 · 非真实账号", "lv": 382, "team_combat": 1286600, "character_count": 187,
                 "progress_normal_campaign": "46-40", "progress_hard_campaign": "35-36", "created_at": "2023-01-16T00:00:00+08:00",
                 "currencies": [{"type": kind, "value": (index + 1) * 12345} for index, kind in enumerate(CurrencyRegistry.DEFINITIONS)]}
        outpost = {"synchro_level": 441, "outpost_battle_level": 318, "infra_core_level": "20", "jukebox_count": 58,
                   "recycle_room_researches": [{"tid": str(tid), "lv": 101, "exp": 0} for tid in (1101, 1102, 1103, 1201, 1202, 1203, 1204)]}
        daily = {"outpost_battle_storage_fullness": 0.72, "intercept_remaining_tickets": 3, "rookie_arena_remaining_count": 5,
                 "special_arena_remaining_count": 0, "counsel_remaining_count": 7, "dispatch_completed_count": 4, "dispatch_in_progress_count": 2,
                 "sim_room_daily_best_record": {"chapter": 3, "difficulty": 5, "score": 12345}}
        if name == "full-current-model":
            # 完整合成示例只使用当前 Builder 已验证的字段，不代表真实账号。
            basic.update(character_costume_count=87, progress_tribe_tower="318",
                         sim_room_overclock_current_sub_season_high_score="12345",
                         sim_room_overclock_latest_season_high_score="23456")
            outpost["memorial_counts"] = [{"category": key, "count": value} for key, value in
                                           (("handwriting", 72), ("calllog", 48), ("data", 120))]
            daily["tower_daily_info_list"] = [{"type": 1, "name": "合成塔开放记录", "is_opened": True, "remaining_count": 3},
                                              {"type": 2, "name": "合成塔关闭记录", "is_opened": False, "remaining_count": 0}]
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
    return result


def union_records_cases(page):
    from astrbot_plugin_nikke.raid_participants import build_ranking, build_member_ranking
    result = {}
    cases = ("normal", "long-name", "tie-rank", "many-members", "empty") if page == "union_records" else ("with-portraits", "1-record", "2-records", "3-records", "many-records", "empty")
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
        result[name] = build_member_ranking(payload, "synthetic-member") if page == "union_member" else build_ranking(payload)
    return result

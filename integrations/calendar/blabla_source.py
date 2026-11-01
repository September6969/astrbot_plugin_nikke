"""BlaBlaLink 官网结构化日程，只读公开接口。"""
from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime, timezone
import httpx
from ...features.calendar.schedule_adapters import BaseScheduleAdapter, FetchResult
from ...features.calendar.canonical_models import CanonicalEvent, FetchOutcome, SourceRole
from ...core.assets.resource_url import game_resource_url

ENDPOINT = "https://api.blablalink.com/api/ugc/direct/standalonesite/Dynamics/GetCalendarDetail"
PAGE = "https://www.blablalink.com/activity-calendar"
TYPES = {
    "PickupGachaEvent": ("recruit", "限时招募"),
    "UnionRaid": ("union_raid", "联盟突袭"),
    "SoloRaid": ("solo_raid", "个人突袭"),
    "CooperationEvent": ("coop", "协同作战"),
    "FieldHubEvent": ("story_event", "剧情活动"),
    "StoryEvent": ("story_event", "剧情活动"),
    "EventPass": ("pass", "活动通行证"),
    "SeasonPass": ("pass", "月度通行证"),
    "BoxGachaEvent": ("costume_gacha", "转盘时装"),
    "LoginEvent": ("login", "限时签到"),
}

class BlablaCalendarAdapter(BaseScheduleAdapter):
    source_name = "blabla"
    source_role = SourceRole.PRIMARY

    def __init__(self, *, transport=None):
        self.transport = transport

    @staticmethod
    def parse(payload):
        if not isinstance(payload, dict) or type(payload.get("code")) is not int or payload["code"] != 0:
            raise ValueError("官方日程响应失败")
        data = payload.get("data")
        required = {"arena", "character_gacha", "raid", "simulation_room", "skin_gacha", "version_event"}
        if not isinstance(data, dict) or not required.issubset(data):
            raise ValueError("官方日程栏目不完整")
        events, invalid, excluded = {}, 0, 0
        now = datetime.now(timezone.utc)
        for module in data.values():
            if not isinstance(module, dict) or not isinstance(module.get("items"), list):
                raise ValueError("官方日程栏目结构异常")
            for row in module["items"]:
                if not isinstance(row, dict):
                    invalid += 1
                    continue
                kind = row.get("type")
                if kind not in TYPES:
                    excluded += 1
                    continue
                try:
                    def timestamp(key):
                        value = row.get(key)
                        if isinstance(value, bool) or not re.fullmatch(r"[0-9]{9,11}", str(value)):
                            raise ValueError("时间戳无效")
                        return datetime.fromtimestamp(int(value), timezone.utc)
                    start, end = timestamp("start_time"), timestamp("end_time")
                    if end <= start:
                        raise ValueError("时间区间无效")
                    category, label = TYPES[kind]
                    name = str(row.get("name") or "").strip()
                    if not name:
                        raise ValueError("名称缺失")
                    characters = row.get("characters") or []
                    identities = sorted(str(x.get("name_code")) for x in characters if isinstance(x,dict))
                    character_names = "、".join(str(x.get("name") or "") for x in characters if isinstance(x,dict))
                    detail = character_names if kind == "PickupGachaEvent" else (str(row.get("costume_name") or name) if kind == "BoxGachaEvent" else name)
                    # 跨栏目相同签到共享身份，不同角色招募及并行剧情独立保留。
                    identity = [kind, int(start.timestamp()), int(end.timestamp()), identities, row.get("resource_id"), row.get("costume_index"), name]
                    if kind == "LoginEvent" and isinstance(row.get("banner"),str) and row["banner"]:
                        identity = [kind,int(start.timestamp()),int(end.timestamp()),row["banner"]]
                    key = "blabla:" + hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:24]
                    banner = row.get("banner")
                    image = None
                    if isinstance(banner,str) and re.fullmatch(r"[A-Za-z0-9_]{1,160}", banner):
                        path = "icon/Logo/pass" if kind == "SeasonPass" else "schedule/banner"
                        image = game_resource_url(f"{path}/{banner}.webp")
                    title = label if kind in ("UnionRaid","SoloRaid","CooperationEvent","LoginEvent") else f"{label} · {detail}".rstrip(" ·")
                    if key in events:
                        continue
                    events[key] = CanonicalEvent(id=key,title=title,event_type=category,start_at=start,end_at=end,
                        banner_url=image,detail_url=PAGE,sources=["blabla"],primary_source="blabla",confidence=1.0,
                        metadata={"category":category,"official_type":kind,"key_visual_url":image,"source_title":name},fetched_at=now)
                except (ValueError, TypeError, OverflowError, OSError):
                    invalid += 1
        if invalid and not events:
            raise ValueError("官方日程没有可验证的有效事件")
        return FetchResult(FetchOutcome.SUCCESS_DATA if events else FetchOutcome.SUCCESS_EMPTY,
            source="blabla",events=list(events.values()),completeness="PARTIAL" if invalid else "COMPLETE",
            diagnostics={"invalid":invalid,"excluded":excluded})

    async def fetch(self):
        return (await self.fetch_result()).events

    async def fetch_result(self):
        async with httpx.AsyncClient(timeout=15, transport=self.transport) as client:
            response = await client.post(ENDPOINT,json={},headers={"Origin":"https://www.blablalink.com","Referer":PAGE,"X-Language":"zh-TW","X-Channel-Type":"2"})
            response.raise_for_status()
            return self.parse(response.json())

"""按会话和用户隔离的日程截止订阅，复用持久化投递状态机。"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

from ..announcement.delivery import AnnouncementDelivery, PlannedPush, aware
from .content_quality import canonical_event_title, calendar_display_title


class CalendarSubscriptions(AnnouncementDelivery):
    SETTING = "calendar_subscriptions_v1"
    TYPES = {
        "协同": {"coop"}, "个人突袭": {"solo_raid"}, "联盟突袭": {"union_raid"},
        "支线": {"event", "story_event"}, "招募": {"recruit"}, "Pass": {"monthly_pass", "event_pass"},
        "月度Pass": {"monthly_pass"}, "活动Pass": {"event_pass"},
        "转盘": {"costume_gacha"}, "双倍": {"double_reward"}, "维护": {"maintenance"},
        "签到": {"login"}, "免费": {"free_reward"},
    }
    ALIASES = {"协同作战": "协同", "单人突袭": "个人突袭", "支线活动": "支线",
               "pickup": "招募", "pick up": "招募", "pass": "Pass", "月度pass": "月度Pass",
               "活动pass": "活动Pass", "转盘时装": "转盘", "gacha": "转盘", "限时双倍": "双倍",
               "停机维护": "维护", "限时签到": "签到", "免费获取": "免费"}
    HELP = ("日程订阅默认提前24小时提醒，每个事件一次。群内只@订阅者。\n"
            "可选类型：协同、个人突袭、联盟突袭、支线、招募、月度Pass、活动Pass、Pass（两者）、转盘、双倍、维护、签到、免费\n"
            "开启或更换：/妮姬 日程 订阅 协同,个人突袭,签到\n"
            "查看：/妮姬 日程 订阅状态\n取消：/妮姬 日程 取消订阅")

    def __init__(self, store, calendar):
        super().__init__(store)
        self.calendar = calendar

    @staticmethod
    def target_key(context):
        if not context.conversation_id or not context.actor_id:
            raise ValueError("当前会话无法保存订阅，请在支持主动消息的会话内重试。")
        return json.dumps([context.conversation_id, context.actor_id, context.is_private_chat], ensure_ascii=False)

    def command(self, context, action, value=""):
        target = self.target_key(context)
        if action in {"取消订阅", "unsubscribe"}:
            self.unsubscribe(target)
            return "已取消你在当前会话的日程提醒。"
        if action in {"订阅状态", "subscription"}:
            preference = self._state()["targets"].get(target, {})
            if not preference.get("enabled"):
                return "你在当前会话尚未开启日程订阅。\n" + self.HELP
            names = "、".join(preference["categories"])
            return f"已订阅：{names}\n提前24小时提醒，每个事件一次。\n取消：/妮姬 日程 取消订阅"
        if not value.strip():
            return self.HELP
        names = []
        for part in re.split(r"[,，、\s]+", value.strip()):
            name = self.ALIASES.get(part.casefold(), part)
            if name not in self.TYPES:
                raise ValueError(f"未知事件类型：{part}\n" + self.HELP)
            if name not in names:
                names.append(name)
        # 更新类型不清除已发送记录，也不为任何其他用户或会话开通。
        self.subscribe(target, (), reminder_hours=(24,))
        state = self._state()
        state["targets"][target]["categories"] = names
        self.store.set_setting(self.SETTING, state)
        return "已开启你在当前会话的日程提醒：" + "、".join(names) + "。\n提前24小时提醒，每个事件一次。群内只@你。"

    def plan(self, records=(), deadlines=(), *, now=None):
        current = aware(now or datetime.now(timezone.utc))
        if self.calendar is None or not self.calendar.has_snapshot():
            return []
        context = self.calendar.freeze_query_context(current)
        # 数据过期或来源失败时暂停主动通知，避免拿旧截止时间催促用户。
        if context.freshness != "FRESH" or self.calendar.last_sync_error:
            return []
        from .time_rules import CalendarTimeRules
        events = CalendarTimeRules.reminder_deadlines(context.events, current)
        state = self._state()
        pushes = []
        for target, preference in state["targets"].items():
            if not preference.get("enabled"):
                continue
            categories = set().union(*(self.TYPES.get(name, set()) for name in preference.get("categories", [])))
            for event in events:
                event_type = event.event_type
                if event_type == "pass":
                    monthly = re.search(r"(?:\d{1,2}月|january|february|march|april|may|june|july|august|september|october|november|december).*pass", event.title, re.I)
                    event_type = "monthly_pass" if monthly else "event_pass"
                if event_type not in categories or not timedelta(0) < event.end_at-current <= timedelta(hours=24):
                    continue
                # 不把版本号或正文变动放入键；同一期活动改文案、改结束时间不会再@。
                start_day = event.start_at.date().isoformat() if event.start_at else "unknown"
                identity = json.dumps([event.server_scope, event.event_type, canonical_event_title(event.title), start_day], ensure_ascii=False)
                entity = hashlib.sha256(identity.encode("utf-8")).hexdigest()
                end = event.end_at.astimezone(timezone(timedelta(hours=8))).strftime("%m/%d %H:%M")
                hours = max(1, int((event.end_at-current).total_seconds()/3600))
                text = f"【日程即将结束】{calendar_display_title(event.title)}\n结束时间：{end}（北京时间），剩余不足{hours+1}小时。\n/妮姬 日程 查看详情；/妮姬 日程 取消订阅 停止提醒。"
                push = PlannedPush(target, entity, 1, "calendar_deadline", text, 24)
                if push.key not in state["delivered"] and push.key not in state["dispatch_intents"]:
                    pushes.append(push)
        return pushes

    async def dispatch_due(self, sender, *, now=None):
        if not any(item.get("enabled") for item in self._state()["targets"].values()):
            return {"succeeded": 0, "failed": 0, "unknown": 0}
        async def send(target, text):
            preference = self._state()["targets"].get(target, {})
            if not preference.get("enabled"):
                return False
            conversation, actor, private = json.loads(target)
            return await sender(conversation, actor, private, text)
        return await self.dispatch((), (), send, now=now)

"""公告投递规划与可注入发送器；构造服务不会发消息。"""
import asyncio
import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone


def aware(value):
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(parsed, datetime) or parsed.tzinfo is None:
        raise ValueError("投递时间必须包含时区")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class PlannedPush:
    target: str
    entity_id: str
    version: int
    push_type: str
    text: str
    reminder_hour: int | None = None

    @property
    def key(self):
        # 不用分隔符拼接，避免目标和内容 ID 内含冒号造成碰撞。
        parts = [self.target, self.entity_id, self.version, self.push_type, self.reminder_hour]
        return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode("utf-8")).hexdigest()


class AnnouncementDelivery:
    SETTING = "announcement_delivery_v1"

    def __init__(self, store):
        self.store = store
        self._dispatch_lock = asyncio.Lock()

    def _state(self):
        return self.store.get_setting(self.SETTING, {"targets": {}, "delivered": {}})

    def subscribe(self, target, records, *, now=None, reminder_hours=(24, 6, 1)):
        if not isinstance(target, str) or not target.strip():
            raise ValueError("订阅目标为空")
        hours = sorted(set(reminder_hours), reverse=True)
        if any(type(hour) is not int or not 1 <= hour <= 168 for hour in hours):
            raise ValueError("提醒时窗超出范围")
        state = self._state()
        old = state["targets"].get(target)
        if old and old["enabled"]:
            # 更新偏好不重置首次订阅基线，避免吞掉尚未发送的新版本。
            old["reminder_hours"] = hours
        else:
            state["targets"][target] = {
                "enabled": True, "subscribed_at": aware(now or datetime.now(timezone.utc)).isoformat(),
                "baseline": {record.content_id: record.content_version for record in records},
                "reminder_hours": hours,
            }
        self.store.set_setting(self.SETTING, state)

    def unsubscribe(self, target):
        state = self._state()
        if target in state["targets"]:
            state["targets"][target]["enabled"] = False
            self.store.set_setting(self.SETTING, state)

    def plan(self, records, deadlines=(), *, now=None):
        now = aware(now or datetime.now(timezone.utc))
        state = self._state()
        planned = {}
        for target, preference in state["targets"].items():
            if not preference["enabled"]:
                continue
            subscribed = aware(preference["subscribed_at"])
            for record in records:
                baseline = preference["baseline"].get(record.content_id)
                if baseline is not None:
                    if record.content_version <= baseline:
                        continue
                else:
                    try:
                        published = aware(record.published_at)
                    except (ValueError, TypeError):
                        continue
                    if not max(subscribed, now - timedelta(days=14)) <= published <= now:
                        continue
                push = PlannedPush(target, record.content_id, record.content_version, "announcement",
                    f"【官方公告】{record.title}\n{record.source_url}")
                if push.key not in state["delivered"]:
                    planned[push.key] = push
            for deadline in deadlines:
                end = aware(deadline.end_at)
                if end <= now:
                    continue
                for hour in preference["reminder_hours"]:
                    due = end - timedelta(hours=hour)
                    # 只在到期后的短窗口提醒；重启不补发早已错过的提醒。
                    if due < subscribed or not due <= now < min(end, due + timedelta(minutes=15)):
                        continue
                    push = PlannedPush(target, deadline.event_id, deadline.deadline_version, "deadline",
                        f"【截止提醒】{deadline.name}\n{deadline.remaining_display(now)}\n{deadline.source_url}", hour)
                    if push.key not in state["delivered"]:
                        planned[push.key] = push
        return list(planned.values())

    async def dispatch(self, records, deadlines, sender, *, now=None, limit=20):
        """sender(target, text) 必须显式返回 True；只有确认成功才保存 PushRecord。"""
        if not 1 <= limit <= 100:
            raise ValueError("单轮投递数量超限")
        async with self._dispatch_lock:
            succeeded = failed = 0
            for push in self.plan(records, deadlines, now=now)[:limit]:
                if not self._state()["targets"].get(push.target, {}).get("enabled"):
                    continue
                try:
                    accepted = await sender(push.target, push.text)
                except Exception:
                    failed += 1
                    continue
                if accepted is not True:
                    failed += 1
                    continue
                state = self._state()
                record = asdict(push)
                record.pop("text")
                record["pushed_at"] = datetime.now(timezone.utc).isoformat()
                state["delivered"][push.key] = record
                self.store.set_setting(self.SETTING, state)
                succeeded += 1
            return {"succeeded": succeeded, "failed": failed}

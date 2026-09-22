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
    DISPATCH_INTENT = "DISPATCH_INTENT"
    CONFIRMED_SUCCESS = "CONFIRMED_SUCCESS"
    CONFIRMED_FAILURE = "CONFIRMED_FAILURE"
    UNKNOWN_AFTER_ACTION = "UNKNOWN_AFTER_ACTION"

    def __init__(self, store):
        self.store = store
        self._dispatch_lock = asyncio.Lock()

    def _state(self):
        state = self.store.get_setting(
            self.SETTING,
            {"targets": {}, "delivered": {}, "dispatch_intents": {}, "retry_after": {}},
        )
        if not isinstance(state, dict):
            raise ValueError("公告投递状态损坏")
        # 新字段采用 additive 方式，旧设置在下一次写入时自然补齐。
        for field in ("targets", "delivered", "dispatch_intents", "retry_after"):
            if field not in state:
                state[field] = {}
            if not isinstance(state[field], dict):
                raise ValueError(f"公告投递状态字段损坏: {field}")
        return state

    @classmethod
    def _intent_record(cls, push, current):
        record = asdict(push)
        record.pop("text")
        record.update({"status": cls.DISPATCH_INTENT, "intent_at": current.isoformat()})
        return record

    def _persist_intent(self, push, current):
        state = self._state()
        if push.key in state["delivered"] or push.key in state["dispatch_intents"]:
            return False
        state["dispatch_intents"][push.key] = self._intent_record(push, current)
        # 没有持久化 intent 就不能调用外部 sender；这是发送前的 fail-closed 闸门。
        self.store.set_setting(self.SETTING, state)
        return True

    def _mark_unknown(self, push_key, current, reason):
        state = self._state()
        intent = state["dispatch_intents"].get(push_key)
        if not isinstance(intent, dict):
            return False
        intent["status"] = self.UNKNOWN_AFTER_ACTION
        intent["unknown_at"] = current.isoformat()
        intent["detail"] = str(reason)[:500]
        state["retry_after"].pop(push_key, None)
        try:
            self.store.set_setting(self.SETTING, state)
        except Exception:
            # 原有 DISPATCH_INTENT 仍然存在时同样禁止重放；不能为了写诊断再冒险发送。
            return False
        return True

    def _recover_orphaned_intents(self, current):
        """重启后显式标记未决意图为未知，并继续阻止自动重放。"""
        state = self._state()
        recovered = 0
        for intent in state["dispatch_intents"].values():
            if not isinstance(intent, dict) or intent.get("status") != self.DISPATCH_INTENT:
                continue
            intent["status"] = self.UNKNOWN_AFTER_ACTION
            intent["unknown_at"] = current.isoformat()
            intent["detail"] = "recovered unresolved dispatch intent"
            recovered += 1
        if recovered:
            # 恢复状态未能落盘时直接失败，不能继续调用外部 sender。
            self.store.set_setting(self.SETTING, state)
        return recovered

    def _commit_failure(self, push_key, current):
        state = self._state()
        intent = state["dispatch_intents"].get(push_key)
        if not isinstance(intent, dict):
            return False
        intent["status"] = self.CONFIRMED_FAILURE
        intent["resolved_at"] = current.isoformat()
        state["dispatch_intents"].pop(push_key, None)
        state["retry_after"][push_key] = (current + timedelta(minutes=5)).isoformat()
        self.store.set_setting(self.SETTING, state)
        return True

    def _commit_success(self, push, current):
        state = self._state()
        intent = state["dispatch_intents"].get(push.key)
        if not isinstance(intent, dict):
            return False
        record = {key: value for key, value in intent.items() if key not in {"status", "detail"}}
        record["status"] = self.CONFIRMED_SUCCESS
        record["pushed_at"] = current.isoformat()
        state["delivered"][push.key] = record
        state["dispatch_intents"].pop(push.key, None)
        state["retry_after"].pop(push.key, None)
        self.store.set_setting(self.SETTING, state)
        return True

    def reconcile_unknown(self, push_key, outcome, *, now=None):
        """只接受人工/上游幂等对账，不替未知投递自动选择重发。"""
        if outcome not in {self.CONFIRMED_SUCCESS, self.CONFIRMED_FAILURE}:
            raise ValueError("未知投递只能对账为 CONFIRMED_SUCCESS 或 CONFIRMED_FAILURE")
        current = aware(now or datetime.now(timezone.utc))
        state = self._state()
        intent = state["dispatch_intents"].get(push_key)
        if not isinstance(intent, dict) or intent.get("status") not in {
            self.DISPATCH_INTENT,
            self.UNKNOWN_AFTER_ACTION,
        }:
            return False
        if outcome == self.CONFIRMED_SUCCESS:
            record = {
                key: value
                for key, value in intent.items()
                if key not in {"status", "detail"}
            }
            record.update(
                {
                    "status": self.CONFIRMED_SUCCESS,
                    "pushed_at": intent.get("intent_at", current.isoformat()),
                    "reconciled_at": current.isoformat(),
                }
            )
            state["delivered"][push_key] = record
        state["dispatch_intents"].pop(push_key, None)
        state["retry_after"].pop(push_key, None)
        self.store.set_setting(self.SETTING, state)
        return True

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

    def cleanup(self, *, now=None, retention_days=90):
        """旧成功记录压缩到版本水位，不能因清理而重新投递旧公告。"""
        if retention_days < 14:
            raise ValueError("投递保留期不能短于重扫窗口")
        current = aware(now or datetime.now(timezone.utc))
        cutoff = current - timedelta(days=retention_days)
        state = self._state()
        removed = 0
        for key, record in list(state["delivered"].items()):
            if aware(record["pushed_at"]) >= cutoff:
                continue
            target = state["targets"].get(record["target"])
            if target is not None and record["push_type"] == "announcement":
                baseline = target["baseline"]
                entity = record["entity_id"]
                baseline[entity] = max(baseline.get(entity, 0), record["version"])
            del state["delivered"][key]
            removed += 1
        retries = state.get("retry_after", {})
        state["retry_after"] = {key: deadline for key, deadline in retries.items() if aware(deadline) > current}
        if removed or len(retries) != len(state["retry_after"]):
            self.store.set_setting(self.SETTING, state)
        return removed

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
                if push.key not in state["delivered"] and push.key not in state["dispatch_intents"]:
                    planned[push.key] = push
            for deadline in deadlines:
                end = aware(deadline.end_at)
                if end <= now:
                    continue
                start = getattr(deadline, "start_at", None)
                if start is not None and aware(start) > now:
                    continue
                for hour in preference["reminder_hours"]:
                    due = end - timedelta(hours=hour)
                    # 只在到期后的短窗口提醒；重启不补发早已错过的提醒。
                    if due < subscribed or not due <= now < min(end, due + timedelta(minutes=15)):
                        continue
                    push = PlannedPush(target, deadline.event_id, deadline.deadline_version, "deadline",
                        f"【截止提醒】{deadline.name}\n{deadline.remaining_display(now)}\n{deadline.source_url}", hour)
                    if push.key not in state["delivered"] and push.key not in state["dispatch_intents"]:
                        planned[push.key] = push
        return list(planned.values())

    async def dispatch(self, records, deadlines, sender, *, now=None, limit=20):
        """先持久化发送意图；未知结果保留并禁止自动重放。"""
        if not 1 <= limit <= 100:
            raise ValueError("单轮投递数量超限")
        async with self._dispatch_lock:
            current = aware(now or datetime.now(timezone.utc))
            unknown = self._recover_orphaned_intents(current)
            self.cleanup(now=current)
            succeeded = failed = 0
            attempted = 0
            for push in self.plan(records, deadlines, now=current):
                if attempted >= limit:
                    break
                retry_after = self._state().get("retry_after", {}).get(push.key)
                if retry_after and aware(retry_after) > current:
                    continue
                if not self._state()["targets"].get(push.target, {}).get("enabled"):
                    continue
                attempted += 1
                if not self._persist_intent(push, current):
                    # 其他实例或同一轮状态变化已经持有该键时，绝不能越过 intent 再发送。
                    continue
                try:
                    accepted = await sender(push.target, push.text)
                except asyncio.CancelledError:
                    self._mark_unknown(push.key, current, "sender cancelled after dispatch intent")
                    unknown += 1
                    raise
                except Exception as exc:
                    self._mark_unknown(push.key, current, f"sender exception: {type(exc).__name__}")
                    unknown += 1
                    continue
                if accepted is not True:
                    try:
                        self._commit_failure(push.key, current)
                    except Exception as exc:
                        self._mark_unknown(push.key, current, f"failure state commit: {type(exc).__name__}")
                        unknown += 1
                        continue
                    failed += 1
                    continue
                try:
                    self._commit_success(push, current)
                except Exception as exc:
                    self._mark_unknown(push.key, current, f"success state commit: {type(exc).__name__}")
                    unknown += 1
                    continue
                succeeded += 1
            return {"succeeded": succeeded, "failed": failed, "unknown": unknown}

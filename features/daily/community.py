"""社区免费领奖编排；只处理官方明确可领取的一次性任务。"""
from __future__ import annotations

import asyncio
import hashlib

from ..account.errors import CredentialExpiredError
from .models import DailyTaskResult, DailyTaskStatus


class CommunityDailyMixin:
    def _account_lock(self, account):
        identity = self.daily_identity(account)
        return self._account_locks.setdefault(identity, asyncio.Lock())

    async def run_community_for_account(self, account, day):
        async with self._account_lock(account):
            signin = await self._run_signin(account, day)
            items = [{"name": "签到", "status": signin.status.value, "detail": signin.detail}]
            stop = {DailyTaskStatus.COOKIE_EXPIRED, DailyTaskStatus.RATE_LIMITED,
                    DailyTaskStatus.UNKNOWN_AFTER_ACTION, DailyTaskStatus.FAILED,
                    DailyTaskStatus.UNAVAILABLE, DailyTaskStatus.PENDING}
            if signin.status in stop or not self.config.get("enable_daily_actions", False):
                return self._community_result(account, day, signin.status, items)
            try:
                rewards = await self.client.get_community_rewards(account)
                if not rewards:
                    items.append({"name": "免费奖励", "status": "already_done", "detail": "本次未返回可领取记录"})
                for reward in rewards:
                    result = await self._claim_reward(account, reward)
                    items.append({"name": reward["name"], "status": result.status.value, "detail": result.detail})
                    if result.status in {DailyTaskStatus.COOKIE_EXPIRED, DailyTaskStatus.RATE_LIMITED,
                                         DailyTaskStatus.UNKNOWN_AFTER_ACTION}:
                        break
            except CredentialExpiredError:
                self.store.mark_cookie_invalid(str(account["qq_id"]))
                items.append({"name": "领奖", "status": "cookie_expired", "detail": "登录已失效，请重新绑定"})
            except asyncio.CancelledError:
                items.append({"name": "领奖", "status": "unknown_after_action", "detail": "执行已取消，未决项目只查询不重发"})
                self._community_result(account, day, DailyTaskStatus.UNKNOWN_AFTER_ACTION, items)
                raise
            except Exception:
                items.append({"name": "领奖", "status": "unavailable", "detail": "奖励查询失败，未提交未知奖励"})
            priorities = [DailyTaskStatus.COOKIE_EXPIRED, DailyTaskStatus.UNKNOWN_AFTER_ACTION,
                          DailyTaskStatus.RATE_LIMITED, DailyTaskStatus.FAILED, DailyTaskStatus.UNAVAILABLE]
            status = next((state for state in priorities if any(i["status"] == state.value for i in items)), DailyTaskStatus.SUCCESS)
            return self._community_result(account, day, status, items)

    def _community_result(self, account, day, status, items):
        result = DailyTaskResult(str(account.get("nickname") or account["qq_id"]), status,
            "\n".join(f"{item['name']}：{item['detail']}" for item in items), tuple(items))
        identity = hashlib.sha256(self.daily_identity(account).encode()).hexdigest()
        self.store.set_setting(f"community_daily:last:{identity}", {"day": day, **result.to_storage()})
        return result

    async def _claim_reward(self, account, reward):
        name = reward["name"]
        state = reward["state"]
        if state == "pending":
            return DailyTaskResult(name, DailyTaskStatus.PENDING, "尚未达成，不代做任务")
        if state == "unknown":
            return DailyTaskResult(name, DailyTaskStatus.UNAVAILABLE, "状态未验证，不提交")
        # 一次性奖励使用固定来源周期，绝不按当天日期重置。
        key = self.daily_run_key(reward["period"], account, "reward:" + reward["id"])
        if state == "claimed":
            if self.store.get_run(key):
                self.store.finish_run(key, "success", "已领取（查询确认）")
            return DailyTaskResult(name, DailyTaskStatus.ALREADY_DONE, "已领取")
        if not self.store.claim_run(key, str(account["qq_id"]), "community_reward", initial_status="DISPATCH_INTENT"):
            previous = self.store.get_run(key) or {}
            if previous.get("status") == "success":
                return DailyTaskResult(name, DailyTaskStatus.UNAVAILABLE, "本地已领取与来源状态冲突，未重复提交")
            return DailyTaskResult(name, DailyTaskStatus.UNKNOWN_AFTER_ACTION, "已有提交记录，结果未确认，未重复提交")
        try:
            error = None
            try:
                await self.client.claim_community_reward(account, reward["id"])
            except CredentialExpiredError:
                raise
            except Exception as exc:
                error = exc
            verified = await self.client.get_community_rewards(account)
            if any(r["id"] == reward["id"] and r["period"] == reward["period"] and r["state"] == "claimed" for r in verified):
                self.store.finish_run(key, "success", "领取成功（查询确认）")
                return DailyTaskResult(name, DailyTaskStatus.SUCCESS, "领取成功")
            # 限流也保留未决意图，不自动重发该奖励。
            if error is not None and str(getattr(error, "code", "")) in {"429", "212000"}:
                return DailyTaskResult(name, DailyTaskStatus.RATE_LIMITED, "请求限流，已停止领奖，待查询确认")
            return DailyTaskResult(name, DailyTaskStatus.UNKNOWN_AFTER_ACTION, "领取结果未确认，未重发")
        except CredentialExpiredError:
            self.store.mark_cookie_invalid(str(account["qq_id"]))
            return DailyTaskResult(name, DailyTaskStatus.COOKIE_EXPIRED, "登录失效，领取结果待确认")
        except asyncio.CancelledError:
            raise
        except Exception:
            return DailyTaskResult(name, DailyTaskStatus.UNKNOWN_AFTER_ACTION, "领取后查询失败，未重发")
        finally:
            if (self.store.get_run(key) or {}).get("status") == "DISPATCH_INTENT":
                self.store.finish_run(key, "UNKNOWN_AFTER_ACTION", "领取结果待查询确认")

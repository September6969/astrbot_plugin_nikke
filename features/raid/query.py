"""综合查询与账号隔离的短时缓存；只保存成功数据，不持久化账号记录。"""
import asyncio
from copy import deepcopy
import hashlib
import json
import time

from ..account.errors import CredentialExpiredError
from .experience import analyze, paginate
from .models import RaidState


class RaidQueryMixin:
    def _init_query_cache(self):
        self._query_cache = {}
        self._query_tasks = {}
        self._query_waiters = {}
        self._monotonic = time.monotonic

    @staticmethod
    def _fingerprint(account):
        return hashlib.sha256(json.dumps(dict(account), sort_keys=True, default=str).encode("utf-8")).hexdigest()

    def invalidate(self, actor):
        for key in list(self._query_cache):
            if key[0] == str(actor):
                self._query_cache.pop(key, None)

    async def _load_dashboard(self, account):
        snapshot = await self._gateway.get_union_raid_dashboard(account)
        current = self._query_time()
        snapshot["fetched_at"] = current.strftime("%Y-%m-%d %H:%M:%S")
        snapshot["now"] = current
        snapshot.setdefault("errors", [])
        payload = snapshot.get("attacks")
        state_payload = snapshot.get("level_info") or payload
        if isinstance(state_payload, dict) and self._builder.resolve_response_state(state_payload, now=current) is RaidState.OFFSEASON:
            season = self._builder.latest_completed_season_id(now=current)
            if season and snapshot.get("guild_id"):
                try:
                    historical = await self._gateway.get_union_raid_season(account,
                        guild_id=str(snapshot["guild_id"]), season_id=season, levels=False)
                    if not isinstance(historical.get("participate_data"), list):
                        raise ValueError("历史记录格式异常")
                    snapshot["attacks"] = historical
                    snapshot["historical_season"] = season
                except CredentialExpiredError:
                    raise
                except Exception:
                    snapshot.pop("attacks", None)
                    snapshot["errors"].append("history")
        return snapshot

    async def _dashboard_snapshot(self, actor):
        account = self._account(actor)
        if account.get("cookie_valid") in (False, 0):
            self.invalidate(actor)
            raise CredentialExpiredError("登录状态已失效，请重新绑定")
        key = (str(actor), self._fingerprint(account))
        now = self._monotonic()
        for old, (expiry, _) in list(self._query_cache.items()):
            if expiry <= now or (old[0] == str(actor) and old != key):
                self._query_cache.pop(old, None)
        cached = self._query_cache.get(key)
        if cached:
            return account, deepcopy(cached[1])
        task = self._query_tasks.get(key)
        if task is None:
            if self._task_factory is None:
                raise RuntimeError("突袭查询任务工厂未配置")
            task = self._task_factory(self._load_dashboard(account))
            if task is None:
                raise RuntimeError("服务正在关闭，请稍后重试")
            self._query_tasks[key] = task
            self._query_waiters[key] = 0
        self._query_waiters[key] += 1
        try:
            snapshot = await asyncio.shield(task)
            latest = self._account_reader.get_account(str(actor))
            if not latest or self._fingerprint(latest) != key[1]:
                self.invalidate(actor)
                raise ValueError("账号状态已变化，请重新查询")
            # 缺失/损坏的响应和部分失败均不进入热缓存。
            good = (not snapshot["errors"] and isinstance(snapshot.get("level_info"), dict)
                and isinstance(snapshot.get("attacks"), dict)
                and isinstance(snapshot["attacks"].get("participate_data"), list))
            if good and not analyze(snapshot["attacks"]).incomplete and key not in self._query_cache:
                if len(self._query_cache) >= 128:
                    self._query_cache.pop(next(iter(self._query_cache)))
                self._query_cache[key] = (self._monotonic() + 30, deepcopy(snapshot))
            return account, deepcopy(snapshot)
        finally:
            self._query_waiters[key] -= 1
            if self._query_waiters[key] == 0:
                self._query_waiters.pop(key, None)
                self._query_tasks.pop(key, None)
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    def _analysis(self, snapshot, member_id=None):
        payload = snapshot.get("attacks")
        manager = payload.get("manager_info", {}) if isinstance(payload, dict) else {}
        season = snapshot.get("historical_season") or (str(manager.get("id")) if isinstance(manager, dict) and manager.get("id") not in (None, "", 0, "0") else None)
        data = analyze(payload, member_id=member_id, season_id=season, historical=bool(snapshot.get("historical_season")))
        data.guild_name = snapshot["guild_name"]
        data.fetched_at = snapshot["fetched_at"]
        return data

    async def dashboard(self, actor):
        account, snapshot = await self._dashboard_snapshot(actor)
        try:
            data = self._builder.build(guild_name=snapshot["guild_name"],
                level_info_payload=snapshot.get("level_info", {}), fetched_at=snapshot["fetched_at"],
                plugin_version=self._plugin_version, now=snapshot["now"])
        except (ValueError, TypeError, KeyError):
            data = self._builder.build(guild_name=snapshot["guild_name"], level_info_payload={},
                fetched_at=snapshot["fetched_at"], plugin_version=self._plugin_version, now=snapshot["now"])
            data.notices.append("Boss 进度暂不可用")
        if "level_info" in snapshot["errors"]:
            data.notices.append("Boss 进度暂不可用")
        try:
            data.ranking = self._analysis(snapshot)
            member_id = str(account.get("game_openid") or "").strip()
            if member_id:
                data.member = self._analysis(snapshot, member_id)
            else:
                data.notices.append("缺少稳定身份，个人摘要暂不可用")
        except ValueError:
            data.notices.append("贡献与个人记录暂不可用")
        return data

    async def ranking_page(self, actor, page=1):
        _, snapshot = await self._dashboard_snapshot(actor)
        return paginate(self._analysis(snapshot), page)

    async def member_page(self, actor, page=1):
        account = self._account(actor)
        member_id = str(account.get("game_openid") or "").strip()
        if not member_id:
            raise ValueError("缺少稳定身份，请重新绑定账号后查询个人记录")
        account, snapshot = await self._dashboard_snapshot(actor)
        member_id = str(account.get("game_openid") or "").strip()
        if not member_id:
            raise ValueError("账号已变更，请重新绑定后查询")
        return paginate(self._analysis(snapshot, member_id), page, member=True)

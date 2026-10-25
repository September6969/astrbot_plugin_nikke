# SPDX-License-Identifier: GPL-3.0-or-later
"""BlaBlaLink API 适配层。

接口与恢复策略基于 ExiaProject/ExiaInvasion GPL-3.0 源码移植。
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
import random
import time
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

import httpx

from ...core.cookie_utils import parse_cookie as _parse_cookie
from ...core.lifecycle.coordinator import RuntimeCoordinator
from ...features.account.errors import CredentialExpiredError
from ...features.daily.errors import UnknownAfterActionError
from .errors import BlaBlaError, CookieExpired
from .http_transport import IsolatedAsyncClient, IsolatedCookies

T = TypeVar("T")


API_BASE = "https://api.blablalink.com"
PLAYER_INFO = "/api/ugc/direct/standalonesite/User/GetUserGamePlayerInfo"
CHECK_LOGIN = "/api/user/CheckLogin"
USER_INFO_NEW = "/api/ugc/proxy/standalonesite/User/GetUserInfoNew"
PRIVACY_SETTING = "/api/ugc/direct/standalonesite/User/GetUserPrivacySetting"
PROFILE = "/api/game/proxy/Game/GetUserProfileBasicInfo"
OUTPOST = "/api/game/proxy/Game/GetUserProfileOutpostInfo"
CHARACTERS = "/api/game/proxy/Game/GetUserCharacters"
DAILY_CONTENTS_PROGRESS = "/api/game/proxy/Game/GetUserDailyContentsProgress"
CHARACTER_DETAILS = "/api/game/proxy/Game/GetUserCharacterDetails"
TASK_LIST = "/api/lip/proxy/lipass/Points/GetTaskListWithStatusV2"
DAILY_CHECK_IN = "/api/lip/proxy/lipass/Points/DailyCheckIn"
DAILY_CONTENTS_PROGRESS = "/api/game/proxy/Game/GetUserDailyContentsProgress"
CDK_REDEEM = "/api/game/proxy/Game/RecordCdkRedemption"
MY_GUILD_INFO = "/api/game/proxy/Game/GetMyGuildInfo"
UNION_RAID_LEVEL_INFO = "/api/game/proxy/Game/GetUnionRaidLevelInfo"
UNION_RAID_DATA = "/api/game/proxy/Game/GetUnionRaidData"
MAIN_QUEST_CLEAR_LINEUP = "/api/game/proxy/Game/GetMainQuestClearLineup"
GET_CDK_REDEMPTION = "/api/game/proxy/Game/GetCdkRedemption"
GET_CDK_REDEMPTION_HISTORY = "/api/game/proxy/Game/GetCdkRedemptionHistory"

NIKKE_DIRECTORY_ZH = "https://sg-tools-cdn.blablalink.com/jz-26/ww-14/c4619ec83335bcfd7b23e43600520dc7.json"
NIKKE_DIRECTORY_EN = "https://sg-tools-cdn.blablalink.com/yl-57/hd-03/1bf030193826e243c2e195f951a4be00.json"


class BlaBlaTimeoutError(BlaBlaError):
    """网络或请求传输超时，结果未确认。"""
    outcome_unknown = True
    pass


class BlaBlaNetworkError(BlaBlaError):
    """网络连接异常。"""
    outcome_unknown = True
    pass


class UnknownAfterAction(BlaBlaError, UnknownAfterActionError):
    """写请求已尝试，后续只读验证仍无法确认结果，禁止自动重发。"""


@dataclass(slots=True)
class ValidationResult:
    valid: bool
    game_uid: str
    game_openid: str
    role_name: str = ""
    nickname: str = ""
    area_id: str = ""


@dataclass(slots=True, frozen=True)
class CdkRedemptionResult:
    success: bool
    terminal: bool
    message: str
    code: str = ""
    is_unknown: bool = False


class BlaBlaClient:
    def __init__(
        self,
        timeout: int = 20,
        diagnostic: Callable[[str], None] | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
        task_factory: Callable[[Awaitable[Any]], asyncio.Task[Any]] | None = None,
        account_reader: Any = None,
    ):
        self.timeout = httpx.Timeout(timeout, connect=min(timeout, 10))
        self.diagnostic = diagnostic
        self._transport = transport
        self._client: httpx.AsyncClient | None = client
        self._external_client = client is not None
        self._public_client: httpx.AsyncClient | None = None
        self._closing = False
        self._closed = False
        self._close_lock = asyncio.Lock()
        self._client_lock = asyncio.Lock()
        self._owned_coordinator: RuntimeCoordinator | None = (
            RuntimeCoordinator() if task_factory is None else None
        )
        self._task_factory = task_factory or (
            self._owned_coordinator.create_task if self._owned_coordinator else None
        )
        self._account_reader = account_reader
        self._query_cache: dict[tuple[Any, ...], tuple[float, Any]] = {}
        self._query_tasks: dict[tuple[Any, ...], asyncio.Task[Any]] = {}
        self._query_waiters: dict[tuple[Any, ...], int] = {}

    @property
    def closing(self) -> bool:
        return self._closing or self._closed

    @property
    def closed(self) -> bool:
        return self._closed

    async def _get_client(self) -> httpx.AsyncClient:
        if self._closing or self._closed:
            raise RuntimeError("BlaBlaClient 已关闭，禁止发起新请求")
        if self._client is None:
            async with self._client_lock:
                if self._client is None and not (self._closing or self._closed):
                    client = httpx.AsyncClient(
                        timeout=self.timeout,
                        follow_redirects=False,
                        transport=self._transport,
                    )
                    try:
                        client._cookies = IsolatedCookies()
                    except Exception:
                        pass
                    self._client = client
        if self._closing or self._closed or self._client is None:
            raise RuntimeError("BlaBlaClient 已关闭，禁止发起新请求")
        return self._client

    async def _get_public_client(self) -> httpx.AsyncClient:
        if self._closing or self._closed:
            raise RuntimeError("BlaBlaClient 已关闭，禁止发起新请求")
        if self._public_client is None:
            async with self._client_lock:
                if self._public_client is None and not (self._closing or self._closed):
                    client = httpx.AsyncClient(
                        timeout=self.timeout,
                        follow_redirects=True,
                        transport=self._transport,
                    )
                    try:
                        client._cookies = IsolatedCookies()
                    except Exception:
                        pass
                    self._public_client = client
        if self._closing or self._closed or self._public_client is None:
            raise RuntimeError("BlaBlaClient 已关闭，禁止发起新请求")
        return self._public_client

    async def aclose(self) -> None:
        """幂等关闭客户端与短缓存中的未决任务。区分 closing 与 closed，支持取消/失败后安全重试。"""
        if self._closed:
            return
        self._closing = True
        async with self._close_lock:
            if self._closed:
                return
            tasks = list(self._query_tasks.values())
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            self._query_tasks.clear()
            self._query_waiters.clear()
            self._query_cache.clear()

            if self._owned_coordinator is not None and not self._owned_coordinator.closed:
                await self._owned_coordinator.close()

            if not self._external_client and self._client is not None:
                await self._client.aclose()
                self._client = None
            if self._public_client is not None:
                await self._public_client.aclose()
                self._public_client = None

            self._closed = True

    async def __aenter__(self) -> BlaBlaClient:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.aclose()

    @staticmethod
    def _account_identity_key(account: Mapping[str, Any]) -> tuple[str, str, str, str, str] | None:
        """从账号字典提取经验证的稳定身份维度，缺失稳定标识时返回 None（不参与缓存）。"""
        if account.get("cookie_valid") in (False, 0):
            return None
        openid = str(account.get("game_openid") or "").strip()
        uid = str(account.get("game_uid") or "").strip()
        area_id = str(account.get("area_id") or "").strip()
        qq_id = str(account.get("qq_id") or "").strip()
        binding_rev = str(account.get("binding_revision") or "").strip()
        if not binding_rev:
            cookie_val = str(account.get("cookie") or "")
            if cookie_val:
                binding_rev = hashlib.sha256(cookie_val.encode("utf-8")).hexdigest()
        if not (openid or uid) or not area_id or not binding_rev:
            return None
        return (qq_id, openid, uid, area_id, binding_rev)

    def invalidate_cache(self, qq_id: str | None = None) -> None:
        """使指定账号或全部账号的短时查询缓存失效。"""
        if qq_id is None:
            self._query_cache.clear()
            return
        target = str(qq_id)
        for key in list(self._query_cache):
            if key[0][0] == target:
                self._query_cache.pop(key, None)

    def invalidate_account_cache(self, account: Mapping[str, Any]) -> None:
        """续期后清除此社区身份所有绑定的短缓存，并取消相关未决查询。"""
        identity = self._account_identity_key(account)
        if identity is None or not identity[1]:
            return
        for key in set(self._query_cache) | set(self._query_tasks):
            if key[0][1] != identity[1]:
                continue
            self._query_cache.pop(key, None)
            task = self._query_tasks.get(key)
            if task is not None and not task.done():
                task.cancel()

    def _check_binding_validity(self, identity: tuple[str, str, str, str, str]) -> None:
        """校验当前绑定的最新状态，若已删除、凭据失效或代次变更则使缓存失效并拒绝返回旧数据。"""
        if self._account_reader is None or not identity or not identity[0]:
            return
        latest = self._account_reader.get_account(identity[0])
        if not latest:
            self.invalidate_cache(identity[0])
            raise ValueError("尚未绑定账号或账号已解绑，请重新绑定")
        if latest.get("cookie_valid") in (False, 0):
            self.invalidate_cache(identity[0])
            raise CredentialExpiredError("账号凭据已失效，请重新绑定")
        latest_ident = self._account_identity_key(latest)
        if latest_ident != identity:
            self.invalidate_cache(identity[0])
            raise ValueError("账号绑定状态已变更，请重新查询")

    async def _execute_cached(
        self,
        account: Mapping[str, Any],
        query_type: str,
        args_key: Any,
        fetcher: Callable[[], Awaitable[T]],
        validator: Callable[[T], bool] | None = None,
    ) -> T:
        if self._closing or self._closed:
            raise RuntimeError("BlaBlaClient 已关闭，禁止发起新请求")

        identity = self._account_identity_key(account)
        if identity is None:
            return await fetcher()

        self._check_binding_validity(identity)

        cache_key = (identity, query_type, args_key)
        now = time.monotonic()

        for old_key, (expiry, _) in list(self._query_cache.items()):
            if expiry <= now:
                self._query_cache.pop(old_key, None)

        cached = self._query_cache.get(cache_key)
        if cached is not None and cached[0] > now:
            self._check_binding_validity(identity)
            return deepcopy(cached[1])

        task = self._query_tasks.get(cache_key)
        if task is None:
            async def _run_fetch() -> T:
                data = await fetcher()
                self._check_binding_validity(identity)
                if validator is not None and not validator(data):
                    return data
                finish_time = time.monotonic()
                if len(self._query_cache) >= 128:
                    self._query_cache.pop(next(iter(self._query_cache)))
                self._query_cache[cache_key] = (finish_time + 30.0, deepcopy(data))
                return data

            if self._task_factory is not None:
                task = self._task_factory(_run_fetch())
                if task is None:
                    raise RuntimeError("服务正在关闭，禁止新建查询任务")
            else:
                raise RuntimeError("服务未正确配置任务工厂")
            self._query_tasks[cache_key] = task
            self._query_waiters[cache_key] = 0

        self._query_waiters[cache_key] += 1
        try:
            result = await asyncio.shield(task)
            self._check_binding_validity(identity)
            return deepcopy(result)
        finally:
            self._query_waiters[cache_key] -= 1
            if self._query_waiters[cache_key] <= 0:
                self._query_waiters.pop(cache_key, None)
                self._query_tasks.pop(cache_key, None)
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    def _diagnose(self, message: str) -> None:
        if not self.diagnostic:
            return
        try:
            self.diagnostic(message)
        except Exception:
            pass

    @staticmethod
    def parse_cookie(cookie: str) -> dict[str, str]:
        """Cookie 字符串解析；委托至共享实现。"""
        return _parse_cookie(cookie)

    async def _post(self, path: str, cookie: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self._closing or self._closed:
            raise RuntimeError("BlaBlaClient 已关闭，禁止发起新请求")
        endpoint = path.rsplit("/", 1)[-1]
        self._diagnose(f"{endpoint} 请求开始；payload_keys={sorted(payload)}")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Cookie": cookie,
            "Origin": "https://www.blablalink.com",
            "Referer": "https://www.blablalink.com/",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
        }
        client = await self._get_client()
        try:
            response = await client.post(API_BASE + path, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException as exc:
            self._diagnose(f"{endpoint} 请求超时")
            raise BlaBlaTimeoutError(f"{endpoint} 请求超时", endpoint=endpoint) from exc
        except httpx.NetworkError as exc:
            self._diagnose(f"{endpoint} 网络异常")
            raise BlaBlaNetworkError(f"{endpoint} 网络连接异常", endpoint=endpoint) from exc
        except httpx.HTTPStatusError as exc:
            self._diagnose(f"{endpoint} HTTP失败；status={exc.response.status_code}")
            raise BlaBlaError(f"{endpoint} HTTP {exc.response.status_code}", str(exc.response.status_code), endpoint) from exc
        except (httpx.HTTPError, ValueError) as exc:
            self._diagnose(f"{endpoint} 请求异常；type={type(exc).__name__}")
            raise BlaBlaError(f"{endpoint} 请求失败：{type(exc).__name__}", endpoint=endpoint) from exc
        code = str(data.get("code", data.get("retcode", data.get("ret_code", data.get("ret", "")))))
        response_data = data.get("data")
        data_keys = sorted(response_data)[:20] if isinstance(response_data, dict) else []
        self._diagnose(f"{endpoint} 响应；code={code or 'missing'}；data_keys={data_keys}")
        if code not in ("", "0"):
            message = str(data.get("message", data.get("msg", f"接口返回 {code}")))
            msg_lower = message.lower()
            if (
                code in {"1000002", "1000003", "1001001", "300001", "401", "403", "11003"}
                or "out of time" in msg_lower
                or ("token" in msg_lower and any(k in msg_lower for k in ("expire", "invalid", "timeout", "out of time")))
            ):
                raise CookieExpired("登录状态已失效，请重新绑定", code, endpoint)
            raise BlaBlaError(message, code, endpoint)
        return data

    async def validate_cookie(self, cookie: str) -> ValidationResult:
        values = self.parse_cookie(cookie)
        game_uid = values.get("game_uid", "")
        game_openid = values.get("game_openid", "")
        missing = [name for name in ("game_token", "game_uid", "game_openid") if not values.get(name)]
        self._diagnose(f"Cookie快照；count={len(values)}；names={sorted(values)}")
        if missing:
            raise BlaBlaError("缺少必要 Cookie：" + ", ".join(missing))

        player: dict[str, Any] | None = None
        player_error: BlaBlaError | None = None
        for delay in (0, 1, 2):
            if delay:
                await asyncio.sleep(delay)
            try:
                player = await self._post(PLAYER_INFO, cookie, {})
                break
            except BlaBlaError as exc:
                player_error = exc
                if exc.code != "1300015" or delay == 2:
                    if exc.code == "1300015":
                        break
                    break

        # BlaBlaLink 有时无法通过空请求推断玩家；按 Exia 的恢复链路显式传入标识。
        if player is None or not player.get("data", {}).get("area_id"):
            try:
                player = await self._post(
                    PLAYER_INFO,
                    cookie,
                    {"intl_openid": game_openid},
                )
                player_error = None
            except BlaBlaError as exc:
                player_error = exc

        # 某些账号的 game_openid 只是网页登录标识，需要先换取正式 intl_openid。
        if player is None or not player.get("data", {}).get("area_id"):
            canonical_openid = ""
            try:
                user_info = await self._post(USER_INFO_NEW, cookie, {})
                user_data = user_info.get("data", {}) or {}
                canonical_openid = str(
                    (user_data.get("info", {}) or {}).get("intl_openid")
                    or user_data.get("intl_openid")
                    or ""
                ).strip()
            except BlaBlaError:
                canonical_openid = ""
            if canonical_openid:
                try:
                    # 隐私查询会促使官网链路完成账号上下文初始化；失败不阻断后续识别。
                    await self._post(PRIVACY_SETTING, cookie, {"intl_openid": canonical_openid})
                except BlaBlaError:
                    pass
                try:
                    player = await self._post(
                        PLAYER_INFO,
                        cookie,
                        {"intl_openid": canonical_openid},
                    )
                    game_openid = canonical_openid
                    player_error = None
                except BlaBlaError as exc:
                    player_error = exc

        if player is None or not player.get("data", {}).get("area_id"):
            try:
                await self._post(CHECK_LOGIN, cookie, {})
            except BlaBlaError:
                if player_error:
                    raise player_error
                raise
            return ValidationResult(True, game_uid, game_openid)

        info = player.get("data", {})
        area_id = str(info.get("area_id", ""))
        role_name = str(info.get("role_name", ""))
        nickname = role_name
        try:
            basic = await self._post(
                PROFILE,
                cookie,
                {"nikke_area_id": int(area_id), "intl_open_id": game_openid},
            )
            nickname = str(basic.get("data", {}).get("basic_info", {}).get("nickname", "")) or role_name
        except BlaBlaError:
            pass
        return ValidationResult(True, game_uid, game_openid, role_name, nickname, area_id)

    async def get_profile(self, account: dict[str, Any]) -> dict[str, Any]:
        area_id = str(account.get("area_id", ""))
        if not area_id:
            validated = await self.validate_cookie(account["cookie"])
            area_id = validated.area_id
        payload = {"nikke_area_id": int(area_id)}
        if account.get("game_openid"):
            payload["intl_open_id"] = account["game_openid"]
        basic, outpost = await asyncio.gather(
            self._post(PROFILE, account["cookie"], payload),
            self._post(OUTPOST, account["cookie"], {"nikke_area_id": int(area_id)}),
        )
        return {
            "basic": basic.get("data", {}).get("basic_info", {}),
            "outpost": outpost.get("data", {}).get("outpost_info", {}),
        }

    async def get_profile_dashboard(self, account: dict[str, Any]) -> dict[str, Any]:
        area_id = str(account.get("area_id", ""))
        if not area_id:
            validated = await self.validate_cookie(account["cookie"])
            area_id = validated.area_id
        payload = {"nikke_area_id": int(area_id)}
        if account.get("game_openid"):
            payload["intl_open_id"] = account["game_openid"]
        roster_payload = {
            "intl_open_id": account.get("game_openid", ""),
            "nikke_area_id": int(area_id),
        }
        daily_payload = {"nikke_area_id": int(area_id)}
        basic_resp, outpost_resp, roster_resp, daily_resp = await asyncio.gather(
            self._post(PROFILE, account["cookie"], payload),
            self._post(OUTPOST, account["cookie"], {"nikke_area_id": int(area_id)}),
            self._post(CHARACTERS, account["cookie"], roster_payload),
            self._post(DAILY_CONTENTS_PROGRESS, account["cookie"], daily_payload),
            return_exceptions=True,
        )
        # 取消和认证失效优先于其他接口故障，避免用户无法获知需要重新绑定。
        responses = (basic_resp, outpost_resp, roster_resp, daily_resp)
        for exception_type in (asyncio.CancelledError, CookieExpired):
            for response in responses:
                if isinstance(response, exception_type):
                    raise response
        # 基础资料是必需数据。
        if isinstance(basic_resp, BaseException):
            raise basic_resp
        basic_data = basic_resp.get("data") if isinstance(basic_resp, dict) else None
        basic = basic_data.get("basic_info") if isinstance(basic_data, dict) else None
        if not isinstance(basic, dict):
            raise BlaBlaError("个人基础资料格式异常", endpoint="GetUserProfileBasicInfo")

        outpost: dict[str, Any] = {}
        outpost_available = False
        if isinstance(outpost_resp, BaseException):
            if isinstance(outpost_resp, (asyncio.CancelledError, CookieExpired)):
                raise outpost_resp
        else:
            outpost_data = outpost_resp.get("data") if isinstance(outpost_resp, dict) else None
            outpost_value = outpost_data.get("outpost_info") if isinstance(outpost_data, dict) else None
            if isinstance(outpost_value, dict):
                outpost = outpost_value
                outpost_available = True

        roster: list[Any] | None = None
        roster_available = False
        if isinstance(roster_resp, BaseException):
            if isinstance(roster_resp, (asyncio.CancelledError, CookieExpired)):
                raise roster_resp
        else:
            roster_data = roster_resp.get("data") if isinstance(roster_resp, dict) else None
            if isinstance(roster_data, dict):
                if "characters" in roster_data:
                    roster_value = roster_data["characters"]
                elif "user_characters" in roster_data:
                    roster_value = roster_data["user_characters"]
                else:
                    roster_value = None
                if isinstance(roster_value, list):
                    roster = roster_value
                    roster_available = True

        daily: dict[str, Any] | None = None
        daily_available = False
        if isinstance(daily_resp, BaseException):
            if isinstance(daily_resp, (asyncio.CancelledError, CookieExpired)):
                raise daily_resp
        else:
            daily_data = daily_resp.get("data") if isinstance(daily_resp, dict) else None
            daily_progress = daily_data.get("daily_progress") if isinstance(daily_data, dict) else None
            if isinstance(daily_progress, list) and daily_progress and isinstance(daily_progress[0], dict):
                daily = daily_progress[0]
                daily_available = True
            elif isinstance(daily_progress, dict):
                daily = daily_progress
                daily_available = True
        return {
            "basic": basic,
            "outpost": outpost,
            "roster": roster,
            "daily": daily,
            "outpost_available": outpost_available,
            "roster_available": roster_available,
            "daily_available": daily_available,
        }

    async def get_daily_contents_progress(self, account: dict[str, Any]) -> dict[str, Any]:
        """读取每日内容进度；只返回 data.daily_progress[0]，不执行任何写操作。"""
        area_id = str(account.get("area_id", ""))
        if not area_id:
            validated = await self.validate_cookie(account["cookie"])
            area_id = validated.area_id
        response = await self._post(
            DAILY_CONTENTS_PROGRESS,
            account["cookie"],
            {"nikke_area_id": int(area_id)},
        )
        data = response.get("data") if isinstance(response, dict) else None
        progress = data.get("daily_progress") if isinstance(data, dict) else None
        if not isinstance(progress, list) or not progress or not isinstance(progress[0], dict):
            raise BlaBlaError("每日内容进度格式异常", endpoint="GetUserDailyContentsProgress")
        return progress[0]

    async def _union_raid_context(self, account: dict[str, Any]) -> dict[str, Any]:
        area_id = str(account.get("area_id", ""))
        openid = str(account.get("game_openid", "")).strip()
        if not area_id or not openid:
            validated = await self.validate_cookie(account["cookie"])
            area_id = area_id or validated.area_id
            openid = openid or validated.game_openid

        guild_payload = {"ignore_toast": True}
        guild_resp = await self._post(MY_GUILD_INFO, account["cookie"], guild_payload)
        guild_data = guild_resp.get("data", {}) if isinstance(guild_resp, dict) else {}

        def _find_first(value: Any, key: str) -> Any:
            if isinstance(value, dict):
                if value.get(key) not in (None, ""):
                    return value[key]
                for item in value.values():
                    found = _find_first(item, key)
                    if found not in (None, ""):
                        return found
            elif isinstance(value, list):
                for item in value:
                    found = _find_first(item, key)
                    if found not in (None, ""):
                        return found
            return None

        guild_id = _find_first(guild_data, "guild_id")
        if not guild_id:
            raise BlaBlaError("未查询到联盟信息，请确认您已加入联盟。", endpoint="GetMyGuildInfo")

        guild_name = str(
            _find_first(guild_data, "guild_name")
            or _find_first(guild_data, "name")
            or "联盟"
        )

        raid_payload = {
            "guild_id": str(guild_id),
            "nikke_area_id": int(area_id),
            "intl_open_id": openid,
        }
        return {"guild_id": guild_id, "guild_name": guild_name, "request": raid_payload}

    async def get_union_raid_overview(self, account: dict[str, Any], *, attacks: bool = False) -> dict[str, Any]:
        context = await self._union_raid_context(account)
        endpoint = UNION_RAID_DATA if attacks else UNION_RAID_LEVEL_INFO
        response = await self._post(endpoint, account["cookie"], context["request"])
        return {"guild_id": context["guild_id"], "guild_name": context["guild_name"],
                "level_info": response.get("data", {})}

    async def get_union_raid_dashboard(self, account: dict[str, Any]) -> dict[str, Any]:
        """共享一次联盟身份查询；局部失败不抹掉另一区域，认证失败始终上抛。"""
        import asyncio
        context = await self._union_raid_context(account)
        results = await asyncio.gather(*[
            self._post(endpoint, account["cookie"], context["request"])
            for endpoint in (UNION_RAID_LEVEL_INFO, UNION_RAID_DATA)
        ], return_exceptions=True)
        output = {"guild_id": context["guild_id"], "guild_name": context["guild_name"], "errors": []}
        for key, result in zip(("level_info", "attacks"), results):
            if isinstance(result, CookieExpired):
                raise result
            if isinstance(result, BaseException):
                if not isinstance(result, Exception):
                    raise result
                output["errors"].append(key)
            elif isinstance(result, dict) and isinstance(result.get("data"), dict):
                output[key] = result["data"]
            else:
                output["errors"].append(key)
        return output

    async def get_union_raid_snapshot(self, account: dict[str, Any]) -> dict[str, Any]:
        """一次采集联盟身份与攻击响应，供休赛期回退复用明确 guild_id。"""
        return await self.get_union_raid_overview(account, attacks=True)

    async def get_union_raid_data(self, account: dict[str, Any]) -> dict[str, Any]:
        """复用联盟上下文，仅请求已确认的攻击列表接口。"""
        response = await self.get_union_raid_snapshot(account)
        return response["level_info"]

    async def get_union_raid_season(self, account: dict[str, Any], *, guild_id: str, season_id: str, levels: bool = False) -> dict[str, Any]:
        """官方公开前端已观察到的历史读取合同；不自动发现或猜测 season_id。"""
        if not guild_id or not season_id:
            raise ValueError("历史突袭需要明确的联盟和赛季")
        endpoint = "/api/game/proxy/Game/" + (
            "GetUnionRaidLevelDataOfGuildSeason" if levels else "GetUnionRaidDataOfGuildSeason"
        )
        response = await self._post(endpoint, account["cookie"], {
            "area_id": int(account["area_id"]), "guild_id": str(guild_id), "season_id": str(season_id),
        })
        data = response.get("data")
        if not isinstance(data, dict):
            raise BlaBlaError("历史突袭返回格式异常", endpoint=endpoint)
        return data

    async def get_roster(self, account: dict[str, Any], include_details: bool = True) -> list[dict[str, Any]]:
        details_complete = False

        async def _fetch():
            nonlocal details_complete
            area_id = int(account["area_id"])
            openid = account.get("game_openid", "")
            roster_resp = await self._post(
                CHARACTERS,
                account["cookie"],
                {"intl_open_id": openid, "nikke_area_id": area_id},
            )
            if not isinstance(roster_resp, dict):
                raise BlaBlaError("角色列表响应不是对象", endpoint=CHARACTERS)
            data = roster_resp.get("data")
            if not isinstance(data, dict):
                raise BlaBlaError("角色列表响应缺失 data 字段", endpoint=CHARACTERS)
            if "characters" not in data and "user_characters" not in data:
                raise BlaBlaError("角色列表响应数据缺失 characters 字段", endpoint=CHARACTERS)
            roster_raw = data.get("characters") if "characters" in data else data.get("user_characters")
            if not isinstance(roster_raw, list):
                raise BlaBlaError("角色列表 characters 不是列表", endpoint=CHARACTERS)
            roster = roster_raw
            if not include_details or not roster:
                return roster

            codes = list(dict.fromkeys(str(c.get("name_code", "")).strip() for c in roster if isinstance(c, dict) and c.get("name_code")))
            if not codes:
                return roster

            detail_resp = await self._post(
                CHARACTER_DETAILS,
                account["cookie"],
                {"intl_open_id": openid, "nikke_area_id": area_id, "name_codes": codes},
            )
            details_data = detail_resp.get("data") if isinstance(detail_resp, dict) else {}
            details = details_data.get("character_details", []) if isinstance(details_data, dict) else []
            if not isinstance(details, list):
                details = []

            by_code: dict[str, dict[str, Any]] = {}
            skill_keys = ("skill1_lv", "skill2_lv", "ulti_skill_lv")
            for detail in details:
                if not isinstance(detail, dict):
                    continue
                code = str(detail.get("name_code", "")).strip()
                if not code:
                    continue
                skills = {}
                for k in skill_keys:
                    if k in detail and detail[k] is not None:
                        skills[k] = detail[k]
                by_code[code] = skills

            # 只信任本次详情响应的完整性，名单自带技能不能掩盖详情缺失。
            def valid_skill(value: Any) -> bool:
                return (
                    isinstance(value, int) and not isinstance(value, bool) and value > 0
                ) or (isinstance(value, str) and value.isascii() and value.isdigit() and int(value) > 0)

            details_complete = all(
                code in by_code and all(valid_skill(by_code[code].get(k)) for k in skill_keys)
                for code in codes
            )

            merged = []
            for item in roster:
                if not isinstance(item, dict):
                    merged.append(item)
                    continue
                code = str(item.get("name_code", "")).strip()
                item_copy = dict(item)
                if code in by_code:
                    item_copy.update(by_code[code])
                merged.append(item_copy)
            return merged

        def _roster_validator(d: Any) -> bool:
            if not isinstance(d, list):
                return False
            if not d:
                return True
            for item in d:
                if not isinstance(item, dict) or not str(item.get("name_code", "")).strip():
                    return False
                if include_details and not details_complete:
                    return False
            return True

        return await self._execute_cached(
            account,
            "roster",
            bool(include_details),
            _fetch,
            validator=_roster_validator,
        )

    async def get_character_detail(
        self,
        account: dict[str, Any],
        name_code: str,
    ) -> dict[str, Any]:
        """只请求指定角色的详情，并保留原始装备槽位与状态效果。"""
        code = str(name_code).strip()

        async def _fetch():
            roster = await self.get_roster(account, include_details=False)
            roster_item = next(
                (item for item in roster if str(item.get("name_code", "")) == code),
                None,
            )
            if roster_item is None:
                raise ValueError("该账号未持有这名妮姬")
            response = await self._post(
                CHARACTER_DETAILS,
                account["cookie"],
                {
                    "intl_open_id": account.get("game_openid", ""),
                    "nikke_area_id": int(account["area_id"]),
                    "name_codes": [code],
                },
            )
            data = response.get("data", {}) or {}
            detail = next(
                (
                    item
                    for item in (data.get("character_details", []) or [])
                    if str(item.get("name_code", "")) == code
                ),
                None,
            )
            if detail is None:
                raise BlaBlaError("未获取到该角色详情", endpoint="GetUserCharacterDetails")
            return {
                "roster_item": roster_item,
                "detail": detail,
                "state_effects": data.get("state_effects", []) or [],
            }

        return await self._execute_cached(
            account,
            "detail",
            code,
            _fetch,
            validator=lambda d: isinstance(d, dict) and "roster_item" in d and "detail" in d,
        )

    async def get_directory(self) -> list[dict[str, Any]]:
        if self._closing or self._closed:
            raise RuntimeError("BlaBlaClient 已关闭，禁止发起新请求")
        client = await self._get_public_client()
        zh_resp, en_resp = await asyncio.gather(
            client.get(NIKKE_DIRECTORY_ZH), client.get(NIKKE_DIRECTORY_EN)
        )
        zh_resp.raise_for_status()
        en_resp.raise_for_status()
        zh_data = zh_resp.json()
        en_data = en_resp.json()
        en_map = {str(x.get("id")): x for x in en_data if isinstance(x, dict)}
        result = []
        for zh in zh_data:
            en = en_map.get(str(zh.get("id")), {})
            result.append(
                {
                    "id": zh.get("id"),
                    "resource_id": zh.get("resource_id"),
                    "name_code": zh.get("name_code"),
                    # 当前 zh CDN 字段是官方繁中；保留旧字段兼容旧调用方。
                    "name_zh_tw": (zh.get("name_localkey") or {}).get("name", ""),
                    "name_zh_cn": zh.get("name_zh_cn", "") if isinstance(zh.get("name_zh_cn", ""), str) else "",
                    "name_zh_cn_alias": zh.get("name_zh_cn_alias", "") if isinstance(zh.get("name_zh_cn_alias", ""), str) else "",
                    "name_cn": (zh.get("name_localkey") or {}).get("name", ""),
                    "name_en": (en.get("name_localkey") or {}).get("name", ""),
                    "element": ((zh.get("element_id") or {}).get("element") or {}).get("element", ""),
                    "weapon": ((zh.get("shot_id") or {}).get("element") or {}).get("weapon_type", ""),
                    # 计算器需要官方目录中的职业与武器合同；保留旧的 weapon 别名兼容已有卡片。
                    "class": zh.get("class", ""),
                    "class_name": zh.get("class", ""),
                    "weapon_type": ((zh.get("shot_id") or {}).get("element") or {}).get("weapon_type", ""),
                    "burst": zh.get("use_burst_skill"),
                    "corporation": zh.get("corporation"),
                    "rare": zh.get("original_rare"),
                }
            )
        return result

    @staticmethod
    def _community_context(account: dict[str, Any]) -> tuple[str, str]:
        raw = str(account.get("x_common_params", ""))
        try:
            context = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BlaBlaError("账号缺少社区上下文，请使用0.1.2扩展重新绑定") from exc
        if not isinstance(context, dict) or not context.get("openid"):
            raise BlaBlaError("账号缺少社区上下文，请使用0.1.2扩展重新绑定")
        game_id = str(BlaBlaClient.parse_cookie(account["cookie"]).get("game_gameid", ""))
        game_id = game_id or str(context.get("intl_game_id", ""))
        if not game_id:
            raise BlaBlaError("账号缺少游戏上下文，请重新绑定")
        return raw, game_id

    async def _community_request(
        self,
        method: str,
        path: str,
        account: dict[str, Any],
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        x_common, _ = self._community_context(account)
        context = json.loads(x_common)
        endpoint = path.rsplit("/", 1)[-1]
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Cookie": account["cookie"],
            "Origin": "https://www.blablalink.com",
            "Referer": "https://www.blablalink.com/",
            "User-Agent": account.get("user_agent") or "Mozilla/5.0",
            "x-channel-type": "2",
            "x-common-params": x_common,
            "x-language": str(context.get("language", "zh-TW")),
        }
        if self._closing or self._closed:
            raise RuntimeError("BlaBlaClient 已关闭，禁止发起新请求")
        self._diagnose(f"{endpoint} 社区请求开始；method={method}；payload_keys={sorted(payload or {})}")
        client = await self._get_client()
        identity = self._account_identity_key(account)
        if identity is not None:
            self._check_binding_validity(identity)
        try:
            response = await client.request(
                method,
                API_BASE + path,
                params=params,
                json=payload if payload is not None else None,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException as exc:
            self._diagnose(f"{endpoint} 社区请求超时")
            raise BlaBlaTimeoutError(f"{endpoint} 请求超时", endpoint=endpoint) from exc
        except httpx.NetworkError as exc:
            self._diagnose(f"{endpoint} 社区网络异常")
            raise BlaBlaNetworkError(f"{endpoint} 网络连接异常", endpoint=endpoint) from exc
        except httpx.HTTPStatusError as exc:
            self._diagnose(f"{endpoint} 社区HTTP失败；status={exc.response.status_code}")
            raise BlaBlaError(f"{endpoint} HTTP {exc.response.status_code}", str(exc.response.status_code), endpoint) from exc
        except (httpx.HTTPError, ValueError) as exc:
            self._diagnose(f"{endpoint} 社区请求异常；type={type(exc).__name__}")
            raise BlaBlaError(f"{endpoint} 请求失败：{type(exc).__name__}", endpoint=endpoint) from exc
        code = str(data.get("code", data.get("retcode", data.get("ret_code", data.get("ret", "")))))
        response_data = data.get("data")
        keys = sorted(response_data)[:20] if isinstance(response_data, dict) else []
        self._diagnose(f"{endpoint} 社区响应；code={code or 'missing'}；data_keys={keys}")
        msg_str = str(data.get("msg", data.get("message", "ok")))
        msg_lower = msg_str.lower()
        if code not in ("", "0") or msg_lower not in {"", "ok", "success"}:
            if (
                code in {"1000002", "1000003", "1001001", "300001", "401", "403", "11003"}
                or "out of time" in msg_lower
                or ("token" in msg_lower and any(k in msg_lower for k in ("expire", "invalid", "timeout", "out of time")))
            ):
                raise CookieExpired("登录状态已失效，请重新绑定", code, endpoint)
            raise BlaBlaError(msg_str if msg_lower not in {"", "ok", "success"} else f"接口返回 {code}", code, endpoint)
        return data

    async def get_community_tasks(self, account: dict[str, Any]) -> list[dict[str, Any]]:
        """读取所有任务，结构异常不能伪装成空列表。"""
        _, game_id = self._community_context(account)
        response = await self._community_request("GET", TASK_LIST, account,
            params={"get_top": "false", "intl_game_id": game_id})
        data = response.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
            raise BlaBlaError("社区任务列表格式异常", endpoint=TASK_LIST)
        if any(not isinstance(task, dict) for task in data["tasks"]):
            raise BlaBlaError("社区任务条目格式异常", endpoint=TASK_LIST)
        return data["tasks"]

    async def get_daily_signin(self, account: dict[str, Any]) -> dict[str, Any]:
        tasks = await self.get_community_tasks(account)
        candidates = [task for task in tasks if task.get("task_type") == 1]
        if not candidates:
            candidates = [task for task in tasks if task.get("task_type") is None and
                any(word in str(task.get("task_name", "")).casefold() for word in ("签到", "簽到", "sign"))]
        if not candidates:
            return {"found": False, "completed": False, "task_id": "", "task_name": ""}
        if len(candidates) != 1:
            raise BlaBlaError("签到任务身份不唯一", endpoint=TASK_LIST)
        task = candidates[0]
        rewards = task.get("reward_infos")
        if not isinstance(rewards, list) or not rewards or any(
            not isinstance(item, dict) or type(item.get("is_completed")) is not bool for item in rewards
        ):
            raise BlaBlaError("签到奖励状态未知", endpoint=TASK_LIST)
        # 官方页面以任务类型识别签到，不能只拿第一项奖励代表全部结果。
        completed = all(item["is_completed"] for item in rewards)
        if any(item["is_completed"] for item in rewards) and not completed:
            raise BlaBlaError("签到奖励状态不一致，请在社区确认", endpoint=TASK_LIST)
        return {"found": True, "completed": completed,
                "task_id": str(task.get("task_id") or ""), "task_name": str(task.get("task_name") or "签到")}

    async def get_community_rewards(self, account: dict[str, Any]) -> list[dict[str, Any]]:
        """官方新手任务是一次性免费奖励；不调用完成任务或积分兑换接口。"""
        endpoint = "/api/game/proxy/Game/HasFinishOnboardingMissionList"
        response = await self._community_request("POST", endpoint, account, payload={})
        data = response.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("mission_done_list"), list):
            raise BlaBlaError("免费奖励列表格式异常", endpoint=endpoint)
        names = {"1": "登录任务奖励", "2": "绑定社区奖励", "3": "绑定游戏奖励",
                 "4": "添加桌面奖励", "5": "关注任务奖励"}
        result = []
        seen = set()
        for item in data["mission_done_list"]:
            if not isinstance(item, dict):
                raise BlaBlaError("免费奖励条目格式异常", endpoint=endpoint)
            tag = str(item.get("tag_id") or "")
            status = item.get("mission_status")
            if not tag or tag in seen:
                raise BlaBlaError("免费奖励身份缺失或重复", endpoint=endpoint)
            seen.add(tag)
            result.append({"id": tag, "name": names.get(tag, "未知任务奖励"),
                "period": "onboarding-v1", "state": {0: "pending", 1: "claimable", 2: "claimed"}.get(status, "unknown")
                if type(status) is int and tag in names else "unknown"})
        return result

    async def claim_community_reward(self, account: dict[str, Any], reward_id: str) -> None:
        """一次提交；调用方负责持久化意图与写后核验，不自动重试。"""
        if reward_id not in {"1", "2", "3", "4", "5"}:
            raise BlaBlaError("奖励类型尚未验证")
        await self._community_request("POST", "/api/game/proxy/Game/OnboardingMissionGiftCollection",
                                      account, payload={"tag_id": reward_id})

    async def perform_daily_signin(self, account: dict[str, Any]) -> str:
        status = await self.get_daily_signin(account)
        if not status["found"]:
            raise BlaBlaError("未找到每日签到任务", endpoint="GetTaskListWithStatusV2")
        if status["completed"]:
            return "今日已经签到"
        if not status["task_id"]:
            raise BlaBlaError("签到任务缺少task_id", endpoint="GetTaskListWithStatusV2")
        last_error: BlaBlaError | None = None
        try:
            await self._community_request(
                "POST", DAILY_CHECK_IN, account, payload={"task_id": status["task_id"]},
            )
        except CookieExpired:
            raise
        except BlaBlaError as exc:
            last_error = exc
        try:
            verified = await self.get_daily_signin(account)
            if verified["completed"]:
                return "签到成功"
        except CookieExpired:
            raise
        except BlaBlaError as exc:
            raise UnknownAfterAction("签到结果未确认，请稍后查询状态，未自动重发", "UNKNOWN_AFTER_ACTION", DAILY_CHECK_IN) from exc
        if last_error and not isinstance(last_error, (BlaBlaTimeoutError, BlaBlaNetworkError)):
            raise last_error
        raise UnknownAfterAction("签到结果未确认，请稍后查询状态，未自动重发", "UNKNOWN_AFTER_ACTION", DAILY_CHECK_IN)

    async def redeem_cdk(self, account: dict[str, Any], code: str) -> CdkRedemptionResult:
        """使用已绑定账号兑换国际服CDK，不对写请求自动重试。"""
        error_messages = {
            "1302009": "账号兑换次数已达上限",
            "1302015": "兑换码无效或已过期",
            "1302016": "该账号已经兑换过此码",
            "1302017": "兑换码全服可用次数已耗尽",
        }
        try:
            response = await self._community_request(
                "POST",
                CDK_REDEEM,
                account,
                payload={"cdkey": code},
            )
        except BlaBlaError as exc:
            if exc.code == "300001":
                raise CookieExpired("登录状态已失效，请重新绑定", exc.code, exc.endpoint) from exc
            if exc.code in error_messages:
                return CdkRedemptionResult(False, True, error_messages[exc.code], exc.code)
            raise
        if not self._has_explicit_cdk_success(response):
            # HTTP 200 与默认的 code/msg 只能证明请求被接收，不能证明兑换成功。
            # 写请求已经发生，必须进入未知态，后续不得自动重发。
            return CdkRedemptionResult(
                False,
                False,
                "兑换请求已发送，但官方响应缺少明确成功字段；请核对官方兑换记录，未自动重发",
                "UNKNOWN_AFTER_ACTION",
                True,
            )
        return CdkRedemptionResult(True, True, "兑换成功", "0")

    @staticmethod
    def _has_explicit_cdk_success(response: Any) -> bool:
        """只接受 CDK 端点的明确成功字段，不把空响应当成成功。

        ``_community_request`` 为兼容历史读接口保留了宽松的公共包络解析；
        CDK 写端点在这里再次收紧合同。字段必须位于 data 中，且值必须是
        明确的布尔成功标记或已完成状态字符串；布尔值不会被当作数字 code。
        """
        if not isinstance(response, dict) or type(response.get("code")) is not int:
            return False
        if response.get("code") != 0:
            return False
        payload = response.get("data")
        if not isinstance(payload, dict) or not payload:
            return False
        for key in ("success", "redeemed", "redeem_success"):
            if type(payload.get(key)) is bool and payload[key] is True:
                return True
        status = payload.get("status")
        if isinstance(status, str) and status.strip().casefold() in {
            "success",
            "succeeded",
            "redeemed",
            "completed",
        }:
            return True
        return False

    async def get_main_quest_clear_lineup(self, account: dict[str, Any], stage_id: int, area_id: int | str) -> dict[str, Any]:
        """查询个人主线战役历史通关阵容。
        根据 contracts/campaign_history.md，业务错误码 1300017 及 212000 均作为受控响应字典返回。
        """
        try:
            res = await self._community_request(
                "POST",
                MAIN_QUEST_CLEAR_LINEUP,
                account,
                payload={"stage_id": int(stage_id), "area_id": int(area_id)},
            )
            return res
        except BlaBlaError as exc:
            if exc.code == "1300017":
                return {"code": 1300017, "data": None, "msg": "暂无可查询的历史阵容"}
            if exc.code == "212000":
                return {"code": 212000, "data": None, "msg": "请求过频"}
            if exc.code == "300001":
                raise CookieExpired("登录状态已失效，请重新绑定", exc.code, exc.endpoint) from exc
            raise

    async def get_cdk_redemption(self, account: dict[str, Any]) -> list[dict]:
        """获取官方可用 CDK 列表。
        先取响应 data，再按已确认字段拆包；接口异常抛出受控异常。
        """
        res = await self._community_request("POST", GET_CDK_REDEMPTION, account, payload={})
        data = res.get("data") if isinstance(res, dict) else res
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("list", "cdk_list", "cdk_redemption_list", "redemption_list", "items", "records"):
                if isinstance(data.get(key), list):
                    return data[key]
        return []


    async def get_cdk_redemption_history(self, account: dict[str, Any]) -> list[dict]:
        """获取官方 CDK 历史兑换记录。
        先取响应 data，再按已确认字段拆包；接口异常抛出受控异常。
        """
        res = await self._community_request(
            "POST",
            GET_CDK_REDEMPTION_HISTORY,
            account,
            payload={
                "page_num": 1,
                "page_size": 20,
            },
        )
        data = res.get("data") if isinstance(res, dict) else res
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in (
                "cdk_redemption_list",
                "list",
                "history_list",
                "history",
                "records",
                "items",
            ):
                if isinstance(data.get(key), list):
                    return data[key]
        return []

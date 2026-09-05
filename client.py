# SPDX-License-Identifier: GPL-3.0-or-later
"""BlaBlaLink API 适配层。

接口与恢复策略基于 ExiaProject/ExiaInvasion GPL-3.0 源码移植。
"""

from __future__ import annotations

import asyncio
import json
import random
from dataclasses import dataclass
from typing import Any, Callable

import httpx


API_BASE = "https://api.blablalink.com"
PLAYER_INFO = "/api/ugc/direct/standalonesite/User/GetUserGamePlayerInfo"
CHECK_LOGIN = "/api/user/CheckLogin"
USER_INFO_NEW = "/api/ugc/proxy/standalonesite/User/GetUserInfoNew"
PRIVACY_SETTING = "/api/ugc/direct/standalonesite/User/GetUserPrivacySetting"
PROFILE = "/api/game/proxy/Game/GetUserProfileBasicInfo"
OUTPOST = "/api/game/proxy/Game/GetUserProfileOutpostInfo"
CHARACTERS = "/api/game/proxy/Game/GetUserCharacters"
CHARACTER_DETAILS = "/api/game/proxy/Game/GetUserCharacterDetails"
TASK_LIST = "/api/lip/proxy/lipass/Points/GetTaskListWithStatusV2"
DAILY_CHECK_IN = "/api/lip/proxy/lipass/Points/DailyCheckIn"
CDK_REDEEM = "/api/game/proxy/Game/RecordCdkRedemption"
MY_GUILD_INFO = "/api/game/proxy/Game/GetMyGuildInfo"
UNION_RAID_LEVEL_INFO = "/api/game/proxy/Game/GetUnionRaidLevelInfo"
UNION_RAID_DATA = "/api/game/proxy/Game/GetUnionRaidData"
MAIN_QUEST_CLEAR_LINEUP = "/api/game/proxy/Game/GetMainQuestClearLineup"
GET_CDK_REDEMPTION = "/api/game/proxy/Game/GetCdkRedemption"
GET_CDK_REDEMPTION_HISTORY = "/api/game/proxy/Game/GetCdkRedemptionHistory"

NIKKE_DIRECTORY_ZH = "https://sg-tools-cdn.blablalink.com/jz-26/ww-14/c4619ec83335bcfd7b23e43600520dc7.json"
NIKKE_DIRECTORY_EN = "https://sg-tools-cdn.blablalink.com/yl-57/hd-03/1bf030193826e243c2e195f951a4be00.json"


class BlaBlaError(RuntimeError):
    def __init__(self, message: str, code: str = "", endpoint: str = ""):
        super().__init__(message)
        self.code = str(code)
        self.endpoint = endpoint


class BlaBlaTimeoutError(BlaBlaError):
    """网络或请求传输超时，结果未确认。"""
    pass


class BlaBlaNetworkError(BlaBlaError):
    """网络连接异常。"""
    pass


class CookieExpired(BlaBlaError):
    pass


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


class BlaBlaClient:
    def __init__(self, timeout: int = 20, diagnostic: Callable[[str], None] | None = None):
        self.timeout = httpx.Timeout(timeout, connect=min(timeout, 10))
        self.diagnostic = diagnostic

    def _diagnose(self, message: str) -> None:
        if not self.diagnostic:
            return
        try:
            self.diagnostic(message)
        except Exception:
            pass

    @staticmethod
    def parse_cookie(cookie: str) -> dict[str, str]:
        values: dict[str, str] = {}
        for part in cookie.split(";"):
            if "=" not in part:
                continue
            name, value = part.strip().split("=", 1)
            values[name] = value
        return values

    async def _post(self, path: str, cookie: str, payload: dict[str, Any]) -> dict[str, Any]:
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
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
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
        code = str(data.get("code", data.get("retcode", data.get("ret_code", ""))))
        response_data = data.get("data")
        data_keys = sorted(response_data)[:20] if isinstance(response_data, dict) else []
        self._diagnose(f"{endpoint} 响应；code={code or 'missing'}；data_keys={data_keys}")
        if code not in ("", "0"):
            message = str(data.get("message", data.get("msg", f"接口返回 {code}")))
            if code in {"1000002", "1000003", "1001001", "401", "403"}:
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
        roster_payload = {"intl_open_id": account.get("game_openid", ""), "nikke_area_id": int(area_id)}
        basic_resp, outpost_resp, roster_resp = await asyncio.gather(
            self._post(PROFILE, account["cookie"], payload),
            self._post(OUTPOST, account["cookie"], {"nikke_area_id": int(area_id)}),
            self._post(CHARACTERS, account["cookie"], roster_payload),
            return_exceptions=True,
        )
        # PROFILE is required.
        if isinstance(basic_resp, BaseException):
            raise basic_resp
        basic = basic_resp.get("data", {}).get("basic_info", {})
        outpost = {}
        if not isinstance(outpost_resp, BaseException):
            outpost = outpost_resp.get("data", {}).get("outpost_info", {})
        roster: list[dict[str, Any]] | None = None
        if not isinstance(roster_resp, BaseException):
            data = roster_resp.get("data", {})
            roster = data.get("characters", data.get("user_characters", [])) or []
        return {"basic": basic, "outpost": outpost, "roster": roster}

    async def get_union_raid_overview(self, account: dict[str, Any]) -> dict[str, Any]:
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
        level_resp = await self._post(UNION_RAID_LEVEL_INFO, account["cookie"], raid_payload)
        level_data = level_resp.get("data", {}) if isinstance(level_resp, dict) else {}

        return {
            "guild_id": guild_id,
            "guild_name": guild_name,
            "level_info": level_data,
        }

    async def get_roster(self, account: dict[str, Any], include_details: bool = True) -> list[dict[str, Any]]:
        area_id = int(account["area_id"])
        openid = account.get("game_openid", "")
        roster_resp = await self._post(
            CHARACTERS,
            account["cookie"],
            {"intl_open_id": openid, "nikke_area_id": area_id},
        )
        data = roster_resp.get("data", {})
        roster = data.get("characters", data.get("user_characters", [])) or []
        if not include_details or not roster:
            return roster
        codes = list(dict.fromkeys(str(c.get("name_code", "")) for c in roster if c.get("name_code")))
        detail_resp = await self._post(
            CHARACTER_DETAILS,
            account["cookie"],
            {"intl_open_id": openid, "nikke_area_id": area_id, "name_codes": codes},
        )
        details_data = detail_resp.get("data", {})
        details = details_data.get("character_details", []) or []
        effects = details_data.get("state_effects", []) or []
        effects_map = {str(effect.get("id")): effect for effect in effects}
        by_code: dict[str, dict[str, Any]] = {}
        slots = ("head", "torso", "arm", "leg")
        for detail in details:
            equipment_effects = []
            for slot in slots:
                for index in range(1, 4):
                    effect_id = detail.get(f"{slot}_equip_option{index}_id")
                    effect = effects_map.get(str(effect_id))
                    for function in (effect or {}).get("function_details", []) or []:
                        equipment_effects.append(
                            {
                                "function_type": function.get("function_type", ""),
                                "function_value": abs(float(function.get("function_value", 0) or 0)),
                                "level": function.get("level"),
                            }
                        )
            by_code[str(detail.get("name_code"))] = {
                **detail,
                "equipment_effects": equipment_effects,
            }
        merged = []
        for item in roster:
            code = str(item.get("name_code", ""))
            merged.append({**item, **by_code.get(code, {})})
        return merged

    async def get_character_detail(
        self,
        account: dict[str, Any],
        name_code: str,
    ) -> dict[str, Any]:
        """只请求指定角色的详情，并保留原始装备槽位与状态效果。"""
        code = str(name_code).strip()
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

    async def get_directory(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
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
                    "name_cn": (zh.get("name_localkey") or {}).get("name", ""),
                    "name_en": (en.get("name_localkey") or {}).get("name", ""),
                    "element": ((zh.get("element_id") or {}).get("element") or {}).get("element", ""),
                    "weapon": ((zh.get("shot_id") or {}).get("element") or {}).get("weapon_type", ""),
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
        self._diagnose(f"{endpoint} 社区请求开始；method={method}；payload_keys={sorted(payload or {})}")
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
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
        code = str(data.get("code", data.get("retcode", "")))
        response_data = data.get("data")
        keys = sorted(response_data)[:20] if isinstance(response_data, dict) else []
        self._diagnose(f"{endpoint} 社区响应；code={code or 'missing'}；data_keys={keys}")
        if code not in ("", "0") or str(data.get("msg", "ok")).lower() not in {"", "ok", "success"}:
            if code in {"1000002", "1000003", "1001001", "300001", "401", "403"}:
                raise CookieExpired("登录状态已失效，请重新绑定", code, endpoint)
            raise BlaBlaError(str(data.get("msg", data.get("message", "社区接口失败"))), code, endpoint)
        return data

    async def get_daily_signin(self, account: dict[str, Any]) -> dict[str, Any]:
        _, game_id = self._community_context(account)
        data = await self._community_request(
            "GET",
            TASK_LIST,
            account,
            params={"get_top": "false", "intl_game_id": game_id},
        )
        for task in (data.get("data", {}) or {}).get("tasks", []) or []:
            name = str(task.get("task_name", ""))
            lowered = name.casefold()
            if "签到" not in name and "簽到" not in name and "sign" not in lowered:
                continue
            reward = next(iter(task.get("reward_infos", []) or []), {})
            return {
                "found": True,
                "completed": bool(reward.get("is_completed", False)),
                "task_id": str(task.get("task_id", "")),
                "task_name": name,
            }
        return {"found": False, "completed": False, "task_id": "", "task_name": ""}

    async def perform_daily_signin(self, account: dict[str, Any]) -> str:
        status = await self.get_daily_signin(account)
        if not status["found"]:
            raise BlaBlaError("未找到每日签到任务", endpoint="GetTaskListWithStatusV2")
        if status["completed"]:
            return "今日已经签到"
        if not status["task_id"]:
            raise BlaBlaError("签到任务缺少task_id", endpoint="GetTaskListWithStatusV2")
        last_error: BlaBlaError | None = None
        for attempt in range(3):
            if attempt:
                await asyncio.sleep((2 ** attempt) + random.uniform(0, 1))
            try:
                await self._community_request(
                    "POST",
                    DAILY_CHECK_IN,
                    account,
                    payload={"task_id": status["task_id"]},
                )
            except BlaBlaError as exc:
                last_error = exc
            verified = await self.get_daily_signin(account)
            if verified["completed"]:
                return "签到成功"
        if last_error:
            raise last_error
        raise BlaBlaError("签到后状态未完成", endpoint="DailyCheckIn")

    async def redeem_cdk(self, account: dict[str, Any], code: str) -> CdkRedemptionResult:
        """使用已绑定账号兑换国际服CDK，不对写请求自动重试。"""
        error_messages = {
            "1302009": "账号兑换次数已达上限",
            "1302015": "兑换码无效或已过期",
            "1302016": "该账号已经兑换过此码",
            "1302017": "兑换码全服可用次数已耗尽",
        }
        try:
            await self._community_request(
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
        return CdkRedemptionResult(True, True, "兑换成功", "0")

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
            return {"code": int(exc.code) if exc.code.isdigit() else -1, "data": None, "msg": str(exc)}

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
        res = await self._community_request("POST", GET_CDK_REDEMPTION_HISTORY, account, payload={})
        data = res.get("data") if isinstance(res, dict) else res
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("list", "history_list", "history", "records", "items"):
                if isinstance(data.get(key), list):
                    return data[key]
        return []

    @staticmethod
    def calculate_ael(character: dict[str, Any]) -> float:
        atk = elem = 0.0
        effects = character.get("equipment_effects", character.get("effects", [])) or []
        for effect in effects:
            kind = str(effect.get("function_type", "")).lower()
            value = abs(float(effect.get("function_value", 0))) / 10000
            if "attack" in kind or kind in {"atk", "statatk", "1"}:
                atk += value
            if "element" in kind or kind in {"elem", "incelementdmg", "2"}:
                elem += value
        grade = int(character.get("grade", 0) or 0)
        core = int(character.get("core", 0) or 0)
        return round((1 + 0.9 * atk) * (1 + elem + 0.10) * (1 + 0.03 * grade + 0.02 * core), 4)

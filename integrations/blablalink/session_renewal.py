"""使用现有隔离客户端提交一次 Login；候选凭证验证由用例负责。"""
from __future__ import annotations

import httpx
import time

from .client import API_BASE
from .http_transport import IsolatedCookies
from .session_cookies import apply_set_cookies, cookie_header, renewal_payload
from ...features.account.renewal_errors import RenewalFailure


class SessionRenewalGateway:
    def __init__(self, client, identity_gateway, *, clock=time.time):
        self.client = client
        self.identity_gateway = identity_gateway
        self.clock = clock

    async def identity(self, account):
        return await self.identity_gateway.identity(account)

    async def request_candidate(self, account, now):
        payload = renewal_payload(account, now)
        # 显式凭证头且禁止响应 Cookie 写入共享客户端全局容器。
        client = await self.client._get_client()
        if not isinstance(client.cookies, IsolatedCookies):
            raise ValueError("客户端 Cookie 隔离未生效，续期不可用")
        try:
            response = await client.post(API_BASE + "/api/user/Login", json=payload, headers={
            "Cookie": account["cookie"], "Origin": "https://www.blablalink.com",
            "Referer": "https://www.blablalink.com/", "x-channel-type": "2",
            "x-language": "en", "User-Agent": account.get("user_agent") or "Mozilla/5.0"})
        except httpx.HTTPError as exc:
            raise RenewalFailure("unknown_after_action", "续期请求结果未知，保留原凭证，不自动重试。", unknown=True) from exc
        if response.status_code != 200:
            status = "rate_limited" if response.status_code == 429 else "rejected"
            raise RenewalFailure(status, "官方拒绝续期请求；保留原凭证，请在官网处理登录或验证要求。")
        try:
            data = response.json()
        except ValueError as exc:
            raise RenewalFailure("incomplete_response", "续期响应结构不完整，保留原凭证。") from exc
        if not isinstance(data, dict) or type(data.get("code")) is not int or data["code"] != 0:
            raise RenewalFailure("rejected", "续期业务状态失败或未知；保留原凭证，可能仍需重新登录。")
        headers = response.headers.get_list("set-cookie")
        if not headers:
            raise RenewalFailure("no_new_cookie", "官方没有返回新 Cookie，保留原凭证。")
        try:
            received_at = self.clock()
            material = apply_set_cookies(account["session_material"], headers, received_at)
        except (ValueError, TypeError, OverflowError) as exc:
            raise RenewalFailure("incomplete_cookie", "候选 Cookie 不完整或无有效会话更新，保留原凭证。") from exc
        cookie = cookie_header(material["cookies"], API_BASE + "/api/user/CheckLogin", received_at)
        if not cookie or "game_token=" not in cookie:
            raise ValueError("候选 Cookie 不适用于官方登录检查")
        for path in ("/api/ugc/proxy/standalonesite/User/GetUserInfoNew", "/api/game/proxy/Game/GetUserProfileBasicInfo"):
            if cookie_header(material["cookies"], API_BASE + path, received_at) != cookie:
                raise ValueError("候选 Cookie 作用域不能覆盖现有账号客户端，保留原凭证")
        return cookie, material

    def invalidate(self, account):
        # 同一稳定账号可能多 QQ 绑定；只清除该游戏身份相关缓存与进行中的查询。
        self.client.invalidate_account_cache(account)

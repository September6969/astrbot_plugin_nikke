# SPDX-License-Identifier: GPL-3.0-or-later
"""浏览器扩展绑定服务。"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import secrets
import stat
import time
from collections import defaultdict, deque
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web

from ..._version import PLUGIN_VERSION
from ...features.account.status import (
    BIND_SESSION_FAILED,
    BIND_SESSION_PENDING,
    BIND_SESSION_SUCCESS,
)
from .bind_template import render_bind_page
from .ports import BindingSessionStore
from ..blablalink.client import BlaBlaClient, BlaBlaError
from ...core.privacy import sanitize_log_text


TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
ALLOWED_COOKIE_NAMES = {"game_token", "game_uid", "game_openid"}
COOKIE_NAME_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}$")
MAX_COOKIE_COUNT = 100
MAX_COOKIE_HEADER_LENGTH = 32 * 1024
EXTENSION_ORIGIN_RE = re.compile(r"^(?:chrome-extension|extension)://[a-z0-9]{16,64}$")
SITE_ORIGIN = "https://nikke.irises777.xyz"
# Cookie 值禁止分隔符与换行，避免拼接 Cookie 头时注入额外字段。
COOKIE_VALUE_FORBIDDEN_RE = re.compile(r"[;\r\n\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# User-Agent 合法地包含 ';'（如 "Windows NT 10.0; Win64"），只禁止换行与控制字符。
USER_AGENT_FORBIDDEN_RE = re.compile(r"[\r\n\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
RATE_WINDOW_SECONDS = 60.0
RATE_BUCKET_LIMIT = 4096
RATE_PRUNE_INTERVAL_SECONDS = 60.0
_LOGGER = logging.getLogger(__name__)


def _parse_trusted_proxy(value: str) -> IPv4Network | IPv6Network | None:
    """容错解析可信反代：单个 IP 或 CIDR；非法值记告警并忽略，不让插件启动失败。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return ip_network(text, strict=False)
    except ValueError:
        _LOGGER.warning("[NIKKE] web_trusted_proxy_ip 无效，已按未配置处理")
        return None


def _bad_request(code: str, message: str) -> web.Response:
    return web.json_response(
        {"ok": False, "code": code, "message": message, "error": message}, status=400
    )


async def _json_object(request: web.Request) -> dict | None:
    """读取 JSON 对象请求体；非法 JSON 或非对象结构返回 None，由调用方回 400。"""
    try:
        body = await request.json(loads=json.loads)
    except (ValueError, UnicodeDecodeError):
        return None
    return body if isinstance(body, dict) else None


def _is_regular_file(path: object) -> bool:
    """以一次 lstat 判断普通文件，避免 readiness 检查跟随符号链接或产生检查间隙。"""
    if not isinstance(path, Path):
        return False
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except (OSError, ValueError):
        return False


def public_error(exc: Exception) -> str:
    """生成可供用户和日志关联的脱敏错误，不回显凭据或邮箱。"""
    text = sanitize_log_text(exc)
    prefix = ""
    if isinstance(exc, BlaBlaError):
        location = "/".join(item for item in (exc.endpoint, exc.code) if item)
        prefix = f"[{location}] " if location else ""
    return (prefix + text)[:240]


class BindingWebService:
    def __init__(
        self,
        store: BindingSessionStore,
        client: BlaBlaClient,
        extension_zip: Path,
        api_key: str = "",
        public_base_url: str = SITE_ORIGIN,
        trusted_proxy_ip: str = "",
    ):
        parsed = urlsplit(public_base_url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            raise ValueError("绑定服务公网地址必须是HTTPS站点地址，不能包含账号、路径或查询参数")
        self.site_origin = f"https://{parsed.netloc}"
        self._trusted_proxy = _parse_trusted_proxy(trusted_proxy_ip)
        self.store = store
        self.client = client
        self.extension_zip = extension_zip
        self.api_key = api_key
        self.runner: web.AppRunner | None = None
        self._requests: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._last_rate_prune = 0.0
        self._route_installers = []

    def add_route_installer(self, installer) -> None:
        """在共享站点启动前注册独立业务路由。"""
        self._route_installers.append(installer)

    @web.middleware
    async def security_middleware(self, request: web.Request, handler):
        host = self._request_ip(request)
        now = time.monotonic()
        bucket, limit = request.get("web_rate_limit", ("default", 60))
        self._prune_rate_buckets(now)
        queue = self._requests[(host, bucket)]
        while queue and now - queue[0] > RATE_WINDOW_SECONDS:
            queue.popleft()
        if len(queue) >= limit:
            return web.json_response({"ok": False, "error": "请求过于频繁"}, status=429)
        queue.append(now)
        origin = request.headers.get("Origin", "")
        allowed_origin = origin == self.site_origin or bool(EXTENSION_ORIGIN_RE.fullmatch(origin))
        if origin and request.path.startswith("/api/") and not allowed_origin:
            return web.json_response({"ok": False, "error": "不允许的请求来源"}, status=403)
        if request.method == "OPTIONS":
            response = web.Response(status=204)
        else:
            response = await handler(request)
        if allowed_origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    def _prune_rate_buckets(self, now: float) -> None:
        """惰性淘汰过期限流桶并限制桶数量，避免大量来源 IP 让字典无界增长。"""
        if (now - self._last_rate_prune < RATE_PRUNE_INTERVAL_SECONDS
                and len(self._requests) < RATE_BUCKET_LIMIT):
            return
        self._last_rate_prune = now
        for key in [key for key, queue in self._requests.items()
                    if not queue or now - queue[-1] > RATE_WINDOW_SECONDS]:
            del self._requests[key]
        overflow = len(self._requests) - RATE_BUCKET_LIMIT + 1
        if overflow > 0:
            oldest = sorted(self._requests, key=lambda key: self._requests[key][-1])
            for key in oldest[:overflow]:
                del self._requests[key]

    def _request_ip(self, request: web.Request) -> str:
        peer = request.remote or "unknown"
        if self._trusted_proxy is not None:
            try:
                if ip_address(peer) in self._trusted_proxy:
                    # Caddy 添加的最后一个地址来自实际 TCP 对端。
                    forwarded = request.headers.getall("X-Forwarded-For", [])
                    if forwarded:
                        return str(ip_address(forwarded[-1].rsplit(",", 1)[-1].strip()))
            except ValueError:
                pass
        return peer

    def app(self) -> web.Application:
        app = web.Application(middlewares=[self.security_middleware], client_max_size=64 * 1024)
        app.add_routes(
            [
                web.get("/healthz", self.health),
                web.get("/bind/{token}", self.bind_page),
                web.post("/api/bind/session", self.create_session),
                web.post("/api/bind/cookies", self.submit_cookies),
                web.get("/api/bind/status", self.bind_status),
                web.get("/download", self.download),
                web.options("/{tail:.*}", self.options),
            ]
        )
        for installer in self._route_installers:
            installer(app)
        return app

    async def start(self, host: str, port: int) -> None:
        self.runner = web.AppRunner(self.app(), access_log=None)
        await self.runner.setup()
        await web.TCPSite(self.runner, host, port).start()

    async def stop(self) -> None:
        if self.runner:
            await self.runner.cleanup()
            self.runner = None

    async def options(self, _: web.Request) -> web.Response:
        return web.Response(status=204)

    def _storage_ready(self) -> bool:
        """数据库须为普通文件；密钥统一由 store.has_valid_key() 判定（兼容环境变量密钥）。"""
        database = getattr(self.store, "db_path", None)
        if not _is_regular_file(database):
            return False
        has_valid_key = getattr(self.store, "has_valid_key", None)
        if callable(has_valid_key):
            return bool(has_valid_key())
        return _is_regular_file(getattr(self.store, "key_path", None))

    async def health(self, _: web.Request) -> web.Response:
        ready = self._storage_ready()
        return web.json_response(
            {
                "ok": ready,
                "service": "nikke-binding",
                "version": PLUGIN_VERSION,
                "storage": "ready" if ready else "unavailable",
            },
            status=200 if ready else 503,
        )

    async def create_session(self, request: web.Request) -> web.Response:
        """供受信任的机器人进程创建绑定会话，公网匿名请求不能调用。"""
        authorization = request.headers.get("Authorization", "")
        expected = f"Bearer {self.api_key}"
        if not self.api_key or not secrets.compare_digest(authorization, expected):
            return web.json_response({"ok": False, "error": "未授权"}, status=401)
        body = await _json_object(request)
        if body is None:
            return _bad_request("INVALID_JSON", "请求体必须是 JSON 对象")
        qq_id = str(body.get("qq_id", "")).strip()
        if not qq_id.isdigit() or len(qq_id) > 20:
            return web.json_response({"ok": False, "error": "QQ号格式错误"}, status=400)
        token = secrets.token_urlsafe(32)
        self.store.create_bind_session(
            token, qq_id, 600, status=BIND_SESSION_PENDING
        )
        return web.json_response(
            {"ok": True, "token": token, "expires_in": 600, "url": f"/bind/{token}"},
            status=201,
        )

    async def bind_page(self, request: web.Request) -> web.Response:
        token = request.match_info["token"]
        session = self.store.get_bind_session(token) if TOKEN_RE.fullmatch(token) else None
        site_origin = getattr(self, "site_origin", SITE_ORIGIN)
        page = render_bind_page(token, session, site_origin)
        return web.Response(text=page, content_type="text/html")

    async def submit_cookies(self, request: web.Request) -> web.Response:
        body = await _json_object(request)
        if body is None:
            return _bad_request("INVALID_JSON", "请求体必须是 JSON 对象")
        token = str(body.get("token", ""))
        cookies = body.get("cookies", [])
        x_common_params = str(body.get("x_common_params", ""))
        user_agent = str(body.get("user_agent", ""))[:512]
        if USER_AGENT_FORBIDDEN_RE.search(user_agent):
            return _bad_request("INVALID_USER_AGENT", "User-Agent 含有非法字符")
        if not TOKEN_RE.fullmatch(token):
            return web.json_response(
                {"ok": False, "code": "TOKEN_INVALID", "message": "绑定令牌格式错误", "error": "绑定令牌格式错误"},
                status=400,
            )
        session = self.store.get_bind_session(token)
        now = int(time.time())
        if not session:
            return web.json_response(
                {"ok": False, "code": "TOKEN_INVALID", "message": "绑定链接无效", "error": "绑定链接无效"},
                status=410,
            )
        if session["used_at"] is not None:
            return web.json_response(
                {"ok": False, "code": "TOKEN_USED", "message": "此绑定链接已经使用", "error": "此绑定链接已经使用"},
                status=410,
            )
        if session["expires_at"] < now:
            return web.json_response(
                {"ok": False, "code": "TOKEN_EXPIRED", "message": "绑定链接已过期", "error": "绑定链接已过期"},
                status=410,
            )
        parts: list[str] = []
        required_names: set[str] = set()
        accepted_cookies = []
        if isinstance(cookies, list):
            for item in cookies[:MAX_COOKIE_COUNT]:
                if not isinstance(item, dict):
                    return _bad_request("INVALID_COOKIES", "Cookie 列表结构无效")
                name = str(item.get("name", ""))
                value = str(item.get("value", ""))
                domain = str(item.get("domain", "")).lower().lstrip(".")
                if domain != "blablalink.com" and not domain.endswith(".blablalink.com"):
                    continue
                if COOKIE_VALUE_FORBIDDEN_RE.search(value):
                    return _bad_request("INVALID_COOKIES", "Cookie 值含有非法字符")
                if not COOKIE_NAME_RE.fullmatch(name) or len(value) > 4096:
                    continue
                part = f"{name}={value}"
                if sum(len(existing) + 2 for existing in parts) + len(part) > MAX_COOKIE_HEADER_LENGTH:
                    break
                parts.append(part)
                accepted_cookies.append({**item, "name": name, "value": value})
                if name in ALLOWED_COOKIE_NAMES:
                    required_names.add(name)
        missing = sorted(ALLOWED_COOKIE_NAMES - required_names)
        if missing:
            msg = "缺少必要 Cookie：" + ", ".join(missing)
            return web.json_response(
                {"ok": False, "code": "MISSING_COOKIES", "message": msg, "error": msg},
                status=400,
            )
        try:
            x_common_data = json.loads(x_common_params)
        except (json.JSONDecodeError, TypeError):
            x_common_data = None
        if (
            not isinstance(x_common_data, dict)
            or not str(x_common_data.get("openid", "")).strip()
            or len(x_common_params) > 8192
        ):
            msg = "账号上下文缺失或不完整，请刷新BlaBlaLink个人主页后重试"
            return web.json_response(
                {"ok": False, "code": "MISSING_CONTEXT", "message": msg, "error": msg},
                status=400,
            )
        cookie = "; ".join(parts)
        try:
            from ..blablalink.session_cookies import capture_material
            session_material = capture_material(accepted_cookies, body.get("renewal_login_payload"))
        except (ValueError, TypeError):
            return web.json_response({"ok": False, "code": "INVALID_SESSION_MATERIAL",
                                      "message": "会话属性或可选续期材料不完整，请重新登录绑定"}, status=400)
        try:
            result = await self.client.validate_cookie(cookie)
            qq_id = self.store.consume_bind_session(
                token,
                cookie,
                result.game_uid,
                result.game_openid,
                result.nickname,
                result.role_name,
                result.area_id,
                x_common_params,
                user_agent,
                success_status=BIND_SESSION_SUCCESS,
                session_material=session_material,
            )
            if qq_id and hasattr(self.client, "invalidate_cache"):
                self.client.invalidate_cache(qq_id)
            return web.json_response({
                "ok": True,
                "code": "BOUND",
                "data": {
                    "nickname": result.nickname,
                    "qq_id": qq_id,
                },
                "qq_id": qq_id,
                "nickname": result.nickname,
            })
        except (BlaBlaError, ValueError) as exc:
            error = public_error(exc)
            self.store.fail_bind_session(
                token, error, status=BIND_SESSION_FAILED
            )
            return web.json_response(
                {"ok": False, "code": "INVALID_COOKIE", "message": error, "error": error},
                status=400,
            )
        except Exception:
            self.store.fail_bind_session(
                token, "服务器验证失败", status=BIND_SESSION_FAILED
            )
            return web.json_response(
                {"ok": False, "code": "SERVER_ERROR", "message": "服务器验证失败，请稍后重试", "error": "服务器验证失败，请稍后重试"},
                status=502,
            )

    async def bind_status(self, request: web.Request) -> web.Response:
        token = str(request.query.get("token", ""))
        session = self.store.get_bind_session(token) if TOKEN_RE.fullmatch(token) else None
        if not session:
            return web.json_response({"ok": False, "status": "missing"}, status=404)
        now = int(time.time())
        expired = session["expires_at"] < now
        status = session["status"]
        masked_qq = ""
        qq_id = session.get("qq_id", "")
        if qq_id:
            masked_qq = f"********{qq_id[-4:]}" if len(qq_id) >= 4 else "********"
        account = None
        if status in ("success", "consumed") and qq_id:
            account = self.store.get_account(qq_id, with_cookie=False)
        nickname = account.get("nickname") if account else ""

        return web.json_response(
            {
                "ok": True,
                "status": status,
                "expired": expired,
                "error": session["error"],
                "nickname": nickname,
                "masked_qq": masked_qq,
                "remaining_seconds": max(0, session["expires_at"] - now) if not expired else 0,
            }
        )

    async def download(self, _: web.Request) -> web.StreamResponse:
        if not self.extension_zip.exists():
            raise web.HTTPNotFound(text="扩展尚未打包")
        return web.FileResponse(self.extension_zip, headers={"Content-Disposition": 'attachment; filename="nikke-bind-extension.zip"'})

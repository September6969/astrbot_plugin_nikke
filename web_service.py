# SPDX-License-Identifier: GPL-3.0-or-later
"""浏览器扩展绑定服务。"""

from __future__ import annotations

import html
import json
import re
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web

from ._version import PLUGIN_VERSION

from .client import BlaBlaClient, BlaBlaError
from .storage import NikkeStore


TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
ALLOWED_COOKIE_NAMES = {"game_token", "game_uid", "game_openid"}
COOKIE_NAME_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}$")
MAX_COOKIE_COUNT = 100
MAX_COOKIE_HEADER_LENGTH = 32 * 1024
EXTENSION_ORIGIN_RE = re.compile(r"^(?:chrome-extension|extension)://[a-z0-9]{16,64}$")
SITE_ORIGIN = "https://nikke.irises777.xyz"


def public_error(exc: Exception) -> str:
    """生成可供用户和日志关联的脱敏错误，不回显凭据或邮箱。"""
    text = str(exc).replace("\r", " ").replace("\n", " ")
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+", "[邮箱已遮盖]", text)
    text = re.sub(r"(?i)((?:token|cookie|authorization)\s*[:=]\s*)[^\s,;]+", r"\1[已遮盖]", text)
    prefix = ""
    if isinstance(exc, BlaBlaError):
        location = "/".join(item for item in (exc.endpoint, exc.code) if item)
        prefix = f"[{location}] " if location else ""
    return (prefix + text)[:240]


class BindingWebService:
    def __init__(self, store: NikkeStore, client: BlaBlaClient, extension_zip: Path, api_key: str = "", public_base_url: str = SITE_ORIGIN):
        parsed = urlsplit(public_base_url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            raise ValueError("绑定服务公网地址必须是HTTPS站点地址，不能包含账号、路径或查询参数")
        self.site_origin = f"https://{parsed.netloc}"
        self.store = store
        self.client = client
        self.extension_zip = extension_zip
        self.api_key = api_key
        self.runner: web.AppRunner | None = None
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    @web.middleware
    async def security_middleware(self, request: web.Request, handler):
        host = request.remote or "unknown"
        now = time.monotonic()
        queue = self._requests[host]
        while queue and now - queue[0] > 60:
            queue.popleft()
        if len(queue) >= 60:
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

    async def health(self, _: web.Request) -> web.Response:
        return web.json_response({"ok": True, "service": "nikke-binding", "version": PLUGIN_VERSION})

    async def create_session(self, request: web.Request) -> web.Response:
        """供受信任的机器人进程创建绑定会话，公网匿名请求不能调用。"""
        authorization = request.headers.get("Authorization", "")
        expected = f"Bearer {self.api_key}"
        if not self.api_key or not secrets.compare_digest(authorization, expected):
            return web.json_response({"ok": False, "error": "未授权"}, status=401)
        body = await request.json(loads=json.loads)
        qq_id = str(body.get("qq_id", "")).strip()
        if not qq_id.isdigit() or len(qq_id) > 20:
            return web.json_response({"ok": False, "error": "QQ号格式错误"}, status=400)
        token = secrets.token_urlsafe(32)
        self.store.create_bind_session(token, qq_id, 600)
        return web.json_response(
            {"ok": True, "token": token, "expires_in": 600, "url": f"/bind/{token}"},
            status=201,
        )

    async def bind_page(self, request: web.Request) -> web.Response:
        token = request.match_info["token"]
        session = self.store.get_bind_session(token) if TOKEN_RE.fullmatch(token) else None
        valid = bool(session and session["expires_at"] >= int(time.time()) and session["used_at"] is None)
        status = "链接有效，请在扩展中粘贴本页地址。" if valid else "链接无效、已使用或已过期。"
        page = f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'><title>NIKKE 安全绑定</title>
<style>body{{font-family:system-ui;background:#10131a;color:#eef2f7;margin:0}}main{{max-width:720px;margin:8vh auto;padding:36px;background:#191f2a;border-top:6px solid #f2b229}}a{{color:#f2b229}}code{{word-break:break-all}}.ok{{color:#71d49b}}.bad{{color:#ff776d}}</style></head>
<body><main><h1>NIKKE · BlaBlaLink 安全绑定</h1><p class='{"ok" if valid else "bad"}'>{html.escape(status)}</p>
<p>1. 安装辅助扩展；2. 点击扩展打开BlaBlaLink并完成官方登录；3. 回到扩展提交Cookie。</p>
<p>机器人不会接收或保存你的账号密码。</p>
<p><a href='/download'>从绑定服务器下载扩展</a> · <a href='https://github.com/September6969/astrbot_plugin_nikke/releases'>GitHub备用下载</a></p>
<code>{html.escape(str(request.url))}</code></main></body></html>"""
        return web.Response(text=page, content_type="text/html")

    async def submit_cookies(self, request: web.Request) -> web.Response:
        body = await request.json(loads=json.loads)
        token = str(body.get("token", ""))
        cookies = body.get("cookies", [])
        x_common_params = str(body.get("x_common_params", ""))
        user_agent = str(body.get("user_agent", ""))[:512]
        if not TOKEN_RE.fullmatch(token):
            return web.json_response({"ok": False, "error": "绑定令牌格式错误"}, status=400)
        session = self.store.get_bind_session(token)
        now = int(time.time())
        if not session or session["expires_at"] < now or session["used_at"] is not None:
            return web.json_response({"ok": False, "error": "绑定链接无效、已使用或已过期"}, status=410)
        parts: list[str] = []
        required_names: set[str] = set()
        if isinstance(cookies, list):
            for item in cookies[:MAX_COOKIE_COUNT]:
                name = str(item.get("name", ""))
                value = str(item.get("value", ""))
                domain = str(item.get("domain", "")).lower().lstrip(".")
                if domain != "blablalink.com" and not domain.endswith(".blablalink.com"):
                    continue
                if not COOKIE_NAME_RE.fullmatch(name) or len(value) > 4096:
                    continue
                part = f"{name}={value}"
                if sum(len(existing) + 2 for existing in parts) + len(part) > MAX_COOKIE_HEADER_LENGTH:
                    break
                parts.append(part)
                if name in ALLOWED_COOKIE_NAMES:
                    required_names.add(name)
        missing = sorted(ALLOWED_COOKIE_NAMES - required_names)
        if missing:
            return web.json_response(
                {"ok": False, "error": "缺少必要 Cookie：" + ", ".join(missing)},
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
            return web.json_response(
                {"ok": False, "error": "账号上下文缺失或不完整，请刷新BlaBlaLink个人主页后重试"},
                status=400,
            )
        cookie = "; ".join(parts)
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
            )
            return web.json_response({"ok": True, "qq_id": qq_id, "nickname": result.nickname})
        except (BlaBlaError, ValueError) as exc:
            error = public_error(exc)
            self.store.fail_bind_session(token, error)
            return web.json_response({"ok": False, "error": error}, status=400)
        except Exception:
            self.store.fail_bind_session(token, "服务器验证失败")
            return web.json_response({"ok": False, "error": "服务器验证失败，请稍后重试"}, status=502)

    async def bind_status(self, request: web.Request) -> web.Response:
        token = str(request.query.get("token", ""))
        session = self.store.get_bind_session(token) if TOKEN_RE.fullmatch(token) else None
        if not session:
            return web.json_response({"ok": False, "status": "missing"}, status=404)
        return web.json_response(
            {
                "ok": True,
                "status": session["status"],
                "expired": session["expires_at"] < int(time.time()),
                "error": session["error"],
            }
        )

    async def download(self, _: web.Request) -> web.StreamResponse:
        if not self.extension_zip.exists():
            raise web.HTTPNotFound(text="扩展尚未打包")
        return web.FileResponse(self.extension_zip, headers={"Content-Disposition": 'attachment; filename="nikke-bind-extension.zip"'})

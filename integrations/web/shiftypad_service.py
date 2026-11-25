# SPDX-License-Identifier: GPL-3.0-or-later
"""ShiftyPad 只读导入的短时网页入口。

安全模型与竞技场编辑页一致：
- ``/shiftypad/open/{token}`` 仅展示同源兑换引导页，GET 不检查也不消费令牌；
- ``POST /shiftypad/api/claim`` 校验 Origin 后一次性兑换令牌并签发 ``__Secure-nikke_shiftypad`` Cookie 与 CSRF 密钥；
- 编辑页面与所有状态/读写 API 仅认同源 Cookie + CSRF 头，HTML/URL/JS 中不包含令牌；
- 受 ``enable_shiftypad_readonly`` 开关控制，未开启时所有接口 fail-closed 返回 404 并清理临时会话。
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import secrets
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from aiohttp import web

from ...features.shiftypad.identity import UidMappingResolver
from ...features.shiftypad.models import (
    ShiftypadPrivateError,
    ShiftypadProfile,
    ShiftypadUpstreamError,
)
from ...features.shiftypad.storage import ShiftypadReadOnlyStore

LINKS_KEY = "shiftypad_web_links_v2"
SESSIONS_KEY = "shiftypad_web_sessions_v2"
COOKIE = "__Secure-nikke_shiftypad"
CSRF_HEADER = "X-Shiftypad-CSRF"
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_SESSION_REQ_KEY: web.RequestKey[tuple[str, dict[str, Any], dict[str, dict[str, Any]]]] = (
    web.RequestKey("shiftypad_session", tuple)
)
LINK_TTL = 600
SESSION_TTL = 3600
IDLE_TTL = 1800
PREVIEW_TTL = 300
MAX_SESSIONS = 200
MAX_BODY = 16 * 1024
SESSION_RATE_LIMIT = 30
SESSION_RATE_WINDOW = 60
_DEFAULT_TEMPLATE_ROOT = Path(__file__).resolve().parents[2] / "templates" / "shiftypad_web"
_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
}


def _json_error(code: str, message: str, status: int = 400, **extra: Any) -> web.Response:
    payload = {"ok": False, "code": code, "message": message, "error": message}
    payload.update(extra)
    return web.json_response(payload, status=status)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ShiftypadWebService:
    """ShiftyPad 同源会话制只读导入网页服务。"""

    def __init__(
        self,
        *,
        store: Any,
        readonly: ShiftypadReadOnlyStore,
        resolver: UidMappingResolver,
        fetcher: Any,
        site_origin: str,
        clock=None,
        session_ttl: int = SESSION_TTL,
        link_ttl: int = LINK_TTL,
        enabled: Callable[[], bool] | bool = True,
        template_root: Path | None = None,
    ) -> None:
        self._store = store
        self._readonly = readonly
        self._resolver = resolver
        self._fetcher = fetcher
        self.site_origin = str(site_origin).rstrip("/")
        self._clock = clock or (lambda: time.time())
        self._session_ttl = max(1, int(session_ttl))
        self._link_ttl = max(1, int(link_ttl))
        self._enabled = enabled
        self._template_root = Path(template_root) if template_root else _DEFAULT_TEMPLATE_ROOT

    def _now(self) -> int:
        value = self._clock()
        return int(value.timestamp()) if isinstance(value, datetime) else int(value)

    def active(self) -> bool:
        """检查功能是否开启；关闭时立即清理挂起入口与临时会话。"""
        enabled = self._enabled() if callable(self._enabled) else bool(self._enabled)
        if not enabled:
            if self._store.get_setting(LINKS_KEY, None):
                self._store.set_setting(LINKS_KEY, {})
            if self._store.get_setting(SESSIONS_KEY, None):
                self._store.set_setting(SESSIONS_KEY, {})
            return False
        return True

    def _clean_map(self, key: str, *, idle_check: bool = False) -> dict[str, dict[str, Any]]:
        raw = self._store.get_setting(key, {})
        if not isinstance(raw, dict):
            return {}
        now = self._now()
        cleaned: dict[str, dict[str, Any]] = {}
        for item_key, value in raw.items():
            if not isinstance(value, dict):
                continue
            if int(value.get("expires_at", 0)) <= now:
                continue
            if idle_check:
                accessed = int(value.get("accessed_at", value.get("created_at", 0)))
                if now - accessed >= IDLE_TTL:
                    continue
            cleaned[str(item_key)] = value
        if len(cleaned) > MAX_SESSIONS:
            ordered = sorted(cleaned.items(), key=lambda item: item[1].get("created_at", 0))
            cleaned = dict(ordered[-MAX_SESSIONS:])
        return cleaned

    def _links(self) -> dict[str, dict[str, Any]]:
        return self._clean_map(LINKS_KEY, idle_check=False)

    def _save_links(self, links: Mapping[str, Any]) -> None:
        self._store.set_setting(LINKS_KEY, dict(links))

    def _sessions(self) -> dict[str, dict[str, Any]]:
        return self._clean_map(SESSIONS_KEY, idle_check=True)

    def _save_sessions(self, sessions: Mapping[str, Any]) -> None:
        self._store.set_setting(SESSIONS_KEY, dict(sessions))

    def create_link(self, actor_id: str) -> str:
        if not self.active():
            raise ValueError("ShiftyPad 只读导入未启用，请由管理员开启 enable_shiftypad_readonly。")
        actor = str(actor_id or "").strip()
        if not actor:
            raise ValueError("缺少机器人用户标识")
        now = self._now()
        # 同一用户重新申请时，撤销尚未兑换的旧入口链接。
        links = {
            key: value
            for key, value in self._links().items()
            if value.get("actor_id") != actor
        }
        if len(links) >= MAX_SESSIONS:
            raise ValueError("ShiftyPad 入口已满，请稍后重试。")
        token = secrets.token_urlsafe(32)
        links[_token_hash(token)] = {
            "actor_id": actor,
            "created_at": now,
            "expires_at": now + self._link_ttl,
        }
        self._save_links(links)
        return f"{self.site_origin}/shiftypad/open/{token}"

    def _cookie_session(
        self, request: web.Request, *, touch: bool = True
    ) -> tuple[str, dict[str, Any], dict[str, dict[str, Any]]]:
        cookie = str(request.cookies.get(COOKIE, "") or "")
        if not TOKEN_RE.fullmatch(cookie):
            raise web.HTTPUnauthorized(reason="请回私聊获取新的 ShiftyPad 导入链接")
        sessions = self._sessions()
        digest = _token_hash(cookie)
        record = sessions.get(digest)
        if not isinstance(record, dict):
            raise web.HTTPUnauthorized(reason="网页会话已过期，请回私聊重新获取")
        if touch:
            record["accessed_at"] = self._now()
            sessions[digest] = record
            self._save_sessions(sessions)
        return digest, record, sessions

    async def _read_limited_body(self, request: web.Request) -> bytes:
        chunks: list[bytes] = []
        total = 0
        async for chunk in request.content.iter_chunked(4096):
            total += len(chunk)
            if total > MAX_BODY:
                raise web.HTTPRequestEntityTooLarge(reason="请求体超过 16KB 限制")
            chunks.append(chunk)
        return b"".join(chunks)

    async def _read_json(self, request: web.Request) -> tuple[dict[str, Any] | None, web.Response | None]:
        raw = await self._read_limited_body(request)
        if request.content_type != "application/json":
            return None, _json_error("INVALID_CONTENT_TYPE", "需要 application/json 请求")
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None, _json_error("INVALID_JSON", "请求格式无效")
        if not isinstance(parsed, dict):
            return None, _json_error("INVALID_JSON", "请求必须是对象")
        return parsed, None

    @web.middleware
    async def security(self, request: web.Request, handler):
        if not request.path.startswith("/shiftypad/"):
            return await handler(request)
        response: web.Response
        try:
            if not self.active():
                return self._apply_headers(
                    _json_error("DISABLED", "ShiftyPad 只读导入当前未启用。", 404)
                )
            if request.method not in {"GET", "HEAD"}:
                if request.headers.get("Origin") != self.site_origin:
                    return self._apply_headers(
                        _json_error("FORBIDDEN_ORIGIN", "来源校验失败", 403)
                    )
                if request.content_length is not None and request.content_length > MAX_BODY:
                    return self._apply_headers(
                        _json_error("PAYLOAD_TOO_LARGE", "请求体超过大小限制", 413)
                    )
                if request.path != "/shiftypad/api/claim":
                    digest, session, sessions = self._cookie_session(request, touch=True)
                    csrf_header = str(request.headers.get(CSRF_HEADER, "") or "")
                    csrf_expected = str(session.get("csrf") or "")
                    if not csrf_expected or not secrets.compare_digest(csrf_header, csrf_expected):
                        return self._apply_headers(
                            _json_error("FORBIDDEN_CSRF", "CSRF 校验失败", 403)
                        )
                    request[_SESSION_REQ_KEY] = (digest, session, sessions)
            elif request.path.startswith("/shiftypad/api/"):
                digest, session, sessions = self._cookie_session(request, touch=True)
                request[_SESSION_REQ_KEY] = (digest, session, sessions)

            if request.path.startswith("/shiftypad/api/") and request.path != "/shiftypad/api/claim":
                digest, session, sessions = request[_SESSION_REQ_KEY]
                now = self._now()
                recent = [
                    ts
                    for ts in (session.get("requests") or [])
                    if isinstance(ts, (int, float)) and now - ts < SESSION_RATE_WINDOW
                ]
                if len(recent) >= SESSION_RATE_LIMIT:
                    return self._apply_headers(
                        _json_error("RATE_LIMITED", "会话请求过于频繁", 429)
                    )
                recent.append(now)
                session["requests"] = recent
                sessions[digest] = session
                self._save_sessions(sessions)

            response = await handler(request)
        except web.HTTPRequestEntityTooLarge as exc:
            response = _json_error("PAYLOAD_TOO_LARGE", exc.reason or "请求体过大", 413)
        except web.HTTPUnauthorized as exc:
            response = _json_error("EXPIRED", exc.reason or "网页会话已过期", 401)
        except web.HTTPForbidden as exc:
            response = _json_error("FORBIDDEN", exc.reason or "权限校验失败", 403)
        except web.HTTPNotFound as exc:
            response = _json_error("NOT_FOUND", exc.reason or "资源不存在", 404)
        except web.HTTPException as exc:
            if exc.status in {302, 303}:
                response = exc
            else:
                response = _json_error("HTTP_ERROR", exc.reason or "请求失败", exc.status)
        except ValueError as exc:
            response = _json_error("BAD_REQUEST", str(exc), 400)
        return self._apply_headers(response)

    @staticmethod
    def _apply_headers(response: web.Response) -> web.Response:
        response.headers.update(_SECURITY_HEADERS)
        return response

    def state_for_session(self, session: Mapping[str, Any]) -> dict[str, Any]:
        actor = str(session.get("actor_id") or "")
        readonly = self._readonly.status(actor)
        remaining = max(0, int(session.get("expires_at", 0)) - self._now())
        return {
            "ok": True,
            "csrf": str(session.get("csrf") or ""),
            "status": readonly["status"],
            "binding": readonly.get("binding"),
            "last_error": readonly.get("last_error", ""),
            "remaining_seconds": remaining,
            "uid_standalone_supported": False,
            "uid_mapping_available": self._resolver.available,
            "uid_note": (
                "数字 UID 不是 ShiftyPad OpenID；未发现受支持的公开 UID→OpenID 接口。"
                "请粘贴本人官方 ShiftyPad 公开链接，或由运营者导入可信 UID 映射。"
            ),
            "fallback_url": "https://www.blablalink.com/shiftyspad/home",
        }

    async def open_page(self, request: web.Request) -> web.Response:
        token = str(request.match_info.get("token") or "")
        if not TOKEN_RE.fullmatch(token):
            raise web.HTTPNotFound()
        # GET 不检查持有人、不消费令牌，也不返回任何绑定资料；只提供同源 POST 兑换表单。
        safe_token = html.escape(token, quote=True)
        markup = (
            "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<meta name=\"referrer\" content=\"no-referrer\">"
            "<link rel=\"stylesheet\" href=\"/shiftypad/static/editor.css\">"
            "<script src=\"/shiftypad/static/claim.js\" defer></script>"
            "<title>进入 ShiftyPad 只读导入</title></head><body><main>"
            "<h1>ShiftyPad 只读导入</h1>"
            "<p>点击后兑换本次一次性入口，进入自己的短时只读导入会话（不登录、不写入游戏账号）。</p>"
            "<form id=\"claim\" method=\"post\" action=\"/shiftypad/api/claim\">"
            f"<input type=\"hidden\" name=\"token\" value=\"{safe_token}\">"
            "<button type=\"submit\">进入只读导入</button></form>"
            "<p id=\"claim-status\" role=\"status\"></p>"
            "<noscript>请启用 JavaScript，或回私聊重新获取入口。</noscript>"
            "<p class=\"note\">链接仅一次性有效；已用过或过期请回私聊重新发送 "
            "<code>/妮姬 我的妮姬 导入</code>。</p>"
            "</main></body></html>"
        )
        return web.Response(text=markup, content_type="text/html")

    async def claim(self, request: web.Request) -> web.Response:
        if request.content_type != "application/x-www-form-urlencoded":
            return _json_error("INVALID_CONTENT_TYPE", "请从引导页面进入只读导入。", 400)
        raw = await self._read_limited_body(request)
        try:
            parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True, strict_parsing=False)
        except UnicodeDecodeError:
            return _json_error("INVALID_FORM", "无效的表单编码。", 400)
        if set(parsed) != {"token"} or len(parsed["token"]) != 1:
            return _json_error("INVALID_TOKEN", "无效的导入链接。", 400)
        token = parsed["token"][0]
        if not TOKEN_RE.fullmatch(token):
            return _json_error("INVALID_TOKEN", "无效的导入链接。", 400)
        links = self._links()
        digest = _token_hash(token)
        link = links.pop(digest, None)
        if not isinstance(link, dict):
            return _json_error(
                "EXPIRED",
                "入口已过期或已使用，请回私聊重新发送 /妮姬 我的妮姬 导入",
                410,
            )
        self._save_links(links)
        sessions = self._sessions()
        if len(sessions) >= MAX_SESSIONS:
            return _json_error("CAPACITY", "临时会话已满，请稍后重试。", 503)
        cookie = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        now = self._now()
        sessions[_token_hash(cookie)] = {
            "actor_id": str(link.get("actor_id") or ""),
            "csrf": csrf,
            "created_at": now,
            "accessed_at": now,
            "expires_at": now + self._session_ttl,
            "preview": None,
            "requests": [],
        }
        self._save_sessions(sessions)
        response = (
            web.json_response({"ok": True, "redirect": "/shiftypad/edit"})
            if request.headers.get("Accept") == "application/json"
            else web.Response(status=303, headers={"Location": "/shiftypad/edit"})
        )
        response.set_cookie(
            COOKIE,
            cookie,
            path="/shiftypad",
            secure=True,
            httponly=True,
            samesite="Lax",
            max_age=self._session_ttl,
        )
        return response

    async def edit_page(self, request: web.Request) -> web.Response:
        self._cookie_session(request, touch=True)
        return web.Response(
            text=(self._template_root / "index.html").read_text(encoding="utf-8"),
            content_type="text/html",
        )

    async def static_file(self, request: web.Request) -> web.Response:
        name = str(request.match_info.get("name") or "")
        if name not in {"claim.js", "editor.js", "editor.css"}:
            raise web.HTTPNotFound()
        return web.Response(
            text=(self._template_root / name).read_text(encoding="utf-8"),
            content_type="text/javascript" if name.endswith(".js") else "text/css",
        )

    async def state_route(self, request: web.Request) -> web.Response:
        _, session, _ = request[_SESSION_REQ_KEY]
        return web.json_response(self.state_for_session(session))

    async def preview(self, request: web.Request) -> web.Response:
        digest, session, sessions = request[_SESSION_REQ_KEY]
        data, err = await self._read_json(request)
        if err is not None or data is None:
            return err  # type: ignore[return-value]
        if data.get("confirmed_public") is not True:
            return _json_error("PUBLIC_CONFIRM_REQUIRED", "请先确认该档案已对所有人公开并获得本人授权")
        uid = str(data.get("uid") or "").strip()
        server = str(data.get("server") or "").strip()
        public_ref = str(data.get("public_ref") or "").strip()
        if len(uid) > 32 or len(server) > 32 or len(public_ref) > 512:
            return _json_error("INVALID_INPUT", "输入长度超出限制")
        resolution = self._resolver.resolve(uid, server, public_reference=public_ref)
        if resolution.status != "resolved" or resolution.identity is None:
            return _json_error(
                "UID_UNRESOLVED",
                resolution.reason or "无法解析该 UID/公开链接",
                400,
                fallback_url=resolution.fallback_url,
                uid_standalone_supported=resolution.uid_standalone,
            )
        try:
            profile = await self._fetcher.fetch(resolution.identity)
        except ShiftypadPrivateError as exc:
            return _json_error("PRIVATE", str(exc), 403)
        except ShiftypadUpstreamError as exc:
            return _json_error("UPSTREAM", str(exc), 502)
        except Exception as exc:
            return _json_error("UPSTREAM", f"读取公开档案失败（{type(exc).__name__}）", 502)
        preview_id = secrets.token_urlsafe(18)
        stored_profile = profile.to_dict(include_identity=True)
        stored_profile["identity"] = {
            "openid": profile.identity.openid,
            "uid": profile.identity.uid,
            "server": profile.identity.server,
            "area_id": profile.identity.area_id,
            "source": profile.identity.source,
            "source_url": profile.identity.source_url,
        }
        session["preview"] = {
            "id": preview_id,
            "profile": stored_profile,
            "expires_at": self._now() + PREVIEW_TTL,
        }
        sessions[digest] = session
        self._save_sessions(sessions)
        payload = profile.to_dict(include_identity=False)
        payload["identity"] = {
            "uid": profile.identity.uid,
            "server": profile.identity.server,
            "area_id": profile.identity.area_id,
            "source": profile.identity.source,
            "source_url": profile.identity.source_url,
        }
        payload.update(
            {
                "ok": True,
                "preview_id": preview_id,
                "expires_in": PREVIEW_TTL,
                "warnings": [
                    "只读导入不会获得登录、私有账号或角色库写入权限。",
                    "需要 ShiftyPad 的持有妮姬与前哨对所有人可见；未公开会拒绝导入。",
                    "数字 UID 仅作本人标注；可查询身份来自公开链接或可信映射。",
                ],
            }
        )
        return web.json_response(payload)

    async def bind(self, request: web.Request) -> web.Response:
        digest, session, sessions = request[_SESSION_REQ_KEY]
        data, err = await self._read_json(request)
        if err is not None or data is None:
            return err  # type: ignore[return-value]
        preview = session.get("preview")
        if not isinstance(preview, Mapping) or int(preview.get("expires_at", 0)) < self._now():
            return _json_error("PREVIEW_EXPIRED", "预览已过期，请重新检查资料")
        if str(data.get("preview_id") or "") != str(preview.get("id") or ""):
            return _json_error("PREVIEW_MISMATCH", "预览标识不匹配，请重新检查")
        try:
            profile = ShiftypadProfile.from_dict(preview.get("profile") or {})
        except (TypeError, ValueError):
            return _json_error("INVALID_PREVIEW", "预览数据损坏，请重新检查")
        binding = self._readonly.bind(str(session.get("actor_id") or ""), profile)
        session["preview"] = None
        sessions[digest] = session
        self._save_sessions(sessions)
        return web.json_response({"ok": True, "status": binding.public_dict()})

    async def sync(self, request: web.Request) -> web.Response:
        _, session, _ = request[_SESSION_REQ_KEY]
        _, err = await self._read_json(request)
        if err is not None:
            return err
        actor = str(session.get("actor_id") or "")
        outcome = await self._readonly.sync(actor, self._fetcher)
        state = self._readonly.status(actor)
        if not outcome.ok:
            return web.json_response(
                {
                    "ok": False,
                    "code": outcome.error_code,
                    "message": outcome.message,
                    "status": state["status"],
                    "binding": state.get("binding"),
                },
                status=409 if outcome.error_code == "PRIVATE" else 502,
            )
        return web.json_response(
            {
                "ok": True,
                "changed": outcome.changed,
                "message": outcome.message,
                "status": state["status"],
                "binding": state.get("binding"),
            }
        )

    async def unbind(self, request: web.Request) -> web.Response:
        _, session, _ = request[_SESSION_REQ_KEY]
        _, err = await self._read_json(request)
        if err is not None:
            return err
        self._readonly.unbind(str(session.get("actor_id") or ""))
        return web.json_response({"ok": True, "status": "unbound"})

    async def revoke(self, request: web.Request) -> web.Response:
        digest, _, sessions = request[_SESSION_REQ_KEY]
        _, err = await self._read_json(request)
        if err is not None:
            return err
        sessions.pop(digest, None)
        self._save_sessions(sessions)
        response = web.json_response({"ok": True})
        response.del_cookie(COOKIE, path="/shiftypad")
        return response

    def mount(self, app: web.Application) -> None:
        app.middlewares.insert(0, self.security)
        app.add_routes(
            [
                web.get("/shiftypad/open/{token}", self.open_page),
                web.post("/shiftypad/api/claim", self.claim),
                web.get("/shiftypad/edit", self.edit_page),
                web.get("/shiftypad/static/{name}", self.static_file),
                web.get("/shiftypad/api/state", self.state_route),
                web.post("/shiftypad/api/preview", self.preview),
                web.post("/shiftypad/api/bind", self.bind),
                web.post("/shiftypad/api/sync", self.sync),
                web.post("/shiftypad/api/unbind", self.unbind),
                web.post("/shiftypad/api/revoke", self.revoke),
            ]
        )


__all__ = [
    "COOKIE",
    "CSRF_HEADER",
    "LINKS_KEY",
    "MAX_BODY",
    "SESSIONS_KEY",
    "ShiftypadWebService",
]

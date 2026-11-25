# SPDX-License-Identifier: GPL-3.0-or-later
"""个人指挥官工作台（/workspace）受控同源服务（Phase 5 & Phase 6）。

安全与收敛保障：
1. 严格一次性入口：GET /workspace/open/{token} 不消费、不泄漏账号信息；
   POST /workspace/api/claim 兑换后签发 __Secure-nikke_workspace Cookie 与 CSRF 密钥；
2. 按需懒加载：GET /workspace/api/bootstrap 绝不触发上游网络请求；
   个人档案、角色练度、单卡、单人突袭估伤与竞技场分析均由用户点击触发；
3. QQ-Web-QQ 受控回发闭环：先 POST /workspace/api/share/preview 展示目标会话与脱敏正文并签发
   一次性确认令牌，再由用户显式提交 POST /workspace/api/share/confirm；
   若发送状态未知（status="unknown"），严禁自动重放。
"""

from __future__ import annotations

import asyncio
import html
import re
import secrets
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

from ...features.account.identity import canonical_account_identity
from ...features.account.status import BIND_SESSION_PENDING
from ...features.arena.presentation import analysis_text, three_team_text
from ...features.catalog import workspace_catalog_payload
from ...features.favorite_grid.grid import resolve_nine
from ...features.overload_advice.advisor import (
    OverloadAdviceError,
    advise,
    parse_options,
    parse_targets,
    render_advice,
)
from ...features.solo_raid.builder import (
    build_five_teams,
    members_from_roster,
    parse_members,
    render_plan,
)
from ...features.sync.calculator import (
    SyncLevelInputError,
    calculate_sync_plan,
    render_sync_plan,
)
from ...features.web_portal import (
    PortalSessionStore,
    WorkspaceSession,
    mask_actor_label,
    redact_share_text,
)
from ...features.wishlist.advisor import (
    OwnedCharacter,
    WishlistError,
    normalize_strategy,
    parse_owned,
    recommend,
    render_wishlist,
)
from .portal_bridge import PortalHostBridge
from .portal_security import (
    apply_portal_headers,
    check_csrf,
    check_same_origin,
    check_session_rate,
    portal_error,
    read_json_object,
)

WORKSPACE_COOKIE = "__Secure-nikke_workspace"
WORKSPACE_CSRF_HEADER = "X-Workspace-CSRF"
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9_-]{8,96}$")
_CST = timezone(timedelta(hours=8))
_DEFAULT_TEMPLATE_ROOT = (
    Path(__file__).resolve().parents[2] / "templates" / "workspace_web"
)


class WorkspaceWebService:
    """个人指挥官工作台（自助绑定、懒加载分析、五队编组与受控分享）。"""

    def __init__(
        self,
        *,
        site_origin: str,
        sessions: PortalSessionStore,
        bridge: PortalHostBridge,
        store: Any,
        feature_flags: Callable[[], Mapping[str, bool]] | Mapping[str, bool] = (),
        profile_application: Any = None,
        character_application: Any = None,
        toolbox: Any = None,
        arena_application: Any = None,
        arena_web: Any = None,
        voice_application: Any = None,
        directory_provider: Callable[[], Any] | None = None,
        template_root: Path | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.site_origin = str(site_origin).rstrip("/")
        self.sessions = sessions
        self.bridge = bridge
        self.store = store
        self._feature_flags = feature_flags
        self.profile_application = profile_application
        self.character_application = character_application
        self.toolbox = toolbox
        self.arena_application = arena_application
        self.arena_web = arena_web
        self.voice_application = voice_application
        self._directory_provider = directory_provider
        self.template_root = (
            Path(template_root) if template_root else _DEFAULT_TEMPLATE_ROOT
        )
        self._clock = clock or (lambda: datetime.now(_CST))

    def _flags(self) -> Mapping[str, bool]:
        raw = self._feature_flags() if callable(self._feature_flags) else self._feature_flags
        return dict(raw) if isinstance(raw, Mapping) else {}

    def create_link(
        self,
        actor_id: str,
        *,
        conversation_id: str = "",
        group_label: str = "",
    ) -> str:
        token = self.sessions.create_workspace_link(
            actor_id,
            conversation_id=conversation_id,
            group_label=group_label,
        )
        return f"{self.site_origin}/workspace/open/{token}"

    def mount(self, app: web.Application) -> None:
        app.middlewares.insert(0, self.security)
        app.add_routes(
            [
                web.get("/workspace", self.index),
                web.get("/workspace/open/{token}", self.open),
                web.post("/workspace/api/claim", self.claim),
                web.post("/workspace/api/revoke", self.revoke),
                web.get("/workspace/static/{name}", self.static),
                web.get("/workspace/api/bootstrap", self.bootstrap),
                web.post("/workspace/api/bind/start", self.bind_start),
                web.get("/workspace/api/bind/status", self.bind_status),
                web.post("/workspace/api/profile/load", self.load_profile),
                web.post("/workspace/api/roster/load", self.load_roster),
                web.post("/workspace/api/character/load", self.load_character),
                web.post("/workspace/api/arena/open", self.open_arena),
                web.post("/workspace/api/arena/analyze", self.analyze_arena),
                web.get("/workspace/api/solo-raid/context", self.solo_raid_context),
                web.post("/workspace/api/solo-raid/build", self.solo_raid_build),
                web.post("/workspace/api/tools/wishlist", self.tool_wishlist),
                web.post("/workspace/api/tools/sync", self.tool_sync),
                web.post("/workspace/api/tools/overload", self.tool_overload),
                web.get("/workspace/api/settings", self.get_settings),
                web.post("/workspace/api/settings", self.update_settings),
                web.post("/workspace/api/share/preview", self.share_preview),
                web.post("/workspace/api/share/confirm", self.share_confirm),
            ]
        )

    def _require_session(self, request: web.Request) -> WorkspaceSession:
        cookie = str(request.cookies.get(WORKSPACE_COOKIE, "") or "")
        session = self.sessions.get_workspace(cookie, touch=True) if cookie else None
        if session is None:
            raise web.HTTPUnauthorized(reason="工作台会话无效或已过期，请回 QQ 私聊发送 /妮姬 工作台。")
        return session

    @web.middleware
    async def security(self, request: web.Request, handler):
        if request.path != "/workspace" and not request.path.startswith("/workspace/"):
            return await handler(request)
        if request.method not in {"GET", "HEAD"}:
            err = check_same_origin(request, self.site_origin)
            if err is not None:
                return err
            if request.path != "/workspace/api/claim":
                try:
                    session = self._require_session(request)
                except web.HTTPUnauthorized as exc:
                    return portal_error("UNAUTHORIZED", exc.reason, status=401)
                csrf_err = check_csrf(
                    request,
                    header_name=WORKSPACE_CSRF_HEADER,
                    expected_csrf=session.csrf,
                )
                if csrf_err is not None:
                    return csrf_err
                rate_err = check_session_rate(
                    session.requests, self.sessions.clock(), limit=45
                )
                if rate_err is not None:
                    return rate_err
        elif request.path.startswith("/workspace/api/"):
            try:
                session = self._require_session(request)
            except web.HTTPUnauthorized as exc:
                return portal_error("UNAUTHORIZED", exc.reason, status=401)
            rate_err = check_session_rate(
                session.requests, self.sessions.clock(), limit=60
            )
            if rate_err is not None:
                return rate_err
        try:
            response = await handler(request)
        except web.HTTPException as exc:
            if exc.status in {302, 303}:
                return apply_portal_headers(exc)
            return portal_error("HTTP_ERROR", exc.reason or "请求失败", status=exc.status)
        except Exception:
            return portal_error("INTERNAL_ERROR", "工作台服务暂不可用", status=500)
        return apply_portal_headers(response)

    async def index(self, request: web.Request) -> web.Response:
        cookie = str(request.cookies.get(WORKSPACE_COOKIE, "") or "")
        if not self.sessions.get_workspace(cookie, touch=False):
            markup = (
                '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<link rel="stylesheet" href="/workspace/static/workspace.css">'
                "<title>个人指挥官工作台</title></head>"
                '<body><main class="claim-shell"><section class="card">'
                "<h1>个人指挥官工作台会话已过期</h1>"
                "<p>工作台包含个人绑定与账号分析功能，不提供匿名访问。</p>"
                "<p>请回到 QQ 私聊发送 <code>/妮姬 工作台</code> 获取新的一次性进入链接，或前往 "
                '<a href="/hall">公共功能大厅</a>。</p>'
                "</section></main></body></html>"
            )
            return web.Response(text=markup, content_type="text/html", status=401)
        return web.Response(
            text=(self.template_root / "index.html").read_text(encoding="utf-8"),
            content_type="text/html",
        )

    async def static(self, request: web.Request) -> web.Response:
        name = request.match_info["name"]
        if name not in {"workspace.css", "workspace.js", "claim.js"}:
            raise web.HTTPNotFound()
        content_type = "text/javascript" if name.endswith(".js") else "text/css"
        return web.Response(
            text=(self.template_root / name).read_text(encoding="utf-8"),
            content_type=content_type,
        )

    async def open(self, request: web.Request) -> web.Response:
        token = request.match_info["token"]
        if not _TOKEN_RE.fullmatch(token):
            raise web.HTTPNotFound()
        # GET 不消费令牌、不检查持有人、不返回任何账号信息
        markup = (
            '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<link rel="stylesheet" href="/workspace/static/workspace.css">'
            '<script src="/workspace/static/claim.js" defer></script>'
            "<title>进入个人指挥官工作台</title></head>"
            '<body><main class="claim-shell"><section class="card">'
            "<h1>个人指挥官工作台</h1>"
            "<p>点击后进入一次性个人会话（60 分钟有效）。首次打开只加载状态，不会主动拉取上游游戏数据。</p>"
            '<form id="claim" method="post" action="/workspace/api/claim">'
            f'<input type="hidden" name="token" value="{html.escape(token, quote=True)}">'
            '<button class="btn primary" type="submit">进入个人工作台</button>'
            "</form>"
            '<p id="claim-status" class="muted" role="status"></p>'
            "</section></main></body></html>"
        )
        return web.Response(text=markup, content_type="text/html")

    async def claim(self, request: web.Request) -> web.Response:
        if request.content_type != "application/x-www-form-urlencoded":
            return portal_error("INVALID_CONTENT_TYPE", "请从引导页进入", status=400)
        data = await request.post()
        token = str(data.get("token", ""))
        if set(data) != {"token"} or not _TOKEN_RE.fullmatch(token):
            return portal_error("TOKEN_INVALID", "无效的工作台链接", status=400)
        try:
            cookie = self.sessions.claim_workspace(token)
        except ValueError as exc:
            return portal_error("TOKEN_UNUSABLE", str(exc), status=410)
        response = (
            web.json_response({"ok": True, "redirect": "/workspace"})
            if request.headers.get("Accept") == "application/json"
            else web.Response(status=303, headers={"Location": "/workspace"})
        )
        response.set_cookie(
            WORKSPACE_COOKIE,
            cookie,
            path="/workspace",
            secure=True,
            httponly=True,
            samesite="Lax",
            max_age=3600,
        )
        return response

    async def revoke(self, request: web.Request) -> web.Response:
        cookie = str(request.cookies.get(WORKSPACE_COOKIE, "") or "")
        self.sessions.revoke_workspace(cookie)
        response = web.json_response({"ok": True})
        response.del_cookie(WORKSPACE_COOKIE, path="/workspace")
        return response

    def _masked_binding_summary(self, actor_id: str) -> dict[str, Any]:
        account = self.store.get_account(actor_id, with_cookie=False)
        if not account:
            return {
                "bound": False,
                "nickname": "",
                "area_id": "",
                "masked_uid": "",
                "cookie_valid": False,
                "push_enabled": False,
            }
        raw_uid = str(account.get("game_uid") or "")
        masked_uid = f"***{raw_uid[-4:]}" if len(raw_uid) >= 4 else ("***" if raw_uid else "")
        return {
            "bound": True,
            "nickname": str(account.get("nickname") or account.get("role_name") or "指挥官"),
            "area_id": str(account.get("area_id") or ""),
            "masked_uid": masked_uid,
            "cookie_valid": bool(account.get("cookie_valid", True)),
            "push_enabled": bool(account.get("push_enabled", True)),
        }

    async def bootstrap(self, request: web.Request) -> web.Response:
        """懒加载初始化：绝不发起 BlaBlaLink 或外部计算调用。"""
        session = self._require_session(request)
        return web.json_response(
            {
                "ok": True,
                "surface": "workspace",
                "csrf": session.csrf,
                "actor_label": mask_actor_label(session.actor_id),
                "share_target": {
                    "available": bool(session.conversation_id),
                    "label": session.group_label or session.conversation_id or "未附带群聊会话",
                },
                "binding": self._masked_binding_summary(session.actor_id),
                "arena_available": bool(self.arena_application is not None),
                "arena_web_available": bool(self.arena_web is not None and self.arena_web.active()),
                "catalog": workspace_catalog_payload(self._flags()),
            }
        )

    async def bind_start(self, request: web.Request) -> web.Response:
        session = self._require_session(request)
        token = secrets.token_urlsafe(32)
        self.store.create_bind_session(
            token, session.actor_id, 600, status=BIND_SESSION_PENDING
        )
        return web.json_response(
            {
                "ok": True,
                "token": token,
                "bind_url": f"{self.site_origin}/bind/{token}",
                "download_url": f"{self.site_origin}/download",
                "expires_in": 600,
            }
        )

    async def bind_status(self, request: web.Request) -> web.Response:
        session = self._require_session(request)
        token = str(request.query.get("token", ""))
        bind_session = (
            self.store.get_bind_session(token) if _TOKEN_RE.fullmatch(token) else None
        )
        if not bind_session or str(bind_session.get("qq_id", "")) != session.actor_id:
            return portal_error("BIND_SESSION_MISSING", "未找到该绑定会话", status=404)
        return web.json_response(
            {
                "ok": True,
                "status": bind_session.get("status", "pending"),
                "error": bind_session.get("error", ""),
                "binding": self._masked_binding_summary(session.actor_id),
            }
        )

    async def load_profile(self, request: web.Request) -> web.Response:
        session = self._require_session(request)
        account = self.store.get_account(session.actor_id, with_cookie=True)
        if not account:
            return portal_error("NOT_BOUND", "尚未绑定账号，请先完成自助绑定。", status=400)
        if self.profile_application is None:
            return portal_error("PROFILE_UNAVAILABLE", "档案服务尚未就绪", status=503)
        dashboard = await self.profile_application.build_dashboard(account)
        diff_text = ""
        if self.toolbox is not None:
            try:
                growth_res = self.toolbox.record_growth(
                    type("Ctx", (), {"actor_id": session.actor_id})(),
                    dashboard,
                    account=account,
                )
                diff_text = str(getattr(growth_res, "summary", "") or "")
            except Exception:
                diff_text = ""
        return web.json_response(
            {
                "ok": True,
                "profile": {
                    "commander_name": getattr(dashboard, "commander_name", ""),
                    "commander_level": getattr(dashboard, "commander_level", None),
                    "team_combat": getattr(dashboard, "team_combat", None),
                    "synchro_level": getattr(dashboard, "synchro_level", None),
                    "outpost_battle_level": getattr(
                        dashboard, "outpost_battle_level", None
                    ),
                    "normal_campaign": getattr(dashboard, "normal_campaign", None),
                    "hard_campaign": getattr(dashboard, "hard_campaign", None),
                    "progress_tribe_tower": getattr(
                        dashboard, "progress_tribe_tower", None
                    ),
                    "character_count": getattr(dashboard, "character_count", None),
                    "fetched_at": getattr(dashboard, "fetched_at", ""),
                    "growth_diff": diff_text,
                },
            }
        )

    def _directory_map(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        sources = []
        if self.toolbox is not None and getattr(self.toolbox, "grid_rows", ()):
            sources.extend(self.toolbox.grid_rows)
        if self._directory_provider is not None:
            sources.extend(self._directory_provider() or ())
        for row in sources:
            if not isinstance(row, Mapping):
                continue
            code = str(row.get("name_code") or row.get("character_key") or "").strip()
            if code and code not in result:
                result[code] = dict(row)
        return result

    async def load_roster(self, request: web.Request) -> web.Response:
        session = self._require_session(request)
        account = self.store.get_account(session.actor_id, with_cookie=True)
        if not account:
            return portal_error("NOT_BOUND", "尚未绑定账号，请先完成自助绑定。", status=400)
        if self.toolbox is None or self.toolbox.roster_loader is None:
            return portal_error("ROSTER_UNAVAILABLE", "角色练度读取器未就绪", status=503)
        rows = await self.toolbox.roster_loader(account)
        directory = self._directory_map()
        items = []
        for row in rows or ():
            if not isinstance(row, Mapping):
                continue
            code = str(row.get("name_code") or "").strip()
            meta = directory.get(code, {})
            name = str(
                row.get("name_zh_cn")
                or meta.get("name_zh_cn")
                or meta.get("name_zh_tw")
                or meta.get("name_cn")
                or code
            )
            items.append(
                {
                    "name_code": code,
                    "name": name,
                    "burst": str(row.get("burst") or meta.get("burst") or ""),
                    "element": str(row.get("element") or meta.get("element") or ""),
                    "combat": int(row.get("combat") or row.get("power") or 0),
                    "grade": int(row.get("grade") or 0),
                    "skill1": row.get("skill1_level"),
                    "skill2": row.get("skill2_level"),
                    "burst_lvl": row.get("ulti_skill_level"),
                }
            )
        items.sort(key=lambda r: (-r["combat"], -r["grade"], r["name"]))
        return web.json_response({"ok": True, "count": len(items), "characters": items})

    async def load_character(self, request: web.Request) -> web.Response:
        session = self._require_session(request)
        body, err = await read_json_object(request)
        if err is not None:
            return err
        assert body is not None
        query = str(body.get("query", "")).strip()
        if not query:
            return portal_error("MISSING_QUERY", "请指定角色名", status=400)
        if self.character_application is None:
            return portal_error("CHARACTER_UNAVAILABLE", "角色详情服务未就绪", status=503)
        directory = (
            tuple(self._directory_provider())
            if self._directory_provider is not None
            else ()
        )
        card = await self.character_application.character_card(
            session.actor_id, query, directory
        )
        lines = []
        for slot_name, piece in (getattr(card, "equipment", {}) or {}).items():
            for opt in getattr(piece, "options", ()) or ():
                lines.append(
                    f"{slot_name}: {getattr(opt, 'display_name', '')} Lv.{getattr(opt, 'tier', '?')}"
                )
        s1 = getattr(card, "skill1_level", "?")
        s2 = getattr(card, "skill2_level", "?")
        sb = getattr(card, "burst_skill_level", "?")
        return web.json_response(
            {
                "ok": True,
                "character": {
                    "name": getattr(card, "name_cn", "") or getattr(card, "name_en", ""),
                    "level": getattr(card, "level", None),
                    "combat": getattr(card, "combat", None),
                    "skills": f"技能 {s1}/{s2}/{sb}",
                    "overload_lines": lines,
                },
            }
        )

    async def open_arena(self, request: web.Request) -> web.Response:
        session = self._require_session(request)
        body, err = await read_json_object(request)
        if err is not None:
            return err
        assert body is not None
        mode = "three" if str(body.get("mode", "single")) == "three" else "single"
        if self.arena_web is None or not self.arena_web.active():
            return portal_error(
                "ARENA_WEB_DISABLED",
                "竞技场网页当前未开启，可直接在下方使用快速分析。",
                status=400,
            )
        return web.json_response(
            {"ok": True, "url": self.arena_web.link(session.actor_id, mode), "mode": mode}
        )

    async def analyze_arena(self, request: web.Request) -> web.Response:
        session = self._require_session(request)
        body, err = await read_json_object(request)
        if err is not None:
            return err
        assert body is not None
        if self.arena_application is None:
            return portal_error("ARENA_DISABLED", "竞技场分析未开启", status=400)
        lineup = str(body.get("lineup", "")).strip()
        owned = bool(body.get("owned", True))
        if not lineup:
            return portal_error("MISSING_LINEUP", "请输入 5 名角色（斜线或逗号分隔）", status=400)
        try:
            res = await self.arena_application.analyze(
                lineup, actor_id=session.actor_id, owned=owned
            )
            text = (
                three_team_text(res)
                if hasattr(res, "teams") and not hasattr(res, "recommendations")
                else analysis_text(res)
            )
        except ValueError as exc:
            return portal_error("ARENA_INVALID", str(exc), status=400)
        return web.json_response({"ok": True, "text": text})

    async def solo_raid_context(self, request: web.Request) -> web.Response:
        session = self._require_session(request)
        catalog = getattr(self.toolbox, "solo_catalog", None) if self.toolbox else None
        seasons = []
        if catalog is not None and catalog.available:
            for s in catalog.seasons:
                seasons.append(
                    {
                        "id": s.season_id,
                        "name": s.name,
                        "bosses": [
                            {"name": b.name, "weakness": b.weakness, "element": b.element}
                            for b in s.bosses
                        ],
                    }
                )
        saved = None
        if self.toolbox is not None:
            plan = self.toolbox.solo_plans.load(session.actor_id)
            if plan is not None:
                saved = {
                    "season_name": plan.season_name,
                    "saved_at": plan.saved_at,
                    "damage_total": plan.damage_total,
                    "damage_model_label": plan.damage_model_label,
                    "teams": [
                        {
                            "index": t.index,
                            "damage": t.damage,
                            "members": [m.name for m in t.members],
                        }
                        for t in plan.teams
                    ],
                }
        engine = getattr(self.toolbox, "solo_engine", None) if self.toolbox else None
        return web.json_response(
            {
                "ok": True,
                "seasons": seasons,
                "saved_plan": saved,
                "engine_configured": engine is not None,
            }
        )

    async def solo_raid_build(self, request: web.Request) -> web.Response:
        session = self._require_session(request)
        body, err = await read_json_object(request)
        if err is not None:
            return err
        assert body is not None
        if self.toolbox is None:
            return portal_error("TOOLBOX_UNAVAILABLE", "单人突袭服务未就绪", status=503)

        source = str(body.get("source", "account")).strip()
        manual_pool = str(body.get("members", "")).strip()
        save_plan = bool(body.get("save", False))
        season = (
            self.toolbox.solo_catalog.latest()
            if self.toolbox.solo_catalog.available
            else None
        )
        boss = season.bosses[0] if season and season.bosses else None

        if source == "manual" or manual_pool:
            if not manual_pool:
                return portal_error("MISSING_MEMBERS", "请输入手工角色池", status=400)
            members = parse_members(manual_pool)
            source_note = "角色来源：工作台手工角色池。"
        else:
            account = self.store.get_account(session.actor_id, with_cookie=True)
            if not account:
                return portal_error(
                    "NOT_BOUND", "尚未绑定账号，请先完成绑定或改用手工角色池。", status=400
                )
            if self.toolbox.roster_loader is None:
                return portal_error("ROSTER_UNAVAILABLE", "角色库读取器未就绪", status=503)
            rows = await self.toolbox.roster_loader(account)
            directory = self._directory_map()
            enriched = []
            for row in rows or ():
                if not isinstance(row, Mapping):
                    continue
                code = str(row.get("name_code") or row.get("character_key") or "").strip()
                meta = directory.get(code, {}) if code else {}
                merged = dict(row)
                for f in ("burst", "element", "name_zh_cn", "name_zh_tw", "name_cn", "resource_id"):
                    if not merged.get(f) and meta.get(f) not in (None, ""):
                        merged[f] = meta[f]
                enriched.append(merged)
            members = members_from_roster(enriched)
            source_note = "角色来源：已绑定账号角色库（已按目录补全爆裂/元素）。"

        plan = build_five_teams(
            members,
            season=season,
            damage_model=self.toolbox.solo_damage_model,
        )
        version_trust = "unavailable"
        version_ok = False
        engine = getattr(self.toolbox, "solo_engine", None)
        if engine is not None:
            est = await engine.estimate(
                plan.teams,
                boss_element=str(
                    getattr(boss, "weakness", "") or getattr(boss, "element", "") or ""
                ),
            )
            version_trust = est.version_trust
            version_ok = est.version_ok
            if est.available:
                by_idx = {t.index: t.damage for t in est.teams}
                teams = tuple(
                    replace(team, damage=by_idx.get(team.index)) for team in plan.teams
                )
                plan = replace(
                    plan,
                    teams=teams,
                    damage_total=est.total,
                    damage_model_label=est.label,
                    estimate_note=est.note,
                )
            elif plan.damage_total is None and est.reason:
                plan = replace(plan, estimate_note=est.reason)
        if save_plan:
            self.toolbox.solo_plans.save(session.actor_id, plan)

        return web.json_response(
            {
                "ok": True,
                "source_note": source_note,
                "plan": plan.to_dict(),
                "text": source_note + "\n" + render_plan(plan, boss=boss),
                "version_trust": version_trust,
                "version_ok": version_ok,
                "saved": save_plan,
            }
        )

    async def tool_wishlist(self, request: web.Request) -> web.Response:
        session = self._require_session(request)
        body, err = await read_json_object(request)
        if err is not None:
            return err
        assert body is not None
        if self.toolbox is None:
            return portal_error("TOOLBOX_UNAVAILABLE", "愿望单服务未就绪", status=503)
        try:
            strategy = normalize_strategy(str(body.get("strategy", "balanced")))
            raw_owned = str(body.get("owned", "")).strip()
            if raw_owned:
                owned = parse_owned(
                    raw_owned,
                    rows=self.toolbox.wishlist_rows,
                    resolver=self.toolbox.grid_resolver,
                )
                source_note = "角色来源：手工输入。"
            else:
                account = self.store.get_account(session.actor_id, with_cookie=True)
                if not account or self.toolbox.roster_loader is None:
                    return portal_error("NOT_BOUND", "未绑定账号时请手工填写已持有列表。", status=400)
                rows = await self.toolbox.roster_loader(account)
                owned = tuple(
                    OwnedCharacter(
                        name_code=str(r.get("name_code") or ""),
                        name="",
                        burst=str(r.get("burst") or ""),
                        limit_break=int(r.get("grade") or 0),
                    )
                    for r in (rows or ())
                    if isinstance(r, Mapping) and r.get("name_code")
                )
                source_note = "角色来源：已绑定账号角色库。"
            res = recommend(
                self.toolbox.wishlist_rows,
                owned,
                strategy,
                exclusions=self.toolbox.wishlist_exclusions,
                eligibility=self.toolbox.wishlist_eligibility,
            )
        except WishlistError as exc:
            return portal_error("INVALID_WISHLIST", str(exc), status=400)
        return web.json_response({"ok": True, "text": source_note + "\n" + render_wishlist(res)})

    async def tool_sync(self, request: web.Request) -> web.Response:
        session = self._require_session(request)
        body, err = await read_json_object(request)
        if err is not None:
            return err
        assert body is not None
        table = getattr(self.toolbox, "sync_table", None) if self.toolbox else None
        current = body.get("current", "")
        inventory = body.get("inventory") or {}
        if body.get("use_account"):
            account = self.store.get_account(session.actor_id, with_cookie=True)
            if not account or self.toolbox is None or self.toolbox.profile_loader is None:
                return portal_error("NOT_BOUND", "尚未绑定账号", status=400)
            profile = await self.toolbox.profile_loader(account)
            outpost = profile.get("outpost") if isinstance(profile, Mapping) else {}
            current = (outpost or {}).get("synchro_level") or current
        try:
            plan = calculate_sync_plan(
                current=current,
                target=body.get("target", ""),
                inventory=inventory,
                production=body.get("production") or {},
                table=table,
                today=self._clock().date(),
            )
        except SyncLevelInputError as exc:
            return portal_error("INVALID_SYNC_INPUT", str(exc), status=400)
        return web.json_response({"ok": True, "text": render_sync_plan(plan)})

    async def tool_overload(self, request: web.Request) -> web.Response:
        body, err = await read_json_object(request)
        if err is not None:
            return err
        assert body is not None
        try:
            targets = parse_targets(str(body.get("targets", "")))
            options = parse_options(body.get("options") or [])
            res = advise(options, targets)
        except (OverloadAdviceError, ValueError, TypeError) as exc:
            return portal_error("INVALID_OVERLOAD_INPUT", str(exc), status=400)
        return web.json_response({"ok": True, "text": render_advice(res)})

    async def get_settings(self, request: web.Request) -> web.Response:
        session = self._require_session(request)
        binding = self._masked_binding_summary(session.actor_id)
        feeds_status = ""
        if self.toolbox is not None and getattr(self.toolbox, "feeds", None) is not None:
            target = f"dm:{session.actor_id}"
            feeds_status = self.toolbox.feeds.command(target, "状态", "")
        return web.json_response(
            {"ok": True, "binding": binding, "feeds_status": feeds_status}
        )

    async def update_settings(self, request: web.Request) -> web.Response:
        session = self._require_session(request)
        body, err = await read_json_object(request)
        if err is not None:
            return err
        assert body is not None
        action = str(body.get("action", "")).strip()
        if action == "toggle_push":
            enabled = bool(body.get("enabled", True))
            updated = self.store.set_push(session.actor_id, enabled)
            return web.json_response({"ok": True, "push_enabled": enabled, "updated": bool(updated)})
        if action == "clear_growth" and self.toolbox is not None:
            self.toolbox.growth.clear(session.actor_id)
            self.toolbox.roster_growth.clear(session.actor_id)
            return web.json_response({"ok": True, "message": "已清除本人全部养成历史快照。"})
        if action == "feeds" and self.toolbox is not None:
            op = str(body.get("op", "状态")).strip()
            kinds = str(body.get("kinds", "")).strip()
            msg = self.toolbox.feeds.command(f"dm:{session.actor_id}", op, kinds)
            return web.json_response({"ok": True, "message": msg})
        return portal_error("UNKNOWN_SETTING_ACTION", "不支持的设置操作", status=400)

    # ------------------------------------------------------------------ QQ-Web-QQ 受控分享闭环

    def _build_share_text_and_media(
        self,
        session: WorkspaceSession,
        kind: str,
        raw_text: str,
        payload: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        account = self.store.get_account(session.actor_id, with_cookie=False) or {}
        ident = canonical_account_identity(account)
        raw_uid = str(ident.game_uid if ident else account.get("game_uid") or "")
        raw_openid = str(ident.game_openid if ident else account.get("game_openid") or "")
        sanitized, notes = redact_share_text(
            raw_text,
            raw_uid=raw_uid,
            raw_openid=raw_openid,
            raw_actor_id=session.actor_id,
        )
        return sanitized, {
            "kind": kind,
            "redaction_notes": list(notes),
            "meta": dict(payload),
        }

    async def share_preview(self, request: web.Request) -> web.Response:
        session = self._require_session(request)
        if not session.conversation_id:
            return portal_error(
                "NO_SHARE_TARGET",
                "当前工作台会话未关联 QQ 发送目标，请从 QQ 对话发送 /妮姬 工作台 进入。",
                status=400,
            )
        body, err = await read_json_object(request)
        if err is not None:
            return err
        assert body is not None
        kind = str(body.get("kind", "")).strip()
        if kind not in {"profile", "solo_raid", "arena", "favorite_grid", "custom"}:
            return portal_error("INVALID_SHARE_KIND", "不支持的分享类型", status=400)
        raw_text = str(body.get("text", "")).strip()
        payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}

        if kind == "favorite_grid" and self.toolbox is not None and not raw_text:
            names = str(body.get("grid_names", "")).strip()
            cells = resolve_nine(names, self.toolbox.grid_rows, self.toolbox.grid_resolver)
            raw_text = "本命九宫格：\n" + " / ".join(f"P{c.index} {c.name}" for c in cells)
            payload = {"grid_names": names}
        if not raw_text:
            return portal_error("EMPTY_SHARE_TEXT", "分享正文不能为空", status=400)
        raw_text = raw_text[:1800]

        preview_text, stored_payload = self._build_share_text_and_media(
            session, kind, raw_text, payload
        )
        target_label = session.group_label or session.conversation_id
        confirm_token, item = self.sessions.create_share_confirmation(
            session,
            kind=kind,
            target_id=session.conversation_id,
            target_label=target_label,
            preview_text=preview_text,
            payload=stored_payload,
        )
        return web.json_response(
            {
                "ok": True,
                "confirm_token": confirm_token,
                "target_label": item.target_label,
                "preview_text": item.preview_text,
                "redaction_notes": stored_payload["redaction_notes"],
                "warning": "请核对接收会话与脱敏正文，确认后才会发送至 QQ。",
            }
        )

    async def share_confirm(self, request: web.Request) -> web.Response:
        session = self._require_session(request)
        body, err = await read_json_object(request)
        if err is not None:
            return err
        assert body is not None
        confirm_token = str(body.get("confirm_token", "")).strip()
        idem = str(body.get("idempotency_key", "")).strip()
        if not confirm_token or not _IDEMPOTENCY_RE.fullmatch(idem):
            return portal_error("INVALID_CONFIRM_PARAMS", "缺少确认令牌或幂等键", status=400)

        prior, record = self.sessions.check_or_begin_delivery(
            session,
            idempotency_key=idem,
            kind="workspace_share",
            target_label=session.group_label or session.conversation_id,
        )
        if prior is not None:
            if prior.status == "unknown":
                return portal_error(
                    "DELIVERY_UNKNOWN",
                    "前次分享状态未知，严格禁止自动重发，请先在 QQ 会话核实。",
                    status=409,
                    delivery_status="unknown",
                )
            if prior.status == "pending":
                return portal_error("DELIVERY_PENDING", "消息正在发送中", status=409)
            return web.json_response(
                {
                    "ok": True,
                    "delivery_status": prior.status,
                    "deduplicated": True,
                    "target_label": prior.target_label,
                }
            )

        confirmed = self.sessions.consume_share_confirmation(session, confirm_token)
        if confirmed is None:
            self.sessions.finish_delivery(
                record, status="failed", message="确认令牌无效或已过期"
            )
            return portal_error("CONFIRM_EXPIRED", "分享确认已过期或已使用，请重新生成预览。", status=410)

        if self.bridge.send_to_qq is None:
            self.sessions.finish_delivery(
                record, status="failed", message="宿主 QQ 发送通道尚未连接"
            )
            return portal_error(
                "SENDER_UNAVAILABLE", "宿主 QQ 发送通道尚未连接", status=503
            )

        images: list[str] = []
        if (
            confirmed.kind == "favorite_grid"
            and self.bridge.render_favorite_grid is not None
            and self.toolbox is not None
        ):
            grid_names = str(confirmed.payload.get("meta", {}).get("grid_names", ""))
            if grid_names:
                try:
                    cells = resolve_nine(
                        grid_names, self.toolbox.grid_rows, self.toolbox.grid_resolver
                    )
                    rendered = await self.bridge.render_favorite_grid(cells)
                    if isinstance(rendered, str) and rendered.strip():
                        images = [rendered]
                except Exception:
                    images = []

        try:
            outcome = await asyncio.wait_for(
                self.bridge.send_to_qq(confirmed.target_id, confirmed.preview_text, images),
                timeout=15.0,
            )
        except (asyncio.TimeoutError, TimeoutError):
            self.sessions.finish_delivery(
                record, status="unknown", message="发送超时，状态未知（未自动重试）"
            )
            return portal_error(
                "DELIVERY_UNKNOWN",
                "QQ 发送超时，投递结果未知，系统已停止自动重发。",
                status=504,
                delivery_status="unknown",
            )
        except Exception as exc:
            status = "unknown" if "unknown" in str(exc).casefold() else "failed"
            msg = (
                "投递结果未知，已阻止自动重发"
                if status == "unknown"
                else "发送至 QQ 失败"
            )
            self.sessions.finish_delivery(record, status=status, message=msg)
            return portal_error(
                "DELIVERY_UNKNOWN" if status == "unknown" else "DELIVERY_FAILED",
                msg,
                status=502,
                delivery_status=status,
            )

        normalized = str(outcome or "sent").strip().casefold()
        if normalized == "unknown":
            self.sessions.finish_delivery(
                record, status="unknown", message="宿主返回未知状态（未自动重试）"
            )
            return portal_error(
                "DELIVERY_UNKNOWN",
                "QQ 投递结果未知，已停止自动重发。",
                status=502,
                delivery_status="unknown",
            )
        self.sessions.finish_delivery(
            record, status="sent", message=f"已发送至 {confirmed.target_label}"
        )
        return web.json_response(
            {
                "ok": True,
                "delivery_status": "sent",
                "target_label": confirmed.target_label,
            }
        )

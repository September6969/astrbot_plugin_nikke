# SPDX-License-Identifier: GPL-3.0-or-later
"""公共功能大厅（/hall）Web 服务：导航、口令复制、公开工具与日程/塔罗群聊反馈。

安全边界：
- 公共浏览页面不读任何个人账号、Cookie、角色库或成长历史；
- 若用户从群内通过 `/妮姬 大厅` 获得 `/hall/open/{token}`，可选择性领取群聊反馈上下文，
  签发仅限 `/hall` 路径的 HttpOnly Cookie 与 CSRF 密钥，用于将日程或塔罗抽牌结果推回该群；
- 群聊投递强制幂等键；若发生超时或状态未知（status="unknown"），拒绝自动重试。
"""

from __future__ import annotations

import asyncio
import html
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

from ...features.calendar.board import build_board, normalize_group, render_board
from ...features.catalog import public_catalog_payload
from ...features.counsel.bank import render_counsel_search
from ...features.favorite_grid.grid import render_ranking
from ...features.overload_advice.advisor import (
    OverloadAdviceError,
    advise,
    parse_options,
    parse_targets,
    render_advice,
    render_character_recommendation,
    simulate,
)
from ...features.sync.calculator import (
    SyncLevelInputError,
    plan_sync_from_inputs,
    render_sync_plan,
)
from ...features.tarot.models import DrawnTarotCard, TarotReading
from ...features.web_portal import HallContextSession, PortalSessionStore
from ...features.wishlist.advisor import (
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

HALL_COOKIE = "__Secure-nikke_hall_ctx"
HALL_CSRF_HEADER = "X-Hall-CSRF"
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9_-]{8,96}$")
_CARD_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_CST = timezone(timedelta(hours=8))
_DEFAULT_TEMPLATE_ROOT = (
    Path(__file__).resolve().parents[2] / "templates" / "hall_web"
)


class HallWebService:
    """公共功能大厅同源路由与公开能力接口。"""

    def __init__(
        self,
        *,
        site_origin: str,
        sessions: PortalSessionStore,
        bridge: PortalHostBridge,
        feature_flags: Callable[[], Mapping[str, bool]] | Mapping[str, bool] = (),
        calendar: Any = None,
        announcements: Any = None,
        guide: Any = None,
        tower: Any = None,
        tarot: Any = None,
        toolbox: Any = None,
        grid_resolver: Any = None,
        template_root: Path | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.site_origin = str(site_origin).rstrip("/")
        self.sessions = sessions
        self.bridge = bridge
        self._feature_flags = feature_flags
        self.calendar = calendar
        self.announcements = announcements
        self.guide = guide
        self.tower = tower
        self.tarot = tarot
        self.toolbox = toolbox
        self.grid_resolver = grid_resolver
        self.template_root = (
            Path(template_root) if template_root else _DEFAULT_TEMPLATE_ROOT
        )
        self._clock = clock or (lambda: datetime.now(_CST))

    def _flags(self) -> Mapping[str, bool]:
        raw = self._feature_flags() if callable(self._feature_flags) else self._feature_flags
        return dict(raw) if isinstance(raw, Mapping) else {}

    def create_group_link(
        self, actor_id: str, conversation_id: str, group_label: str = ""
    ) -> str:
        token = self.sessions.create_hall_link(actor_id, conversation_id, group_label)
        return f"{self.site_origin}/hall/open/{token}"

    def public_url(self) -> str:
        return f"{self.site_origin}/hall"

    def mount(self, app: web.Application) -> None:
        app.middlewares.insert(0, self.security)
        app.add_routes(
            [
                web.get("/hall", self.index),
                web.get("/hall/open/{token}", self.open),
                web.post("/hall/api/claim", self.claim),
                web.post("/hall/api/revoke", self.revoke),
                web.get("/hall/static/{name}", self.static),
                web.get("/hall/api/bootstrap", self.bootstrap),
                web.get("/hall/api/catalog", self.catalog),
                web.get("/hall/api/calendar", self.api_calendar),
                web.get("/hall/api/gacha", self.api_gacha),
                web.get("/hall/api/announcements", self.api_announcements),
                web.get("/hall/api/guides", self.api_guides),
                web.get("/hall/api/character", self.api_character),
                web.get("/hall/api/tower", self.api_tower),
                web.get("/hall/api/ranking", self.api_ranking),
                web.post("/hall/api/tarot", self.api_tarot),
                web.get("/hall/api/tarot/image/{card_key}", self.api_tarot_image),
                web.post("/hall/api/tools/counsel", self.api_counsel),
                web.post("/hall/api/tools/sync", self.api_sync),
                web.post("/hall/api/tools/wishlist", self.api_wishlist),
                web.post("/hall/api/tools/overload-sim", self.api_overload_sim),
                web.post("/hall/api/tools/overload-recommend", self.api_overload_recommend),
                web.post("/hall/api/feedback/calendar", self.feedback_calendar),
                web.post("/hall/api/feedback/tarot", self.feedback_tarot),
            ]
        )

    def _optional_session(self, request: web.Request) -> HallContextSession | None:
        cookie = str(request.cookies.get(HALL_COOKIE, "") or "")
        return self.sessions.get_hall(cookie, touch=True) if cookie else None

    @web.middleware
    async def security(self, request: web.Request, handler):
        if request.path != "/hall" and not request.path.startswith("/hall/"):
            return await handler(request)
        if request.method not in {"GET", "HEAD"}:
            err = check_same_origin(request, self.site_origin)
            if err is not None:
                return err
            if request.path in {
                "/hall/api/feedback/calendar",
                "/hall/api/feedback/tarot",
                "/hall/api/revoke",
            }:
                session = self._optional_session(request)
                if session is None:
                    return portal_error(
                        "HALL_CONTEXT_REQUIRED",
                        "尚未连接群聊反馈上下文，请回 QQ 群发送 /妮姬 大厅 获取群引导链接。",
                        status=401,
                    )
                csrf_err = check_csrf(
                    request,
                    header_name=HALL_CSRF_HEADER,
                    expected_csrf=session.csrf,
                )
                if csrf_err is not None:
                    return csrf_err
                rate_err = check_session_rate(
                    session.requests, self.sessions.clock(), limit=30
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
            return portal_error("INTERNAL_ERROR", "公共大厅请求暂不可用", status=500)
        return apply_portal_headers(response)

    async def index(self, _request: web.Request) -> web.Response:
        text = (self.template_root / "index.html").read_text(encoding="utf-8")
        return web.Response(text=text, content_type="text/html")

    async def static(self, request: web.Request) -> web.Response:
        name = request.match_info["name"]
        if name not in {"hall.css", "hall.js", "claim.js"}:
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
        markup = (
            '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<link rel="stylesheet" href="/hall/static/hall.css">'
            '<script src="/hall/static/claim.js" defer></script>'
            "<title>进入 NIKKE 公共功能大厅</title></head>"
            '<body><main class="claim-shell"><section class="card">'
            "<h1>NIKKE 公共功能大厅</h1>"
            "<p>当前入口仅绑定用于回推「日程」或「随机塔罗」的目标群聊上下文，不会读取任何个人账号或练度数据。</p>"
            '<form id="claim" method="post" action="/hall/api/claim">'
            f'<input type="hidden" name="token" value="{html.escape(token, quote=True)}">'
            '<button class="btn primary" type="submit">确认进入公共大厅</button>'
            "</form>"
            '<p id="claim-status" class="muted" role="status"></p>'
            '<p><a href="/hall">直接以匿名模式打开公共大厅</a></p>'
            "</section></main></body></html>"
        )
        return web.Response(text=markup, content_type="text/html")

    async def claim(self, request: web.Request) -> web.Response:
        if request.content_type != "application/x-www-form-urlencoded":
            return portal_error("INVALID_CONTENT_TYPE", "请从大厅引导页进入", status=400)
        data = await request.post()
        token = str(data.get("token", ""))
        if set(data) != {"token"} or not _TOKEN_RE.fullmatch(token):
            return portal_error("TOKEN_INVALID", "无效的大厅群聊链接", status=400)
        try:
            cookie = self.sessions.claim_hall(token)
        except ValueError as exc:
            return portal_error("TOKEN_UNUSABLE", str(exc), status=410)
        response = (
            web.json_response({"ok": True, "redirect": "/hall"})
            if request.headers.get("Accept") == "application/json"
            else web.Response(status=303, headers={"Location": "/hall"})
        )
        response.set_cookie(
            HALL_COOKIE,
            cookie,
            path="/hall",
            secure=True,
            httponly=True,
            samesite="Lax",
            max_age=3600,
        )
        return response

    async def revoke(self, request: web.Request) -> web.Response:
        cookie = str(request.cookies.get(HALL_COOKIE, "") or "")
        self.sessions.revoke_hall(cookie)
        response = web.json_response({"ok": True})
        response.del_cookie(HALL_COOKIE, path="/hall")
        return response

    async def bootstrap(self, request: web.Request) -> web.Response:
        session = self._optional_session(request)
        catalog = public_catalog_payload(self._flags())
        return web.json_response(
            {
                "ok": True,
                "surface": "hall",
                "catalog": catalog,
                "flags": dict(self._flags()),
                "group_context": {
                    "active": session is not None,
                    "label": session.group_label if session else "",
                    "csrf": session.csrf if session else "",
                },
                "workspace_hint": "需要查看个人档案、角色练度、自助绑定或单人突袭五队，请向机器人发送 /妮姬 工作台。",
            }
        )

    async def catalog(self, _request: web.Request) -> web.Response:
        return web.json_response({"ok": True, **public_catalog_payload(self._flags())})

    async def api_calendar(self, request: web.Request) -> web.Response:
        horizon = request.query.get("horizon", "14")
        if self.calendar is None:
            return web.json_response(
                {"ok": True, "available": False, "text": "日程服务尚未就绪。"}
            )
        try:
            snapshot = self.calendar.query_schedule(horizon)
        except ValueError as exc:
            return portal_error("INVALID_HORIZON", str(exc), status=400)
        items = []
        if snapshot.has_snapshot and self.bridge.build_calendar_payload is not None:
            payload = self.bridge.build_calendar_payload(snapshot)
            for page in payload.get("pages", ()) or ():
                for bucket in ("active_items", "next_items"):
                    for row in page.get(bucket, ()) or ():
                        items.append(
                            {
                                "title": row.get("full_title") or row.get("title") or "",
                                "time_range": row.get("time_range")
                                or row.get("start_time_display")
                                or "时间待确认",
                                "remaining": row.get("remaining") or "",
                                "bucket": "进行中" if bucket == "active_items" else "即将开启",
                            }
                        )
        elif snapshot.has_snapshot:
            for ev in snapshot.context.events:
                items.append(
                    {
                        "title": getattr(ev, "title", ""),
                        "time_range": getattr(ev, "category", ""),
                        "remaining": "",
                        "bucket": "",
                    }
                )
        return web.json_response(
            {
                "ok": True,
                "available": bool(snapshot.service_available and snapshot.has_snapshot),
                "horizon_days": snapshot.horizon_days,
                "activity_count": snapshot.activity_count,
                "data_quality": snapshot.data_quality,
                "last_updated_at": snapshot.last_updated_at,
                "sync_warning": snapshot.sync_warning,
                "items": items[:24],
                "fallback_text": snapshot.fallback_text,
            }
        )

    async def api_gacha(self, request: web.Request) -> web.Response:
        raw_group = request.query.get("group", "").strip()
        selected = normalize_group(raw_group) if raw_group else None
        if raw_group and selected is None:
            return portal_error(
                "INVALID_GROUP", "未知类型，支持：卡池 / 活动 / 皮肤 / 突袭", status=400
            )
        if self.calendar is None:
            return web.json_response({"ok": True, "available": False, "text": "日程服务尚未就绪。"})
        snapshot = self.calendar.query_schedule()
        if not snapshot.service_available or not snapshot.has_snapshot:
            return web.json_response(
                {"ok": True, "available": False, "text": "日程快照尚未就绪，请稍后重试。"}
            )
        board = build_board(
            snapshot.context.events,
            snapshot.context.now,
            groups=(selected,) if selected else None,
        )
        return web.json_response(
            {
                "ok": True,
                "available": True,
                "group": selected or "全部",
                "text": render_board(board),
            }
        )

    async def api_announcements(self, request: web.Request) -> web.Response:
        if self.announcements is None:
            return web.json_response({"ok": True, "text": "公告服务尚未就绪。"})
        locale = request.query.get("locale", "").strip() or None
        category = request.query.get("category", "").strip() or None
        query = request.query.get("q", "").strip() or None
        text = await self.announcements.view_announcements(
            locale=locale, category=category, query=query
        )
        return web.json_response({"ok": True, "text": text})

    async def api_guides(self, request: web.Request) -> web.Response:
        category_aliases = {
            "练度": "progression",
            "progression": "progression",
            "红球": "red_orbs",
            "red_orbs": "red_orbs",
            "珍藏品": "favorite",
            "favorite": "favorite",
            "充能": "arena_charge",
            "arena_charge": "arena_charge",
            "洗词条": "overload",
            "overload": "overload",
            "pvp": "pvp",
            "配队": "pvp",
        }
        categories = [
            {"id": "progression", "label": "练度一图流"},
            {"id": "red_orbs", "label": "同步器与红球"},
            {"id": "favorite", "label": "珍藏品养成"},
            {"id": "arena_charge", "label": "竞技场充能"},
            {"id": "overload", "label": "洗词条教学"},
            {"id": "pvp", "label": "PVP 配队"},
        ]
        raw_cat = request.query.get("category", "").strip().lower()
        raw_page = request.query.get("page", "1").strip() or "1"
        if not raw_page.isdigit() or not (1 <= int(raw_page) <= 100):
            return portal_error("INVALID_PAGE", "页码须为正整数", status=400)
        if not raw_cat or self.guide is None:
            return web.json_response(
                {"ok": True, "categories": categories, "entries": []}
            )
        folder = category_aliases.get(raw_cat, raw_cat)
        try:
            page_result = self.guide.page(folder, page_number=int(raw_page))
        except (ValueError, OSError):
            return portal_error("GUIDE_UNAVAILABLE", "未找到该攻略分类", status=404)
        entries = [
            {
                "caption": entry.caption(now=page_result.current_date),
                "links": list(entry.links),
                "file_count": len(entry.files),
            }
            for entry in page_result.entries
        ]
        return web.json_response(
            {
                "ok": True,
                "categories": categories,
                "category": folder,
                "page": page_result.page_number,
                "total_pages": page_result.total_pages,
                "entries": entries,
            }
        )

    async def api_character(self, request: web.Request) -> web.Response:
        q = request.query.get("q", "").strip()
        rows = getattr(self.toolbox, "grid_rows", ()) if self.toolbox is not None else ()
        if not q:
            return web.json_response({"ok": True, "matches": [], "total_rows": len(rows)})
        resolver = self.grid_resolver or (
            getattr(self.toolbox, "grid_resolver", None) if self.toolbox else None
        )
        matches = resolver.find(rows, q) if resolver is not None else []
        items = [
            {
                "name_code": str(row.get("name_code") or ""),
                "name": resolver.display_name(row)
                if resolver is not None
                else str(row.get("name_zh_cn") or row.get("name_cn") or ""),
                "rarity": str(row.get("rarity") or row.get("original_rare") or ""),
                "burst": str(row.get("burst") or row.get("use_burst_skill") or ""),
                "element": str(row.get("element") or ""),
                "weapon": str(row.get("weapon") or ""),
                "company": str(row.get("corporation") or row.get("company") or ""),
                "squad": str(row.get("squad") or ""),
            }
            for row in matches[:12]
        ]
        return web.json_response({"ok": True, "query": q, "matches": items})

    async def api_tower(self, request: web.Request) -> web.Response:
        tower_name = request.query.get("tower", "无限塔").strip() or "无限塔"
        floor = request.query.get("floor", "").strip()
        if self.tower is None:
            return web.json_response({"ok": True, "text": "塔层资料尚未就绪。"})
        if not floor:
            return web.json_response(
                {"ok": True, "text": "请输入楼层，例如：无限塔 100 或 朝圣者 50。"}
            )
        text = await self.tower.describe(tower_name, floor)
        return web.json_response({"ok": True, "text": text})

    async def api_ranking(self, _request: web.Request) -> web.Response:
        if self.toolbox is None or getattr(self.toolbox, "grid_ranking", None) is None:
            return web.json_response({"ok": True, "text": "本命人气榜尚未就绪。"})
        rows = self.toolbox.grid_ranking.ranking(limit=10)
        return web.json_response(
            {"ok": True, "rows": list(rows), "text": render_ranking(rows)}
        )

    def _draw_tarot(self, mode: str) -> TarotReading:
        if mode in {"three", "三张"}:
            return self.tarot.draw_three()
        return self.tarot.draw_single()

    def _serialize_reading(self, reading: TarotReading) -> dict[str, Any]:
        cards = []
        for draw in reading.cards:
            meaning = draw.meaning
            img_path = self.tarot.deck.resolve_image(draw.card)
            cards.append(
                {
                    "key": draw.card.key,
                    "name_zh": draw.card.name_zh,
                    "roman": draw.card.roman,
                    "character": draw.card.character,
                    "orientation": draw.orientation,
                    "orientation_label": "逆位" if draw.orientation == "reversed" else "正位",
                    "position": draw.position,
                    "keywords": list(meaning.keywords),
                    "meaning": meaning.meaning,
                    "advice": meaning.advice,
                    "image_url": (
                        f"/hall/api/tarot/image/{draw.card.key}"
                        if img_path is not None and img_path.is_file()
                        else ""
                    ),
                }
            )
        return {
            "mode": reading.mode,
            "deck_size": reading.deck_size,
            "cards": cards,
            "text": self.tarot.format_reading(reading),
        }

    async def api_tarot(self, request: web.Request) -> web.Response:
        if self.tarot is None:
            return portal_error("TAROT_UNAVAILABLE", "塔罗牌库暂不可用", status=503)
        body, err = await read_json_object(request)
        if err is not None:
            return err
        assert body is not None
        mode = str(body.get("mode", "single")).strip().casefold()
        if mode not in {"single", "three", "单抽", "三张"}:
            return portal_error("INVALID_MODE", "塔罗模式仅支持 single 或 three", status=400)
        reading = self._draw_tarot(mode)
        return web.json_response({"ok": True, **self._serialize_reading(reading)})

    async def api_tarot_image(self, request: web.Request) -> web.StreamResponse:
        if self.tarot is None:
            raise web.HTTPNotFound()
        card_key = request.match_info["card_key"]
        if not _CARD_KEY_RE.fullmatch(card_key):
            raise web.HTTPNotFound()
        card = self.tarot.deck.card_by_key(card_key)
        if card is None:
            raise web.HTTPNotFound()
        path = self.tarot.deck.resolve_image(card)
        if path is None or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    async def api_counsel(self, request: web.Request) -> web.Response:
        body, err = await read_json_object(request)
        if err is not None:
            return err
        assert body is not None
        name = str(body.get("character", "")).strip()
        kw = str(body.get("keyword", "")).strip()
        if not name:
            return portal_error("MISSING_CHARACTER", "请填写妮姬名称或别名", status=400)
        bank = getattr(self.toolbox, "counsel", None)
        if bank is None:
            return web.json_response({"ok": True, "text": "咨询题库尚未配置。"})
        res = bank.search(name, kw)
        return web.json_response({"ok": True, "text": render_counsel_search(res, bank)})

    async def api_sync(self, request: web.Request) -> web.Response:
        body, err = await read_json_object(request)
        if err is not None:
            return err
        assert body is not None
        table = getattr(self.toolbox, "sync_table", None) if self.toolbox else None
        outpost_table = getattr(self.toolbox, "outpost_table", None) if self.toolbox else None
        manual_costs = body.get("manual_costs")
        try:
            plan, outpost_meta = plan_sync_from_inputs(
                current=body.get("current", ""),
                target=body.get("target", ""),
                inventory=body.get("inventory") if isinstance(body.get("inventory"), Mapping) else {},
                production=body.get("production") if isinstance(body.get("production"), Mapping) else None,
                outpost_level=body.get("outpost_level"),
                academy_boosts=body.get("academy_boosts") if isinstance(body.get("academy_boosts"), Mapping) else None,
                hourly_override=body.get("hourly_override") if isinstance(body.get("hourly_override"), Mapping) else None,
                cases=body.get("cases") if isinstance(body.get("cases"), Mapping) else None,
                wipeout_count=body.get("wipeout_count", 1),
                extra_daily=body.get("extra_daily") if isinstance(body.get("extra_daily"), Mapping) else None,
                manual_costs=manual_costs if isinstance(manual_costs, Mapping) else None,
                table=table,
                outpost_table=outpost_table,
                today=self._clock().date(),
            )
        except SyncLevelInputError as exc:
            return portal_error("INVALID_SYNC_INPUT", str(exc), status=400)
        return web.json_response(
            {
                "ok": True,
                "plan": plan.to_dict(),
                "outpost": outpost_meta,
                "text": render_sync_plan(plan),
            }
        )

    async def api_wishlist(self, request: web.Request) -> web.Response:
        body, err = await read_json_object(request)
        if err is not None:
            return err
        assert body is not None
        if self.toolbox is None:
            return portal_error("TOOLBOX_UNAVAILABLE", "愿望单服务未就绪", status=503)
        try:
            strategy = normalize_strategy(str(body.get("strategy", "balanced")))
            owned = parse_owned(
                str(body.get("owned", "")),
                rows=self.toolbox.wishlist_rows,
                resolver=self.toolbox.grid_resolver,
            )
            result = recommend(
                self.toolbox.wishlist_rows,
                owned,
                strategy,
                exclusions=self.toolbox.wishlist_exclusions,
                eligibility=self.toolbox.wishlist_eligibility,
            )
        except WishlistError as exc:
            return portal_error("INVALID_WISHLIST", str(exc), status=400)
        return web.json_response({"ok": True, "text": render_wishlist(result)})

    async def api_overload_sim(self, request: web.Request) -> web.Response:
        body, err = await read_json_object(request)
        if err is not None:
            return err
        assert body is not None
        try:
            targets = parse_targets(str(body.get("targets", "")))
            raw_options = body.get("options") or []
            options = parse_options(raw_options if isinstance(raw_options, list) else [])
            attempts = int(body.get("attempts", 100) or 100)
            attempts = max(1, min(attempts, 500))
            result = advise(options, targets)
            if body.get("simulate", True):
                sim = simulate(options, result.targets, attempts=attempts)
                from dataclasses import replace

                result = replace(result, simulation=sim)
        except (OverloadAdviceError, ValueError, TypeError) as exc:
            return portal_error("INVALID_OVERLOAD_INPUT", str(exc), status=400)
        return web.json_response({"ok": True, "text": render_advice(result)})

    async def api_overload_recommend(self, request: web.Request) -> web.Response:
        body, err = await read_json_object(request)
        if err is not None:
            return err
        assert body is not None
        query = str(body.get("character", "") or "").strip()
        if not query:
            return portal_error("MISSING_CHARACTER", "请填写妮姬名称或别名", status=400)
        characters = (getattr(self.toolbox, "overload_character_targets", None) or {}) if self.toolbox else {}
        rows = getattr(self.toolbox, "grid_rows", ()) if self.toolbox else ()
        resolver = self.grid_resolver or (getattr(self.toolbox, "grid_resolver", None) if self.toolbox else None)
        q = query.casefold()
        matched = None
        matched_name = query
        for key, spec in characters.items():
            if key.casefold() == q:
                matched = spec
                break
        if matched is None:
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                key = str(row.get("character_key") or row.get("name_code") or "")
                if key not in characters:
                    continue
                for col in ("name_cn", "name_zh_cn", "name_zh_tw", "name_en", "name", "name_code"):
                    val = row.get(col)
                    if isinstance(val, (str, int)) and str(val).casefold().strip() == q:
                        matched = characters[key]
                        matched_name = str(row.get("name_zh_cn") or row.get("name_cn") or query)
                        break
                if matched is not None:
                    break
        if matched is None and resolver is not None and rows:
            for row in resolver.find(rows, query)[:5]:
                key = str(row.get("character_key") or row.get("name_code") or "")
                if key in characters:
                    matched = characters[key]
                    matched_name = resolver.display_name(row)
                    break
        if matched is None:
            return portal_error("CHARACTER_NOT_FOUND", f"未收录角色「{query}」的专属推荐", status=404)
        return web.json_response(
            {
                "ok": True,
                "character": matched_name,
                "targets": list(matched.targets),
                "avoid": list(matched.avoid),
                "text": render_character_recommendation(matched_name, matched),
            }
        )

    # ------------------------------------------------------------------ 群聊反馈（日程 & 随机塔罗 E2E）

    async def _send_group_feedback(
        self,
        session: HallContextSession,
        *,
        kind: str,
        idempotency_key: str,
        text: str,
        image_paths: list[str],
    ) -> web.Response:
        prior, record = self.sessions.check_or_begin_delivery(
            session,
            idempotency_key=idempotency_key,
            kind=kind,
            target_label=session.group_label,
        )
        if prior is not None:
            if prior.status == "unknown":
                return portal_error(
                    "DELIVERY_UNKNOWN",
                    "上一次群内发送结果未知（可能已送达），系统严格禁止自动重发。请先在群聊确认后使用新操作再试。",
                    status=409,
                    delivery_status="unknown",
                )
            if prior.status == "pending":
                return portal_error(
                    "DELIVERY_PENDING",
                    "当前消息正在发送中，请勿重复提交。",
                    status=409,
                    delivery_status="pending",
                )
            return web.json_response(
                {
                    "ok": True,
                    "delivery_status": prior.status,
                    "deduplicated": True,
                    "target": session.group_label,
                    "message": prior.message,
                }
            )

        if self.bridge.send_to_qq is None:
            self.sessions.finish_delivery(
                record, status="failed", message="宿主 QQ 发送通道尚未连接"
            )
            return portal_error(
                "SENDER_UNAVAILABLE",
                "宿主 QQ 发送通道尚未连接",
                status=503,
                delivery_status="failed",
            )

        try:
            outcome = await asyncio.wait_for(
                self.bridge.send_to_qq(session.conversation_id, text, image_paths),
                timeout=15.0,
            )
        except (asyncio.TimeoutError, TimeoutError):
            self.sessions.finish_delivery(
                record,
                status="unknown",
                message="发送响应超时，结果未知（未自动重试）",
            )
            return portal_error(
                "DELIVERY_UNKNOWN",
                "群聊投递超时，发送状态未知，系统已停止自动重试以免重复刷屏。",
                status=504,
                delivery_status="unknown",
            )
        except Exception as exc:
            status = "unknown" if "unknown" in str(exc).casefold() else "failed"
            msg = (
                "群聊发送状态未知，已停止自动重试"
                if status == "unknown"
                else "群聊发送失败，请稍后重试"
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
                record, status="unknown", message="宿主返回未知投递状态（未自动重试）"
            )
            return portal_error(
                "DELIVERY_UNKNOWN",
                "发送状态未知，系统已阻止自动重发，请到群里核对。",
                status=502,
                delivery_status="unknown",
            )
        self.sessions.finish_delivery(
            record, status="sent", message=f"已发送至 {session.group_label}"
        )
        return web.json_response(
            {
                "ok": True,
                "delivery_status": "sent",
                "target": session.group_label,
                "summary": text[:200],
                "image_count": len(image_paths),
            }
        )

    async def feedback_calendar(self, request: web.Request) -> web.Response:
        session = self._optional_session(request)
        if session is None:
            return portal_error("HALL_CONTEXT_REQUIRED", "请先从群聊进入大厅", status=401)
        body, err = await read_json_object(request)
        if err is not None:
            return err
        assert body is not None
        idem = str(body.get("idempotency_key", "")).strip()
        if not _IDEMPOTENCY_RE.fullmatch(idem):
            return portal_error("INVALID_IDEMPOTENCY_KEY", "缺少有效幂等键", status=400)
        if self.calendar is None:
            return portal_error("CALENDAR_UNAVAILABLE", "日程服务尚未就绪", status=503)
        horizon = body.get("horizon", 14)
        snapshot = self.calendar.query_schedule(horizon)
        if not snapshot.service_available or not snapshot.has_snapshot:
            return portal_error("CALENDAR_EMPTY", "日程快照尚未就绪", status=503)

        images: list[str] = []
        text = snapshot.fallback_text
        if (
            self.bridge.build_calendar_payload is not None
            and self.bridge.render_t2i is not None
        ):
            payload = self.bridge.build_calendar_payload(snapshot)
            try:
                rendered = await self.bridge.render_t2i("calendar_schedule", payload)
            except Exception:
                rendered = None
            if isinstance(rendered, str) and rendered.strip():
                images = [rendered]
            elif isinstance(rendered, (list, tuple)):
                images = [str(p) for p in rendered if isinstance(p, str) and p.strip()]
            text = (
                f"【NIKKE 公共大厅 · 未来 {snapshot.horizon_days} 天日程】"
                if images
                else str(payload.get("fallback_text", text))
            )
        return await self._send_group_feedback(
            session,
            kind="hall_calendar",
            idempotency_key=idem,
            text=text,
            image_paths=images,
        )

    def _reading_from_feedback_body(self, body: dict[str, Any]) -> TarotReading:
        cards_payload = body.get("cards")
        mode = str(body.get("mode", "single")).strip().casefold()
        if isinstance(cards_payload, list) and cards_payload:
            drawn: list[DrawnTarotCard] = []
            for raw in cards_payload[:3]:
                if not isinstance(raw, dict):
                    continue
                card = self.tarot.deck.card_by_key(str(raw.get("key", "")))
                if card is None:
                    continue
                orientation = (
                    "reversed"
                    if str(raw.get("orientation", "")).strip() == "reversed"
                    else "upright"
                )
                pos = str(raw.get("position", "") or "")
                drawn.append(DrawnTarotCard(card, orientation, pos))
            if drawn:
                resolved_mode = "three" if len(drawn) == 3 else "single"
                return TarotReading(
                    resolved_mode,
                    tuple(drawn),
                    len(self.tarot.deck.active_cards()),
                )
        return self._draw_tarot(mode)

    async def feedback_tarot(self, request: web.Request) -> web.Response:
        session = self._optional_session(request)
        if session is None:
            return portal_error("HALL_CONTEXT_REQUIRED", "请先从群聊进入大厅", status=401)
        body, err = await read_json_object(request)
        if err is not None:
            return err
        assert body is not None
        idem = str(body.get("idempotency_key", "")).strip()
        if not _IDEMPOTENCY_RE.fullmatch(idem):
            return portal_error("INVALID_IDEMPOTENCY_KEY", "缺少有效幂等键", status=400)
        if self.tarot is None:
            return portal_error("TAROT_UNAVAILABLE", "塔罗牌库暂不可用", status=503)

        reading = self._reading_from_feedback_body(body)
        images = [
            str(path)
            for path in self.tarot.image_paths(reading)
            if path is not None and Path(path).is_file()
        ]
        text = self.tarot.format_reading(reading)
        return await self._send_group_feedback(
            session,
            kind="hall_tarot",
            idempotency_key=idem,
            text=text,
            image_paths=images,
        )

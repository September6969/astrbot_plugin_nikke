"""挂载于现有站点的同源竞技场接口。"""

import asyncio
import hashlib
import html
import json
import io
import re
import secrets
from collections import Counter
from pathlib import Path

from aiohttp import web

from ...features.arena.models import ArenaRosterSnapshot, ArenaTeam, ArenaThreeTeamPlan
from ...features.arena.optimizer import ThreeTeamOptimizer, validate_three
from ...features.arena.presentation import analysis_text, three_team_text
from .sessions import ArenaSessionStore

COOKIE = "__Secure-nikke_arena"
TOKEN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


class ArenaWebRoutes:
    def __init__(self, application, *, origin: str, template_root: Path, enabled, assets=None,
                 listener_ready=None):
        self.application = application
        self.origin = origin
        self.template_root = template_root
        self.enabled = enabled
        self.store = ArenaSessionStore()
        self.optimizer = ThreeTeamOptimizer(application.analyzer)
        # 以已收录模板的主选频次为主，同一模板对同一角色只计一次。
        preferred = Counter()
        featured = Counter()
        for template in application.analyzer.templates:
            preferred.update({slot[0] for slot in template["slots"] if slot})
            featured.update({key for slot in template["slots"] for key in slot})
        statistics = application.analyzer.statistics
        usage = statistics.character_usage if statistics and statistics.status == "available" else {}
        self.catalogue = sorted(application.directory.characters.values(),
                                key=lambda char: (-usage.get(char.key, 0), -preferred[char.key], -featured[char.key]))
        scope = statistics.metadata if usage else {}
        self.catalogue_basis = (f"赛事出场次数 · {scope['server']} {','.join(scope['seasons'])}"
                                if scope else "竞技场模板常见度")
        self.compute_slots = asyncio.Semaphore(2)
        self.portrait_slots = asyncio.Semaphore(4)
        self.assets = assets
        self.listener_ready = listener_ready

    def diagnostics(self) -> tuple[str, str]:
        if not self.active():
            return "已停用", "已停用"
        listener = ("监听中" if self.listener_ready() else "未监听") if self.listener_ready else "未接入探测"
        self.store.clean()
        full = len(self.store.sessions) >= self.store.capacity or len(self.store.links) >= self.store.capacity
        return listener, "容量已满" if full else "正常"

    def active(self) -> bool:
        if not self.enabled():
            self.store.clear()
            return False
        return True

    def link(self, actor_id: str, mode: str = "single") -> str:
        if not self.active():
            raise ValueError("竞技场网页当前未启用，单队可使用文字解队。")
        return self.origin + "/arena/open/" + self.store.create_link(actor_id, mode)

    def latest(self, actor_id: str):
        return self.store.latest(actor_id) if self.active() else None

    def mount(self, app: web.Application) -> None:
        app.middlewares.insert(0, self.security)
        app.add_routes([
            web.get("/arena/open/{token}", self.open),
            web.post("/arena/api/claim", self.claim),
            web.get("/arena/edit", self.edit),
            web.get("/arena/static/{name}", self.static),
            web.get("/arena/portrait/{key}", self.portrait, name="arena_portrait"),
            web.get("/arena/api/roster", self.roster),
            web.post("/arena/api/draft", self.draft),
            web.post("/arena/api/analyze", self.analyze),
            web.get("/arena/api/result", self.result),
            web.post("/arena/api/revoke", self.revoke),
        ])
        app.on_cleanup.append(self.cleanup)

    async def cleanup(self, _app) -> None:
        self.store.clear()

    @web.middleware
    async def security(self, request: web.Request, handler):
        if not request.path.startswith("/arena/"):
            return await handler(request)
        portrait = request.match_info.route.name == "arena_portrait" and request.method in {"GET", "HEAD"}
        try:
            if not self.active():
                raise web.HTTPNotFound()
            if portrait:
                self.session(request)
                # 头像目录单独计量，避免加载图片用尽编辑和分析的请求额度。
                request["web_rate_limit"] = ("arena_portrait", 240)
            if request.method not in {"GET", "HEAD"}:
                if request.headers.get("Origin") != self.origin:
                    raise web.HTTPForbidden(reason="来源校验失败")
                if request.path != "/arena/api/claim":
                    session = self.session(request)
                    if not secrets.compare_digest(request.headers.get("X-Arena-CSRF", ""), session.csrf):
                        raise web.HTTPForbidden(reason="CSRF 校验失败")
            if request.path.startswith("/arena/api/") and request.path != "/arena/api/claim":
                session = self.session(request)
                now = self.store.clock()
                session.requests[:] = [value for value in session.requests if now - value < 60]
                if len(session.requests) >= 30:
                    raise web.HTTPTooManyRequests(reason="会话请求过于频繁")
                session.requests.append(now)
            response = await handler(request)
        except ValueError as exc:
            response = web.json_response({"error": str(exc)}, status=400)
        except web.HTTPException as exc:
            response = web.json_response({"error": exc.reason}, status=exc.status)
            if exc.status in {302, 303}:
                response = exc
        except (asyncio.TimeoutError, TimeoutError):
            response = web.json_response({"error": "请求超时，请稍后重试。"}, status=503)
        except Exception:
            response = web.json_response({"error": "竞技场服务暂不可用。"}, status=503)
        response.headers.update({
            "Cache-Control": "private, max-age=300" if portrait and response.status == 200 else "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; "
                                       "img-src 'self' data:; connect-src 'self'; "
                                       "base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
        })
        return response

    def session(self, request):
        cookie = request.cookies.get(COOKIE, "")
        if not TOKEN.fullmatch(cookie):
            raise web.HTTPUnauthorized(reason="请回 QQ 获取新的编辑链接")
        try:
            return self.store.get(cookie)
        except ValueError:
            raise web.HTTPUnauthorized(reason="编辑会话已过期")

    async def open(self, request):
        token = request.match_info["token"]
        if not TOKEN.fullmatch(token):
            raise web.HTTPNotFound()
        # GET 不检查持有人、不消费令牌，也不返回任何账号资料。
        markup = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
                  '<meta name="viewport" content="width=device-width,initial-scale=1">'
                  '<link rel="stylesheet" href="/arena/static/editor.css">'
                  '<script src="/arena/static/claim.js" defer></script>'
                  '<title>进入竞技场编辑器</title><main><h1>竞技场编辑器</h1>'
                  '<p>点击后进入自己的临时编辑会话。首次进入有效期为 15 分钟。</p>'
                  '<form id="claim" method="post" action="/arena/api/claim">'
                  f'<input type="hidden" name="token" value="{html.escape(token, quote=True)}">'
                  '<button type="submit">进入编辑</button></form>'
                  '<p id="claim-status" role="status"></p>'
                  '<noscript>请启用 JavaScript，或回 QQ 使用文字解队。</noscript>'
                  '<p>链接已用过时，请回 QQ 重新获取。</p></main></html>')
        return web.Response(text=markup, content_type="text/html")

    async def claim(self, request):
        if request.content_type != "application/x-www-form-urlencoded":
            raise ValueError("请从引导页面进入编辑。")
        data = await request.post()
        if set(data) != {"token"} or not TOKEN.fullmatch(str(data["token"])):
            raise ValueError("无效的编辑链接。")
        cookie = self.store.claim(str(data["token"]))
        response = (web.json_response({"redirect": "/arena/edit"})
                    if request.headers.get("Accept") == "application/json"
                    else web.Response(status=303, headers={"Location": "/arena/edit"}))
        response.set_cookie(COOKIE, cookie, path="/arena", secure=True, httponly=True,
                            samesite="Lax", max_age=3600)
        return response

    async def edit(self, request):
        self.session(request)
        return web.Response(text=(self.template_root / "index.html").read_text(encoding="utf-8"),
                            content_type="text/html")

    async def static(self, request):
        name = request.match_info["name"]
        if name not in {"editor.js", "editor.css", "claim.js"}:
            raise web.HTTPNotFound()
        return web.Response(text=(self.template_root / name).read_text(encoding="utf-8"),
                            content_type="text/javascript" if name.endswith(".js") else "text/css")

    async def roster(self, request):
        session = self.session(request)
        snapshot = await self.application.read_roster(session.actor_id)
        characters = [{"key": char.key, "name": char.name, "burst": char.burst,
                       "base_key": char.base_key or char.key,
                       "aliases": self.application.directory.search_names(char.key),
                       "portrait": "/arena/portrait/" + char.key if self.assets else ""}
                      for char in self.catalogue]
        return web.json_response({
            "characters": characters, "owned": sorted(snapshot.keys), "roster_status": snapshot.status,
            "catalogue_basis": self.catalogue_basis,
            "csrf": session.csrf, "draft": session.draft, "revision": session.revision, "mode": session.mode,
        })

    async def portrait(self, request):
        self.session(request)
        char = self.application.directory.characters.get(request.match_info["key"])
        if char is None or self.assets is None:
            raise web.HTTPNotFound()

        def prepare():
            image, fallback = self.assets.get_lineup_portrait_by_resource_id(char.resource_id)
            if image is None or fallback:
                return None
            image.thumbnail((96, 96))
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return buffer.getvalue()

        async with self.portrait_slots:
            data = await asyncio.to_thread(prepare)
        if data is None:
            raise web.HTTPNotFound()
        return web.Response(body=data, content_type="image/png")

    async def payload(self, request) -> dict:
        if request.content_type != "application/json":
            raise ValueError("需要 JSON 请求。")
        try:
            value = await request.json()
        except (ValueError, UnicodeError):
            raise ValueError("JSON 格式无效。") from None
        if not isinstance(value, dict):
            raise ValueError("请求必须为对象。")
        return value

    def validate_draft(self, data: dict) -> dict:
        fields = {"teams", "roster_mode", "manual_owned", "objective"}
        if not isinstance(data, dict) or not fields <= set(data) <= fields | {"manual_candidates"}:
            raise ValueError("草稿字段无效。")
        teams = data["teams"]
        if (not isinstance(teams, list) or len(teams) not in {1, 3}
                or any(not isinstance(team, list) or len(team) != 5 for team in teams)):
            raise ValueError("请编辑一队或三队，每队五个位置。")
        known = self.application.directory.characters
        keys = [key for team in teams for key in team]
        if any(not isinstance(key, str) or (key and key not in known) for key in keys):
            raise ValueError("存在未知角色。")
        if not isinstance(data["roster_mode"], str) or data["roster_mode"] not in {"owned", "sandbox", "manual"}:
            raise ValueError("角色库模式无效。")
        owned = data["manual_owned"]
        if (not isinstance(owned, list) or len(owned) > 300
                or any(not isinstance(key, str) or key not in known for key in owned)):
            raise ValueError("手动持有列表无效。")
        if not isinstance(data["objective"], str) or data["objective"] not in {"two", "balanced", "speed"}:
            raise ValueError("三队目标无效。")
        candidates = data.get("manual_candidates")
        if "manual_candidates" in data and (
            len(teams) != 3 or not isinstance(candidates, list) or len(candidates) != 3
            or any(candidate is not None and (
                not isinstance(candidate, list) or len(candidate) != 5
                or any(not isinstance(key, str) or key not in known for key in candidate)
            ) for candidate in candidates)
        ):
            raise ValueError("手动候选需要按三场提供，每个候选恰好五人。")
        return data

    async def draft(self, request):
        session = self.session(request)
        payload = await self.payload(request)
        if set(payload) != {"draft", "revision"} or type(payload["revision"]) is not int:
            raise ValueError("草稿版本格式无效。")
        data = self.validate_draft(payload["draft"])
        async with session.lock:
            revision = payload["revision"]
            if revision == session.revision - 1 and session.draft == data:
                # 保存成功但回包丢失时，确认重试收到的是同一份草稿。
                return web.json_response({"revision": session.revision})
            if revision != session.revision:
                raise web.HTTPConflict(reason="草稿已在另一页面更新，请刷新")
            session.draft = data
            session.revision += 1
        return web.json_response({"revision": session.revision})

    async def analyze(self, request):
        session = self.session(request)
        payload = await self.payload(request)
        if set(payload) != {"draft", "idempotency_key", "revision"} or type(payload["revision"]) is not int:
            raise ValueError("分析字段无效。")
        key = payload["idempotency_key"]
        if not isinstance(key, str) or not TOKEN.fullmatch(key):
            raise ValueError("幂等键格式无效。")
        draft = self.validate_draft(payload["draft"])
        signature = hashlib.sha256(json.dumps(draft, sort_keys=True).encode("utf-8")).hexdigest()
        async with session.lock:
            prior = session.submissions.get(key)
            if prior:
                if prior[0] != signature:
                    raise web.HTTPConflict(reason="幂等键已用于另一份阵容")
                return web.json_response(prior[1])
            if payload["revision"] != session.revision:
                raise web.HTTPConflict(reason="草稿已在另一页面更新，请刷新")
            async with asyncio.timeout(20):
                async with self.compute_slots:
                    result = await self.calculate(session.actor_id, draft)
            # 会话可能在等待名单时到期或关闭，重新验证后才落结果。
            if not self.active():
                raise web.HTTPGone(reason="网页已关闭")
            self.session(request)
            session.draft = draft
            session.revision += 1
            self.store.save_result(session, result)
            response = self.result_payload(result)
            response["revision"] = session.revision
            if len(session.submissions) >= 16:
                session.submissions.pop(next(iter(session.submissions)))
            session.submissions[key] = (signature, response)
            return web.json_response(response)

    async def calculate(self, actor_id, draft):
        directory = self.application.directory
        teams = tuple(ArenaTeam(tuple(directory.characters[key] for key in team if key))
                      for team in draft["teams"])
        available = None
        if draft["roster_mode"] == "owned":
            available = await self.application.read_roster(actor_id)
            if available.status not in {"available", "partial"}:
                raise ValueError("持有角色库不可读取，请检查绑定或选择手动/沙盒模式。")
        elif draft["roster_mode"] == "manual":
            available = ArenaRosterSnapshot(frozenset(draft["manual_owned"]), "manual", 0, "", ())
        if len(teams) == 3:
            validate_three(teams)
            manual = tuple(ArenaTeam(tuple(directory.characters[key] for key in candidate)) if candidate else None
                           for candidate in draft.get("manual_candidates", ()))
            return await asyncio.to_thread(
                self.optimizer.solve, teams, available,
                objective=draft["objective"], manual_candidates=manual,
            )
        return await asyncio.to_thread(self.application.analyzer.analyze, teams[0], available)

    @staticmethod
    def result_payload(result):
        text = three_team_text(result) if isinstance(result, ArenaThreeTeamPlan) else analysis_text(result)
        return {"text": text, "saved": True, "model_version": result.model_version}

    async def result(self, request):
        session = self.session(request)
        return web.json_response(self.result_payload(session.result) if session.result else {"saved": False})

    async def revoke(self, request):
        self.store.revoke(request.cookies.get(COOKIE, ""))
        response = web.json_response({"revoked": True})
        response.del_cookie(COOKIE, path="/arena")
        return response

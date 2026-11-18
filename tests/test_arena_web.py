"""临时编辑会话、同源校验与账号隔离验收。"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from astrbot_plugin_nikke.core.storage import NikkeStore
from astrbot_plugin_nikke.features.arena.roster import ArenaRosterProvider
from astrbot_plugin_nikke.integrations.arena.sessions import ArenaSessionStore
from astrbot_plugin_nikke.integrations.arena.web_routes import ArenaWebRoutes, COOKIE
from astrbot_plugin_nikke.integrations.blablalink.client import BlaBlaClient, CHARACTERS
from astrbot_plugin_nikke.integrations.web.service import BindingWebService
from astrbot_plugin_nikke.application.commands.arena import ArenaCommandHandler
from astrbot_plugin_nikke.application.commands.contracts import CommandContext
from test_arena_core import arena


def test_preview_claim_replay_expiry_and_storage_hashes():
    clock = [0.0]
    store = ArenaSessionStore(clock=lambda: clock[0], capacity=2)
    token = store.create_link("a")
    assert token not in store.links
    cookie = store.claim(token)
    assert cookie not in store.sessions
    assert store.get(cookie).actor_id == "a"
    with pytest.raises(ValueError):
        store.claim(token)
    clock[0] = 1801
    with pytest.raises(ValueError):
        store.get(cookie)
    token = store.create_link("b")
    clock[0] += 901
    with pytest.raises(ValueError):
        store.claim(token)


def test_absolute_expiry_results_ttl_and_revoke():
    clock = [0.0]
    store = ArenaSessionStore(clock=lambda: clock[0])
    cookie = store.claim(store.create_link("a"))
    session = store.get(cookie)
    store.save_result(session, "result-a")
    assert store.latest("b") is None
    for now in (1000, 2000, 3000):
        clock[0] = now
        assert store.get(cookie).actor_id == "a"
    clock[0] = 3601
    with pytest.raises(ValueError):
        store.get(cookie)
    assert store.latest("a") == "result-a"
    clock[0] = 7201
    assert store.latest("a") is None


def draft(arena):
    team = arena.directory.parse_team("红莲/豺狼/布兰儿/桑迪/特蕾娜")
    return {"teams": [list(team.keys)], "roster_mode": "sandbox", "manual_owned": [], "objective": "two"}


@pytest_asyncio.fixture
async def site(arena):
    async def owned(_actor):
        raise ValueError("synthetic-cookie-secret")
    arena.roster = SimpleNamespace(owned=owned)
    enabled = [True]
    routes = ArenaWebRoutes(arena, origin="https://arena.example",
                           template_root=Path(__file__).resolve().parents[1] / "templates" / "arena_web",
                           enabled=lambda: enabled[0])
    binding = BindingWebService(arena.roster, None, Path("unused.zip"), public_base_url=routes.origin)
    binding.add_route_installer(routes.mount)
    client = TestClient(TestServer(binding.app()))
    await client.start_server()
    yield client, routes, enabled
    await client.close()


async def claim(client, routes, actor="a", token=None):
    token = token or routes.store.create_link(actor)
    response = await client.post("/arena/api/claim", data={"token": token},
                                 headers={"Origin": routes.origin}, allow_redirects=False)
    assert response.status == 303
    assert response.headers["Location"] == "/arena/edit"
    morsel = response.cookies[COOKIE]
    assert morsel["secure"] and morsel["httponly"] and morsel["samesite"] == "Lax"
    cookie = morsel.value
    session = routes.store.get(cookie)
    headers = {"Cookie": f"{COOKIE}={cookie}", "Origin": routes.origin, "X-Arena-CSRF": session.csrf}
    return headers


@pytest.mark.asyncio
async def test_command_to_shared_web_and_back(site, arena):
    client, routes, _ = site
    handler = ArenaCommandHandler(arena, enabled=True, web_routes=routes)

    async def command(action, actor="a"):
        context = CommandContext(actor_id=actor, is_private_chat=True, parameters={"action": action})
        return (await handler.handle(context)).messages[0].text

    link = (await command("编辑")).splitlines()[-1]
    token = link.rsplit("/", 1)[-1]
    headers = await claim(client, routes, token=token)
    payload = {"draft": draft(arena), "idempotency_key": "test-command-to-web-integration-01", "revision": 0}
    response = await client.post("/arena/api/analyze", json=payload, headers=headers)
    assert response.status == 200
    assert await command("结果") == (await response.json())["text"]
    assert "暂无" in await command("结果", actor="b")


@pytest.mark.asyncio
async def test_browser_three_team_analysis_recovers_from_timeout_and_requires_close_confirmation(site):
    """用真实编辑器回归分析按钮、丢失回包和结束会话。"""
    browser_api = pytest.importorskip("playwright.async_api")
    client, routes, _ = site
    routes.origin = str(client.make_url("/")).rstrip("/")
    link = routes.link("browser-fixture", "three")

    async with browser_api.async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        release_response = asyncio.Event()
        try:
            page = await browser.new_page(viewport={"width": 320, "height": 800})
            page.set_default_timeout(7000)
            await page.clock.install()
            await page.goto(link)
            await page.locator("#claim button").click()
            await page.wait_for_url("**/arena/edit")
            await browser_api.expect(page.locator("#picker-title")).to_contain_text("P1")
            await page.get_by_role("button", name="B1", exact=True).click()
            await page.get_by_role("searchbox", name="搜索角色").fill("豺狼")
            await page.locator("#choices").get_by_role("button", name="豺狼 · B1").click()
            await browser_api.expect(page.locator("#picker-title")).to_contain_text("P2")
            await page.get_by_role("button", name="第 1 队 · P1 豺狼").click()
            await page.get_by_role("button", name="换位", exact=True).click()
            await page.get_by_role("button", name="第 1 队 · P2 空位").click()
            await browser_api.expect(page.get_by_role("button", name="第 1 队 · P2 豺狼")).to_be_visible()
            await page.get_by_role("button", name="换位", exact=True).click()
            await page.get_by_role("button", name="队伍 2 · 0/5").click()
            await page.get_by_role("button", name="第 2 队 · P1 空位").click()
            await browser_api.expect(page.get_by_role("button", name="第 2 队 · P1 豺狼")).to_be_visible()
            await page.get_by_text("粘贴导入", exact=True).click()
            await page.locator("#paste").fill(
                "红莲/豺狼/布兰儿/桑迪/特蕾娜\n"
                "丽塔/麦斯威尔：平凡技师/尼恩：透视之眼/拉普拉斯/德雷克\n"
                "N102/安妮：奇迹仙女/麦斯威尔/拉普拉斯：究极英雄/德雷克：终极反派"
            )
            await page.locator("#import").click()
            await browser_api.expect(page.locator("#status")).to_have_text("草稿已保存")
            await page.get_by_text("加入我方候选", exact=True).click()
            candidate = page.get_by_role("textbox", name="第 1 场")
            await candidate.fill("红莲/豺狼/布兰儿/桑迪/特蕾娜")
            await page.get_by_role("button", name="保存我方候选").click()
            await browser_api.expect(page.locator("#status")).to_have_text("草稿已保存")

            summary = page.locator("#end-session summary")
            analyze = page.locator("#analyze")
            await summary.click()
            await browser_api.expect(page.get_by_role("button", name="确认结束会话")).to_be_visible()
            await browser_api.expect(analyze).to_be_enabled()
            await summary.click()

            first_saved = asyncio.Event()
            submissions = []

            async def intercept_analysis(route):
                key = route.request.post_data_json["idempotency_key"]
                submissions.append(key)
                response = await route.fetch()
                if len(submissions) == 1:
                    assert response.ok
                    first_saved.set()
                    await release_response.wait()
                await route.fulfill(response=response)

            await page.route("**/arena/api/analyze", intercept_analysis)
            await analyze.click()
            await asyncio.wait_for(first_saved.wait(), 5)
            await browser_api.expect(analyze).to_have_text("正在分析…")
            await page.clock.fast_forward(25000)
            await browser_api.expect(page.locator("#status")).to_contain_text("请求等待超时")
            await browser_api.expect(analyze).to_have_text("重试分析")
            release_response.set()
            await analyze.click()
            await browser_api.expect(page.locator("#result")).to_be_visible()
            assert len(submissions) == 2 and submissions[0] == submissions[1]
            await page.reload()
            await browser_api.expect(page.locator("#result")).to_be_visible()
            await page.get_by_text("加入我方候选", exact=True).click()
            await browser_api.expect(candidate).to_have_value("红莲/豺狼/布兰儿/桑迪/特蕾娜")

            await summary.click()
            await page.get_by_role("button", name="确认结束会话").click()
            await browser_api.expect(page.locator("#status")).to_contain_text("会话已结束")
            await browser_api.expect(analyze).to_be_disabled()
            button_box = await analyze.bounding_box()
            status_box = await page.locator("#status").bounding_box()
            assert 0 <= status_box["y"] - (button_box["y"] + button_box["height"]) <= 60
        finally:
            release_response.set()
            await browser.close()


@pytest.mark.asyncio
async def test_manual_candidates_respect_roster_and_cross_team_exclusivity(site, arena):
    client, routes, _ = site
    headers = await claim(client, routes)
    teams = [list(arena.directory.parse_team(line).keys) for line in (
        "红莲/豺狼/布兰儿/桑迪/特蕾娜",
        "丽塔/麦斯威尔：平凡技师/尼恩：透视之眼/拉普拉斯/德雷克",
        "N102/安妮：奇迹仙女/麦斯威尔/拉普拉斯：究极英雄/德雷克：终极反派",
    )]
    arena.analyzer.templates = []
    permitted = [key for team in teams for key in team]
    payload = {"draft": {"teams": teams, "roster_mode": "manual", "manual_owned": permitted[:14],
                        "objective": "two", "manual_candidates": teams},
               "idempotency_key": "manual-candidate-roster-00000001", "revision": 0}
    response = await client.post("/arena/api/analyze", json=payload, headers=headers)
    assert response.status == 400
    assert "第 3 场" in (await response.json())["error"]
    assert routes.latest("a") is None

    payload["draft"]["manual_owned"] = permitted
    response = await client.post("/arena/api/analyze", json=payload, headers=headers)
    assert response.status == 200
    assert "手动加入本场候选" in (await response.json())["text"]
    assert [list(item.team.keys) for item in routes.latest("a").teams] == teams

    payload["revision"] = 1
    payload["idempotency_key"] = "manual-candidate-roster-00000002"
    payload["draft"]["manual_candidates"] = [teams[0], teams[0], teams[2]]
    response = await client.post("/arena/api/analyze", json=payload, headers=headers)
    assert response.status == 200
    assert not routes.latest("a").teams
    assert "未找到十五人互斥" in (await response.json())["text"]


@pytest.mark.asyncio
async def test_bound_store_and_gateway_isolate_web_and_qq_results(tmp_path, arena):
    store = NikkeStore(tmp_path / "binding")
    enemy = arena.directory.parse_team("红莲/豺狼/布兰儿/桑迪/特蕾娜")
    owned = next(item.team.keys for item in arena.analyzer.analyze(enemy, limit=100).recommendations
                 if all(arena.directory.by_code.get(char.name_code) == char.key
                        for char in item.team.characters))
    other_owned = next(key for key in enemy.keys if key not in owned)
    profile_keys = {"900001": owned, "900002": (other_owned,), "900003": ()}
    cookies = {actor: f"game_token=fake-secret-{actor}" for actor in profile_keys}
    for actor, cookie in cookies.items():
        token = f"fixture-binding-{actor}"
        store.create_bind_session(token, actor, status="pending")
        store.consume_bind_session(token, cookie, actor, f"openid-{actor}",
                                   "私有昵称", "私有角色名", "1", success_status="success")

    calls = []

    def upstream(request):
        assert request.url.path == CHARACTERS
        payload = json.loads(request.content)
        assert set(payload) == {"intl_open_id", "nikke_area_id"}
        actor = payload["intl_open_id"].removeprefix("openid-")
        assert request.headers["Cookie"] == cookies[actor]
        calls.append(actor)
        if actor == "900003":
            return httpx.Response(200, json={"code": "401"})
        rows = [{"name_code": arena.directory.characters[key].name_code}
                for key in profile_keys[actor]]
        return httpx.Response(200, json={"code": 0, "data": {"characters": rows}})

    gateway = BlaBlaClient(transport=httpx.MockTransport(upstream), account_reader=store)
    arena.roster = ArenaRosterProvider(store, gateway, arena.directory)
    routes = ArenaWebRoutes(arena, origin="https://arena.example",
                           template_root=Path(__file__).resolve().parents[1] / "templates" / "arena_web",
                           enabled=lambda: True)
    binding = BindingWebService(store, gateway, Path("unused.zip"), public_base_url=routes.origin)
    binding.add_route_installer(routes.mount)
    handler = ArenaCommandHandler(arena, enabled=True, web_routes=routes)

    async def command(actor, action):
        result = await handler.handle(CommandContext(actor_id=actor, is_private_chat=True,
                                                      parameters={"action": action}))
        return result.messages[0].text

    try:
        async with TestClient(TestServer(binding.app())) as client:
            payload = {"draft": {**draft(arena), "roster_mode": "owned"},
                       "idempotency_key": "bound-roles-integration-test-0001", "revision": 0}
            first, second, expired = profile_keys
            for actor, key in ((first, owned), (second, (other_owned,))):
                token = (await command(actor, "编辑")).splitlines()[-1].rsplit("/", 1)[-1]
                headers = await claim(client, routes, actor=actor, token=token)
                view = await client.get("/arena/api/roster", headers=headers)
                assert view.status == 200
                roster = await view.json()
                assert roster["owned"] == sorted(key)
                assert roster["roster_status"] == "available"
                assert all(marker not in str(roster) for marker in ("fake-secret", "openid-", "私有昵称", "私有角色名"))
                assert f"已映射 {len(key)} 人" in await command(actor, "我的")
                response = await client.post("/arena/api/analyze", json=payload, headers=headers)
                assert response.status == 200
                assert await command(actor, "结果") == (await response.json())["text"]
                if actor == first:
                    assert "暂无" in await command(second, "结果")
            assert routes.latest(first).recommendations
            assert all(set(item.team.keys) <= set(owned) for item in routes.latest(first).recommendations)
            assert not routes.latest(second).recommendations
            headers = await claim(client, routes, actor=expired)
            view = await client.get("/arena/api/roster", headers=headers)
            assert (await view.json())["roster_status"] == "expired"
            assert "重新绑定" in await command(expired, "我的")
            response = await client.post("/arena/api/analyze", json=payload, headers=headers)
            assert response.status == 400
            assert routes.latest(expired) is None
            assert calls.count(first) == calls.count(second) == 1
    finally:
        await gateway.aclose()


def test_web_diagnostics_distinguishes_listener_and_session_capacity(arena):
    listening = [False]
    routes = ArenaWebRoutes(arena, origin="https://arena.example", template_root=Path("unused"),
                           enabled=lambda: True, listener_ready=lambda: listening[0])
    assert routes.diagnostics() == ("未监听", "正常")
    listening[0] = True
    routes.store.capacity = 1
    routes.link("private-actor")
    assert routes.diagnostics() == ("监听中", "容量已满")


@pytest.mark.asyncio
async def test_get_preview_does_not_consume_or_expose_identity(site):
    client, routes, _ = site
    token = routes.store.create_link("private-actor")
    for _ in range(2):
        response = await client.get("/arena/open/" + token)
        text = await response.text()
        assert response.status == 200
        assert "private-actor" not in text
        assert response.headers["Cache-Control"] == "no-store"
    routes.store.claim(token)


@pytest.mark.asyncio
async def test_claim_origin_and_token_replay(site):
    client, routes, _ = site
    token = routes.store.create_link("a")
    response = await client.post("/arena/api/claim", data={"token": token},
                                 headers={"Origin": "https://evil.example"})
    assert response.status == 403
    response = await client.post("/arena/api/claim", data={"token": token}, allow_redirects=False)
    assert response.status == 403
    routes.store.claim(token)
    response = await client.post("/arena/api/claim", data={"token": token},
                                 headers={"Origin": routes.origin}, allow_redirects=False)
    assert response.status == 400


@pytest.mark.asyncio
async def test_roster_is_sanitized_and_session_bound(site, arena):
    client, routes, _ = site
    headers = await claim(client, routes)
    response = await client.get("/arena/api/roster", headers=headers)
    data = await response.json()
    assert response.status == 200
    assert data["roster_status"] == "unavailable"
    assert "synthetic-cookie-secret" not in str(data)
    assert "actor_id" not in data
    assert data["characters"]
    assert (await client.get("/arena/api/roster")).status == 401
    payload = {"draft": {**draft(arena), "roster_mode": "owned"},
               "idempotency_key": "failed-roles-integration-test-01", "revision": 0}
    analysis = await client.post("/arena/api/analyze", json=payload, headers=headers)
    assert analysis.status == 400
    assert "synthetic-cookie-secret" not in await analysis.text()
    command = ArenaCommandHandler(arena, enabled=True, web_routes=routes)
    reply = await command.handle(CommandContext(actor_id="a", is_private_chat=True,
                                                parameters={"action": "我的"}))
    assert "unavailable" in reply.messages[0].text
    assert "synthetic-cookie-secret" not in reply.messages[0].text


@pytest.mark.asyncio
async def test_roster_lists_frequent_template_picks_first(site, arena):
    client, routes, _ = site
    headers = await claim(client, routes)
    async with client.get("/arena/api/roster", headers=headers) as response:
        keys = [entry["key"] for entry in (await response.json())["characters"]]
    assert keys[:3] == ["jackal", "centi", "blanc"]
    assert set(keys) == set(arena.directory.characters)


@pytest.mark.asyncio
async def test_portraits_have_private_cache_and_do_not_exhaust_editor_limit(site):
    client, routes, _ = site
    routes.assets = SimpleNamespace(
        get_lineup_portrait_by_resource_id=lambda _: (Image.new("RGBA", (48, 48)), False)
    )
    url = "/arena/portrait/scarlet"
    async with client.get(url) as response:
        assert response.status == 401
        assert response.headers["Cache-Control"] == "no-store"
    headers = await claim(client, routes)
    for _ in range(65):
        async with client.get(url, headers=headers) as response:
            assert response.status == 200
            assert response.headers["Cache-Control"] == "private, max-age=300"
            assert response.content_type == "image/png"
            await response.read()
    async with client.get("/arena/api/roster", headers=headers) as response:
        assert response.status == 200
        assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
async def test_csrf_draft_revision_and_schema(site, arena):
    client, routes, _ = site
    headers = await claim(client, routes)
    payload = {"draft": draft(arena), "revision": 0}
    bad = dict(headers, **{"X-Arena-CSRF": "bad"})
    assert (await client.post("/arena/api/draft", json=payload, headers=bad)).status == 403
    assert (await client.post("/arena/api/draft", json=payload, headers=headers)).status == 200
    replay = await client.post("/arena/api/draft", json=payload, headers=headers)
    assert replay.status == 200 and await replay.json() == {"revision": 1}
    payload["draft"]["teams"][0].reverse()
    assert (await client.post("/arena/api/draft", json=payload, headers=headers)).status == 409
    payload["actor_id"] = "b"
    assert (await client.post("/arena/api/draft", json=payload, headers=headers)).status == 400


@pytest.mark.asyncio
async def test_analysis_idempotent_actor_result_and_disable(site, arena):
    client, routes, enabled = site
    headers = await claim(client, routes)
    payload = {"draft": draft(arena), "idempotency_key": "a" * 40, "revision": 0}
    first = await client.post("/arena/api/analyze", json=payload, headers=headers)
    assert first.status == 200
    data = await first.json()
    repeat = await client.post("/arena/api/analyze", json=payload, headers=headers)
    assert await repeat.json() == data
    assert routes.latest("a") is not None
    assert routes.latest("b") is None
    payload["draft"]["objective"] = "speed"
    assert (await client.post("/arena/api/analyze", json=payload, headers=headers)).status == 409
    other_headers = await claim(client, routes, "b")
    assert await (await client.get("/arena/api/result", headers=other_headers)).json() == {"saved": False}
    enabled[0] = False
    assert (await client.get("/arena/api/result", headers=headers)).status == 404
    assert not routes.store.sessions


@pytest.mark.asyncio
async def test_session_rate_limit_and_revoke(site):
    client, routes, _ = site
    headers = await claim(client, routes)
    for _ in range(30):
        assert (await client.get("/arena/api/result", headers=headers)).status == 200
    response = await client.get("/arena/api/result", headers=headers)
    assert response.status == 429
    assert response.headers["Cache-Control"] == "no-store"
    routes.store.sessions.clear()
    headers = await claim(client, routes, "b")
    assert (await client.post("/arena/api/revoke", json={}, headers=headers)).status == 200
    assert (await client.get("/arena/edit", headers=headers)).status == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [
    {"teams": None}, {"actor_id": "b"}, [], None,
    {"teams": [["unknown"] * 5], "roster_mode": "sandbox", "manual_owned": [], "objective": "two"},
    {"teams": [[""] * 5], "roster_mode": [], "manual_owned": [], "objective": "two"},
])
async def test_reject_untrusted_drafts(site, bad):
    client, routes, _ = site
    headers = await claim(client, routes)
    response = await client.post("/arena/api/draft", json={"draft": bad, "revision": 0}, headers=headers)
    assert response.status == 400


@pytest.mark.asyncio
async def test_stale_analysis_cannot_overwrite_newer_draft(site, arena):
    client, routes, _ = site
    headers = await claim(client, routes)
    previous = draft(arena)
    updated = dict(previous, objective="speed")
    response = await client.post("/arena/api/draft", json={"draft": updated, "revision": 0}, headers=headers)
    assert response.status == 200
    response = await client.post("/arena/api/analyze", json={
        "draft": previous, "idempotency_key": "b" * 40, "revision": 0,
    }, headers=headers)
    assert response.status == 409
    response = await client.get("/arena/api/roster", headers=headers)
    assert (await response.json())["draft"] == updated
    assert routes.latest("a") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("trusted_peer,other_status", [("", 429), ("127.0.0.1", 200)])
async def test_trusted_proxy_keeps_client_rate_buckets_separate(trusted_peer, other_status):
    binding = BindingWebService(None, None, Path("unused.zip"), trusted_proxy_ip=trusted_peer)
    app = binding.app()

    async def ready(_request):
        from aiohttp import web
        return web.Response(status=200)

    app.router.add_get("/rate-probe", ready)
    async with TestClient(TestServer(app)) as client:
        for _ in range(60):
            assert (await client.get("/rate-probe", headers={"X-Forwarded-For": "192.0.2.1"})).status == 200
        assert (await client.get("/rate-probe", headers={"X-Forwarded-For": "192.0.2.3, 192.0.2.1"})).status == 429
        assert (await client.get("/rate-probe", headers={"X-Forwarded-For": "192.0.2.2"})).status == other_status

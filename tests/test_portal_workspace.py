# SPDX-License-Identifier: GPL-3.0-or-later
"""个人指挥官工作台（Phase 5-6）与 QQ-Web-QQ 闭环、纯 @机器人 入口测试。"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from astrbot_plugin_nikke.adapters.astrbot.command_adapter import AstrBotCommandAdapter
from astrbot_plugin_nikke.application.commands.contracts import CommandContext
from astrbot_plugin_nikke.application.commands.portal import PortalCommandHandler
from astrbot_plugin_nikke.core.storage import NikkeStore
from astrbot_plugin_nikke.features.solo_raid.plans import SoloRaidPlanStore
from astrbot_plugin_nikke.features.solo_raid.seasons import Boss, Season, SeasonCatalog
from astrbot_plugin_nikke.features.web_portal import PortalSessionStore
from astrbot_plugin_nikke.integrations.web.portal_bridge import PortalHostBridge
from astrbot_plugin_nikke.integrations.web.workspace_service import (
    WORKSPACE_COOKIE,
    WORKSPACE_CSRF_HEADER,
    WorkspaceWebService,
)

SITE_ORIGIN = "https://nikke.irises777.xyz"


@dataclass
class _FakeDashboard:
    commander_name: str = "测试指挥官"
    commander_level: int = 310
    team_combat: int = 550000
    synchro_level: int = 280
    outpost_battle_level: int = 220
    normal_campaign: str = "34-18"
    hard_campaign: str = "18-12"
    progress_tribe_tower: str = "300"
    character_count: int = 98
    fetched_at: str = "2026-11-25 10:00"


class _FakeProfileApp:
    def __init__(self) -> None:
        self.calls = 0

    async def build_dashboard(self, _account):
        self.calls += 1
        return _FakeDashboard()


class _FakeRosterToolbox:
    def __init__(self, store: NikkeStore) -> None:
        self.calls = 0
        self.solo_catalog = SeasonCatalog(
            seasons=(
                Season(
                    season_id="43",
                    name="Season 43",
                    source_url="https://example.com",
                    checked_at="2026-11-25",
                    bosses=(Boss(boss_id="boss_1", name="BossA", weakness="Fire", element="Fire"),),
                ),
            ),
            available=True,
            reason="",
        )
        self.solo_plans = SoloRaidPlanStore(store)
        self.solo_damage_model = None
        self.solo_engine = None
        self.grid_rows = ()
        self.grid_resolver = None
        self.wishlist_rows = ()
        self.wishlist_exclusions = ()
        self.wishlist_eligibility = {}
        root = Path(__file__).resolve().parents[1] / "assets" / "data"
        from astrbot_plugin_nikke.features.sync.cost_table import SyncCostTable
        from astrbot_plugin_nikke.features.sync.outpost import OutpostRateTable
        from astrbot_plugin_nikke.features.overload_advice.advisor import load_character_targets

        self.sync_table = SyncCostTable.from_file(root / "sync_level_costs.json")
        self.outpost_table = OutpostRateTable.from_file(root / "outpost_rates.json")
        self.overload_character_targets = load_character_targets(root / "overload_recommendations.json")
        self.feeds = SimpleNamespace(command=lambda *_args: "订阅状态：无")

    @staticmethod
    async def profile_loader(_account):
        return {
            "basic": {
                "currencies": [
                    {"type": 3000, "value": "8746"},
                    {"type": 2000, "value": "8648063"},
                    {"type": 1000, "value": "48966309"},
                ]
            },
            "outpost": {
                "synchro_level": 574,
                "outpost_battle_level": 651,
                "tactic_academy_class": 13000,
                "tactic_academy_lesson": 13003,
            },
        }

    @staticmethod
    async def card_loader(_actor_id, query):
        return SimpleNamespace(
            name_cn=query or "红莲",
            equipment={
                "head": SimpleNamespace(
                    equipped=True,
                    options=(SimpleNamespace(display_name="防御力增加", tier=6, locked=False),),
                )
            },
        )

    async def roster_loader(self, _account):
        self.calls += 1
        return [
            {"name_code": "1", "name_zh_cn": "丽塔", "burst": "Step1", "element": "Iron", "combat": 50000, "grade": 3},
            {"name_code": "2", "name_zh_cn": "桑迪", "burst": "Step2", "element": "Iron", "combat": 48000, "grade": 3},
            {"name_code": "3", "name_zh_cn": "红莲", "burst": "Step3", "element": "Electric", "combat": 70000, "grade": 3},
        ]

    @staticmethod
    def record_growth(_ctx, _dashboard, account=None):
        return SimpleNamespace(summary="战力 +1200")


def _make_workspace(tmp_path: Path, *, send_fn=None):
    store = NikkeStore(tmp_path / "data")
    seed_tok = "seed_tok_" + ("a" * 32)
    store.create_bind_session(seed_tok, "1008611", 600, status="pending")
    store.consume_bind_session(
        seed_tok,
        "game_token=tok_secret; game_uid=1234567890; game_openid=openid_99999999",
        "1234567890",
        "openid_99999999",
        "CommanderA",
        "CommanderA",
        "81",
        success_status="success",
    )
    sessions = PortalSessionStore()
    bridge = PortalHostBridge(send_to_qq=send_fn)
    profile_app = _FakeProfileApp()
    toolbox = _FakeRosterToolbox(store)
    arena_web = SimpleNamespace(
        active=lambda: True,
        link=lambda actor, mode="single": f"{SITE_ORIGIN}/arena/open/fake_{actor}_{mode}",
    )
    ws = WorkspaceWebService(
        site_origin=SITE_ORIGIN,
        sessions=sessions,
        bridge=bridge,
        store=store,
        feature_flags={"enable_arena": True, "arena_web_enabled": True},
        profile_application=profile_app,
        toolbox=toolbox,
        arena_web=arena_web,
    )
    app = web.Application()
    ws.mount(app)
    return ws, app, store, profile_app, toolbox


@pytest.mark.asyncio
async def test_workspace_lazy_bootstrap_self_bind_and_five_team_build(tmp_path: Path) -> None:
    ws, app, store, profile_app, toolbox = _make_workspace(tmp_path)
    link = ws.create_link("1008611", conversation_id="aiocqhttp:GroupMessage:555666", group_label="QQ群(555666)")
    token = link.rsplit("/", 1)[-1]

    async with TestClient(TestServer(app)) as client:
        # 未登录访问工作台返回 401
        unauth = await client.get("/workspace")
        assert unauth.status == 401

        # GET open 不消费
        assert (await client.get(f"/workspace/open/{token}")).status == 200
        assert (await client.get(f"/workspace/open/{token}")).status == 200

        claim = await client.post(
            "/workspace/api/claim",
            data={"token": token},
            headers={"Origin": SITE_ORIGIN, "Accept": "application/json"},
        )
        assert claim.status == 200
        cookie = claim.cookies[WORKSPACE_COOKIE].value

        # bootstrap 绝不触发 profile/roster 上游调用，且 UID 脱敏
        boot = await client.get("/workspace/api/bootstrap", cookies={WORKSPACE_COOKIE: cookie})
        assert boot.status == 200
        boot_json = await boot.json()
        assert profile_app.calls == 0
        assert toolbox.calls == 0
        assert boot_json["binding"]["bound"] is True
        assert "1234567890" not in str(boot_json)
        assert boot_json["binding"]["masked_uid"] == "***7890"
        csrf = boot_json["csrf"]

        # 自助生成绑定会话
        bind_resp = await client.post(
            "/workspace/api/bind/start",
            cookies={WORKSPACE_COOKIE: cookie},
            headers={"Origin": SITE_ORIGIN, WORKSPACE_CSRF_HEADER: csrf},
        )
        assert bind_resp.status == 200
        bind_data = await bind_resp.json()
        assert store.get_bind_session(bind_data["token"]) is not None

        # 按需拉取个人档案
        prof_resp = await client.post(
            "/workspace/api/profile/load",
            cookies={WORKSPACE_COOKIE: cookie},
            headers={"Origin": SITE_ORIGIN, WORKSPACE_CSRF_HEADER: csrf},
        )
        assert prof_resp.status == 200
        assert profile_app.calls == 1
        assert (await prof_resp.json())["profile"]["commander_level"] == 310

        # 单人突袭五队编组（账号池）
        sr_resp = await client.post(
            "/workspace/api/solo-raid/build",
            json={"source": "account", "save": True},
            cookies={WORKSPACE_COOKIE: cookie},
            headers={"Origin": SITE_ORIGIN, WORKSPACE_CSRF_HEADER: csrf},
        )
        assert sr_resp.status == 200
        sr_json = await sr_resp.json()
        assert len(sr_json["plan"]["teams"]) == 5
        assert toolbox.solo_plans.load("1008611") is not None

        # 竞技场独立编辑器跳转链接
        arena_resp = await client.post(
            "/workspace/api/arena/open",
            json={"mode": "three"},
            cookies={WORKSPACE_COOKIE: cookie},
            headers={"Origin": SITE_ORIGIN, WORKSPACE_CSRF_HEADER: csrf},
        )
        assert arena_resp.status == 200
        assert "/arena/open/fake_1008611_three" in (await arena_resp.json())["url"]

        # 同步器账号上下文懒加载 + 资源箱/前哨计算 + 超限预设对比 + 单人突袭手选弱点
        sync_ctx = await client.post(
            "/workspace/api/sync/context",
            cookies={WORKSPACE_COOKIE: cookie},
            headers={"Origin": SITE_ORIGIN, WORKSPACE_CSRF_HEADER: csrf},
        )
        assert sync_ctx.status == 200
        ctx_json = await sync_ctx.json()
        assert ctx_json["bound"] is True
        assert ctx_json["synchro_level"] == 574
        assert ctx_json["outpost_level"] == 651
        assert ctx_json["estimated_above_400"] is False

        sync_calc = await client.post(
            "/workspace/api/tools/sync",
            json={
                "current": 574,
                "target": 580,
                "outpost_level": 651,
                "wipeout_count": 1,
                "inventory": ctx_json["inventory"],
                "cases": {
                    "core_dust": {"24h": 5},
                    "credits": {"24h": 2},
                    "battle_data": {"24h": 5},
                },
                "extra_daily": {"core_dust": 500},
            },
            cookies={WORKSPACE_COOKIE: cookie},
            headers={"Origin": SITE_ORIGIN, WORKSPACE_CSRF_HEADER: csrf},
        )
        assert sync_calc.status == 200
        sync_json = await sync_calc.json()
        assert sync_json["plan"]["outpost_level"] == 651
        assert sync_json["plan"]["case_yields"]["core_dust"] > 0
        assert sync_json["plan"]["gainable_levels"] >= 1

        ol_resp = await client.post(
            "/workspace/api/tools/overload",
            json={"character_query": "红莲", "preset": "通用输出", "simulate": True},
            cookies={WORKSPACE_COOKIE: cookie},
            headers={"Origin": SITE_ORIGIN, WORKSPACE_CSRF_HEADER: csrf},
        )
        assert ol_resp.status == 200
        ol_json = await ol_resp.json()
        assert "内置通用定位预设" in ol_json["text"]
        assert "防御力增加" in ol_json["text"]

        ol_auto = await client.post(
            "/workspace/api/tools/overload",
            json={"character_query": "alice", "preset": "auto", "simulate": False},
            cookies={WORKSPACE_COOKIE: cookie},
            headers={"Origin": SITE_ORIGIN, WORKSPACE_CSRF_HEADER: csrf},
        )
        assert ol_auto.status == 200
        assert "角色专属推荐" in (await ol_auto.json())["text"]

        sr_ctx = await (
            await client.get("/workspace/api/solo-raid/context", cookies={WORKSPACE_COOKIE: cookie})
        ).json()
        assert sr_ctx["latest"]["bosses"][0]["weakness"] == "Fire"

        # 全部 30 项功能目录的 web_tab 与实际页面完全对齐，无悬空标签页
        import re as _re
        from astrbot_plugin_nikke.features.catalog.registry import FEATURES
        root = Path(__file__).resolve().parents[1] / "templates"
        hall_tabs = set(_re.findall(r'id="tab-([a-z0-9_-]+)"', (root / "hall_web" / "index.html").read_text(encoding="utf-8")))
        ws_tabs = set(_re.findall(r'id="tab-([a-z0-9_-]+)"', (root / "workspace_web" / "index.html").read_text(encoding="utf-8")))
        for f in FEATURES:
            if f.entry_mode in ("hall", "both") and not f.requires_binding:
                assert f.web_tab in hall_tabs, f.id
            if f.entry_mode in ("workspace", "both"):
                assert f.web_tab in ws_tabs, f.id

        # 模板无内联 style 与动态 innerHTML
        root = Path(__file__).resolve().parents[1] / "templates"
        for asset in (
            root / "workspace_web" / "index.html",
            root / "workspace_web" / "workspace.js",
            root / "hall_web" / "index.html",
            root / "hall_web" / "hall.js",
        ):
            content = asset.read_text(encoding="utf-8")
            assert "style=" not in content
            assert ".innerHTML" not in content

        # 安全校验：错误 Origin 或缺少 CSRF 必须被拒绝
        bad_origin = await client.post(
            "/workspace/api/profile/load",
            cookies={WORKSPACE_COOKIE: cookie},
            headers={"Origin": "https://evil.example", WORKSPACE_CSRF_HEADER: csrf},
        )
        assert bad_origin.status == 403
        bad_csrf = await client.post(
            "/workspace/api/profile/load",
            cookies={WORKSPACE_COOKIE: cookie},
            headers={"Origin": SITE_ORIGIN, WORKSPACE_CSRF_HEADER: "invalid-csrf"},
        )
        assert bad_csrf.status == 403

        # 账号隔离：用户 B 的工作台会话不可读取用户 A 的 bind_status 或 solo_plans
        token_b = ws.create_link("2009999").rsplit("/", 1)[-1]
        claim_b = await client.post(
            "/workspace/api/claim",
            data={"token": token_b},
            headers={"Origin": SITE_ORIGIN, "Accept": "application/json"},
        )
        assert claim_b.status == 200
        cookie_b = claim_b.cookies[WORKSPACE_COOKIE].value
        boot_b = await (await client.get("/workspace/api/bootstrap", cookies={WORKSPACE_COOKIE: cookie_b})).json()
        assert boot_b["binding"]["bound"] is False
        cross_bind = await client.get(
            f"/workspace/api/bind/status?token={bind_data['token']}",
            cookies={WORKSPACE_COOKIE: cookie_b},
        )
        assert cross_bind.status == 404
        sr_ctx_b = await (await client.get("/workspace/api/solo-raid/context", cookies={WORKSPACE_COOKIE: cookie_b})).json()
        assert sr_ctx_b["saved_plan"] is None


@pytest.mark.asyncio
async def test_workspace_share_preview_redacts_pii_and_blocks_unknown_retry(tmp_path: Path) -> None:
    sent: list[tuple[str, str]] = []
    mode = ["sent"]

    async def fake_send(target: str, text: str, _images):
        sent.append((target, text))
        return mode[0]

    ws, app, _store, _p, _t = _make_workspace(tmp_path, send_fn=fake_send)
    token = ws.create_link("1008611", conversation_id="aiocqhttp:GroupMessage:555666", group_label="测试群").rsplit("/", 1)[-1]

    async with TestClient(TestServer(app)) as client:
        claim = await client.post(
            "/workspace/api/claim",
            data={"token": token},
            headers={"Origin": SITE_ORIGIN, "Accept": "application/json"},
        )
        cookie = claim.cookies[WORKSPACE_COOKIE].value
        csrf = (await (await client.get("/workspace/api/bootstrap", cookies={WORKSPACE_COOKIE: cookie})).json())["csrf"]

        prev = await client.post(
            "/workspace/api/share/preview",
            json={
                "kind": "profile",
                "text": "我的进度：UID 1234567890 openid_99999999 game_token=abc 战力 550000",
            },
            cookies={WORKSPACE_COOKIE: cookie},
            headers={"Origin": SITE_ORIGIN, WORKSPACE_CSRF_HEADER: csrf},
        )
        assert prev.status == 200
        prev_json = await prev.json()
        assert "1234567890" not in prev_json["preview_text"]
        assert "openid_99999999" not in prev_json["preview_text"]
        assert "game_token=abc" not in prev_json["preview_text"]
        assert "测试群" in prev_json["target_label"]

        conf = await client.post(
            "/workspace/api/share/confirm",
            json={"confirm_token": prev_json["confirm_token"], "idempotency_key": "share_ok_1"},
            cookies={WORKSPACE_COOKIE: cookie},
            headers={"Origin": SITE_ORIGIN, WORKSPACE_CSRF_HEADER: csrf},
        )
        assert conf.status == 200
        assert (await conf.json())["delivery_status"] == "sent"
        assert "1234567890" not in sent[0][1]

        # 二次确认同一 confirm_token 失败
        prev2 = await client.post(
            "/workspace/api/share/preview",
            json={"kind": "profile", "text": "再次分享测试"},
            cookies={WORKSPACE_COOKIE: cookie},
            headers={"Origin": SITE_ORIGIN, WORKSPACE_CSRF_HEADER: csrf},
        )
        t2 = (await prev2.json())["confirm_token"]
        mode[0] = "unknown"
        conf_u = await client.post(
            "/workspace/api/share/confirm",
            json={"confirm_token": t2, "idempotency_key": "share_unknown_1"},
            cookies={WORKSPACE_COOKIE: cookie},
            headers={"Origin": SITE_ORIGIN, WORKSPACE_CSRF_HEADER: csrf},
        )
        assert conf_u.status == 502
        assert (await conf_u.json())["delivery_status"] == "unknown"

        # 相同幂等键禁止重发
        conf_u2 = await client.post(
            "/workspace/api/share/confirm",
            json={"confirm_token": t2, "idempotency_key": "share_unknown_1"},
            cookies={WORKSPACE_COOKIE: cookie},
            headers={"Origin": SITE_ORIGIN, WORKSPACE_CSRF_HEADER: csrf},
        )
        assert conf_u2.status == 409
        assert (await conf_u2.json())["code"] == "DELIVERY_UNKNOWN"
        assert len(sent) == 2


@pytest.mark.asyncio
async def test_portal_qq_commands_and_pure_mention_detection() -> None:
    links = SimpleNamespace(
        public_base_url=SITE_ORIGIN,
        hall_public_url=lambda: f"{SITE_ORIGIN}/hall",
        create_hall_group_url=lambda a, c, group_label="": f"{SITE_ORIGIN}/hall/open/group_{a}",
        create_workspace_url=lambda a, conversation_id="", group_label="": f"{SITE_ORIGIN}/workspace/open/ws_{a}",
    )
    handler = PortalCommandHandler(portal_links=links, public_base_url=SITE_ORIGIN, allow_group_workspace=False)

    # 群聊 /妮姬 大厅 返回带群聊反馈的引导链接
    hall_res = await handler.handle(
        CommandContext("aiocqhttp", "u1", False, False, "group:123456", {"mode": "hall"})
    )
    assert "/hall/open/group_u1" in hall_res.messages[0].text

    # 群聊 /妮姬 工作台 默认引导至私聊
    ws_group = await handler.handle(
        CommandContext("aiocqhttp", "u1", False, False, "group:123456", {"mode": "workspace"})
    )
    assert "私聊机器人" in ws_group.messages[0].text
    assert "/workspace/open/" not in ws_group.messages[0].text

    # 私聊 /妮姬 工作台 返回一次性工作台链接
    ws_dm = await handler.handle(
        CommandContext("aiocqhttp", "u1", False, True, "private:u1", {"mode": "workspace"})
    )
    assert "/workspace/open/ws_u1" in ws_dm.messages[0].text

    # 纯 @机器人 识别：无正文触发，有正文或戳一戳 notice 不触发
    adapter = AstrBotCommandAdapter()
    pure_event = SimpleNamespace(
        message_str="   ",
        is_at_or_wake_command=True,
        message_obj=SimpleNamespace(raw_message={"post_type": "message"}),
    )
    text_event = SimpleNamespace(
        message_str="日程",
        is_at_or_wake_command=True,
        message_obj=SimpleNamespace(raw_message={"post_type": "message"}),
    )
    notice_event = SimpleNamespace(
        message_str="",
        is_at_or_wake_command=False,
        message_obj=SimpleNamespace(raw_message={"post_type": "notice"}),
    )
    assert adapter.is_pure_bot_mention(pure_event) is True
    assert adapter.is_pure_bot_mention(text_event) is False
    assert adapter.is_pure_bot_mention(notice_event) is False

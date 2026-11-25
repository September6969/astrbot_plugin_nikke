# SPDX-License-Identifier: GPL-3.0-or-later
"""公共功能大厅（Phase 4）：匿名隔离、群上下文领取、日程/塔罗群聊反馈闭环测试。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from astrbot_plugin_nikke.features.calendar.canonical_models import QueryContext
from astrbot_plugin_nikke.features.calendar.application import CalendarScheduleSnapshot
from astrbot_plugin_nikke.features.tarot.service import TarotService
from astrbot_plugin_nikke.features.web_portal import PortalSessionStore
from astrbot_plugin_nikke.integrations.web.hall_service import (
    HALL_COOKIE,
    HALL_CSRF_HEADER,
    HallWebService,
)
from astrbot_plugin_nikke.integrations.web.portal_bridge import PortalHostBridge

SITE_ORIGIN = "https://nikke.irises777.xyz"
CST = timezone(timedelta(hours=8))


def _seed_tarot_deck(plugin_root: Path) -> None:
    tarot_dir = plugin_root / "assets" / "tarot"
    tarot_dir.mkdir(parents=True, exist_ok=True)
    cards = []
    for i in range(22):
        img = tarot_dir / f"major_{i:02d}.png"
        img.write_bytes(b"fake-png")
        cards.append(
            {
                "id": i,
                "key": f"major_{i:02d}",
                "arcana": "major",
                "roman": str(i),
                "name_zh": f"大阿卡那{i}",
                "name_en": f"Major {i}",
                "character": f"妮姬{i}",
                "image": f"major_{i:02d}.png",
                "upright": {"keywords": ["希望", "前行"], "meaning": "正位顺遂", "advice": "稳步推进"},
                "reversed": {"keywords": ["审慎", "停顿"], "meaning": "逆位留意", "advice": "稍作调整"},
            }
        )
    (tarot_dir / "tarot_cards.json").write_text(
        json.dumps({"cards": cards}, ensure_ascii=False), encoding="utf-8"
    )


class _FakeCalendarApp:
    def query_schedule(self, horizon="14"):
        days = int(str(horizon or "14"))
        now = datetime(2026, 11, 25, 12, 0, tzinfo=CST)
        ctx = QueryContext(
            now=now,
            snapshot_version="v1",
            events=(),
            source_health={},
            freshness="FRESH",
            coverage="FULL",
            health_display="OK",
            source_display="LOCAL",
        )
        return CalendarScheduleSnapshot(
            context=ctx,
            horizon_days=days,
            has_snapshot=True,
            activity_count=1,
            data_quality="FULL",
            last_updated_at="2026-11-25 12:00",
            sync_warning="",
            fallback_text=f"未来 {days} 天：示例活动 进行中",
        )


def _make_hall_service(tmp_path: Path, *, send_fn=None, render_fn=None):
    sessions = PortalSessionStore()
    bridge = PortalHostBridge(
        send_to_qq=send_fn,
        render_t2i=render_fn,
        build_calendar_payload=lambda snap: {
            "pages": [
                {
                    "active_items": [
                        {
                            "full_title": "周年限定卡池",
                            "time_range": "11-20 ~ 12-05",
                            "remaining": "剩余 10 天",
                        }
                    ],
                    "next_items": [],
                }
            ],
            "fallback_text": snap.fallback_text,
        },
    )
    plugin_root = tmp_path / "plugin"
    _seed_tarot_deck(plugin_root)
    tarot_svc = TarotService(plugin_root, tmp_path / "tarot", deck_mode="major")
    hall = HallWebService(
        site_origin=SITE_ORIGIN,
        sessions=sessions,
        bridge=bridge,
        feature_flags={"enable_arena": True},
        calendar=_FakeCalendarApp(),
        tarot=tarot_svc,
    )
    app = web.Application()
    hall.mount(app)
    return hall, app


@pytest.mark.asyncio
async def test_hall_public_access_has_zero_personal_data_and_strict_csp(tmp_path: Path) -> None:
    _hall, app = _make_hall_service(tmp_path)
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/hall")
        assert resp.status == 200
        csp = resp.headers["Content-Security-Policy"]
        assert "frame-ancestors 'none'" in csp
        assert "style-src 'self'" in csp
        assert resp.headers["Cache-Control"] == "no-store"

        boot = await client.get("/hall/api/bootstrap")
        assert boot.status == 200
        payload = await boot.json()
        assert payload["surface"] == "hall"
        assert payload["group_context"]["active"] is False
        assert "binding" not in payload
        assert all(not f["requires_binding"] for f in payload["catalog"]["features"])

        cal = await client.get("/hall/api/calendar?horizon=14")
        assert cal.status == 200
        cal_data = await cal.json()
        assert cal_data["available"] is True
        assert cal_data["items"][0]["title"] == "周年限定卡池"


@pytest.mark.asyncio
async def test_hall_open_non_consuming_claim_and_e2e_calendar_tarot_feedback(
    tmp_path: Path,
) -> None:
    sent_messages: list[tuple[str, str, list[str]]] = []

    async def fake_send(target: str, text: str, images):
        sent_messages.append((target, text, list(images)))
        return "sent"

    async def fake_render(page: str, _payload):
        assert page == "calendar_schedule"
        img_file = tmp_path / "cal.png"
        img_file.write_bytes(b"png")
        return str(img_file)

    hall, app = _make_hall_service(tmp_path, send_fn=fake_send, render_fn=fake_render)
    link = hall.create_group_link("u1001", "aiocqhttp:GroupMessage:888999", "测试群")
    token = link.rsplit("/", 1)[-1]

    async with TestClient(TestServer(app)) as client:
        # GET /hall/open/{token} 不消费令牌
        open_resp1 = await client.get(f"/hall/open/{token}")
        open_resp2 = await client.get(f"/hall/open/{token}")
        assert open_resp1.status == 200 and open_resp2.status == 200

        # POST /hall/api/claim 兑换一次性上下文 Cookie
        claim_resp = await client.post(
            "/hall/api/claim",
            data={"token": token},
            headers={"Origin": SITE_ORIGIN, "Accept": "application/json"},
        )
        assert claim_resp.status == 200
        hall_cookie = claim_resp.cookies[HALL_COOKIE].value
        assert claim_resp.cookies[HALL_COOKIE]["httponly"]

        # 二次兑换同一令牌必须失败
        replay = await client.post(
            "/hall/api/claim",
            data={"token": token},
            headers={"Origin": SITE_ORIGIN, "Accept": "application/json"},
        )
        assert replay.status == 410

        boot = await client.get("/hall/api/bootstrap", cookies={HALL_COOKIE: hall_cookie})
        boot_json = await boot.json()
        csrf = boot_json["group_context"]["csrf"]
        assert boot_json["group_context"]["active"] is True

        # 错误 CSRF 必须拒绝
        bad_csrf = await client.post(
            "/hall/api/feedback/calendar",
            json={"horizon": 14, "idempotency_key": "cal_bad_csrf_1"},
            cookies={HALL_COOKIE: hall_cookie},
            headers={"Origin": SITE_ORIGIN, HALL_CSRF_HEADER: "wrong"},
        )
        assert bad_csrf.status == 403

        # 日程回推群聊端到端成功
        cal_fb = await client.post(
            "/hall/api/feedback/calendar",
            json={"horizon": 14, "idempotency_key": "cal_ok_key_01"},
            cookies={HALL_COOKIE: hall_cookie},
            headers={"Origin": SITE_ORIGIN, HALL_CSRF_HEADER: csrf},
        )
        assert cal_fb.status == 200
        assert (await cal_fb.json())["delivery_status"] == "sent"
        assert sent_messages[-1][0] == "aiocqhttp:GroupMessage:888999"
        assert len(sent_messages[-1][2]) == 1

        # 同幂等键去重不重发
        cal_dup = await client.post(
            "/hall/api/feedback/calendar",
            json={"horizon": 14, "idempotency_key": "cal_ok_key_01"},
            cookies={HALL_COOKIE: hall_cookie},
            headers={"Origin": SITE_ORIGIN, HALL_CSRF_HEADER: csrf},
        )
        assert cal_dup.status == 200
        assert (await cal_dup.json())["deduplicated"] is True
        assert len(sent_messages) == 1

        # 抽塔罗 + 回推群聊端到端成功
        draw = await client.post(
            "/hall/api/tarot",
            json={"mode": "single"},
            headers={"Origin": SITE_ORIGIN},
        )
        assert draw.status == 200
        draw_json = await draw.json()
        assert len(draw_json["cards"]) == 1

        tarot_fb = await client.post(
            "/hall/api/feedback/tarot",
            json={
                "mode": "single",
                "cards": draw_json["cards"],
                "idempotency_key": "tarot_ok_key_01",
            },
            cookies={HALL_COOKIE: hall_cookie},
            headers={"Origin": SITE_ORIGIN, HALL_CSRF_HEADER: csrf},
        )
        assert tarot_fb.status == 200
        assert (await tarot_fb.json())["delivery_status"] == "sent"
        assert len(sent_messages) == 2


@pytest.mark.asyncio
async def test_hall_feedback_blocks_retry_on_unknown_delivery(tmp_path: Path) -> None:
    calls = 0

    async def ambiguous_send(_target: str, _text: str, _images):
        nonlocal calls
        calls += 1
        return "unknown"

    hall, app = _make_hall_service(tmp_path, send_fn=ambiguous_send)
    token = hall.create_group_link("u1002", "aiocqhttp:GroupMessage:111222", "群B").rsplit("/", 1)[-1]

    async with TestClient(TestServer(app)) as client:
        claim = await client.post(
            "/hall/api/claim",
            data={"token": token},
            headers={"Origin": SITE_ORIGIN, "Accept": "application/json"},
        )
        cookie = claim.cookies[HALL_COOKIE].value
        csrf = (await (await client.get("/hall/api/bootstrap", cookies={HALL_COOKIE: cookie})).json())["group_context"]["csrf"]

        first = await client.post(
            "/hall/api/feedback/tarot",
            json={"mode": "single", "idempotency_key": "tarot_unknown_1"},
            cookies={HALL_COOKIE: cookie},
            headers={"Origin": SITE_ORIGIN, HALL_CSRF_HEADER: csrf},
        )
        assert first.status == 502
        assert (await first.json())["delivery_status"] == "unknown"

        # 同一幂等键绝不自动或再次重发
        second = await client.post(
            "/hall/api/feedback/tarot",
            json={"mode": "single", "idempotency_key": "tarot_unknown_1"},
            cookies={HALL_COOKIE: cookie},
            headers={"Origin": SITE_ORIGIN, HALL_CSRF_HEADER: csrf},
        )
        assert second.status == 409
        assert (await second.json())["code"] == "DELIVERY_UNKNOWN"
        assert calls == 1

"""以官方公开合同字段驱动 HTTP 模拟，不以点击响应替代任务进度。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest

from astrbot_plugin_nikke.core.storage import NikkeStore
from astrbot_plugin_nikke.features.daily.runner import DailyRunner
from astrbot_plugin_nikke.features.daily.actions import CommunityTaskService
from astrbot_plugin_nikke.integrations.blablalink.client import BlaBlaClient
from astrbot_plugin_nikke.integrations.blablalink.community_actions import CommunityActionsGateway
from test_session_renewal import bind


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed", [None, "list", "task", "liked", "rate", "captcha", "expired"])
async def test_full_http_flow_or_fail_closed_without_unrecognized_write(tmp_path, malformed):
    store = NikkeStore(tmp_path)
    account = bind(store)
    progress = {"browse": 0, "like": 0}
    writes = []
    paths = []
    def handle(request):
        paths.append(request.url.path)
        body = json.loads(request.content) if request.content else {}
        name = request.url.path.rsplit("/", 1)[-1]
        data = {}
        if name == "CheckLogin":
            if malformed == "expired": return httpx.Response(200, json={"code": 300001, "msg": "game not login"})
        elif name == "GetUserInfoNew": data = {"info": {"intl_openid": "synthetic-openid"}}
        elif name == "GetTaskListWithStatusV2":
            assert request.method == "GET" and request.url.params["get_top"] == "false"
            data = {"tasks": [{"task_id": str(72 + i), "task_type": 13 + i, "cyclical_type": 1, "periodicity_type": 1,
                "reward_infos": [{"need_completed_times": 1, "completed_times": progress[k], "is_completed": progress[k] == 1}]}
                for i, k in enumerate(progress)]}
            if malformed == "task": data["tasks"] = []
        elif name == "GetPlateList": data = {"list": [{"id": 46, "unique_identifier": "recommend"}]}
        elif name == "GetPostListNew":
            assert body["plate_id"] == 46 and body["limit"] == "10"
            data = {"list": [{"post_uuid": "synthetic-post", "my_upvote": {"is_star": False}}]}
            if malformed == "list": data = {"renamed": []}
        elif name == "GetPost":
            assert body["original_content"] == 0
            data = {"post_uuid": "synthetic-post", "my_upvote": {"is_star": False}}
            if body["browse_post"] == 1:
                assert store.list_runs(action="community_action")[-1]["status"] == "DISPATCH_INTENT"
                writes.append("browse")
                if malformed in {"rate", "captcha"}:
                    return httpx.Response(429 if malformed == "rate" else 403, json={"code": 429})
                progress["browse"] += 1
            else:
                assert body["browse_post"] == 2
                if malformed == "liked": data["my_upvote"]["is_star"] = True
        elif name == "PostStar":
            assert body == {"post_uuid": "synthetic-post", "type": 1, "like_type": 1}
            writes.append("like")
            progress["like"] += 1
        else: raise AssertionError(name)
        return httpx.Response(200, json={"code": 0, "msg": "ok", "data": data})
    client = BlaBlaClient(transport=httpx.MockTransport(handle), account_reader=store)
    gateway = CommunityActionsGateway(client, clock=lambda: datetime(2026, 10, 22, 12, tzinfo=timezone.utc))
    service = CommunityTaskService(gateway=gateway, store=store, config={"enable_daily_actions": True},
        account_lock=DailyRunner(store=store)._account_lock, sleep=AsyncMock(), clock=gateway.clock)
    try:
        result = await service.execute(account)
        if malformed is None:
            assert result.status == "completed" and writes == ["browse", "like"]
        elif malformed == "liked":
            assert result.status == "incomplete" and writes == ["browse"]
        elif malformed in {"rate", "captcha"}:
            assert writes == ["browse"] and result.status == "unknown_after_action"
            assert paths[-1].endswith("GetPost")
        else:
            assert not writes and result.status != "completed"
        assert not any(any(w in p for w in ("Collection", "Follow", "Comment", "CreatePost", "DailyCheckIn")) for p in paths)
    finally:
        await client.aclose()

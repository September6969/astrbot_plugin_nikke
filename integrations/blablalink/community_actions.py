"""当前官方 UGC 社区任务适配；证据见 COMMUNITY_ACTIONS_AND_RENEWAL.md。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import re

from ...features.daily.action_models import PostCandidate, TaskProgress
from .errors import BlaBlaError


DIRECT = "/api/ugc/direct/standalonesite/Dynamics/"
PROXY = "/api/ugc/proxy/standalonesite/Dynamics/"
# 任务身份来自官方匿名目录，不根据翻译名称或列表位置猜测。
TASKS = {"browse": (13, "72"), "like": (14, "73")}
POST_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def parse_progress(tasks: list[dict[str, Any]], period: str) -> dict[str, TaskProgress | None]:
    result = {}
    for kind, (task_type, task_id) in TASKS.items():
        matches = [t for t in tasks if t.get("task_type") == task_type]
        result[kind] = None
        if len(matches) != 1:
            continue
        item = matches[0]
        rewards = item.get("reward_infos")
        if (item.get("task_id") != task_id or type(item.get("task_type")) is not int
                or type(item.get("cyclical_type")) is not int or item["cyclical_type"] != 1
                or type(item.get("periodicity_type")) is not int or item["periodicity_type"] != 1
                or not isinstance(rewards, list) or len(rewards) != 1 or not isinstance(rewards[0], dict)):
            continue
        reward = rewards[0]
        target, current, completed = (reward.get(k) for k in ("need_completed_times", "completed_times", "is_completed"))
        if (type(target) is not int or type(current) is not int or type(completed) is not bool
                or target <= 0 or current < 0 or current > target or completed != (current == target)):
            continue
        result[kind] = TaskProgress(kind, task_id, period, target, current, completed)
    return result


def parse_post(item: Any) -> PostCandidate:
    if not isinstance(item, dict) or not isinstance(item.get("post_uuid"), str) or not POST_ID.fullmatch(item["post_uuid"]):
        raise BlaBlaError("帖子身份结构变化，未提交动作")
    upvote = item.get("my_upvote")
    liked = upvote.get("is_star") if isinstance(upvote, dict) else None
    return PostCandidate(item["post_uuid"], liked if type(liked) is bool else None)


class CommunityActionsGateway:
    def __init__(self, client, *, clock=None):
        self.client = client
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def _request(self, account, endpoint, payload):
        data = await self.client._community_request("POST", endpoint, account, payload=payload)
        if type(data.get("code")) is not int or data["code"] != 0 or not isinstance(data.get("data"), dict):
            raise BlaBlaError("社区响应合同变化，已停止")
        return data["data"]

    async def identity(self, account) -> str:
        # CheckLogin 只验证登录；稳定社区身份必须由 UserInfo 响应再次确认。
        response = await self.client._community_request("POST", "/api/user/CheckLogin", account, payload={})
        if type(response.get("code")) is not int or response["code"] != 0:
            raise BlaBlaError("登录检查状态不明确")
        data = await self._request(account, "/api/ugc/proxy/standalonesite/User/GetUserInfoNew", {})
        identity = (data.get("info") or {}).get("intl_openid")
        if not isinstance(identity, str) or not identity or identity != str(account.get("game_openid") or ""):
            raise BlaBlaError("社区身份无法与绑定账号一致核对")
        return identity

    async def progress(self, account):
        before = self.clock().astimezone(timezone.utc).date().isoformat()
        _, game_id = self.client._community_context(account)
        response = await self.client._community_request("GET", "/api/lip/proxy/lipass/Points/GetTaskListWithStatusV2",
            account, params={"get_top": "false", "intl_game_id": game_id})
        data = response.get("data")
        if (type(response.get("code")) is not int or response["code"] != 0 or not isinstance(data, dict)
                or not isinstance(data.get("tasks"), list) or any(not isinstance(t, dict) for t in data["tasks"])):
            raise BlaBlaError("社区任务列表响应合同变化")
        tasks = data["tasks"]
        after = self.clock().astimezone(timezone.utc).date().isoformat()
        if after != before:
            raise BlaBlaError("查询跨越官方 UTC 刷新边界，请稍后查询")
        return parse_progress(tasks, "community-utc:" + before)

    async def candidates(self, account):
        plates = await self._request(account, DIRECT + "GetPlateList", {"page_type": 0, "limit": 10})
        items = plates.get("list")
        if not isinstance(items, list) or any(not isinstance(i, dict) for i in items):
            raise BlaBlaError("社区分区结构变化")
        matches = [p for p in items if p.get("unique_identifier") == "recommend"]
        if len(matches) != 1 or type(matches[0].get("id")) is not int:
            raise BlaBlaError("社区推荐分区未确认")
        data = await self._request(account, DIRECT + "GetPostListNew", {
            "search_type": 0, "plate_id": matches[0]["id"], "plate_unique_id": "recommend",
            "nextPageCursor": "", "order_by": 2, "limit": "10",
        })
        items = data.get("list")
        if not isinstance(items, list):
            raise BlaBlaError("帖子列表结构变化")
        posts = [parse_post(item) for item in items]
        # 只取有限首批候选；重复项不增加预算，候选不足留待用户查看。
        return list({post.post_id: post for post in reversed(posts)}.values())[::-1]

    async def liked(self, account, post_id):
        self._check_id(post_id)
        data = await self._request(account, DIRECT + "GetPost", {
            "post_uuid": post_id, "browse_post": 2, "original_content": 0})
        post = parse_post(data)
        if post.post_id != post_id:
            raise BlaBlaError("帖子响应身份不一致")
        return post.liked

    async def dispatch(self, account, kind, post_id):
        self._check_id(post_id)
        if kind == "browse":
            await self._request(account, DIRECT + "GetPost", {
                "post_uuid": post_id, "browse_post": 1, "original_content": 0})
        elif kind == "like":
            response = await self.client._community_request("POST", PROXY + "PostStar", account,
                payload={"post_uuid": post_id, "type": 1, "like_type": 1})
            if type(response.get("code")) is not int or response["code"] != 0:
                raise BlaBlaError("点赞提交响应未知")
        else:
            raise ValueError("未支持的社区动作")

    @staticmethod
    def _check_id(post_id):
        if not isinstance(post_id, str) or not POST_ID.fullmatch(post_id):
            raise ValueError("帖子身份非法")

# SPDX-License-Identifier: GPL-3.0-or-later
"""BlaBlaLink 官方公告只读 HTTP 适配器。"""

from __future__ import annotations

import logging

import httpx

from astrbot_plugin_nikke.features.announcement.models import AnnouncementRecord

logger = logging.getLogger("nikke.announcements")


async def fetch_official_announcements() -> list[AnnouncementRecord]:
    """读取并校验旧官方公告接口，供主来源失败时受控回退。"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            "https://api.blablalink.com/api/ugc/direct/standalonesite/User/GetAnnouncements"
        )
        response.raise_for_status()
        data = response.json()
        code = data.get("code")
        if code not in (0, "0") or data.get("code_type") == 1:
            message = data.get("msg") or f"状态码 {code}"
            raise RuntimeError(f"官方公告接口返回业务错误: {message} (code={code})")
        payload = data.get("data")
        if not isinstance(payload, dict):
            raise RuntimeError("官方公告数据结构缺失或非字典对象")
        if "list" not in payload:
            raise RuntimeError("官方公告数据缺失 list 字段")
        items = payload["list"]
        if not isinstance(items, list):
            raise RuntimeError("官方公告 list 字段非列表格式")

        records: list[AnnouncementRecord] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            content_id = item.get("content_id") or item.get("id")
            if (
                not isinstance(content_id, (str, int))
                or isinstance(content_id, bool)
                or not str(content_id).strip()
            ):
                logger.warning("跳过缺少稳定 ID 的公告")
                continue
            records.append(
                AnnouncementRecord(
                    content_id=str(content_id),
                    title=str(item.get("title", "")),
                    body=str(item.get("content", "") or item.get("body", "")),
                    published_at=str(item.get("publish_time", "")),
                    source_url=str(item.get("url", "")),
                    locale="und",
                )
            )
    return records

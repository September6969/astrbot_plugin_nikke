"""官网 InformationFeeds 只读适配器，合同及采样来源见 docs/evidence/overnight.md。"""
import asyncio
from datetime import datetime, timezone
from html.parser import HTMLParser
import httpx
from .announcement_models import AnnouncementRecord

BASE = "https://na-community.playerinfinite.com/api/gpts.information_feeds_svr.InformationFeedsSvr/"
HOSTS = {"en": "nikke-en.com", "ja": "nikke-jp.com", "ko": "nikke-kr.com", "th": "nikke-sea.com", "de": "nikke-de.com", "fr": "nikke-fr.com"}


class PlainBody(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"br", "p", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


class InformationFeedsSource:
    def __init__(self, locale="en", *, max_pages=2, page_size=5, transport=None):
        if locale not in {"en", "ja", "ko", "th", "de", "fr"}:
            raise ValueError("官网尚未验证此语言")
        if not 1 <= max_pages <= 5 or not 1 <= page_size <= 20:
            raise ValueError("公告扫描范围超限")
        self.locale, self.max_pages, self.page_size = locale, max_pages, page_size
        self.transport = transport

    async def fetch(self):
        headers = {"X-GameId": "16", "X-AreaId": "na", "X-Source": "pc_web", "X-Language": self.locale}
        async with httpx.AsyncClient(headers=headers, timeout=10, transport=self.transport) as client:
            async def post(name, payload):
                response = await client.post(BASE + name, json=payload)
                response.raise_for_status()
                result = response.json()
                if not isinstance(result, dict) or result.get("code") != 0:
                    raise ValueError("CMS 请求失败")
                data = result.get("data")
                if not isinstance(data, dict) or data.get("result") != 0:
                    raise ValueError("CMS 业务响应失败")
                return data
            columns = await post("GetLabelList", {})
            news = next((x for x in columns.get("primary_label_list", []) if isinstance(x, dict) and x.get("raw_label_name") == "official_news"), None)
            if not news:
                raise ValueError("CMS 官方新闻栏目不存在")
            offset, seen, items = 0, set(), []
            for _ in range(self.max_pages):
                page = await post("GetContentByLabel", {
                    "language": [self.locale], "gameid": "16", "offset": offset, "get_num": self.page_size,
                    "ext_info_type_list": [0, 1, 2], "primary_label_id": news["label_id"],
                    "secondary_label_id": news["default_secondary_label_id"], "content_class": 0,
                })
                rows = page.get("info_content")
                if not isinstance(rows, list):
                    raise ValueError("CMS 公告列表格式无效")
                for row in rows:
                    if not isinstance(row, dict) or not row.get("content_id"):
                        raise ValueError("CMS 公告缺少 ID")
                    identifier = str(row["content_id"])
                    if identifier not in seen:
                        seen.add(identifier)
                        items.append(identifier)
                next_offset = page.get("next_offset")
                if not rows or page.get("is_finish") or not isinstance(next_offset, int) or next_offset <= offset or next_offset >= page.get("total_num", next_offset + 1):
                    break
                offset = next_offset
            limit = asyncio.Semaphore(3)
            async def detail(identifier):
                async with limit:
                    data = await post("GetContentInfoById", {"content_id": identifier})
                if str(data.get("content_id")) != identifier or not isinstance(data.get("content"), str):
                    raise ValueError("CMS 公告全文格式无效")
                body = PlainBody()
                body.feed(data["content"])
                return AnnouncementRecord(
                    f"informationfeeds:{self.locale}:{identifier}", str(data.get("title", "")),
                    "".join(body.parts), datetime.fromtimestamp(int(data["pub_timestamp"]), timezone.utc).isoformat(),
                    source_url=f"https://{HOSTS[self.locale]}/newsdetail.html?content_id={identifier}",
                )
            return await asyncio.gather(*(detail(identifier) for identifier in items))

"""官网 InformationFeeds 只读适配器，合同及采样来源见 docs/evidence/overnight.md。"""
import asyncio
from datetime import datetime, timezone
from html.parser import HTMLParser
import httpx
from .announcement_models import AnnouncementRecord

BASE = "https://na-community.playerinfinite.com/api/gpts.information_feeds_svr.InformationFeedsSvr/"
HOSTS = {"en": "nikke-en.com", "ja": "nikke-jp.com", "ko": "nikke-kr.com", "th": "nikke-sea.com", "de": "nikke-de.com", "fr": "nikke-fr.com"}
SUPPORTED_LOCALES = frozenset(HOSTS)


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
    @staticmethod
    def _timestamp(value):
        """CMS 实际结构允许非负整数及规范十进制字符串，拒绝布尔和隐式截断。"""
        if type(value) is int:
            return value if value >= 0 else None
        if isinstance(value, str):
            normalized = value.strip()
            if normalized and normalized.isascii() and normalized.isdecimal():
                return int(normalized)
        return None

    def __init__(self, locale="en", *, max_pages=2, page_size=5, transport=None):
        if locale not in SUPPORTED_LOCALES:
            raise ValueError("官网尚未验证此语言")
        if type(max_pages) is not int or type(page_size) is not int or not 1 <= max_pages <= 5 or not 1 <= page_size <= 20:
            raise ValueError("公告扫描范围超限")
        self.locale, self.max_pages, self.page_size = locale, max_pages, page_size
        self.transport = transport
        self.last_scan = None

    async def fetch(self):
        headers = {"X-GameId": "16", "X-AreaId": "na", "X-Source": "pc_web", "X-Language": self.locale}
        async with httpx.AsyncClient(headers=headers, timeout=10, transport=self.transport) as client:
            async def post(name, payload):
                response = await client.post(BASE + name, json=payload)
                response.raise_for_status()
                result = response.json()
                if not isinstance(result, dict) or type(result.get("code")) is not int or result["code"] != 0:
                    raise ValueError("CMS 请求失败")
                data = result.get("data")
                if not isinstance(data, dict) or type(data.get("result")) is not int or data["result"] != 0:
                    raise ValueError("CMS 业务响应失败")
                return data
            columns = await post("GetLabelList", {})
            news = next((x for x in columns.get("primary_label_list", []) if isinstance(x, dict) and x.get("raw_label_name") == "official_news"), None)
            if not news:
                raise ValueError("CMS 官方新闻栏目不存在")

            target_secondary_ids: list[Any] = []
            for sec in news.get("secondary_label_list", []):
                if isinstance(sec, dict) and sec.get("raw_label_name") in {"NEWS", "NOTICE"}:
                    sid = sec.get("label_id")
                    if sid is not None and sid not in target_secondary_ids:
                        target_secondary_ids.append(sid)
            if not target_secondary_ids:
                default_sid = news.get("default_secondary_label_id")
                if default_sid is not None and not isinstance(default_sid, bool):
                    target_secondary_ids.append(default_sid)

            seen, items, pages_scanned = set(), [], 0
            finished = False
            for sec_id in target_secondary_ids:
                offset = 0
                for _ in range(self.max_pages):
                    page = await post("GetContentByLabel", {
                        "language": [self.locale], "gameid": "16", "offset": offset, "get_num": self.page_size,
                        "ext_info_type_list": [0, 1, 2], "primary_label_id": news["label_id"],
                        "secondary_label_id": sec_id, "content_class": 0,
                    })
                    rows = page.get("info_content")
                    if not isinstance(rows, list):
                        raise ValueError("CMS 公告列表格式无效")
                    pages_scanned += 1
                    for row in rows:
                        if not isinstance(row, dict) or type(row.get("content_id")) not in {str, int} or not str(row["content_id"]).strip():
                            raise ValueError("CMS 公告缺少 ID")
                        identifier = str(row["content_id"]).strip()
                        if identifier not in seen:
                            seen.add(identifier)
                            items.append(identifier)
                    next_offset = page.get("next_offset")
                    total_num = page.get("total_num")
                    if not rows or page.get("is_finish") is True or type(next_offset) is not int or type(total_num) is not int or next_offset <= offset or next_offset >= total_num:
                        finished = True
                        break
                    offset = next_offset
            limit = asyncio.Semaphore(3)
            async def detail(identifier):
                async with limit:
                    data = await post("GetContentInfoById", {"content_id": identifier})
                if type(data.get("content_id")) not in {str, int} or str(data["content_id"]).strip() != identifier or not isinstance(data.get("content"), str):
                    raise ValueError("CMS 公告全文格式无效")
                title = data.get("title")
                timestamp = self._timestamp(data.get("pub_timestamp"))
                if not isinstance(title, str) or not title.strip() or timestamp is None:
                    raise ValueError("CMS 公告元数据格式无效")
                body = PlainBody()
                body.feed(data["content"])
                try:
                    published_at = datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
                except (OverflowError, OSError, ValueError) as exc:
                    raise ValueError("CMS 公告发布时间无效") from exc
                return AnnouncementRecord(
                    f"informationfeeds:{self.locale}:{identifier}", title.strip(),
                    "".join(body.parts), published_at,
                    source_url=f"https://{HOSTS[self.locale]}/newsdetail.html?content_id={identifier}",
                    locale=self.locale,
                )
            records = await asyncio.gather(*(detail(identifier) for identifier in items))
            self.last_scan = {
                "pages_scanned": pages_scanned,
                "requested_pages": self.max_pages,
                "page_size": self.page_size,
                "finished": finished,
                "unique_records": len(records),
            }
            return records

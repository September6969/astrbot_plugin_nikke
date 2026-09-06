"""以真实公开响应的结构构造离线样例，不复制公告正文。"""
import json
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
import httpx
from astrbot_plugin_nikke.announcement_sources import InformationFeedsSource


class InformationFeedsTests(IsolatedAsyncioTestCase):
    async def test_public_shape_fixture_and_language_link(self):
        root = Path(__file__).parent / "fixtures/informationfeeds"
        names = {"GetLabelList": "labels.json", "GetContentByLabel": "list.json", "GetContentInfoById": "detail.json"}
        def handle(request):
            name = names[request.url.path.rsplit("/", 1)[-1]]
            return httpx.Response(200, json=json.loads((root / name).read_text(encoding="utf-8")))
        result = await InformationFeedsSource("ja", max_pages=1, transport=httpx.MockTransport(handle)).fetch()
        self.assertEqual(result[0].body, "\nFixture body")
        self.assertTrue(result[0].source_url.startswith("https://nikke-jp.com/"))

    async def test_locale_pagination_detail(self):
        offsets = []
        def handle(request):
            self.assertNotIn("cookie", request.headers)
            self.assertEqual(request.headers["X-Language"], "en")
            payload = json.loads(request.content)
            if request.url.path.endswith("GetLabelList"):
                data = {"primary_label_list": [{"raw_label_name": "official_news", "label_id": 309, "default_secondary_label_id": 496}]}
            elif request.url.path.endswith("GetContentByLabel"):
                offsets.append(payload["offset"])
                self.assertEqual(payload["language"], ["en"])
                data = {"info_content": [{"content_id": str(payload["offset"])}], "next_offset": payload["offset"]+1, "total_num": 2}
            else:
                data = {"content_id": payload["content_id"], "title": "测试", "content": "<p>截止至 2026-09-10 23:59 UTC</p><script>secret</script>", "pub_timestamp": "1788566400"}
            return httpx.Response(200, json={"code": 0, "data": dict(data, result=0)})
        result = await InformationFeedsSource(transport=httpx.MockTransport(handle), page_size=1).fetch()
        self.assertEqual(offsets, [0, 1])
        self.assertEqual(len(result), 2)
        self.assertNotIn("secret", result[0].body)
        self.assertTrue(result[0].content_id.startswith("informationfeeds:en:"))

    async def test_business_failure(self):
        source = InformationFeedsSource(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"code": 1})))
        with self.assertRaises(ValueError):
            await source.fetch()

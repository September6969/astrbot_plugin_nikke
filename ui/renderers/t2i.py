"""通过注入的 AstrBot 原生异步接口渲染，不拥有浏览器。"""
import asyncio

from astrbot_plugin_nikke.ui.t2i_assets import T2IAssetResolver
from astrbot_plugin_nikke.ui.payloads.campaign import CampaignT2IPayloadBuilder
from astrbot_plugin_nikke.ui.payloads.character import CharacterT2IPayloadBuilder
from astrbot_plugin_nikke.ui.payloads.profile import ProfileT2IPayloadBuilder
from astrbot_plugin_nikke.ui.payloads.raid_member import UnionMemberT2IPayloadBuilder
from astrbot_plugin_nikke.ui.payloads.raid_overview import UnionOverviewT2IPayloadBuilder
from astrbot_plugin_nikke.ui.payloads.raid_records import UnionRecordsT2IPayloadBuilder
from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader


class T2IRenderer:
    OPTIONS = {"type": "png", "quality": None, "full_page": True,
               "animations": "disabled", "caret": "hide", "scale": "css", "omit_background": False}

    def __init__(self, html_render, assets, timeout: float = 30):
        self._html_render = html_render
        self.timeout = timeout
        self.loader = T2ITemplateLoader()
        self.payload_builder = CampaignT2IPayloadBuilder(assets, T2IAssetResolver())

    async def render_campaign_history(self, record) -> str:
        payload = self.payload_builder.build(record)
        return await self.render_payload("campaign", payload)

    async def render_payload(self, page, payload) -> str:
        options = dict(self.OPTIONS)
        if isinstance(payload, dict) and "canvas" in payload and isinstance(payload["canvas"], dict):
            c_w = payload["canvas"].get("width")
            c_h = payload["canvas"].get("height")
            if c_w and c_h:
                options["viewport"] = {"width": int(c_w), "height": int(c_h)}
        result = await asyncio.wait_for(self._html_render(self.loader.load(page), payload,
                                                         options=options), self.timeout)
        if not isinstance(result, str) or not result.strip():
            raise ValueError("原生渲染器未返回图片")
        return result

    async def render_view(self, page, data, **kwargs):
        if page == "character":
            # 只在线程中准备既有本地资产；原生 HTML 渲染仍为直接异步调用。
            assets = await asyncio.to_thread(self.payload_builder.assets.resolve_character_assets, data)
            payload = CharacterT2IPayloadBuilder(self.payload_builder.resolver).build(data, assets)
            return await self.render_payload(page, payload)
        builders = {
            "profile": ProfileT2IPayloadBuilder(self.payload_builder.assets, self.payload_builder.resolver),
            "union_overview": UnionOverviewT2IPayloadBuilder(self.payload_builder.assets, self.payload_builder.resolver),
            "union_records": UnionRecordsT2IPayloadBuilder(),
            "union_member": UnionMemberT2IPayloadBuilder(self.payload_builder.assets, self.payload_builder.resolver),
        }
        if page in builders:
            data = builders[page].build(data, **kwargs)
        elif page == "calendar_schedule":
            pages = data.get("pages") if isinstance(data, dict) else None
            if pages and isinstance(pages, list):
                bundle_meta = {k: v for k, v in data.items() if k != "pages"}
                if len(pages) > 1:
                    results = []
                    for p in pages:
                        page_payload = {**bundle_meta, **p}
                        results.append(await self.render_payload(page, page_payload))
                    return results
                elif len(pages) == 1:
                    page_payload = {**bundle_meta, **pages[0]}
                    return await self.render_payload(page, page_payload)
            return await self.render_payload(page, data)
        else:
            raise ValueError("尚未支持该展示页面")
        return await self.render_payload(page, data)

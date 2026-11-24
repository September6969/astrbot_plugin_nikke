"""通过注入的 AstrBot 原生异步接口渲染，不拥有浏览器。"""
import asyncio
from typing import Any

from astrbot_plugin_nikke.ui.t2i_assets import T2IAssetResolver
from astrbot_plugin_nikke.ui.payloads.campaign import CampaignT2IPayloadBuilder
from astrbot_plugin_nikke.ui.payloads.character import CharacterT2IPayloadBuilder
from astrbot_plugin_nikke.ui.payloads.profile import ProfileT2IPayloadBuilder
from astrbot_plugin_nikke.ui.payloads.roster import RosterT2IPayloadBuilder
from astrbot_plugin_nikke.ui.payloads.raid_member import UnionMemberT2IPayloadBuilder
from astrbot_plugin_nikke.ui.payloads.raid_overview import UnionOverviewT2IPayloadBuilder
from astrbot_plugin_nikke.ui.payloads.raid_records import UnionRecordsT2IPayloadBuilder
from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader
from astrbot_plugin_nikke.ui.payloads.arena import ArenaT2IPayloadBuilder


class T2IRenderer:
    OPTIONS: dict[str, object] = {"type": "png", "quality": None, "full_page": True,
               "animations": "disabled", "caret": "hide", "scale": "css", "omit_background": False}
    # 这些页面的 builder 会做 Pillow 编解码，统一放进线程，避免阻塞事件循环（AUD-021）。
    _THREADED_BUILDERS = frozenset({"profile", "union_overview", "union_records", "union_member", "roster"})

    def __init__(self, html_render, assets, timeout: float = 30):
        self._html_render = html_render
        self.assets = assets
        self.timeout = timeout
        self.loader = T2ITemplateLoader()
        self.payload_builder = CampaignT2IPayloadBuilder(assets, T2IAssetResolver())
        self._builders: dict[str, Any] = {}

    def _builder(self, page: str) -> Any:
        """按页面懒加载并复用 builder，使其资产缓存跨请求生效。"""
        builder = self._builders.get(page)
        if builder is not None:
            return builder
        assets = self.payload_builder.assets
        resolver = self.payload_builder.resolver
        if page == "profile":
            builder = ProfileT2IPayloadBuilder(assets, resolver)
        elif page == "union_overview":
            builder = UnionOverviewT2IPayloadBuilder(assets, resolver)
        elif page == "union_records":
            builder = UnionRecordsT2IPayloadBuilder()
        elif page == "union_member":
            builder = UnionMemberT2IPayloadBuilder(assets, resolver)
        elif page == "roster":
            builder = RosterT2IPayloadBuilder(self.assets, resolver)
        elif page == "character":
            builder = CharacterT2IPayloadBuilder(
                resolver, identity_resolver=getattr(self.assets, "nikke_db", None)
            )
        elif page in {"arena_matchup", "arena_three_teams"}:
            builder = self._builders.get("arena") or ArenaT2IPayloadBuilder(self.assets)
            self._builders["arena"] = builder
        else:
            raise ValueError("尚未支持该展示页面")
        self._builders[page] = builder
        return builder

    def _character_payload(self, data) -> dict[str, Any]:
        # 资产准备、立绘/图标缩放与 PNG 编码都是同步 Pillow 工作，只在工作线程中执行。
        assets = self.payload_builder.assets.resolve_character_assets(data)
        return self._builder("character").build(data, assets)

    async def render_campaign_history(self, record) -> str:
        payload = await asyncio.to_thread(self.payload_builder.build, record)
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
        if page in {"arena_matchup", "arena_three_teams"}:
            async with asyncio.timeout(self.timeout):
                pages = await asyncio.to_thread(self._builder(page).pages, data)
                if len(pages) == 1:
                    return await self.render_payload(page, pages[0])
                return [await self.render_payload(page, payload) for payload in pages]
        if page == "character":
            self._builder("character")  # 在事件循环线程内完成懒加载，避免工作线程并发创建。
            payload = await asyncio.to_thread(self._character_payload, data)
            return await self.render_payload(page, payload)
        if page in self._THREADED_BUILDERS:
            builder = self._builder(page)
            # 总表 builder 不接受额外展示参数，保持与既有调用合同一致。
            extra = {} if page == "roster" else kwargs
            data = await asyncio.to_thread(builder.build, data, **extra)
            return await self.render_payload(page, data)
        if page == "calendar_schedule":
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
        raise ValueError("尚未支持该展示页面")

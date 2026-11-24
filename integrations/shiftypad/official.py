# SPDX-License-Identifier: GPL-3.0-or-later
"""官方 ShiftyPad 公开档案的 HTTP 只读适配器。

放在 integrations 层，领域层只保留解析与端口；不携带任何 Cookie、Token 或登录态。
"""

from __future__ import annotations

import httpx

from ...features.shiftypad.fetcher import (
    CONTRACT,
    SOURCE_PAGE,
    parse_public_profile,
)
from ...features.shiftypad.identity import OPENID_RE
from ...features.shiftypad.models import (
    ShiftypadIdentity,
    ShiftypadPrivateError,
    ShiftypadProfile,
    ShiftypadUpstreamError,
)

ENDPOINT = "https://api.blablalink.com/api/ugc/direct/standalonesite/User/GetUserProfile"


class OfficialPublicProfileFetcher:
    """只读官方公开档案；不发送本插件账号凭据。"""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 12.0,
        endpoint: str = ENDPOINT,
    ) -> None:
        self._transport = transport
        self._timeout = timeout
        self._endpoint = endpoint

    async def fetch(self, identity: ShiftypadIdentity) -> ShiftypadProfile:
        if not isinstance(identity, ShiftypadIdentity) or not OPENID_RE.fullmatch(identity.openid):
            raise ShiftypadUpstreamError("缺少受支持的公开 OpenID")
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    self._endpoint,
                    json={"intl_openid": identity.openid},
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "Origin": "https://www.blablalink.com",
                        "Referer": SOURCE_PAGE,
                        "X-Language": "zh-TW",
                        "X-Channel-Type": "2",
                        "User-Agent": "astrbot-plugin-nikke/1.0 (read-only public profile)",
                    },
                )
        except httpx.HTTPError as exc:
            raise ShiftypadUpstreamError("ShiftyPad 公开档案暂时不可用") from exc
        if response.status_code in (401, 403):
            raise ShiftypadPrivateError("该 ShiftyPad 档案未公开或需要登录")
        if response.status_code == 404:
            raise ShiftypadUpstreamError("未找到该 ShiftyPad 公开档案")
        if response.status_code != 200:
            raise ShiftypadUpstreamError(f"ShiftyPad 公开档案返回 HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ShiftypadUpstreamError("ShiftyPad 公开档案响应不是 JSON") from exc
        return parse_public_profile(payload, identity)


__all__ = ["CONTRACT", "ENDPOINT", "SOURCE_PAGE", "OfficialPublicProfileFetcher"]

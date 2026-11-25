# SPDX-License-Identifier: GPL-3.0-or-later
"""公共大厅与个人工作台共享的同源安全头、CSRF、速率与请求体校验。"""

from __future__ import annotations

import json
import secrets
from typing import Any

from aiohttp import web


PORTAL_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data: blob:; connect-src 'self'; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)
MAX_PORTAL_BODY = 32 * 1024


def apply_portal_headers(response: web.StreamResponse) -> web.StreamResponse:
    response.headers.update(
        {
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": PORTAL_CSP,
        }
    )
    return response


def portal_error(
    code: str, message: str, *, status: int = 400, **extra: Any
) -> web.Response:
    payload: dict[str, Any] = {
        "ok": False,
        "code": code,
        "message": message,
        "error": message,
    }
    payload.update(extra)
    return apply_portal_headers(web.json_response(payload, status=status))


def check_same_origin(request: web.Request, site_origin: str) -> web.Response | None:
    origin = request.headers.get("Origin", "")
    if origin != site_origin:
        return portal_error("FORBIDDEN_ORIGIN", "来源校验失败", status=403)
    return None


def check_csrf(
    request: web.Request, *, header_name: str, expected_csrf: str
) -> web.Response | None:
    actual = str(request.headers.get(header_name, "") or "")
    if not expected_csrf or not secrets.compare_digest(actual, expected_csrf):
        return portal_error("FORBIDDEN_CSRF", "CSRF 校验失败", status=403)
    return None


def check_session_rate(
    requests: list[float], now: float, *, limit: int = 40, window: float = 60.0
) -> web.Response | None:
    requests[:] = [ts for ts in requests if now - ts < window]
    if len(requests) >= limit:
        return portal_error("RATE_LIMITED", "请求过于频繁，请稍后再试。", status=429)
    requests.append(now)
    return None


async def read_json_object(
    request: web.Request, *, max_bytes: int = MAX_PORTAL_BODY
) -> tuple[dict[str, Any] | None, web.Response | None]:
    if request.content_length is not None and request.content_length > max_bytes:
        return None, portal_error("PAYLOAD_TOO_LARGE", "请求体超过大小限制", status=413)
    if request.content_type != "application/json":
        return None, portal_error(
            "INVALID_CONTENT_TYPE", "需要 application/json 请求", status=400
        )
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.content.iter_chunked(4096):
        total += len(chunk)
        if total > max_bytes:
            return None, portal_error(
                "PAYLOAD_TOO_LARGE", "请求体超过大小限制", status=413
            )
        chunks.append(chunk)
    try:
        parsed = json.loads(b"".join(chunks).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None, portal_error("INVALID_JSON", "JSON 格式无效", status=400)
    if not isinstance(parsed, dict):
        return None, portal_error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)
    return parsed, None

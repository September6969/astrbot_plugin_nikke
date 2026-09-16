# SPDX-License-Identifier: GPL-3.0-or-later
"""统一异步 HTTP 抓取客户端 FetchClient。

提供统一的：
1. connect/read 超时（默认 connect 3.0s, read 5.0s）；
2. 基础并发限制（Semaphore=4）；
3. 幂等 GET 请求单次重试（退避 0.5s）；
4. Host 级别熔断器（连续 3 次失败熔断 10 分钟，支持 Half-Open 探活）；
5. 敏感参数脱敏与统一异常/状态码归类；
6. 响应 JSON 安全解析与 Schema 异常封装。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Mapping
from urllib.parse import urlparse

import httpx

from ...core.privacy import safe_exception_message

logger = logging.getLogger("nikke.fetch_client")

DEFAULT_CONNECT_TIMEOUT = 3.0
DEFAULT_READ_TIMEOUT = 5.0
DEFAULT_MAX_CONCURRENCY = 4
DEFAULT_MAX_RETRIES = 1
DEFAULT_CIRCUIT_FAILURE_THRESHOLD = 3
DEFAULT_CIRCUIT_RECOVERY_SECONDS = 600.0  # 10 分钟


class FetchError(Exception):
    """FetchClient 基础异常。"""

    def __init__(self, message: str, *, status_code: int | None = None, host: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.host = host


class CircuitBreakerOpenError(FetchError):
    """熔断器处于开启状态异常。"""

    def __init__(self, host: str, reset_at: float):
        remaining = max(0.0, reset_at - time.monotonic())
        super().__init__(
            f"目标主机 {host} 熔断保护已触发（连续失败超阈值），将在 {remaining:.1f} 秒后解除",
            host=host,
        )
        self.reset_at = reset_at


class FetchTimeoutError(FetchError):
    """请求超时异常。"""


class FetchNetworkError(FetchError):
    """网络连接异常。"""


class FetchHTTPStatusError(FetchError):
    """HTTP 状态码异常。"""


class FetchDecodeError(FetchError):
    """JSON 响应解析异常。"""


class CircuitBreaker:
    """单个 Host 的熔断状态追踪器。"""

    def __init__(
        self,
        failure_threshold: int = DEFAULT_CIRCUIT_FAILURE_THRESHOLD,
        recovery_seconds: float = DEFAULT_CIRCUIT_RECOVERY_SECONDS,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self.consecutive_failures: int = 0
        self.state: str = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.tripped_at: float = 0.0

    def can_request(self) -> bool:
        now = time.monotonic()
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if now - self.tripped_at >= self.recovery_seconds:
                self.state = "HALF_OPEN"
                return True
            return False
        if self.state == "HALF_OPEN":
            # 允许单次探活
            return True
        return True

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.state = "CLOSED"
        self.tripped_at = 0.0

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.failure_threshold:
            self.state = "OPEN"
            self.tripped_at = time.monotonic()


def _sanitize_url(url: str) -> str:
    """对 URL 的 query 部分进行基础脱敏，移除可能的 token/key/auth 等敏感值。"""
    try:
        parsed = urlparse(url)
        # 仅保留协议、主机和路径，避免 query 中存在敏感 token
        if parsed.query:
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?..."
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    except Exception:
        return "https://sanitized-url"


class FetchClient:
    """统一异步网络抓取客户端。"""

    def __init__(
        self,
        *,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        max_retries: int = DEFAULT_MAX_RETRIES,
        circuit_failure_threshold: int = DEFAULT_CIRCUIT_FAILURE_THRESHOLD,
        circuit_recovery_seconds: float = DEFAULT_CIRCUIT_RECOVERY_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
        default_headers: Mapping[str, str] | None = None,
    ):
        self.timeout = httpx.Timeout(
            timeout=connect_timeout + read_timeout,
            connect=connect_timeout,
            read=read_timeout,
            write=read_timeout,
        )
        self.max_retries = max_retries
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.circuit_failure_threshold = circuit_failure_threshold
        self.circuit_recovery_seconds = circuit_recovery_seconds
        self.transport = transport
        self.default_headers = dict(default_headers or {})
        if "User-Agent" not in self.default_headers:
            self.default_headers["User-Agent"] = "NIKKE-AstrBot-Plugin/1.0"

        self._breakers: dict[str, CircuitBreaker] = {}
        self._breaker_lock = asyncio.Lock()

    def _get_breaker(self, host: str) -> CircuitBreaker:
        if host not in self._breakers:
            self._breakers[host] = CircuitBreaker(
                failure_threshold=self.circuit_failure_threshold,
                recovery_seconds=self.circuit_recovery_seconds,
            )
        return self._breakers[host]

    async def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """执行 GET 请求并解析 JSON，附带熔断、重试、并发控制与脱敏异常处理。"""
        parsed = urlparse(url)
        host = parsed.netloc or "unknown"
        safe_url = _sanitize_url(url)

        breaker = self._get_breaker(host)
        if not breaker.can_request():
            reset_at = breaker.tripped_at + breaker.recovery_seconds
            logger.warning("[NIKKE Fetch] 主机 %s 处于熔断保护期，阻断外部请求", host)
            raise CircuitBreakerOpenError(host, reset_at)

        req_headers = {**self.default_headers, **(headers or {})}
        req_timeout = self.timeout if timeout is None else httpx.Timeout(timeout, connect=min(timeout, DEFAULT_CONNECT_TIMEOUT))

        attempt = 0
        last_exception: Exception | None = None

        while attempt <= self.max_retries:
            attempt += 1
            try:
                async with self.semaphore:
                    async with httpx.AsyncClient(
                        transport=self.transport,
                        timeout=req_timeout,
                        follow_redirects=True,
                    ) as client:
                        response = await client.get(url, params=params, headers=req_headers)
                        response.raise_for_status()
                        payload = response.json()

                breaker.record_success()
                return payload

            except httpx.TimeoutException as exc:
                last_exception = exc
                logger.warning(
                    "[NIKKE Fetch] 请求超时 (%s, attempt %d/%d): %s",
                    safe_url,
                    attempt,
                    self.max_retries + 1,
                    safe_exception_message(exc),
                )
            except httpx.NetworkError as exc:
                last_exception = exc
                logger.warning(
                    "[NIKKE Fetch] 网络连接失败 (%s, attempt %d/%d): %s",
                    safe_url,
                    attempt,
                    self.max_retries + 1,
                    safe_exception_message(exc),
                )
            except httpx.HTTPStatusError as exc:
                # 4xx / 5xx 状态码通常不适合立即无脑重试
                breaker.record_failure()
                status = exc.response.status_code
                logger.warning(
                    "[NIKKE Fetch] HTTP 状态码异常 (%s, status=%d): %s",
                    safe_url,
                    status,
                    safe_exception_message(exc),
                )
                raise FetchHTTPStatusError(
                    f"HTTP 请求返回错误状态码 {status}",
                    status_code=status,
                    host=host,
                ) from exc
            except (ValueError, TypeError) as exc:
                # JSON 解析异常
                breaker.record_failure()
                logger.warning(
                    "[NIKKE Fetch] JSON 解析失败 (%s): %s",
                    safe_url,
                    safe_exception_message(exc),
                )
                raise FetchDecodeError(
                    f"上游返回非标准 JSON: {safe_exception_message(exc)}",
                    host=host,
                ) from exc
            except Exception as exc:
                breaker.record_failure()
                logger.error(
                    "[NIKKE Fetch] 未知请求异常 (%s): %s",
                    safe_url,
                    safe_exception_message(exc),
                )
                raise FetchError(f"请求失败: {safe_exception_message(exc)}", host=host) from exc

            if attempt <= self.max_retries:
                await asyncio.sleep(0.5)

        # 重试耗尽，记录熔断失败
        breaker.record_failure()
        if isinstance(last_exception, httpx.TimeoutException):
            raise FetchTimeoutError(f"请求 {host} 超时", host=host) from last_exception
        raise FetchNetworkError(f"连接 {host} 失败", host=host) from last_exception

# SPDX-License-Identifier: GPL-3.0-or-later
"""CDK 兑换服务与输入解析器。

遵循 contracts/cdk.md：
1. 保持 CDK 原始大小写，输入去重并限制单次最大数量；
2. 明确区分成功、业务失败与网络超时 (RESULT_UNKNOWN)；
3. 遇到 CookieExpired 或限流立即中止剩余批量；
4. 业务失败统一引导至 BlaBlaLink 手动填写；
5. 同账号并发互斥锁。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from typing import Any

import httpx

from .cdk_models import CdkBatchResult, CdkRedeemResult
from .client import (
    BlaBlaClient,
    BlaBlaError,
    BlaBlaNetworkError,
    BlaBlaTimeoutError,
    CookieExpired,
)

logger = logging.getLogger("nikke.cdk")

CDK_PATTERN: re.Pattern[str] = re.compile(r"[A-Za-z0-9_-]{4,64}")


class CdkInputParser:
    @staticmethod
    def parse(text: str, max_items: int = 10) -> list[str]:
        """从输入文本中解析出干净的 CDK 列表。
        支持空格、换行、逗号、分号分隔，保持大小写，去重并限制最大数量。
        """
        raw = str(text or "").strip()
        if not raw:
            return []

        # 按常见分隔符切分
        tokens = re.split(r"[\s,;，；\n\r]+", raw)
        seen: set[str] = set()
        codes: list[str] = []

        for token in tokens:
            cleaned = token.strip().strip("\"'[]()")
            if not CDK_PATTERN.fullmatch(cleaned):
                continue
            if cleaned not in seen:
                seen.add(cleaned)
                codes.append(cleaned)
                if len(codes) >= max_items:
                    break

        return codes


class CdkService:
    def __init__(self, client: BlaBlaClient):
        self.client = client
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    async def _get_account_lock(self, account_key: str) -> asyncio.Lock:
        async with self._global_lock:
            if account_key not in self._locks:
                self._locks[account_key] = asyncio.Lock()
            return self._locks[account_key]

    async def _redeem_single_core(self, account: dict[str, Any], code: str) -> CdkRedeemResult:
        """单条 CDK 兑换的核心逻辑（不加锁）。"""
        try:
            res = await self.client.redeem_cdk(account, code)
            if res.success:
                return CdkRedeemResult(code=code, success=True, message=res.message or "兑换成功", terminal=True)
            else:
                return CdkRedeemResult(
                    code=code,
                    success=False,
                    message=f"{res.message or '兑换失败'}（若持续失败请前往 BlaBlaLink 手动填写）",
                    terminal=getattr(res, "terminal", True),
                )
        except CookieExpired:
            raise
        except (BlaBlaTimeoutError, httpx.TimeoutException, BlaBlaNetworkError, httpx.NetworkError) as exc:
            logger.warning("CDK 兑换网络异常: %s", type(exc).__name__)
            return CdkRedeemResult(
                code=code,
                success=False,
                message="网络请求超时，请先检查游戏内邮箱或官方兑换记录，切勿频繁重复提交",
                is_unknown=True,
                terminal=False,
            )
        except BlaBlaError as exc:
            code_str = str(exc.code).strip()
            is_rate_limit = code_str in {"212000", "429"} or "请求过频" in str(exc)
            if is_rate_limit:
                return CdkRedeemResult(
                    code=code,
                    success=False,
                    message="请求过频，请稍后再试",
                    is_rate_limited=True,
                    terminal=False,
                )

            # 临时 HTTP 错误（5xx、408 等）与服务端异常不应永久阻止重试
            is_http_temp = False
            if code_str.isdigit():
                code_int = int(code_str)
                if 500 <= code_int < 600 or code_int in {408, 429}:
                    is_http_temp = True
            elif "HTTP" in str(exc) or any(err in str(exc) for err in ("500", "502", "503", "504")):
                is_http_temp = True

            if is_http_temp:
                return CdkRedeemResult(
                    code=code,
                    success=False,
                    message=f"社区服务响应异常 ({exc.code or 'HTTP错误'})，可稍后重试",
                    terminal=False,
                )

            return CdkRedeemResult(
                code=code,
                success=False,
                message=f"{exc}（若持续失败请前往 BlaBlaLink 手动填写）",
                terminal=False,
            )
        except Exception as exc:
            logger.error("CDK 兑换异常: %s", type(exc).__name__)
            return CdkRedeemResult(
                code=code,
                success=False,
                message="系统异常，请前往 BlaBlaLink 手动填写",
                terminal=False,
            )

    async def redeem_single(
        self,
        account: dict[str, Any],
        code: str,
        account_key: str = "",
    ) -> CdkRedeemResult:
        """单条 CDK 兑换，使用账号锁互斥。"""
        lock = await self._get_account_lock(account_key or str(account.get("game_uid", "default")))
        async with lock:
            return await self._redeem_single_core(account, code)

    async def redeem_batch(
        self,
        account: dict[str, Any],
        codes: list[str],
        account_key: str = "",
        delay: float = 1.0,
        store=None,
        qq_id: str = "",
    ) -> CdkBatchResult:
        """批量串行兑换 CDK，遇登录失效或限流安全中止。与单条兑换共享同账号互斥锁。"""
        if len(codes) > 10:
            raise ValueError("单次最多兑换 10 个码")
        delay = max(1.0, delay)
        lock = await self._get_account_lock(account_key or str(account.get("game_uid", "default")))
        batch_res = CdkBatchResult()

        async with lock:
            for index, code in enumerate(codes):
                try:
                    res = await self._redeem_persistently(account, code, store, qq_id) if store is not None else await self._redeem_single_core(account, code)
                    batch_res.results.append(res)
                    if res.is_rate_limited or "请求过频" in (res.message or ""):
                        batch_res.stopped_by_rate_limit = True
                        logger.warning("CDK 批量兑换触发限流，中止剩余任务")
                        break
                except CookieExpired:
                    batch_res.stopped_by_cookie = True
                    batch_res.results.append(
                        CdkRedeemResult(code=code, success=False, message="登录状态已失效，已中止剩余兑换")
                    )
                    logger.warning("CDK 批量兑换登录失效，中止剩余任务")
                    break

                if index < len(codes) - 1 and delay > 0:
                    await asyncio.sleep(delay)

        return batch_res

    async def _redeem_persistently(self, account, code, store, qq_id):
        """批量使用单条命令相同的持久键与原子 claim/retry，锁由调用者持有。"""
        game_uid = str(account.get("game_uid") or account.get("uid") or "default").strip()
        digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
        key = f"cdk:{qq_id}:{game_uid}:{digest}"
        existing = store.get_run(key)
        # 批量重放不能隐式重试未知写结果，需用户先确认官方记录。
        if existing and existing["status"] in {"success", "terminal", "unknown"}:
            status = existing["status"]
            return CdkRedeemResult(code, status == "success", "此码已有处理记录，请核对官方兑换历史",
                                   is_unknown=status == "unknown", terminal=status != "unknown")
        if existing and existing["status"] == "running":
            changed = store.mark_stale_running_unknown(
                key, stale_after=120, detail="兑换结果未确认，请先检查官方兑换历史。")
            current = store.get_run(key)
            unknown = changed or (current and current["status"] == "unknown")
            message = "兑换结果未确认，请先检查官方兑换历史" if unknown else "此码正在处理，请稍后查询"
            return CdkRedeemResult(code, False, message, is_unknown=True, terminal=False)
        claimed = store.retry_run(key, {"failed", "expired"}) if existing else store.claim_run(key, qq_id, "cdk")
        if not claimed:
            return CdkRedeemResult(code, False, "此码正在处理，请稍后查询", is_unknown=True, terminal=False)
        try:
            result = await self._redeem_single_core(account, code)
        except CookieExpired:
            store.finish_run(key, "expired", "登录状态已失效")
            raise
        except asyncio.CancelledError:
            store.finish_run(key, "unknown", "兑换中断，结果未确认")
            raise
        status = "success" if result.success else "unknown" if result.is_unknown else "failed" if not result.terminal else "terminal"
        # 不将可能含兑换码的上游消息持久化。
        detail = {"success": "兑换成功", "unknown": "结果未确认，请核对官方历史", "failed": "请求失败，可稍后重试", "terminal": "官方已拒绝此码"}[status]
        store.finish_run(key, status, detail)
        return result


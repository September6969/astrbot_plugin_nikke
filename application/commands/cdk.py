# SPDX-License-Identifier: GPL-3.0-or-later
"""CDK 单码、批量和只读查询命令用例。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from ...features.cdk.models import CdkBatchResult
from ...features.cdk.service import CDK_PATTERN, CdkInputParser, CdkService
from ...integrations.blablalink.client import CookieExpired
from .contracts import CommandContext, CommandResult, TextReply


class CdkAccountReader(Protocol):
    """读取绑定账号的最小端口。"""

    def get_account(
        self, qq_id: str, with_cookie: bool = True
    ) -> Mapping[str, Any] | None:
        """返回绑定账号及写入接口凭据。"""


class CdkCommandStore(Protocol):
    """CDK 命令需要的最小存储端口。"""

    def mark_cookie_invalid(self, qq_id: str) -> None:
        """标记绑定凭据失效。"""


class CdkCommandHandler:
    """处理 CDK 命令结果；写入状态和持久键完全归服务层所有。"""

    def __init__(
        self,
        *,
        account_reader: CdkAccountReader,
        store: CdkCommandStore,
        client: Any,
        service: CdkService,
        config: Mapping[str, Any],
    ) -> None:
        self._account_reader = account_reader
        self._store = store
        self._client = client
        self._service = service
        self._config = config

    async def handle(self, context: CommandContext) -> CommandResult:
        """显式分派 CDK 写入或只读查询操作。"""
        operation = context.parameters.get("operation", "").strip().casefold()
        if operation == "single":
            return await self._single(context)
        if operation == "batch":
            return await self._batch(context)
        if operation == "available":
            return await self._available(context)
        if operation == "history":
            return await self._history(context)
        return self._text("未知 CDK 操作。")

    async def _single(self, context: CommandContext) -> CommandResult:
        if not bool(self._config.get("enable_cdk_redemption", False)):
            return self._text("CDK真实兑换当前由管理员关闭。")
        code = context.parameters.get("code", "").strip()
        if not CDK_PATTERN.fullmatch(code):
            return self._text("兑换码格式无效：仅支持4至64位字母、数字、下划线或连字符。")
        account = self._account(context.actor_id)
        if account is None:
            return self._unbound()
        if not CdkService.canonical_account_key(account):
            return self._text("账号缺少稳定游戏身份，未执行兑换。")
        masked = self.mask_code(code)
        try:
            result = await self._service.redeem_single(
                account, code, store=self._store, qq_id=context.actor_id
            )
            return self._text(f"兑换码 {masked}：{result.message}")
        except CookieExpired:
            self._store.mark_cookie_invalid(context.actor_id)
            return self._text("登录状态已失效，请重新发送 /妮姬 账号 绑定。")
        except Exception:
            return self._text(f"兑换码 {masked}：请求失败，可稍后查询结果。")

    async def _batch(self, context: CommandContext) -> CommandResult:
        if not bool(self._config.get("enable_cdk_redemption", False)):
            return self._text("CDK真实兑换当前由管理员关闭。")
        codes = CdkInputParser.parse(context.parameters.get("codes", ""), max_items=10)
        if not codes:
            return self._text("未检测到有效的兑换码。支持空格/换行/逗号分隔，单次最多10个。")
        account = self._account(context.actor_id)
        if account is None:
            return self._unbound()
        if not CdkService.canonical_account_key(account):
            return self._text("账号缺少稳定游戏身份，未执行兑换。")
        try:
            batch = await self._service.redeem_batch(
                account, codes, store=self._store, qq_id=context.actor_id
            )
        except CookieExpired:
            self._store.mark_cookie_invalid(context.actor_id)
            return self._text("登录状态已失效，请重新发送 /妮姬 账号 绑定。")
        return self._batch_result(batch, context.actor_id)

    async def _available(self, context: CommandContext) -> CommandResult:
        account = self._account(context.actor_id)
        if account is None:
            return self._unbound()
        try:
            items = await self._client.get_cdk_redemption(account)
            available = [
                item
                for item in items
                if isinstance(item, dict) and item.get("status") in (None, 0, "0")
            ]
            if not available:
                return self._text("官方暂无可查询的可用 CDK 列表。")
            lines = ["【官方可用 CDK 列表】"]
            for item in available[:15]:
                code = str(
                    item.get("cdk")
                    or item.get("cdkey")
                    or item.get("code")
                    or item.get("title")
                    or "未知"
                )
                desc = str(item.get("desc") or item.get("reward") or "").strip()
                expire = str(item.get("expire_time") or item.get("end_time") or "").strip()
                extra = f" ({desc})" if desc else ""
                exp_str = f" [截止: {expire}]" if expire else ""
                lines.append(f"• {code}{extra}{exp_str}")
            return self._text("\n".join(lines))
        except CookieExpired:
            self._store.mark_cookie_invalid(context.actor_id)
            return self._text("登录状态已失效，请重新发送 /妮姬 账号 绑定。")
        except Exception as exc:
            return self._text(f"获取可用 CDK 失败：{exc}")

    async def _history(self, context: CommandContext) -> CommandResult:
        account = self._account(context.actor_id)
        if account is None:
            return self._unbound()
        try:
            items = await self._client.get_cdk_redemption_history(account)
            if not items:
                return self._text("官方暂无 CDK 兑换历史记录。")
            lines = ["【CDK 兑换历史记录】"]
            for item in items[:15]:
                code = str(item.get("cdk") or item.get("cdkey") or item.get("code") or "未知")
                masked = self.mask_code(code)
                status = str(item.get("status") or item.get("result") or item.get("msg") or "已兑换")
                redeemed_at = str(
                    item.get("redeemed_at")
                    or item.get("created_at")
                    or item.get("time")
                    or ""
                ).strip()
                time_suffix = f" [{redeemed_at}]" if redeemed_at else ""
                lines.append(f"• {masked}: {status}{time_suffix}")
            return self._text("\n".join(lines))
        except CookieExpired:
            self._store.mark_cookie_invalid(context.actor_id)
            return self._text("登录状态已失效，请重新发送 /妮姬 账号 绑定。")
        except Exception as exc:
            return self._text(f"获取 CDK 兑换历史失败：{exc}")

    def _account(self, actor_id: str) -> dict[str, Any] | None:
        account = self._account_reader.get_account(actor_id)
        return dict(account) if account is not None else None

    def _batch_result(self, batch: CdkBatchResult, actor_id: str) -> CommandResult:
        lines = [f"【CDK 批量兑换结果】共 {len(batch.results)} 项："]
        for result in batch.results:
            icon = "✓" if result.success else ("?" if result.is_unknown else "✗")
            lines.append(f"{icon} {self.mask_code(result.code)}：{result.message}")
        if batch.stopped_by_cookie:
            self._store.mark_cookie_invalid(actor_id)
            lines.append("\n⚠️ 登录状态已失效，已中止剩余兑换。请重新绑定。")
        elif batch.stopped_by_rate_limit:
            lines.append("\n⚠️ 遇到官方频控限制，已中止剩余兑换，请稍后再试。")
        return self._text("\n".join(lines))

    @staticmethod
    def mask_code(code: str) -> str:
        return code[:2] + "***" + code[-2:] if len(code) > 4 else "***"

    @staticmethod
    def _unbound() -> CommandResult:
        return CdkCommandHandler._text("尚未绑定账号，请先私聊发送 /妮姬 账号 绑定")

    @staticmethod
    def _text(text: str) -> CommandResult:
        return CommandResult((TextReply(text),))

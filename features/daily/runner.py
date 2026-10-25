# SPDX-License-Identifier: GPL-3.0-or-later
"""日常签到与任务定时执行器。"""

from __future__ import annotations

import asyncio
import hashlib
import random
import logging
from datetime import datetime, timezone, timedelta
from collections.abc import Mapping
from typing import Any

from ...core.privacy import safe_exception_message
from ..account.errors import CredentialExpiredError
from .errors import UnknownAfterActionError
from .community import CommunityDailyMixin
from .models import DailyTaskResult, DailyTaskStatus
from .action_models import account_scope
from .ports import DailyGateway, DailyStore


class DailyRunner(CommunityDailyMixin):
    """日常任务执行器，管理账号签到、并发控制、幂等与重试锁。"""

    def __init__(
        self,
        client: DailyGateway | None = None,
        store: DailyStore | None = None,
        config: dict[str, Any] | None = None,
    ):
        self._client = client
        self._store = store
        self.config = config or {}
        self._account_locks = {}
        self.on_automatic_result = None

    @property
    def client(self) -> DailyGateway:
        if self._client is None:
            raise RuntimeError("DailyGateway 未配置")
        return self._client

    @property
    def store(self) -> DailyStore:
        if self._store is None:
            raise RuntimeError("DailyStore 未配置")
        return self._store

    @staticmethod
    def daily_error_result(account_name: str, prefix: str, exc: Exception) -> DailyTaskResult:
        """把异常映射到保守状态，避免所有异常都显示为泛化失败。"""
        message = str(exc)
        code = str(getattr(exc, "code", ""))
        if code in {"212000", "429"} or "请求过频" in message or "限流" in message:
            return DailyTaskResult(account_name, DailyTaskStatus.RATE_LIMITED, f"{prefix}请求受到频控，请稍后再试")
        return DailyTaskResult(account_name, DailyTaskStatus.FAILED, f"{prefix}失败：{type(exc).__name__}")

    async def read_only_daily_recovery(
        self, account: Mapping[str, Any], account_name: str
    ) -> DailyTaskResult:
        """恢复未决任务时只读核验，绝不重放签到写操作。"""
        await self.client.get_profile(account)
        status = await self.client.get_daily_signin(account)
        if status.get("completed"):
            return DailyTaskResult(account_name, DailyTaskStatus.ALREADY_DONE, "登录有效；今日已经签到（恢复核验）")
        return DailyTaskResult(
            account_name,
            DailyTaskStatus.UNKNOWN_AFTER_ACTION,
            "登录有效；签到结果未确认，未自动重发",
        )

    @staticmethod
    def daily_identity(account: Mapping[str, Any]) -> str:
        """构造不依赖 QQ 的稳定游戏账号作用域。"""
        game_uid = str(account.get("game_uid") or account.get("uid") or "").strip()
        area_id = str(account.get("area_id") or "").strip()
        platform = str(account.get("platform") or "global").strip().casefold()
        if not game_uid or not area_id or not platform:
            return ""
        return f"{platform}:{area_id}:{game_uid}"

    @classmethod
    def daily_run_key(cls, day: str, account: Mapping[str, Any], action: str) -> str:
        identity = cls.daily_identity(account)
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        prefix = f"community-utc:{day}" if action in {"daily", "signin"} else day
        return f"{prefix}:game:{digest}:{action}"

    def legacy_daily_guard(self, day: str, qq_id: str, action: str, account_name: str) -> DailyTaskResult | None:
        """发现旧 QQ 作用域记录时显式阻断，不把它静默当成新账号结果。"""
        legacy_key = f"{day}:{qq_id}:{action}"
        legacy = self.store.get_run(legacy_key)
        if not legacy:
            return None
        status = str(legacy.get("status", ""))
        return DailyTaskResult(
            account_name,
            DailyTaskStatus.UNKNOWN_AFTER_ACTION
            if status in {"running", "DISPATCH_INTENT", "unknown", "UNKNOWN_AFTER_ACTION"}
            else DailyTaskStatus.UNAVAILABLE,
            "发现旧版 QQ 作用域记录，未据此判定今日结果，也未执行写操作；请先完成账号作用域迁移",
        )

    async def run_daily_for_account(self, account, day):
        async with self._account_lock(account):
            return await self._run_signin(account, day)

    async def _run_signin(
        self, account: Mapping[str, Any], day: str
    ) -> DailyTaskResult:
        qq_id = str(account["qq_id"])
        account_name = str(account.get("nickname") or qq_id)
        if not self.daily_identity(account):
            return DailyTaskResult(
                account_name,
                DailyTaskStatus.UNAVAILABLE,
                "账号缺少稳定游戏 UID、区服或平台身份，未执行日常写操作",
            )
        # 新周期使用独立命名空间。旧北京时间记录只阻止未知写入，成功仍以来源状态复核。
        digest = hashlib.sha256(self.daily_identity(account).encode()).hexdigest()[:24]
        try:
            next_day = (datetime.fromisoformat(day) + timedelta(days=1)).strftime("%Y-%m-%d")
        except ValueError:
            next_day = day
        old_keys = [f"{date}:game:{digest}:{action}" for date in {day, next_day} for action in ("daily", "signin")]
        old_keys.extend(f"{next_day}:{qq_id}:{action}" for action in ("daily", "signin"))
        if any((self.store.get_run(key) or {}).get("status") in {
            "running", "DISPATCH_INTENT", "unknown", "UNKNOWN_AFTER_ACTION"
        } for key in old_keys):
            try:
                return await self.read_only_daily_recovery(account, account_name)
            except CredentialExpiredError:
                self.store.mark_cookie_invalid(qq_id)
                return DailyTaskResult(account_name, DailyTaskStatus.COOKIE_EXPIRED, "登录失效，请重新绑定")
            except asyncio.CancelledError:
                raise
            except Exception:
                return DailyTaskResult(account_name, DailyTaskStatus.UNKNOWN_AFTER_ACTION, "旧周期签到待确认，未重发")
        legacy_daily = self.legacy_daily_guard(day, qq_id, "daily", account_name)
        if legacy_daily:
            return legacy_daily
        run_key = self.daily_run_key(day, account, "daily")
        if not self.store.claim_run(
            run_key, qq_id, "daily", initial_status="DISPATCH_INTENT"
        ):
            existing = self.store.get_run(run_key)
            existing_status = str(existing.get("status", "")) if existing else ""
            if existing_status in {"running", "DISPATCH_INTENT", "unknown", "UNKNOWN_AFTER_ACTION"}:
                try:
                    result = await self.read_only_daily_recovery(account, account_name)
                except CredentialExpiredError:
                    self.store.mark_cookie_invalid(qq_id)
                    result = DailyTaskResult(account_name, DailyTaskStatus.COOKIE_EXPIRED, "Cookie失效，请重新绑定")
                except asyncio.CancelledError:
                    raise
                except Exception:
                    result = DailyTaskResult(
                        account_name,
                        DailyTaskStatus.UNKNOWN_AFTER_ACTION,
                        "今日签到结果未确认，请先查询状态；未自动重发",
                    )
                self.store.finish_run(run_key, result.run_status, result.detail)
                return result
            if existing_status in {"failed", "expired"}:
                return DailyTaskResult(
                    account_name,
                    DailyTaskStatus.FAILED,
                    "今日签到已有失败记录，未自动重发",
                )
            if existing_status in {"pending", "unavailable"}:
                if not self.store.transition_run(
                    run_key,
                    from_statuses={"pending", "unavailable"},
                    to_status="DISPATCH_INTENT",
                    refresh_created_at=True,
                ):
                    return DailyTaskResult(
                        account_name,
                        DailyTaskStatus.UNKNOWN_AFTER_ACTION,
                        "今日签到正在重新检查，请稍后查询；未自动重发",
                    )
            else:
                return DailyTaskResult(account_name, DailyTaskStatus.ALREADY_DONE, "今日已执行")
        legacy_signin = self.legacy_daily_guard(day, qq_id, "signin", account_name)
        if legacy_signin:
            self.store.finish_run(run_key, legacy_signin.run_status, legacy_signin.detail)
            return legacy_signin
        signin_key = self.daily_run_key(day, account, "signin")
        signin_owned = False
        signin_finished = False
        if bool(self.config.get("enable_daily_actions", False)):
            signin_owned = self.store.claim_run(
                signin_key, qq_id, "signin", initial_status="DISPATCH_INTENT"
            )
            if not signin_owned:
                existing_signin = self.store.get_run(signin_key) or {}
                signin_status = str(existing_signin.get("status", ""))
                if signin_status in {"pending", "unavailable"}:
                    signin_owned = self.store.transition_run(
                        signin_key,
                        from_statuses={"pending", "unavailable"},
                        to_status="DISPATCH_INTENT",
                        refresh_created_at=True,
                    )
                    if not signin_owned:
                        result = DailyTaskResult(
                            account_name,
                            DailyTaskStatus.UNAVAILABLE,
                            "签到任务仍在重新检查，未执行写操作",
                        )
                        self.store.finish_run(run_key, result.run_status, result.detail)
                        return result
                elif signin_status == "success":
                    result = DailyTaskResult(
                        account_name,
                        DailyTaskStatus.ALREADY_DONE,
                        str(existing_signin.get("detail") or "登录有效；今日已经签到"),
                    )
                elif signin_status in {"running", "DISPATCH_INTENT", "unknown", "UNKNOWN_AFTER_ACTION"}:
                    try:
                        result = await self.read_only_daily_recovery(account, account_name)
                    except CredentialExpiredError:
                        self.store.mark_cookie_invalid(qq_id)
                        result = DailyTaskResult(account_name, DailyTaskStatus.COOKIE_EXPIRED, "Cookie失效，请重新绑定")
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        result = DailyTaskResult(
                            account_name,
                            DailyTaskStatus.UNKNOWN_AFTER_ACTION,
                            "登录有效；签到结果未确认，未自动重发",
                        )
                    self.store.finish_run(signin_key, result.run_status, result.detail)
                    signin_finished = True
                elif signin_status == "expired":
                    result = DailyTaskResult(account_name, DailyTaskStatus.COOKIE_EXPIRED, "Cookie失效，请重新绑定")
                elif signin_status == "failed":
                    result = DailyTaskResult(account_name, DailyTaskStatus.FAILED, "今日签到已有失败记录，未自动重发")
                else:
                    result = DailyTaskResult(
                        account_name,
                        DailyTaskStatus.UNKNOWN_AFTER_ACTION,
                        "登录有效；签到已执行或正在执行，结果未确认；未自动重发",
                    )
                if not signin_owned:
                    self.store.finish_run(run_key, result.run_status, result.detail)
                    return result
        try:
            await self.client.get_profile(account)
            status = await self.client.get_daily_signin(account)
            if not status["found"]:
                result = DailyTaskResult(account_name, DailyTaskStatus.UNAVAILABLE, "登录有效；未找到签到任务")
            elif status["completed"]:
                result = DailyTaskResult(account_name, DailyTaskStatus.ALREADY_DONE, "登录有效；今日已经签到")
            elif not bool(self.config.get("enable_daily_actions", False)):
                result = DailyTaskResult(
                    account_name,
                    DailyTaskStatus.PENDING,
                    "登录有效；自动签到未启用；当前今日待签到",
                )
            else:
                try:
                    detail = "登录有效；" + await self.client.perform_daily_signin(account)
                    self.store.finish_run(signin_key, "success", detail)
                    signin_finished = True
                    result = DailyTaskResult(account_name, DailyTaskStatus.SUCCESS, detail)
                except UnknownAfterActionError:
                    self.store.finish_run(
                        signin_key,
                        "UNKNOWN_AFTER_ACTION",
                        "签到结果未确认，未自动重发",
                    )
                    signin_finished = True
                    result = DailyTaskResult(
                        account_name,
                        DailyTaskStatus.UNKNOWN_AFTER_ACTION,
                        "签到结果未确认，请稍后查询状态；未自动重发",
                    )
                except CredentialExpiredError:
                    self.store.finish_run(signin_key, "expired", "登录状态已失效")
                    signin_finished = True
                    raise
                except Exception as exc:
                    mapped = self.daily_error_result(account_name, "登录有效；签到", exc)
                    self.store.finish_run(signin_key, mapped.run_status, mapped.detail)
                    signin_finished = True
                    result = mapped
        except asyncio.CancelledError:
            existing_signin = self.store.get_run(signin_key) or {}
            if str(existing_signin.get("status", "")) in {
                "running",
                "DISPATCH_INTENT",
                "unknown",
                "UNKNOWN_AFTER_ACTION",
            }:
                self.store.finish_run(signin_key, "UNKNOWN_AFTER_ACTION", "签到已取消，结果未确认，未自动重发")
            self.store.finish_run(run_key, "UNKNOWN_AFTER_ACTION", "日常任务已取消，结果未确认，未自动重发")
            raise
        except CredentialExpiredError:
            self.store.mark_cookie_invalid(qq_id)
            existing_signin = self.store.get_run(signin_key) or {}
            if str(existing_signin.get("status", "")) in {"running", "DISPATCH_INTENT", "unknown", "UNKNOWN_AFTER_ACTION"}:
                self.store.finish_run(signin_key, "expired", "登录状态已失效")
                signin_finished = True
            result = DailyTaskResult(account_name, DailyTaskStatus.COOKIE_EXPIRED, "Cookie失效，请重新绑定")
        except Exception as exc:
            result = self.daily_error_result(account_name, "登录状态检查", exc)
        if signin_owned and not signin_finished:
            self.store.finish_run(signin_key, result.run_status, result.detail)
        self.store.finish_run(run_key, result.run_status, result.detail)
        return result

    async def run_all_daily(
        self,
        day: str,
        stagger: bool = False,
        automatic: bool = False,
    ) -> list[DailyTaskResult]:
        accounts = self.store.list_accounts(
            push_only=not automatic,
            with_cookie=True,
            auto_daily_only=automatic,
        )
        semaphore = asyncio.Semaphore(max(1, int(self.config.get("max_concurrency", 2))))

        async def run(account: Mapping[str, Any]) -> DailyTaskResult:
            if stagger:
                await asyncio.sleep(random.uniform(0, 15 * 60))
            async with semaphore:
                # 随机错峰后重新检查绑定和自动开关，避免已退出账号继续执行。
                reader = getattr(self.store, "get_account", None)
                if automatic and callable(reader):
                    current = reader(str(account["qq_id"]))
                    if not current or not current.get("auto_daily_enabled") or self.daily_identity(current) != self.daily_identity(account):
                        return DailyTaskResult(str(account.get("nickname") or account["qq_id"]), DailyTaskStatus.PENDING, "自动日常已关闭或绑定已变化，未执行")
                    account = current
                run_day = datetime.now(timezone.utc).strftime("%Y-%m-%d") if stagger else day
                if automatic and account.get("game_openid") and self.store.get_setting(f"community_automation:halt:{account_scope(account)}:{run_day}", False):
                    return DailyTaskResult(str(account.get("nickname") or account["qq_id"]), DailyTaskStatus.PENDING,
                        "额外社区能力触发安全暂停，本轮不再提交其他自动写操作；请本人私聊查询。",
                        ({"name": "额外能力安全暂停", "status": "pending", "detail": "需本人私聊处理"},))
                identity = self.daily_identity(account)
                preference = self.store.get_setting(f"daily_scope_v2:{account['qq_id']}", "")
                try:
                    if automatic and identity and preference == identity:
                        result = await self.run_community_for_account(account, run_day)
                    else:
                        result = await self.run_daily_for_account(account, run_day)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    result = self.daily_error_result(str(account.get("nickname") or account["qq_id"]), "日常", exc)
                if automatic and self.on_automatic_result is not None:
                    try:
                        await self.on_automatic_result(account, run_day, result)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        logging.getLogger(__name__).warning("日常异常通知未完成：%s", type(exc).__name__)
                return result

        results = await asyncio.gather(*(run(account) for account in accounts))
        # 管理员手动批次不能污染自动汇总的数据源，避免绕过账号自动签到偏好。
        scope = "automatic" if automatic else "manual"
        self.store.set_setting(f"daily_results:{day}:{scope}", [result.to_storage() for result in results])
        return results

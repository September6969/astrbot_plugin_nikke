from __future__ import annotations

import ast
import inspect
import textwrap
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot_plugin_nikke.application.commands.cdk import CdkCommandHandler
from astrbot_plugin_nikke.application.commands.contracts import CommandContext
from astrbot_plugin_nikke.features.cdk.models import CdkBatchResult, CdkRedeemResult
from astrbot_plugin_nikke.features.cdk.service import CdkService
from astrbot_plugin_nikke.main import NikkePlugin


class _Store:
    def __init__(self):
        self.invalidated = []

    def get_account(self, actor_id, with_cookie=True):
        return {
            "qq_id": actor_id,
            "game_uid": "game-1",
            "area_id": "3",
            "platform": "global",
            "cookie": "synthetic-cookie",
        }

    def mark_cookie_invalid(self, actor_id):
        self.invalidated.append(actor_id)


@pytest.fixture
def cdk_handler():
    store = _Store()
    client = AsyncMock()
    service = AsyncMock()
    service.redeem_single.return_value = CdkRedeemResult("TEST-CODE", True, "兑换成功")
    service.redeem_batch.return_value = CdkBatchResult(
        results=[CdkRedeemResult("TEST-CODE", True, "兑换成功")]
    )
    handler = CdkCommandHandler(
        account_reader=store,
        store=store,
        client=client,
        service=service,
        config={"enable_cdk_redemption": True},
    )
    return handler, store, client, service


@pytest.mark.asyncio
async def test_single_and_batch_commands_always_use_persistent_service_path(cdk_handler):
    handler, store, _, service = cdk_handler
    account = store.get_account("qq-1")
    await handler.handle(
        CommandContext(actor_id="qq-1", parameters={"operation": "single", "code": "TEST-CODE"})
    )
    await handler.handle(
        CommandContext(actor_id="qq-1", parameters={"operation": "batch", "codes": "TEST-CODE"})
    )
    service.redeem_single.assert_awaited_once_with(
        account, "TEST-CODE", store=store, qq_id="qq-1"
    )
    service.redeem_batch.assert_awaited_once_with(
        account, ["TEST-CODE"], store=store, qq_id="qq-1"
    )


@pytest.mark.asyncio
async def test_query_commands_are_owned_by_handler(cdk_handler):
    handler, _, client, _ = cdk_handler
    client.get_cdk_redemption.return_value = [{"cdk": "AVAILABLE", "status": 0}]
    result = await handler.handle(
        CommandContext(actor_id="qq-1", parameters={"operation": "available"})
    )
    assert "AVAILABLE" in result.messages[0].text


def test_cdk_persistent_identity_is_stable_across_qq_rebinding():
    first = {"game_uid": "game-1", "area_id": "3", "platform": "global"}
    second = {**first, "qq_id": "different-qq"}
    assert CdkService.canonical_account_key(first) == CdkService.canonical_account_key(second)
    assert CdkService.persistent_run_key(first, "TEST-CODE") == CdkService.persistent_run_key(
        second, "TEST-CODE"
    )


@pytest.mark.parametrize("method_name", ["daily", "claim", "cdk", "cdk_batch", "cdk_available", "cdk_history"])
def test_main_write_command_adapters_do_not_interpret_persistent_write_state(method_name):
    method = getattr(NikkePlugin, method_name)
    tree = ast.parse(textwrap.dedent(inspect.getsource(method)))
    forbidden_names = {
        "run_key",
        "claim_run",
        "get_run",
        "retry_run",
        "finish_run",
        "DISPATCH_INTENT",
        "UNKNOWN_AFTER_ACTION",
    }
    found = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    found.update(node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute))
    assert not (found & forbidden_names)

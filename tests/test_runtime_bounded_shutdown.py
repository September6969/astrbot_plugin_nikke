"""坏任务、坏资源和关闭者取消均不能伪造完整关闭。"""

import asyncio
import threading

import pytest

from astrbot_plugin_nikke.core.lifecycle.coordinator import RuntimeCoordinator


def coordinator():
    value = RuntimeCoordinator()
    value.close_budget_seconds = .08
    value.task_timeout_seconds = .02
    value.cleanup_timeout_seconds = .02
    return value


@pytest.mark.asyncio
async def test_stubborn_task_is_survivor_but_independent_cleanup_runs():
    value = coordinator()
    started = asyncio.Event()
    release = asyncio.Event()
    cleaned = []
    async def stubborn():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()
    value.register_cleanup("independent", lambda: cleaned.append(True))
    task = value.create_task(stubborn())
    await started.wait()
    close = asyncio.create_task(value.close())
    try:
        done, _ = await asyncio.wait({close}, timeout=.4)
        assert close in done
        with pytest.raises(TimeoutError):
            await close
        assert cleaned == [True]
        assert value.survivors
        assert not value.closed
    finally:
        release.set()
        await asyncio.gather(task, close, return_exceptions=True)
    await value.close()
    assert value.closed


@pytest.mark.asyncio
async def test_hanging_cleanup_does_not_block_later_resource():
    value = coordinator()
    release = asyncio.Event()
    cleaned = []
    async def stuck():
        await release.wait()
    value.register_cleanup("normal", lambda: cleaned.append(True))
    value.register_cleanup("stuck", stuck)
    close = asyncio.create_task(value.close())
    try:
        done, _ = await asyncio.wait({close}, timeout=.4)
        assert close in done
        with pytest.raises(TimeoutError):
            await close
        assert cleaned == [True]
        assert "normal" in value._completed_cleanup
        assert "stuck" not in value._completed_cleanup
        assert not value.closed
    finally:
        release.set()
        await asyncio.gather(close, return_exceptions=True)
    await value.close()
    assert value.closed


@pytest.mark.asyncio
async def test_cleanup_exception_isolated_and_only_failure_retried():
    value = coordinator()
    calls = []
    def failing():
        calls.append("failed")
        if calls.count("failed") == 1:
            raise ValueError("synthetic")
    value.register_cleanup("good", lambda: calls.append("good"))
    value.register_cleanup("failed", failing)
    with pytest.raises(ValueError):
        await value.close()
    assert calls == ["failed", "good"]
    assert not value.closed
    await value.close()
    assert calls == ["failed", "good", "failed"]


@pytest.mark.asyncio
async def test_cancelled_close_keeps_completed_and_inflight_cleanup():
    value = coordinator()
    value.cleanup_timeout_seconds = 1
    value.close_budget_seconds = 2
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []
    async def waiting():
        calls.append("waiting")
        started.set()
        await release.wait()
    value.register_cleanup("waiting", waiting)
    value.register_cleanup("completed", lambda: calls.append("completed"))
    close = asyncio.create_task(value.close())
    await started.wait()
    close.cancel()
    with pytest.raises(asyncio.CancelledError):
        await close
    assert not value.closed
    assert "completed" in value._completed_cleanup
    release.set()
    await value.close()
    assert calls == ["completed", "waiting"]
    assert value.state == "CLOSED"
    assert not value.survivors


@pytest.mark.asyncio
async def test_blocking_sync_cleanup_is_tracked_not_falsely_completed():
    value = coordinator()
    release = threading.Event()
    calls = []
    def blocked():
        calls.append("blocked")
        release.wait(2)
    value.register_cleanup("good", lambda: calls.append("good"))
    value.register_cleanup("blocked", blocked)
    try:
        with pytest.raises(TimeoutError):
            await value.close()
        assert "good" in value._completed_cleanup
        assert "blocked" not in value._completed_cleanup
        assert value.survivors
    finally:
        release.set()
    value.close_budget_seconds = 1
    await value.close()
    assert calls.count("blocked") == 1
    assert value.closed


@pytest.mark.asyncio
async def test_self_cancelled_cleanup_is_not_external_close_cancellation():
    value = coordinator()
    cleaned = []
    async def self_cancelled():
        raise asyncio.CancelledError()
    value.register_cleanup("good", lambda: cleaned.append(True))
    value.register_cleanup("cancelled", self_cancelled)
    with pytest.raises(RuntimeError, match="自行取消"):
        await value.close()
    assert cleaned == [True]
    assert not value.closed

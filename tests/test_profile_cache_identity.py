"""研究快照的真实账号隔离、成功缓存和并发合同。"""

import asyncio

import pytest

from astrbot_plugin_nikke.features.account.errors import CredentialExpiredError
from astrbot_plugin_nikke.tests.test_character_application_contract import make_application


def account(**changes):
    return {"platform": "GLOBAL", "area_id": "1", "game_uid": "42", "qq_id": "qq", **changes}


class Gateway:
    def __init__(self):
        self.calls = 0
        self.error = None
        self.started = asyncio.Event()
        self.release = None

    async def get_profile(self, value):
        self.calls += 1
        self.started.set()
        if self.release is not None:
            await self.release.wait()
        if self.error:
            raise self.error
        return {"identity": (value.get("platform"), value.get("area_id"), value.get("game_uid"))}


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"area_id": "2"}, {"platform": "jp"}, {"game_uid": "99"}])
async def test_complete_identity_isolates_area_platform_and_rebinding(changes):
    gateway = Gateway()
    app, _, _ = make_application(gateway=gateway)
    first = await app.profile_for_stat_calculation(account())
    second = await app.profile_for_stat_calculation(account(**changes))
    assert first != second
    assert gateway.calls == 2


@pytest.mark.asyncio
async def test_normalized_complete_identity_reuses_success():
    gateway = Gateway()
    app, _, _ = make_application(gateway=gateway)
    first = await app.profile_for_stat_calculation(account(platform=" global ", area_id=1))
    second = await app.profile_for_stat_calculation(account(platform="GLOBAL", area_id="1"))
    assert first is second
    assert gateway.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["platform", "area_id", "game_uid"])
async def test_incomplete_identity_never_enters_shared_cache(missing):
    gateway = Gateway()
    app, _, _ = make_application(gateway=gateway)
    value = account()
    value.pop(missing)
    await app.profile_for_stat_calculation(value)
    await app.profile_for_stat_calculation(value)
    assert gateway.calls == 2
    assert not app._stats_profile_cache


@pytest.mark.asyncio
async def test_cold_concurrency_shares_one_request():
    gateway = Gateway()
    gateway.release = asyncio.Event()
    app, _, _ = make_application(gateway=gateway)
    tasks = [asyncio.create_task(app.profile_for_stat_calculation(account())) for _ in range(8)]
    await gateway.started.wait()
    await asyncio.sleep(0)
    gateway.release.set()
    results = await asyncio.gather(*tasks)
    assert gateway.calls == 1
    assert all(result is results[0] for result in results)


@pytest.mark.asyncio
async def test_temporary_failure_is_not_success_cache():
    gateway = Gateway()
    gateway.error = OSError("synthetic outage")
    app, _, _ = make_application(gateway=gateway)
    assert await app.profile_for_stat_calculation(account()) == {}
    gateway.error = None
    assert await app.profile_for_stat_calculation(account()) != {}
    assert gateway.calls == 2


@pytest.mark.asyncio
async def test_expired_credentials_propagate_and_are_not_cached():
    gateway = Gateway()
    gateway.error = CredentialExpiredError("expired")
    app, _, _ = make_application(gateway=gateway)
    with pytest.raises(CredentialExpiredError):
        await app.profile_for_stat_calculation(account())
    assert not app._stats_profile_cache

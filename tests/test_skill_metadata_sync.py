from concurrent.futures import ThreadPoolExecutor
import pytest
from astrbot_plugin_nikke.core.assets.skill_metadata import SkillMetadata

def row(rid=19, icon="new_icon"):
    return {"resource_id": rid, **{key: {"icon": icon} for key in ("skill1_detail", "skill2_detail", "ulti_skill_detail")}}

def test_new_role_persists_and_merges_concurrent_requests(tmp_path):
    calls = []
    sync = SkillMetadata(tmp_path, fetch=lambda url: calls.append(url) or row(), clock=lambda: 100000)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: sync.resolve(19, {}), range(3)))
    assert len(calls) == 1
    assert all(x["burst"] == "new_icon" for x in results)
    rebooted = SkillMetadata(tmp_path, fetch=lambda _: pytest.fail("缓存命中不请求"), clock=lambda: 100010)
    assert rebooted.resolve(19, {}) == results[0]

def test_refresh_failure_keeps_old_and_throttles_retry(tmp_path):
    now = [100000]
    calls = []
    def fetch(url):
        calls.append(url)
        return row() if len(calls) == 1 else row(rid=99)
    sync = SkillMetadata(tmp_path, fetch=fetch, clock=lambda: now[0])
    old = sync.resolve(19, {})
    now[0] += 86401
    assert sync.resolve(19, {}) == old
    assert sync.resolve(19, {}) == old
    assert len(calls) == 2

@pytest.mark.parametrize("data", [row(rid=99), {}, row(icon="../bad"), {"resource_id":19}])
def test_invalid_metadata_never_replaces_fallback(tmp_path, data):
    sync = SkillMetadata(tmp_path, fetch=lambda _: data, clock=lambda: 100000)
    assert sync.resolve(19, {"skill1":"old"}) == {"skill1":"old"}
    assert not (tmp_path/"character-skills/19.json").exists()

def test_remote_disabled_never_fetches(tmp_path):
    sync = SkillMetadata(tmp_path, fetch=lambda _: pytest.fail("离线模式禁止访问网络"))
    assert sync.resolve(19, {"skill1":"old"}, remote=False) == {"skill1":"old"}

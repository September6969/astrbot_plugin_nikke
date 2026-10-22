"""验证宿主包路径下的公告身份及全量无效保护。"""
import importlib
import importlib.util
from pathlib import Path
import sys

import pytest

from astrbot_plugin_nikke.features.announcement.service import AnnouncementService
from astrbot_plugin_nikke.features.announcement.models import AnnouncementRecord


def test_adapters_share_host_namespace_model():
    # 用独立包名模拟 AstrBot 加载插件，不改变标准包导入。
    root = Path(__file__).resolve().parents[1]
    name = "nikke_host_identity_probe"
    spec = importlib.util.spec_from_file_location(name, root / "__init__.py", submodule_search_locations=[str(root)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        sync = importlib.import_module(name + ".features.announcement.synchronization")
        for adapter in ("information_feeds", "official_source"):
            source = importlib.import_module(name + ".integrations.announcement." + adapter)
            row = source.AnnouncementRecord("probe", "标题", "正文", "2026-10-20T00:00:00+00:00")
            assert isinstance(row, sync.AnnouncementRecord)
    finally:
        for key in list(sys.modules):
            if key == name or key.startswith(name + "."):
                del sys.modules[key]


@pytest.mark.asyncio
async def test_all_invalid_records_fail_without_clearing_existing_data(tmp_path):
    service = AnnouncementService(tmp_path)
    service.add_or_update(AnnouncementRecord("existing", "标题", "正文", "2026-10-20T00:00:00+00:00"))
    before = service.last_updated_at
    async def fetch():
        return [object(), object()]
    success, message = await service.sync_from_source(fetch)
    assert not success
    assert "全部无效" in message
    assert service.last_sync_report["success"] is False
    assert service.last_updated_at == before
    assert "existing" in service._records

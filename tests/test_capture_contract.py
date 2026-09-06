"""使用全合成账号验证抓取合同，不访问网络。"""
import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch
from astrbot_plugin_nikke.scripts import capture_union_raid_fixtures as capture


class CaptureTests(IsolatedAsyncioTestCase):
    async def test_payload_and_outputs_do_not_expose_identity(self):
        account = dict(area_id=1, game_openid="synthetic-full-openid", cookie="SYNTHETIC_COOKIE")
        responses = [{"code": 0, "data": {"guild_id": "SYNTHETIC_GUILD"}},
                     {"code": 0, "data": {"level_info": []}},
                     {"code": 0, "data": {"participate_data": []}}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(capture, "NikkeStore") as store, patch.object(capture, "post", AsyncMock(side_effect=responses)) as post:
                store.return_value.list_accounts.return_value = [account]
                await capture.capture(root, root / "out")
                self.assertEqual(post.call_args_list[0].args[3], {"ignore_toast": True})
                for call in post.call_args_list[1:]:
                    self.assertEqual(call.args[3]["intl_open_id"], "synthetic-full-openid")
            output = "".join(p.read_text(encoding="utf-8") for p in (root / "out").glob("*.json"))
            for secret in ("synthetic-full-openid", "SYNTHETIC_COOKIE", "SYNTHETIC_GUILD"):
                self.assertNotIn(secret, output)

    async def test_failed_read_does_not_emit_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(capture, "NikkeStore") as store, patch.object(capture, "post", AsyncMock(side_effect=[
                {"code": 0, "data": {"guild_id": "synthetic"}}, {"code": 212000, "data": None}, {"code": 0, "data": {}}
            ])):
                store.return_value.list_accounts.return_value = [dict(area_id=1, game_openid="synthetic")]
                with self.assertRaises(RuntimeError):
                    await capture.capture(root, root / "out")
                self.assertFalse((root / "out").exists())

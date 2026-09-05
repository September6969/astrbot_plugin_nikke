"""内容版本与日程版本独立持久化回归。"""
import tempfile
from pathlib import Path
from unittest import TestCase
from astrbot_plugin_nikke.announcement_models import AnnouncementRecord
from astrbot_plugin_nikke.announcement_service import AnnouncementService


class VersionTests(TestCase):
    def test_content_only_and_deadline_change_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            service = AnnouncementService(Path(directory))
            def update(body):
                service.add_or_update(AnnouncementRecord("test", "活动", body, "2026-09-05"))
            update("截止至 2026-09-10 23:59")
            update("更新说明。截止至 2026-09-10 23:59")
            self.assertEqual(service.list_announcements()[0].content_version, 2)
            self.assertEqual(service.list_announcements()[0].deadline_version, 1)
            update("截止至 2026-09-11 23:59")
            service = AnnouncementService(Path(directory))
            self.assertEqual(service.list_announcements()[0].deadline_version, 2)
            self.assertEqual(next(iter(service._deadlines.values())).deadline_version, 2)
            update("活动取消")
            service = AnnouncementService(Path(directory))
            self.assertEqual(service.list_announcements()[0].deadline_version, 3)
            self.assertFalse(service._deadlines)

    def test_missing_identity_rejected(self):
        service = AnnouncementService()
        for identifier in ["", "None", " "]:
            with self.assertRaises(ValueError):
                service.add_or_update(AnnouncementRecord(identifier, "标题", "正文", ""))
        self.assertEqual(service.record_count(), 0)

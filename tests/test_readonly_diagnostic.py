"""诊断结果不得泄露输入标识或额外字段。"""
import json
from unittest import TestCase
from astrbot_plugin_nikke.scripts.diagnose_readonly import summarize


class DiagnosticTests(TestCase):
    def test_counts_only(self):
        bundle = {"canonical_openid": "SENTINEL", "xcommon_openid": "SENTINEL",
            "cookie": "COOKIE_SECRET", "qq_id": "QQ_SECRET", "raid": {"participate_data": [
                {"openid": "SENTINEL", "day": 0, "level": 2, "nickname": "PRIVATE_NAME"}]}}
        result = summarize(bundle)
        self.assertEqual(result["raid"]["canonical_matches"], 1)
        self.assertEqual(result["daily"]["writes_performed"], 0)
        for secret in ["SENTINEL", "COOKIE_SECRET", "QQ_SECRET", "PRIVATE_NAME"]:
            self.assertNotIn(secret, json.dumps(result))

    def test_empty_report_is_not_live_evidence(self):
        result = summarize({})
        self.assertEqual(result["raid"]["rows"], 0)
        self.assertFalse(result["daily"]["status_read"])

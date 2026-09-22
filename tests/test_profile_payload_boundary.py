"""验证 Profile payload 已独立，同时保留旧模块的兼容导入。"""

from astrbot_plugin_nikke.ui.payloads.profile import ProfileT2IPayloadBuilder as ExtractedProfileBuilder
from astrbot_plugin_nikke.ui.t2i_payloads import ProfileT2IPayloadBuilder as LegacyProfileBuilder


def test_profile_payload_builder_uses_extracted_module_and_legacy_export():
    assert ExtractedProfileBuilder is LegacyProfileBuilder
    assert ExtractedProfileBuilder.__module__ == "astrbot_plugin_nikke.ui.payloads.profile"

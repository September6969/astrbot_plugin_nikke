"""验证 Profile payload 的规范模块归属。"""

from astrbot_plugin_nikke.ui.payloads.profile import ProfileT2IPayloadBuilder


def test_profile_payload_builder_uses_canonical_page_module():
    assert ProfileT2IPayloadBuilder.__module__ == "astrbot_plugin_nikke.ui.payloads.profile"

# SPDX-License-Identifier: GPL-3.0-or-later
import unittest

from astrbot_plugin_nikke.cookie_utils import parse_cookie


class CookieUtilsTests(unittest.TestCase):
    def test_parse_empty_or_whitespace(self):
        self.assertEqual(parse_cookie(""), {})
        self.assertEqual(parse_cookie("   "), {})

    def test_parse_standard_cookie(self):
        cookie = "game_token=abc123; game_uid=10001; game_openid=openid_xyz"
        parsed = parse_cookie(cookie)
        self.assertEqual(parsed, {
            "game_token": "abc123",
            "game_uid": "10001",
            "game_openid": "openid_xyz",
        })

    def test_parse_cookie_with_special_characters_and_padding(self):
        cookie = " foo=bar=baz ; single_val ; =empty_key; valid=123 "
        parsed = parse_cookie(cookie)
        self.assertEqual(parsed["foo"], "bar=baz")
        self.assertEqual(parsed["valid"], "123")
        self.assertNotIn("", parsed)
        self.assertNotIn("single_val", parsed)

    def test_parse_cookie_preserves_empty_values(self):
        cookie = "token=; uid=100"
        parsed = parse_cookie(cookie)
        self.assertEqual(parsed, {"token": "", "uid": "100"})

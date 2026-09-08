# SPDX-License-Identifier: GPL-3.0-or-later

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeploymentConfigTests(unittest.TestCase):
    def test_caddy_example_does_not_log_one_time_bind_urls(self):
        caddyfile = (ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")

        self.assertIn("reverse_proxy astrbot:6210", caddyfile)
        self.assertNotRegex(caddyfile, r"(?m)^\s*log\s*\{")
        for header in (
            'Strict-Transport-Security "max-age=31536000; includeSubDomains"',
            'X-Content-Type-Options "nosniff"',
            'X-Frame-Options "DENY"',
            'Referrer-Policy "no-referrer"',
            "-Server",
        ):
            with self.subTest(header=header):
                self.assertIn(header, caddyfile)

    def test_compose_publishes_only_proxy_ports_and_mounts_config_read_only(self):
        compose = (ROOT / "deploy" / "docker-compose.caddy.yml").read_text(encoding="utf-8")

        self.assertIn('"80:80"', compose)
        self.assertIn('"443:443"', compose)
        self.assertIn('"443:443/udp"', compose)
        self.assertNotRegex(compose, r"(?m)^\s*-\s*[\"']?[^\r\n\"']*6210:")
        self.assertIn("/etc/caddy/Caddyfile:ro", compose)
        self.assertIn("external: true", compose)


if __name__ == "__main__":
    unittest.main()

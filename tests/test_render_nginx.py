from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops"))

from render_nginx import RenderError, render  # noqa: E402


class NginxRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.template = ROOT / "deploy" / "nginx" / "ibl-course-designer.conf.template"
        self.environment = {
            "PUBLIC_DOMAIN": "adp.example.com",
            "TLS_CERT_PATH": "/etc/tls/fullchain.pem",
            "TLS_KEY_PATH": "/etc/tls/private.key",
            "NGINX_ACCESS_LOG": "/var/log/nginx/access.log",
            "PROXY_CA_CERT_PATH": "/etc/ssl/certs/ca-certificates.crt",
        }

    def test_render_has_https_upstreams_and_query_safe_logs(self) -> None:
        with mock.patch.dict(os.environ, self.environment, clear=True):
            output = render(self.template)
        self.assertIn("server_name adp.example.com;", output)
        self.assertIn("proxy_pass https://qyapi.weixin.qq.com;", output)
        self.assertIn("proxy_pass https://chan.lke.cloud.tencent.com;", output)
        self.assertEqual(output.count("proxy_ssl_verify on;"), 2)
        self.assertIn("proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;", output)
        self.assertIn('"$request_method $uri $server_protocol"', output)
        self.assertNotIn("$request_uri $server_protocol", output)
        self.assertNotIn("$http_referer", output)
        self.assertEqual(output.count("error_log /dev/null crit;"), 2)
        self.assertNotIn("{{", output)

    def test_invalid_domain_is_rejected(self) -> None:
        environment = dict(self.environment, PUBLIC_DOMAIN="bad; include /tmp/file")
        with mock.patch.dict(os.environ, environment, clear=True):
            with self.assertRaises(RenderError):
                render(self.template)

    def test_relative_certificate_path_is_rejected(self) -> None:
        environment = dict(self.environment, TLS_CERT_PATH="cert.pem")
        with mock.patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(RenderError, "absolute Linux path"):
                render(self.template)


if __name__ == "__main__":
    unittest.main()

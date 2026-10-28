"""A Cloudflare block must never be reported to a customer as a revoked licence."""

import io
import unittest
import urllib.error

from core import license_remote


def http_error(code, body):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(body))


class ServiceDenialTest(unittest.TestCase):

    def test_the_services_own_json_is_a_denial(self):
        self.assertTrue(license_remote._is_service_denial(
            http_error(403, b'{"ok":false,"error":"unknown license"}')))

    def test_cloudflare_block_page_is_not(self):
        self.assertFalse(license_remote._is_service_denial(
            http_error(403, b"<html>error code: 1010</html>")))

    def test_plain_text_block_is_not(self):
        self.assertFalse(license_remote._is_service_denial(http_error(403, b"error code: 1010")))

    def test_empty_body_is_not(self):
        self.assertFalse(license_remote._is_service_denial(http_error(403, b"")))

    def test_foreign_json_is_not(self):
        self.assertFalse(license_remote._is_service_denial(
            http_error(403, b'{"message":"blocked by WAF"}')))


if __name__ == "__main__":
    unittest.main()

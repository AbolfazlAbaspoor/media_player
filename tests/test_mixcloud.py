"""
Mixcloud نداره اکسترکتور جستجوی yt-dlp؛ /search/ هم یه صفحه‌ی کاملاً
کلاینت-سایده. حالا API عمومی و بدون کلیدِ api.mixcloud.com/search/ رو
مستقیم می‌گیریم و parse می‌کنیم. بدون شبکه: core.net.fetch_text mock می‌شه.
"""

import json
import unittest
from unittest import mock

from core.services.mixcloud import Mixcloud


SAMPLE_RESPONSE = json.dumps({
    "data": [
        {
            "key": "/dj-shadow/endtroducing/",
            "url": "https://www.mixcloud.com/dj-shadow/endtroducing/",
            "name": "Endtroducing Set",
            "user": {"name": "DJ Shadow", "username": "dj-shadow",
                      "url": "https://www.mixcloud.com/dj-shadow/"},
        },
        {"no_url": True},
    ]
})


class MixcloudSearchStubsTest(unittest.TestCase):

    def test_parses_data_into_stubs(self):
        with mock.patch("core.services.mixcloud.net.fetch_text",
                         return_value=("u", SAMPLE_RESPONSE)):
            stubs = Mixcloud()._search_stubs("jazz", count=10)

        self.assertEqual(len(stubs), 1)
        self.assertEqual(stubs[0]["webpage_url"], "https://www.mixcloud.com/dj-shadow/endtroducing/")
        self.assertEqual(stubs[0]["title"], "Endtroducing Set")
        self.assertEqual(stubs[0]["uploader"], "DJ Shadow")
        self.assertEqual(stubs[0]["channel_url"], "https://www.mixcloud.com/dj-shadow/")

    def test_network_failure_returns_empty_list(self):
        with mock.patch("core.services.mixcloud.net.fetch_text", side_effect=OSError("boom")):
            self.assertEqual(Mixcloud()._search_stubs("jazz", count=10), [])


if __name__ == "__main__":
    unittest.main()

"""
archive.org قبلاً advancedsearch.php (JSON) رو مستقیم به اکسترکتور
عمومی yt-dlp می‌داد و همیشه fail می‌شد. حالا JSON خودمون گرفته و parse
می‌شه، مثل core/services/aparat.py. بدون شبکه: core.net.fetch_text
mock می‌شه.
"""

import json
import unittest
from unittest import mock

from core.services.archive import ArchiveOrg


SAMPLE_RESPONSE = json.dumps({
    "response": {
        "numFound": 2,
        "docs": [
            {"identifier": "jazz_concert_1959", "title": "Jazz Concert 1959", "creator": "Miles Davis"},
            {"identifier": "old_radio_show", "title": ["Old Radio Show", "alt"], "creator": ["Unknown"]},
            {"identifier": "", "title": "no id, must be skipped"},
        ],
    }
})


class ArchiveSearchStubsTest(unittest.TestCase):

    def test_parses_docs_into_stubs(self):
        with mock.patch("core.services.archive.net.fetch_text",
                         return_value=("https://archive.org/advancedsearch.php", SAMPLE_RESPONSE)):
            stubs = ArchiveOrg()._search_stubs("jazz", count=10)

        self.assertEqual(len(stubs), 2)
        self.assertEqual(stubs[0]["id"], "jazz_concert_1959")
        self.assertEqual(stubs[0]["webpage_url"], "https://archive.org/details/jazz_concert_1959")
        self.assertEqual(stubs[0]["title"], "Jazz Concert 1959")
        self.assertEqual(stubs[0]["uploader"], "Miles Davis")
        # عنوان/سازنده‌ی لیستی باید تک‌مقدار بشه.
        self.assertEqual(stubs[1]["title"], "Old Radio Show")
        self.assertEqual(stubs[1]["uploader"], "Unknown")

    def test_respects_count_limit(self):
        with mock.patch("core.services.archive.net.fetch_text",
                         return_value=("u", SAMPLE_RESPONSE)):
            stubs = ArchiveOrg()._search_stubs("jazz", count=1)
        self.assertEqual(len(stubs), 1)

    def test_network_failure_returns_empty_list(self):
        with mock.patch("core.services.archive.net.fetch_text", side_effect=OSError("boom")):
            stubs = ArchiveOrg()._search_stubs("jazz", count=10)
        self.assertEqual(stubs, [])

    def test_malformed_json_returns_empty_list(self):
        with mock.patch("core.services.archive.net.fetch_text", return_value=("u", "not json")):
            stubs = ArchiveOrg()._search_stubs("jazz", count=10)
        self.assertEqual(stubs, [])


if __name__ == "__main__":
    unittest.main()

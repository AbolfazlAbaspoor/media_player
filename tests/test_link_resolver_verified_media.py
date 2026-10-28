"""
core.link_resolver.try_ytdlp باید نتیجه‌ی resolve‌شده رو verified_media=True
علامت بزنه (توضیح کامل: core/services/_ytdlp_service.py::_resolve_entry).
بدون این پرچم، bot.py::_expand_item برای هر لینکِ .m3u8 (لایوهای سایت‌های
دیگه هم، نه فقط یوتیوب) یه دانلودِ کامل و بی‌فایده‌ی اضافه انجام می‌داد.
"""

import unittest
from unittest import mock

from core import link_resolver


class TryYtdlpVerifiedMediaTest(unittest.TestCase):

    def test_single_result_is_marked_verified(self):
        info = {"url": "https://cdn.example.com/live/index.m3u8", "title": "Live"}
        with mock.patch("core.proxy_retry.extract_with_fallback", return_value=info), \
             mock.patch.object(link_resolver, "_domain_needs_proxy", return_value=True):
            result = link_resolver.try_ytdlp("https://example.com/live")
        self.assertTrue(result["verified_media"])

    def test_playlist_entries_are_all_marked_verified(self):
        info = {"entries": [
            {"url": "https://cdn/a.mp3", "title": "a"},
            {"url": "https://cdn/b.mp3", "title": "b"},
        ]}
        with mock.patch("core.proxy_retry.extract_with_fallback", return_value=info), \
             mock.patch.object(link_resolver, "_domain_needs_proxy", return_value=True):
            result = link_resolver.try_ytdlp("https://example.com/playlist")
        self.assertTrue(result["verified_media"])
        for item in result["items"]:
            self.assertTrue(item["verified_media"])

    def test_no_direct_url_returns_none(self):
        with mock.patch("core.proxy_retry.extract_with_fallback", return_value={"title": "x"}), \
             mock.patch.object(link_resolver, "_domain_needs_proxy", return_value=True):
            result = link_resolver.try_ytdlp("https://example.com/nope")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

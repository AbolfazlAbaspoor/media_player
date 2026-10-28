"""
The services moved onto the shared yt-dlp base keep what made them distinct.
Entries here carry their formats, so no network call is made.
"""

import unittest

from core.services._ytdlp_service import YtdlpService
from core.services.instagram import Instagram
from core.services.soundcloud import SoundCloud
from core.services.tiktok import TikTok


def full_entry(**fields):
    entry = {"id": "1", "formats": [{"url": "https://cdn/stream"}], "webpage_url": "https://page"}
    entry.update(fields)
    return entry


class SharedBaseTest(unittest.TestCase):

    def test_all_three_inherit_the_base(self):
        for cls in (Instagram, SoundCloud, TikTok):
            self.assertTrue(issubclass(cls, YtdlpService), cls.__name__)

    def test_foreign_links_are_refused(self):
        self.assertIsNone(SoundCloud().search("https://www.youtube.com/watch?v=x"))
        self.assertIsNone(TikTok().search("https://soundcloud.com/a/b"))

    def test_soundcloud_plays_after_one_result(self):
        self.assertEqual(SoundCloud.SEARCH_FIRST_COUNT, 1)
        self.assertEqual(SoundCloud.SEARCH_PREFIX, "scsearch")

    def test_resolved_entries_are_marked_verified_media(self):
        # bot.py::_expand_item از این پرچم استفاده می‌کنه تا برای لینکی که
        # yt-dlp خودش از formats انتخابش کرده (مثلاً یه .m3u8 لایو)، دوباره
        # کل فایل رو دانلود نکنه فقط برای تشخیصِ «واقعاً HLS هست یا نه».
        resolved = SoundCloud()._resolve_entry(full_entry())
        self.assertTrue(resolved["verified_media"])


class TikTokTest(unittest.TestCase):

    def test_untitled_video_gets_the_uploader_name(self):
        resolved = TikTok()._resolve_entry(full_entry(title=None, uploader="scout2015"))
        self.assertEqual(resolved["title"], "TikTok by scout2015")

    def test_a_real_title_is_kept(self):
        resolved = TikTok()._resolve_entry(full_entry(title="Dance", uploader="x"))
        self.assertEqual(resolved["title"], "Dance")

    def test_text_is_not_a_search(self):
        self.assertIsNone(TikTok().search("funny cats"))


class InstagramTest(unittest.TestCase):

    def test_description_stands_in_for_a_missing_title(self):
        resolved = Instagram()._resolve_entry(full_entry(title=None, description="sunset at the beach"))
        self.assertEqual(resolved["title"], "sunset at the beach")

    def test_long_titles_are_cut(self):
        resolved = Instagram()._resolve_entry(full_entry(title="x" * 500))
        self.assertEqual(len(resolved["title"]), 100)

    def test_channel_url_is_built_from_the_uploader(self):
        resolved = Instagram()._resolve_entry(full_entry(title="t", uploader="nasa"))
        self.assertEqual(resolved["channel_url"], "https://www.instagram.com/nasa/")

    def test_text_search_explains_itself(self):
        with self.assertRaises(ValueError) as caught:
            Instagram().search("some words")
        self.assertIn("no text search", str(caught.exception))

    def test_listing_methods_used_by_commands_still_exist(self):
        for name in ("get_channel_all", "get_hashtag_feed"):
            self.assertTrue(callable(getattr(Instagram(), name, None)), name)
        self.assertEqual(Instagram().get_hashtag_feed("#"), [])


class FirstPlayableTest(unittest.TestCase):
    """A playlist whose first video is gone must still play."""

    def _service_with(self, playable_ids):
        svc = SoundCloud()
        svc._resolve_entry = lambda entry, interactive=False: (
            {"id": entry["id"], "url": "https://cdn/" + entry["id"], "title": entry["id"]}
            if entry["id"] in playable_ids else None)
        return svc

    def test_skips_a_removed_first_item(self):
        entries = [{"id": "gone"}, {"id": "private"}, {"id": "ok"}, {"id": "later"}]
        index, first = self._service_with({"ok", "later"})._first_playable(entries)
        self.assertEqual((index, first["id"]), (2, "ok"))

    def test_gives_up_after_the_limit(self):
        entries = [{"id": str(i)} for i in range(10)]
        svc = self._service_with({"9"})
        self.assertEqual(svc._first_playable(entries), (None, None))

    def test_growth_continues_after_the_played_item(self):
        from unittest import mock
        svc = self._service_with({"b"})
        info = {"_type": "playlist", "entries": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}
        with mock.patch("core.proxy_retry.extract_with_fallback", return_value=info):
            result = svc.search("https://soundcloud.com/x/sets/y")
        self.assertEqual(result[0]["id"], "b")
        self.assertEqual(svc.get_playlist_growth_info()[2], 2)


if __name__ == "__main__":
    unittest.main()

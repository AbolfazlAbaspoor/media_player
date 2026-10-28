"""
bot.py::_expand_item باید resolve_playlist (که یه دانلودِ کاملِ شبکه‌ایه) رو
صدا نزنه وقتی لینک از قبل با verified_media=True از یه resolver مبتنی بر
yt-dlp اومده -- این دقیقاً مسیر داغِ لایوهای یوتیوب/HLS رو چند ثانیه سریع‌تر
می‌کنه. برای لینک‌های تأییدنشده (خام/پسوند-حدسی) رفتار قبلی دست‌نخورده می‌مونه.

توضیح کامل: bot.py::_expand_item / core/services/_ytdlp_service.py::_resolve_entry.
"""

import unittest
from unittest import mock

import bot


class ExpandItemVerifiedMediaTest(unittest.TestCase):

    def test_verified_media_skips_the_playlist_probe(self):
        url = "https://manifest.googlevideo.com/api/manifest/hls_playlist/.../index.m3u8"
        with mock.patch.object(bot, "resolve_playlist") as probe:
            result = bot._expand_item(url, "Live title", "https://youtube.com/watch?v=x",
                                       True, verified=True)
        probe.assert_not_called()
        self.assertEqual(result, [(url, "Live title", "https://youtube.com/watch?v=x", True)])

    def test_unverified_link_still_goes_through_the_probe(self):
        url = "http://example.com/list.m3u8"
        with mock.patch.object(bot, "resolve_playlist", return_value=[url]) as probe:
            result = bot._expand_item(url, "T", "P", True, verified=False)
        probe.assert_called_once_with(url)
        self.assertEqual(result, [(url, "T", "P", True)])

    def test_default_is_unverified_for_backward_compatibility(self):
        url = "http://example.com/list.m3u8"
        with mock.patch.object(bot, "resolve_playlist", return_value=[url]) as probe:
            bot._expand_item(url, "T", "P", True)
        probe.assert_called_once()

    def test_an_unverified_simple_list_still_expands_into_several_tracks(self):
        # یه فایل .m3u ساده (نه HLS واقعی) که چند لینک جداست -- باید مثل
        # قبل expand بشه، چون verified=False.
        with mock.patch.object(bot, "resolve_playlist", return_value=["a", "b"]):
            result = bot._expand_item("http://x/list.m3u", "T", "P", True, verified=False)
        self.assertEqual(result, [("a", None, None, True), ("b", None, None, True)])


class LoadAndPlayVerifiedUrlCollectionTest(unittest.TestCase):
    """
    load_and_play باید verified_media رو فقط از دیکشنری‌هایی که واقعاً اون
    کلید رو دارن جمع کنه و به _expand_item پاس بده -- بدون اینکه بقیه‌ی
    منطقش (که تست جدایی داره) رو لمس کنه.
    """

    def test_verified_flag_travels_from_item_dict_to_expand_item(self):
        items = [
            {"url": "https://cdn/live.m3u8", "title": "Live", "verified_media": True},
            {"url": "http://x/list.m3u8", "title": "Raw"},
        ]
        calls = []

        def fake_expand(url, title, public_url, private, verified=False):
            calls.append((url, verified))
            return [(url, title, public_url, private)]

        fake_track = mock.Mock(url="https://cdn/live.m3u8", title="Live",
                                public_url=None, private=True)
        fake_queue = mock.Mock()
        fake_queue.replace.return_value = (2, fake_track)
        fake_queue.meta.return_value = []

        with mock.patch.object(bot, "_expand_item", side_effect=fake_expand), \
             mock.patch.object(bot, "documentary"), \
             mock.patch.object(bot, "iptv"), \
             mock.patch.object(bot, "history"), \
             mock.patch.object(bot, "_roam_clear_deadline"), \
             mock.patch.object(bot, "bot") as fake_bot, \
             mock.patch.object(bot, "player") as fake_player:
            fake_bot.search_lock = mock.MagicMock()
            fake_bot.playback_lock = mock.MagicMock()
            fake_bot.queue = fake_queue
            fake_bot.playback_mode = 2
            fake_bot.search_session = {}
            fake_bot.playlist_growth_session = {}
            fake_player.is_paused = False
            bot.load_and_play(items, private=True)

        self.assertIn(("https://cdn/live.m3u8", True), calls)
        self.assertIn(("http://x/list.m3u8", False), calls)


if __name__ == "__main__":
    unittest.main()

"""
باگ: af/aff فقط public_url (لینکِ صفحه) رو ذخیره می‌کنن، چون لینکِ استریمِ
واقعیِ یوتیوب/ساندکلاد/... چند ساعت بعد منقضی می‌شه (core/accounts.py).
ولی sf.py همون لینکِ صفحه رو مستقیم به‌عنوانِ "url" به load_and_play می‌داد
-- و mpv هوکِ yt-dlpِ خودش رو عمداً خاموش داره (core/mpv/player.py)، پس
فروریتِ هر سرویسی (یوتیوب و امثالش) اصلاً پخش نمی‌شد. حالا هر آیتم موقعِ
پخش دوباره resolve می‌شه (core.command_helpers.resolve_playable)، دقیقاً
مثلِ یه لینکِ تازه‌پیست‌شده.
"""

import threading
import unittest
from unittest import mock

from core import command_helpers
from tests.helpers import load_command

sf = load_command("sf")


class ImmediateThread:
    """جایگزینِ threading.Thread: بلافاصله و همزمان اجرا می‌کنه، برای تست."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)

    def join(self, timeout=None):
        pass


def _ctx(bot):
    return {"bot": bot, "uid": 1, "nickname": "N", "username": "u", "args": []}


class FakeBot:
    def __init__(self):
        self.channel = []
        self.t = mock.Mock()
        self.channel_broadcast = lambda text: self.channel.append(text)
        self.player = mock.Mock()
        self.load_and_play_calls = []

    def load_and_play(self, items, private=True, service_name=None):
        self.load_and_play_calls.append({"items": items, "private": private, "service_name": service_name})
        return len(items)


class FavoritesResolveTest(unittest.TestCase):
    def setUp(self):
        self.thread_patch = mock.patch.object(threading, "Thread", ImmediateThread)
        self.thread_patch.start()

    def tearDown(self):
        self.thread_patch.stop()

    def test_stored_page_link_is_resolved_to_a_real_stream_at_play_time(self):
        bot = FakeBot()
        entries = [{"url": "https://www.youtube.com/watch?v=abc", "public_url": "https://www.youtube.com/watch?v=abc",
                    "title": "Song", "time": 42}]

        resolved_item = {"url": "https://real-stream.example/x.webm", "title": "Song",
                         "public_url": "https://www.youtube.com/watch?v=abc", "info": {"a": 1}}
        with mock.patch.object(command_helpers, "resolve_playable",
                               return_value=(resolved_item, "youtube")) as resolve:
            sf._play_entries(bot, _ctx(bot), entries)

        resolve.assert_called_once_with(bot, "https://www.youtube.com/watch?v=abc")
        call = bot.load_and_play_calls[0]
        self.assertEqual(call["items"][0]["url"], "https://real-stream.example/x.webm")
        self.assertEqual(call["service_name"], "youtube")
        bot.player.seek_to.assert_called_once_with(42)

    def test_entry_that_fails_to_resolve_is_skipped_not_fatal(self):
        bot = FakeBot()
        entries = [
            {"url": "https://dead.example/1", "public_url": "https://dead.example/1", "title": "Dead", "time": 10},
            {"url": "https://good.example/2", "public_url": "https://good.example/2", "title": "Good", "time": 5},
        ]

        def fake_resolve(bot_, url):
            if "dead" in url:
                return {"url": None}, None
            return {"url": "https://real.example/2.webm", "title": "Good",
                    "public_url": url, "info": None}, "soundcloud"

        with mock.patch.object(command_helpers, "resolve_playable", side_effect=fake_resolve):
            sf._play_entries(bot, _ctx(bot), entries)

        call = bot.load_and_play_calls[0]
        self.assertEqual(len(call["items"]), 1)
        self.assertEqual(call["items"][0]["url"], "https://real.example/2.webm")
        # resume باید مالِ همون آیتمی باشه که واقعاً پخش شد (۵)، نه اولیِ خراب (۱۰).
        bot.player.seek_to.assert_called_once_with(5)

    def test_all_entries_failing_to_resolve_notifies_instead_of_crashing(self):
        bot = FakeBot()
        entries = [{"url": "https://dead.example/1", "public_url": "https://dead.example/1",
                    "title": "Dead", "time": 0}]
        with mock.patch.object(command_helpers, "resolve_playable", return_value=({"url": None}, None)):
            sf._play_entries(bot, _ctx(bot), entries)
        self.assertEqual(bot.load_and_play_calls, [])
        self.assertEqual(len(bot.channel), 1)

    def test_direct_media_favorite_still_plays_unchanged(self):
        # فروریتی که از اول لینکِ مستقیم بوده (نه صفحه‌ی یه سرویس) باید
        # دست‌نخورده کار کنه.
        bot = FakeBot()
        entries = [{"url": "https://cdn.example/song.mp3", "public_url": "https://cdn.example/song.mp3",
                    "title": "MP3", "time": 0}]
        with mock.patch.object(command_helpers, "resolve_playable",
                               return_value=({"url": "https://cdn.example/song.mp3", "title": "MP3",
                                             "public_url": "https://cdn.example/song.mp3"}, None)):
            sf._play_entries(bot, _ctx(bot), entries)
        self.assertEqual(bot.load_and_play_calls[0]["items"][0]["url"], "https://cdn.example/song.mp3")


class ResolvePlayableTest(unittest.TestCase):
    """core.command_helpers.resolve_playable خودش."""

    def test_owning_service_result_is_used(self):
        service = mock.Mock()
        service.owns_url.return_value = True
        service.URL_MARKERS = ("example.com",)
        service.search.return_value = [{"url": "https://stream/x", "title": "T", "public_url": "https://example.com/x"}]
        bot = mock.Mock(services={"svc": service})
        item, name = command_helpers.resolve_playable(bot, "https://example.com/x")
        self.assertEqual(item["url"], "https://stream/x")
        self.assertEqual(name, "svc")

    def test_falls_back_to_generic_pipeline_when_no_service_owns_it(self):
        bot = mock.Mock(services={})
        with mock.patch.object(command_helpers, "_generic_item",
                               return_value={"url": "https://direct/file.mp3", "title": None}) as generic:
            item, name = command_helpers.resolve_playable(bot, "https://direct/file.mp3")
        generic.assert_called_once_with("https://direct/file.mp3")
        self.assertEqual(item["url"], "https://direct/file.mp3")
        self.assertIsNone(name)

    def test_last_resort_returns_the_raw_url(self):
        bot = mock.Mock(services={})
        with mock.patch.object(command_helpers, "_generic_item", return_value=None):
            item, name = command_helpers.resolve_playable(bot, "https://unknown.example/x")
        self.assertEqual(item["url"], "https://unknown.example/x")


if __name__ == "__main__":
    unittest.main()

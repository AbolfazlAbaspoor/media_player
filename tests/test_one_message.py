"""
E12: exactly two lines to the channel per action -- an "X searched/
requested a link" acknowledgement, then a compact "Now playing" line once
the track actually starts. Never the requester's raw link/query text
leaking anyone's private URL, and no separate private acknowledgement
(the ack itself now goes to the channel so the rest of the channel isn't
left guessing while a slow search runs).
"""

import os
import unittest
from unittest import mock

from core import command_helpers
from tests.helpers import load_command

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeBot:
    def __init__(self, service_result):
        self.channel = []
        self.private = []
        self.t = mock.Mock()
        self.t.user_message.side_effect = lambda uid, text: self.private.append(text)
        self.t.channel_message.side_effect = lambda text: self.channel.append(text)
        self.channel_broadcast = lambda text: self.channel.append(text)
        self.channel_messages_enabled = True
        service = mock.Mock()
        service.search.return_value = service_result
        service.get_playlist_growth_info.return_value = None
        self.services = {"youtube": service, "soundcloud": service}
        self.current_service_index = 0
        self.playback_mode = "normal"
        self.single_track_modes = ()
        self.last_started = None
        self.last_channel_url = None
        self.track_meta = []
        self.queue = mock.Mock(index=0, length=1, expected_total=0)
        self.player = mock.Mock(now_playing_title=None, duration_seconds=200)
        self.playlist_growth_session = {}
        self.search_lock = mock.MagicMock()
        self.license = None

    def load_and_play(self, items, private=True, service_name=None):
        items = items if isinstance(items, list) else [items]
        self.track_meta = [{"title": i.get("title"), "public_url": i.get("public_url"),
                            "private": private, "fallback_label": i.get("url"),
                            "service": service_name} for i in items]
        return len(items)

    def format_time(self, s):
        return "3:20"


class OneMessageTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from core import i18n
        i18n.load_languages()
        i18n.set_language("en")

    def setUp(self):
        mock.patch("core.command_helpers._wait_for_duration", return_value=200).start()
        mock.patch("core.manager.searchable_service_names", return_value=["youtube"]).start()
        mock.patch("core.command_helpers.start_growth_session",
                   side_effect=lambda bot, *a: a[-1]).start()

    def tearDown(self):
        mock.patch.stopall()

    def _ctx(self, bot, args):
        return {"bot": bot, "uid": 7, "nickname": "Ali", "username": "ali", "args": args}

    def test_search_sends_exactly_two_channel_messages(self):
        bot = FakeBot({"url": "https://g/v", "title": "Shadmehr - Abi", "public_url": "https://youtu.be/x"})
        load_command("p").run(self._ctx(bot, ["shadmehr"]))
        self.assertEqual(len(bot.channel), 2, bot.channel)
        self.assertIn("shadmehr", bot.channel[0])
        self.assertIn("Ali", bot.channel[0])
        self.assertIn("Shadmehr - Abi", bot.channel[1])
        self.assertEqual(len(bot.private), 0)   # ack now goes to the channel, not privately

    def test_pasted_link_never_leaks_the_url(self):
        link = "https://secret.example/private.mp3"
        bot = FakeBot({"url": link, "title": None, "public_url": link})
        load_command("p").run(self._ctx(bot, [link]))
        self.assertEqual(len(bot.channel), 2, bot.channel)
        self.assertNotIn("secret.example", " ".join(bot.channel + bot.private))
        self.assertTrue(bot.track_meta[0]["private"])

    def test_u_does_not_announce_the_link(self):
        link = "https://secret.example/stream.m3u8"
        bot = FakeBot(None)
        with mock.patch("core.link_resolver.looks_like_direct_media", return_value=True):
            load_command("u").run(self._ctx(bot, [link]))
        self.assertNotIn("secret.example", " ".join(bot.channel + bot.private))
        self.assertEqual(len(bot.channel), 2, bot.channel)

    def test_playlist_total_is_not_lost(self):
        bot = FakeBot({"url": "https://g/v", "title": "Mix", "public_url": "https://youtu.be/x"})
        bot.queue = mock.Mock(index=0, length=1, expected_total=438)
        command_helpers.broadcast_now_playing(bot)
        self.assertIn("438", bot.channel[-1])

    def test_ap_link_is_private_and_unannounced(self):
        link = "https://www.aparat.com/v/abc"
        bot = FakeBot({"url": "https://cdn/x.mp4", "title": "Clip", "public_url": link})
        command_helpers.run_search_and_play_command(
            self._ctx(bot, [link]), lambda: bot.services["youtube"].search(link), "youtube",
            announce_key="search_requested", announce_query=link)
        self.assertTrue(bot.track_meta[0]["private"])
        self.assertNotIn("aparat.com", " ".join(bot.channel + bot.private))


if __name__ == "__main__":
    unittest.main()

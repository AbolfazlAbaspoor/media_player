"""
E8/E13: link handling must be smart (try a loaded service's richer path
before falling back to the generic link_resolver pipeline) and unified
(pasting a bare link must behave exactly like `u <link>` -- one shared
code path, core.command_helpers.run_link_command).
"""

import os
import unittest
from unittest import mock
from tests.helpers import load_command

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeService:
    """A minimal stand-in for a core.services._ytdlp_service.YtdlpService subclass."""

    def __init__(self, name, markers, result):
        self.SERVICE_NAME = name
        self.URL_MARKERS = markers
        self._result = result
        self.search_calls = []

    def owns_url(self, url):
        low = (url or "").lower()
        return any(m in low for m in self.URL_MARKERS)

    def search(self, url):
        self.search_calls.append(url)
        return self._result

    def get_playlist_growth_info(self):
        return None


class FakeBot:
    def __init__(self, services=None):
        self.channel = []
        self.private = []
        self.t = mock.Mock()
        self.t.user_message.side_effect = lambda uid, text: self.private.append(text)
        self.t.channel_message.side_effect = lambda text: self.channel.append(text)
        self.channel_broadcast = lambda text: self.channel.append(text)
        self.channel_messages_enabled = True
        self.services = services or {}
        self.current_service_index = 0
        self.last_started = None
        self.last_channel_url = None
        self.track_meta = []
        self.queue = mock.Mock(index=0, length=1, expected_total=0)
        self.player = mock.Mock(now_playing_title=None, duration_seconds=200)
        self.playlist_growth_session = {}
        self.search_lock = mock.MagicMock()
        self.license = None
        self.load_and_play_calls = []

    def load_and_play(self, items, private=True, service_name=None):
        self.load_and_play_calls.append((items, private, service_name))
        items = items if isinstance(items, list) else [items]
        self.track_meta = [{"title": i.get("title"), "public_url": i.get("public_url"),
                            "private": private, "fallback_label": i.get("url"),
                            "service": service_name} for i in items]
        return len(items)

    def format_time(self, s):
        return "3:20"


def _ctx(bot, uid=7, nickname="Ali", username="ali"):
    return {"bot": bot, "uid": uid, "nickname": nickname, "username": username}


class SmartLinkHandlingTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from core import i18n
        i18n.load_languages()
        i18n.set_language("en")

    def setUp(self):
        mock.patch("core.command_helpers._wait_for_duration", return_value=200).start()
        mock.patch("core.command_helpers.start_growth_session",
                   side_effect=lambda bot, *a: a[-1]).start()

    def tearDown(self):
        mock.patch.stopall()

    # -------------------------------------------------- service-first resolution

    def test_url_a_loaded_service_owns_goes_through_that_service(self):
        from core import command_helpers, link_resolver

        yt_result = {"url": "https://cdn/x", "title": "Real Title",
                      "public_url": "https://youtube.com/watch?v=abc", "channel_url": "https://youtube.com/@ch"}
        youtube = FakeService("youtube", ("youtube.com", "youtu.be"), yt_result)
        bot = FakeBot({"youtube": youtube})

        with mock.patch.object(link_resolver, "resolve") as generic_resolve, \
             mock.patch.object(link_resolver, "looks_like_direct_media") as direct_check:
            command_helpers.run_link_command(bot, _ctx(bot), "https://youtube.com/watch?v=abc")
            generic_resolve.assert_not_called()
            direct_check.assert_not_called()

        self.assertEqual(youtube.search_calls, ["https://youtube.com/watch?v=abc"])
        self.assertEqual(len(bot.load_and_play_calls), 1)
        items, private, service_name = bot.load_and_play_calls[0]
        self.assertEqual(service_name, "youtube")
        self.assertTrue(private)
        self.assertEqual(bot.last_channel_url, "https://youtube.com/@ch")

    def test_more_specific_marker_wins_over_generic_one(self):
        """music.youtube.com must resolve to youtubemusic, not youtube."""
        from core import command_helpers

        yt_result = {"url": "https://cdn/generic", "title": "Wrong service"}
        ytm_result = {"url": "https://cdn/music", "title": "Right service"}
        youtube = FakeService("youtube", ("youtube.com", "youtu.be"), yt_result)
        youtubemusic = FakeService("youtubemusic", ("music.youtube.com",), ytm_result)
        # dict order mirrors the real loader (alphabetical filenames: youtube.py
        # before youtubemusic.py), so "youtube" is checked first.
        bot = FakeBot({"youtube": youtube, "youtubemusic": youtubemusic})

        command_helpers.run_link_command(bot, _ctx(bot), "https://music.youtube.com/watch?v=abc")

        self.assertEqual(youtubemusic.search_calls, ["https://music.youtube.com/watch?v=abc"])
        self.assertEqual(youtube.search_calls, [])
        _items, _private, service_name = bot.load_and_play_calls[0]
        self.assertEqual(service_name, "youtubemusic")

    def test_url_no_service_claims_falls_through_to_generic_pipeline(self):
        from core import command_helpers, link_resolver

        youtube = FakeService("youtube", ("youtube.com", "youtu.be"), None)
        bot = FakeBot({"youtube": youtube})
        url = "https://random-blog.example/post/123"

        with mock.patch.object(link_resolver, "looks_like_direct_media", return_value=False), \
             mock.patch.object(link_resolver, "resolve",
                                return_value={"url": "https://cdn/found.mp3", "title": None,
                                              "public_url": url}) as generic_resolve:
            command_helpers.run_link_command(bot, _ctx(bot), url)
            generic_resolve.assert_called_once_with(url)

        self.assertEqual(youtube.search_calls, [])  # never asked -- it doesn't own this URL
        items, private, service_name = bot.load_and_play_calls[0]
        self.assertIsNone(service_name)
        self.assertTrue(private)

    def test_direct_media_link_with_no_owning_service_skips_resolve(self):
        from core import command_helpers, link_resolver

        bot = FakeBot({})
        url = "https://cdn.example.com/track.mp3"

        with mock.patch.object(link_resolver, "resolve") as generic_resolve:
            command_helpers.run_link_command(bot, _ctx(bot), url)
            generic_resolve.assert_not_called()

        items, private, service_name = bot.load_and_play_calls[0]
        self.assertTrue(private)

    # -------------------------------------------------- unification (u vs. bare paste)

    def test_u_and_bare_paste_are_byte_identical_for_a_service_url(self):
        """
        commands/u.py::run() and bot.py's pasted-link branch both now call
        core.command_helpers.run_link_command with the same ctx shape --
        this proves they produce the exact same channel messages and the
        exact same load_and_play call for the same input.
        """
        from core import command_helpers

        url = "https://soundcloud.com/artist/track"
        result = {"url": "https://cdn/audio", "title": "Some Track", "public_url": url}

        def run_via_u(bot):
            load_command("u").run({"bot": bot, "uid": 7, "nickname": "Ali", "username": "ali", "args": [url]})

        def run_via_paste(bot):
            # Mirrors bot.py::on_user_msg's link_ctx exactly.
            link_ctx = {"uid": 7, "nickname": "Ali", "username": "ali", "bot": bot}
            command_helpers.run_link_command(bot, link_ctx, url)

        bot_u = FakeBot({"soundcloud": FakeService("soundcloud", ("soundcloud.com",), dict(result))})
        run_via_u(bot_u)

        bot_paste = FakeBot({"soundcloud": FakeService("soundcloud", ("soundcloud.com",), dict(result))})
        run_via_paste(bot_paste)

        self.assertEqual(bot_u.channel, bot_paste.channel)
        self.assertEqual(bot_u.private, bot_paste.private)
        self.assertEqual(
            [(items, private, name) for items, private, name in bot_u.load_and_play_calls],
            [(items, private, name) for items, private, name in bot_paste.load_and_play_calls],
        )

    def test_u_and_bare_paste_are_byte_identical_for_a_generic_url(self):
        from core import command_helpers, link_resolver

        url = "https://random-blog.example/post/123"
        found = {"url": "https://cdn/found.mp3", "title": None, "public_url": url}

        def run_via_u(bot):
            with mock.patch.object(link_resolver, "looks_like_direct_media", return_value=False), \
                 mock.patch.object(link_resolver, "resolve", return_value=dict(found)):
                load_command("u").run({"bot": bot, "uid": 7, "nickname": "Ali", "username": "ali", "args": [url]})

        def run_via_paste(bot):
            link_ctx = {"uid": 7, "nickname": "Ali", "username": "ali", "bot": bot}
            with mock.patch.object(link_resolver, "looks_like_direct_media", return_value=False), \
                 mock.patch.object(link_resolver, "resolve", return_value=dict(found)):
                command_helpers.run_link_command(bot, link_ctx, url)

        bot_u = FakeBot({})
        run_via_u(bot_u)
        bot_paste = FakeBot({})
        run_via_paste(bot_paste)

        self.assertEqual(bot_u.channel, bot_paste.channel)
        self.assertEqual(bot_u.private, bot_paste.private)
        self.assertEqual(bot_u.load_and_play_calls, bot_paste.load_and_play_calls)

    def test_pasted_link_never_leaks_the_url_via_shared_path(self):
        from core import command_helpers, link_resolver

        link = "https://secret.example/private.mp3"
        bot = FakeBot({})
        with mock.patch.object(link_resolver, "looks_like_direct_media", return_value=True):
            command_helpers.run_link_command(bot, _ctx(bot), link)

        self.assertNotIn("secret.example", " ".join(bot.channel + bot.private))
        self.assertTrue(bot.track_meta[0]["private"])

    # -------------------------------------------------- never give up while something could play

    def test_service_finds_nothing_then_generic_pipeline_plays(self):
        from core import command_helpers, link_resolver

        empty = FakeService("youtube", ("youtube.com",), None)
        bot = FakeBot({"youtube": empty})
        url = "https://youtube.com/watch?v=dead"
        found = {"url": "https://cdn/found.mp4", "title": "T", "public_url": url}
        with mock.patch.object(link_resolver, "looks_like_direct_media", return_value=False), \
             mock.patch.object(link_resolver, "resolve", return_value=found) as generic:
            command_helpers.run_link_command(bot, _ctx(bot), url)
            generic.assert_called_once_with(url)
        self.assertEqual(len(bot.load_and_play_calls), 1)
        self.assertEqual(bot.load_and_play_calls[0][0], found)

    def test_service_raising_also_falls_back_to_generic(self):
        from core import command_helpers, link_resolver

        svc = FakeService("youtube", ("youtube.com",), None)
        svc.search = mock.Mock(side_effect=RuntimeError("boom secret"))
        bot = FakeBot({"youtube": svc})
        with mock.patch.object(link_resolver, "looks_like_direct_media", return_value=True):
            command_helpers.run_link_command(bot, _ctx(bot), "https://youtube.com/watch?v=x.mp3")
        self.assertEqual(len(bot.load_and_play_calls), 1)

    def test_nothing_resolves_hands_raw_url_to_player(self):
        from core import command_helpers, link_resolver

        bot = FakeBot({})
        url = "http://127.0.0.1:8123/somefile"
        with mock.patch.object(link_resolver, "resolve", return_value=None), \
             mock.patch.object(command_helpers, "_confirm_playback", return_value=True):
            command_helpers.run_link_command(bot, _ctx(bot), url)
        items, private, _name = bot.load_and_play_calls[0]
        self.assertEqual(items["url"], url)
        self.assertTrue(private)

    def test_raw_handoff_rejected_by_player_reports_short_message_without_url(self):
        from core import command_helpers, link_resolver

        bot = FakeBot({})
        url = "http://secret.example:9/nothing"
        with mock.patch.object(link_resolver, "resolve", return_value=None), \
             mock.patch.object(command_helpers, "_confirm_playback", return_value=False):
            command_helpers.run_link_command(bot, _ctx(bot), url)
        joined = " ".join(bot.channel + bot.private)
        self.assertNotIn("secret.example", joined)
        self.assertEqual(len(bot.channel), 2)  # ack + unplayable
        self.assertNotIn("Traceback", joined)

    def test_generic_playlist_items_are_all_queued(self):
        from core import command_helpers, link_resolver

        bot = FakeBot({})
        items = [{"url": f"https://cdn/{n}.mp3", "title": str(n)} for n in range(3)]
        found = dict(items[0], items=items)
        with mock.patch.object(link_resolver, "resolve", return_value=found):
            command_helpers.run_link_command(bot, _ctx(bot), "https://site.example/list")
        self.assertEqual(bot.load_and_play_calls[0][0], items)


class ProbeAndScanTest(unittest.TestCase):

    def test_classify_probe(self):
        from core import link_resolver as lr
        self.assertEqual(lr.classify_probe("audio/mpeg", b""), "media")
        self.assertEqual(lr.classify_probe("application/vnd.apple.mpegurl", b""), "media")
        self.assertEqual(lr.classify_probe("text/html", b"<html>"), "html")
        self.assertEqual(lr.classify_probe("application/octet-stream", b"ID3\x04"), "media")
        self.assertEqual(lr.classify_probe("application/octet-stream", b"\xff\xfb\x90"), "media")
        self.assertEqual(lr.classify_probe("", b"  <!DOCTYPE html>"), "html")
        self.assertEqual(lr.classify_probe("application/octet-stream", b"zzzz"), "unknown")

    def test_resolve_extensionless_media_via_probe(self):
        from core import link_resolver as lr
        with mock.patch.object(lr, "probe_details",
                               return_value=("media", "http://h:8000/name", "audio/mpeg", b"")), \
             mock.patch.object(lr, "try_ytdlp") as yt:
            item = lr.resolve("http://h:8000/name")
        yt.assert_not_called()
        self.assertEqual(item["url"], "http://h:8000/name")

    def test_html_scan_tags_json_ld_and_escaped_json(self):
        from core import html_media_scan as h
        base = "https://x.example/p/1"
        self.assertEqual(h.find_media('<video src="/v/a.mp4"></video>', base), "https://x.example/v/a.mp4")
        self.assertEqual(h.find_media('{"contentUrl": "https://c.example/s.mp3"}', base), "https://c.example/s.mp3")
        self.assertEqual(h.find_media('var c={"u":"https:\\/\\/c.example\\/live.m3u8?x=1"}', base),
                         "https://c.example/live.m3u8?x=1")
        self.assertIsNone(h.find_media("<p>nothing</p>", base))

    def test_iframes_found_and_resolved_one_level(self):
        from core import html_media_scan as h, link_resolver as lr
        page = '<iframe src="https://www.youtube.com/embed/jNQXAC9IVRw"></iframe>'
        self.assertEqual(h.find_iframes(page, "https://x.example/"), ["https://www.youtube.com/embed/jNQXAC9IVRw"])
        scan = h.PageScan(None, [], ["https://www.youtube.com/embed/jNQXAC9IVRw"], None, "https://x.example/post")
        with mock.patch.object(h, "scan_detailed", return_value=scan), \
             mock.patch.object(lr, "try_ytdlp", return_value={"url": "https://cdn/y", "title": "t", "public_url": "e"}):
            item = lr.try_html_scan("https://x.example/post")
        self.assertEqual(item["url"], "https://cdn/y")
        self.assertEqual(item["public_url"], "https://x.example/post")

    def test_start_index_for_watch_with_list(self):
        from core.services._ytdlp_service import YtdlpService
        entries = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        self.assertEqual(YtdlpService._start_index("https://youtube.com/watch?v=c&list=PL1", entries), 2)
        self.assertEqual(YtdlpService._start_index("https://youtube.com/playlist?list=PL1", entries), 0)
        self.assertEqual(YtdlpService._start_index("https://youtube.com/watch?v=zz&list=PL1", entries), 0)

    def test_bare_link_without_scheme_is_detected(self):
        # هدف: دیگه نیازی به u/iru نباشه -- لینکِ بدونِ http:// هم پیست
        # خام باید شناسایی بشه.
        from core import command_helpers
        self.assertTrue(command_helpers.looks_like_bare_link("instagram.com/reel/xyz"))
        self.assertTrue(command_helpers.looks_like_bare_link("youtu.be/abc123"))
        self.assertTrue(command_helpers.looks_like_bare_link("www.example.com/path?q=1"))
        self.assertFalse(command_helpers.looks_like_bare_link("hello world"))
        self.assertFalse(command_helpers.looks_like_bare_link("n"))
        self.assertFalse(command_helpers.looks_like_bare_link(""))
        self.assertFalse(command_helpers.looks_like_bare_link("some query text"))

    def test_normalize_pasted_link_adds_scheme_once(self):
        from core import command_helpers
        self.assertEqual(command_helpers.normalize_pasted_link("instagram.com/p/1"),
                         "https://instagram.com/p/1")
        self.assertEqual(command_helpers.normalize_pasted_link("http://x.com"), "http://x.com")
        self.assertEqual(command_helpers.normalize_pasted_link("https://x.com"), "https://x.com")


if __name__ == "__main__":
    unittest.main()

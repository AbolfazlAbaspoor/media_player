"""
Spotify: the track list comes from Spotify's public embed page and every song
is played from YouTube. No network here; pages and yt-dlp are faked.
"""

import json
import os
import unittest
from unittest import mock

from core.services import spotify
from core.services._ytdlp_service import YtdlpService
from core.services.spotify import Spotify
from tests.helpers import load_command

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TRACK_ID = "4cOdK2wGLETKBW3PvgPWqT"


def page(payload):
    return ('<html><body><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(payload) + "</script></body></html>")


TRACK_PAGE = page({"props": {"pageProps": {"state": {"data": {"entity": {
    "type": "track", "name": "Never Gonna Give You Up", "id": TRACK_ID,
    "uri": "spotify:track:" + TRACK_ID, "title": "Never Gonna Give You Up",
    "artists": [{"name": "Rick Astley"}], "duration": 213573,
}}}}}})

PLAYLIST_PAGE = page({"props": {"pageProps": {"state": {"data": {"entity": {
    "type": "playlist", "name": "Road Trip",
    "trackList": [
        {"uri": "spotify:track:" + "A" * 22, "title": "Song A", "subtitle": "Artist 1,\xa0Artist 2", "duration": 180000},
        {"uri": "spotify:track:" + "B" * 22, "title": "Song B", "subtitle": "Artist 3", "duration": 200000},
    ],
}}}}}})


def fake_youtube(candidates):
    """extract_pooled: a flat ytsearch returns candidates, a watch URL resolves to a stream."""
    def extract(service_name, opts, target, label=None):
        if target.startswith("ytsearch"):
            return {"entries": [
                {"id": vid, "url": "https://www.youtube.com/watch?v=" + vid, "duration": seconds}
                for vid, seconds in candidates]}
        vid = target.rsplit("=", 1)[-1]
        return {"id": vid, "formats": [{"url": "https://cdn/" + vid}], "webpage_url": target,
                "title": "a YouTube title", "channel_url": "https://youtube.com/@someone"}
    return extract


class LinkTest(unittest.TestCase):

    def test_every_link_shape_becomes_one_canonical_link(self):
        want = "https://open.spotify.com/track/" + TRACK_ID
        for text in ("https://open.spotify.com/track/" + TRACK_ID + "?si=abc",
                     "https://open.spotify.com/intl-de/track/" + TRACK_ID,
                     "open.spotify.com/embed/track/" + TRACK_ID,
                     "spotify:track:" + TRACK_ID):
            self.assertEqual(spotify.canonical_link(text), want, text)

    def test_other_links_are_not_spotify(self):
        for text in ("https://www.youtube.com/watch?v=x", "spotify", "", None):
            self.assertIsNone(spotify.canonical_link(text))

    def test_a_short_link_is_followed(self):
        svc = Spotify()
        album = "https://open.spotify.com/album/" + "C" * 22
        with mock.patch.object(svc, "_fetch_text", return_value=(album, "")):
            self.assertEqual(svc.canonical_link("https://spotify.link/xyz"), album)


class EmbedPageTest(unittest.TestCase):

    def test_a_track(self):
        name, tracks = spotify.parse_embed_page(TRACK_PAGE)
        self.assertEqual(name, "Never Gonna Give You Up")
        self.assertEqual(tracks, [{"id": TRACK_ID, "title": "Never Gonna Give You Up",
                                   "artists": "Rick Astley", "duration": 213.573}])

    def test_a_playlist(self):
        name, tracks = spotify.parse_embed_page(PLAYLIST_PAGE)
        self.assertEqual(name, "Road Trip")
        self.assertEqual([spotify.display_name(t) for t in tracks],
                         ["Artist 1, Artist 2 - Song A", "Artist 3 - Song B"])
        self.assertEqual(tracks[1]["id"], "B" * 22)

    def test_a_moved_entity_is_still_found(self):
        moved = page({"props": {"somewhereElse": [{"entity": {
            "type": "album", "name": "X", "trackList": [{"title": "Only", "subtitle": "Y"}]}}]}})
        self.assertEqual(spotify.parse_embed_page(moved)[1][0]["title"], "Only")

    def test_garbage_is_nothing_found_not_a_crash(self):
        for html in ("", "<html>no data</html>", '<script id="__NEXT_DATA__">{broken</script>'):
            self.assertEqual(spotify.parse_embed_page(html), (None, []))


class MatchTest(unittest.TestCase):

    def test_first_result_with_a_close_duration_wins(self):
        candidates = [{"id": "mix", "duration": 3600}, {"id": "song", "duration": 215},
                      {"id": "cover", "duration": 214}]
        self.assertEqual(spotify.pick_match(candidates, 213.5, 10)["id"], "song")

    def test_without_a_close_one_the_top_result_plays(self):
        candidates = [{"id": "top", "duration": 400}, {"id": "other", "duration": 500}]
        self.assertEqual(spotify.pick_match(candidates, 200, 10)["id"], "top")
        self.assertEqual(spotify.pick_match(candidates, None, 10)["id"], "top")
        self.assertIsNone(spotify.pick_match([], 200, 10))


class SearchTest(unittest.TestCase):

    def test_spotify_is_on_the_shared_base_and_uses_youtube_cookies(self):
        self.assertTrue(issubclass(Spotify, YtdlpService))
        self.assertEqual(Spotify.COOKIE_SERVICE, "youtube")
        self.assertFalse(Spotify.SUPPORTS_SEARCH)

    def test_a_track_plays_from_youtube_under_its_spotify_name(self):
        svc = Spotify()
        with mock.patch.object(svc, "_fetch_text", return_value=("", TRACK_PAGE)), \
                mock.patch("core.proxy_retry.extract_pooled",
                           side_effect=fake_youtube([("mix", 3600), ("song", 214)])):
            result = svc.search("https://open.spotify.com/track/" + TRACK_ID + "?si=1")
        self.assertEqual(result["url"], "https://cdn/song")
        self.assertEqual(result["title"], "Rick Astley - Never Gonna Give You Up")
        self.assertEqual(result["public_url"], "https://open.spotify.com/track/" + TRACK_ID)
        self.assertIsNone(result["channel_url"])
        self.assertIsNone(svc.get_playlist_growth_info())

    def test_a_playlist_plays_the_first_song_and_grows_the_rest(self):
        svc = Spotify()
        link = "https://open.spotify.com/playlist/" + "P" * 22
        with mock.patch.object(svc, "_fetch_text", return_value=("", PLAYLIST_PAGE)), \
                mock.patch("core.proxy_retry.extract_pooled", side_effect=fake_youtube([("a", 181)])):
            result = svc.search(link)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Artist 1, Artist 2 - Song A")
        self.assertEqual(svc.get_playlist_growth_info(), (link, 2, 1))
        rest = svc.grow_playlist(link, 1)
        self.assertEqual([stub["title"] for stub in rest], ["Artist 3 - Song B"])

    def test_nothing_is_fetched_for_a_foreign_link(self):
        svc = Spotify()
        with mock.patch.object(svc, "_fetch_text", side_effect=AssertionError("network")):
            self.assertIsNone(svc.search("https://soundcloud.com/a/b"))
            self.assertIsNone(svc.search(""))

    def test_oembed_names_a_track_the_embed_page_did_not(self):
        svc = Spotify()

        def fetch(url):
            if "/embed/" in url:
                return "", "<html></html>"
            return "", json.dumps({"title": "Some Song"})

        with mock.patch.object(svc, "_fetch_text", side_effect=fetch):
            name, tracks = svc.describe("spotify:track:" + TRACK_ID)
        self.assertEqual(tracks[0]["title"], "Some Song")


class LinkCommandsGrowTest(unittest.TestCase):
    """sc/tk/spt start queue growth, so n continues through a set, a profile or a playlist."""

    @classmethod
    def setUpClass(cls):
        from core import i18n
        i18n.load_languages()
        i18n.set_language("en")

    def _run(self, command, service_name, args, service):
        bot = mock.Mock()
        bot.services = {service_name: service}
        ctx = {"bot": bot, "uid": 1, "nickname": "Ali", "username": "ali", "args": args}
        with mock.patch("core.command_helpers.run_search_and_play_command") as helper:
            load_command(command).run(ctx)
        return bot, helper

    def test_sc_and_tk_use_the_growing_play_path_with_a_private_https_link(self):
        for command, service_name, link in (("sc", "soundcloud", "soundcloud.com/artist/sets/x"),
                                            ("tk", "tiktok", "www.tiktok.com/@someone")):
            service = mock.Mock()
            bot, helper = self._run(command, service_name, [link], service)
            helper.assert_called_once()
            args, kwargs = helper.call_args
            self.assertEqual(args[2], service_name)
            self.assertEqual(kwargs["announce_query"], "https://" + link)
            args[1]()
            service.search.assert_called_once_with("https://" + link)

    def test_spt_plays_the_canonical_link(self):
        bot, helper = self._run("spt", "spotify", ["spotify:playlist:" + "P" * 22], Spotify())
        self.assertEqual(helper.call_args.kwargs["announce_query"],
                         "https://open.spotify.com/playlist/" + "P" * 22)

    def test_spt_info_lists_without_playing(self):
        service = mock.Mock()
        service.canonical_link.return_value = "https://open.spotify.com/album/" + "C" * 22
        service.describe.return_value = ("Album", [{"title": "One", "artists": "X", "duration": 61.0},
                                                   {"title": "Two", "artists": "", "duration": None}])
        bot, helper = self._run("spt", "spotify", ["info", "spotify:album:" + "C" * 22], service)
        helper.assert_not_called()
        text = bot.send_long_text.call_args.args[1]
        self.assertIn("1. X - One", text)
        self.assertIn("2. Two", text)

    def test_a_foreign_link_is_refused_by_name(self):
        bot, helper = self._run("sc", "soundcloud", ["https://youtube.com/x"], mock.Mock())
        helper.assert_not_called()
        self.assertIn("SoundCloud", bot.t.user_message.call_args.args[1])


if __name__ == "__main__":
    unittest.main()

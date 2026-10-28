"""
رادیو جوان: API جستجو/آهنگ/ویدیو و لینک‌های پیست‌شده. بدون شبکه:
core.net.fetch_text (و urllib برای لینک‌کوتاه) mock می‌شه.
"""

import json
import unittest
from unittest import mock

from core.services.radiojavan import RadioJavan, stub_from_item

FETCH = "core.services.radiojavan.net.fetch_text"

SONG = {
    "id": 152298, "title": 'Shadmehr Aghili - "Mamnoon"', "artist": "Shadmehr Aghili", "song": "Mamnoon",
    "permlink": "Shadmehr-Aghili-Mamnoon", "link": "https://host2.cdn/media/mp3/mp3-256/152298-x.mp3",
    "plays": "17,203,339", "likes": "24,919", "duration": 215.112,
    "created_at": "2025-10-05T09:18:06-04:00",
}
VIDEO = {
    "title": 'Shadmehr Aghili - "Mamnoon"', "artist": "Shadmehr Aghili", "song": "Mamnoon",
    "permlink": "shadmehr-aghili-mamnoon", "link": "https://host2.cdn/media/music_video/hq/shadmehr-aghili-mamnoon.mp4",
    "hq_link": "https://host2.cdn/media/music_video/4k/shadmehr-aghili-mamnoon.mp4", "views": "777,556",
}
SEARCH = {
    "mp3s": [SONG, {"title": "no link", "permlink": "x"}, dict(SONG, permlink="Other", artist=None, song=None,
                                                             title="Other Song")],
    "videos": [VIDEO],
}


def api(payloads):
    """fetch_text که بر اساس بخشی از آدرس جواب JSON می‌ده."""
    def fake(url, **kwargs):
        for part, payload in payloads.items():
            if part in url:
                return url, json.dumps(payload)
        raise OSError("unexpected " + url)
    return fake


class StubTest(unittest.TestCase):

    def test_song_stub_carries_the_direct_link_and_meta(self):
        stub = stub_from_item(SONG)
        self.assertEqual(stub["id"], "Shadmehr-Aghili-Mamnoon")
        self.assertEqual(stub["url"], "https://play.radiojavan.com/song/Shadmehr-Aghili-Mamnoon")
        self.assertEqual(stub["media_url"], SONG["link"])
        self.assertEqual(stub["title"], "Shadmehr Aghili - Mamnoon")
        self.assertEqual(stub["view_count"], 17203339)
        self.assertEqual(stub["like_count"], 24919)
        self.assertEqual(stub["uploader"], "Shadmehr Aghili")
        self.assertTrue(stub["timestamp"])

    def test_title_falls_back_to_the_raw_title(self):
        self.assertEqual(stub_from_item(dict(SONG, artist=None))["title"], SONG["title"])

    def test_video_uses_the_regular_mp4_not_4k(self):
        stub = stub_from_item(VIDEO, "video")
        self.assertTrue(stub["media_url"].endswith("/hq/shadmehr-aghili-mamnoon.mp4"))
        self.assertEqual(stub["url"], "https://play.radiojavan.com/video/shadmehr-aghili-mamnoon")

    def test_items_without_permlink_or_link_are_dropped(self):
        self.assertIsNone(stub_from_item({"permlink": "x"}))
        self.assertIsNone(stub_from_item({"link": "https://a/b.mp3"}))
        self.assertIsNone(stub_from_item(None))


class SearchTest(unittest.TestCase):

    def test_search_stubs_from_mp3s_only(self):
        with mock.patch(FETCH, side_effect=api({"api/p/search": SEARCH})) as fetch:
            stubs = RadioJavan()._search_stubs("ممنون", count=10)
        self.assertEqual([s["id"] for s in stubs], ["Shadmehr-Aghili-Mamnoon", "Other"])
        self.assertIn("query=%D9%85%D9%85%D9%86%D9%88%D9%86", fetch.call_args[0][0])

    def test_count_limit(self):
        with mock.patch(FETCH, side_effect=api({"api/p/search": SEARCH})):
            self.assertEqual(len(RadioJavan()._search_stubs("x", count=1)), 1)

    def test_network_and_json_failures_return_empty(self):
        with mock.patch(FETCH, side_effect=OSError("boom")):
            self.assertEqual(RadioJavan()._search_stubs("x", count=5), [])
        with mock.patch(FETCH, return_value=("u", "<html>blocked</html>")):
            self.assertEqual(RadioJavan()._search_stubs("x", count=5), [])

    def test_text_search_plays_the_first_hit_without_another_request(self):
        svc = RadioJavan()
        with mock.patch(FETCH, side_effect=api({"api/p/search": SEARCH})) as fetch:
            resolved = svc.search("ممنون")
        self.assertEqual(resolved["url"], SONG["link"])
        self.assertEqual(resolved["title"], "Shadmehr Aghili - Mamnoon")
        self.assertTrue(resolved["verified_media"])
        self.assertEqual(resolved["info"]["service"], "radiojavan")
        self.assertEqual(resolved["info"]["ext"], "mp3")
        self.assertEqual(fetch.call_count, 1)

    def test_queue_resolves_stubs_locally(self):
        stub = stub_from_item(SONG)
        with mock.patch(FETCH) as fetch:
            resolved = RadioJavan().resolve_stub(stub)
        self.assertEqual(resolved["url"], SONG["link"])
        fetch.assert_not_called()

    def test_stub_without_media_url_is_not_resolved(self):
        self.assertIsNone(RadioJavan().resolve_stub({"id": "x", "url": "https://play.radiojavan.com/song/x"}))


class LinkTest(unittest.TestCase):

    def test_kind_and_permlink(self):
        kp = RadioJavan._kind_and_permlink
        self.assertEqual(kp("https://play.radiojavan.com/song/Shadmehr-Aghili-Mamnoon?x=1"),
                         ("song", "Shadmehr-Aghili-Mamnoon"))
        self.assertEqual(kp("https://www.radiojavan.com/mp3s/mp3/Shadmehr-Aghili-Mamnoon"),
                         ("song", "Shadmehr-Aghili-Mamnoon"))
        self.assertEqual(kp("https://play.radiojavan.com/video/a-b"), ("video", "a-b"))
        self.assertEqual(kp("https://www.radiojavan.com/videos/video/a-b"), ("video", "a-b"))
        self.assertEqual(kp("https://rj.app/m/abc"), ("short", "https://rj.app/m/abc"))
        self.assertEqual(kp("https://play.radiojavan.com/artist/Shadmehr-Aghili"), (None, None))
        self.assertEqual(kp("https://www.radiojavan.com/"), (None, None))

    def test_song_link_uses_the_item_api(self):
        with mock.patch(FETCH, side_effect=api({"api/p/mp3?id=Shadmehr-Aghili-Mamnoon": SONG})) as fetch:
            resolved = RadioJavan().search("https://www.radiojavan.com/mp3s/mp3/Shadmehr-Aghili-Mamnoon")
        self.assertEqual(resolved["url"], SONG["link"])
        self.assertEqual(resolved["public_url"], "https://play.radiojavan.com/song/Shadmehr-Aghili-Mamnoon")
        self.assertIn("api/p/mp3?id=", fetch.call_args[0][0])

    def test_video_link_uses_the_video_api(self):
        with mock.patch(FETCH, side_effect=api({"api/p/video?id=shadmehr-aghili-mamnoon": VIDEO})):
            resolved = RadioJavan().search("https://play.radiojavan.com/video/shadmehr-aghili-mamnoon")
        self.assertTrue(resolved["url"].endswith(".mp4"))
        self.assertEqual(resolved["info"]["ext"], "mp4")

    def test_short_link_is_followed_then_resolved(self):
        svc = RadioJavan()
        final = "https://play.radiojavan.com/song/shadmehr-aghili-mamnoon?appOverlay=1"
        with mock.patch.object(RadioJavan, "_follow_short_link", return_value=final) as follow, \
                mock.patch(FETCH, side_effect=api({"api/p/mp3?id=shadmehr-aghili-mamnoon": SONG})):
            resolved = svc.search("https://rj.app/m/dv2PyO7q")
        follow.assert_called_once_with("https://rj.app/m/dv2PyO7q")
        self.assertEqual(resolved["url"], SONG["link"])

    def test_failed_short_link_returns_none(self):
        with mock.patch.object(RadioJavan, "_follow_short_link", return_value=None):
            self.assertIsNone(RadioJavan().search("https://rj.app/m/x"))

    def test_follow_short_link_returns_the_final_address(self):
        response = mock.MagicMock()
        response.geturl.return_value = "https://play.radiojavan.com/song/a"
        response.__enter__.return_value = response
        with mock.patch("core.services.radiojavan.proxy_state.open_direct_then_proxy",
                        return_value=response) as opener:
            self.assertEqual(RadioJavan._follow_short_link("https://rj.app/m/x"),
                             "https://play.radiojavan.com/song/a")
        self.assertIn("Mozilla", opener.call_args[0][0].get_header("User-agent"))
        with mock.patch("core.services.radiojavan.proxy_state.open_direct_then_proxy",
                        side_effect=OSError("boom")):
            self.assertIsNone(RadioJavan._follow_short_link("https://rj.app/m/x"))

    def test_api_failure_and_unsupported_links_give_none(self):
        with mock.patch(FETCH, side_effect=OSError("boom")):
            self.assertIsNone(RadioJavan().search("https://play.radiojavan.com/song/x"))
        with mock.patch(FETCH) as fetch:
            self.assertIsNone(RadioJavan().search("https://play.radiojavan.com/artist/x"))
            self.assertIsNone(RadioJavan().search("https://example.com/song/x"))
        fetch.assert_not_called()

    def test_routes_radiojavan_links_only(self):
        svc = RadioJavan()
        for url in ("https://play.radiojavan.com/song/x", "https://www.radiojavan.com/mp3s/mp3/x",
                    "https://rj.app/m/abc"):
            self.assertTrue(svc.owns_url(url), url)
        self.assertFalse(svc.owns_url("https://example.com/rj.app/m/x"))
        self.assertFalse(svc.owns_url("https://www.aparat.com/v/abc"))


if __name__ == "__main__":
    unittest.main()

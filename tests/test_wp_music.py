"""
سایت‌های دانلود موزیکِ وردپرسی (upmusics / nex1music / rozmusic) روی پایه‌ی
مشترک core/services/_wp_music.py. بدون شبکه: core.net.fetch_text mock می‌شه.
"""

import unittest
from unittest import mock

from core.services import _wp_music
from core.services._wp_music import (
    clean_title, is_post_url, media_links, parse_search_html)
from core.services.nex1music import Nex1Music
from core.services.rozmusic import RozMusic
from core.services.upmusics import UpMusics

FETCH = "core.services._wp_music.net.fetch_text"

CARD = '''
<article class="upsng"><header>
  <h2><a title="t" rel="bookmark" href="{url}">{title}</a></h2>
  <h2><a href="https://upmusics.com/tag/extra/">تگ</a></h2>
</header></article>
'''
SIDEBAR = '''
<aside><h2><a href="https://upmusics.com/happy-birthday/">تولدت مبارک</a></h2></aside>
'''
SEARCH_PAGE = (
    "<h2><a href='https://upmusics.com/before-first-card/'>قبل از نتایج</a></h2>"
    + CARD.format(url="https://upmusics.com/%D8%A2%D9%87%D9%86%DA%AF-%D8%A7%D9%88%D9%84/",
                  title="دانلود آهنگ شادمهر به نام ماه شبام + متن آهنگ")
    + CARD.format(url="https://upmusics.com/second/", title="دوم &amp; سوم")
    + CARD.format(url="https://upmusics.com/second/", title="تکراری")
    + CARD.format(url="https://other.example/post/", title="سایت دیگه")
    + SIDEBAR
)
POST_PAGE = '''
<html><head><meta property="og:title" content="دانلود آهنگ علی ‌صدا به نام راه"></head><body>
<audio src="http://dl.site.ir/Music/2019/Ali - Rah 128.mp3"></audio>
<a href="https://dl.site.ir/Music/2019/Ali - Rah 128.mp3">128</a>
<a href="https://dl.site.ir/Music/2019/Ali - Rah.mp3">320</a>
<a href="https://dl.site.ir/Music/2019/Ali - Rah [64].mp3">64</a>
</body></html>
'''


class CleanTitleTest(unittest.TestCase):

    def test_download_prefix_and_lyrics_suffix_go(self):
        self.assertEqual(
            clean_title("دانلود آهنگ شادمهر کیانی به نام ماه شبام + متن آهنگ"),
            "شادمهر کیانی - ماه شبام")

    def test_plain_title_is_kept(self):
        self.assertEqual(clean_title("سوی سازندگی"), "سوی سازندگی")

    def test_entities_tags_and_blank(self):
        self.assertEqual(clean_title("a &amp; <b>b</b>"), "a & b")
        self.assertEqual(clean_title(""), "Unknown")


class IsPostUrlTest(unittest.TestCase):

    def test_posts(self):
        self.assertTrue(is_post_url("https://upmusics.com/some-post/"))
        self.assertTrue(is_post_url("https://rozmusic.com/%D8%A2.html"))

    def test_listings_home_search_and_files_are_not_posts(self):
        for url in ("https://upmusics.com/", "https://upmusics.com/tag/x/",
                    "https://upmusics.com/category/new/", "https://upmusics.com/search/x",
                    "https://nex1music.com/?s=x", "https://dl.site.ir/a/b.mp3", ""):
            self.assertFalse(is_post_url(url), url)


class ParseSearchHtmlTest(unittest.TestCase):

    def test_card_marker_keeps_only_result_cards(self):
        stubs = parse_search_html(SEARCH_PAGE, "upmusics.com", '<article class="upsng"')
        # سایدبار، h2 قبل از کارت‌ها، لینک سایت دیگه، تگ و تکراری حذف می‌شن.
        self.assertEqual([s["title"] for s in stubs], ["شادمهر - ماه شبام", "دوم & سوم"])
        self.assertEqual(stubs[1]["id"], "second")
        self.assertEqual(stubs[1]["url"], stubs[1]["webpage_url"])

    def test_without_marker_every_h2_post_link_counts(self):
        stubs = parse_search_html(SEARCH_PAGE, "upmusics.com")
        self.assertIn("happy-birthday", [s["id"] for s in stubs])
        self.assertNotIn("extra", [s["id"] for s in stubs])

    def test_empty(self):
        self.assertEqual(parse_search_html("", "upmusics.com"), [])
        self.assertEqual(parse_search_html(None, "upmusics.com", "x"), [])


class MediaLinksTest(unittest.TestCase):

    def test_best_quality_first_and_spaces_encoded(self):
        links = media_links(POST_PAGE, "https://site.ir/post/")
        self.assertEqual(len(links), 3)  # http و https یک فایل‌ان
        self.assertTrue(links[0].endswith("Ali%20-%20Rah.mp3"))  # بدون عدد = اصلی
        self.assertTrue(links[0].startswith("https://"))
        self.assertIn("128", links[1])
        self.assertIn("64", links[2])
        self.assertNotIn(" ", "".join(links))

    def test_preview_only_used_when_nothing_else(self):
        page = '<a href="https://d.ir/x/Song Demo.mp3">d</a><a href="https://d.ir/x/Song (320).mp3">f</a>'
        self.assertEqual(media_links(page, "https://s.ir/")[0], "https://d.ir/x/Song%20(320).mp3")
        only_demo = '<audio src="https://d.ir/x/Song Demo.mp3"></audio>'
        self.assertEqual(media_links(only_demo, "https://s.ir/"), ["https://d.ir/x/Song%20Demo.mp3"])

    def test_year_or_id_in_filename_is_not_a_bitrate(self):
        page = ('<a href="https://d.ir/1790768716_Name.mp3">a</a>'
                '<a href="https://d.ir/1790768716_Name_128.mp3">b</a>')
        self.assertTrue(media_links(page, "https://s.ir/")[0].endswith("1790768716_Name.mp3"))

    def test_protocol_relative_and_no_media(self):
        self.assertEqual(media_links('<a href="//d.ir/a.mp3">a</a>', "https://s.ir/p"),
                         ["https://d.ir/a.mp3"])
        self.assertEqual(media_links("<p>nothing</p>", "https://s.ir/"), [])
        self.assertEqual(media_links(None, "https://s.ir/"), [])


class ServiceTest(unittest.TestCase):

    def test_search_stubs_count_url_and_marker(self):
        with mock.patch(FETCH, return_value=("u", SEARCH_PAGE)) as fetch:
            stubs = UpMusics()._search_stubs("شادمهر", count=1)
        self.assertEqual(len(stubs), 1)
        self.assertEqual(fetch.call_args[0][0], "https://upmusics.com/search/%D8%B4%D8%A7%D8%AF%D9%85%D9%87%D8%B1")

    def test_search_url_templates(self):
        for cls, expected in ((Nex1Music, "https://nex1music.com/?s=x"),
                              (RozMusic, "https://rozmusic.com/?s=x")):
            with mock.patch(FETCH, return_value=("u", "")) as fetch:
                cls()._search_stubs("x", count=5)
            self.assertEqual(fetch.call_args[0][0], expected)

    def test_network_failure_returns_empty_without_raising(self):
        with mock.patch(FETCH, side_effect=OSError("boom")):
            self.assertEqual(UpMusics()._search_stubs("x", count=5), [])

    def test_resolve_picks_the_best_mp3(self):
        stub = {"id": "p", "url": "https://rozmusic.com/p.html", "webpage_url": "https://rozmusic.com/p.html",
                "title": "علی - راه"}
        with mock.patch(FETCH, return_value=("u", POST_PAGE)):
            resolved = RozMusic().resolve_stub(stub)
        self.assertTrue(resolved["url"].endswith("Ali%20-%20Rah.mp3"))
        self.assertEqual(resolved["title"], "علی - راه")
        self.assertEqual(resolved["public_url"], "https://rozmusic.com/p.html")
        self.assertTrue(resolved["verified_media"])
        self.assertEqual(resolved["info"]["service"], "rozmusic")
        self.assertEqual(resolved["info"]["ext"], "mp3")

    def test_resolve_without_title_uses_og_title(self):
        with mock.patch(FETCH, return_value=("u", POST_PAGE)):
            resolved = Nex1Music().search("https://nex1music.com/some-post/")
        self.assertEqual(resolved["title"], "علی صدا - راه")

    def test_demo_only_post_is_labelled(self):
        page = '<audio src="https://d.ir/x/Song Demo.mp3"></audio>'
        with mock.patch(FETCH, return_value=("u", page)):
            resolved = UpMusics().search("https://upmusics.com/song/")
        self.assertTrue(resolved["title"].endswith("(دمو)"))

    def test_post_without_mp3_resolves_to_nothing(self):
        with mock.patch(FETCH, return_value=("u", "<p>zip only</p>")):
            self.assertIsNone(UpMusics().search("https://upmusics.com/album/"))

    def test_page_failure_falls_back_to_the_ytdlp_base(self):
        base = "core.services._wp_music.YtdlpService._resolve_entry"
        with mock.patch(FETCH, side_effect=OSError("boom")), \
                mock.patch(base, return_value={"url": "x"}) as fallback:
            result = UpMusics().search("https://upmusics.com/song/")
        self.assertEqual(result, {"url": "x"})
        fallback.assert_called_once()

    def test_only_posts_of_the_own_site_are_routed(self):
        svc = UpMusics()
        self.assertTrue(svc.owns_url("https://upmusics.com/x/"))
        self.assertTrue(svc.owns_url("https://www.UpMusics.com/x/"))
        self.assertFalse(svc.owns_url("https://rozmusic.com/x.html"))
        with mock.patch(FETCH) as fetch:
            self.assertIsNone(svc.search("https://rozmusic.com/x.html"))
            # تگ و فایل مستقیم: None تا لوله‌ی عمومیِ لینک پخششون کنه.
            self.assertIsNone(svc.search("https://upmusics.com/tag/x/"))
            self.assertIsNone(svc.search("https://dl.upmusics.com/a/b.mp3"))
        fetch.assert_not_called()

    def test_each_site_declares_its_own_markers(self):
        self.assertEqual(UpMusics.URL_MARKERS, ("upmusics.com",))
        self.assertEqual(Nex1Music.URL_MARKERS, ("nex1music.com",))
        self.assertEqual(RozMusic.URL_MARKERS, ("rozmusic.com",))
        for cls in (UpMusics, Nex1Music, RozMusic):
            self.assertTrue(issubclass(cls, _wp_music.WpMusicService))
            self.assertTrue(cls.AUDIO_ONLY)
            self.assertTrue(cls.CARD_MARKER)


if __name__ == "__main__":
    unittest.main()

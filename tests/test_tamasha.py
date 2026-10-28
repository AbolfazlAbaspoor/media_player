"""
تماشا: پارس صفحه‌ی جستجوی HTML، حذفِ نتایجِ پاک‌شده و ساخت استاب. بدون شبکه:
core.net.fetch_text و core.net.probe mock می‌شن.
"""

import unittest
from unittest import mock

from core.services import tamasha
from core.services.tamasha import Tamasha, drop_dead, parse_search_html

CARD = '''
<div class="video compact-video compact-video video-grid--item ">
  <div class=vid-wrapper>
    <div class="vid-present-container" data-block-video-id="{uid}">
      <a href="https://tamasha.com/v/{uid}" class="vid-present has-link" title="{title}"
         {hover}
      >
        <img class="vid-thumbnail" src="data:x" alt="{title}" title="{title}">
        {time}
      </a>
    </div>
  </div>
  <div class="vid-meta">
    <a href="https://tamasha.com/v/{uid}" class="vid-name" title="{title}"><span>{title}</span></a>
    <a class="compact channel-info" href="/danial64">
      <span>Danial_nikooparvar</span>
    </a>
  </div>
</div>
'''
HOVER = 'data-video-hover="https://{host}.tamasha.com/statics/videos_preview/99/e8/{uid}_x_200x114.mp4"'
PAGE = (
    CARD.format(uid="jN3Ox", title="گیتار &amp; شادمهر", hover=HOVER.format(host="as-v1", uid="jN3Ox"),
                time='<time class="vid-time">01:41</time>')
    + CARD.format(uid="RzzVg", title="دوم", hover=HOVER.format(host="as-v2", uid="RzzVg"), time="")
    + CARD.format(uid="jN3Ox", title="تکراری", hover="", time="")
    + CARD.format(uid="NoHost", title="بی‌پیش‌نمایش", hover="", time="")
)


class ParseSearchHtmlTest(unittest.TestCase):

    def test_cards_become_stubs_without_duplicates(self):
        stubs = parse_search_html(PAGE)
        self.assertEqual([s["id"] for s in stubs], ["jN3Ox", "RzzVg", "NoHost"])
        first = stubs[0]
        self.assertEqual(first["url"], "https://tamasha.com/v/jN3Ox")
        self.assertEqual(first["webpage_url"], first["url"])
        self.assertEqual(first["title"], "گیتار & شادمهر")
        self.assertEqual(first["duration"], 101)
        self.assertEqual(first["uploader"], "Danial_nikooparvar")
        self.assertEqual(first["channel_url"], "https://tamasha.com/danial64")
        self.assertIsNone(stubs[1]["duration"])

    def test_stream_url_comes_from_the_preview_host(self):
        stubs = parse_search_html(PAGE)
        self.assertEqual(stubs[0]["stream_url"], "https://as-v1.tamasha.com/statics/stream/jN3Ox/master.m3u8")
        self.assertEqual(stubs[1]["stream_url"], "https://as-v2.tamasha.com/statics/stream/RzzVg/master.m3u8")
        self.assertIsNone(stubs[2]["stream_url"])

    def test_empty_page(self):
        self.assertEqual(parse_search_html(""), [])
        self.assertEqual(parse_search_html(None), [])


class DropDeadTest(unittest.TestCase):

    @staticmethod
    def stubs(n):
        return [{"id": f"v{i}", "stream_url": f"https://as-v1.tamasha.com/statics/stream/v{i}/master.m3u8"}
                for i in range(n)]

    def test_removed_videos_are_dropped_in_order(self):
        def probe(url, **kwargs):
            if "/v1/" in url or "/v3/" in url:
                raise OSError("404")
            return url, "audio/x-mpegurl", b"#EXTM3U"
        with mock.patch("core.services.tamasha.net.probe", side_effect=probe):
            kept = drop_dead(self.stubs(5))
        self.assertEqual([s["id"] for s in kept], ["v0", "v2", "v4"])

    def test_when_every_check_fails_the_list_is_untouched(self):
        with mock.patch("core.services.tamasha.net.probe", side_effect=OSError("offline")):
            self.assertEqual(len(drop_dead(self.stubs(4))), 4)

    def test_stub_without_stream_url_counts_as_alive(self):
        with mock.patch("core.services.tamasha.net.probe", side_effect=OSError("404")) as probe:
            kept = drop_dead([{"id": "a", "stream_url": None}, {"id": "b", "stream_url": "https://x/y"}])
        self.assertEqual([s["id"] for s in kept], ["a"])
        self.assertEqual(probe.call_count, 1)

    def test_only_the_first_results_are_checked(self):
        total = tamasha._ALIVE_CHECK_LIMIT + 5
        with mock.patch("core.services.tamasha.net.probe", side_effect=OSError("404")) as probe:
            kept = drop_dead(self.stubs(total))
        self.assertEqual(probe.call_count, tamasha._ALIVE_CHECK_LIMIT)
        # چکِ اول‌ها همه شکست خورد -> اون‌ها دست‌نخورده، و بقیه هم می‌مونن.
        self.assertEqual(len(kept), total)

    def test_empty(self):
        self.assertEqual(drop_dead([]), [])


class SearchStubsTest(unittest.TestCase):

    def test_count_limit_and_query_parameter(self):
        with mock.patch("core.services.tamasha.net.fetch_text", return_value=("u", PAGE)) as fetch, \
                mock.patch("core.services.tamasha.net.probe", return_value=("u", "", b"")):
            stubs = Tamasha()._search_stubs("موسیقی", count=2)
        self.assertEqual(len(stubs), 2)
        # پارامتر query است نه q (q جستجو رو نادیده می‌گیره).
        self.assertIn("search?query=%D9%85", fetch.call_args[0][0])

    def test_network_failure_returns_empty_without_raising(self):
        with mock.patch("core.services.tamasha.net.fetch_text", side_effect=OSError("boom")):
            self.assertEqual(Tamasha()._search_stubs("x", count=5), [])


class OwnsUrlTest(unittest.TestCase):

    def test_routes_tamasha_links_only(self):
        svc = Tamasha()
        self.assertTrue(svc.owns_url("https://tamasha.com/v/jN3Ox"))
        self.assertFalse(svc.owns_url("https://www.namasha.com/v/Lrs9ENss"))
        self.assertFalse(svc.owns_url("https://www.aparat.com/v/abc"))


if __name__ == "__main__":
    unittest.main()

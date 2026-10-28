"""
«هر لینکی باید پخش بشه»: قانون‌های تازه‌ی لوله‌ی عمومی (core/link_resolver.py،
core/html_media_scan.py، core/playlist_utils.py). همه‌ی شبکه mock شده.
"""

import unittest
from unittest import mock

import bot
from core import html_media_scan as hms
from core import link_resolver as lr
from core import net
from core import playlist_utils as pu

BASE = "https://site.example/dir/page"
CRLF = bytes((13, 10))


def _probe(kind, final=None):
    """probe_details ساختگی که همیشه همون kind رو می‌ده."""
    return lambda url, headers=None: (kind, final or url, "", b"")


class ShareLinkRewriteTest(unittest.TestCase):

    def test_dropbox_dl0_becomes_dl1(self):
        self.assertEqual(lr.rewrite_share_link("https://www.dropbox.com/s/abc/song.mp3?dl=0"),
                         "https://www.dropbox.com/s/abc/song.mp3?dl=1")

    def test_dropbox_without_dl_or_with_raw_gets_dl1(self):
        self.assertEqual(lr.rewrite_share_link("https://dropbox.com/scl/fi/x/a.mp3?rlkey=k"),
                         "https://dropbox.com/scl/fi/x/a.mp3?rlkey=k&dl=1")
        self.assertEqual(lr.rewrite_share_link("https://www.dropbox.com/s/abc/a.mp3?raw=1"),
                         "https://www.dropbox.com/s/abc/a.mp3?dl=1")

    def test_google_drive_file_and_open_links_become_direct_download(self):
        expected = "https://drive.usercontent.google.com/download?id=AbC_12-x&export=download&confirm=t"
        self.assertEqual(lr.rewrite_share_link("https://drive.google.com/file/d/AbC_12-x/view?usp=sharing"), expected)
        self.assertEqual(lr.rewrite_share_link("https://drive.google.com/open?id=AbC_12-x"), expected)
        self.assertEqual(lr.rewrite_share_link("https://drive.google.com/uc?id=AbC_12-x&export=download"), expected)

    def test_other_links_are_untouched(self):
        for url in ("https://example.com/a.mp3", "https://drive.google.com/drive/folders/zzz",
                    "https://notdropbox.com/s/a.mp3"):
            self.assertEqual(lr.rewrite_share_link(url), url)


class PlaylistParsingTest(unittest.TestCase):

    def test_pls_entries_are_ordered_by_number(self):
        text = "[playlist]\nNumberOfEntries=2\nFile2=http://b/stream\nTitle2=B\nFile1=http://a/stream\nVersion=2\n"
        self.assertEqual(pu.parse_entries(text, "http://x/l.pls"), ["http://a/stream", "http://b/stream"])

    def test_xspf_locations_with_entities_and_relative_paths(self):
        text = ('<?xml version="1.0"?><playlist xmlns="http://xspf.org/ns/0/"><trackList>'
                "<track><location>http://a/x.mp3?a=1&amp;b=2</location></track>"
                "<track><location>rel/y.mp3</location></track></trackList></playlist>")
        self.assertEqual(pu.parse_entries(text, "http://h/d/l.xspf"),
                         ["http://a/x.mp3?a=1&b=2", "http://h/d/rel/y.mp3"])

    def test_asx_refs(self):
        text = '<ASX version="3.0"><Entry><Ref HREF="http://a/live" /></Entry></ASX>'
        self.assertEqual(pu.parse_entries(text, "http://h/l.asx"), ["http://a/live"])

    def test_m3u_with_and_without_header(self):
        self.assertEqual(pu.parse_entries("#EXTM3U\n#EXTINF:1,x\nhttp://a/1.mp3\n", "http://h/l.m3u"),
                         ["http://a/1.mp3"])
        self.assertEqual(pu.parse_entries("http://a/1.mp3\nhttp://a/2.mp3\n", "http://h/l.m3u"),
                         ["http://a/1.mp3", "http://a/2.mp3"])

    def test_real_hls_is_not_a_simple_list(self):
        self.assertIsNone(pu.parse_entries("#EXTM3U\n#EXT-X-TARGETDURATION:6\nseg0.ts\n", "http://h/i.m3u8"))
        self.assertIsNone(pu.parse_entries("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nlow.m3u8\n", "http://h/i.m3u8"))

    def test_only_network_schemes_survive(self):
        text = "[playlist]\nFile1=file:///C:/secret.mp3\nFile2=http://ok/s\nFile3=/etc/passwd\n"
        # File3 نسبیه ولی با base شبکه‌ای می‌شه http؛ file:// باید بیفته.
        self.assertEqual(pu.parse_entries(text, "http://h/l.pls"), ["http://ok/s", "http://h/etc/passwd"])

    def test_entry_count_is_capped(self):
        text = "\n".join(f"http://a/{i}.mp3" for i in range(pu.MAX_ENTRIES + 50))
        self.assertEqual(len(pu.parse_entries("#EXTM3U\n" + text, "http://h/l.m3u")), pu.MAX_ENTRIES)

    def test_garbage_is_none(self):
        self.assertIsNone(pu.parse_entries("<html>hi</html>", "http://h/x"))
        self.assertIsNone(pu.parse_entries("", "http://h/x"))

    def test_resolve_playlist_handles_every_extension_and_force(self):
        with mock.patch.object(pu, "_fetch_text", return_value="[playlist]\nFile1=http://a/s\n") as fetch:
            self.assertEqual(pu.resolve_playlist("http://h/l.pls"), ["http://a/s"])
            self.assertEqual(pu.resolve_playlist("http://h/noext", force=True), ["http://a/s"])
            fetch.reset_mock()
            self.assertEqual(pu.resolve_playlist("http://h/noext"), ["http://h/noext"])
            fetch.assert_not_called()

    def test_resolve_playlist_falls_back_to_the_url_on_error(self):
        with mock.patch.object(pu, "_fetch_text", side_effect=OSError("down")):
            self.assertEqual(pu.resolve_playlist("http://h/l.xspf"), ["http://h/l.xspf"])

    def test_expand_item_opens_a_pls_into_several_tracks(self):
        with mock.patch.object(bot, "resolve_playlist", return_value=["http://a/s1", "http://a/s2"]):
            result = bot._expand_item("http://h/l.pls", "T", "P", True, verified=False)
        self.assertEqual([r[0] for r in result], ["http://a/s1", "http://a/s2"])


class ClassifyProbeTest(unittest.TestCase):

    def test_playlists_are_recognised_by_type_and_by_content(self):
        self.assertEqual(lr.classify_probe("audio/x-scpls", b""), "playlist")
        self.assertEqual(lr.classify_probe("application/xspf+xml", b""), "playlist")
        self.assertEqual(lr.classify_probe("text/plain", b"[playlist]\nFile1=x"), "playlist")
        self.assertEqual(lr.classify_probe("audio/x-mpegurl", b"#EXTM3U\nhttp://a"), "playlist")
        self.assertEqual(lr.classify_probe("application/octet-stream", b'<?xml version="1.0"?><playlist version="1">'),
                         "playlist")
        self.assertEqual(lr.classify_probe("video/x-ms-asf", b"<asx version=3>"), "playlist")

    def test_real_media_and_pages_are_unchanged(self):
        self.assertEqual(lr.classify_probe("audio/mpeg", b"\xff\xfb"), "media")
        self.assertEqual(lr.classify_probe("text/html", b"<html>"), "html")
        self.assertEqual(lr.classify_probe("application/vnd.apple.mpegurl", b""), "media")


class HtmlCandidatesTest(unittest.TestCase):

    def test_extensionless_declared_media_is_weak(self):
        for html in ('<meta property="og:audio" content="https://c/live">',
                     '<meta name="twitter:player:stream" content="https://c/live">',
                     '<meta content="https://c/live" property="og:video:url">',
                     '<script type="application/ld+json">{"contentUrl": "https://c/live"}</script>',
                     '<audio src="/live"></audio>'):
            strong, weak = hms.find_candidates(html, "https://c/page")
            self.assertEqual((strong, weak), ([], ["https://c/live"]), html)

    def test_json_key_with_absolute_extensionless_url_is_weak(self):
        strong, weak = hms.find_candidates('{"stream_url":"http:\\/\\/radio.example:8000\\/live"}', BASE)
        self.assertEqual((strong, weak), ([], ["http://radio.example:8000/live"]))

    def test_unrelated_absolute_urls_are_not_candidates(self):
        self.assertEqual(hms.find_candidates('<a href="https://x/page">x</a> {"home":"https://x/"}', BASE), ([], []))

    def test_json_key_with_extension_accepts_relative_paths(self):
        strong, _ = hms.find_candidates("var cfg={file:'audio/a.mp3', title:'x'}", BASE)
        self.assertEqual(strong, ["https://site.example/dir/audio/a.mp3"])

    def test_plain_anchor_to_a_media_file(self):
        strong, _ = hms.find_candidates('<a href="/files/a.m4a?dl=1">get</a>', BASE)
        self.assertEqual(strong, ["https://site.example/files/a.m4a?dl=1"])

    def test_extension_inside_a_query_value_is_not_media(self):
        html = '<a href="/player?file=http%3A%2F%2Fc%2Fa.wav">x</a>'
        strong, _ = hms.find_candidates(html, BASE)
        # از نسخه‌ی decode‌شده می‌گیره، نه از خودِ /player.
        self.assertEqual(strong, ["http://c/a.wav"])

    def test_playlist_files_are_strong_candidates(self):
        strong, _ = hms.find_candidates('<a href="/radio/live.pls">listen</a>', BASE)
        self.assertEqual(strong, ["https://site.example/radio/live.pls"])

    def test_candidates_are_deduplicated_and_capped(self):
        html = "".join(f'<audio src="/a{i}"></audio>' for i in range(20)) + '<audio src="/a0"></audio>'
        _, weak = hms.find_candidates(html, BASE)
        self.assertEqual(len(weak), len(set(weak)))
        self.assertLessEqual(len(weak), 6)

    def test_find_media_keeps_returning_the_first_strong_link(self):
        self.assertEqual(hms.find_media('<video src="/v/a.mp4">', BASE), "https://site.example/v/a.mp4")
        self.assertIsNone(hms.find_media('<meta property="og:audio" content="https://c/live">', BASE))

    def test_redirects(self):
        self.assertEqual(hms.find_redirect('<meta http-equiv="refresh" content="0; url=/next">', BASE),
                         "https://site.example/next")
        self.assertEqual(hms.find_redirect("<meta http-equiv=refresh content='3;URL=\"https://o/x\"'>", BASE),
                         "https://o/x")
        self.assertEqual(hms.find_redirect('<script>window.location.href = "/go";</script>', BASE),
                         "https://site.example/go")
        self.assertEqual(hms.find_redirect("<script>location.replace('/go2')</script>", BASE),
                         "https://site.example/go2")

    def test_js_redirect_ignored_on_a_big_page_and_self_redirect_ignored(self):
        big = '<script>window.location = "/login";</script>' + "x" * 7000
        self.assertIsNone(hms.find_redirect(big, BASE))
        self.assertIsNone(hms.find_redirect('<meta http-equiv="refresh" content="0; url=%s">' % BASE, BASE))
        self.assertIsNone(hms.find_redirect("<p>no redirect</p>", BASE))

    def test_lazy_iframe_and_twitter_player_are_frames(self):
        html = ('<iframe data-src="/lazy"></iframe><embed src="https://e/x">'
                '<meta name="twitter:player" content="https://p/player">')
        self.assertEqual(hms.find_iframes(html, BASE),
                         ["https://site.example/lazy", "https://e/x", "https://p/player"])

    def test_scan_detailed_uses_the_final_url_as_base_and_caps_the_download(self):
        with mock.patch.object(net, "fetch",
                               return_value=("https://final.example/x/", b'<audio src="a.mp3">')) as fetch:
            scan = hms.scan_detailed("https://short.example/s")
        self.assertEqual(scan.found, "https://final.example/x/a.mp3")
        self.assertEqual(scan.final, "https://final.example/x/")
        self.assertEqual(fetch.call_args.kwargs["max_bytes"], hms._MAX_BYTES)

    def test_scan_detailed_never_raises(self):
        with mock.patch.object(net, "fetch", side_effect=OSError("down")):
            scan = hms.scan_detailed("https://x.example/")
        self.assertEqual(scan, hms.PageScan(None, [], [], None, "https://x.example/"))


class ResolveFlowTest(unittest.TestCase):

    def setUp(self):
        # هیچ‌کدوم از مراحل گرون نباید ناخواسته واقعی اجرا بشن.
        for name in ("try_ytdlp", "try_html_scan", "_browser_item"):
            patcher = mock.patch.object(lr, name, return_value=None)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(lr, "has_dedicated_extractor", return_value=False)
        self.dedicated = patcher.start()
        self.addCleanup(patcher.stop)

    def test_shortener_redirecting_to_a_media_file_returns_the_final_file(self):
        with mock.patch.object(lr, "probe_details",
                               return_value=("media", "https://cdn.example/a.mp3", "audio/mpeg", b"")):
            item = lr.resolve("https://bit.example/x")
        self.assertEqual(item["url"], "https://cdn.example/a.mp3")
        self.assertEqual(item["public_url"], "https://bit.example/x")

    def test_shortener_redirecting_to_a_page_continues_with_the_final_url(self):
        self.try_ytdlp.return_value = {"url": "https://cdn/x", "title": "T"}
        with mock.patch.object(lr, "probe_details",
                               return_value=("html", "https://www.youtube.com/watch?v=jNQXAC9IVRw", "", b"")):
            item = lr.resolve("https://bit.example/y")
        self.try_ytdlp.assert_called_once_with("https://www.youtube.com/watch?v=jNQXAC9IVRw")
        self.assertEqual(item["url"], "https://cdn/x")

    def test_dropbox_share_link_is_rewritten_before_anything_else(self):
        item = lr.resolve("https://www.dropbox.com/s/abc/song.mp3?dl=0")
        self.assertEqual(item["url"], "https://www.dropbox.com/s/abc/song.mp3?dl=1")

    def test_google_drive_link_is_probed_after_rewrite(self):
        seen = []

        def fake_probe(url, headers=None):
            seen.append(url)
            return "media", url, "audio/mpeg", b""
        with mock.patch.object(lr, "probe_details", side_effect=fake_probe):
            item = lr.resolve("https://drive.google.com/file/d/AbC123/view")
        self.assertTrue(seen[0].startswith("https://drive.usercontent.google.com/download?id=AbC123"))
        self.assertEqual(item["url"], seen[0])

    def test_extensionless_playlist_is_expanded_and_entries_resolved(self):
        with mock.patch.object(lr, "probe_details", side_effect=lambda u, headers=None: (
                ("playlist", u, "", b"") if u == "http://h/list" else ("media", u, "audio/mpeg", b""))), \
             mock.patch.object(pu, "resolve_playlist", return_value=["http://h:8000/a", "http://h:8000/b"]):
            item = lr.resolve("http://h/list")
        self.assertEqual([i["url"] for i in item["items"]], ["http://h:8000/a", "http://h:8000/b"])
        self.assertEqual(item["url"], "http://h:8000/a")
        self.assertEqual(item["public_url"], "http://h/list")

    def test_single_entry_playlist_is_a_plain_item(self):
        with mock.patch.object(lr, "probe_details", side_effect=lambda u, headers=None: (
                ("playlist", u, "", b"") if u == "http://h/list" else ("media", u, "", b""))), \
             mock.patch.object(pu, "resolve_playlist", return_value=["http://h:8000/a"]):
            item = lr.resolve("http://h/list")
        self.assertNotIn("items", item)
        self.assertEqual(item["url"], "http://h:8000/a")

    def test_unparseable_playlist_is_handed_over_as_is(self):
        with mock.patch.object(lr, "probe_details", side_effect=_probe("playlist")), \
             mock.patch.object(pu, "resolve_playlist", side_effect=lambda u, force=False: [u]):
            item = lr.resolve("http://h/hls")
        self.assertEqual(item["url"], "http://h/hls")

    def test_pls_with_extension_is_expanded(self):
        with mock.patch.object(pu, "resolve_playlist", return_value=["http://a/1.mp3", "http://a/2.mp3"]):
            item = lr.resolve("http://h/radio.pls")
        self.assertEqual(len(item["items"]), 2)

    def test_m3u8_is_not_fetched_by_the_resolver(self):
        with mock.patch.object(pu, "resolve_playlist") as fetch:
            item = lr.resolve("http://h/live.m3u8")
        fetch.assert_not_called()
        self.assertEqual(item["url"], "http://h/live.m3u8")

    def test_order_is_ytdlp_then_scan_then_forced_generic_then_browser(self):
        self.dedicated.return_value = True
        calls = []
        self.try_ytdlp.side_effect = lambda url, **kw: calls.append(("ytdlp", kw)) or None
        self.try_html_scan.side_effect = lambda *a, **kw: calls.append(("scan", {})) or None
        self._browser_item.side_effect = lambda *a, **kw: calls.append(("browser", {})) or None
        with mock.patch.object(lr, "probe_details", side_effect=_probe("unknown")):
            self.assertIsNone(lr.resolve("https://site.example/page"))
        self.assertEqual(calls, [("ytdlp", {}), ("scan", {}), ("ytdlp", {"force_generic": True}), ("browser", {})])

    def test_forced_generic_only_when_a_dedicated_extractor_claimed_the_url(self):
        calls = []
        self.try_ytdlp.side_effect = lambda url, **kw: calls.append(kw) or None
        with mock.patch.object(lr, "probe_details", side_effect=_probe("unknown")):
            lr.resolve("https://plain.example/page")
        self.assertEqual(calls, [{}])

    def test_youtube_failure_skips_the_slow_page_and_browser_tiers(self):
        with mock.patch.object(lr, "probe_details", side_effect=_probe("html")):
            self.assertIsNone(lr.resolve("https://www.youtube.com/watch?v=jNQXAC9IVRw"))
        self.try_html_scan.assert_not_called()
        self._browser_item.assert_not_called()

    def test_bogus_generic_result_is_dropped_and_the_page_scan_runs(self):
        self.try_ytdlp.return_value = {"url": "https://x/player", "title": None, "generic": True}
        self.try_html_scan.return_value = {"url": "https://x/real.mp3", "title": None, "public_url": "u"}
        with mock.patch.object(lr, "probe_details", side_effect=_probe("html")), \
             mock.patch.object(lr, "_is_reachable", return_value=False):
            item = lr.resolve("https://x/page")
        self.assertEqual(item["url"], "https://x/real.mp3")

    def test_reachable_generic_result_is_kept_without_the_flag(self):
        self.try_ytdlp.return_value = {"url": "https://x/a.mp3", "title": None, "generic": True}
        with mock.patch.object(lr, "probe_details", side_effect=_probe("html")), \
             mock.patch.object(lr, "_is_reachable", return_value=True):
            item = lr.resolve("https://x/page")
        self.assertNotIn("generic", item)
        self.assertEqual(item["url"], "https://x/a.mp3")

    def test_expired_budget_stops_everything(self):
        budget = lr._Budget(seconds=-1)
        self.assertIsNone(lr._resolve("https://x/page", budget))
        self.try_ytdlp.assert_not_called()

    def test_resolve_never_raises(self):
        with mock.patch.object(lr, "probe_details", side_effect=RuntimeError("boom")):
            self.assertIsNone(lr.resolve("https://x/page"))


class RealBrowserTierBudgetTest(unittest.TestCase):

    def test_little_time_left_means_no_browser(self):
        with mock.patch("core.browser_extract.is_available", return_value=True), \
             mock.patch("core.browser_extract.extract_stream") as extract:
            self.assertIsNone(lr._browser_item("https://x/p", lr._Budget(seconds=5)))
        extract.assert_not_called()

    def test_enough_time_uses_the_browser_and_attaches_the_referer(self):
        with mock.patch("core.browser_extract.is_available", return_value=True), \
             mock.patch("core.browser_extract.extract_stream", return_value="https://cdn/x.m3u8") as extract:
            item = lr._browser_item("https://x/p", lr._Budget(seconds=60))
        self.assertEqual(item["url"], "https://cdn/x.m3u8")
        self.assertEqual(item["headers"]["referrer"], "https://x/p")
        self.assertLessEqual(extract.call_args.kwargs["timeout_ms"], 20000)


class HtmlTierTest(unittest.TestCase):

    def _scan(self, **kw):
        base = dict(found=None, candidates=[], iframes=[], redirect=None, final="https://p.example/page")
        base.update(kw)
        return hms.PageScan(**base)

    def setUp(self):
        patcher = mock.patch.object(lr, "_stream_headers", return_value=None)
        self.headers = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(lr, "has_dedicated_extractor", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_weak_candidate_that_probes_as_media_wins(self):
        scans = {"https://p.example/page": self._scan(candidates=["https://c.example/live"])}
        with mock.patch.object(hms, "scan_detailed", side_effect=lambda u: scans[u]), \
             mock.patch.object(lr, "probe_details", return_value=("media", "https://c.example/live", "audio/mpeg", b"")):
            item = lr.try_html_scan("https://p.example/page")
        self.assertEqual(item, {"url": "https://c.example/live", "title": None, "public_url": "https://p.example/page"})

    def test_weak_candidate_that_is_a_page_is_scanned_as_a_frame(self):
        scans = {"https://p.example/page": self._scan(candidates=["https://c.example/embed"]),
                 "https://c.example/embed": self._scan(found="https://c.example/a.mp3", final="https://c.example/embed")}
        with mock.patch.object(hms, "scan_detailed", side_effect=lambda u: scans[u]), \
             mock.patch.object(lr, "probe_details", return_value=("html", "https://c.example/embed", "", b"")):
            item = lr.try_html_scan("https://p.example/page")
        self.assertEqual(item["url"], "https://c.example/a.mp3")
        self.assertEqual(item["public_url"], "https://p.example/page")

    def test_weak_candidate_that_is_a_playlist_is_expanded(self):
        scans = {"https://p.example/page": self._scan(candidates=["https://c.example/list"])}
        with mock.patch.object(hms, "scan_detailed", side_effect=lambda u: scans[u]), \
             mock.patch.object(lr, "probe_details", return_value=("playlist", "https://c.example/list", "", b"")), \
             mock.patch.object(pu, "resolve_playlist", return_value=["https://c.example/a.mp3"]):
            item = lr.try_html_scan("https://p.example/page")
        self.assertEqual(item["url"], "https://c.example/a.mp3")

    def test_meta_refresh_target_is_resolved_with_the_full_pipeline(self):
        scans = {"https://p.example/page": self._scan(redirect="https://p.example/real")}
        with mock.patch.object(hms, "scan_detailed", side_effect=lambda u: scans[u]), \
             mock.patch.object(lr, "_resolve", return_value={"url": "https://c/a.mp3", "title": None,
                                                              "public_url": "https://p.example/real"}) as resolve:
            item = lr.try_html_scan("https://p.example/page")
        self.assertEqual(resolve.call_args.args[0], "https://p.example/real")
        self.assertEqual(resolve.call_args.args[2], 1)  # hops
        self.assertEqual(item["url"], "https://c/a.mp3")

    def test_redirect_hops_are_bounded(self):
        scans = {"https://p.example/page": self._scan(redirect="https://p.example/next")}
        with mock.patch.object(hms, "scan_detailed", side_effect=lambda u: scans[u]), \
             mock.patch.object(lr, "_resolve") as resolve:
            self.assertIsNone(lr.try_html_scan("https://p.example/page", hops=lr.MAX_REDIRECT_HOPS))
        resolve.assert_not_called()

    def test_redirect_loop_ends(self):
        # صفحه‌ای که به خودش/دیگری برمی‌گرده: با سقفِ hop تموم می‌شه، نه بی‌نهایت.
        def scan(url):
            return self._scan(redirect=url + "x", final=url)
        with mock.patch.object(hms, "scan_detailed", side_effect=scan), \
             mock.patch.object(lr, "try_ytdlp", return_value=None), \
             mock.patch.object(lr, "probe_details", side_effect=_probe("html")), \
             mock.patch.object(lr, "_browser_item", return_value=None):
            self.assertIsNone(lr.resolve("https://loop.example/a"))

    def test_iframe_chain_goes_three_levels_deep_but_no_further(self):
        chain = {f"https://f.example/{n}": self._scan(iframes=[f"https://f.example/{n + 1}"],
                                                      final=f"https://f.example/{n}") for n in range(0, 6)}
        chain["https://f.example/3"] = self._scan(found="https://c/a.mp3", final="https://f.example/3")
        chain["https://f.example/5"] = self._scan(found="https://c/too-deep.mp3", final="https://f.example/5")
        chain["https://f.example/4"] = self._scan(iframes=["https://f.example/5"], final="https://f.example/4")
        with mock.patch.object(hms, "scan_detailed", side_effect=lambda u: chain[u]):
            item = lr.try_html_scan("https://f.example/0")
            self.assertEqual(item["url"], "https://c/a.mp3")
            chain["https://f.example/3"] = self._scan(iframes=["https://f.example/4"], final="https://f.example/3")
            self.assertIsNone(lr.try_html_scan("https://f.example/0"))

    def test_page_budget_is_enforced(self):
        def scan(url):
            return self._scan(iframes=[url + "/a", url + "/b", url + "/c"], final=url)
        budget = lr._Budget(max_pages=3)
        with mock.patch.object(hms, "scan_detailed", side_effect=scan) as scan_mock:
            self.assertIsNone(lr.try_html_scan("https://f.example", budget=budget))
        self.assertEqual(scan_mock.call_count, 3)

    def test_iframe_with_dedicated_extractor_uses_ytdlp_the_rest_is_scanned(self):
        scans = {"https://p.example/page": self._scan(iframes=["https://ad.example/x", "https://www.aparat.com/video/video/embed/videohash/abc/vt/frame"]),
                 "https://ad.example/x": self._scan(final="https://ad.example/x")}
        with mock.patch.object(hms, "scan_detailed", side_effect=lambda u: scans[u]), \
             mock.patch.object(lr, "has_dedicated_extractor", side_effect=lambda u: "aparat" in u), \
             mock.patch.object(lr, "try_ytdlp", return_value={"url": "https://cdn/v", "title": "t"}) as ytdlp:
            item = lr.try_html_scan("https://p.example/page")
        ytdlp.assert_called_once()
        self.assertEqual(item["url"], "https://cdn/v")

    def test_media_iframe_src_is_used_directly(self):
        scans = {"https://p.example/page": self._scan(iframes=["https://c.example/embed.mp4"])}
        with mock.patch.object(hms, "scan_detailed", side_effect=lambda u: scans[u]):
            item = lr.try_html_scan("https://p.example/page")
        self.assertEqual(item["url"], "https://c.example/embed.mp4")

    def test_headers_from_the_page_travel_with_the_found_media(self):
        self.headers.return_value = {"referrer": "https://p.example/page", "user_agent": "UA"}
        with mock.patch.object(hms, "scan_detailed",
                               return_value=self._scan(found="https://c.example/a.mp3")):
            item = lr.try_html_scan("https://p.example/page")
        self.headers.assert_called_once_with("https://c.example/a.mp3", "https://p.example/page")
        self.assertEqual(item["headers"]["referrer"], "https://p.example/page")

    def test_no_headers_key_when_none_are_needed(self):
        with mock.patch.object(hms, "scan_detailed", return_value=self._scan(found="https://c.example/a.mp3")):
            item = lr.try_html_scan("https://p.example/page")
        self.assertNotIn("headers", item)


class StreamHeadersTest(unittest.TestCase):

    def test_hls_always_gets_referer_and_ua(self):
        with mock.patch.object(net, "probe") as probe:
            headers = lr._stream_headers("https://c/live.m3u8?x=1", "https://p/page")
        probe.assert_not_called()
        self.assertEqual(headers["referrer"], "https://p/page")
        self.assertTrue(headers["user_agent"])

    def test_file_that_plays_without_referer_needs_none(self):
        with mock.patch.object(net, "probe", return_value=("u", "audio/mpeg", b"")):
            self.assertIsNone(lr._stream_headers("https://c/a.mp3", "https://p/page"))

    def test_file_that_is_refused_gets_the_page_as_referer(self):
        with mock.patch.object(net, "probe", side_effect=OSError("403")):
            headers = lr._stream_headers("https://c/a.mp3", "https://p/page")
        self.assertEqual(headers["referrer"], "https://p/page")

    def test_no_page_no_headers(self):
        self.assertIsNone(lr._stream_headers("https://c/a.mp3", None))
        self.assertIsNone(lr._stream_headers("https://c/a.mp3", "https://c/a.mp3"))

    def test_ytdlp_info_referer_becomes_player_headers(self):
        info = {"url": "https://c/a.mp3", "title": "t",
                "http_headers": {"User-Agent": "UA", "Referer": "https://p/page"}}
        item = lr._item_from_info(info, "https://p/page")
        self.assertEqual(item["headers"], {"referrer": "https://p/page", "user_agent": "UA"})

    def test_ytdlp_default_headers_without_referer_are_not_forwarded(self):
        info = {"url": "https://c/a.mp3", "http_headers": {"User-Agent": "UA"}}
        self.assertNotIn("headers", lr._item_from_info(info, "https://p"))

    def test_generic_extractor_results_are_flagged_for_validation(self):
        info = {"url": "https://c/a.mp3", "extractor_key": "Generic"}
        self.assertTrue(lr._item_from_info(info, "https://p")["generic"])
        self.assertNotIn("generic", lr._item_from_info({"url": "u", "extractor_key": "Youtube"}, "p"))

    def test_reachability_uses_the_item_referer_and_rejects_html(self):
        item = {"url": "https://c/a.mp3", "headers": {"referrer": "https://p/page"}}
        with mock.patch.object(net, "probe", return_value=("u", "audio/mpeg", b"")) as probe:
            self.assertTrue(lr._is_reachable(item))
        self.assertEqual(probe.call_args.kwargs["headers"], {"Referer": "https://p/page"})
        with mock.patch.object(net, "probe", return_value=("u", "text/html", b"<html>")):
            self.assertFalse(lr._is_reachable(item))
        with mock.patch.object(net, "probe", side_effect=OSError("404")):
            self.assertFalse(lr._is_reachable(item))


class ForceGenericTest(unittest.TestCase):

    def test_force_generic_asks_ytdlp_for_the_generic_extractor(self):
        fake = mock.MagicMock()
        fake.__enter__.return_value = fake
        fake.extract_info.return_value = {"url": "https://c/a.mp3", "title": "t"}
        with mock.patch("yt_dlp.YoutubeDL", return_value=fake):
            item = lr.try_ytdlp("https://site.example/page", force_generic=True)
        fake.extract_info.assert_called_once_with("https://site.example/page", download=False, ie_key="Generic")
        self.assertEqual(item["url"], "https://c/a.mp3")

    def test_dedicated_extractor_detection(self):
        self.assertTrue(lr.has_dedicated_extractor("https://soundcloud.com/forss/flickermood"))
        self.assertFalse(lr.has_dedicated_extractor("https://no-such-site.example/page"))


class IcyStreamTest(unittest.TestCase):

    def _serve(self, reply):
        import socket
        import threading
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        self.addCleanup(server.close)

        def run():
            try:
                conn, _ = server.accept()
                conn.recv(1024)
                conn.sendall(reply)
                conn.close()
            except OSError:
                pass
        threading.Thread(target=run, daemon=True).start()
        return f"http://127.0.0.1:{server.getsockname()[1]}/;stream"

    def test_icy_status_line_is_detected(self):
        self.assertTrue(net.is_icy_stream(self._serve(b"ICY 200 OK" + CRLF + b"icy-name:x" + CRLF + CRLF)))

    def test_normal_http_and_dead_hosts_are_not_icy(self):
        self.assertFalse(net.is_icy_stream(self._serve(b"HTTP/1.0 200 OK" + CRLF + CRLF)))
        self.assertFalse(net.is_icy_stream("https://secure.example/x"))
        self.assertFalse(net.is_icy_stream("http://127.0.0.1:9/x", timeout=1))

    def test_failed_probe_of_an_icy_server_is_media(self):
        with mock.patch.object(net, "probe", side_effect=OSError("bad status line")),              mock.patch.object(net, "is_icy_stream", return_value=True):
            self.assertEqual(lr.probe_details("http://h:8000/;")[0], "media")

    def test_failed_probe_of_anything_else_is_unknown(self):
        with mock.patch.object(net, "probe", side_effect=OSError("down")),              mock.patch.object(net, "is_icy_stream", return_value=False):
            self.assertEqual(lr.probe_details("http://h:8000/x"), ("unknown", "http://h:8000/x", "", b""))


class NetBoundsTest(unittest.TestCase):

    def test_probe_adds_extra_headers_to_the_range_request(self):
        with mock.patch.object(net, "_urlopen_with_fallback", return_value=("u", "", b"")) as opener:
            net.probe("https://c/x", headers={"Referer": "https://p/"})
        sent = opener.call_args.args[1]
        self.assertEqual(sent["Referer"], "https://p/")
        self.assertIn("Range", sent)

    def test_fetch_passes_the_byte_cap_to_the_reader(self):
        response = mock.Mock(url="https://c/x")
        response.read.return_value = b"abc"

        def fake_open(url, headers, timeout, label, what, read):
            return read(response)
        with mock.patch.object(net, "_urlopen_with_fallback", side_effect=fake_open):
            net.fetch("https://c/x", max_bytes=100)
            response.read.assert_called_with(100)
            net.fetch("https://c/x")
            response.read.assert_called_with()


class LoadAndPlayHeadersTest(unittest.TestCase):
    """bot.load_and_play: هدرهای resolver با مکانیزمِ IPTV روی mpv می‌شینن."""

    def _play(self, items, service_name=None):
        fake_track = mock.Mock(url="u", title="t", public_url=None, private=True)
        fake_queue = mock.Mock()
        fake_queue.replace.return_value = (1, fake_track)
        fake_queue.meta.return_value = []
        order = []
        with mock.patch.object(bot, "_expand_item", side_effect=lambda u, t, p, pr, verified=False: [(u, t, p, pr)]), \
             mock.patch.object(bot, "documentary"), \
             mock.patch.object(bot, "iptv") as iptv, \
             mock.patch.object(bot, "live_dvr"), \
             mock.patch.object(bot, "history"), \
             mock.patch.object(bot, "_roam_clear_deadline"), \
             mock.patch.object(bot, "bot") as fake_bot, \
             mock.patch.object(bot, "player") as fake_player:
            iptv.SERVICE_NAME = "iptv"
            iptv.clear.side_effect = lambda b: order.append("clear")
            iptv.apply_stream_headers.side_effect = lambda b, h: order.append("apply")
            fake_bot.search_lock = mock.MagicMock()
            fake_bot.playback_lock = mock.MagicMock()
            fake_queue.replace.side_effect = lambda *a, **k: order.append("play") or (1, fake_track)
            fake_bot.queue = fake_queue
            fake_bot.playback_mode = 2
            fake_bot.search_session = {}
            fake_bot.playlist_growth_session = {}
            fake_player.is_paused = False
            bot.load_and_play(items, private=True, service_name=service_name)
        return iptv, order

    def test_headers_are_applied_after_clear_and_before_playing(self):
        headers = {"referrer": "https://p/page", "user_agent": "UA"}
        iptv, order = self._play([{"url": "https://c/a.mp3", "headers": headers}])
        iptv.apply_stream_headers.assert_called_once()
        self.assertEqual(iptv.apply_stream_headers.call_args.args[1], headers)
        self.assertEqual(order, ["clear", "apply", "play"])

    def test_no_headers_no_call(self):
        iptv, order = self._play([{"url": "https://c/a.mp3"}, "https://c/b.mp3"])
        iptv.apply_stream_headers.assert_not_called()
        self.assertEqual(order, ["clear", "play"])

    def test_iptv_own_playback_is_left_alone(self):
        iptv, _ = self._play([{"url": "https://c/a.mp3", "headers": {"referrer": "r"}}], service_name="iptv")
        iptv.apply_stream_headers.assert_not_called()


class ResolvedItemIsStillPrivateTest(unittest.TestCase):
    """لینکِ کاربر همیشه private=True، حتی وقتی resolver هدر/پلی‌لیست می‌ده."""

    def test_private_and_headers_reach_load_and_play(self):
        from tests.test_smart_link_handling import FakeBot, _ctx
        from core import command_helpers, i18n
        i18n.load_languages()
        i18n.set_language("en")
        fake = FakeBot({})
        item = {"url": "https://c/a.mp3", "title": None, "public_url": "https://p/page",
                "headers": {"referrer": "https://p/page"}}
        with mock.patch.object(lr, "resolve", return_value=item), \
             mock.patch("core.command_helpers._wait_for_duration", return_value=200):
            command_helpers.run_link_command(fake, _ctx(fake), "https://p/page")
        items, private, service = fake.load_and_play_calls[0]
        self.assertTrue(private)
        self.assertEqual(items["headers"], item["headers"])

    def test_dropbox_direct_shortcut_uses_the_rewritten_link(self):
        from core import command_helpers
        item = command_helpers._generic_item("https://www.dropbox.com/s/abc/song.mp3?dl=0")
        self.assertEqual(item["url"], "https://www.dropbox.com/s/abc/song.mp3?dl=1")


if __name__ == "__main__":
    unittest.main()

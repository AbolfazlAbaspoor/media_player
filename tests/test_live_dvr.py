"""
core/live_dvr.py: قابلیتِ cld (لایو با برگشت‌به‌عقب). آفلاین -- شبکه/yt-dlp/mpv
واقعی هیچ‌جا اجرا نمی‌شن، فقط منطقِ سقفِ منابع، لایسنس، و پاک‌سازی.
"""

import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

from core import live_dvr


class FakeBot:
    def __init__(self, allowed=True):
        self._allowed = allowed
        self.player = mock.Mock()
        self.live_dvr_session = None

    services = {}


class LicensedTest(unittest.TestCase):
    def test_licensed_reads_bot_allows_service_for_the_right_name(self):
        bot = FakeBot()
        with mock.patch("core.live_dvr.license_gate.bot_allows_service", return_value=True) as m:
            self.assertTrue(live_dvr.licensed(bot))
        m.assert_called_once_with(bot, "live_dvr")

    def test_not_licensed(self):
        bot = FakeBot()
        with mock.patch("core.live_dvr.license_gate.bot_allows_service", return_value=False):
            self.assertFalse(live_dvr.licensed(bot))


class ResourceCapTest(unittest.TestCase):
    """
    hook() (داخلِ _download_thread) باید با رسیدنِ سقفِ زمان یا حجم
    DownloadCancelled بندازه -- بدونِ نیاز به شبکه/yt-dlp واقعی: خودِ
    _download_thread رو با یه YoutubeDL جعلی صدا می‌زنیم که فقط hook رو
    با مقادیرِ دلخواه امتحان می‌کنه.
    """

    def _run_with_fake_ydl(self, cap_seconds, cap_bytes, hook_calls, start_time_offset=0):
        session = {"stop_event": threading.Event(), "download_done": False, "tmpdir": tempfile.mkdtemp()}
        self.addCleanup(shutil.rmtree, session["tmpdir"], ignore_errors=True)
        captured_hook = {}

        class FakeYDL:
            def __init__(self, opts):
                captured_hook["hook"] = opts["progress_hooks"][0]

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def download(self, urls):
                for call in hook_calls:
                    captured_hook["hook"](call)

        with mock.patch("core.live_dvr.ytdlp_lazy.YoutubeDL", FakeYDL), \
             mock.patch("core.live_dvr.time.time", side_effect=[start_time_offset] + [
                 start_time_offset + c.get("_t", 0) for c in hook_calls] * 2):
            live_dvr._download_thread(FakeBot(), session, "https://x", None, cap_seconds, cap_bytes)
        self.assertTrue(session["download_done"])

    def test_byte_cap_stops_download(self):
        # اولین hook زیرِ سقف، دومی بالاش -- نباید کرش کنه (DownloadCancelled
        # گرفته می‌شه، نه این‌که تا بالا propagate بشه).
        self._run_with_fake_ydl(
            cap_seconds=10_000, cap_bytes=1000,
            hook_calls=[{"downloaded_bytes": 500, "_t": 0}, {"downloaded_bytes": 2000, "_t": 0}])

    def test_stop_event_cancels_immediately(self):
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)
        session = {"stop_event": threading.Event(), "download_done": False, "tmpdir": tmpdir}
        session["stop_event"].set()
        captured_hook = {}

        class FakeYDL:
            def __init__(self, opts):
                captured_hook["hook"] = opts["progress_hooks"][0]

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def download(self, urls):
                captured_hook["hook"]({"downloaded_bytes": 1})

        with mock.patch("core.live_dvr.ytdlp_lazy.YoutubeDL", FakeYDL):
            live_dvr._download_thread(FakeBot(), session, "https://x", None, 10_000, 10_000_000)
        self.assertTrue(session["download_done"])


class FindPartFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_ignores_fragment_files_picks_main_part(self):
        open(os.path.join(self.tmp, "stream.m4a.part-Frag12.part"), "wb").write(b"x" * 10)
        main = os.path.join(self.tmp, "stream.m4a.part")
        open(main, "wb").write(b"x" * 1000)
        found = live_dvr._find_part_file(self.tmp)
        self.assertEqual(found, main)

    def test_empty_dir_returns_none(self):
        self.assertIsNone(live_dvr._find_part_file(self.tmp))


class ClearTest(unittest.TestCase):
    def test_clear_is_a_safe_noop_without_a_session(self):
        bot = FakeBot()
        live_dvr.clear(bot)  # نباید استثنا بندازه
        self.assertIsNone(bot.live_dvr_session)

    def test_clear_stops_thread_restores_mpv_and_removes_tmpdir(self):
        bot = FakeBot()
        tmpdir = tempfile.mkdtemp()
        open(os.path.join(tmpdir, "stream.m4a.part"), "wb").write(b"x")
        bot.player.raw.keep_open = "yes"
        bot.player.raw.keep_open_pause = "no"

        stop_event = threading.Event()
        thread = mock.Mock()
        thread.is_alive.return_value = False
        bot.live_dvr_session = {
            "bot": bot, "tmpdir": tmpdir, "stop_event": stop_event, "thread": thread,
            "active": True, "keep_open_defaults": {"keep_open": "no", "keep_open_pause": "yes"},
        }

        live_dvr.clear(bot)

        self.assertTrue(stop_event.is_set())
        self.assertIsNone(bot.live_dvr_session)
        self.assertFalse(os.path.isdir(tmpdir))
        self.assertEqual(bot.player.raw.keep_open, "no")
        self.assertEqual(bot.player.raw.keep_open_pause, "yes")


class IsActiveTest(unittest.TestCase):
    def test_false_without_session(self):
        self.assertFalse(live_dvr.is_active(FakeBot()))

    def test_true_only_when_active_flag_set(self):
        bot = FakeBot()
        bot.live_dvr_session = {"active": False}
        self.assertFalse(live_dvr.is_active(bot))
        bot.live_dvr_session["active"] = True
        self.assertTrue(live_dvr.is_active(bot))


def _box(kind, payload=b""):
    import struct
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


class SplitHeaderTest(unittest.TestCase):
    def test_keeps_only_ftyp_and_moov(self):
        data = _box(b"ftyp", b"AAAA") + _box(b"moov", b"BB") + _box(b"moof", b"CC") + _box(b"mdat", b"DDD")
        self.assertEqual(live_dvr.split_mp4_header(data), _box(b"ftyp", b"AAAA") + _box(b"moov", b"BB"))

    def test_no_moov_returns_empty(self):
        self.assertEqual(live_dvr.split_mp4_header(_box(b"moof", b"x") + _box(b"mdat", b"y")), b"")

    def test_truncated_box_stops_safely(self):
        data = _box(b"ftyp", b"AAAA") + _box(b"moov", b"BB") + _box(b"mdat", b"D" * 10)[:-3]
        self.assertEqual(live_dvr.split_mp4_header(data), _box(b"ftyp", b"AAAA") + _box(b"moov", b"BB"))

    def test_garbage_is_safe(self):
        self.assertEqual(live_dvr.split_mp4_header(b"\x00\x01"), b"")


class SqHelpersTest(unittest.TestCase):
    def test_sq_roundtrip(self):
        url = "https://h/videoplayback?id=1&sq=7&x=y"
        self.assertEqual(live_dvr._sq_of(url), 7)
        self.assertEqual(live_dvr._sq_of(live_dvr._with_sq(url, 0)), 0)
        self.assertIn("id=1", live_dvr._with_sq(url, 0))

    def test_sq_missing(self):
        self.assertIsNone(live_dvr._sq_of("https://h/v?id=1"))

    def test_compute_start_sq(self):
        self.assertEqual(live_dvr.compute_start_sq(1000, 10, 2.0), 700)
        self.assertEqual(live_dvr.compute_start_sq(1000, 10, 5), 880)
        self.assertEqual(live_dvr.compute_start_sq(1000, 10, None), 700)

    def test_compute_start_sq_never_below_one(self):
        self.assertEqual(live_dvr.compute_start_sq(50, 30, 2.0), 1)

    def test_find_fragment_generator(self):
        def gen(ctx):
            return iter(())
        self.assertEqual(live_dvr.find_fragment_generator({"fragments": gen, "target_duration": 2}), (gen, 2))
        self.assertEqual(live_dvr.find_fragment_generator({"requested_formats": [{"fragments": gen}]}), (gen, None))
        self.assertEqual(live_dvr.find_fragment_generator({"fragments": [1, 2]}), (None, None))


class _Resp:
    def __init__(self, data):
        self._d = data

    def read(self):
        return self._d


class DvrThreadTest(unittest.TestCase):
    """دانلودِ v2 با یه YoutubeDL جعلی: هدر از sq=0، backfill از start_sq، بعدش tail."""

    HEAD = 100

    def _session(self):
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)
        return {"stop_event": threading.Event(), "download_done": False,
                "backfill_done": threading.Event(), "tmpdir": tmpdir}

    def _fake(self, tail=3, info_extra=None, calls=None, header_ok=True):
        head = self.HEAD
        header_body = _box(b"ftyp", b"F") + _box(b"moov", b"M") + _box(b"moof", b"0") + _box(b"mdat", b"0")

        def fragments(ctx):
            for i in range(head + tail):
                yield {"url": "https://h/v?id=1&sq=%d" % i, "fragment_count": head}

        class FakeYDL:
            def __init__(self, opts):
                if calls is not None:
                    calls.append(opts)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def extract_info(self, url, download=True):
                info = {"fragments": fragments, "target_duration": 2}
                info.update(info_extra or {})
                return info

            def urlopen(self, url):
                sq = live_dvr._sq_of(url)
                if sq == 0:
                    return _Resp(header_body if header_ok else b"junk")
                return _Resp(b"<%d>" % sq)

        return FakeYDL

    def test_backfill_then_tail_written_in_order(self):
        session = self._session()
        with mock.patch("core.live_dvr.ytdlp_lazy.YoutubeDL", self._fake()):
            live_dvr._dvr_thread(FakeBot(), session, "https://x", None, 1, 10_000, 10**9)
        self.assertTrue(session["download_done"])
        self.assertTrue(session["backfill_done"].is_set())
        self.assertEqual(session["start_sq"], self.HEAD - 30)
        data = open(os.path.join(session["tmpdir"], "stream.dvr.part"), "rb").read()
        expected = _box(b"ftyp", b"F") + _box(b"moov", b"M") + b"".join(
            b"<%d>" % i for i in range(self.HEAD - 30, self.HEAD + 3))
        self.assertEqual(data, expected)
        # بخشِ قبل از start_sq (مدیای اولِ برودکست) نباید توی فایل باشه.
        self.assertNotIn(b"<5>", data)

    def test_byte_cap_stops_download(self):
        session = self._session()
        with mock.patch("core.live_dvr.ytdlp_lazy.YoutubeDL", self._fake(tail=50)):
            live_dvr._dvr_thread(FakeBot(), session, "https://x", None, 1, 10_000, 200)
        size = os.path.getsize(os.path.join(session["tmpdir"], "stream.dvr.part"))
        self.assertLess(size, 400)
        self.assertTrue(session["download_done"])

    def test_stop_event_before_start(self):
        session = self._session()
        session["stop_event"].set()
        with mock.patch("core.live_dvr.ytdlp_lazy.YoutubeDL", self._fake()):
            live_dvr._dvr_thread(FakeBot(), session, "https://x", None, 1, 10_000, 10**9)
        self.assertTrue(session["download_done"])
        self.assertTrue(session["backfill_done"].is_set())

    def test_no_header_fails_cleanly(self):
        session = self._session()
        with mock.patch("core.live_dvr.ytdlp_lazy.YoutubeDL", self._fake(header_ok=False)):
            live_dvr._dvr_thread(FakeBot(), session, "https://x", None, 1, 10_000, 10**9)
        self.assertFalse(os.path.exists(os.path.join(session["tmpdir"], "stream.dvr.part")))
        self.assertTrue(session["backfill_done"].is_set())
        self.assertTrue(session["download_done"])

    def test_falls_back_to_legacy_without_generator(self):
        session = self._session()
        fake = self._fake(info_extra={"fragments": None})
        with mock.patch("core.live_dvr.ytdlp_lazy.YoutubeDL", fake), \
             mock.patch("core.live_dvr._download_thread") as legacy:
            live_dvr._dvr_thread(FakeBot(), session, "https://x", None, 1, 10_000, 10**9)
        legacy.assert_called_once()
        self.assertTrue(session["backfill_done"].is_set())

    def test_proxy_and_live_from_start_passed_to_ytdlp(self):
        session = self._session()
        calls = []
        with mock.patch("core.live_dvr.ytdlp_lazy.YoutubeDL", self._fake(calls=calls)), \
             mock.patch("core.live_dvr.proxy_state.get_proxy_url", return_value="http://127.0.0.1:2080"):
            live_dvr._dvr_thread(FakeBot(), session, "https://x", None, 1, 10_000, 10**9)
        self.assertEqual(calls[0]["proxy"], "http://127.0.0.1:2080")
        self.assertTrue(calls[0]["live_from_start"])


class SeekToEdgeTest(unittest.TestCase):
    def test_seeks_near_end(self):
        bot = FakeBot()
        bot.player.raw.duration = 300.0
        live_dvr._seek_to_live_edge(bot)
        bot.player.raw.seek.assert_called_once_with(300.0 - live_dvr._EDGE_MARGIN_SECONDS, reference="absolute")

    def test_unknown_duration_does_nothing(self):
        bot = FakeBot()
        bot.player.raw.duration = None
        live_dvr._seek_to_live_edge(bot)
        bot.player.raw.seek.assert_not_called()


class BackSettingsTest(unittest.TestCase):
    def test_defaults(self):
        bot = FakeBot()
        self.assertGreaterEqual(live_dvr.default_back_minutes(bot), 1)
        self.assertGreaterEqual(live_dvr.max_back_minutes(bot), live_dvr.default_back_minutes(bot))
        self.assertGreaterEqual(live_dvr.backfill_timeout_seconds(bot), 1)


class CldCommandArgsTest(unittest.TestCase):
    def _ctx(self, args):
        bot = mock.Mock()
        bot.require_channel_service.return_value = ("youtube", mock.Mock())
        bot.last_channel_url = "https://ch"
        bot.config = {}
        return {"bot": bot, "uid": 1, "nickname": "n", "username": "u", "args": args}

    def _run(self, args, start_result=None):
        from commands import cld
        ctx = self._ctx(args)
        with mock.patch("commands.cld.live_dvr.licensed", return_value=True), \
             mock.patch("commands.cld.live_dvr.max_back_minutes", return_value=120), \
             mock.patch("commands.cld.live_dvr.start",
                        return_value=start_result or {"title": "T", "back_minutes": 5}) as start:
            cld.run(ctx)
        return ctx, start

    def test_no_args_uses_default(self):
        _, start = self._run([])
        self.assertIsNone(start.call_args.kwargs["back_minutes"])

    def test_minutes_passed(self):
        _, start = self._run(["30"])
        self.assertEqual(start.call_args.kwargs["back_minutes"], 30)

    def test_bad_minutes_rejected_without_starting(self):
        for bad in ("abc", "0", "-5", "9999"):
            ctx, start = self._run([bad])
            start.assert_not_called()
            ctx["bot"].t.user_message.assert_called_once()


class StartBackMinutesTest(unittest.TestCase):
    def test_minutes_clamped_and_passed_to_thread(self):
        bot = FakeBot()
        service = mock.Mock()
        service.get_channel_live.return_value = [{"url": "https://w", "title": "T"}]
        seen = {}

        def fake_thread(bot_, session, url, cookiefile, back_minutes, cap_seconds, cap_bytes):
            seen["back"] = back_minutes
            session["backfill_done"].set()
            session["download_done"] = True

        with mock.patch("core.live_dvr.licensed", return_value=True), \
             mock.patch("core.live_dvr._dvr_thread", fake_thread), \
             mock.patch("core.live_dvr.max_back_minutes", return_value=60), \
             mock.patch("core.live_dvr.start_wait_seconds", return_value=0), \
             mock.patch("core.live_dvr._START_TIMEOUT_EXTRA_SECONDS", 0), \
             mock.patch("core.live_dvr.backfill_timeout_seconds", return_value=1):
            with self.assertRaises(live_dvr.LiveDVRError):
                live_dvr.start(bot, service, "https://ch", back_minutes=999)
        self.assertEqual(seen["back"], 60)
        # سشنِ ناموفق باید پاک شده باشه (پوشه‌ی موقت نمونه).
        self.assertIsNone(bot.live_dvr_session)


if __name__ == "__main__":
    unittest.main()

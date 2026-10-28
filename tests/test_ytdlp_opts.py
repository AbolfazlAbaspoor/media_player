"""
گزینه‌ی js_runtimes باید توی هر دیکشنریِ opts واقعیِ yt-dlp باشه --
core/ytdlp_opts.py و جاهایی که ازش استفاده می‌کنن. بدون شبکه: فقط
patch کردن core.platform_paths.js_runtime و چک کردن دیکشنری نهایی.
"""

import unittest
from unittest import mock

from core import ytdlp_opts
from core.services.soundcloud import SoundCloud
from core.services.tiktok import TikTok


class WithJsRuntimeTest(unittest.TestCase):

    def setUp(self):
        ytdlp_opts._reset_cache()

    def tearDown(self):
        ytdlp_opts._reset_cache()

    def test_adds_key_when_a_runtime_is_found(self):
        with mock.patch.object(ytdlp_opts.platform_paths, "js_runtime",
                                return_value={"deno": {"path": "/bin/deno"}}):
            opts = ytdlp_opts.with_js_runtime({})
        self.assertEqual(opts["js_runtimes"], {"deno": {"path": "/bin/deno"}})

    def test_no_key_when_nothing_found(self):
        with mock.patch.object(ytdlp_opts.platform_paths, "js_runtime", return_value={}):
            opts = ytdlp_opts.with_js_runtime({})
        self.assertNotIn("js_runtimes", opts)

    def test_result_is_cached_across_calls(self):
        probe = mock.Mock(return_value={"node": {"path": "/bin/node"}})
        with mock.patch.object(ytdlp_opts.platform_paths, "js_runtime", probe):
            ytdlp_opts.with_js_runtime({})
            ytdlp_opts.with_js_runtime({})
        self.assertEqual(probe.call_count, 1)


class ServiceBaseWiringTest(unittest.TestCase):
    """هر سرویسِ روی پایه‌ی مشترک، opts نهایی‌ش باید js_runtimes داشته باشه."""

    def setUp(self):
        ytdlp_opts._reset_cache()

    def tearDown(self):
        ytdlp_opts._reset_cache()

    def test_base_opts_carry_js_runtimes(self):
        with mock.patch.object(ytdlp_opts.platform_paths, "js_runtime",
                                return_value={"deno": {"path": "/bin/deno"}}):
            for cls in (SoundCloud, TikTok):
                opts = cls()._opts()
                self.assertEqual(opts.get("js_runtimes"), {"deno": {"path": "/bin/deno"}}, cls.__name__)

    def test_base_opts_omit_key_when_no_runtime(self):
        with mock.patch.object(ytdlp_opts.platform_paths, "js_runtime", return_value={}):
            opts = SoundCloud()._opts()
        self.assertNotIn("js_runtimes", opts)


if __name__ == "__main__":
    unittest.main()

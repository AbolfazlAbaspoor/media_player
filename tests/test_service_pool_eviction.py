"""
گزارش کاربر (2026-09-27): بعد از افزودن pool کردنِ نمونه‌های YoutubeDL،
چند سرویس (از جمله youtubemusic) گاهی "internal error" می‌دادن. یه نمونه‌ی
pool‌شده که یه بار extract_info‌ش fail شده ممکنه توی وضعیتِ بد بمونه
(اتصالِ HTTP نصفه‌کاره‌ی مرده) و همون نمونه‌ی خراب برای درخواست‌های بعدیِ
همون سرویس دوباره برگردونده بشه تا ربات ری‌استارت بشه. این تست تضمین
می‌کنه شکستِ extract_info نمونه رو از pool دور می‌ریزه.
"""

import unittest
from unittest import mock

from core import service_pool


class FakeYDL:
    instances_created = 0

    def __init__(self, opts):
        FakeYDL.instances_created += 1
        self.opts = dict(opts)
        self.calls = 0
        self.closed = False

    def extract_info(self, target, download=False):
        self.calls += 1
        raise RuntimeError("boom")

    def close(self):
        self.closed = True


class ServicePoolEvictionTest(unittest.TestCase):
    def setUp(self):
        FakeYDL.instances_created = 0
        service_pool.cleanup_yt_instances()

    def tearDown(self):
        service_pool.cleanup_yt_instances()

    def test_evict_removes_and_closes_the_pooled_instance(self):
        with mock.patch("core.service_pool.YoutubeDL", FakeYDL):
            first = service_pool.get_yt_instance("svc", {"a": 1})
            self.assertIs(service_pool.get_yt_instance("svc", {"a": 1}), first)

            service_pool.evict("svc", {"a": 1})
            self.assertTrue(first.closed)

            second = service_pool.get_yt_instance("svc", {"a": 1})
            self.assertIsNot(second, first)

    def test_extract_with_fallback_evicts_broken_instance_on_failure(self):
        from core import proxy_retry
        with mock.patch("core.service_pool.YoutubeDL", FakeYDL), \
             mock.patch("core.proxy_retry.proxy_state.get_proxy_url", return_value=None), \
             mock.patch("core.proxy_retry.bot_context.bot", mock.Mock()):
            with self.assertRaises(RuntimeError):
                proxy_retry.extract_with_fallback({"a": 1}, "http://x", label="svc")
            # نمونه‌ی خراب باید دور ریخته شده باشه؛ تلاشِ بعدی نمونه‌ی تازه می‌سازه.
            with self.assertRaises(RuntimeError):
                proxy_retry.extract_with_fallback({"a": 1}, "http://x", label="svc")
        self.assertEqual(FakeYDL.instances_created, 2)

    def test_extract_pooled_evicts_broken_instance_on_failure(self):
        from core import proxy_retry
        with mock.patch("core.service_pool.YoutubeDL", FakeYDL), \
             mock.patch("core.proxy_retry.proxy_state.get_proxy_url", return_value=None):
            with self.assertRaises(RuntimeError):
                proxy_retry.extract_pooled("svc", {"a": 1}, "http://x")
            with self.assertRaises(RuntimeError):
                proxy_retry.extract_pooled("svc", {"a": 1}, "http://x")
        self.assertEqual(FakeYDL.instances_created, 2)


if __name__ == "__main__":
    unittest.main()

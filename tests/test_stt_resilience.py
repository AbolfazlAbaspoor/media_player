"""
تست‌های تاب‌آوریِ تشخیص گفتار (core/stt.py): retry از مسیرِ دیگه، cooldown،
fallback به موتورِ تنظیم‌شده و نشتِ کلید. کاملاً آفلاین: perform با یه
transport ساختگی جایگزین می‌شه و زمان/خواب mock است.
"""

import json
import unittest
from unittest import mock

from core import i18n
from core import stt

SECRET = "AIzaSECRETKEY123456"
GOOD = b'{"result":[{"alternative":[{"transcript":"hello"}]}]}\n'


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds


class ResilienceTest(unittest.TestCase):

    def setUp(self):
        stt.reset_guards()
        self.clock = FakeClock()
        for target, value in (("_now", self.clock.now), ("_sleep", self.clock.sleep)):
            patcher = mock.patch.object(stt, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(stt.proxy_state, "get_proxy_url", return_value="http://127.0.0.1:2080")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(stt.reset_guards)

    def timeouts(self, script):
        """perform ساختگی: هر عنصر یا bytes است یا یه خطا؛ مسیرها ثبت می‌شن."""
        routes = []
        items = list(script)

        def fake(request, timeout, secrets=(), route="auto"):
            routes.append(route)
            item = items.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        return fake, routes

    def test_retry_via_other_route_then_success(self):
        fake, routes = self.timeouts([stt.TransientSpeechError("slow", "timeout"), GOOD])
        with mock.patch.object(stt, "perform", fake):
            text = stt.GoogleEngine({"google_key": SECRET}).transcribe(b"\x00\x00", "en-US", 20)
        self.assertEqual(text, "hello")
        self.assertEqual(routes, ["auto", "direct"])
        self.assertIn(stt.RETRY_BACKOFF_SECONDS, self.clock.slept)

    def test_permanent_error_is_not_retried(self):
        fake, routes = self.timeouts([stt.SpeechToTextError("bad key")])
        with mock.patch.object(stt, "perform", fake):
            with self.assertRaises(stt.SpeechToTextError):
                stt.GoogleEngine({}).transcribe(b"\x00\x00", "en-US", 20)
        self.assertEqual(len(routes), 1)

    def test_throttle_then_cooldown_answers_immediately(self):
        err = stt.TransientSpeechError("x", "timeout")
        fake, routes = self.timeouts([err, err])
        engine = stt.GoogleEngine({})
        with mock.patch.object(stt, "perform", fake):
            with self.assertRaises(stt.SpeechThrottledError) as first:
                engine.transcribe(b"\x00\x00", "en-US", 20)
            self.assertEqual(len(routes), 2)
            slept_before = len(self.clock.slept)
            with self.assertRaises(stt.SpeechThrottledError) as second:
                engine.transcribe(b"\x00\x00", "en-US", 20)
        self.assertEqual(len(routes), 2)  # هیچ درخواستِ جدیدی نرفت
        self.assertEqual(len(self.clock.slept), slept_before)  # هیچ انتظاری
        self.assertLessEqual(second.exception.retry_after, first.exception.retry_after)
        # بعد از cooldown دوباره تلاش می‌شه.
        self.clock.t += 400
        fake2, routes2 = self.timeouts([GOOD])
        with mock.patch.object(stt, "perform", fake2):
            self.assertEqual(engine.transcribe(b"\x00\x00", "en-US", 20), "hello")

    def test_fallback_engine_used_only_when_configured(self):
        err = stt.TransientSpeechError("x", "timeout")

        def fake(request, timeout, secrets=(), route="auto"):
            if "google.com" in request.full_url:
                raise err
            return json.dumps({"text": "from whisper"}).encode()

        with mock.patch.object(stt, "perform", fake):
            settings = {"openai_api_key": "sk-abcdef"}
            self.assertEqual(
                stt.transcribe_with_fallback("google", settings, b"\x00\x00", "en-US", 20),
                "from whisper")
            stt.reset_guards()
            with self.assertRaises(stt.SpeechThrottledError):
                stt.transcribe_with_fallback("google", {}, b"\x00\x00", "en-US", 20)

    def test_no_key_in_user_message(self):
        err = stt.TransientSpeechError("x", "timeout")
        fake, _ = self.timeouts([err, err])
        with mock.patch.object(stt, "perform", fake):
            with self.assertRaises(stt.SpeechThrottledError) as ctx:
                stt.GoogleEngine({"google_key": SECRET}).transcribe(b"\x00\x00", "en-US", 20)
        for lang in ("en", "fa"):
            i18n.set_language(lang) if hasattr(i18n, "set_language") else None
            message = i18n.t("vs_throttled", seconds=ctx.exception.retry_after)
            self.assertNotIn(SECRET, message)
            self.assertNotIn("google.com", message)
        self.assertNotIn(SECRET, str(ctx.exception))

    def test_i18n_placeholders_match(self):
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data = {}
        for lang in ("en", "fa"):
            with open(os.path.join(root, "languages", f"{lang}.json"), encoding="utf-8") as f:
                data[lang] = json.load(f)["strings"]["vs_throttled"]
        self.assertIn("{seconds}", data["en"])
        self.assertIn("{seconds}", data["fa"])


if __name__ == "__main__":
    unittest.main()

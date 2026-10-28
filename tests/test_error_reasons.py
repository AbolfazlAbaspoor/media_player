"""
سرچی که چیزی پیدا نمی‌کنه باید دلیلِ واقعی رو بگه (ربات‌نیستی/403/404/...)،
نه فقط «Nothing found» -- بدونِ نشون‌دادنِ متنِ خامِ exception.
"""

import unittest
from unittest import mock

from core import error_reasons, logging_setup

BOT_CHECK = ("ERROR: [youtube] 5j9lg4rKxVQ: Sign in to confirm you're not a bot. "
             "Use --cookies-from-browser or --cookies for the authentication.")


class ClassifyTest(unittest.TestCase):
    def setUp(self):
        error_reasons._last = None

    def test_known_reasons(self):
        cases = {
            BOT_CHECK: "err_bot_check",
            "HTTP Error 403: Forbidden": "err_forbidden",
            "HTTP Error 404: Not Found": "err_not_found",
            "HTTP Error 429: Too Many Requests": "err_rate_limited",
            "ERROR: [youtube] abc: Private video": "err_unavailable",
            "The uploader has not made this video available in your country": "err_geo_blocked",
            "Read timed out": "err_timeout",
            "Unable to connect to proxy": "err_network",
            "Unsupported URL: https://x": "err_unsupported",
        }
        for text, key in cases.items():
            self.assertEqual(error_reasons.classify(Exception(text)), key, text)

    def test_video_id_containing_403_is_not_a_403(self):
        self.assertIsNone(error_reasons.classify(Exception("[youtube] ab403cd: some other thing")))

    def test_own_nothing_found_is_not_mistaken_for_404(self):
        self.assertIsNone(error_reasons.classify(ValueError("Nothing found.")))

    def test_reason_found_through_the_exception_chain(self):
        try:
            try:
                raise RuntimeError(BOT_CHECK)
            except RuntimeError:
                raise ValueError("Nothing found.")
        except ValueError as e:
            self.assertEqual(error_reasons.classify(e), "err_bot_check")

    def test_remembered_failure_explains_a_later_plain_nothing_found(self):
        # resolveِ آیتم‌ها توی تردهای استخر شکست خورده و قورت داده شده؛
        # بعداً فقط یه ValueError("Nothing found.") تازه ساخته می‌شه.
        error_reasons.remember(RuntimeError(BOT_CHECK))
        self.assertEqual(error_reasons.reason_key(ValueError("Nothing found.")), "err_bot_check")
        # بعد از مصرف پاک می‌شه -- به خطای بعدی نمی‌چسبه.
        self.assertIsNone(error_reasons.reason_key(ValueError("Nothing found.")))


class SafeErrorTextTest(unittest.TestCase):
    def setUp(self):
        error_reasons._last = None

    def test_user_sees_the_reason_not_the_raw_text(self):
        with mock.patch.object(logging_setup, "log_exception"):
            text = logging_setup.safe_error_text(RuntimeError(BOT_CHECK))
        self.assertNotIn("5j9lg4rKxVQ", text)
        self.assertNotIn("--cookies", text)
        from core import i18n
        self.assertEqual(text, i18n.t("err_bot_check"))

    def test_plain_nothing_found_still_passes_through(self):
        with mock.patch.object(logging_setup, "log_exception"):
            self.assertEqual(logging_setup.safe_error_text(ValueError("Nothing found.")), "Nothing found.")


class StaleNowPlayingTest(unittest.TestCase):
    def test_announcement_dropped_if_a_new_search_started_meanwhile(self):
        from core import command_helpers
        bot = mock.Mock()
        bot.queue.index = 0
        bot.queue.length = 1
        bot.queue.expected_total = 1
        bot.queue.epoch = 1
        sent = []
        bot.channel_broadcast = sent.append

        def new_search_happens(_bot):
            bot.queue.epoch = 2   # replace() وسطِ انتظار برای duration
            return 120

        with mock.patch.object(command_helpers, "_wait_for_duration", side_effect=new_search_happens), \
             mock.patch.object(command_helpers, "current_display_title", return_value="Old song"):
            command_helpers.broadcast_now_playing(bot)
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()

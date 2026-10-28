"""
The bot's side of the YouTube-cookie alert: hitting YouTube's bot check writes a
tiny alerts.json in the bot's own directory, at most once per 6 hours, cheaply
and without ever raising.
"""

import json
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from core import bot_alerts
from core import error_reasons

BOT_CHECK = ("ERROR: [youtube] 5j9lg4rKxVQ: Sign in to confirm you're not a bot. "
             "Use --cookies-from-browser or --cookies for the authentication.")
KEY = bot_alerts.YOUTUBE_COOKIE_KEY
HOUR = 3600


class AlertsBase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        bot_alerts._last_written.clear()
        error_reasons._last = None
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(bot_alerts._last_written.clear)

    def stored(self):
        with open(os.path.join(self.tmp, "alerts.json"), encoding="utf-8") as f:
            return json.load(f)


class NoteTest(AlertsBase):

    def test_writes_the_timestamp_for_the_server_to_pick_up(self):
        self.assertTrue(bot_alerts.note_youtube_cookie_needed(self.tmp, now=1000))
        self.assertEqual(self.stored(), {KEY: 1000})

    def test_debounced_to_once_per_six_hours(self):
        self.assertTrue(bot_alerts.note_youtube_cookie_needed(self.tmp, now=1000))
        self.assertFalse(bot_alerts.note_youtube_cookie_needed(self.tmp, now=1000 + 6 * HOUR - 1))
        self.assertEqual(self.stored()[KEY], 1000)
        self.assertTrue(bot_alerts.note_youtube_cookie_needed(self.tmp, now=1000 + 6 * HOUR))
        self.assertEqual(self.stored()[KEY], 1000 + 6 * HOUR)

    def test_a_restart_does_not_reset_the_debounce(self):
        bot_alerts.note_youtube_cookie_needed(self.tmp, now=1000)
        bot_alerts._last_written.clear()  # پروسه‌ی تازه
        self.assertFalse(bot_alerts.note_youtube_cookie_needed(self.tmp, now=1000 + HOUR))
        self.assertEqual(self.stored()[KEY], 1000)

    def test_other_keys_in_the_file_survive(self):
        with open(os.path.join(self.tmp, "alerts.json"), "w", encoding="utf-8") as f:
            json.dump({"something_else": 7}, f)
        bot_alerts.note_youtube_cookie_needed(self.tmp, now=1000)
        self.assertEqual(self.stored(), {"something_else": 7, KEY: 1000})

    def test_never_raises(self):
        with open(os.path.join(self.tmp, "alerts.json"), "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertTrue(bot_alerts.note_youtube_cookie_needed(self.tmp, now=1000))  # خراب = خالی
        self.assertFalse(bot_alerts.note_youtube_cookie_needed(os.path.join(self.tmp, "missing"), now=1))
        bot_alerts._last_written.clear()
        with mock.patch.object(bot_alerts, "write_json_atomic", side_effect=OSError("disk full")):
            self.assertFalse(bot_alerts.note_youtube_cookie_needed(self.tmp, now=10 * HOUR))

    def test_no_bot_dir_means_nothing_to_do(self):
        with mock.patch.object(bot_alerts.bot_context, "bot", SimpleNamespace()):
            self.assertFalse(bot_alerts.note_youtube_cookie_needed(now=1000))


class ErrorReasonsHookTest(AlertsBase):

    def setUp(self):
        super().setUp()
        bot = SimpleNamespace(bot_dir=self.tmp)
        mock.patch.object(bot_alerts.bot_context, "bot", bot).start()
        self.addCleanup(mock.patch.stopall)

    def test_remembering_a_bot_check_writes_the_alert(self):
        error_reasons.remember(Exception(BOT_CHECK))
        self.assertIn(KEY, self.stored())

    def test_classifying_a_bot_check_writes_the_alert(self):
        self.assertEqual(error_reasons.reason_key(Exception(BOT_CHECK)), "err_bot_check")
        self.assertIn(KEY, self.stored())

    def test_other_failures_write_nothing(self):
        error_reasons.remember(Exception("HTTP Error 403: Forbidden"))
        error_reasons.reason_key(Exception("HTTP Error 404: Not Found"))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "alerts.json")))

    def test_repeated_bot_checks_touch_the_disk_once(self):
        with mock.patch.object(bot_alerts, "write_json_atomic",
                               wraps=bot_alerts.write_json_atomic) as write:
            for _ in range(20):
                error_reasons.remember(Exception(BOT_CHECK))
        self.assertEqual(write.call_count, 1)

    def test_a_broken_alert_writer_never_breaks_the_failure_path(self):
        with mock.patch.object(bot_alerts, "note_youtube_cookie_needed",
                               side_effect=RuntimeError("boom")):
            error_reasons.remember(Exception(BOT_CHECK))  # نباید exception بده


if __name__ == "__main__":
    unittest.main()

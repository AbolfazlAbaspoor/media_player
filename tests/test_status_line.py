"""The bot's status line on the TeamTalk server."""

import unittest
from unittest import mock

from core import status_line


class StatusLineTest(unittest.TestCase):

    def setUp(self):
        status_line.invalidate()
        self.t = mock.Mock()

    def test_sends_once_then_skips_identical_text(self):
        self.assertTrue(status_line.apply(self.t, {}, "Playing: A"))
        self.assertFalse(status_line.apply(self.t, {}, "Playing: A"))
        self.assertEqual(self.t.set_status.call_count, 1)

    def test_resends_after_reconnect(self):
        status_line.apply(self.t, {}, "Idle")
        status_line.invalidate()               # what connect_bot() does
        self.assertTrue(status_line.apply(self.t, {}, "Idle"))
        self.assertEqual(self.t.set_status.call_count, 2)

    def test_hiding_clears_the_old_status_once(self):
        status_line.apply(self.t, {}, "Playing: A")
        self.assertTrue(status_line.apply(self.t, {}, "Playing: B", visible=False))
        self.assertEqual(self.t.set_status.call_args[0][1], "")
        self.assertFalse(status_line.apply(self.t, {}, "Playing: C", visible=False))

    def test_failure_does_not_raise_and_is_retried(self):
        self.t.set_status.side_effect = RuntimeError("disconnected")
        self.assertFalse(status_line.apply(self.t, {}, "Idle"))
        self.t.set_status.side_effect = None
        self.assertTrue(status_line.apply(self.t, {}, "Idle"))

    def test_long_titles_are_capped(self):
        status_line.apply(self.t, {}, "x" * 2000)
        self.assertLessEqual(len(self.t.set_status.call_args[0][1]), status_line.MAX_LENGTH)

    def test_gender_and_away_flags(self):
        self.assertEqual(status_line.mode_for({}), 0x1000)
        self.assertEqual(status_line.mode_for({"status": {"gender": "female"}}), 0x100)
        self.assertEqual(status_line.mode_for({"status": {"gender": "male"}}), 0)
        cfg = {"status": {"gender": "male", "away_when_paused": True}}
        self.assertEqual(status_line.mode_for(cfg, paused=True), 1)
        self.assertEqual(status_line.mode_for(cfg, paused=False), 0)

    def test_unknown_gender_falls_back_to_neutral(self):
        self.assertEqual(status_line.mode_for({"status": {"gender": "robot"}}), 0x1000)

    def test_neutral_gender_combines_with_away_when_paused(self):
        # مُد پیش‌فرض/موردعلاقه‌ی صاحب ربات: خنثی (4096) + away موقع پاز.
        # قبلاً فقط ترکیبِ male+away تست شده بود؛ خنثی (که بیت‌های بالاتری
        # داره) هم باید درست OR بشه، نه جایگزینِ بیتِ away.
        cfg = {"status": {"gender": "neutral", "away_when_paused": True}}
        self.assertEqual(status_line.mode_for(cfg, paused=True), 0x1001)
        self.assertEqual(status_line.mode_for(cfg, paused=False), 0x1000)


if __name__ == "__main__":
    unittest.main()

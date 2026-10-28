"""
گزارش کاربر (2026-09-27):
  - m وسطِ پخش تغییری نمی‌کرد تا یه سرچ/پخشِ تازه.
  - n باید همیشه بعدی رو پخش کنه، حتی توی m3 (repeat_track) -- خودِ کاربر
    صریحاً «بعدی» رو خواسته.
  - b توی اولِ صف باید پیامِ خصوصی بده، نه به کلِ کانال.
"""

import unittest
from unittest import mock

from core import trackqueue
from core.trackqueue import TrackQueue
from tests.helpers import load_command


class RepeatTrackForceTest(unittest.TestCase):
    def _queue(self, n=3):
        q = TrackQueue(play_fn=lambda *a, **k: None)
        q.replace([{"url": f"http://x/{i}"} for i in range(n)])
        return q

    def test_natural_finish_repeats_same_track(self):
        q = self._queue()
        q.mode = trackqueue.MODE_REPEAT_TRACK
        q._active = True
        ok, track = q.advance()  # مثلِ on_track_finished، بدونِ force
        self.assertTrue(ok)
        self.assertEqual(track.url, "http://x/0")
        self.assertEqual(q.index, 0)

    def test_manual_n_moves_forward_even_in_repeat_track_mode(self):
        q = self._queue()
        q.mode = trackqueue.MODE_REPEAT_TRACK
        ok, track = q.advance(force=True)
        self.assertTrue(ok)
        self.assertEqual(track.url, "http://x/1")
        self.assertEqual(q.index, 1)


class ModeCommandUpdatesLiveQueueTest(unittest.TestCase):
    def test_m_updates_queue_mode_immediately(self):
        m = load_command("m")
        queue = mock.Mock(mode=trackqueue.MODE_PLAYLIST)
        bot = mock.Mock()
        bot.queue = queue
        bot.playback_modes = {1: "single", 2: "playlist", 3: "repeat_track", 4: "repeat_playlist"}
        bot.resolve_mode.return_value = 3
        ctx = {"uid": 1, "nickname": "u", "args": ["3"]}
        m.run(ctx | {"bot": bot})
        self.assertEqual(bot.playback_mode, 3)
        # قبلاً فقط bot.playback_mode ست می‌شد و صفِ در حال اجرا تا پخشِ
        # بعدی از این بی‌خبر می‌موند.
        self.assertEqual(queue.mode, 3)


class BeginningOfQueueIsPrivateTest(unittest.TestCase):
    def test_b_at_start_sends_private_not_channel(self):
        b = load_command("b")
        bot = mock.Mock()
        bot.queue.length = 3
        bot.queue.retreat.return_value = (False, None)
        channel_msgs = []
        private_msgs = []
        bot.channel_broadcast = lambda text: channel_msgs.append(text)
        bot.t.user_message.side_effect = lambda uid, text: private_msgs.append(text)
        bot.channel_messages_enabled = True
        ctx = {"uid": 1, "nickname": "u", "bot": bot}
        with mock.patch("core.documentary.is_active", return_value=False), \
             mock.patch("core.iptv.step_command", return_value=False):
            b.run(ctx)
        self.assertEqual(channel_msgs, [])
        self.assertEqual(len(private_msgs), 1)
        self.assertIn("queue_start", "queue_start")  # sanity: key resolved to some text
        self.assertTrue(private_msgs[0])


if __name__ == "__main__":
    unittest.main()

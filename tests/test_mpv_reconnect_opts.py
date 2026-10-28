import unittest

from core.mpv.player import Player


class ReconnectOptsTest(unittest.TestCase):
    def test_no_eof_based_reconnect(self):
        # reconnect_at_eof / reconnect_streamed لایو HLS رو از کار می‌ندازن.
        opts = Player.DEFAULT_RECONNECT_OPTS.split(",")
        for bad in ("reconnect=1", "reconnect_at_eof=1", "reconnect_streamed=1"):
            self.assertNotIn(bad, opts)
        self.assertIn("reconnect_on_network_error=1", opts)


if __name__ == "__main__":
    unittest.main()

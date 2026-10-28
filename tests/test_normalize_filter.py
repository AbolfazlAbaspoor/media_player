import unittest

from core.mpv.player import Player


class NormalizeFilterTest(unittest.TestCase):
    def test_uses_lavfi_loudnorm(self):
        # فیلتر خام ffmpeg توی mpv اعمال نمی‌شد؛ باید lavfi باشه.
        self.assertTrue(Player.NORMALIZE_FILTER.startswith("lavfi=["))
        self.assertIn("loudnorm", Player.NORMALIZE_FILTER)

    def test_set_normalize_toggles_af(self):
        class Raw:
            af = None
        p = Player.__new__(Player)
        p.raw = Raw()
        p.set_normalize(True)
        self.assertEqual(p.raw.af, Player.NORMALIZE_FILTER)
        p.set_normalize(False)
        self.assertEqual(p.raw.af, "")


if __name__ == "__main__":
    unittest.main()

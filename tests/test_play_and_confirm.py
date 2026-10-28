"""
bot.py::_play_and_confirm باید یه استثنا بندازه اگه mpv واقعاً پخش رو
تأیید نکنه -- تا trackqueue._play_index بگیردش و بره سراغِ آیتمِ بعدیِ صف
به‌جای این‌که یه "Now playing" جعلی برای آهنگی که هیچ‌وقت پخش نشد بفرسته
(باگی که کاربر گزارش داد: دو پیامِ Now playing پشتِ‌سرهم برای دو آیتمِ
متوالی، و پرشِ خودکارِ غیرمنتظره وقتی چیزی قابل‌پخش نیست).
"""

import unittest
from unittest import mock

import bot


class PlayAndConfirmTest(unittest.TestCase):
    def test_raises_when_playback_not_confirmed(self):
        with mock.patch.object(bot, "player") as fake_player, \
             mock.patch.object(bot.command_helpers, "_confirm_playback", return_value=False):
            with self.assertRaises(RuntimeError):
                bot._play_and_confirm("http://bad/url")
        fake_player.play.assert_called_once_with("http://bad/url")

    def test_does_not_raise_when_confirmed(self):
        with mock.patch.object(bot, "player") as fake_player, \
             mock.patch.object(bot.command_helpers, "_confirm_playback", return_value=True):
            bot._play_and_confirm("http://good/url")
        fake_player.play.assert_called_once_with("http://good/url")


if __name__ == "__main__":
    unittest.main()

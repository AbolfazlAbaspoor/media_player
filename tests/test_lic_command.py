"""
دستور lic/license: قبلاً توی حالت «نصب بدون محدودیت» ورودیِ نادرستی به
send_long_text می‌داد (uid به‌جای یه تابع)، پس هیچ پیامی فرستاده نمی‌شد --
خطا بی‌صدا قورت داده می‌شد. این تست همون مسیر رو دوباره چک می‌کنه.
"""

import os
import unittest
from unittest import mock
from tests.helpers import load_command

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeState:
    unlicensed = True
    managed = False
    key = None

    def status_text(self):
        return "بدون لایسنس"

    def in_grace(self):
        return False


class LicCommandTest(unittest.TestCase):

    def _ctx(self, bot):
        return {"bot": bot, "uid": 7}

    def test_unrestricted_install_actually_sends_a_message(self):
        bot = mock.Mock()
        bot.license = FakeState()
        bot.t.user_message = mock.Mock()
        # send_long_text باید همیشه با یه تابعِ قابل‌صدازدن به‌عنوان آرگومان
        # اول صدا زده بشه، نه مستقیم uid (باگی که این تست جلوش رو می‌گیره).
        bot.send_long_text = mock.Mock(side_effect=lambda send_fn, text: send_fn(text))

        load_command("lic").run(self._ctx(bot))

        bot.send_long_text.assert_called_once()
        first_arg = bot.send_long_text.call_args.args[0]
        self.assertTrue(callable(first_arg), "send_long_text must get a callable, not uid")
        bot.t.user_message.assert_called_once()
        self.assertEqual(bot.t.user_message.call_args.args[0], 7)
        self.assertIn("بدون لایسنس", bot.t.user_message.call_args.args[1])


if __name__ == "__main__":
    unittest.main()

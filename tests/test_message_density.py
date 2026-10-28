"""
پیام‌های کمتر برای یه اتفاق: ck قبلاً دو تا user_message جدا می‌فرستاد
(وضعیت، بعد نکته‌ی ری‌استارت) -- الان باید یکی باشه با هر دو تکه‌ی اطلاعات.
"""

import os
import unittest
from unittest import mock

from core import i18n
from tests.helpers import load_command

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CkOneMessageTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        i18n.load_languages()
        i18n.set_language("en")

    def test_toggling_cookies_sends_exactly_one_message(self):
        bot = mock.Mock()
        bot.cfg = {}
        bot.commands = {"ck": {"usage": "ck [true|false]"}}
        ctx = {"bot": bot, "uid": 1, "nickname": "Ali", "args": []}

        load_command("ck").run(ctx)

        # تغییر تنظیمات ربات خبر کانالیه (مثل ns/h/ic)، نه پیام خصوصی
        bot.t.user_message.assert_not_called()
        bot.channel_broadcast.assert_called_once()
        text = bot.channel_broadcast.call_args.args[0]
        self.assertIn("Ali", text)
        self.assertIn("rs services", text)


if __name__ == "__main__":
    unittest.main()

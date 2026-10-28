"""
دستورهای اینستاگرام (cr/dlr/fr/lr/rl/rr/ufr/ig) قبلاً وقتی instagram_api
یه استثنای خام می‌داد، متنِ کامل exception رو (تا ۵۰ کاراکتر بریده‌شده،
ولی همچنان خام) مستقیم به کاربر توی تیم‌تاک نشون می‌دادن -- که می‌تونست
جزئیات داخلیِ کتابخونه یا مسیر فایل رو لو بده. این تست‌ها تأیید می‌کنن
حالا از core.logging_setup.safe_error_text رد می‌شن.
"""

import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import i18n
from core import instagram_api
from core import instagram_user
from core import logging_setup
from tests.helpers import load_command

# بدون این، i18n.t() هیچ فایل زبانی نداره و فقط خودِ کلید رو برمی‌گردونه
# (مثلاً "command_error")، که هیچ‌وقت شامل متن exception نمی‌شه -- یعنی
# تست‌های زیر بدون این خط، مستقل از باگ واقعی، همیشه سبز می‌شدن.
i18n.load_languages()


class FakeBot:
    def __init__(self):
        self.sent = []
        self.t = mock.Mock()
        self.t.user_message.side_effect = lambda uid, text: self.sent.append(text)
        self.cfg = {"_ig_sessions": {"s1": {"tt_username": "alice", "ig_username": "alice_ig"}}}
        self._ig_reels = {"alice": [mock.Mock(pk="reel123")]}
        self._ig_current_index = {"alice": 0}
        self._instagram_sessions_init = True


_RAW_EXCEPTION_TEXT = ("/very/internal/system/path/that/should/never/leak.py failed "
                        "with a raw library-internal message")
# فقط ابتدای متن -- دقیقاً همون بخشی که با str(e)[:50] قدیمی هم رد می‌شد؛
# اگه assertNotIn روی کل _RAW_EXCEPTION_TEXT بود، یه بریدنِ ۵۰ کاراکتری
# قدیمی هم قبول می‌شد (چون رشته‌ی کامل دیگه توش نبود) و باگ رو نمی‌گرفت.
_LEAK_MARKER = _RAW_EXCEPTION_TEXT[:40]


class InstagramCommandsHideRawErrorsTest(unittest.TestCase):

    def _run_with_raising_api(self, command_name, api_function_name):
        module = load_command(command_name)
        bot = FakeBot()
        ctx = {"bot": bot, "uid": 1, "username": "alice", "nickname": "Alice"}

        with mock.patch.object(instagram_user, "load_saved_session",
                                return_value=({"dummy": True}, "cookie")), \
             mock.patch.object(instagram_api, "load_client_from_session",
                                return_value=mock.Mock()), \
             mock.patch.object(instagram_api, api_function_name,
                                side_effect=RuntimeError(_RAW_EXCEPTION_TEXT)):
            module.run(ctx)

        self.assertTrue(bot.sent, f"{command_name}: no message was sent to the user")
        combined = "\n".join(bot.sent)
        self.assertNotIn(_LEAK_MARKER, combined,
                          f"{command_name} leaked the raw exception text to the user")

    def test_cr_hides_raw_error(self):
        module = load_command("cr")
        bot = FakeBot()
        ctx = {"bot": bot, "uid": 1, "username": "alice", "nickname": "Alice", "args": ["nice", "post"]}
        with mock.patch.object(instagram_user, "load_saved_session",
                                return_value=({"dummy": True}, "cookie")), \
             mock.patch.object(instagram_api, "load_client_from_session",
                                return_value=mock.Mock()), \
             mock.patch.object(instagram_api, "comment_reel",
                                side_effect=RuntimeError(_RAW_EXCEPTION_TEXT)):
            module.run(ctx)
        combined = "\n".join(bot.sent)
        self.assertNotIn(_LEAK_MARKER, combined)

    def test_dlr_hides_raw_error(self):
        self._run_with_raising_api("dlr", "unlike_reel")

    def test_fr_hides_raw_error(self):
        module = load_command("fr")
        bot = FakeBot()
        bot._ig_reels = {"alice": [mock.Mock(user=mock.Mock(pk="user123"))]}
        ctx = {"bot": bot, "uid": 1, "username": "alice", "nickname": "Alice"}
        with mock.patch.object(instagram_user, "load_saved_session",
                                return_value=({"dummy": True}, "cookie")), \
             mock.patch.object(instagram_api, "load_client_from_session",
                                return_value=mock.Mock()), \
             mock.patch.object(instagram_api, "follow_user",
                                side_effect=RuntimeError(_RAW_EXCEPTION_TEXT)):
            module.run(ctx)
        combined = "\n".join(bot.sent)
        self.assertNotIn(_LEAK_MARKER, combined)

    def test_lr_hides_raw_error(self):
        self._run_with_raising_api("lr", "like_reel")

    def test_rr_hides_raw_error(self):
        self._run_with_raising_api("rr", "fetch_feed_reels")

    def test_ufr_hides_raw_error(self):
        module = load_command("ufr")
        bot = FakeBot()
        bot._ig_reels = {"alice": [mock.Mock(user=mock.Mock(pk="user123"))]}
        ctx = {"bot": bot, "uid": 1, "username": "alice", "nickname": "Alice"}
        with mock.patch.object(instagram_user, "load_saved_session",
                                return_value=({"dummy": True}, "cookie")), \
             mock.patch.object(instagram_api, "load_client_from_session",
                                return_value=mock.Mock()), \
             mock.patch.object(instagram_api, "unfollow_user",
                                side_effect=RuntimeError(_RAW_EXCEPTION_TEXT)):
            module.run(ctx)
        combined = "\n".join(bot.sent)
        self.assertNotIn(_LEAK_MARKER, combined)

    def test_rl_hides_raw_error(self):
        module = load_command("rl")
        bot = FakeBot()
        ctx = {"bot": bot, "uid": 1, "username": "alice", "nickname": "Alice"}
        with mock.patch.object(instagram_user, "load_saved_session",
                                return_value=({"dummy": True}, "cookie")), \
             mock.patch.object(instagram_api, "load_client_from_session",
                                return_value=mock.Mock()), \
             mock.patch.object(instagram_api, "fetch_feed_reels",
                                side_effect=RuntimeError(_RAW_EXCEPTION_TEXT)):
            module.run(ctx)
        combined = "\n".join(bot.sent)
        self.assertNotIn(_LEAK_MARKER, combined)

    def test_ig_hides_raw_error(self):
        module = load_command("ig")
        bot = FakeBot()
        ctx = {"bot": bot, "uid": 1, "username": "alice", "args": []}
        with mock.patch.object(instagram_user, "set_bot_dir",
                                side_effect=RuntimeError(_RAW_EXCEPTION_TEXT)):
            module.run(ctx)
        combined = "\n".join(bot.sent)
        self.assertNotIn(_LEAK_MARKER, combined)


class SafeErrorTextSanityTest(unittest.TestCase):
    """پایه‌ی همه‌ی فیکس‌های بالا: safe_error_text واقعاً استثنای خام رو مخفی می‌کنه."""

    def test_generic_exception_is_replaced_with_generic_text(self):
        text = logging_setup.safe_error_text(RuntimeError(_RAW_EXCEPTION_TEXT))
        self.assertNotIn(_LEAK_MARKER, text)

    def test_clean_value_error_passes_through(self):
        text = logging_setup.safe_error_text(ValueError("Nothing found."))
        self.assertEqual(text, "Nothing found.")


if __name__ == "__main__":
    unittest.main()

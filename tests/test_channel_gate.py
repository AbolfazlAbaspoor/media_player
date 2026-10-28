"""The Telegram side of mandatory channel membership."""

import asyncio
import unittest
from unittest import mock

from telegram.error import TelegramError
from telegram.ext import ApplicationHandlerStop

from licensing.telegram import channel_gate as cg


def run(coro):
    return asyncio.run(coro)


class FakeApp:
    def __init__(self, member_status="member", error=None):
        self.bot_data = {"db": mock.Mock(), "supervisor": None}
        self.bot = mock.Mock()
        self.bot.id = 999

        async def get_chat_member(channel, user_id):
            if error:
                raise TelegramError(error)
            return mock.Mock(status=member_status, is_member=True)

        async def send_message(*a, **k):
            return None

        self.bot.get_chat_member = get_chat_member
        self.bot.send_message = mock.AsyncMock()


def private_update(user_id=100, callback=None):
    update = mock.Mock()
    update.chat_member = None
    update.effective_user = mock.Mock(id=user_id, language_code="fa")
    update.effective_chat = mock.Mock(type="private")
    update.effective_message = mock.Mock()
    update.effective_message.reply_text = mock.AsyncMock()
    if callback is None:
        update.callback_query = None
    else:
        update.callback_query = mock.Mock(data=callback)
    return update


class GateTest(unittest.TestCase):

    def setUp(self):
        self.patches = [
            mock.patch("licensing.membership.required_channel", return_value="@official"),
            mock.patch("licensing.membership.is_out", return_value=False),
            mock.patch("licensing.membership.mark_left", return_value=True),
            mock.patch("licensing.membership.grace_seconds", return_value=86400),
            mock.patch("licensing.config.is_admin", return_value=False),
            mock.patch("licensing.config.admin_ids", return_value=[1]),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        mock.patch.stopall()

    def _gate(self, app, update):
        context = mock.Mock(application=app)
        run(cg.gate(update, context))

    def test_member_passes(self):
        self._gate(FakeApp("member"), private_update())

    def test_non_member_is_stopped_with_a_join_prompt(self):
        update = private_update()
        with self.assertRaises(ApplicationHandlerStop):
            self._gate(FakeApp("left"), update)
        update.effective_message.reply_text.assert_awaited()

    def test_unknown_membership_never_blocks(self):
        # bot not admin / network down: do not punish anyone
        self._gate(FakeApp(error="Bad Request: member list is inaccessible"), private_update())

    def test_admins_are_never_gated(self):
        with mock.patch("licensing.config.is_admin", return_value=True):
            self._gate(FakeApp("left"), private_update())

    def test_the_i_joined_button_reaches_its_handler(self):
        self._gate(FakeApp("left"), private_update(callback=cg.CALLBACK_CHECK))

    def test_feature_off_gates_nothing(self):
        with mock.patch("licensing.membership.required_channel", return_value=""):
            self._gate(FakeApp("left"), private_update())

    def test_group_chats_are_not_gated(self):
        update = private_update()
        update.effective_chat = mock.Mock(type="supergroup")
        self._gate(FakeApp("left"), update)


class HourlyCheckTest(unittest.TestCase):

    def tearDown(self):
        mock.patch.stopall()

    def test_broken_check_pauses_nobody(self):
        mock.patch("licensing.membership.required_channel", return_value="@official").start()
        mock.patch("licensing.membership.users_to_check", return_value=[100, 101]).start()
        pause = mock.patch("licensing.membership.pause_user").start()
        mock.patch("licensing.membership.users_to_pause", return_value=[100]).start()
        mock.patch("licensing.config.is_admin", return_value=False).start()
        mock.patch("licensing.config.admin_ids", return_value=[]).start()
        paused = run(cg.check_all(FakeApp(error="Forbidden")))
        self.assertEqual(paused, 0)
        pause.assert_not_called()

    def test_member_left_past_grace_is_paused_and_told(self):
        mock.patch("licensing.membership.required_channel", return_value="@official").start()
        mock.patch("licensing.membership.users_to_check", return_value=[100]).start()
        mock.patch("licensing.membership.mark_left", return_value=False).start()
        mock.patch("licensing.membership.users_to_pause", return_value=[100]).start()
        mock.patch("licensing.membership.pause_user", return_value=[{"id": 7}]).start()
        mock.patch("licensing.config.is_admin", return_value=False).start()
        app = FakeApp("left")
        self.assertEqual(run(cg.check_all(app)), 1)
        app.bot.send_message.assert_awaited()


class AdminCommandTest(unittest.TestCase):

    def test_refuses_a_channel_where_the_bot_is_not_admin(self):
        app = FakeApp("member")
        update = private_update(user_id=1)
        context = mock.Mock(application=app, args=["@official"])
        with mock.patch("licensing.config.is_admin", return_value=True):
            run(cg.cmd_channel(update, context))
        app.bot_data["db"].set_setting.assert_not_called()


class RegistrationTest(unittest.TestCase):

    def test_sales_bot_builds_with_the_gate_first(self):
        from licensing import config
        from licensing.telegram import sales_bot
        real_get = config.get

        def fake_get(key, *args, **kwargs):
            # A fresh checkout has no data/licensing/config.json, and the build
            # must not depend on the real token or rewrite the real catalog.
            if key == "sales_bot_token":
                return "123456:TEST"
            return real_get(key, *args, **kwargs)

        with mock.patch("licensing.config.get", side_effect=fake_get),                 mock.patch("licensing.sync.autoregister", return_value=[]):
            app = sales_bot.build_application(mock.Mock(), None, None)
        self.assertIn(-1, app.handlers)
        group0 = app.handlers[0]
        names = [getattr(h.callback, "__name__", "") for h in group0]
        self.assertLess(names.index("on_check"), names.index("on_callback"))


if __name__ == "__main__":
    unittest.main()

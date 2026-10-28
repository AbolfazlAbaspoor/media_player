"""
Server side of the YouTube-cookie alert: the periodic scan of supervised bots'
directories, notifying the licence owner (with the Cookies button) and every
admin exactly once, then marking the alert handled. Offline: temp DB and bot
directories, mocked Telegram.
"""

import asyncio
import os
import shutil
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from telegram.error import TelegramError

from core import bot_alerts
from licensing import cookie_alerts
from licensing import db as db_module
from licensing import i18n
from licensing import licenses
from licensing import provisioning
from licensing.telegram.sales import alerts, background

DAY = 86400
OWNER = 5
ADMINS = [1, 2]


def run(coro):
    return asyncio.run(coro)


class CookieAlertBase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = db_module.Database(os.path.join(self.tmp, "t.sqlite3"))
        mock.patch.object(provisioning, "DATA_DIR", os.path.join(self.tmp, "data")).start()
        mock.patch("licensing.config.admin_ids", return_value=list(ADMINS)).start()
        i18n.set_language("en")
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(self.db.close)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(i18n.set_language, None)
        bot_alerts._last_written.clear()
        self.addCleanup(bot_alerts._last_written.clear)

        self.license = self.make_license(OWNER)
        self.instance = self.make_instance(self.license, "bot-a")
        self.supervisor = SimpleNamespace(status=lambda: [{"slug": "bot-a", "alive": True}])
        self.application = mock.Mock()
        self.application.bot.send_message = mock.AsyncMock()
        self.application.bot_data = {"db": self.db, "supervisor": self.supervisor}

    def make_license(self, user_id, status="active"):
        now = int(time.time())
        return self.db.create_license(
            key=licenses.unique_key(self.db), user_id=user_id, order_id=None, max_bots=2,
            max_users=1, features=[], starts_at=now, expires_at=now + 30 * DAY, status=status)

    def make_instance(self, license_row, slug):
        instance = self.db.create_instance(license_row["id"], slug, "h", 1, "nick", "user", "pw")
        return self.db.update_instance(instance["id"], status="running")

    def raise_alert(self, instance=None, ago=10):
        """کاری که خودِ ربات می‌کنه (core/bot_alerts.py)، با زمانِ دلخواه."""
        bot_dir = provisioning.instance_dirs(instance or self.instance)[1]
        os.makedirs(bot_dir, exist_ok=True)
        bot_alerts._last_written.clear()
        if os.path.exists(bot_alerts.alerts_path(bot_dir)):
            os.remove(bot_alerts.alerts_path(bot_dir))     # مشکلِ تازه، نه debounce
        self.assertTrue(bot_alerts.note(bot_alerts.YOUTUBE_COOKIE_KEY, bot_dir=bot_dir,
                                        now=time.time() - ago))

    def scan(self):
        return run(alerts.notify_cookie_alerts(self.application))

    def sent(self):
        """{chat_id: (text, reply_markup)}"""
        return {call.args[0]: (call.args[1], call.kwargs.get("reply_markup"))
                for call in self.application.bot.send_message.call_args_list}

    def buttons(self, markup):
        return [button.callback_data for row in markup.inline_keyboard for button in row]


class NotifyTest(CookieAlertBase):

    def test_owner_and_every_admin_are_told_once(self):
        self.raise_alert()
        self.assertEqual(self.scan(), 1)
        sent = self.sent()
        self.assertEqual(set(sent), {OWNER, *ADMINS})
        for chat_id, (text, markup) in sent.items():
            self.assertIn("bot-a", text, chat_id)
            self.assertEqual(self.buttons(markup), [f"ck:menu:{self.instance['id']}"], chat_id)
        self.assertIn("Cookies", sent[OWNER][0])
        self.assertIn(self.license["key"], sent[1][0])
        self.assertNotIn(self.license["key"], sent[OWNER][0])

    def test_handled_alerts_are_not_repeated(self):
        self.raise_alert()
        self.scan()
        self.application.bot.send_message.reset_mock()
        self.assertEqual(self.scan(), 0)
        self.application.bot.send_message.assert_not_called()

    def test_recipients_are_addressed_in_their_own_language(self):
        self.db.upsert_user(OWNER, "o", "Owner")
        self.db.set_user_lang(OWNER, "fa")
        self.db.upsert_user(1, "a", "A")
        self.db.set_user_lang(1, "en")
        self.raise_alert()
        self.scan()
        sent = self.sent()
        self.assertIn("کوکی", sent[OWNER][0])
        self.assertNotIn("Cookies", sent[1][0])
        self.assertNotIn("کوکی", sent[1][0])

    def test_an_owner_who_is_an_admin_gets_a_single_message(self):
        with mock.patch("licensing.config.admin_ids", return_value=[OWNER, 2]):
            self.raise_alert()
            self.scan()
        self.assertEqual(self.application.bot.send_message.await_count, 2)
        sent = self.sent()
        self.assertEqual(set(sent), {OWNER, 2})
        self.assertIn(self.license["key"], sent[OWNER][0])          # متنِ ادمین
        self.assertEqual(self.buttons(sent[OWNER][1]), [f"ck:menu:{self.instance['id']}"])

    def test_no_alert_file_no_messages(self):
        self.assertEqual(self.scan(), 0)
        self.application.bot.send_message.assert_not_called()

    def test_only_supervised_running_licences_are_scanned(self):
        suspended = self.make_license(7, status="suspended")
        other = self.make_instance(suspended, "bot-b")
        self.raise_alert(other)
        self.assertEqual(self.scan(), 0)
        self.application.bot.send_message.assert_not_called()

    def test_each_bot_is_reported_separately(self):
        second = self.make_instance(self.make_license(8), "bot-c")
        self.raise_alert()
        self.raise_alert(second)
        self.assertEqual(self.scan(), 2)
        owners = {call.args[0] for call in self.application.bot.send_message.call_args_list}
        self.assertEqual(owners, {OWNER, 8, *ADMINS})


class CostAndRetryTest(CookieAlertBase):

    def test_nothing_is_read_when_no_bot_is_supervised(self):
        self.raise_alert()
        for supervisor in (None, SimpleNamespace(status=lambda: [])):
            self.application.bot_data["supervisor"] = supervisor
            with mock.patch.object(bot_alerts, "read") as read:
                self.assertEqual(self.scan(), 0)
            read.assert_not_called()
        self.application.bot.send_message.assert_not_called()

    def test_a_new_alert_inside_the_renotify_window_is_absorbed_silently(self):
        self.raise_alert(ago=3 * 3600)
        self.scan()
        self.application.bot.send_message.reset_mock()
        self.raise_alert(ago=5)              # مشکل ادامه داره، ۶ ساعت بعد دوباره نوشته
        self.assertEqual(self.scan(), 0)
        self.application.bot.send_message.assert_not_called()
        self.assertEqual(self.scan(), 0)     # و دیده‌شده ثبت شده، نه در صفِ تلاش

    def test_a_new_alert_after_a_day_notifies_again(self):
        self.raise_alert(ago=3 * 3600)
        self.scan()
        self.application.bot.send_message.reset_mock()
        state = cookie_alerts._state(self.db, self.instance["id"])
        cookie_alerts._save_state(self.db, self.instance["id"],
                                  notified=int(state["notified"]) - 2 * DAY)
        self.raise_alert(ago=5)
        self.assertEqual(self.scan(), 1)
        self.assertEqual(self.application.bot.send_message.await_count, 1 + len(ADMINS))

    def test_undelivered_alerts_are_retried_until_delivered(self):
        self.raise_alert()
        self.application.bot.send_message.side_effect = TelegramError("proxy down")
        self.assertEqual(self.scan(), 1)
        self.application.bot.send_message.side_effect = None
        self.application.bot.send_message.reset_mock()
        self.assertEqual(self.scan(), 1)                      # دوباره تلاش شد
        self.assertEqual(self.application.bot.send_message.await_count, 1 + len(ADMINS))
        self.application.bot.send_message.reset_mock()
        self.assertEqual(self.scan(), 0)                      # حالا رسیدگی‌شده

    def test_an_alert_nobody_can_receive_is_dropped_after_a_day(self):
        self.raise_alert(ago=2 * DAY)
        self.application.bot.send_message.side_effect = TelegramError("blocked")
        self.assertEqual(self.scan(), 1)
        self.application.bot.send_message.side_effect = None
        self.application.bot.send_message.reset_mock()
        self.assertEqual(self.scan(), 0)
        self.application.bot.send_message.assert_not_called()


class LoopTest(CookieAlertBase):

    def run_loop(self, scan):
        waited = []

        async def fake_sleep(seconds):
            waited.append(seconds)
            if len(waited) > 2:
                raise asyncio.CancelledError
        with mock.patch.object(background.asyncio, "sleep", fake_sleep), \
                mock.patch.object(background, "notify_cookie_alerts", scan), \
                mock.patch.object(background.logging_setup, "log_exception"):
            run(background._cookie_alert_loop(self.application))
        return waited

    def test_scans_every_ten_minutes(self):
        scan = mock.AsyncMock()
        waited = self.run_loop(scan)
        self.assertEqual(waited[:2], [600, 600])
        self.assertEqual(scan.await_count, 2)

    def test_a_failing_scan_does_not_kill_the_loop(self):
        scan = mock.AsyncMock(side_effect=RuntimeError("boom"))
        self.run_loop(scan)
        self.assertEqual(scan.await_count, 2)


if __name__ == "__main__":
    unittest.main()

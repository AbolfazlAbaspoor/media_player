"""
Daily admin report over Telegram: what goes into it (bots, errors, expiring
licences, pending orders, crypto), that raw exception text never does, who gets
it in which language, when it is scheduled, and the admin panel's "Report now"
button. Everything is offline (temp DB, temp errors.log, mocked Telegram).
"""

import asyncio
import os
import shutil
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from licensing import config
from licensing import daily_report
from licensing import db as db_module
from licensing import expiry
from licensing import i18n
from licensing import licenses
from licensing.telegram import keyboards as kb
from licensing.telegram import texts as T
from licensing.telegram.sales import background, callbacks, reports

DAY = 86400
SECRET = "SUPERSECRET-exception-text"


def run(coro):
    return asyncio.run(coro)


def log_line(ago_seconds, context, level="ERROR", logger="bot", now=None):
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime((now or time.time()) - ago_seconds))
    return f"[{logger}] (while: {context}) {stamp},123 [{level}] Unhandled exception\n"


def supervisor(*items):
    return SimpleNamespace(status=lambda: [
        dict({"slug": "x", "alive": False, "blocked": False, "failures": 0,
              "last_exit_code": None}, **item) for item in items])


class ReportBase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = db_module.Database(os.path.join(self.tmp, "t.sqlite3"))
        self.errors_log = os.path.join(self.tmp, "errors.log")
        self.crypto = {"enabled": False}
        mock.patch("licensing.config.crypto_settings", side_effect=lambda: dict(self.crypto)).start()
        mock.patch("licensing.config.admin_ids", return_value=[1, 2]).start()
        mock.patch("licensing.config.is_admin", side_effect=lambda uid: uid in (1, 2)).start()
        mock.patch("licensing.daily_report.logging_setup.ERRORS_FILE", self.errors_log).start()
        i18n.set_language("en")
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(self.db.close)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(i18n.set_language, None)

    def write_log(self, *lines):
        with open(self.errors_log, "w", encoding="utf-8") as f:
            f.writelines(lines)

    def make_license(self, user_id, expires_in, key=None):
        now = int(time.time())
        return self.db.create_license(
            key=key or licenses.unique_key(self.db), user_id=user_id, order_id=None, max_bots=1,
            max_users=1, features=[], starts_at=now, expires_at=now + expires_in, status="active")

    def make_instance(self, license_row, slug, status="running"):
        instance = self.db.create_instance(license_row["id"], slug, "h", 1, "nick", "user", "pw")
        return self.db.update_instance(instance["id"], status=status)


class ErrorsSummaryTest(ReportBase):

    def test_counts_only_the_last_24_hours_and_groups_contexts(self):
        self.write_log(
            log_line(3 * 3600, "searching 'foo' on youtube (requested by bob)"),
            f"Traceback (most recent call last):\n  ValueError: {SECRET}\n",
            log_line(2 * 3600, "searching 'bar baz' on youtube (requested by alice)"),
            log_line(1 * 3600, "searching 'q' on youtube (requested by carol)"),
            log_line(600, "idle"),
            log_line(2 * DAY, "idle"),          # بیرونِ پنجره
            "#e1:AAAAENCRYPTEDLINE\n",          # رمزشده: خونده نمی‌شه
        )
        total, top = daily_report.errors_summary()
        self.assertEqual(total, 4)
        self.assertEqual(top[0], ("searching '…' on youtube", 3))
        self.assertEqual(top[1], ("idle", 1))

    def test_no_user_data_or_exception_text_in_the_contexts(self):
        self.write_log(
            log_line(60, "resolving link 'https://user-private.example/x?t=1' (requested by bob)"),
            f"ValueError: {SECRET}\n")
        _total, top = daily_report.errors_summary()
        shown = " ".join(context for context, _count in top)
        for leaked in ("user-private", "bob", SECRET):
            self.assertNotIn(leaked, shown)

    def test_top_is_limited_and_a_missing_log_is_zero(self):
        self.write_log(*[log_line(60, f"task {chr(97 + i)}") for i in range(10)])
        self.assertEqual(len(daily_report.errors_summary()[1]), daily_report.TOP_ERRORS)
        os.remove(self.errors_log)
        self.assertEqual(daily_report.errors_summary(), (0, []))

    def test_the_rotated_log_counts_too(self):
        with open(self.errors_log + ".1", "w", encoding="utf-8") as f:
            f.write(log_line(3600, "old file"))
        self.write_log(log_line(60, "new file"))
        self.assertEqual(daily_report.errors_summary()[0], 2)


class CollectTest(ReportBase):

    def test_bots_running_crashed_and_blocked(self):
        lic = self.make_license(5, 10 * DAY)
        self.make_instance(lic, "a")
        self.make_instance(lic, "b")
        self.make_instance(lic, "c")
        self.make_instance(lic, "d", status="crashed")   # supervisor اصلاً نمی‌شناسه
        self.make_instance(lic, "e", status="removed")   # حذف‌شده شمرده نمی‌شه
        sup = supervisor({"slug": "a", "alive": True},
                         {"slug": "b", "blocked": True},
                         {"slug": "c", "failures": 2, "last_exit_code": 1})
        self.assertEqual(daily_report.bot_health(self.db, sup),
                         {"running": 1, "crashed": 2, "blocked": 1})

    def test_without_a_supervisor_the_database_answers(self):
        lic = self.make_license(5, 10 * DAY)
        self.make_instance(lic, "a")
        self.make_instance(lic, "b", status="blocked")
        self.assertEqual(daily_report.bot_health(self.db, None),
                         {"running": 1, "crashed": 0, "blocked": 1})

    def test_licences_expiring_within_three_days_are_listed(self):
        self.db.upsert_user(5, "bob", "Bob")
        self.make_license(5, 2 * DAY, key="TT-SOON-0000-0001")
        self.make_license(5, 10 * DAY, key="TT-LATE-0000-0002")
        data = daily_report.collect(self.db, None)
        self.assertEqual(data["expiring"]["count"], 1)
        item = data["expiring"]["items"][0]
        self.assertEqual((item["key"], item["user"]), ("TT-SOON-0000-0001", "@bob"))

    def test_orders_pending_counts_only_those_awaiting_the_admin(self):
        for status in ("admin_review", "check_failed", "awaiting_receipt", "approved"):
            self.db.create_order(user_id=5, months=1, users=1, bots=1, features=[],
                                 amount_usd=5, status=status)
        self.assertEqual(daily_report.collect(self.db, None)["orders_pending"], 2)

    def test_crypto_is_absent_when_disabled_and_counted_when_enabled(self):
        self.assertIsNone(daily_report.collect(self.db, None)["crypto"])
        self.crypto = {"enabled": True}
        now = int(time.time())
        for index, (status, paid_at) in enumerate(
                (("pending", None), ("paid", now - 3600), ("paid", now - 3 * DAY), ("expired", None))):
            order = self.db.create_order(user_id=5, months=1, users=1, bots=1, features=[],
                                         amount_usd=5, status="awaiting_receipt")
            payment = self.db.create_crypto_payment(
                order["id"], 5, "trc20", "T" + "a" * 33, 5_000_000 + index, now + 1800)
            if status != "pending":
                self.db.set_crypto_payment_status(payment["id"], status)
            if paid_at:
                self.db._execute("UPDATE crypto_payments SET paid_at = ? WHERE id = ?",
                                 (paid_at, payment["id"]))
        crypto = daily_report.collect(self.db, None)["crypto"]
        self.assertEqual((crypto["pending"], crypto["received"], crypto["received_micro"]),
                         (1, 1, 5_000_001))


class TextTest(ReportBase):

    def report(self, lang="en", crypto=False):
        i18n.set_language(lang)
        if not self.db.get_license_by_key("TT-SOON-0000-0001"):
            self.db.upsert_user(5, "bob", "Bob")
            self.make_license(5, 1 * DAY, key="TT-SOON-0000-0001")
        self.write_log(log_line(60, "searching 'x' on <b>youtube</b>"),
                       f"ValueError: {SECRET}\n")
        self.crypto = {"enabled": crypto}
        return T.daily_report(daily_report.collect(self.db, supervisor({"slug": "a", "alive": True})))

    def test_every_section_is_there_in_both_languages(self):
        for lang in ("en", "fa"):
            text = self.report(lang, crypto=True)
            for needle in ("TT-SOON-0000-0001", "@bob", "USDT", "searching &#x27;…&#x27; on &lt;b&gt;youtube&lt;/b&gt;"):
                self.assertIn(needle, text, (lang, needle))
            self.assertNotIn("report_", text)        # کلیدِ ترجمه‌نشده
            self.assertNotIn(SECRET, text)
        self.assertIn("Daily report", self.report("en"))
        self.assertIn("گزارش روزانه", self.report("fa"))

    def test_crypto_line_only_when_enabled(self):
        self.assertNotIn("USDT", self.report(crypto=False))

    def test_a_long_expiring_list_says_how_many_more(self):
        for _ in range(daily_report.MAX_EXPIRING_LISTED + 2):
            self.make_license(5, DAY)
        i18n.set_language("en")
        text = T.daily_report(daily_report.collect(self.db, None))
        self.assertIn("and 2 more", text)


class SendingTest(ReportBase):

    def app(self, sup=None):
        application = mock.Mock()
        application.bot.send_message = mock.AsyncMock()
        application.bot_data = {"db": self.db, "supervisor": sup}
        return application

    def test_every_admin_gets_it_in_their_own_language(self):
        self.db.upsert_user(1, "a", "A")
        self.db.set_user_lang(1, "fa")
        self.db.upsert_user(2, "b", "B")
        self.db.set_user_lang(2, "en")
        application = self.app()
        self.assertEqual(run(reports.send_daily_report(application)), 2)
        sent = {call.args[0]: call.args[1] for call in application.bot.send_message.call_args_list}
        self.assertEqual(set(sent), {1, 2})
        self.assertIn("گزارش روزانه", sent[1])
        self.assertIn("Daily report", sent[2])

    def test_an_unreachable_admin_does_not_stop_the_others(self):
        from telegram.error import TelegramError
        application = self.app()
        application.bot.send_message.side_effect = [TelegramError("blocked"), None]
        self.assertEqual(run(reports.send_daily_report(application)), 1)


class ReportNowTest(ReportBase):

    def update(self, user_id):
        update = mock.Mock()
        update.effective_user.id = user_id
        update.callback_query = None
        return update

    def context(self):
        context = mock.Mock()
        context.application.bot_data = {"db": self.db, "supervisor": None}
        return context

    def test_an_admin_gets_the_same_report_on_demand(self):
        self.db.upsert_user(1, "a", "A")
        with mock.patch.object(reports, "_send", new=mock.AsyncMock()) as send:
            run(reports.admin_report_now(self.update(1), self.context()))
        text, markup = send.call_args.args[1], send.call_args.args[2]
        self.assertIn("Daily report", text)
        self.assertIsNotNone(markup)

    def test_anybody_else_is_turned_away_without_collecting(self):
        with mock.patch.object(reports, "_send", new=mock.AsyncMock()) as send, \
                mock.patch.object(daily_report, "collect") as collect:
            run(reports.admin_report_now(self.update(99), self.context()))
        collect.assert_not_called()
        self.assertIn("admin", send.call_args.args[1].lower())

    def test_the_admin_panel_has_the_button_and_the_callback_reaches_it(self):
        i18n.set_language("en")
        buttons = [b for row in kb.admin_panel(0, 0).inline_keyboard for b in row]
        report = [b for b in buttons if b.callback_data == "adm:report"]
        self.assertEqual([b.text for b in report], ["📊 Report now"])

        update = mock.Mock()
        update.callback_query.data = "adm:report"
        update.callback_query.answer = mock.AsyncMock()
        with mock.patch.object(callbacks, "_db", return_value=self.db), \
                mock.patch.object(callbacks, "_user_row", return_value={"blocked": 0}), \
                mock.patch.object(callbacks, "_is_admin", return_value=True), \
                mock.patch.object(callbacks, "admin_report_now", new=mock.AsyncMock()) as handler:
            run(callbacks.on_callback(update, self.context()))
        handler.assert_awaited_once()


class SchedulingTest(ReportBase):

    def cfg(self, **values):
        real = config.get
        return mock.patch("licensing.config.get",
                          side_effect=lambda key, default=None: values.get(key, real(key, default)))

    def test_hour_defaults_to_nine_and_bad_values_fall_back(self):
        with self.cfg(daily_report_hour=None):
            self.assertEqual(daily_report.report_hour(), 9)
        for bad in ("soon", 24, -1):
            with self.cfg(daily_report_hour=bad):
                self.assertEqual(daily_report.report_hour(), 9, bad)
        with self.cfg(daily_report_hour="7"):
            self.assertEqual(daily_report.report_hour(), 7)
        with self.cfg(daily_report_hour=0):
            self.assertEqual(daily_report.report_hour(), 0)

    def test_the_enable_flag(self):
        with self.cfg(daily_report_enabled=False):
            self.assertFalse(daily_report.enabled())
        with self.cfg(daily_report_enabled="off"):
            self.assertFalse(daily_report.enabled())
        with self.cfg(daily_report_enabled=True):
            self.assertTrue(daily_report.enabled())

    def test_the_delay_is_the_nightly_calculation_at_the_report_hour(self):
        # ۰۸:۳۰ امروز -> تا ۰۹:۰۰ سی دقیقه؛ ۰۹:۰۰:۰۱ -> تقریباً یه روز.
        morning = time.mktime((2026, 9, 30, 8, 30, 0, 0, 0, -1))
        self.assertEqual(expiry.seconds_until_next_run(hour=9, minute=0, now=morning), 1800)
        after = time.mktime((2026, 9, 30, 9, 0, 1, 0, 0, -1))
        self.assertEqual(expiry.seconds_until_next_run(hour=9, minute=0, now=after), DAY - 1)

    def run_loop(self, sleeps, **values):
        """حلقه رو اجرا می‌کنه؛ sleepها پشت‌سرهم از sleeps مصرف می‌شن و آخرش cancel."""
        waited = []

        async def fake_sleep(seconds):
            waited.append(seconds)
            if len(waited) > len(sleeps):
                raise asyncio.CancelledError
        send = mock.AsyncMock()
        with self.cfg(**values), \
                mock.patch.object(background.asyncio, "sleep", fake_sleep), \
                mock.patch.object(background.expiry, "seconds_until_next_run",
                                  return_value=1234) as until, \
                mock.patch.object(background, "send_daily_report", send):
            run(background._daily_report_loop(mock.Mock()))
        return waited, until, send

    def test_the_loop_sleeps_until_the_configured_hour_then_sends_once(self):
        waited, until, send = self.run_loop([1234], daily_report_hour=6)
        until.assert_called_with(hour=6, minute=0)
        self.assertEqual(waited[0], 1234)
        self.assertEqual(waited[1], 60)          # جلوی ارسالِ دوباره
        send.assert_awaited_once()

    def test_a_disabled_report_sleeps_but_sends_nothing(self):
        _waited, _until, send = self.run_loop([1234], daily_report_enabled=False)
        send.assert_not_called()

    def test_a_failing_send_does_not_kill_the_loop(self):
        waited = []

        async def fake_sleep(seconds):
            waited.append(seconds)
            if len(waited) > 4:
                raise asyncio.CancelledError
        send = mock.AsyncMock(side_effect=RuntimeError("boom"))
        with mock.patch.object(background.asyncio, "sleep", fake_sleep), \
                mock.patch.object(background.logging_setup, "log_exception"), \
                mock.patch.object(background, "send_daily_report", send):
            run(background._daily_report_loop(mock.Mock()))
        self.assertEqual(send.await_count, 2)


if __name__ == "__main__":
    unittest.main()

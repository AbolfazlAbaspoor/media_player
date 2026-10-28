"""
B8: /catalog, /quote (command + button wizard), the button-driven "issue
a licence" wizard (/grant equivalent), the button-driven rental-reset
wizard, and audio-line add/delete/ensure from the admin panel.

Also requirement 2: every one of these must be reachable by tapping
through buttons and prompted messages, never a raw command a reader has
to memorize -- these tests exercise exactly that button/prompt path, not
just the slash-command shortcut.
"""

import asyncio
import os
import shutil
import tempfile
import unittest
from unittest import mock

from core import audio_lines
from licensing import db as db_module
from licensing.telegram.sales import admin_catalog
from licensing.telegram.sales import admin_grants
from licensing.telegram.sales import admin_panel


def run(coro):
    return asyncio.run(coro)


def _update():
    update = mock.Mock()
    update.effective_user.id = 1
    update.callback_query = None
    return update


class CatalogTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = db_module.Database(os.path.join(self.tmp, "t.sqlite3"))
        mock.patch.object(admin_catalog, "_is_admin", return_value=True).start()
        mock.patch.object(admin_catalog, "_db", return_value=self.db).start()
        self.sent = mock.patch.object(admin_catalog, "_send", new=mock.AsyncMock()).start()
        self.context = mock.Mock()
        self.context.user_data = {}

    def tearDown(self):
        mock.patch.stopall()
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_catalog_button_shows_prices_from_the_shared_catalog_module(self):
        from licensing import catalog, pricing

        run(admin_catalog.cmd_catalog(_update(), self.context))
        text = self.sent.call_args[0][1]
        base = catalog.pricing()["base_monthly_usd"]
        self.assertIn(pricing.format_usd(base), text)

    def test_quote_command_uses_pricing_quote(self):
        self.context.args = ["3", "2"]
        run(admin_catalog.cmd_quote(_update(), self.context))
        text = self.sent.call_args[0][1]
        self.assertIn("3", text)
        self.assertIn("2", text)

    def test_quote_command_bad_args_shows_usage(self):
        self.context.args = ["3"]
        run(admin_catalog.cmd_quote(_update(), self.context))
        self.sent.assert_awaited()

    def test_quote_wizard_walks_months_bots_features(self):
        update = _update()
        run(admin_catalog.admin_quote_start(update, self.context))
        self.assertEqual(self.context.user_data["awaiting"], "quote_months")

        run(admin_catalog.admin_quote_months(update, self.context, "6"))
        self.assertEqual(self.context.user_data["quote_wizard"]["months"], 6)
        self.assertEqual(self.context.user_data["awaiting"], "quote_bots")

        run(admin_catalog.admin_quote_bots(update, self.context, "2"))
        self.assertEqual(self.context.user_data["quote_wizard"]["bots"], 2)
        self.assertEqual(self.context.user_data["awaiting"], "quote_features")

        run(admin_catalog.admin_quote_features(update, self.context, "-"))
        text = self.sent.call_args[0][1]
        self.assertIn("6", text)
        self.assertNotIn("quote_wizard", self.context.user_data)

    def test_quote_wizard_rejects_non_numeric_months(self):
        update = _update()
        run(admin_catalog.admin_quote_start(update, self.context))
        run(admin_catalog.admin_quote_months(update, self.context, "abc"))
        # awaiting نباید عوض بشه چون رد شد
        self.assertEqual(self.context.user_data["awaiting"], "quote_months")


class GrantWizardTest(unittest.TestCase):
    """
    🎁 صدورِ لایسنس: فقط آیدیِ مشتری تایپ می‌شه؛ مدت (روز/ماه)، ربات و
    امکانات همه با دکمه‌ان (admin_gift.py) -- نه عدد و کدِ تایپی.
    """

    def setUp(self):
        from licensing.telegram.sales import admin_gift
        self.gift = admin_gift
        self.tmp = tempfile.mkdtemp()
        self.db = db_module.Database(os.path.join(self.tmp, "t.sqlite3"))
        for module in (admin_grants, admin_gift):
            mock.patch.object(module, "_is_admin", return_value=True).start()
            mock.patch.object(module, "_db", return_value=self.db).start()
        self.sent = mock.patch.object(admin_grants, "_send", new=mock.AsyncMock()).start()
        self.gift_sent = mock.patch.object(admin_gift, "_send", new=mock.AsyncMock()).start()
        mock.patch("licensing.telegram.sales.admin_commands._db", return_value=self.db).start()
        mock.patch("licensing.telegram.sales.admin_commands._notify",
                   new=mock.AsyncMock()).start()

        self.update = _update()
        self.context = mock.Mock()
        self.context.user_data = {}
        self.context.application.bot_data = {"db": self.db}

    def tearDown(self):
        mock.patch.stopall()
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _tap(self, action, arg=None):
        run(self.gift.gift_on_callback(self.update, self.context, action, arg))

    def _markup_callbacks(self):
        markup = self.gift_sent.call_args[0][2]
        return [b.callback_data for row in markup.inline_keyboard for b in row]

    def test_full_wizard_issues_a_licence_with_buttons_only(self):
        run(admin_grants.admin_grant_start(self.update, self.context))
        self.assertEqual(self.context.user_data["awaiting"], "grant_user_id")

        run(admin_grants.admin_grant_user_id(self.update, self.context, "777"))
        self.assertNotIn("awaiting", self.context.user_data)
        self.assertEqual(self.context.user_data["gift"]["user_id"], 777)
        callbacks = self._markup_callbacks()
        for expected in ("agr:d:+1", "agr:d:-1", "agr:d:+30", "agr:d:-30",
                         "agr:b:+1", "agr:feat", "agr:issue", "agr:cancel"):
            self.assertIn(expected, callbacks)

        self._tap("d", "+30")          # ۶۰ روز
        self._tap("d", "+1")           # ۶۱ روز
        self._tap("b", "+1")           # ۲ ربات
        self._tap("feat")
        some_code = sorted(__import__("licensing.catalog", fromlist=["x"]).features())[0]
        self._tap("tf", some_code)
        self._tap("done")
        self._tap("issue")

        row = self.db.licenses_by_user(777)[0]
        self.assertEqual(int(row["max_bots"]), 2)
        self.assertEqual(int(row["expires_at"]) - int(row["starts_at"]), 61 * 86400)
        self.assertIn(some_code, row["features"])
        self.assertNotIn("gift", self.context.user_data)

    def test_a_few_days_gift_is_possible(self):
        run(admin_grants.admin_grant_user_id(self.update, self.context, "779"))
        for _ in range(27):
            self._tap("d", "-1")       # ۳۰ -> ۳ روز
        self._tap("issue")
        row = self.db.licenses_by_user(779)[0]
        self.assertEqual(int(row["expires_at"]) - int(row["starts_at"]), 3 * 86400)

    def test_duration_and_bots_are_clamped(self):
        run(admin_grants.admin_grant_user_id(self.update, self.context, "780"))
        for _ in range(40):
            self._tap("d", "-1")
            self._tap("b", "-1")
        state = self.context.user_data["gift"]
        self.assertEqual(state["days"], 1)
        self.assertEqual(state["bots"], 1)

    def test_bad_telegram_id_is_rejected(self):
        run(admin_grants.admin_grant_start(self.update, self.context))
        run(admin_grants.admin_grant_user_id(self.update, self.context, "not-a-number"))
        self.assertEqual(self.context.user_data["awaiting"], "grant_user_id")
        self.assertNotIn("gift", self.context.user_data)

    def test_cancel_issues_nothing(self):
        run(admin_grants.admin_grant_user_id(self.update, self.context, "778"))
        self._tap("cancel")
        self._tap("issue")   # بعد از لغو، دکمه‌ی قدیمیِ «صدور» نباید کاری کنه
        self.assertEqual(self.db.licenses_by_user(778), [])

    def test_rental_wizard_writes_to_cloudflare_with_chosen_days_and_bots(self):
        with mock.patch("licensing.cloudflare.available", return_value=True),              mock.patch("licensing.cloudflare.write_licence") as write:
            run(admin_grants.admin_rental_start(self.update, self.context))
            self.assertEqual(self.context.user_data["gift"]["mode"], "rental")
            self._tap("d", "-30")      # ۳۰ -> ۱ روز (حداقل)
            self._tap("d", "+1")       # ۲ روز
            self._tap("tclear")
            self._tap("issue")
        args = write.call_args[0]
        key, expires_at, features, bots = args[0], args[1], args[2], args[3]
        self.assertTrue(key.startswith("TT-"))
        self.assertEqual(features, [])
        self.assertEqual(bots, 1)
        self.assertAlmostEqual(expires_at - __import__("time").time(), 2 * 86400, delta=60)

    def test_rental_all_features_means_all(self):
        with mock.patch("licensing.cloudflare.available", return_value=True),              mock.patch("licensing.cloudflare.write_licence") as write:
            run(admin_grants.admin_rental_start(self.update, self.context))
            self._tap("issue")          # پیش‌فرضِ اجاره‌ای: همه‌ی امکانات
        self.assertIsNone(write.call_args[0][2])


class RentalResetWizardTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = db_module.Database(os.path.join(self.tmp, "t.sqlite3"))
        mock.patch.object(admin_grants, "_is_admin", return_value=True).start()
        mock.patch.object(admin_grants, "_db", return_value=self.db).start()
        self.sent = mock.patch.object(admin_grants, "_send", new=mock.AsyncMock()).start()
        mock.patch("licensing.config.get",
                   side_effect=lambda k, d=None: [] if k == "protected_licences" else d).start()

        self.update = _update()
        self.context = mock.Mock()
        self.context.user_data = {}

    def tearDown(self):
        mock.patch.stopall()
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_start_asks_for_key_then_shows_day_buttons(self):
        run(admin_grants.admin_rental_reset_start(self.update, self.context))
        self.assertEqual(self.context.user_data["awaiting"], "rental_reset_key")

        run(admin_grants.admin_rental_reset_key_text(self.update, self.context, "tt-aaaa-bbbb-cccc"))
        markup = self.sent.call_args[0][2]
        callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
        self.assertTrue(any(cb.startswith("adm:rreset:TT-AAAA-BBBB-CCCC:") for cb in callbacks))

    def test_protected_key_is_refused_before_touching_cloudflare(self):
        with mock.patch("licensing.config.get",
                        side_effect=lambda k, d=None: ["TT-EQ4F-2V6D-AWFF"]
                        if k == "protected_licences" else d), \
             mock.patch("licensing.cloudflare.get") as kv_get:
            run(admin_grants.admin_rental_reset_attempt(
                self.update, self.context, "TT-EQ4F-2V6D-AWFF", 30, force=False))
        kv_get.assert_not_called()
        text = self.sent.call_args[0][1]
        self.assertIn("EQ4F", text)

    def test_bound_licence_offers_a_confirm_button_instead_of_force_flag(self):
        record = {"fingerprint": "abc", "features": None, "max_bots": 1, "note": ""}
        with mock.patch("licensing.cloudflare.available", return_value=True), \
             mock.patch("licensing.cloudflare.get", return_value=record), \
             mock.patch("licensing.cloudflare.write_licence") as write_mock:
            run(admin_grants.admin_rental_reset_attempt(
                self.update, self.context, "TT-AAAA-BBBB-CCCC", 30, force=False))
        write_mock.assert_not_called()
        markup = self.sent.call_args[0][2]
        callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
        self.assertIn("adm:rresetok:TT-AAAA-BBBB-CCCC:30", callbacks)

    def test_confirm_button_forces_the_reset(self):
        record = {"fingerprint": "abc", "features": None, "max_bots": 1, "note": ""}
        with mock.patch("licensing.cloudflare.available", return_value=True), \
             mock.patch("licensing.cloudflare.get", return_value=record), \
             mock.patch("licensing.cloudflare.write_licence") as write_mock, \
             mock.patch("licensing.cloudflare.delete"):
            run(admin_grants.admin_rental_reset_force_button(
                self.update, self.context, "TT-AAAA-BBBB-CCCC", "30"))
        write_mock.assert_called_once()

    def test_unbound_licence_resets_immediately_without_confirmation(self):
        record = {"fingerprint": None, "features": None, "max_bots": 1, "note": ""}
        with mock.patch("licensing.cloudflare.available", return_value=True), \
             mock.patch("licensing.cloudflare.get", return_value=record), \
             mock.patch("licensing.cloudflare.write_licence") as write_mock, \
             mock.patch("licensing.cloudflare.delete"):
            run(admin_grants.admin_rental_reset_days_button(
                self.update, self.context, "TT-AAAA-BBBB-CCCC", "30"))
        write_mock.assert_called_once()


class LineManagementTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = db_module.Database(os.path.join(self.tmp, "t.sqlite3"))
        mock.patch.object(admin_panel, "_is_admin", return_value=True).start()
        mock.patch.object(admin_panel, "_db", return_value=self.db).start()
        self.sent = mock.patch.object(admin_panel, "_send", new=mock.AsyncMock()).start()

        self.update = _update()
        self.context = mock.Mock()
        self.context.user_data = {}

    def tearDown(self):
        mock.patch.stopall()
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_add_asks_then_creates_the_line(self):
        run(admin_panel.admin_line_add_start(self.update, self.context))
        self.assertEqual(self.context.user_data["awaiting"], "line_add")

        line = {"slug": "myline", "output_device": "out", "input_device": "in"}
        with mock.patch.object(audio_lines, "create_line", return_value=line) as create:
            run(admin_panel.admin_line_add_text(self.update, self.context, "myline a test line"))
        create.assert_called_once()
        self.assertNotIn("awaiting", self.context.user_data)

    def test_add_failure_shows_the_domain_error_not_a_crash(self):
        with mock.patch.object(audio_lines, "create_line",
                               side_effect=audio_lines.AudioLineError("no more lines")):
            run(admin_panel.admin_line_add_text(self.update, self.context, "myline"))
        text = self.sent.call_args[0][1]
        self.assertIn("no more lines", text)

    def test_delete_asks_for_confirmation(self):
        run(admin_panel.admin_line_del_confirm(self.update, self.context, "myline"))
        markup = self.sent.call_args[0][2]
        callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
        self.assertIn("adm:linedelok:myline", callbacks)

    def test_delete_confirmed_calls_destroy_line(self):
        with mock.patch.object(audio_lines, "destroy_line", return_value=True) as destroy, \
             mock.patch.object(audio_lines, "list_lines", return_value=[]):
            run(admin_panel.admin_line_del(self.update, self.context, "myline"))
        destroy.assert_called_once_with("myline")

    def test_ensure_reports_the_restored_count(self):
        with mock.patch.object(audio_lines, "ensure_all_lines", return_value=3):
            run(admin_panel.admin_line_ensure(self.update, self.context))
        text = self.sent.call_args[0][1]
        self.assertIn("3", text)

    def test_lines_list_has_a_delete_button_per_line_and_add_ensure_buttons(self):
        lines = [{"slug": "a", "alive": True, "output_device": "o", "input_device": "i"}]
        with mock.patch.object(audio_lines, "list_lines", return_value=lines):
            run(admin_panel.admin_lines(self.update, self.context))
        markup = self.sent.call_args[0][2]
        callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
        self.assertIn("adm:linedel:a", callbacks)
        self.assertIn("adm:lineadd", callbacks)
        self.assertIn("adm:lineensure", callbacks)


if __name__ == "__main__":
    unittest.main()


class FreebotSelfTest(unittest.TestCase):
    """👑 یه‌ضرب: لایسنسِ نامحدود برای خودِ ادمین، بدونِ پرسیدنِ آیدی."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = db_module.Database(os.path.join(self.tmp, "t.sqlite3"))
        mock.patch.object(admin_grants, "_is_admin", return_value=True).start()
        mock.patch.object(admin_grants, "_db", return_value=self.db).start()
        mock.patch.object(admin_grants, "_send", new=mock.AsyncMock()).start()
        self.update = _update()
        self.update.effective_user.id = 4242
        self.update.effective_chat.send_message = mock.AsyncMock()
        self.context = mock.Mock()
        self.context.user_data = {}

    def tearDown(self):
        mock.patch.stopall()
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_grants_unlimited_to_the_admin_themself(self):
        run(admin_grants.admin_freebot_self(self.update, self.context))
        rows = self.db.licenses_by_user(4242)
        self.assertEqual(len(rows), 1)
        self.assertGreaterEqual(int(rows[0]["max_bots"]), 99)
        from licensing import catalog
        for code in catalog.features():
            self.assertIn(code, rows[0]["features"])

    def test_non_admin_gets_nothing(self):
        with mock.patch.object(admin_grants, "_is_admin", return_value=False):
            run(admin_grants.admin_freebot_self(self.update, self.context))
        self.assertEqual(self.db.licenses_by_user(4242), [])

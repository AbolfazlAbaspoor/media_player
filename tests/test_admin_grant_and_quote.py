"""
B7 (2026-09-16): admin muscle memory. /grant, manage.py grant/quote and
promo-add all used to take a users argument/option; it is gone now, but
the old form (with an extra numeric/legacy argument in the old users
position) must still be accepted, ignored, and reported in one short line
-- never crash and never silently misinterpret a bots count as a users
count.
"""

import asyncio
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

import manage
from licensing import db as db_module

FUTURE = int(time.time()) + 30 * 86400


class TelegramGrantTest(unittest.TestCase):
    """/grant <user_id> <months> [bots] [feature_codes...] (sales bot)."""

    def setUp(self):
        from licensing.telegram.sales import admin_commands as ac
        self.ac = ac
        self.tmp = tempfile.mkdtemp()
        self.db = db_module.Database(os.path.join(self.tmp, "t.sqlite3"))
        mock.patch.object(ac, "_is_admin", return_value=True).start()
        mock.patch.object(ac, "_db", return_value=self.db).start()
        self.sent = mock.patch.object(ac, "_send", new=mock.AsyncMock()).start()
        mock.patch.object(ac, "_notify", new=mock.AsyncMock()).start()
        self.update = mock.Mock()
        self.update.effective_user.id = 1
        self.context = mock.Mock()

    def tearDown(self):
        mock.patch.stopall()
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_new_form_has_no_users_argument(self):
        self.context.args = ["555", "2", "3"]  # user_id months bots
        asyncio.run(self.ac.cmd_grant(self.update, self.context))
        row = self.db.licenses_by_user(555)[0]
        self.assertEqual(int(row["max_bots"]), 3)
        text = self.sent.call_args[0][1]
        self.assertNotIn("ignored", text.lower())

    def test_legacy_form_with_extra_users_argument_is_accepted_and_ignored(self):
        self.context.args = ["556", "2", "3", "9"]  # ...bots, then old users=9
        asyncio.run(self.ac.cmd_grant(self.update, self.context))
        row = self.db.licenses_by_user(556)[0]
        self.assertEqual(int(row["max_bots"]), 3)  # "9" was not read as bots
        text = self.sent.call_args[0][1]
        self.assertIn("ignored", text.lower())

    def test_legacy_form_with_users_and_features_keeps_the_features(self):
        self.context.args = ["557", "1", "1", "9", "svc_tiktok"]
        asyncio.run(self.ac.cmd_grant(self.update, self.context))
        row = self.db.licenses_by_user(557)[0]
        self.assertEqual(db_module.json_list(row["features"]), ["svc_tiktok"])


class ManageGrantAndQuoteTest(unittest.TestCase):
    """python manage.py grant / quote."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = db_module.Database(os.path.join(self.tmp, "t.sqlite3"))
        mock.patch.object(manage, "_db", return_value=self.db).start()
        self.buf = []
        mock.patch("builtins.print",
                   side_effect=lambda *a: self.buf.append(" ".join(str(x) for x in a))).start()

    def tearDown(self):
        mock.patch.stopall()
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_grant_new_form(self):
        code = manage.cmd_grant(["600", "2", "3"])
        self.assertEqual(code, 0)
        row = self.db.licenses_by_user(600)[0]
        self.assertEqual(int(row["max_bots"]), 3)

    def test_grant_legacy_form_ignores_the_old_users_argument(self):
        code = manage.cmd_grant(["601", "2", "3", "9"])
        self.assertEqual(code, 0)
        row = self.db.licenses_by_user(601)[0]
        self.assertEqual(int(row["max_bots"]), 3)
        self.assertTrue(any("نادیده" in line for line in self.buf))

    def test_quote_new_form(self):
        code = manage.cmd_quote(["1", "2"])
        self.assertEqual(code, 0)
        self.assertTrue(any("ربات: 2" in line for line in self.buf))
        self.assertFalse(any("نادیده" in line for line in self.buf))

    def test_quote_legacy_form_ignores_the_old_users_argument(self):
        code = manage.cmd_quote(["1", "5", "2"])  # months=1, users=5 (legacy), bots=2
        self.assertEqual(code, 0)
        self.assertTrue(any("ربات: 2" in line for line in self.buf))
        self.assertTrue(any("نادیده" in line for line in self.buf))


class PromoAddIgnoresLegacyUsersTest(unittest.TestCase):
    """promo-add / /promoadd silently accept and ignore a legacy users= option."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = db_module.Database(os.path.join(self.tmp, "t.sqlite3"))

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_manage_promo_add_ignores_legacy_users_option(self):
        with mock.patch.object(manage, "_db", return_value=self.db), \
                mock.patch("builtins.print"):
            code = manage.cmd_promo_add(["welcome10", "percent_off", "10", "5",
                                        "users=7", "bots=2"])
        self.assertEqual(code, 0)
        promo = self.db.get_promo("WELCOME10")
        self.assertEqual(int(promo["max_bots"]), 2)
        self.assertEqual(int(promo["max_users"]), 1)  # legacy option silently ignored

    def test_telegram_promoadd_ignores_legacy_users_option(self):
        from licensing.telegram.sales import promo_codes as pc

        with mock.patch.object(pc, "_is_admin", return_value=True), \
                mock.patch.object(pc, "_db", return_value=self.db), \
                mock.patch.object(pc, "_send", new=mock.AsyncMock()):
            context = mock.Mock()
            context.args = ["gift5", "percent_off", "5", "3", "users=9"]
            update = mock.Mock()
            update.effective_user.id = 1
            asyncio.run(pc.cmd_promoadd(update, context))
        promo = self.db.get_promo("GIFT5")
        self.assertIsNotNone(promo)
        self.assertEqual(int(promo["max_users"]), 1)


class LicCommandHasNoQuotaTest(unittest.TestCase):
    """commands/lic.py shows how many operators are set, not "X of Y"."""

    def _run(self, admins=None, bot_admins=None):
        from commands import lic

        state = mock.Mock(unlicensed=False, managed=True, key="TT-AAAA-BBBB-CCCC")
        state.status_text.return_value = "لایسنس فعال"
        state.in_grace.return_value = False

        bot = mock.Mock()
        bot.license = state
        bot.services = {"youtube"}
        bot.commands = {"p", "s"}
        bot.cfg = {"admins": admins or [], "bot_admins": bot_admins or []}
        bot.send_long_text = mock.Mock()
        ctx = {"bot": bot, "uid": 42}
        lic.run(ctx)
        return bot.send_long_text.call_args[0][1]

    def test_operator_count_is_shown_without_a_quota(self):
        text = self._run(admins=[1, 2], bot_admins=[3])
        self.assertIn("Admin users: 3", text)
        self.assertNotIn(" از ", text)  # no "X of Y" wording left

    def test_no_operator_line_when_none_are_configured(self):
        text = self._run(admins=[], bot_admins=[])
        self.assertNotIn("Admin users", text)


if __name__ == "__main__":
    unittest.main()

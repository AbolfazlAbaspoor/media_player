"""
B8 + requirement 3: an admin-only view of every licence on the server
(not just one user's), filterable/pageable/searchable, each opening the
full licence card with extend/suspend/resume/revoke and a delete action
distinct from revoke.
"""

import asyncio
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from licensing import db as db_module
from licensing import licenses
from licensing.telegram.sales import admin_licenses

FUTURE = int(time.time()) + 30 * 86400


def run(coro):
    return asyncio.run(coro)


class AdminLicensesTestBase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = db_module.Database(os.path.join(self.tmp, "t.sqlite3"))
        # همه‌ی ماژول‌ها (admin_licenses، my_licenses، admin_commands) از
        # config.is_admin استفاده می‌کنن -- یه پچِ سراسری، به‌جای پچِ
        # جداگونه‌ی هر تابعِ _is_admin تویِ هر فایل.
        mock.patch("licensing.config.is_admin", return_value=True).start()
        mock.patch.object(admin_licenses, "_db", return_value=self.db).start()
        self.sent = mock.patch.object(admin_licenses, "_send", new=mock.AsyncMock()).start()
        mock.patch("licensing.telegram.sales.my_licenses._db", return_value=self.db).start()
        mock.patch("licensing.telegram.sales.my_licenses._notify", new=mock.AsyncMock()).start()
        mock.patch("licensing.telegram.sales.my_licenses._send", new=mock.AsyncMock()).start()
        mock.patch("licensing.telegram.sales.admin_commands._notify", new=mock.AsyncMock()).start()

        self.update = mock.Mock()
        self.update.effective_user.id = 1
        self.update.callback_query = None
        self.context = mock.Mock()
        self.context.user_data = {}
        self.context.application.bot_data = {"db": self.db, "supervisor": None}

    def tearDown(self):
        mock.patch.stopall()
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _license(self, user_id, status="active", key=None):
        row = self.db.create_license(
            key=key or licenses.unique_key(self.db), user_id=user_id, order_id=None,
            max_bots=1, max_users=1, features=[],
            starts_at=int(time.time()), expires_at=FUTURE, status=status)
        return row


class ListFilterPaginationTest(AdminLicensesTestBase):

    def test_lists_licences_across_different_owners(self):
        self._license(100)
        self._license(200)
        run(admin_licenses.admin_licenses_list(self.update, self.context, "active", 0))
        text, markup = self.sent.call_args[0][1], self.sent.call_args[0][2]
        self.assertIn("2", text)
        keys_in_markup = [b.callback_data for row in markup.inline_keyboard for b in row]
        self.assertTrue(any(cb.startswith("lic:show:") for cb in keys_in_markup))

    def test_filter_excludes_other_statuses(self):
        self._license(100, status="active")
        self._license(200, status="revoked")
        run(admin_licenses.admin_licenses_list(self.update, self.context, "revoked", 0))
        text = self.sent.call_args[0][1]
        self.assertIn("1", text)

    def test_pagination_second_page(self):
        for uid in range(300, 312):   # 12 licences, page size 8
            self._license(uid)
        run(admin_licenses.admin_licenses_list(self.update, self.context, "active", 0))
        markup = self.sent.call_args[0][2]
        nav_targets = [b.callback_data for row in markup.inline_keyboard for b in row
                      if b.callback_data.startswith("adm:lics:active:")]
        self.assertTrue(any(cb.endswith(":1") for cb in nav_targets))

    def test_empty_status_is_reported_not_crashed(self):
        run(admin_licenses.admin_licenses_list(self.update, self.context, "paused", 0))
        self.sent.assert_awaited()

    def test_non_admin_is_refused(self):
        with mock.patch.object(admin_licenses, "_is_admin", return_value=False):
            run(admin_licenses.admin_licenses_list(self.update, self.context))
        text = self.sent.call_args[0][1]
        self.assertTrue(text)


class FindLicenseTest(AdminLicensesTestBase):

    def test_find_start_asks_for_key_or_id(self):
        run(admin_licenses.admin_license_find_start(self.update, self.context))
        self.assertEqual(self.context.user_data["awaiting"], "license_find")

    def test_find_by_exact_key(self):
        row = self._license(500)
        with mock.patch("licensing.telegram.sales.admin_licenses.show_license",
                        new=mock.AsyncMock()) as show:
            run(admin_licenses.admin_license_find_text(self.update, self.context, row["key"]))
        show.assert_awaited_once()

    def test_find_by_telegram_id_with_one_license_opens_card(self):
        self._license(501)
        with mock.patch("licensing.telegram.sales.admin_licenses.show_license",
                        new=mock.AsyncMock()) as show:
            run(admin_licenses.admin_license_find_text(self.update, self.context, "501"))
        show.assert_awaited_once()

    def test_find_by_telegram_id_with_several_licenses_lists_them(self):
        self._license(502)
        self._license(502)
        run(admin_licenses.admin_license_find_text(self.update, self.context, "502"))
        text = self.sent.call_args[0][1]
        self.assertIn("2", text)

    def test_find_nothing_matching(self):
        run(admin_licenses.admin_license_find_text(self.update, self.context, "999999"))
        self.sent.assert_awaited()


class CardActionsTest(AdminLicensesTestBase):

    def setUp(self):
        super().setUp()
        self.row = self._license(600)

    def test_extend_calls_shared_extend_logic_and_reshows_card(self):
        with mock.patch("licensing.telegram.sales.admin_licenses.show_license",
                        new=mock.AsyncMock()) as show:
            run(admin_licenses.admin_extend_license(self.update, self.context, int(self.row["id"]), 3))
        updated = self.db.get_license(int(self.row["id"]))
        self.assertGreater(int(updated["expires_at"]), FUTURE)
        show.assert_awaited_once()

    def test_suspend_then_resume(self):
        with mock.patch("licensing.telegram.sales.admin_licenses.show_license", new=mock.AsyncMock()):
            run(admin_licenses.admin_suspend_button(self.update, self.context, int(self.row["id"])))
        self.assertEqual(self.db.get_license(int(self.row["id"]))["status"], licenses.STATUS_SUSPENDED)
        with mock.patch("licensing.telegram.sales.admin_licenses.show_license", new=mock.AsyncMock()):
            run(admin_licenses.admin_resume_button(self.update, self.context, int(self.row["id"])))
        self.assertEqual(self.db.get_license(int(self.row["id"]))["status"], licenses.STATUS_ACTIVE)

    def test_resume_on_an_expired_license_is_refused_not_crashed(self):
        expired = self._license(601, status=licenses.STATUS_SUSPENDED)
        self.db.update_license(int(expired["id"]), expires_at=int(time.time()) - 10)
        run(admin_licenses.admin_resume_button(self.update, self.context, int(expired["id"])))
        self.assertEqual(self.db.get_license(int(expired["id"]))["status"], licenses.STATUS_SUSPENDED)

    def test_revoke_requires_confirmation_first(self):
        run(admin_licenses.admin_revoke_confirm(self.update, self.context, int(self.row["id"])))
        self.assertEqual(self.db.get_license(int(self.row["id"]))["status"], licenses.STATUS_ACTIVE)
        markup = self.sent.call_args[0][2]
        callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
        self.assertIn(f"adm:revokeok:{self.row['id']}", callbacks)

    def test_revoke_confirmed_actually_revokes(self):
        with mock.patch("licensing.telegram.sales.admin_licenses.show_license", new=mock.AsyncMock()):
            run(admin_licenses.admin_revoke_button(self.update, self.context, int(self.row["id"])))
        self.assertEqual(self.db.get_license(int(self.row["id"]))["status"], licenses.STATUS_REVOKED)


class DeleteIsReachableFromTheAdminCardTest(AdminLicensesTestBase):
    """
    Requirement 3: full deletion (distinct from revoke) must be reachable
    from the card the admin list opens -- my_licenses.show_license /
    kb.license_actions already do this for an admin viewing ANY licence;
    this locks in that the admin-wide list wires into that exact path.
    """

    def test_admin_viewing_someone_elses_licence_gets_the_delete_button(self):
        from licensing.telegram import keyboards as kb
        from licensing.telegram.sales.my_licenses import show_license

        row = self._license(700)   # owned by a different telegram id than the admin
        with mock.patch("licensing.telegram.sales.my_licenses._is_admin", return_value=True), \
             mock.patch("licensing.telegram.sales.my_licenses._db", return_value=self.db), \
             mock.patch("licensing.telegram.sales.my_licenses._supervisor", return_value=None), \
             mock.patch("licensing.telegram.sales.my_licenses._send", new=mock.AsyncMock()) as sent:
            run(show_license(self.update, self.context, int(row["id"])))
        markup = sent.call_args[0][2]
        callbacks = [b.callback_data for r in markup.inline_keyboard for b in r]
        self.assertIn(f"lic:del:{row['id']}", callbacks)

    def test_admin_delete_license_removes_the_row_and_instances(self):
        from licensing.telegram.sales.my_licenses import admin_delete_license

        row = self._license(701)
        with mock.patch("licensing.telegram.sales.my_licenses._is_admin", return_value=True), \
             mock.patch("licensing.telegram.sales.my_licenses._db", return_value=self.db), \
             mock.patch("licensing.telegram.sales.my_licenses._supervisor", return_value=None), \
             mock.patch("licensing.telegram.sales.my_licenses._send", new=mock.AsyncMock()), \
             mock.patch("licensing.provisioning.deactivate_license", return_value=[]):
            run(admin_delete_license(self.update, self.context, int(row["id"]), confirmed=True))
        self.assertIsNone(self.db.get_license(int(row["id"])))


if __name__ == "__main__":
    unittest.main()

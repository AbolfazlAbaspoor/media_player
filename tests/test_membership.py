"""
Mandatory membership of the official Telegram channel: leave -> warned,
24h out -> licence paused and bots stopped, rejoin -> everything back.
"""

import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from unittest import mock

from licensing import db as db_module
from licensing import licenses, membership

NOW = int(time.time())
DAY = 86400


class MembershipTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = db_module.Database(os.path.join(self.tmp, "t.sqlite3"))
        self.refresh = mock.patch("licensing.provisioning.refresh_license_files").start()
        mock.patch.object(membership, "required_channel", return_value="@official").start()
        mock.patch("licensing.config.get",
                   side_effect=lambda k, d=None: 24 if k == "channel_grace_hours" else d).start()
        self.db.upsert_user(100, "cust", "Cust")

    def tearDown(self):
        mock.patch.stopall()
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _licence(self, status="active", expires_at=NOW + 30 * DAY, key="TT-AAAA-BBBB-CCCC"):
        return self.db.create_license(key, 100, None, 1, 1, [], NOW, expires_at, status=status)

    def _instance(self, license_row, slug, status):
        return self.db.create_instance(int(license_row["id"]), slug, "host", 10333,
                                       "nick", "user", "pass", status=status)

    # ------------------------------------------------------------ migration

    def test_old_database_gains_the_new_columns(self):
        path = os.path.join(self.tmp, "old.sqlite3")
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE users (telegram_id INTEGER PRIMARY KEY, username TEXT, "
                     "first_name TEXT, lang TEXT NOT NULL DEFAULT 'en', created_at INTEGER NOT NULL, "
                     "last_seen_at INTEGER, blocked INTEGER NOT NULL DEFAULT 0, "
                     "personal_bot_token TEXT, personal_bot_username TEXT, "
                     "personal_bot_status TEXT NOT NULL DEFAULT 'none')")
        conn.commit()
        conn.close()
        old = db_module.Database(path)
        cols = {row[1] for row in old.query("PRAGMA table_info(users)")}
        old.close()
        self.assertIn("channel_left_at", cols)

    # --------------------------------------------------------------- status

    def test_member_statuses(self):
        for status in ("creator", "owner", "administrator", "member"):
            self.assertTrue(membership.is_member_status(status), status)
        for status in ("left", "kicked", "banned", None):
            self.assertFalse(membership.is_member_status(status), status)
        self.assertTrue(membership.is_member_status("restricted", is_member=True))
        self.assertFalse(membership.is_member_status("restricted", is_member=False))

    def test_join_url(self):
        self.assertEqual(membership.join_url("@official"), "https://t.me/official")
        self.assertIsNone(membership.join_url("-1001234567890"))

    def test_leaving_warns_once(self):
        self.assertTrue(membership.mark_left(self.db, 100, NOW))
        self.assertFalse(membership.mark_left(self.db, 100, NOW + 3600))
        self.assertTrue(membership.is_out(self.db, 100))

    def test_rejoining_clears_the_mark(self):
        membership.mark_left(self.db, 100, NOW)
        self.assertTrue(membership.mark_joined(self.db, 100))
        self.assertFalse(membership.is_out(self.db, 100))
        self.assertFalse(membership.mark_joined(self.db, 100))

    # --------------------------------------------------------------- timing

    def test_nobody_is_paused_inside_the_24_hours(self):
        self._licence()
        membership.mark_left(self.db, 100, NOW - 23 * 3600)
        self.assertEqual(membership.users_to_pause(self.db, NOW), [])

    def test_paused_after_24_hours(self):
        self._licence()
        membership.mark_left(self.db, 100, NOW - 25 * 3600)
        self.assertEqual(membership.users_to_pause(self.db, NOW), [100])

    # ------------------------------------------------------- pause / resume

    def test_pause_stops_running_bots_and_resume_brings_back_only_those(self):
        lic = self._licence()
        running = self._instance(lic, "bot-running", "running")
        stopped_by_customer = self._instance(lic, "bot-stopped", "stopped")
        supervisor = mock.Mock()

        paused = membership.pause_user(self.db, 100, supervisor)
        self.assertEqual([row["status"] for row in paused], ["paused"])
        supervisor.stop.assert_called_once_with("bot-running")
        # the supervisor marks what it stops as stopped
        self.db.update_instance(int(running["id"]), status="stopped")

        membership.resume_user(self.db, 100, supervisor)
        self.assertEqual(self.db.get_license(int(lic["id"]))["status"], "active")
        self.assertEqual(self.db.get_instance(int(running["id"]))["status"], "created")
        self.assertEqual(self.db.get_instance(int(stopped_by_customer["id"]))["status"], "stopped")
        started = [c.args[0]["slug"] for c in supervisor.start_instance.call_args_list]
        self.assertEqual(started, ["bot-running"])

    def test_rejoining_never_lifts_an_admin_suspension(self):
        lic = self._licence(status=licenses.STATUS_SUSPENDED)
        membership.resume_user(self.db, 100)
        self.assertEqual(self.db.get_license(int(lic["id"]))["status"], "suspended")

    def test_pause_leaves_suspended_and_expired_licences_alone(self):
        suspended = self._licence(status="suspended", key="TT-SUSP-0000-0001")
        expired = self._licence(status="expired", key="TT-EXPD-0000-0002")
        membership.pause_user(self.db, 100)
        self.assertEqual(self.db.get_license(int(suspended["id"]))["status"], "suspended")
        self.assertEqual(self.db.get_license(int(expired["id"]))["status"], "expired")

    def test_licence_that_expired_while_paused_goes_to_expired_not_active(self):
        lic = self._licence(expires_at=NOW + DAY)
        membership.pause_user(self.db, 100)
        self.db.update_license(int(lic["id"]), expires_at=NOW - 60)
        membership.resume_user(self.db, 100)
        self.assertEqual(self.db.get_license(int(lic["id"]))["status"], "expired")

    def test_feature_off_means_nobody_is_out(self):
        membership.mark_left(self.db, 100, NOW)
        with mock.patch.object(membership, "required_channel", return_value=""):
            self.assertFalse(membership.is_out(self.db, 100))


if __name__ == "__main__":
    unittest.main()

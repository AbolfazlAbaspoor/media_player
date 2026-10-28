"""
E11: a dead personal-bot token (invalid or revoked) is marked dead once,
never retried again -- including after a platform restart -- and the
owner is told exactly once, through the sales bot.
"""

import asyncio
import os
import shutil
import tempfile
import unittest
from unittest import mock

from telegram.error import Forbidden, InvalidToken, NetworkError, TimedOut

from licensing import db as db_module
from licensing.telegram import customer_bot
from licensing.telegram import runner as runner_module


def run(coro):
    return asyncio.run(coro)


class DeadTokenDetectionTest(unittest.TestCase):
    """start_customer_bot tells apart a dead token from a transient failure."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = db_module.Database(os.path.join(self.tmp, "t.sqlite3"))
        self.runner = runner_module.BotRunner(self.db)

    def tearDown(self):
        mock.patch.stopall()
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _fake_app(self, error):
        app = mock.Mock()
        app.initialize = mock.AsyncMock(side_effect=error)
        app.start = mock.AsyncMock()
        app.shutdown = mock.AsyncMock()
        return app

    def test_invalid_token_is_reported_dead(self):
        app = self._fake_app(InvalidToken())
        with mock.patch.object(customer_bot, "build_application", return_value=app):
            started, error, dead = run(self.runner.start_customer_bot(1, "bad:token"))
        self.assertFalse(started)
        self.assertTrue(dead)
        app.shutdown.assert_awaited()

    def test_forbidden_is_reported_dead(self):
        app = self._fake_app(Forbidden("bot was blocked by the user"))
        with mock.patch.object(customer_bot, "build_application", return_value=app):
            started, error, dead = run(self.runner.start_customer_bot(2, "revoked:token"))
        self.assertFalse(started)
        self.assertTrue(dead)

    def test_network_error_is_not_dead(self):
        app = self._fake_app(NetworkError("proxy timeout"))
        with mock.patch.object(customer_bot, "build_application", return_value=app):
            started, error, dead = run(self.runner.start_customer_bot(3, "some:token"))
        self.assertFalse(started)
        self.assertFalse(dead)

    def test_timed_out_is_not_dead(self):
        app = self._fake_app(TimedOut())
        with mock.patch.object(customer_bot, "build_application", return_value=app):
            started, error, dead = run(self.runner.start_customer_bot(4, "some:token"))
        self.assertFalse(started)
        self.assertFalse(dead)


class StartAllSkipsDeadTest(unittest.TestCase):
    """runner.start_all never retries a token already marked dead."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = db_module.Database(os.path.join(self.tmp, "t.sqlite3"))
        self.runner = runner_module.BotRunner(self.db)
        self.runner._sales_bot = mock.Mock(send_message=mock.AsyncMock())

    def tearDown(self):
        mock.patch.stopall()
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dead_row_is_never_started(self):
        self.db.upsert_user(100, first_name="dead-owner")
        self.db.set_personal_bot(100, "dead:token", "deadbot", status="dead")

        with mock.patch.object(self.runner, "start_customer_bot",
                                new=mock.AsyncMock()) as start:
            started, failed = run(self.runner.start_all())

        start.assert_not_called()
        self.assertEqual(started, 0)
        self.assertEqual(failed, [])

    def test_platform_restart_after_a_previous_run_still_skips_it(self):
        """Simulates two separate process lifetimes: the token dies during
        the first run, and a brand-new BotRunner (a "restart") must still
        skip it because the mark lives in the database, not in memory."""
        self.db.upsert_user(101, first_name="owner")
        self.db.set_personal_bot(101, "revoked:token", "bot101", status="running")

        with mock.patch.object(self.runner, "start_customer_bot",
                                new=mock.AsyncMock(return_value=(False, "InvalidToken: x", True))):
            run(self.runner.start_all())

        self.assertEqual(self.db.get_user(101)["personal_bot_status"], "dead")

        fresh_runner = runner_module.BotRunner(self.db)
        with mock.patch.object(fresh_runner, "start_customer_bot",
                                new=mock.AsyncMock()) as start_again:
            run(fresh_runner.start_all())
        start_again.assert_not_called()

    def test_a_newly_dead_token_notifies_the_owner_once(self):
        self.db.upsert_user(102, first_name="owner")
        self.db.set_personal_bot(102, "revoked:token", "bot102", status="running")

        with mock.patch.object(self.runner, "start_customer_bot",
                                new=mock.AsyncMock(return_value=(False, "InvalidToken: x", True))):
            run(self.runner.start_all())

        self.runner._sales_bot.send_message.assert_awaited_once()
        args, kwargs = self.runner._sales_bot.send_message.call_args
        self.assertEqual(args[0], 102)

    def test_a_transient_failure_is_not_marked_dead(self):
        self.db.upsert_user(103, first_name="owner")
        self.db.set_personal_bot(103, "some:token", "bot103", status="running")

        with mock.patch.object(self.runner, "start_customer_bot",
                                new=mock.AsyncMock(return_value=(False, "NetworkError: x", False))):
            run(self.runner.start_all())

        self.assertEqual(self.db.get_user(103)["personal_bot_status"], "failed")
        self.runner._sales_bot.send_message.assert_not_awaited()


class MarkDeadTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = db_module.Database(os.path.join(self.tmp, "t.sqlite3"))
        self.runner = runner_module.BotRunner(self.db)
        self.runner._sales_bot = mock.Mock(send_message=mock.AsyncMock())
        self.db.upsert_user(200, first_name="owner")
        self.db.set_personal_bot(200, "tok", "bot200", status="running")

    def tearDown(self):
        mock.patch.stopall()
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_marks_status_and_notifies(self):
        run(self.runner.mark_dead(200, reason="InvalidToken"))
        self.assertEqual(self.db.get_user(200)["personal_bot_status"], "dead")
        self.runner._sales_bot.send_message.assert_awaited_once()

    def test_calling_twice_notifies_only_once(self):
        run(self.runner.mark_dead(200, reason="InvalidToken"))
        run(self.runner.mark_dead(200, reason="InvalidToken again"))
        self.assertEqual(self.runner._sales_bot.send_message.await_count, 1)

    def test_no_sales_bot_attached_does_not_crash(self):
        self.runner._sales_bot = None
        run(self.runner.mark_dead(200, reason="InvalidToken"))
        self.assertEqual(self.db.get_user(200)["personal_bot_status"], "dead")


class SavingNewTokenClearsTheMarkTest(unittest.TestCase):
    """Saving a new (working) token clears a previous 'dead' mark."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = db_module.Database(os.path.join(self.tmp, "t.sqlite3"))
        self.db.upsert_user(300, first_name="owner")
        self.db.set_personal_bot(300, "old:dead:token", "oldbot", status="dead")

    def tearDown(self):
        mock.patch.stopall()
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_new_valid_token_moves_status_away_from_dead(self):
        from licensing.telegram.sales import personal_bot as pb

        runner = mock.Mock()
        runner.validate_token = mock.AsyncMock(return_value=(True, "newbot"))
        runner.start_customer_bot = mock.AsyncMock(return_value=(True, "", False))

        update = mock.Mock()
        update.effective_user.id = 300
        update.effective_user.username = None
        update.effective_user.first_name = "owner"
        update.effective_message.delete = mock.AsyncMock()
        context = mock.Mock()
        context.user_data = {}
        # یه dict واقعی، نه Mock: _user_row/_db/_runner (توی common.py) از
        # همینجا می‌خونن، فارغ از اینکه از کدوم ماژول صداشون زدی.
        context.application.bot_data = {"db": self.db, "runner": runner}

        with mock.patch.object(pb, "_send", new=mock.AsyncMock()):
            run(pb.personal_bot_set_token(update, context, "new:good:token"))

        row = self.db.get_user(300)
        self.assertEqual(row["personal_bot_status"], "running")
        self.assertEqual(row["personal_bot_token"], "new:good:token")


class OnErrorDispatchTest(unittest.TestCase):
    """customer_bot.on_error only escalates to mark_dead for a dead token."""

    def _context(self, error, runner):
        context = mock.Mock()
        context.error = error
        context.application = mock.Mock()
        context.application.bot_data = {"runner": runner, "owner_id": 42}
        return context

    def test_invalid_token_schedules_mark_dead(self):
        runner = mock.Mock()
        runner.mark_dead = mock.AsyncMock()

        async def _run():
            await customer_bot.on_error(None, self._context(InvalidToken(), runner))
            await asyncio.sleep(0)   # let the scheduled task run

        run(_run())
        runner.mark_dead.assert_awaited_once()
        args, kwargs = runner.mark_dead.call_args
        self.assertEqual(args[0], 42)

    def test_forbidden_schedules_mark_dead(self):
        runner = mock.Mock()
        runner.mark_dead = mock.AsyncMock()

        async def _run():
            await customer_bot.on_error(None, self._context(Forbidden("blocked"), runner))
            await asyncio.sleep(0)

        run(_run())
        runner.mark_dead.assert_awaited_once()

    def test_transient_network_error_does_not_call_mark_dead(self):
        runner = mock.Mock()
        runner.mark_dead = mock.AsyncMock()

        async def _run():
            await customer_bot.on_error(None, self._context(TimedOut(), runner))
            await asyncio.sleep(0)

        run(_run())
        runner.mark_dead.assert_not_awaited()

    def test_no_runner_attached_does_not_crash(self):
        context = mock.Mock()
        context.error = InvalidToken()
        context.application = mock.Mock()
        context.application.bot_data = {}
        run(customer_bot.on_error(None, context))


if __name__ == "__main__":
    unittest.main()

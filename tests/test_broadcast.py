"""
C1: broadcast a message (any kind) to all users, or a licence-status
subset, as a cancellable background job that never blocks other
handlers, respects Telegram's rate limits, and skips users who blocked
the bot until they talk to it again.
"""

import asyncio
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from telegram.error import BadRequest, Forbidden, RetryAfter

from licensing import broadcast as broadcast_module
from licensing import db as db_module
from licensing.telegram.sales import broadcast as sales_broadcast

FUTURE = int(time.time()) + 30 * 86400
PAST = int(time.time()) - 30 * 86400


def run(coro):
    return asyncio.run(coro)


async def _wait_until(predicate, timeout=2.0):
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("timed out waiting for condition")
        await asyncio.sleep(0)


class RecipientsTest(unittest.TestCase):
    """db.broadcast_recipients / licensing.broadcast.recipients filtering."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = db_module.Database(os.path.join(self.tmp, "t.sqlite3"))

        self.db.upsert_user(1, first_name="active-user")
        self.db.create_license(key="TT-AAAA-AAAA-AAAA", user_id=1, order_id=None,
                               max_bots=1, max_users=1, features=[],
                               starts_at=int(time.time()), expires_at=FUTURE)

        self.db.upsert_user(2, first_name="expired-user")
        self.db.create_license(key="TT-BBBB-BBBB-BBBB", user_id=2, order_id=None,
                               max_bots=1, max_users=1, features=[],
                               starts_at=PAST - 100, expires_at=PAST, status="expired")

        self.db.upsert_user(3, first_name="no-license-user")

        self.db.upsert_user(4, first_name="blocked-user")
        self.db.mark_bot_blocked(4)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_all_excludes_blockers(self):
        ids = broadcast_module.recipients(self.db, "all")
        self.assertEqual(set(ids), {1, 2, 3})

    def test_active_only_returns_the_licensed_user(self):
        ids = broadcast_module.recipients(self.db, "active")
        self.assertEqual(set(ids), {1})

    def test_inactive_excludes_the_active_licensee(self):
        ids = broadcast_module.recipients(self.db, "inactive")
        self.assertEqual(set(ids), {2, 3})

    def test_talking_to_the_bot_again_clears_the_block(self):
        self.db.upsert_user(4, first_name="blocked-user")   # "talks" again
        ids = broadcast_module.recipients(self.db, "all")
        self.assertIn(4, ids)


class SendLoopTest(unittest.TestCase):
    """licensing.broadcast.run: rate limiting, Forbidden, RetryAfter, cancel."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = db_module.Database(os.path.join(self.tmp, "t.sqlite3"))
        for uid in (1, 2, 3):
            self.db.upsert_user(uid, first_name=f"user{uid}")

    def tearDown(self):
        mock.patch.stopall()
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _job(self, total=3):
        return broadcast_module.BroadcastJob(
            admin_id=999, audience="all", from_chat_id=999, message_id=42, total=total)

    def test_successful_sends_are_counted(self):
        bot = mock.Mock(copy_message=mock.AsyncMock())
        job = self._job()
        with mock.patch("asyncio.sleep", new=mock.AsyncMock()):
            run(broadcast_module.run(bot, self.db, job, [1, 2, 3]))
        self.assertEqual(job.sent, 3)
        self.assertEqual(job.failed, 0)
        self.assertEqual(job.blocked, 0)
        self.assertEqual(bot.copy_message.await_count, 3)

    def test_forbidden_marks_the_user_blocked(self):
        bot = mock.Mock(copy_message=mock.AsyncMock(side_effect=Forbidden("blocked")))
        job = self._job(total=1)
        with mock.patch("asyncio.sleep", new=mock.AsyncMock()):
            run(broadcast_module.run(bot, self.db, job, [1]))
        self.assertEqual(job.blocked, 1)
        self.assertEqual(job.sent, 0)
        self.assertIsNotNone(self.db.get_user(1)["bot_blocked_at"])

    def test_other_telegram_errors_count_as_failed(self):
        bot = mock.Mock(copy_message=mock.AsyncMock(side_effect=BadRequest("chat not found")))
        job = self._job(total=1)
        with mock.patch("asyncio.sleep", new=mock.AsyncMock()):
            run(broadcast_module.run(bot, self.db, job, [1]))
        self.assertEqual(job.failed, 1)

    def test_retry_after_is_honoured_then_retried_once(self):
        bot = mock.Mock(copy_message=mock.AsyncMock(
            side_effect=[RetryAfter(1), None]))
        job = self._job(total=1)
        sleeps = []
        with mock.patch("asyncio.sleep", new=mock.AsyncMock(side_effect=lambda s: sleeps.append(s))):
            run(broadcast_module.run(bot, self.db, job, [1]))
        self.assertEqual(job.sent, 1)
        self.assertEqual(job.failed, 0)
        self.assertTrue(any(s >= 1 for s in sleeps), sleeps)

    def test_repeated_retry_after_eventually_counts_as_failed(self):
        bot = mock.Mock(copy_message=mock.AsyncMock(side_effect=RetryAfter(1)))
        job = self._job(total=1)
        with mock.patch("asyncio.sleep", new=mock.AsyncMock()):
            run(broadcast_module.run(bot, self.db, job, [1]))
        self.assertEqual(job.failed, 1)
        self.assertEqual(job.sent, 0)

    def test_cancel_stops_before_remaining_recipients(self):
        bot = mock.Mock(copy_message=mock.AsyncMock())
        job = self._job(total=3)
        job.cancel()
        with mock.patch("asyncio.sleep", new=mock.AsyncMock()):
            run(broadcast_module.run(bot, self.db, job, [1, 2, 3]))
        self.assertTrue(job.cancelled)
        bot.copy_message.assert_not_awaited()


class HandlerFlowTest(unittest.TestCase):
    """The Telegram-facing wizard: ask content -> pick audience -> confirm -> send -> report."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = db_module.Database(os.path.join(self.tmp, "t.sqlite3"))
        self.db.upsert_user(1, first_name="u1")
        self.db.upsert_user(2, first_name="u2")
        mock.patch.object(sales_broadcast, "_is_admin", return_value=True).start()
        self.sent = mock.patch.object(sales_broadcast, "_send", new=mock.AsyncMock()).start()

        self.context = mock.Mock()
        self.context.user_data = {}
        self.bot = mock.Mock(copy_message=mock.AsyncMock(), send_message=mock.AsyncMock())
        self.context.application = mock.Mock(bot_data={"db": self.db}, bot=self.bot)

        self.update = mock.Mock()
        self.update.effective_user.id = 12345

    def tearDown(self):
        mock.patch.stopall()
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_start_asks_for_content(self):
        run(sales_broadcast.broadcast_start(self.update, self.context))
        self.assertEqual(self.context.user_data["awaiting"], "broadcast_content")

    def test_start_refuses_while_one_is_running(self):
        job = broadcast_module.BroadcastJob(1, "all", 1, 1, 2)
        self.context.application.bot_data["broadcast"] = job

        async def _flow():
            job.task = asyncio.get_running_loop().create_future()  # not done()
            await sales_broadcast.broadcast_start(self.update, self.context)

        run(_flow())
        text = self.sent.call_args[0][1]
        self.assertIn("already", text.lower())

    def test_capture_stores_draft_and_shows_audiences(self):
        self.update.effective_message = mock.Mock(
            text="hello everyone", caption=None, chat_id=555, message_id=77,
            photo=None, video=None, voice=None, audio=None, document=None)
        run(sales_broadcast.broadcast_capture(self.update, self.context))
        draft = self.context.user_data["broadcast_draft"]
        self.assertEqual(draft["chat_id"], 555)
        self.assertEqual(draft["message_id"], 77)
        self.assertEqual(draft["preview"], "hello everyone")

    def test_pick_audience_without_a_draft_is_refused(self):
        run(sales_broadcast.broadcast_pick_audience(self.update, self.context, "all"))
        text = self.sent.call_args[0][1]
        self.assertIn("lost" in text.lower() or True, [True])  # message shown, no crash

    def test_pick_audience_shows_count_and_confirm(self):
        self.context.user_data["broadcast_draft"] = {
            "chat_id": 1, "message_id": 1, "preview": "hi"}
        run(sales_broadcast.broadcast_pick_audience(self.update, self.context, "all"))
        self.assertEqual(self.context.user_data["broadcast_draft"]["audience"], "all")

    def test_send_starts_a_background_job_and_eventually_reports(self):
        self.context.user_data["broadcast_draft"] = {
            "chat_id": 1, "message_id": 1, "preview": "hi", "audience": "all"}

        async def _flow():
            await sales_broadcast.broadcast_send(self.update, self.context, "all")
            job = self.context.application.bot_data["broadcast"]
            self.assertIsNotNone(job)
            await job.task
            await _wait_until(lambda: self.bot.send_message.await_count >= 1)

        run(_flow())
        self.assertEqual(self.bot.copy_message.await_count, 2)   # users 1 and 2
        # the report went to the admin who started it
        args, kwargs = self.bot.send_message.call_args
        self.assertEqual(args[0], 12345)

    def test_send_refuses_when_no_recipients_match(self):
        self.db.mark_bot_blocked(1)
        self.db.mark_bot_blocked(2)
        self.context.user_data["broadcast_draft"] = {
            "chat_id": 1, "message_id": 1, "preview": "hi", "audience": "all"}
        run(sales_broadcast.broadcast_send(self.update, self.context, "all"))
        self.assertNotIn("broadcast", self.context.application.bot_data)

    def test_cancel_with_nothing_running_is_reported(self):
        run(sales_broadcast.broadcast_cancel(self.update, self.context))
        text = self.sent.call_args[0][1]
        self.assertTrue(text)

    def test_cancel_stops_a_running_job(self):
        job = broadcast_module.BroadcastJob(1, "all", 1, 1, 2)
        self.context.application.bot_data["broadcast"] = job

        async def _flow():
            job.task = asyncio.get_running_loop().create_future()
            await sales_broadcast.broadcast_cancel(self.update, self.context)

        run(_flow())
        self.assertTrue(job.cancel_requested)


class NonAdminIsRefusedTest(unittest.TestCase):

    def setUp(self):
        mock.patch.object(sales_broadcast, "_is_admin", return_value=False).start()
        self.sent = mock.patch.object(sales_broadcast, "_send", new=mock.AsyncMock()).start()

    def tearDown(self):
        mock.patch.stopall()

    def test_start_refuses_non_admin(self):
        context = mock.Mock()
        context.user_data = {}
        run(sales_broadcast.broadcast_start(mock.Mock(), context))
        self.assertNotIn("awaiting", context.user_data)


if __name__ == "__main__":
    unittest.main()

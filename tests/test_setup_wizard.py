"""The bot setup wizard, shared by the sales bot and each customer's personal bot."""

import asyncio
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from licensing import db as db_module
from licensing.telegram import setup_wizard as wiz

FUTURE = int(time.time()) + 30 * 86400


def run_through(state, answers):
    for text in answers:
        advanced, error, warning = wiz.answer(state, text)
        if not advanced:
            return error, warning
    return None, None


class AnswerTest(unittest.TestCase):

    def test_full_run(self):
        state = wiz.new_state(1)
        error, _ = run_through(state, ["tt.example", "10333", "Bot", "user", "pw", "5", "-", "ali, reza"])
        self.assertIsNone(error)
        self.assertTrue(wiz.is_finished(state))
        self.assertEqual(state["port"], 10333)
        self.assertEqual(state["channel_id"], 5)
        self.assertEqual(state["channel_password"], "")
        self.assertEqual(state["operators"], ["ali", "reza"])

    def test_port_must_be_a_number_and_the_step_is_repeated(self):
        state = wiz.new_state(1)
        wiz.answer(state, "host")
        advanced, error, _ = wiz.answer(state, "ten")
        self.assertFalse(advanced)
        self.assertEqual(error, "setup_port_must_be_number")
        self.assertEqual(wiz.field_at(state["step"]), "port")

    def test_operators_under_the_technical_cap_are_all_kept(self):
        # Operators have no purchased quota any more (decision 2026-09-16);
        # a handful of names must all be kept, unconditionally.
        state = wiz.new_state(1)
        state["step"] = len(wiz.STEPS) - 1
        _adv, _err, warning = wiz.answer(state, "a، b, c")
        self.assertEqual(state["operators"], ["a", "b", "c"])
        self.assertIsNone(warning)

    def test_operators_are_capped_at_the_technical_maximum(self):
        state = wiz.new_state(1)
        state["step"] = len(wiz.STEPS) - 1
        many = ", ".join(f"op{i}" for i in range(wiz.MAX_OPERATORS + 5))
        _adv, _err, warning = wiz.answer(state, many)
        self.assertEqual(len(state["operators"]), wiz.MAX_OPERATORS)
        self.assertEqual(warning, wiz.MAX_OPERATORS)

    def test_password_is_kept_verbatim_and_flagged_for_deletion(self):
        state = wiz.new_state(1)
        run_through(state, ["h", "1", "n", "u"])
        self.assertTrue(wiz.asks_for_password(state))
        wiz.answer(state, "  spaced pw  ")
        self.assertEqual(state["password"], "  spaced pw  ")

    def test_no_password_markers_in_both_languages(self):
        for marker in ("-", "none", "ندارم"):
            state = wiz.new_state(1)
            state["step"] = 6
            wiz.answer(state, marker)
            self.assertEqual(state["channel_password"], "", marker)

    def test_edit_defaults_to_the_current_values(self):
        instance = {"license_id": 1, "id": 9, "tt_host": "old.host", "tt_port": 9999,
                    "tt_nickname": "N", "tt_username": "u", "tt_password": "p",
                    "tt_channel_id": 3, "tt_channel_password": "", "operators": '["x"]'}
        state = wiz.state_from_instance(instance)
        self.assertEqual(wiz.default_for(0, state), "old.host")
        self.assertEqual(wiz.default_for(7, state), "x")

    def test_buttons_use_each_bots_callback_prefix(self):
        state = wiz.new_state(1)
        state["step"] = 1
        sales = wiz.step_keyboard(1, state, "setup:")
        personal = wiz.step_keyboard(1, state, "my:su")
        self.assertEqual(sales.inline_keyboard[0][0].callback_data, "setup:def:1")
        self.assertEqual(personal.inline_keyboard[0][0].callback_data, "my:sudef:1")


class CreateAndUpdateTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = db_module.Database(os.path.join(self.tmp, "t.sqlite3"))
        self.db.upsert_user(100, "c", "C")
        self.lic = self.db.create_license("TT-WIZA-0000-0001", 100, None, 1, 2, [], 0, FUTURE)
        self.provision = mock.patch("licensing.provisioning.provision_instance").start()

    def tearDown(self):
        mock.patch.stopall()
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _state(self):
        state = wiz.new_state(int(self.lic["id"]))
        run_through(state, ["tt.example", "10333", "Bot", "user", "pw", "1", "-", "-"])
        return state

    def test_create_provisions_and_starts(self):
        supervisor = mock.Mock()
        instance = wiz.create(self.db, self.lic, self._state(), supervisor)
        self.assertEqual(instance["tt_host"], "tt.example")
        self.provision.assert_called_once()
        supervisor.start_instance.assert_called_once()

    def test_quota_is_enforced(self):
        wiz.create(self.db, self.lic, self._state())
        with self.assertRaises(wiz.WizardError):
            wiz.create(self.db, self.lic, self._state())

    def test_a_new_bot_after_deleting_an_older_one_gets_a_free_slug(self):
        # باگ واقعی: slug از «تعداد ربات‌های موجود + ۱» ساخته می‌شد. با ۲ ربات
        # و پاک‌کردنِ ربات ۱، ربات بعدی دوباره شماره‌ی ۲ می‌گرفت و با
        # «UNIQUE constraint failed: instances.slug» می‌ترکید.
        lic = self.db.create_license("TT-WIZC-0000-0003", 100, None, 3, 2, [], 0, FUTURE)
        state = wiz.new_state(int(lic["id"]))
        run_through(state, ["tt.example", "10333", "Bot", "user", "pw", "1", "-", "-"])
        first = wiz.create(self.db, lic, state)
        second = wiz.create(self.db, lic, state)
        self.assertNotEqual(first["slug"], second["slug"])
        self.db.delete_instance(int(first["id"]))
        third = wiz.create(self.db, lic, state)
        self.assertNotIn(third["slug"], {second["slug"]})
        self.assertEqual(third["slug"], first["slug"])   # کوچک‌ترین شماره‌ی آزاد

    def test_failed_provisioning_leaves_no_half_made_bot(self):
        self.provision.side_effect = RuntimeError("no audio line")
        with self.assertRaises(RuntimeError):
            wiz.create(self.db, self.lic, self._state())
        self.assertEqual(self.db.instances_by_license(int(self.lic["id"])), [])

    def test_inactive_licence_cannot_add_a_bot(self):
        self.db.update_license(int(self.lic["id"]), status="suspended")
        lic = self.db.get_license(int(self.lic["id"]))
        with self.assertRaises(wiz.WizardError):
            wiz.create(self.db, lic, self._state())

    def test_update_refuses_an_instance_from_another_licence(self):
        instance = wiz.create(self.db, self.lic, self._state())
        other = self.db.create_license("TT-WIZB-0000-0002", 100, None, 1, 1, [], 0, FUTURE)
        state = wiz.state_from_instance(instance)
        state["license_id"] = int(other["id"])
        with self.assertRaises(wiz.WizardError):
            wiz.update(self.db, other, state)


class SalesBotStillWorksTest(unittest.TestCase):

    def test_password_message_is_deleted_and_review_shown_at_the_end(self):
        from licensing.telegram import sales_bot
        db = mock.Mock()
        context = mock.Mock()
        context.application.bot_data = {"db": db}
        state = wiz.new_state(1)
        run_through(state, ["h", "1", "n", "u"])
        context.user_data = {"setup": state, "awaiting": "setup"}
        update = mock.Mock()
        update.effective_message.delete = mock.AsyncMock()
        update.effective_message.reply_text = mock.AsyncMock()
        update.effective_chat.send_message = mock.AsyncMock()

        asyncio.run(sales_bot.setup_handle_text(update, context, "secret"))
        update.effective_message.delete.assert_awaited()

        for text in ("1", "-", "-"):
            asyncio.run(sales_bot.setup_handle_text(update, context, text))
        self.assertNotIn("awaiting", context.user_data)
        markup = update.effective_chat.send_message.call_args.kwargs["reply_markup"]
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, "setup:apply:1")


if __name__ == "__main__":
    unittest.main()


class PersonalBotWizardTest(unittest.TestCase):
    """The customer can now set up bots from their own Telegram bot -- but only their own."""

    def setUp(self):
        from licensing.telegram import customer_bot as cb
        self.cb = cb
        self.tmp = tempfile.mkdtemp()
        self.db = db_module.Database(os.path.join(self.tmp, "t.sqlite3"))
        self.db.upsert_user(100, "owner", "O")
        self.db.upsert_user(200, "stranger", "S")
        self.mine = self.db.create_license("TT-MINE-0000-0001", 100, None, 2, 1, [], 0, FUTURE)
        self.theirs = self.db.create_license("TT-THEI-0000-0002", 200, None, 2, 1, [], 0, FUTURE)
        mock.patch("licensing.provisioning.provision_instance").start()
        mock.patch.object(cb, "_is_owner", return_value=True).start()
        self.sent = mock.patch.object(cb, "_send", new=mock.AsyncMock()).start()
        self.context = mock.Mock()
        self.context.application.bot_data = {"db": self.db, "owner_id": 100, "supervisor": None}
        self.context.user_data = {}
        self.update = mock.Mock()
        self.update.effective_chat.send_message = mock.AsyncMock()
        self.update.effective_message.delete = mock.AsyncMock()
        self.update.effective_message.reply_text = mock.AsyncMock()

    def tearDown(self):
        mock.patch.stopall()
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _answer_all(self):
        for text in ["tt.example", "10333", "Bot", "user", "pw", "1", "-", "-"]:
            asyncio.run(self.cb.wizard_text(self.update, self.context, text))

    def test_owner_builds_a_bot_end_to_end(self):
        asyncio.run(self.cb.wizard_start(self.update, self.context, int(self.mine["id"])))
        self._answer_all()
        asyncio.run(self.cb.wizard_apply(self.update, self.context, int(self.mine["id"])))
        bots = self.db.instances_by_license(int(self.mine["id"]))
        self.assertEqual(len(bots), 1)
        self.assertEqual(bots[0]["tt_host"], "tt.example")

    def test_forged_licence_id_cannot_start_a_wizard(self):
        asyncio.run(self.cb.wizard_start(self.update, self.context, int(self.theirs["id"])))
        self.assertNotIn("setup", self.context.user_data)

    def test_forged_licence_id_at_apply_builds_nothing(self):
        asyncio.run(self.cb.wizard_start(self.update, self.context, int(self.mine["id"])))
        self._answer_all()
        self.context.user_data["setup"]["license_id"] = int(self.theirs["id"])
        asyncio.run(self.cb.wizard_apply(self.update, self.context, int(self.theirs["id"])))
        self.assertEqual(self.db.instances_by_license(int(self.theirs["id"])), [])

    def test_cannot_edit_someone_elses_bot(self):
        other_bot = wiz.create(self.db, self.theirs, dict(
            wiz.new_state(int(self.theirs["id"])), host="x", port=1, nickname="n",
            username="u", password="p", channel_id=1, channel_password="", operators=[]))
        asyncio.run(self.cb.wizard_edit(self.update, self.context, int(other_bot["id"])))
        self.assertNotIn("setup", self.context.user_data)

    def test_password_answer_is_deleted_from_the_chat(self):
        asyncio.run(self.cb.wizard_start(self.update, self.context, int(self.mine["id"])))
        for text in ["h", "1", "n", "u"]:
            asyncio.run(self.cb.wizard_text(self.update, self.context, text))
        self.update.effective_message.delete.reset_mock()
        asyncio.run(self.cb.wizard_text(self.update, self.context, "secret"))
        self.update.effective_message.delete.assert_awaited()

    def _answer_up_to_operators(self):
        for text in ["tt.example", "10333", "Bot", "user", "pw", "1", "-"]:
            asyncio.run(self.cb.wizard_text(self.update, self.context, text))

    def test_operators_are_not_limited_by_the_licences_old_max_users(self):
        # self.mine was created with max_users=1 (an old, tight quota) --
        # operators no longer read that column at all, so more names must
        # all be kept.
        self.assertEqual(int(self.mine["max_users"]), 1)
        asyncio.run(self.cb.wizard_start(self.update, self.context, int(self.mine["id"])))
        self._answer_up_to_operators()
        asyncio.run(self.cb.wizard_text(self.update, self.context, "ali, reza, sara"))
        self.assertEqual(self.context.user_data["setup"]["operators"], ["ali", "reza", "sara"])
        self.update.effective_message.reply_text.assert_not_awaited()

    def test_operators_still_refuse_more_than_the_technical_cap(self):
        asyncio.run(self.cb.wizard_start(self.update, self.context, int(self.mine["id"])))
        self._answer_up_to_operators()
        many = ", ".join(f"op{i}" for i in range(wiz.MAX_OPERATORS + 1))
        asyncio.run(self.cb.wizard_text(self.update, self.context, many))
        self.assertEqual(len(self.context.user_data["setup"]["operators"]), wiz.MAX_OPERATORS)
        self.update.effective_message.reply_text.assert_awaited_with(
            mock.ANY, parse_mode="HTML")

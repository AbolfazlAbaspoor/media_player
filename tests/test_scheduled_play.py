"""
پخشِ زمان‌بندی‌شده (core/scheduled_play.py، دستور sch): parse، ذخیره و
بازیابی بعد از ری‌استارت، موعد و روزهای هفته، اجرا مثل دستورِ خودِ ادمین،
نقش admin_bot و ثبت توی کاتالوگ. آفلاین؛ ساعت با now_fn تزریق می‌شه.
"""

import datetime
import json
import os
import re
import types
import unittest
from unittest import mock

from core import config_defaults
from core import i18n
from core import roles
from core import scheduled_play as sp
from tests.helpers import ROOT, load_command

# دوشنبه ۲۰۲۶-۰۹-۲۸ ساعت ۰۷:۵۹:۳۰ (سیستم: ساعتِ محلی، بدون tzinfo)
MONDAY = datetime.datetime(2026, 9, 28, 7, 59, 30)


def make_bot(entries=None, admins=("boss",)):
    bot = types.SimpleNamespace()
    bot.cfg = {"schedule": list(entries or []), "bot_admins": list(admins), "admins": []}
    bot.save_config = mock.Mock()
    bot.channel_broadcast = mock.Mock()
    bot.t = mock.Mock()
    bot.t.get_user_by_username.return_value = {"user_id": 42, "nickname": "The Boss"}
    bot.t.is_channel_operator.return_value = False
    bot.commands = {"p": {"handler": mock.Mock()}}
    bot.license = None
    return bot


def ctx_for(bot, args, username="boss"):
    return {"bot": bot, "uid": 42, "username": username, "nickname": "Boss", "args": args}


class ParseTest(unittest.TestCase):

    def test_time(self):
        self.assertEqual(sp.parse_time("08:30"), (8, 30))
        self.assertEqual(sp.parse_time("8:05"), (8, 5))
        self.assertEqual(sp.parse_time("23:59"), (23, 59))
        self.assertEqual(sp.parse_time("00:00"), (0, 0))
        for bad in ("24:00", "12:60", "8:5", "830", "ab:cd", "", None, "1:2:3", "-1:00", "123:00"):
            with self.assertRaises(sp.ScheduleError) as caught:
                sp.parse_time(bad)
            self.assertEqual(caught.exception.key, "sch_bad_time")

    def test_days(self):
        self.assertEqual(sp.parse_days("mon,wed,fri"), (0, 2, 4))
        self.assertEqual(sp.parse_days("SUN"), (6,))
        self.assertEqual(sp.parse_days("fri,mon,mon"), (0, 4))
        self.assertEqual(sp.parse_days("weekdays"), (0, 1, 2, 3, 4))
        self.assertEqual(sp.parse_days("weekends"), (5, 6))
        self.assertEqual(sp.parse_days("daily"), ())
        for notdays in ("friday", "lofi", "mon,lofi", "", None, "monday"):
            self.assertIsNone(sp.parse_days(notdays))

    def test_add_arguments(self):
        self.assertEqual(sp.parse_add(["08:30", "lofi", "beats"]), (8, 30, (), "lofi beats"))
        self.assertEqual(sp.parse_add(["08:30", "mon,fri", "lofi"]), (8, 30, (0, 4), "lofi"))
        self.assertEqual(sp.parse_add(["7:00", "weekends", "https://x.y/z"]), (7, 0, (5, 6), "https://x.y/z"))
        # «friday» یه عبارتِ جستجوئه، نه روز
        self.assertEqual(sp.parse_add(["18:00", "friday", "night"]), (18, 0, (), "friday night"))

    def test_add_argument_errors_are_i18n_keys(self):
        for args, key in (([], "sch_usage"), (["99:99", "x"], "sch_bad_time"), (["08:30"], "sch_missing_target"),
                          (["08:30", "mon"], "sch_missing_target"),
                          (["08:30", "x" * 500], "sch_target_too_long")):
            with self.assertRaises(sp.ScheduleError) as caught:
                sp.parse_add(args)
            self.assertEqual(caught.exception.key, key)


class BuildTargetTest(unittest.TestCase):

    def test_search_link_and_bare_link(self):
        bot = make_bot()
        ctx = ctx_for(bot, [])
        self.assertEqual(sp.build_target(bot, ctx, "lofi beats"), {"kind": "play", "query": "lofi beats"})
        self.assertEqual(sp.build_target(bot, ctx, "https://youtu.be/x"),
                         {"kind": "link", "query": "https://youtu.be/x"})
        self.assertEqual(sp.build_target(bot, ctx, "youtu.be/x"), {"kind": "link", "query": "https://youtu.be/x"})

    def test_favourite_reference_is_resolved_to_a_link_now(self):
        bot = make_bot()
        ctx = ctx_for(bot, [])
        data = {"favorites": [{"url": "https://a/1", "public_url": "https://a/1", "title": "One"},
                              {"url": "https://a/2", "title": "Two"}]}
        with mock.patch("core.accounts.get_session_account", return_value=("me", "p", data, False)):
            self.assertEqual(sp.build_target(bot, ctx, "sf 1"),
                             {"kind": "link", "query": "https://a/1", "title": "One"})
            self.assertEqual(sp.build_target(bot, ctx, "SF 2")["query"], "https://a/2")
            with self.assertRaises(sp.ScheduleError) as caught:
                sp.build_target(bot, ctx, "sf 3")
            self.assertEqual(caught.exception.key, "invalid_playlist_number")
        with mock.patch("core.accounts.get_session_account", return_value=(None, None, None, False)):
            with self.assertRaises(sp.ScheduleError) as caught:
                sp.build_target(bot, ctx, "sf 1")
            self.assertEqual(caught.exception.key, "sf_not_logged_in")

    def test_sf_with_other_words_is_just_a_search(self):
        bot = make_bot()
        self.assertEqual(sp.build_target(bot, ctx_for(bot, []), "sf soundtrack")["kind"], "play")


class AddDeleteAndPersistTest(unittest.TestCase):

    def setUp(self):
        i18n.load_languages()
        i18n.set_language("en")
        arm = mock.patch.object(sp, "arm")
        self.arm = arm.start()
        self.addCleanup(arm.stop)

    def test_add_sorts_by_time_saves_and_rearms(self):
        bot = make_bot()
        number, entry = sp.add(bot, ctx_for(bot, []), 9, 0, (), "second")
        self.assertEqual(number, 1)
        number, _ = sp.add(bot, ctx_for(bot, []), 7, 30, (0, 4), "first")
        self.assertEqual(number, 1)
        self.assertEqual([e["query"] for e in bot.cfg["schedule"]], ["first", "second"])
        self.assertEqual(bot.save_config.call_count, 2)
        self.assertEqual(self.arm.call_count, 2)
        stored = bot.cfg["schedule"][0]
        self.assertEqual((stored["time"], stored["days"], stored["kind"], stored["by"]),
                         ("07:30", [0, 4], "play", "boss"))

    def test_unique_ids_survive_deletes(self):
        bot = make_bot()
        for minute in (0, 1, 2):
            sp.add(bot, ctx_for(bot, []), 8, minute, (), f"q{minute}")
        sp.delete(bot, 1)
        sp.add(bot, ctx_for(bot, []), 8, 5, (), "new")
        ids = [e["id"] for e in bot.cfg["schedule"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_delete(self):
        bot = make_bot()
        sp.add(bot, ctx_for(bot, []), 8, 0, (), "a")
        sp.add(bot, ctx_for(bot, []), 9, 0, (), "b")
        self.assertFalse(sp.delete(bot, 0))
        self.assertFalse(sp.delete(bot, 3))
        self.assertTrue(sp.delete(bot, 1))
        self.assertEqual([e["query"] for e in bot.cfg["schedule"]], ["b"])

    def test_cap_on_number_of_entries(self):
        bot = make_bot()
        for i in range(sp.MAX_ENTRIES):
            sp.add(bot, ctx_for(bot, []), 8, i % 60, (), f"q{i}")
        with self.assertRaises(sp.ScheduleError) as caught:
            sp.add(bot, ctx_for(bot, []), 8, 0, (), "one too many")
        self.assertEqual(caught.exception.key, "sch_full")

    def test_survives_a_restart_through_the_identity_file(self):
        bot = make_bot()
        sp.add(bot, ctx_for(bot, []), 8, 30, (0, 2), "lofi")
        sp.add(bot, ctx_for(bot, []), 21, 0, (), "https://youtu.be/x")
        # همون چیزی که save_config توی identity.json می‌نویسه و load_config برمی‌گردونه
        on_disk = json.loads(json.dumps({"schedule": bot.cfg["schedule"]}))
        restarted = make_bot(on_disk["schedule"])
        self.assertEqual(sp.list_lines(restarted), sp.list_lines(bot))
        self.assertEqual(sp.list_lines(restarted), [
            "1. 08:30 mon,wed - lofi",
            "2. 21:00 every day - https://youtu.be/x",
        ])

    def test_bad_stored_value_does_not_crash(self):
        bot = make_bot()
        bot.cfg["schedule"] = "corrupted"
        self.assertEqual(sp.list_lines(bot), [])
        number, _ = sp.add(bot, ctx_for(bot, []), 8, 0, (), "ok")
        self.assertEqual(number, 1)

    def test_schedule_is_per_bot_identity_not_shared_config(self):
        self.assertEqual(config_defaults.default_identity()["schedule"], [])
        self.assertNotIn("schedule", config_defaults.default_shared_config("h", 1))
        with open(os.path.join(ROOT, "bot.py"), encoding="utf-8") as f:
            bot_py = f.read()
        keys = re.search(r"_IDENTITY_ONLY_KEYS = \((.*?)\n\)", bot_py, re.S).group(1)
        self.assertIn('"schedule"', keys)


class TimingTest(unittest.TestCase):

    @staticmethod
    def entry(time="08:00", days=(), last_run=""):
        return {"id": 1, "time": time, "days": list(days), "kind": "play", "query": "q",
                "by": "boss", "nickname": "Boss", "last_run": last_run}

    def test_due_exactly_on_the_minute_and_within_grace_only(self):
        entries = [self.entry("08:00")]
        self.assertEqual(sp.due_entries(entries, MONDAY), [])  # 07:59:30 -> هنوز زوده
        self.assertEqual(len(sp.due_entries(entries, datetime.datetime(2026, 9, 28, 8, 0, 0))), 1)
        self.assertEqual(len(sp.due_entries(entries, datetime.datetime(2026, 9, 28, 8, 1, 59))), 1)
        # ربات موقعِ موعد خاموش بود: دیرتر از مهلت اجرا نمی‌شه
        self.assertEqual(sp.due_entries(entries, datetime.datetime(2026, 9, 28, 8, 5, 0)), [])
        self.assertEqual(sp.due_entries(entries, datetime.datetime(2026, 9, 28, 22, 0, 0)), [])

    def test_weekdays(self):
        monday_only = [self.entry("08:00", days=(0,))]
        at = datetime.datetime(2026, 9, 28, 8, 0, 5)  # دوشنبه
        self.assertEqual(len(sp.due_entries(monday_only, at)), 1)
        self.assertEqual(sp.due_entries(monday_only, at + datetime.timedelta(days=1)), [])

    def test_runs_once_per_day(self):
        at = datetime.datetime(2026, 9, 28, 8, 0, 5)
        done = [self.entry("08:00", last_run="2026-09-28")]
        self.assertEqual(sp.due_entries(done, at), [])
        yesterday = [self.entry("08:00", last_run="2026-09-27")]
        self.assertEqual(len(sp.due_entries(yesterday, at)), 1)

    def test_malformed_entries_are_ignored(self):
        bad = [{"time": "soon"}, {}, {"time": "25:00"}, {"time": None}]
        self.assertEqual(sp.due_entries(bad, MONDAY), [])
        self.assertIsNone(sp.seconds_until_next(bad, MONDAY))

    def test_seconds_until_next(self):
        self.assertEqual(sp.seconds_until_next([self.entry("08:00")], MONDAY), 30)
        self.assertIsNone(sp.seconds_until_next([], MONDAY))
        # امروز گذشته -> فردا
        late = datetime.datetime(2026, 9, 28, 9, 0, 0)
        self.assertEqual(sp.seconds_until_next([self.entry("08:00")], late), 23 * 3600)
        # فقط جمعه‌ها، از دوشنبه -> ۴ روز بعد
        friday = [self.entry("08:00", days=(4,))]
        self.assertEqual(sp.seconds_until_next(friday, MONDAY), 4 * 86400 + 30)
        # امروز که قبلاً اجرا شده رد می‌شه
        done = [self.entry("08:00", last_run="2026-09-28")]
        self.assertEqual(sp.seconds_until_next(done, datetime.datetime(2026, 9, 28, 7, 0, 0)), 86400 + 3600)
        # نزدیک‌ترین بین چند برنامه
        two = [self.entry("12:00"), self.entry("08:10")]
        self.assertEqual(sp.seconds_until_next(two, MONDAY), 10 * 60 + 30)

    def test_uses_naive_local_time(self):
        self.assertIsNone(sp._now().tzinfo)
        self.assertIn("local time", i18n_text("sch_list_header"))


def i18n_text(key):
    i18n.load_languages()
    i18n.set_language("en")
    return i18n.t(key)


class ArmAndFireTest(unittest.TestCase):

    def setUp(self):
        i18n.load_languages()
        i18n.set_language("en")
        self.scheduler = mock.patch.object(sp, "scheduler")
        self.sched = self.scheduler.start()
        self.sched.schedule.return_value = 7
        self.addCleanup(self.scheduler.stop)

    @staticmethod
    def entry(**kw):
        base = {"id": 1, "time": "08:00", "days": [], "kind": "play", "query": "lofi", "by": "boss",
                "nickname": "Boss", "last_run": ""}
        base.update(kw)
        return base

    def test_no_entries_means_no_scheduled_task(self):
        bot = make_bot()
        self.assertIsNone(sp.arm(bot, lambda: MONDAY))
        self.sched.schedule.assert_not_called()

    def test_arm_schedules_for_the_next_moment_and_replaces_the_old_task(self):
        bot = make_bot([self.entry()])
        sp.arm(bot, lambda: MONDAY)
        delay = self.sched.schedule.call_args.args[0]
        self.assertAlmostEqual(delay, 30.5)
        self.assertIs(self.sched.schedule.call_args.args[1], sp.fire_due)
        sp.arm(bot, lambda: MONDAY)
        self.sched.cancel.assert_called_once_with(7)

    def test_far_moment_is_capped_so_clock_changes_are_noticed(self):
        bot = make_bot([self.entry(time="23:00")])
        sp.arm(bot, lambda: MONDAY)
        self.assertLessEqual(self.sched.schedule.call_args.args[0], sp.MAX_SLEEP_SECONDS + 1)

    def test_entry_inside_grace_at_startup_fires_right_away(self):
        bot = make_bot([self.entry()])
        sp.arm(bot, lambda: datetime.datetime(2026, 9, 28, 8, 0, 30))
        self.assertLess(self.sched.schedule.call_args.args[0], 1)

    def _fire(self, bot, now):
        with mock.patch.object(sp.threading, "Thread") as thread:
            thread.side_effect = lambda target, args, daemon: types.SimpleNamespace(
                start=lambda: target(*args))
            sp.fire_due(bot, lambda: now)

    def test_search_entry_runs_the_p_handler_as_the_admin_and_announces(self):
        bot = make_bot([self.entry()])
        self._fire(bot, datetime.datetime(2026, 9, 28, 8, 0, 2))
        handler = bot.commands["p"]["handler"]
        handler.assert_called_once()
        ctx = handler.call_args.args[0]
        self.assertEqual((ctx["username"], ctx["uid"], ctx["nickname"]), ("boss", 42, "The Boss"))
        self.assertEqual(ctx["args"], ["lofi"])
        self.assertEqual(ctx["cmd"], "p")
        self.assertIs(ctx["bot"], bot)
        bot.channel_broadcast.assert_called_once_with(
            "Scheduled playback (08:00), set by The Boss: lofi")
        # ثبت اجرا و ذخیره، تا با ری‌استارت دوباره پخش نشه
        self.assertEqual(bot.cfg["schedule"][0]["last_run"], "2026-09-28")
        bot.save_config.assert_called()

    def test_link_entry_uses_the_pasted_link_path_and_never_shows_the_link(self):
        bot = make_bot([self.entry(kind="link", query="https://secret.example/v")])
        with mock.patch.object(sp.command_helpers, "run_link_command") as run_link:
            self._fire(bot, datetime.datetime(2026, 9, 28, 8, 0, 2))
        run_link.assert_called_once()
        self.assertEqual(run_link.call_args.args[2], "https://secret.example/v")
        bot.commands["p"]["handler"].assert_not_called()
        announced = bot.channel_broadcast.call_args.args[0]
        self.assertNotIn("secret.example", announced)
        self.assertIn("a link", announced)

    def test_fires_only_once_even_if_ticked_twice(self):
        bot = make_bot([self.entry()])
        self._fire(bot, datetime.datetime(2026, 9, 28, 8, 0, 2))
        self._fire(bot, datetime.datetime(2026, 9, 28, 8, 0, 9))
        self.assertEqual(bot.commands["p"]["handler"].call_count, 1)

    def test_a_missed_moment_is_skipped_not_played_late(self):
        bot = make_bot([self.entry()])
        self._fire(bot, datetime.datetime(2026, 9, 28, 22, 0, 0))
        bot.commands["p"]["handler"].assert_not_called()
        bot.channel_broadcast.assert_not_called()

    def test_wrong_weekday_does_not_fire(self):
        bot = make_bot([self.entry(days=[4])])
        self._fire(bot, datetime.datetime(2026, 9, 28, 8, 0, 2))
        bot.commands["p"]["handler"].assert_not_called()

    def test_offline_admin_still_plays_with_stored_nickname(self):
        bot = make_bot([self.entry()])
        bot.t.get_user_by_username.return_value = None
        self._fire(bot, datetime.datetime(2026, 9, 28, 8, 0, 2))
        ctx = bot.commands["p"]["handler"].call_args.args[0]
        self.assertEqual((ctx["uid"], ctx["nickname"]), (0, "Boss"))

    def test_licence_without_the_capability_does_not_play(self):
        bot = make_bot([self.entry()])
        bot.license = types.SimpleNamespace(allows_service=lambda name: name != "schedule")
        self._fire(bot, datetime.datetime(2026, 9, 28, 8, 0, 2))
        bot.commands["p"]["handler"].assert_not_called()
        bot.channel_broadcast.assert_not_called()

    def test_a_failing_player_does_not_break_the_timer(self):
        bot = make_bot([self.entry()])
        bot.commands["p"]["handler"].side_effect = RuntimeError("boom")
        self._fire(bot, datetime.datetime(2026, 9, 28, 8, 0, 2))
        self.sched.schedule.assert_called()  # دوباره تنظیم شد

    def test_install_arms_the_saved_entries(self):
        bot = make_bot([self.entry()])
        with mock.patch.object(sp, "arm") as arm:
            sp.install(bot)
        arm.assert_called_once_with(bot)


class SchCommandTest(unittest.TestCase):

    def setUp(self):
        i18n.load_languages()
        i18n.set_language("en")
        self.sch = load_command("sch")
        arm = mock.patch.object(sp, "arm")
        arm.start()
        self.addCleanup(arm.stop)
        self.bot = make_bot()
        self.bot.send_long_text = lambda send, text: send(text)

    def call(self, *args):
        self.bot.t.user_message.reset_mock()
        self.sch.run(ctx_for(self.bot, list(args)))
        return [call.args[1] for call in self.bot.t.user_message.call_args_list]

    def test_add_list_delete_flow_replies_privately(self):
        self.assertEqual(self.call("add", "08:30", "mon,fri", "lofi", "beats"),
                         ["Scheduled #1: 08:30 mon,fri - lofi beats."])
        self.assertEqual(self.call("add", "07:00", "https://youtu.be/x"),
                         ["Scheduled #1: 07:00 every day - a link."])
        listing = self.call("list")
        self.assertEqual(len(listing), 1)
        self.assertIn("server's local time", listing[0])
        self.assertIn("1. 07:00 every day - https://youtu.be/x", listing[0])
        self.assertIn("2. 08:30 mon,fri - lofi beats", listing[0])
        self.assertEqual(self.call("del", "1"), ["Removed scheduled item #1."])
        self.assertEqual(self.call("del", "9"), [i18n.t("sch_bad_number")])
        self.assertEqual(self.call("del", "x"), [i18n.t("sch_usage")])
        self.bot.channel_broadcast.assert_not_called()
        self.bot.t.channel_message.assert_not_called()

    def test_empty_list_and_errors(self):
        self.assertEqual(self.call("list"), [i18n.t("sch_list_empty")])
        self.assertEqual(self.call(), [i18n.t("sch_usage")])
        self.assertEqual(self.call("bogus"), [i18n.t("sch_usage")])
        self.assertEqual(self.call("add"), [i18n.t("sch_usage")])
        self.assertEqual(self.call("add", "25:00", "x"), [i18n.t("sch_bad_time")])
        self.assertEqual(self.call("add", "08:00"), [i18n.t("sch_missing_target")])

    def test_favourite_not_logged_in_error_is_private(self):
        with mock.patch("core.accounts.get_session_account", return_value=(None, None, None, False)):
            self.assertEqual(self.call("add", "08:00", "sf", "1"), [i18n.t("sf_not_logged_in")])

    def test_admin_bot_or_higher_only(self):
        self.assertEqual(self.sch.REQUIRED_ROLE, "admin_bot")
        bot = make_bot(admins=["boss"])
        bot.cfg["admins"] = ["owner"]
        self.assertTrue(roles.has_role(bot, 1, "boss", self.sch.REQUIRED_ROLE))
        self.assertTrue(roles.has_role(bot, 2, "owner", self.sch.REQUIRED_ROLE))
        self.assertFalse(roles.has_role(bot, 3, "random", self.sch.REQUIRED_ROLE))
        bot.t.is_channel_operator.return_value = True
        self.assertFalse(roles.has_role(bot, 4, "operator", self.sch.REQUIRED_ROLE))

    def test_loaded_command_entry_carries_the_admin_role(self):
        from core.command_manager import CommandManager
        commands = CommandManager().load_commands()
        self.assertEqual(commands["sch"]["role"], "admin_bot")
        self.assertEqual(commands["sub"]["role"], "normal")
        self.assertEqual(commands["vn"]["role"], "normal")


class CatalogRegistrationTest(unittest.TestCase):

    def test_sub_and_vn_are_free_and_sch_is_a_paid_capability(self):
        from licensing import catalog
        self.assertIn("sub", catalog.BASE_COMMANDS)
        self.assertIn("vn", catalog.BASE_COMMANDS)
        self.assertNotIn("sch", catalog.BASE_COMMANDS)
        feature = catalog.features()["cap_schedule"]
        self.assertEqual(feature["commands"], ["sch"])
        self.assertEqual(feature["services"], ["schedule"])
        self.assertEqual(feature["price_usd"], 1.5)
        self.assertEqual(catalog.CAPABILITY_OF_FEATURE["cap_schedule"], "schedule")
        self.assertIn("schedule", catalog.CAPABILITY_SERVICES)
        self.assertEqual(catalog.service_for_command("sch"), "schedule")
        for command in ("sub", "vn"):
            self.assertIsNone(catalog.service_for_command(command))
        for panel in catalog.PANELS:
            if panel["code"] in ("p1", "p3", "p4"):
                self.assertNotIn("cap_schedule", panel["features"])

    def test_licence_gate_keys_off_the_schedule_service(self):
        from core import license_gate
        state = license_gate.LicenseState(data={"key": "K", "status": "active",
                                                "expires_at": 4102444800,
                                                "features": ["cap_schedule"]})
        self.assertTrue(state.allows_service("schedule"))
        plain = license_gate.LicenseState(data={"key": "K", "status": "active",
                                                "expires_at": 4102444800, "features": []})
        self.assertFalse(plain.allows_service("schedule"))
        self.assertEqual(license_gate.service_for_command("sch"), "schedule")


if __name__ == "__main__":
    unittest.main()

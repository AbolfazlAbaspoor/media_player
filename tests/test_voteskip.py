"""
رأی برای رد کردنِ آهنگ (core/voteskip.py، دستور vn): آستانه‌ی «بیشتر از نصف»،
تنهایی = فوری، ریست با عوض‌شدنِ آهنگ، رأیِ کسی که رفته، و این‌که رد کردن از همون
مسیر n (handlerِ n -> TrackQueue.advance(force=True)) می‌ره. آفلاین.
"""

import types
import unittest
from unittest import mock

from core import i18n
from core import voteskip
from core.trackqueue import TrackQueue
from tests.helpers import load_command


def user(name, uid):
    return {"username": name, "user_id": uid, "nickname": name.title()}


def make_bot(users, ratio=None):
    bot = types.SimpleNamespace()
    bot.cfg = {} if ratio is None else {"vote_skip": {"ratio": ratio}}
    bot.queue = types.SimpleNamespace(epoch=1, index=0)
    bot.player = types.SimpleNamespace(current_url="stream-0")
    bot.channel_users = list(users)
    bot.t = mock.Mock()
    bot.t.get_channel_users.side_effect = lambda exclude_self=True: list(bot.channel_users)
    bot.channel_messages_enabled = True
    bot.channel_broadcast = mock.Mock()
    bot.commands = {"n": {"handler": mock.Mock()}}
    return bot


def ctx_for(bot, name, uid):
    return {"bot": bot, "uid": uid, "username": name, "nickname": name.title(), "args": []}


class NeededVotesTest(unittest.TestCase):

    def test_more_than_half(self):
        table = {1: 1, 2: 2, 3: 2, 4: 3, 5: 3, 6: 4, 7: 4, 10: 6}
        for users, needed in table.items():
            self.assertEqual(voteskip.needed_votes(users, 0.5), needed, users)

    def test_never_more_than_everyone_and_at_least_one(self):
        self.assertEqual(voteskip.needed_votes(3, 0.99), 3)
        self.assertEqual(voteskip.needed_votes(4, 0.0), 1)
        self.assertEqual(voteskip.needed_votes(0, 0.5), 1)

    def test_ratio_setting_with_default_and_bad_values(self):
        bot = make_bot([])
        self.assertEqual(voteskip.ratio(bot), 0.5)
        for raw, expected in ((0.75, 0.75), ("0.25", 0.25), (5, 0.99), (-1, 0.0),
                              ("junk", 0.5), (None, 0.5), (float("nan"), 0.5)):
            bot.cfg = {"vote_skip": {"ratio": raw}}
            self.assertEqual(voteskip.ratio(bot), expected, raw)
        bot.cfg = {"vote_skip": "not a dict"}
        self.assertEqual(voteskip.ratio(bot), 0.5)

    def test_default_lives_in_shared_config_defaults(self):
        from core import config_defaults
        shared = config_defaults.default_shared_config("h", 1)
        self.assertEqual(shared["vote_skip"], {"ratio": 0.5})
        self.assertNotIn("vote_skip", config_defaults.default_identity())


class CastTest(unittest.TestCase):

    def test_single_user_alone_skips_immediately(self):
        bot = make_bot([user("alice", 1)])
        self.assertEqual(voteskip.cast(bot, ctx_for(bot, "alice", 1)), ("passed", 1, 1))

    def test_needs_more_than_half_of_the_channel(self):
        bot = make_bot([user("a", 1), user("b", 2), user("c", 3), user("d", 4)])
        self.assertEqual(voteskip.cast(bot, ctx_for(bot, "a", 1)), ("voted", 1, 3))
        self.assertEqual(voteskip.cast(bot, ctx_for(bot, "b", 2)), ("voted", 2, 3))
        self.assertEqual(voteskip.cast(bot, ctx_for(bot, "c", 3)), ("passed", 3, 3))

    def test_two_users_need_both(self):
        bot = make_bot([user("a", 1), user("b", 2)])
        self.assertEqual(voteskip.cast(bot, ctx_for(bot, "a", 1))[0], "voted")
        self.assertEqual(voteskip.cast(bot, ctx_for(bot, "b", 2))[0], "passed")

    def test_double_vote_does_not_count_twice(self):
        bot = make_bot([user("a", 1), user("b", 2), user("c", 3)])
        voteskip.cast(bot, ctx_for(bot, "a", 1))
        self.assertEqual(voteskip.cast(bot, ctx_for(bot, "a", 1)), ("already", 1, 2))

    def test_votes_reset_when_the_track_changes(self):
        bot = make_bot([user("a", 1), user("b", 2), user("c", 3), user("d", 4)])
        voteskip.cast(bot, ctx_for(bot, "a", 1))
        voteskip.cast(bot, ctx_for(bot, "b", 2))
        bot.queue.index = 1
        bot.player.current_url = "stream-1"
        self.assertEqual(voteskip.cast(bot, ctx_for(bot, "c", 3)), ("voted", 1, 3))
        # و همین‌طور با سرچِ تازه (epoch جدید) و با همون index
        bot.queue.epoch = 2
        self.assertEqual(voteskip.cast(bot, ctx_for(bot, "a", 1)), ("voted", 1, 3))

    def test_a_passed_vote_clears_the_ballot(self):
        bot = make_bot([user("a", 1)])
        self.assertEqual(voteskip.cast(bot, ctx_for(bot, "a", 1))[0], "passed")
        self.assertEqual(voteskip.cast(bot, ctx_for(bot, "a", 1))[0], "passed")

    def test_a_voter_who_left_the_channel_no_longer_counts(self):
        bot = make_bot([user("a", 1), user("b", 2), user("c", 3)])
        voteskip.cast(bot, ctx_for(bot, "a", 1))
        bot.channel_users = [user("b", 2), user("c", 3)]
        self.assertEqual(voteskip.cast(bot, ctx_for(bot, "b", 2)), ("voted", 1, 2))

    def test_outsiders_cannot_vote(self):
        bot = make_bot([user("a", 1)])
        self.assertEqual(voteskip.cast(bot, ctx_for(bot, "stranger", 9))[0], "not_in_channel")

    def test_nothing_playing(self):
        bot = make_bot([user("a", 1)])
        bot.player.current_url = None
        self.assertEqual(voteskip.cast(bot, ctx_for(bot, "a", 1))[0], "no_track")

    def test_users_without_a_username_are_identified_by_id(self):
        bot = make_bot([user("", 5), user("", 6), user("", 7)])
        self.assertEqual(voteskip.cast(bot, ctx_for(bot, "", 5)), ("voted", 1, 2))
        self.assertEqual(voteskip.cast(bot, ctx_for(bot, "", 6))[0], "passed")

    def test_ratio_one_half_quarter_is_configurable(self):
        bot = make_bot([user("a", 1), user("b", 2), user("c", 3), user("d", 4)], ratio=0.25)
        self.assertEqual(voteskip.cast(bot, ctx_for(bot, "a", 1)), ("voted", 1, 2))
        self.assertEqual(voteskip.cast(bot, ctx_for(bot, "b", 2))[0], "passed")


class RunVoteTest(unittest.TestCase):

    def setUp(self):
        i18n.load_languages()
        i18n.set_language("en")

    def test_vote_is_announced_in_the_channel_without_skipping(self):
        bot = make_bot([user("a", 1), user("b", 2), user("c", 3)])
        voteskip.run_vote(bot, ctx_for(bot, "a", 1))
        bot.channel_broadcast.assert_called_once_with("A voted to skip (1/2).")
        bot.commands["n"]["handler"].assert_not_called()

    def test_passing_vote_announces_then_skips_through_the_n_handler(self):
        bot = make_bot([user("a", 1), user("b", 2), user("c", 3)])
        voteskip.run_vote(bot, ctx_for(bot, "a", 1))
        ctx = ctx_for(bot, "b", 2)
        voteskip.run_vote(bot, ctx)
        self.assertEqual(bot.channel_broadcast.call_args_list[-1].args[0], "B voted to skip (2/2).")
        bot.commands["n"]["handler"].assert_called_once_with(ctx)

    def test_lone_user_skips_at_once(self):
        bot = make_bot([user("a", 1)])
        voteskip.run_vote(bot, ctx_for(bot, "a", 1))
        bot.channel_broadcast.assert_called_once_with("A voted to skip (1/1).")
        bot.commands["n"]["handler"].assert_called_once()

    def test_errors_and_repeats_are_private_not_channel(self):
        bot = make_bot([user("a", 1), user("b", 2), user("c", 3)])
        voteskip.run_vote(bot, ctx_for(bot, "a", 1))
        bot.channel_broadcast.reset_mock()
        voteskip.run_vote(bot, ctx_for(bot, "a", 1))
        voteskip.run_vote(bot, ctx_for(bot, "stranger", 9))
        bot.player.current_url = None
        voteskip.run_vote(bot, ctx_for(bot, "a", 1))
        bot.channel_broadcast.assert_not_called()
        self.assertEqual([c.args for c in bot.t.user_message.call_args_list], [
            (1, i18n.t("vn_already", votes=1, needed=2)),
            (9, i18n.t("vn_not_in_channel")),
            (1, i18n.t("nothing_playing")),
        ])

    def test_channel_messages_off_falls_back_to_the_voter(self):
        bot = make_bot([user("a", 1), user("b", 2), user("c", 3)])
        bot.channel_messages_enabled = False
        voteskip.run_vote(bot, ctx_for(bot, "a", 1))
        bot.channel_broadcast.assert_not_called()
        bot.t.user_message.assert_called_once_with(1, "A voted to skip (1/2).")

    def test_skip_failure_is_reported_privately_without_raw_text(self):
        bot = make_bot([user("a", 1)])
        bot.commands["n"]["handler"].side_effect = RuntimeError("secret C:\\path")
        voteskip.run_vote(bot, ctx_for(bot, "a", 1))
        text = bot.t.user_message.call_args.args[1]
        self.assertNotIn("secret", text)
        self.assertNotIn("C:\\path", text)


class SkipPathTest(unittest.TestCase):
    """vn باید واقعاً از TrackQueue.advance(force=True) بره، نه فقط یه mock."""

    def test_vn_advances_the_real_queue_via_the_n_command(self):
        queue = TrackQueue(play_fn=lambda *a, **k: None)
        queue.replace([{"url": f"http://x/{i}"} for i in range(3)])
        bot = make_bot([user("a", 1)])
        bot.queue = queue
        bot.player.current_url = "http://x/0"
        bot.track_meta = queue.meta()
        bot.search_lock = mock.MagicMock()
        bot.search_session = {}
        n = load_command("n")
        bot.commands = {"n": {"handler": n.run}}
        with mock.patch.object(queue, "advance", wraps=queue.advance) as advance, \
                mock.patch("core.command_helpers.broadcast_now_playing") as announce:
            voteskip.run_vote(bot, ctx_for(bot, "a", 1))
        advance.assert_called_once_with(force=True)
        self.assertEqual(queue.index, 1)
        announce.assert_called_once()

    def test_vn_command_is_free_thin_and_listed(self):
        from licensing import catalog
        vn = load_command("vn")
        self.assertEqual(vn.NAME, "vn")
        self.assertIn("vn", catalog.BASE_COMMANDS)
        self.assertIsNone(catalog.service_for_command("vn"))
        self.assertTrue(vn.USAGE)
        with mock.patch.object(voteskip, "run_vote") as run_vote:
            vn.run({"bot": "BOT", "uid": 1})
        run_vote.assert_called_once()


if __name__ == "__main__":
    unittest.main()

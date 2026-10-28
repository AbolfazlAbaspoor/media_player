"""
Links a customer must never be able to obtain: paid content the owner bought
(documentaries, IPTV) and links a user pasted in themselves.
"""

import os
import unittest
from unittest import mock

from core import command_helpers as ch
from tests.helpers import load_command

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PAID = {"title": "Documentary 7", "public_url": "https://cfdl.ir/vmfiles/7.mkv",
        "private": True, "fallback_label": "https://cfdl.ir/vmfiles/7.mkv",
        "service": "documentary"}
PASTED = {"title": None, "public_url": "https://example.com/secret.mp3",
          "private": True, "fallback_label": "https://example.com/secret.mp3",
          "service": None}
SEARCH = {"title": "Shadmehr - Abi", "public_url": "https://youtu.be/abc",
          "private": False, "fallback_label": None, "service": "youtube"}


class FakeBot:
    def __init__(self, meta):
        self.sent = []
        self.track_meta = [meta]
        self.queue = mock.Mock(index=0)
        self.player = mock.Mock(current_url="https://x/stream", position_seconds=None,
                                duration_seconds=None)
        self.t = mock.Mock()
        self.t.user_message.side_effect = lambda uid, text: self.sent.append(text)

    def format_time(self, s):
        return str(s)


class HelperTest(unittest.TestCase):

    def test_paid_content_is_never_shareable_even_if_marked_public(self):
        self.assertFalse(ch.is_shareable(dict(PAID, private=False)))

    def test_pasted_link_is_not_shareable(self):
        self.assertFalse(ch.is_shareable(PASTED))

    def test_search_result_is_shareable(self):
        self.assertTrue(ch.is_shareable(SEARCH))

    def test_paid_content_cannot_be_downloaded(self):
        self.assertFalse(ch.is_downloadable(PAID))

    def test_user_may_download_their_own_link(self):
        self.assertTrue(ch.is_downloadable(PASTED))

    def test_display_title_never_returns_a_private_link(self):
        for candidate in (None, "https://example.com/secret.mp3"):
            label = ch.display_title(PASTED, candidate)
            self.assertFalse(ch.is_link(label), label)

    def test_display_title_keeps_a_real_title(self):
        self.assertEqual(ch.display_title(PAID), "Documentary 7")

    def test_display_title_takes_a_non_link_title_from_mpv(self):
        self.assertEqual(ch.display_title(PASTED, "Some Song"), "Some Song")

    def test_display_title_ignores_mpv_url_tail_media_title(self):
        tail = "webm&rqh=1&gir=yes&clen=3433755&sig=AE0s2JYw=="
        self.assertNotEqual(ch.display_title({}, tail), tail)
        self.assertEqual(ch.display_title({"title": "Real"}, tail), "Real")


class CommandLeakTest(unittest.TestCase):

    def _run(self, command, meta):
        bot = FakeBot(meta)
        load_command(command).run({"bot": bot, "uid": 1, "args": [], "nickname": "n",
                                   "username": "u"})
        return "\n".join(bot.sent)

    def test_k_does_not_give_out_a_documentary(self):
        self.assertNotIn("cfdl.ir", self._run("k", PAID))

    def test_k_does_not_give_out_a_pasted_link(self):
        self.assertNotIn("secret.mp3", self._run("k", PASTED))

    def test_k_still_shares_a_search_result(self):
        self.assertIn("youtu.be/abc", self._run("k", SEARCH))

    def test_i_does_not_print_a_private_link(self):
        out = self._run("i", PAID)
        self.assertNotIn("cfdl.ir", out)
        self.assertIn("Documentary 7", out)


class DocumentaryIsPaidTest(unittest.TestCase):

    def test_documentary_loads_as_private(self):
        from core import documentary
        bot = mock.Mock()
        with mock.patch.object(documentary, "licensed", return_value=True), \
             mock.patch.object(documentary, "is_valid_number", return_value=True), \
             mock.patch.object(documentary, "item_for",
                               return_value={"url": "u", "title": "t", "public_url": "u"}):
            documentary.play(bot, 7)
        _args, kwargs = bot.load_and_play.call_args
        self.assertTrue(kwargs.get("private"))


if __name__ == "__main__":
    unittest.main()


class SelftestDoesNotRevealTheDocumentarySourceTest(unittest.TestCase):
    """dg is run by the bot's admin, who on a rented bot is the customer."""

    def _report(self, url_for):
        from core import documentary, selftest
        report = mock.Mock()
        bot = mock.Mock(license=None)
        with mock.patch.object(documentary, "url_for", side_effect=url_for), \
             mock.patch.object(documentary, "min_number", return_value=7), \
             mock.patch("core.logging_setup.log_exception"):
            selftest.check_documentary(report, bot)
        return " ".join(str(a) for call in report.add.call_args_list for a in call[0])

    def test_healthy_pattern_is_not_printed(self):
        text = self._report(lambda bot, n: "https://cfdl.ir/vmfiles/%d.mkv" % n)
        self.assertNotIn("cfdl.ir", text)

    def test_broken_pattern_does_not_leak_through_the_error(self):
        def boom(bot, n):
            raise ValueError("bad pattern https://cfdl.ir/vmfiles/{n}.mkv")
        self.assertNotIn("cfdl.ir", self._report(boom))

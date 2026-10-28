"""
تست‌های IPTV (roadmap C2): پارسِ M3U، نرمال‌سازیِ سرچ، حالت تلویزیون
(TV mode)، حریمِ خصوصیِ آدرس استریم، و ثبتِ درست توی کاتالوگ لایسنس.

هیچ تستی درخواست شبکه‌ی واقعی نمی‌زنه -- core.iptv.fetch_channels (یا
لایه‌ی پایین‌ترش، _fetch_text) همیشه mock می‌شه.
"""

import os
import unittest
from unittest import mock

from core import iptv
from licensing import catalog
from tests.helpers import load_command

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# کدپوینت‌های دقیق (نه چیزی که با چشم شبیه‌هم به‌نظر می‌رسن) تا تست واقعاً
# فرقِ فارسی/عربی رو بسنجه، نه یه رشته‌ی تصادفاً یکی.
YEH_PERSIAN = "ی"   # ی
YEH_ARABIC = "ي"    # ي
KEH_PERSIAN = "ک"   # ک
KAF_ARABIC = "ك"    # ك
DIGIT_ONE_FA = "۱"  # ۱  (Extended Arabic-Indic/Persian)

SECRET_URL = "http://sneakyuser:sneakypass@iptv-provider.example.com:8080/get.php?username=u&password=p&type=m3u"


class FakeBot:
    """
    یه ربات ساختگیِ حداقلی -- شبیه FakeBot توی tests/test_privacy.py، ولی
    برای IPTV: iptv_channels/iptv_playing_index واقعی (نه Mock)، چون
    getattr(bot, "license", None) با Mock() خام درست کار نمی‌کنه (Mock
    خودش برای هر attribute یه Mock تازه می‌سازه، پس None هیچ‌وقت True
    نمی‌شه).
    """

    def __init__(self, cfg=None, license=None):
        self.cfg = cfg if cfg is not None else {}
        self.license = license
        self.player = mock.Mock()
        self.iptv_channels = []
        self.iptv_playing_index = None
        self.load_and_play = mock.Mock()
        self.save_config = mock.Mock()
        self.sent = []
        self.t = mock.Mock()
        self.t.user_message.side_effect = lambda uid, text: self.sent.append(text)
        self.channel_broadcast = mock.Mock(side_effect=lambda text: self.sent.append(text))
        self.send_long_text = lambda send_fn, text: send_fn(text)


def ctx(bot, args=None, uid=1, nickname="Nick", username="user1"):
    return {"bot": bot, "uid": uid, "args": args or [], "nickname": nickname,
            "username": username, "cmd": "tv", "raw": ""}


# --------------------------------------------------------------- پارس M3U

class ParseM3UTest(unittest.TestCase):

    def test_basic_two_entries(self):
        text = (
            "#EXTM3U\n"
            "#EXTINF:-1,Channel One\n"
            "http://a.example/1.m3u8\n"
            "#EXTINF:-1,Channel Two\n"
            "http://a.example/2.m3u8\n"
        )
        channels = iptv.parse_m3u(text)
        self.assertEqual([c["name"] for c in channels], ["Channel One", "Channel Two"])
        self.assertEqual(channels[0]["url"], "http://a.example/1.m3u8")

    def test_name_with_comma_in_title_and_attribute(self):
        text = (
            '#EXTM3U\n'
            '#EXTINF:-1 tvg-id="x" group-title="News, Local",Channel, Extra Part\n'
            'http://a.example/1.m3u8\n'
        )
        channels = iptv.parse_m3u(text)
        self.assertEqual(channels[0]["name"], "Channel, Extra Part")
        self.assertEqual(channels[0]["group"], "News, Local")

    def test_extvlcopt_user_agent_and_referrer(self):
        text = (
            "#EXTM3U\n"
            "#EXTINF:-1,Secure Channel\n"
            "#EXTVLCOPT:http-user-agent=MyAgent/1.0\n"
            "#EXTVLCOPT:http-referrer=https://example.com/\n"
            "http://a.example/secure.m3u8\n"
        )
        channels = iptv.parse_m3u(text)
        self.assertEqual(channels[0]["user_agent"], "MyAgent/1.0")
        self.assertEqual(channels[0]["referrer"], "https://example.com/")

    def test_extvlcopt_without_headers_leaves_them_none(self):
        text = "#EXTM3U\n#EXTINF:-1,Plain\nhttp://a.example/plain.m3u8\n"
        channels = iptv.parse_m3u(text)
        self.assertIsNone(channels[0]["user_agent"])
        self.assertIsNone(channels[0]["referrer"])

    def test_extgrp_sets_group(self):
        text = "#EXTM3U\n#EXTGRP:Sports\n#EXTINF:-1,Ch\nhttp://a.example/1.m3u8\n"
        channels = iptv.parse_m3u(text)
        self.assertEqual(channels[0]["group"], "Sports")

    def test_entry_without_extinf_gets_a_name_from_the_url(self):
        text = "#EXTM3U\nhttp://a.example/bare-channel.m3u8\n"
        channels = iptv.parse_m3u(text)
        self.assertEqual(len(channels), 1)
        self.assertTrue(channels[0]["name"])
        self.assertEqual(channels[0]["url"], "http://a.example/bare-channel.m3u8")

    def test_blank_lines_and_crlf_are_tolerated(self):
        text = "#EXTM3U\r\n\r\n#EXTINF:-1,Ch\r\n\r\nhttp://a.example/1.m3u8\r\n"
        channels = iptv.parse_m3u(text)
        self.assertEqual(len(channels), 1)
        self.assertEqual(channels[0]["name"], "Ch")

    def test_leading_bom_is_stripped(self):
        text = "﻿#EXTM3U\n#EXTINF:-1,Ch\nhttp://a.example/1.m3u8\n"
        channels = iptv.parse_m3u(text)
        self.assertEqual(len(channels), 1)
        self.assertEqual(channels[0]["name"], "Ch")

    def test_tvg_name_used_when_title_is_empty(self):
        text = '#EXTM3U\n#EXTINF:-1 tvg-name="Fallback Name",\nhttp://a.example/1.m3u8\n'
        channels = iptv.parse_m3u(text)
        self.assertEqual(channels[0]["name"], "Fallback Name")

    def test_missing_playlist_does_not_crash(self):
        self.assertEqual(iptv.parse_m3u(""), [])
        self.assertEqual(iptv.parse_m3u(None), [])

    def test_source_name_is_attached(self):
        text = "#EXTM3U\n#EXTINF:-1,Ch\nhttp://a.example/1.m3u8\n"
        channels = iptv.parse_m3u(text, source_name="My Source")
        self.assertEqual(channels[0]["source"], "My Source")


# ------------------------------------------------------------- نرمال‌سازیِ سرچ

class SearchNormalizationTest(unittest.TestCase):

    def test_case_insensitive(self):
        channels = [{"name": "BBC Persian"}]
        self.assertEqual(iptv.search(None, "bbc persian", channels=channels), channels)

    def test_arabic_yeh_and_kaf_match_persian_stored_name(self):
        name = KEH_PERSIAN + "انال " + YEH_PERSIAN + KEH_PERSIAN  # کانال یک
        query = KAF_ARABIC + "انال " + YEH_ARABIC + KAF_ARABIC     # كانال يك
        channels = [{"name": name}]
        result = iptv.search(None, query, channels=channels)
        self.assertEqual(len(result), 1)

    def test_persian_digit_matches_ascii_digit_query(self):
        name = KEH_PERSIAN + "انال " + DIGIT_ONE_FA  # کانال ۱
        channels = [{"name": name}, {"name": "Other"}]
        result = iptv.search(None, KEH_PERSIAN + "انال 1", channels=channels)
        self.assertEqual([c["name"] for c in result], [name])

    def test_partial_words_match_in_any_order(self):
        channels = [{"name": "Radio Javan Persian"}]
        self.assertEqual(len(iptv.search(None, "persian radio", channels=channels)), 1)

    def test_no_match_returns_empty(self):
        channels = [{"name": "BBC"}, {"name": "CNN"}]
        self.assertEqual(iptv.search(None, "nonexistent-zzz", channels=channels), [])

    def test_empty_query_returns_everything(self):
        channels = [{"name": "A"}, {"name": "B"}]
        self.assertEqual(iptv.search(None, "   ", channels=channels), channels)

    def test_search_uses_fetch_channels_when_none_given(self):
        with mock.patch.object(iptv, "fetch_channels", return_value=[{"name": "Alpha"}]) as fc:
            result = iptv.search(mock.sentinel.bot, "alpha")
        fc.assert_called_once_with(mock.sentinel.bot)
        self.assertEqual(result, [{"name": "Alpha"}])


# ---------------------------------------------------------------- صفحه‌بندی

class PaginateTest(unittest.TestCase):

    def test_splits_into_pages(self):
        items = list(range(1, 36))
        page_items, page, pages, total = iptv.paginate(items, 1, 15)
        self.assertEqual(page_items, list(range(1, 16)))
        self.assertEqual((page, pages, total), (1, 3, 35))

    def test_second_page(self):
        items = list(range(1, 36))
        page_items, page, pages, total = iptv.paginate(items, 2, 15)
        self.assertEqual(page_items, list(range(16, 31)))

    def test_out_of_range_page_clamps_to_last(self):
        items = list(range(1, 10))
        page_items, page, pages, total = iptv.paginate(items, 99, 15)
        self.assertEqual(page, 1)
        self.assertEqual(page_items, items)

    def test_empty_list(self):
        page_items, page, pages, total = iptv.paginate([], 1, 15)
        self.assertEqual((page_items, page, pages, total), ([], 1, 1, 0))


# --------------------------------------------------------------- حالتِ تلویزیون

class TvModeTest(unittest.TestCase):

    def _channels(self):
        return [{"name": "Ch A", "url": "http://x/a.m3u8"},
                {"name": "Ch B", "url": "http://x/b.m3u8"},
                {"name": "Ch C", "url": "http://x/c.m3u8"}]

    def test_no_list_initially(self):
        bot = FakeBot()
        self.assertFalse(iptv.has_list(bot))
        self.assertFalse(iptv.is_active(bot))

    def test_set_list_makes_has_list_true_but_not_active(self):
        bot = FakeBot()
        iptv.set_list(bot, self._channels())
        self.assertTrue(iptv.has_list(bot))
        self.assertFalse(iptv.is_active(bot))

    def test_play_by_number_selects_and_activates(self):
        bot = FakeBot()
        iptv.set_list(bot, self._channels())
        channel = iptv.play(bot, 2)
        self.assertEqual(channel["name"], "Ch B")
        self.assertTrue(iptv.is_active(bot))
        bot.load_and_play.assert_called_once()
        args, kwargs = bot.load_and_play.call_args
        self.assertIs(kwargs["private"], True)
        self.assertEqual(kwargs["service_name"], iptv.SERVICE_NAME)
        self.assertEqual(args[0]["url"], "http://x/b.m3u8")
        self.assertEqual(args[0]["title"], "Ch B")
        self.assertIsNone(args[0]["public_url"])

    def test_play_accepts_persian_digit(self):
        bot = FakeBot()
        iptv.set_list(bot, self._channels())
        channel = iptv.play(bot, DIGIT_ONE_FA)
        self.assertEqual(channel["name"], "Ch A")

    def test_play_invalid_number_raises(self):
        bot = FakeBot()
        iptv.set_list(bot, self._channels())
        with self.assertRaises(iptv.IPTVError):
            iptv.play(bot, 99)
        bot.load_and_play.assert_not_called()

    def test_play_without_any_list_raises(self):
        bot = FakeBot()
        with self.assertRaises(iptv.IPTVError):
            iptv.play(bot, 1)

    def test_step_forward_then_backward(self):
        bot = FakeBot()
        iptv.set_list(bot, self._channels())
        iptv.play(bot, 1)
        forward = iptv.step(bot, +1)
        self.assertEqual(forward["name"], "Ch B")
        backward = iptv.step(bot, -1)
        self.assertEqual(backward["name"], "Ch A")

    def test_step_none_at_start_edge(self):
        bot = FakeBot()
        iptv.set_list(bot, self._channels())
        iptv.play(bot, 1)
        self.assertIsNone(iptv.step(bot, -1))

    def test_step_none_at_end_edge(self):
        bot = FakeBot()
        iptv.set_list(bot, self._channels())
        iptv.play(bot, 3)
        self.assertIsNone(iptv.step(bot, +1))

    def test_step_none_when_nothing_playing(self):
        bot = FakeBot()
        iptv.set_list(bot, self._channels())
        self.assertIsNone(iptv.step(bot, +1))

    def _mpv_defaults(self, bot):
        bot.player.raw.user_agent = "libmpv"
        bot.player.raw.referrer = ""

    def test_clear_restores_the_players_own_headers(self):
        bot = FakeBot()
        self._mpv_defaults(bot)
        iptv.set_list(bot, [{"name": "Ch A", "url": "http://x/a.m3u8",
                             "user_agent": "UA", "referrer": "http://ref.example"}])
        iptv.play(bot, 1)
        self.assertEqual(bot.player.raw.user_agent, "UA")
        self.assertEqual(bot.player.raw.referrer, "http://ref.example")
        iptv.clear(bot)
        self.assertFalse(iptv.has_list(bot))
        self.assertFalse(iptv.is_active(bot))
        self.assertEqual(bot.player.raw.user_agent, "libmpv")
        self.assertEqual(bot.player.raw.referrer, "")

    def test_a_channel_without_headers_gets_the_defaults_not_the_previous_ones(self):
        bot = FakeBot()
        self._mpv_defaults(bot)
        iptv.set_list(bot, [
            {"name": "Ch A", "url": "http://x/a.m3u8", "user_agent": "UA"},
            {"name": "Ch B", "url": "http://x/b.m3u8"},
        ])
        iptv.play(bot, 1)
        self.assertEqual(bot.player.raw.user_agent, "UA")
        iptv.play(bot, 2)
        self.assertEqual(bot.player.raw.user_agent, "libmpv")

    def test_clear_leaves_the_player_alone_when_iptv_never_touched_it(self):
        # load_and_play صداش می‌زنه برای هر پخشی؛ قبلاً User-Agent یوتیوب رو خالی می‌کرد.
        bot = FakeBot()
        self._mpv_defaults(bot)
        bot.player.raw.user_agent = "custom/1.0"
        iptv.clear(bot)
        self.assertEqual(bot.player.raw.user_agent, "custom/1.0")

    def test_n_and_b_share_one_step_path_that_never_leaks_a_url(self):
        bot = FakeBot()
        bot.iptv_channels = [{"name": "Ch A", "url": "http://x/a.m3u8"}]
        bot.iptv_playing_index = 0
        ctx = {"uid": 1, "nickname": "Ali", "username": "ali"}
        failure = RuntimeError("open http://secret.example/s.m3u8 failed")
        with mock.patch.object(iptv, "step", side_effect=failure):
            self.assertTrue(iptv.step_command(bot, ctx, +1))
        self.assertNotIn("secret.example", " ".join(bot.sent))
        bot.iptv_playing_index = None
        self.assertFalse(iptv.step_command(bot, ctx, -1))

    def test_licence_without_service_blocks_play(self):
        bot = FakeBot(license=mock.Mock(allows_service=mock.Mock(return_value=False)))
        iptv.set_list(bot, self._channels())
        with self.assertRaises(iptv.IPTVError):
            iptv.play(bot, 1)
        bot.load_and_play.assert_not_called()

    def test_no_license_object_means_open(self):
        bot = FakeBot(license=None)
        iptv.set_list(bot, self._channels())
        iptv.play(bot, 1)
        bot.load_and_play.assert_called_once()

    def test_step_also_checks_licence(self):
        allow = mock.Mock(return_value=True)
        bot = FakeBot(license=mock.Mock(allows_service=allow))
        iptv.set_list(bot, self._channels())
        iptv.play(bot, 1)
        allow.return_value = False
        with self.assertRaises(iptv.IPTVError):
            iptv.step(bot, +1)


# ----------------------------------------------------------------- دستور tv

class TvCommandTest(unittest.TestCase):

    def _channels(self):
        return [{"name": "Alpha", "url": "https://x/alpha.m3u8"},
                {"name": "Beta", "url": "https://x/beta.m3u8"}]

    def test_no_args_shows_status_without_crashing(self):
        bot = FakeBot()
        with mock.patch.object(iptv, "fetch_channels", return_value=self._channels()):
            load_command("tv").run(ctx(bot))
        self.assertTrue(bot.sent)

    def test_no_args_survives_a_fully_unavailable_service(self):
        bot = FakeBot()
        with mock.patch.object(iptv, "fetch_channels", side_effect=iptv.IPTVError("down")):
            load_command("tv").run(ctx(bot))
        self.assertTrue(bot.sent)

    def test_search_lists_matches_and_sets_the_last_list(self):
        bot = FakeBot()
        with mock.patch.object(iptv, "fetch_channels", return_value=self._channels()):
            load_command("tv").run(ctx(bot, args=["alpha"]))
        self.assertTrue(iptv.has_list(bot))
        self.assertEqual([c["name"] for c in bot.iptv_channels], ["Alpha"])

    def test_search_with_no_match_notifies(self):
        bot = FakeBot()
        with mock.patch.object(iptv, "fetch_channels", return_value=self._channels()):
            load_command("tv").run(ctx(bot, args=["zzz-nonexistent"]))
        self.assertTrue(bot.sent)
        self.assertFalse(iptv.has_list(bot))

    def test_number_after_search_plays_from_that_list(self):
        bot = FakeBot()
        with mock.patch.object(iptv, "fetch_channels", return_value=self._channels()):
            tv = load_command("tv")
            tv.run(ctx(bot, args=["alpha"]))
            tv.run(ctx(bot, args=["1"]))
        self.assertTrue(iptv.is_active(bot))
        bot.load_and_play.assert_called_once()

    def test_list_command_pages_all_channels(self):
        bot = FakeBot(cfg={"iptv": {"page_size": 1}})
        with mock.patch.object(iptv, "fetch_channels", return_value=self._channels()):
            load_command("tv").run(ctx(bot, args=["list", "2"]))
        self.assertEqual([c["name"] for c in bot.iptv_channels], ["Beta"])

    def test_bare_number_command_reuses_last_list_like_bot_dispatch(self):
        """
        همون مسیری که bot.py._handle_number_command صدا می‌زنه: بعد از
        tv list، فرستادن یه عدد خام (نه tv <عدد>) باید از همون لیست پخش کنه.
        """
        bot = FakeBot()
        with mock.patch.object(iptv, "fetch_channels", return_value=self._channels()):
            load_command("tv").run(ctx(bot, args=["list"]))
        channel = iptv.play(bot, 2)
        self.assertEqual(channel["name"], "Beta")

    def test_playing_something_else_ends_tv_mode(self):
        """load_and_play توی bot.py برای هر سرویسِ غیر-iptv iptv.clear رو صدا می‌زنه."""
        bot = FakeBot()
        iptv.set_list(bot, self._channels())
        iptv.play(bot, 1)
        self.assertTrue(iptv.is_active(bot))
        iptv.clear(bot)  # شبیه‌سازیِ اثر load_and_play روی یه پخشِ غیر-IPTV
        self.assertFalse(iptv.is_active(bot))
        self.assertFalse(iptv.has_list(bot))


# ----------------------------------------------------------------- دستور tvs

class TvsCommandTest(unittest.TestCase):

    def _bot(self):
        return FakeBot(cfg={"iptv": {"sources": [{"name": "A", "url": "https://a.example/list.m3u"}]}})

    def test_show_lists_sources_by_name(self):
        bot = self._bot()
        load_command("tvs").run(ctx(bot))
        joined = "\n".join(bot.sent)
        self.assertIn("A", joined)

    def test_show_with_no_sources(self):
        bot = FakeBot(cfg={"iptv": {"sources": []}})
        load_command("tvs").run(ctx(bot))
        self.assertTrue(bot.sent)

    def test_add_appends_and_saves(self):
        bot = self._bot()
        load_command("tvs").run(ctx(bot, args=["add", "https://b.example/list.m3u", "B"]))
        self.assertEqual(len(bot.cfg["iptv"]["sources"]), 2)
        self.assertEqual(bot.cfg["iptv"]["sources"][1]["name"], "B")
        bot.save_config.assert_called_once()

    def test_add_without_a_name_gets_a_generic_placeholder(self):
        bot = self._bot()
        load_command("tvs").run(ctx(bot, args=["add", "https://b.example/list.m3u"]))
        name = bot.cfg["iptv"]["sources"][1]["name"]
        self.assertNotIn("b.example", name)
        self.assertTrue(name)

    def test_add_rejects_a_non_http_url(self):
        bot = self._bot()
        load_command("tvs").run(ctx(bot, args=["add", "not-a-url"]))
        self.assertEqual(len(bot.cfg["iptv"]["sources"]), 1)
        bot.save_config.assert_not_called()

    def test_del_removes_by_displayed_index(self):
        bot = self._bot()
        load_command("tvs").run(ctx(bot, args=["del", "1"]))
        self.assertEqual(bot.cfg["iptv"]["sources"], [])
        bot.save_config.assert_called_once()

    def test_del_with_bad_index_leaves_sources_alone(self):
        bot = self._bot()
        load_command("tvs").run(ctx(bot, args=["del", "9"]))
        self.assertEqual(len(bot.cfg["iptv"]["sources"]), 1)
        bot.save_config.assert_not_called()

    def test_reload_invalidates_cache_and_forces_a_fresh_fetch(self):
        bot = self._bot()
        with mock.patch.object(iptv, "fetch_channels", return_value=[{"name": "X"}]) as fc:
            load_command("tvs").run(ctx(bot, args=["reload"]))
        fc.assert_called_once_with(bot, force=True)
        self.assertTrue(bot.sent)

    def test_unknown_action_shows_usage(self):
        bot = self._bot()
        load_command("tvs").run(ctx(bot, args=["frobnicate"]))
        self.assertTrue(bot.sent)


# -------------------------------------------------------------------- حریم

class PrivacyTest(unittest.TestCase):

    def test_mask_host_hides_userinfo_path_and_query(self):
        masked = iptv.mask_host(SECRET_URL)
        for secret in ("sneakyuser", "sneakypass", "get.php", "username", "password"):
            self.assertNotIn(secret, masked)

    def test_mask_host_keeps_some_of_the_hostname_for_identification(self):
        masked = iptv.mask_host("https://iptv-org.github.io/iptv/countries/ir.m3u")
        self.assertIn("*", masked)
        self.assertNotIn("countries", masked)
        self.assertNotIn("ir.m3u", masked)

    def test_search_results_never_print_the_url(self):
        bot = FakeBot()
        channels = [{"name": "Sneaky Channel", "url": SECRET_URL}]
        with mock.patch.object(iptv, "fetch_channels", return_value=channels):
            load_command("tv").run(ctx(bot, args=["sneaky"]))
        joined = "\n".join(bot.sent)
        self.assertNotIn(SECRET_URL, joined)
        self.assertNotIn("sneakypass", joined)

    def test_now_playing_broadcast_never_prints_the_url(self):
        bot = FakeBot()
        iptv.set_list(bot, [{"name": "Sneaky Channel", "url": SECRET_URL}])
        load_command("tv").run(ctx(bot, args=["1"]))
        joined = "\n".join(bot.sent)
        self.assertNotIn(SECRET_URL, joined)
        self.assertNotIn("sneakypass", joined)

    def test_tvs_show_only_reveals_a_masked_host(self):
        bot = FakeBot(cfg={"iptv": {"sources": [{"name": "Secret", "url": SECRET_URL}]}})
        load_command("tvs").run(ctx(bot))
        joined = "\n".join(bot.sent)
        self.assertNotIn(SECRET_URL, joined)
        self.assertNotIn("sneakyuser", joined)
        self.assertNotIn("sneakypass", joined)

    def test_tvs_add_confirmation_does_not_echo_the_raw_url(self):
        bot = FakeBot(cfg={"iptv": {"sources": []}})
        load_command("tvs").run(ctx(bot, args=["add", SECRET_URL, "Secret"]))
        joined = "\n".join(bot.sent)
        self.assertNotIn(SECRET_URL, joined)
        self.assertNotIn("sneakypass", joined)

    def test_iptv_is_registered_as_paid_private(self):
        from core import command_helpers
        self.assertIn("iptv", command_helpers.PAID_PRIVATE_SERVICES)

    def test_iptv_track_is_not_shareable_and_not_downloadable(self):
        from core import command_helpers as ch
        meta = {"title": "Sneaky Channel", "public_url": None, "private": True, "service": "iptv"}
        self.assertFalse(ch.is_shareable(meta))
        self.assertFalse(ch.is_downloadable(meta))

    def test_display_title_never_leaks_the_stream_url(self):
        from core import command_helpers as ch
        meta = {"title": None, "service": "iptv", "private": True, "public_url": None}
        label = ch.display_title(meta, SECRET_URL)
        self.assertFalse(ch.is_link(label or ""))

    def test_play_item_passed_to_load_and_play_has_no_public_url(self):
        bot = FakeBot()
        iptv.set_list(bot, [{"name": "Ch", "url": SECRET_URL}])
        iptv.play(bot, 1)
        args, _kwargs = bot.load_and_play.call_args
        self.assertIsNone(args[0]["public_url"])


# ------------------------------------------------------------- کاتالوگ/لایسنس

class CatalogRegistrationTest(unittest.TestCase):

    def test_iptv_is_a_capability_service(self):
        self.assertIn("iptv", catalog.CAPABILITY_SERVICES)

    def test_cap_iptv_maps_to_the_iptv_service(self):
        self.assertEqual(catalog.CAPABILITY_OF_FEATURE.get("cap_iptv"), "iptv")

    def test_cap_iptv_feature_exists_with_its_commands(self):
        feature = catalog.features()["cap_iptv"]
        self.assertIn("iptv", feature["services"])
        self.assertIn("tv", feature["commands"])
        self.assertIn("tvs", feature["commands"])

    def test_service_for_command_tv_and_tvs(self):
        self.assertEqual(catalog.service_for_command("tv"), "iptv")
        self.assertEqual(catalog.service_for_command("tvs"), "iptv")

    def test_licence_gate_blocks_iptv_without_the_feature(self):
        from core import license_gate as gate
        s = gate.LicenseState(data={"key": "TT-TEST-0000-0000", "expires_at": 9999999999,
                                    "features": ["cap_proxy"]})
        self.assertFalse(s.allows_service("iptv"))

    def test_licence_gate_allows_iptv_with_the_feature(self):
        from core import license_gate as gate
        s = gate.LicenseState(data={"key": "TT-TEST-0000-0000", "expires_at": 9999999999,
                                    "features": ["cap_iptv"]})
        self.assertTrue(s.allows_service("iptv"))


class ConfigDefaultsTest(unittest.TestCase):

    def test_default_shared_config_ships_a_working_source(self):
        from core.config_defaults import default_shared_config
        cfg = default_shared_config("host", 1234)
        self.assertIn("iptv", cfg)
        sources = cfg["iptv"]["sources"]
        self.assertTrue(sources)
        self.assertTrue(iptv.looks_like_source_url(sources[0]["url"]))


class HelpersTest(unittest.TestCase):

    def test_looks_like_source_url(self):
        self.assertTrue(iptv.looks_like_source_url("https://example.com/list.m3u"))
        self.assertTrue(iptv.looks_like_source_url("http://example.com/list.m3u"))
        self.assertFalse(iptv.looks_like_source_url("ftp://example.com/list.m3u"))
        self.assertFalse(iptv.looks_like_source_url(""))
        self.assertFalse(iptv.looks_like_source_url(None))

    def test_fetch_channels_raises_when_no_sources_configured(self):
        bot = FakeBot(cfg={"iptv": {"sources": []}})
        with self.assertRaises(iptv.IPTVError):
            iptv.fetch_channels(bot)

    def test_fetch_channels_raises_when_every_source_fails(self):
        bot = FakeBot(cfg={"iptv": {"sources": [{"name": "A", "url": "https://a.example/list.m3u"}]}})
        with mock.patch.object(iptv, "_fetch_text", side_effect=OSError("network down")):
            with self.assertRaises(iptv.IPTVError):
                iptv.fetch_channels(bot)

    def test_fetch_channels_survives_a_partial_failure(self):
        bot = FakeBot(cfg={"iptv": {"sources": [
            {"name": "Bad", "url": "https://bad.example/list.m3u"},
            {"name": "Good", "url": "https://good.example/list.m3u"},
        ]}})

        def fake_fetch(url, timeout=None):
            if "bad" in url:
                raise OSError("boom")
            return "#EXTM3U\n#EXTINF:-1,Ch\nhttp://good.example/ch.m3u8\n"

        with mock.patch.object(iptv, "_fetch_text", side_effect=fake_fetch):
            channels = iptv.fetch_channels(bot)
        self.assertEqual(len(channels), 1)
        self.assertEqual(channels[0]["name"], "Ch")

    def test_fetch_channels_is_cached_between_calls(self):
        bot = FakeBot(cfg={"iptv": {"sources": [{"name": "A", "url": "https://a.example/list.m3u"}]}})
        with mock.patch.object(iptv, "_fetch_text",
                               return_value="#EXTM3U\n#EXTINF:-1,Ch\nhttp://a.example/ch.m3u8\n") as ft:
            iptv.fetch_channels(bot)
            iptv.fetch_channels(bot)
        self.assertEqual(ft.call_count, 1)


if __name__ == "__main__":
    unittest.main()

"""
زیرنویس زنده (core/subtitles.py، دستور sub): parse و dedupe، منطق زمان‌بندی
(pause/seek/تغییر آهنگ)، انتخاب زیرنویس (دستی بر خودکار) و tick روی یه ربات
ساختگی. همه آفلاین -- بدون شبکه و mpv.
"""

import types
import unittest
from unittest import mock

from core import i18n
from core import subtitles
from core.subtitles import Cue, Cursor
from tests.helpers import load_command

# نمونه‌ی واقعی از شکلِ زیرنویسِ خودکارِ یوتیوب: هر cue دوخطیه، خطِ اول تکرارِ
# خطِ دومِ cueِ قبلی، و cueهای ۱۰ میلی‌ثانیه‌ای که همون متن رو تکرار می‌کنن.
ROLLING_VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.000 align:start position:0%
 
hello<00:00:00.500><c> there</c><00:00:01.000><c> everyone</c>

00:00:02.000 --> 00:00:02.010 align:start position:0%
hello there everyone

00:00:02.010 --> 00:00:04.000 align:start position:0%
hello there everyone
welcome<00:00:02.500><c> to</c><00:00:03.000><c> the</c><00:00:03.500><c> show</c>

00:00:04.000 --> 00:00:04.010 align:start position:0%
welcome to the show

00:00:04.010 --> 00:00:06.000 align:start position:0%
welcome to the show
today&nbsp;we&#39;re<c.colorE5E5E5> talking</c> about cats
"""

SRT = """1
00:00:01,000 --> 00:00:03,500
<i>First</i> line
second line

2
00:00:04,000 --> 00:00:05,000
{\\an8}Top text

3
00:01:02,500 --> 00:01:04,000
After a minute
"""


class ParseTest(unittest.TestCase):

    def test_srt_parses_times_and_strips_styling(self):
        cues = subtitles.parse_cues(SRT)
        self.assertEqual(len(cues), 3)
        self.assertEqual(cues[0], Cue(1.0, 3.5, "First line\nsecond line"))
        self.assertEqual(cues[1].text, "Top text")
        self.assertAlmostEqual(cues[2].start, 62.5)

    def test_vtt_strips_inline_timestamps_and_entities(self):
        cues = subtitles.parse_cues(ROLLING_VTT)
        texts = [cue.text for cue in cues]
        self.assertEqual(texts[0], "hello there everyone")
        self.assertIn("welcome to the show", texts[2])
        self.assertIn("today we're talking about cats", texts[-1])
        self.assertTrue(all("<" not in text and "&" not in text for text in texts))

    def test_header_note_and_empty_cues_are_ignored(self):
        text = "WEBVTT\n\nNOTE this is a comment\n\nSTYLE\n::cue { color: red }\n\n" \
               "00:00:01.000 --> 00:00:02.000\n<c></c>\n\n00:00:02.000 --> 00:00:03.000\nreal\n"
        self.assertEqual([c.text for c in subtitles.parse_cues(text)], ["real"])

    def test_blank_line_right_after_timing_does_not_swallow_the_text(self):
        # «خطِ تک‌فاصله»ی یوتیوب اگه جایی به خطِ خالی تبدیل بشه
        text = ("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n\nhello there\n\n"
                "00:00:02.000 --> 00:00:03.000\nnext\n")
        self.assertEqual([c.text for c in subtitles.parse_cues(text)], ["hello there", "next"])

    def test_short_timestamps_and_bom_and_crlf(self):
        text = "\ufeffWEBVTT\r\n\r\n01:02.250 --> 01:03.000\r\nmm:ss form\r\n"
        cues = subtitles.parse_cues(text)
        self.assertEqual(len(cues), 1)
        self.assertAlmostEqual(cues[0].start, 62.25)

    def test_garbage_and_empty_input(self):
        self.assertEqual(subtitles.parse_cues(""), [])
        self.assertEqual(subtitles.parse_cues(None), [])
        self.assertEqual(subtitles.parse_cues("<html>not a subtitle</html>"), [])
        self.assertEqual(subtitles.parse_cues("x --> y\nhello"), [])

    def test_persian_text_survives(self):
        cues = subtitles.parse_cues("1\n00:00:01,000 --> 00:00:02,000\nسلام <i>دنیا</i>\n")
        self.assertEqual(cues[0].text, "سلام دنیا")


class DedupeTest(unittest.TestCase):

    def test_rolling_auto_captions_keep_each_line_once(self):
        cues = subtitles.dedupe_rolling(subtitles.parse_cues(ROLLING_VTT))
        self.assertEqual([cue.text for cue in cues],
                         ["hello there everyone", "welcome to the show",
                          "today we're talking about cats"])
        # پنجره‌ی نمایشِ cueِ اول با cueهای تکراریِ بعدش دراز نشده چون متنِ تازه‌ای نبوده
        self.assertEqual(cues[0].start, 0.0)

    def test_word_by_word_growth_emits_only_the_new_part(self):
        cues = [Cue(0, 1, "I"), Cue(1, 2, "I think"), Cue(2, 3, "I think so")]
        self.assertEqual([c.text for c in subtitles.dedupe_rolling(cues)], ["I", "think", "so"])

    def test_fully_repeated_cue_extends_previous_window(self):
        cues = [Cue(0, 1, "a\nb"), Cue(1, 1.01, "a\nb")]
        out = subtitles.dedupe_rolling(cues)
        self.assertEqual(out, [Cue(0, 1.01, "a\nb")])

    def test_merge_repeats_joins_touching_identical_cues_only(self):
        cues = [Cue(0, 1, "no"), Cue(1, 2, "no"), Cue(5, 6, "no")]
        self.assertEqual(subtitles.merge_repeats(cues), [Cue(0, 2, "no"), Cue(5, 6, "no")])

    def test_message_text_is_single_line_and_capped(self):
        self.assertEqual(subtitles.message_text(Cue(0, 1, "a\nb")), "a b")
        long = subtitles.message_text(Cue(0, 1, "x" * 1000))
        self.assertLessEqual(len(long), subtitles.MAX_CUE_CHARS)


CUES = [Cue(1, 3, "one"), Cue(4, 6, "two"), Cue(10, 12, "three"), Cue(20, 22, "four")]


def texts(cues):
    return [cue.text for cue in cues]


class CursorTest(unittest.TestCase):

    def test_normal_playback_sends_each_cue_once_at_its_time(self):
        cursor = Cursor(CUES)
        self.assertEqual(texts(cursor.poll(0.0)), [])
        self.assertEqual(texts(cursor.poll(0.5)), [])
        self.assertEqual(texts(cursor.poll(1.0)), ["one"])
        self.assertEqual(texts(cursor.poll(1.5)), [])
        self.assertEqual(texts(cursor.poll(4.2)), ["two"])
        self.assertEqual(texts(cursor.poll(4.7)), [])

    def test_pause_sends_nothing_even_when_polled_repeatedly(self):
        cursor = Cursor(CUES)
        cursor.poll(0.0)
        cursor.poll(1.2)
        for _ in range(20):
            self.assertEqual(cursor.poll(1.2), [])

    def test_first_poll_mid_cue_sends_the_active_cue(self):
        self.assertEqual(texts(Cursor(CUES).poll(11.0)), ["three"])

    def test_first_poll_between_cues_sends_nothing(self):
        self.assertEqual(Cursor(CUES).poll(7.0), [])

    def test_backward_seek_replays_the_cue_at_the_new_position(self):
        cursor = Cursor(CUES)
        cursor.poll(0.0)
        for position in (1.0, 4.0, 4.5, 10.0, 10.5):
            cursor.poll(position)
        self.assertEqual(texts(cursor.poll(2.0)), ["one"])
        # بعد از seek دوباره از همون‌جا جلو می‌ره، نه این‌که cueهای بینِ راه تکرار بشن
        self.assertEqual(texts(cursor.poll(2.5)), [])
        self.assertEqual(texts(cursor.poll(4.1)), ["two"])

    def test_backward_seek_into_a_gap_sends_nothing_then_resumes(self):
        cursor = Cursor(CUES)
        cursor.poll(0.0)
        cursor.poll(11.0)
        self.assertEqual(cursor.poll(8.0), [])
        self.assertEqual(texts(cursor.poll(10.2)), ["three"])

    def test_forward_seek_skips_the_cues_in_between(self):
        cursor = Cursor(CUES)
        cursor.poll(0.0)
        cursor.poll(1.0)
        # پرش از ۱ به ۲۰.۵: فقط cueِ در حال نمایش، نه «two» و «three» که رد شدن
        self.assertEqual(texts(cursor.poll(20.5)), ["four"])

    def test_small_backward_jitter_does_not_resend(self):
        cursor = Cursor(CUES)
        cursor.poll(0.0)
        cursor.poll(1.2)
        self.assertEqual(cursor.poll(1.0), [])
        self.assertEqual(cursor.poll(1.3), [])

    def test_stall_catches_up_with_at_most_the_last_few_cues(self):
        cues = [Cue(i, i + 0.5, f"c{i}") for i in range(10)]
        cursor = Cursor(cues)
        cursor.poll(0.0)
        out = cursor.poll(3.0)  # ۳ ثانیه‌ی عقب‌ماندگی: cueهای ۱ تا ۳
        self.assertEqual(texts(out), ["c2", "c3"])

    def test_unknown_position_is_ignored(self):
        cursor = Cursor(CUES)
        self.assertEqual(cursor.poll(None), [])
        self.assertEqual(cursor.poll(0.5), [])  # اولین poll واقعی = هم‌زمان‌سازی
        self.assertEqual(texts(cursor.poll(1.0)), ["one"])

    def test_position_zero_start_cue_is_sent(self):
        cursor = Cursor([Cue(0, 2, "intro")])
        self.assertEqual(texts(cursor.poll(0.3)), ["intro"])


class ChooseSubtitleTest(unittest.TestCase):

    @staticmethod
    def formats(*exts):
        return [{"ext": ext, "url": f"https://x/{ext}"} for ext in exts]

    def test_manual_beats_auto(self):
        info = {"subtitles": {"en": self.formats("vtt")},
                "automatic_captions": {"en": self.formats("vtt")}}
        self.assertEqual(subtitles.choose_subtitle(info, "en")["kind"], "manual")

    def test_manual_beats_auto_even_with_a_less_exact_language(self):
        info = {"subtitles": {"en-GB": self.formats("vtt")},
                "automatic_captions": {"en": self.formats("vtt")}}
        chosen = subtitles.choose_subtitle(info, "en")
        self.assertEqual((chosen["kind"], chosen["lang"]), ("manual", "en-GB"))

    def test_falls_back_to_auto(self):
        info = {"subtitles": {"de": self.formats("vtt")},
                "automatic_captions": {"fa": self.formats("srv3", "vtt")}}
        chosen = subtitles.choose_subtitle(info, "fa")
        self.assertEqual((chosen["kind"], chosen["ext"]), ("auto", "vtt"))

    def test_exact_language_wins_then_shortest_prefix_match(self):
        info = {"subtitles": {"en-US": self.formats("vtt"), "en": self.formats("vtt"),
                              "en-orig": self.formats("vtt")}}
        self.assertEqual(subtitles.choose_subtitle(info, "en")["lang"], "en")
        info = {"subtitles": {"en-US": self.formats("vtt"), "en-orig": self.formats("vtt")}}
        self.assertEqual(subtitles.choose_subtitle(info, "en")["lang"], "en-US")
        info = {"subtitles": {"en": self.formats("vtt")}}
        self.assertEqual(subtitles.choose_subtitle(info, "en-us")["lang"], "en")

    def test_prefers_vtt_then_srt_and_skips_unusable_formats(self):
        info = {"subtitles": {"en": self.formats("ttml", "srt", "vtt")}}
        self.assertEqual(subtitles.choose_subtitle(info, "en")["ext"], "vtt")
        info = {"subtitles": {"en": self.formats("ttml", "srt")}}
        self.assertEqual(subtitles.choose_subtitle(info, "en")["ext"], "srt")
        self.assertIsNone(subtitles.choose_subtitle({"subtitles": {"en": self.formats("ttml")}}, "en"))

    def test_none_when_language_is_missing_or_info_is_bad(self):
        self.assertIsNone(subtitles.choose_subtitle({"subtitles": {"de": self.formats("vtt")}}, "fa"))
        self.assertIsNone(subtitles.choose_subtitle({}, "en"))
        self.assertIsNone(subtitles.choose_subtitle(None, "en"))

    def test_normalize_language(self):
        self.assertEqual(subtitles.normalize_language("FA"), "fa")
        self.assertEqual(subtitles.normalize_language("en_US"), "en-us")
        for bad in ("", "f", "english_language_name", "fa!", "12", None):
            self.assertIsNone(subtitles.normalize_language(bad))


class FetchTest(unittest.TestCase):

    def test_fetch_uses_ytdlp_options_cookies_and_dedupes_only_auto(self):
        youtube = types.SimpleNamespace(_cookiefile="C:/cookies/youtube.txt")
        bot = types.SimpleNamespace(services={"youtube": youtube})
        info = {"subtitles": {}, "automatic_captions": {"en": [{"ext": "vtt", "url": "https://x/a.vtt"}]}}
        with mock.patch.object(subtitles.proxy_retry, "extract_pooled", return_value=info) as extract, \
                mock.patch.object(subtitles.net, "fetch",
                                  return_value=("u", ROLLING_VTT.encode("utf-8"))) as fetch:
            cues = subtitles.fetch_cues(bot, "https://www.youtube.com/watch?v=x", "en")
        opts = extract.call_args.args[1]
        self.assertTrue(opts["writesubtitles"] and opts["writeautomaticsub"])
        self.assertEqual(opts["subtitleslangs"], ["en"])
        self.assertTrue(opts["skip_download"])
        self.assertEqual(opts["cookiefile"], "C:/cookies/youtube.txt")
        self.assertEqual(fetch.call_args.args[0], "https://x/a.vtt")
        self.assertEqual([cue.text for cue in cues][:2], ["hello there everyone", "welcome to the show"])

    def test_manual_subtitles_keep_intentional_line_repeats(self):
        body = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nNo.\n\n00:00:03.000 --> 00:00:04.000\nNo.\n"
        info = {"subtitles": {"en": [{"ext": "vtt", "url": "https://x/m.vtt"}]}}
        with mock.patch.object(subtitles.proxy_retry, "extract_pooled", return_value=info), \
                mock.patch.object(subtitles.net, "fetch", return_value=("u", body.encode())):
            cues = subtitles.fetch_cues(types.SimpleNamespace(services={}), "https://y/", "en")
        self.assertEqual([cue.text for cue in cues], ["No.", "No."])

    def test_no_subtitles_returns_empty_without_downloading(self):
        with mock.patch.object(subtitles.proxy_retry, "extract_pooled", return_value={}), \
                mock.patch.object(subtitles.net, "fetch") as fetch:
            self.assertEqual(subtitles.fetch_cues(types.SimpleNamespace(services={}), "https://y/", "fa"), [])
        fetch.assert_not_called()


def make_bot(position=0.0, url="https://www.youtube.com/watch?v=a", index=0, epoch=1):
    """یه ربات ساختگی با صف/پلیر/تیم‌تاکِ کمینه؛ position با bot.player قابل‌تغییره."""
    bot = types.SimpleNamespace()
    bot.cfg = {"language": "en"}
    bot.services = {}
    bot.queue = types.SimpleNamespace(epoch=epoch, index=index)
    bot.track_meta = [{"public_url": url}, {"public_url": "https://www.youtube.com/watch?v=b"}]
    bot.player = types.SimpleNamespace(position_seconds=position, current_url="direct-stream-0")
    bot.t = mock.Mock()
    return bot


class SyncWorkers:
    """workers.submit همگام: تست بدونِ ترد و sleep."""

    def __call__(self, fn, *args, **kwargs):
        fn(*args, **kwargs)


class TickTest(unittest.TestCase):

    def setUp(self):
        i18n.load_languages()
        i18n.set_language("en")
        patcher = mock.patch.object(subtitles.workers, "submit", SyncWorkers())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fetch = mock.patch.object(subtitles, "fetch_cues")
        self.fetch_mock = self.fetch.start()
        self.addCleanup(self.fetch.stop)
        self.fetch_mock.return_value = [Cue(1, 3, "one"), Cue(4, 6, "two")]
        self.bot = make_bot()

    def sent(self):
        return [(call.args[0], call.args[1]) for call in self.bot.t.user_message.call_args_list]

    def run_tick(self, position, paused=False, current="direct-stream-0"):
        self.bot.player.position_seconds = position
        subtitles.tick(self.bot, current, paused)

    def test_off_by_default_and_costs_nothing(self):
        self.run_tick(1.5)
        self.fetch_mock.assert_not_called()
        self.bot.t.user_message.assert_not_called()
        self.assertEqual(subtitles.enabled_count(self.bot), 0)
        # حتی position هم خونده نمی‌شه (IPCِ mpv)
        reads = []

        class Player:
            current_url = "direct-stream-0"

            @property
            def position_seconds(self):
                reads.append(1)
                return 1.0

        self.bot.player = Player()
        subtitles.tick(self.bot, "direct-stream-0", False)
        self.assertEqual(reads, [])

    def test_cues_go_privately_to_each_enabled_user_at_their_time(self):
        subtitles.enable(self.bot, 11, "alice", "en")
        subtitles.enable(self.bot, 22, "bob", "en")
        self.run_tick(0.2)
        self.assertEqual(self.sent(), [])
        self.run_tick(1.1)
        self.assertEqual(sorted(self.sent()), [(11, "one"), (22, "one")])
        self.bot.t.channel_message.assert_not_called()
        # یه بار fetch برای هر زبان، نه برای هر کاربر
        self.assertEqual(self.fetch_mock.call_count, 1)

    def test_users_with_different_languages_get_their_own_subtitles(self):
        self.fetch_mock.side_effect = lambda bot, url, lang: [Cue(1, 3, f"text-{lang}")]
        subtitles.enable(self.bot, 11, "alice", "en")
        subtitles.enable(self.bot, 22, "bob", "fa")
        self.run_tick(0.0)
        self.run_tick(1.1)
        self.assertEqual(sorted(self.sent()), [(11, "text-en"), (22, "text-fa")])

    def test_disable_stops_sending_and_toggle_remembers_language(self):
        enabled, lang = subtitles.toggle(self.bot, 11, "alice")
        self.assertEqual((enabled, lang), (True, "en"))
        subtitles.enable(self.bot, 11, "alice", "fa")
        self.assertEqual(subtitles.toggle(self.bot, 11, "alice"), (False, "fa"))
        self.run_tick(1.1)
        self.assertEqual(self.sent(), [])
        self.assertEqual(subtitles.toggle(self.bot, 11, "alice"), (True, "fa"))

    def test_pause_sends_nothing_and_resume_continues(self):
        subtitles.enable(self.bot, 11, "alice", "en")
        self.run_tick(0.0)
        self.run_tick(1.1)
        self.bot.t.user_message.reset_mock()
        for _ in range(5):
            self.run_tick(1.1, paused=True)
        self.assertEqual(self.sent(), [])
        self.run_tick(4.1)  # resume: ۳ ثانیه جلوتر ولی زیر SEEK_GAP
        self.assertEqual(self.sent(), [(11, "two")])

    def test_seek_back_resends_and_seek_forward_skips(self):
        self.fetch_mock.return_value = [Cue(1, 3, "one"), Cue(4, 6, "two"), Cue(30, 32, "late")]
        subtitles.enable(self.bot, 11, "alice", "en")
        for position in (0.0, 1.1, 4.1):
            self.run_tick(position)
        self.bot.t.user_message.reset_mock()
        self.run_tick(2.0)
        self.assertEqual(self.sent(), [(11, "one")])
        self.bot.t.user_message.reset_mock()
        self.run_tick(31.0)
        self.assertEqual(self.sent(), [(11, "late")])

    def test_track_change_reloads_and_resyncs(self):
        subtitles.enable(self.bot, 11, "alice", "en")
        self.run_tick(0.0)
        self.run_tick(1.1)
        self.assertEqual(self.fetch_mock.call_count, 1)
        self.bot.t.user_message.reset_mock()
        self.fetch_mock.return_value = [Cue(0.5, 2, "next-track")]
        self.bot.queue.index = 1
        self.bot.player.current_url = "direct-stream-1"
        self.run_tick(0.6, current="direct-stream-1")
        self.assertEqual(self.fetch_mock.call_count, 2)
        self.assertEqual(self.fetch_mock.call_args.args[1], "https://www.youtube.com/watch?v=b")
        self.assertEqual(self.sent(), [(11, "next-track")])

    def test_repeat_of_same_track_does_not_refetch_but_replays(self):
        subtitles.enable(self.bot, 11, "alice", "en")
        for position in (0.0, 1.1, 4.1):
            self.run_tick(position)
        self.bot.t.user_message.reset_mock()
        self.run_tick(1.2)  # repeat-track: پرش به اولِ همون آهنگ
        self.assertEqual(self.fetch_mock.call_count, 1)
        self.assertEqual(self.sent(), [(11, "one")])

    def test_no_subtitles_tells_the_user_once_per_track_privately(self):
        self.fetch_mock.return_value = []
        subtitles.enable(self.bot, 11, "alice", "fa")
        for position in (0.0, 0.5, 1.0, 1.5):
            self.run_tick(position)
        self.assertEqual(self.sent(), [(11, i18n.t("sub_none", lang="fa"))])
        self.assertEqual(self.fetch_mock.call_count, 1)
        self.bot.t.channel_message.assert_not_called()
        # آهنگِ بعدی هم (اگه باز زیرنویس نداشت) یک‌بار خبر می‌ده
        self.bot.queue.index = 1
        self.run_tick(0.0, current="direct-stream-1")
        self.assertEqual(len(self.sent()), 2)

    def test_private_track_without_public_link_reports_no_subtitles_without_fetching(self):
        self.bot.track_meta = [{"public_url": None}]
        subtitles.enable(self.bot, 11, "alice", "en")
        self.run_tick(0.0)
        self.fetch_mock.assert_not_called()
        self.assertEqual(self.sent(), [(11, i18n.t("sub_none", lang="en"))])

    def test_fetch_failure_reports_generic_message_not_the_exception(self):
        self.fetch_mock.side_effect = RuntimeError("boom C:\\secret\\path")
        subtitles.enable(self.bot, 11, "alice", "en")
        self.run_tick(0.0)
        self.run_tick(0.5)
        messages = [text for _, text in self.sent()]
        self.assertEqual(len(messages), 1)
        self.assertIn(i18n.t("sub_failed"), messages[0])
        self.assertNotIn("boom", messages[0])
        self.assertNotIn("secret", messages[0])

    def test_user_who_logged_out_is_forgotten(self):
        subtitles.enable(self.bot, 11, "alice", "en")
        subtitles.enable(self.bot, 22, "bob", "en")
        subtitles._on_logged_out(self.bot, {"params": {"user": {"username": "alice"}}})
        self.assertEqual(subtitles.enabled_count(self.bot), 1)
        self.run_tick(0.0)
        self.run_tick(1.1)
        self.assertEqual(self.sent(), [(22, "one")])
        # برگشتنِ alice: دوباره خاموشه تا خودش sub بزنه
        self.assertEqual(subtitles.toggle(self.bot, 33, "alice"), (True, "en"))

    def test_connection_loss_forgets_everyone(self):
        subtitles.enable(self.bot, 11, "alice", "en")
        subtitles.forget_all(self.bot)
        self.assertEqual(subtitles.enabled_count(self.bot), 0)

    def test_kick_from_a_channel_keeps_state_but_server_kick_clears(self):
        subtitles.enable(self.bot, 11, "alice", "en")
        subtitles._on_kicked(self.bot, {"params": {"channel_id": 5}})
        self.assertEqual(subtitles.enabled_count(self.bot), 1)
        subtitles._on_kicked(self.bot, {"params": {"channel_id": 0}})
        self.assertEqual(subtitles.enabled_count(self.bot), 0)

    def test_nothing_playing_drops_the_loaded_track(self):
        subtitles.enable(self.bot, 11, "alice", "en")
        self.run_tick(0.0)
        subtitles.tick(self.bot, None, False)
        self.assertIsNone(subtitles._peek(self.bot).key)

    def test_safe_tick_never_raises_and_logs_once(self):
        subtitles.enable(self.bot, 11, "alice", "en")
        with mock.patch.object(subtitles, "tick", side_effect=RuntimeError("x")), \
                mock.patch.object(subtitles.logging_setup, "log_exception") as logged:
            subtitles.safe_tick(self.bot, "f", False)
            subtitles.safe_tick(self.bot, "f", False)
        self.assertEqual(logged.call_count, 1)

    def test_default_language_follows_bot_language_or_config(self):
        self.assertEqual(subtitles.default_language(self.bot), "en")
        self.bot.cfg["language"] = "fa"
        self.assertEqual(subtitles.default_language(self.bot), "fa")
        self.bot.cfg["subtitles"] = {"default_language": "de"}
        self.assertEqual(subtitles.default_language(self.bot), "de")


class SubCommandTest(unittest.TestCase):

    def setUp(self):
        i18n.load_languages()
        i18n.set_language("en")
        self.sub = load_command("sub")
        self.bot = make_bot()

    def call(self, *args):
        self.bot.t.user_message.reset_mock()
        self.sub.run({"bot": self.bot, "uid": 7, "username": "alice", "nickname": "Alice", "args": list(args)})
        return [call.args for call in self.bot.t.user_message.call_args_list]

    def test_toggle_language_and_private_replies(self):
        self.assertEqual(self.call(), [(7, i18n.t("sub_on", lang="en"))])
        self.assertEqual(subtitles.enabled_count(self.bot), 1)
        self.assertEqual(self.call(), [(7, i18n.t("sub_off"))])
        self.assertEqual(subtitles.enabled_count(self.bot), 0)
        self.assertEqual(self.call("fa"), [(7, i18n.t("sub_on", lang="fa"))])
        self.assertEqual(self.call("FA"), [(7, i18n.t("sub_on", lang="fa"))])  # دوباره ست = هنوز روشن
        self.assertEqual(subtitles.enabled_count(self.bot), 1)
        self.assertEqual(self.call("off"), [(7, i18n.t("sub_off"))])
        self.assertEqual(self.call("on"), [(7, i18n.t("sub_on", lang="fa"))])
        self.bot.t.channel_message.assert_not_called()

    def test_bad_language_gets_usage_and_changes_nothing(self):
        self.assertEqual(self.call("not a language!"), [(7, i18n.t("sub_bad_lang"))])
        self.assertEqual(subtitles.enabled_count(self.bot), 0)

    def test_is_free_and_in_help(self):
        from licensing import catalog
        self.assertIn("sub", catalog.BASE_COMMANDS)
        self.assertIsNone(catalog.service_for_command("sub"))
        self.assertEqual(self.sub.NAME, "sub")
        self.assertTrue(self.sub.USAGE)
        self.assertFalse(hasattr(self.sub, "REQUIRED_ROLE"))


if __name__ == "__main__":
    unittest.main()

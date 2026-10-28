"""
تست‌های جستجوی صوتی (roadmap C3): تبدیل PCM، ماشین‌حالتِ ضبط (بدونِ
هیچ نخ/تایمرِ واقعی -- core.voice_search._collect یه تابعِ خالصه)،
موتورهای core/stt.py (با mock کردنِ urllib)، اعتبارسنجی/ماسکِ تنظیمات،
و ثبتِ درستِ کاتالوگ. هیچ تستی نه شبکه‌ی واقعی می‌زنه، نه به DLL تیم‌تاک
نیاز داره -- core/voice_search.py عمداً طوری نوشته شده که هیچ‌وقت
teamtalk.TeamTalk5 رو import نکنه (توضیحش بالای همون فایل).
"""

import io
import json
import os
import struct
import unittest
import urllib.error
from array import array
from unittest import mock

from core import voice_search as vs
from core import stt
from licensing import catalog
from tests.helpers import load_command

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def pcm16(values):
    return struct.pack("<%dh" % len(values), *values)


def make_block(pcm, sample_rate=16000, channels=1, user_id=1, stream_type=vs.STREAM_TYPE_VOICE):
    return {"user_id": user_id, "sample_rate": sample_rate, "channels": channels,
            "pcm": pcm, "stream_type": stream_type, "stream_id": 1}


class FakeTT:
    """
    بدنه‌ی حداقلیِ bot.t که core.voice_search واقعاً صداش می‌زنه. هیچ
    اتصال واقعی‌ای برقرار نمی‌کنه؛ فقط تماس‌ها رو ثبت می‌کنه تا تست‌ها
    ترتیب/تعدادشون رو چک کنن.
    """

    def __init__(self, in_channel=True, admin=False, output_ready=False, subscribe_ok=True):
        self.in_channel = in_channel
        self.admin = admin
        self._output_ready = output_ready
        self.subscribe_ok = subscribe_ok
        self.no_recording = False
        self.sent = []
        self.calls = []
        self.voice_held = set()

    def user_message(self, uid, text):
        self.sent.append((uid, text))

    def get_user_info(self, uid):
        return {"channel_id": 1 if self.in_channel else 2}

    def get_my_channel_id(self):
        return 1

    def is_server_admin(self):
        return self.admin

    def sound_output_ready(self):
        return self._output_ready

    def recording_blocked(self):
        return self.no_recording

    def open_virtual_sound_output(self):
        self.calls.append("open_output")
        return True

    def close_sound_output(self):
        self.calls.append("close_output")
        return True

    def hold_voice(self, uid):
        self.calls.append(("hold_voice", uid))
        self.voice_held.add(uid)

    def release_voice(self, uid):
        self.calls.append(("release_voice", uid))
        self.voice_held.discard(uid)

    def enable_audio_blocks(self, uid, enable=True):
        self.calls.append(("enable_audio_blocks", uid, enable))
        return True

    def listen_to_voice(self, uid, intercept=False):
        self.calls.append(("listen_to_voice", uid, intercept))
        return self.subscribe_ok

    def stop_listening_to_voice(self, uid, intercept=False):
        self.calls.append(("stop_listening_to_voice", uid, intercept))
        return True


class FakeBot:
    def __init__(self, cfg=None, in_channel=True, admin=False, subscribe_ok=True):
        self.cfg = cfg if cfg is not None else {}
        self.t = FakeTT(in_channel=in_channel, admin=admin, subscribe_ok=subscribe_ok)
        self.save_config = mock.Mock()
        self.channel_messages_enabled = True
        self.channel_broadcast = mock.Mock(side_effect=lambda text: self.sent_channel.append(text))
        self.sent_channel = []
        self.services = {}
        self.current_service_index = 0
        self.commands = {"p": {"handler": mock.Mock(), "role": "normal", "usage": "p [query]"}}


def ctx(bot, args=None, uid=1, nickname="Nick", username="user1"):
    return {"bot": bot, "uid": uid, "args": args or [], "nickname": nickname,
            "username": username, "cmd": "vs", "raw": ""}


# ------------------------------------------------------------- تبدیلِ PCM

class PcmConversionTest(unittest.TestCase):

    def test_mono_same_rate_is_unchanged(self):
        data = pcm16([100, -100, 200, -200])
        out = vs.to_mono16k(data, 16000, 1)
        self.assertEqual(out, data)

    def test_stereo_is_downmixed_to_mono(self):
        # چپ=1000، راست=-1000 -> میانگین صفر.
        data = pcm16([1000, -1000] * 50)
        out = vs.to_mono16k(data, 16000, 2)
        values = array("h")
        values.frombytes(out)
        self.assertTrue(all(v == 0 for v in values))
        self.assertEqual(len(values), 50)

    def test_resample_changes_length_proportionally(self):
        data = pcm16([1000] * 800)  # 800 sample، ۸۰۰۰ هرتز -> ۰.۱ ثانیه
        out = vs.to_mono16k(data, 8000, 1)
        values = array("h")
        values.frombytes(out)
        # ۰.۱ ثانیه‌ی ۱۶۰۰۰هرتزی یعنی ۱۶۰۰ نمونه.
        self.assertEqual(len(values), 1600)

    def test_empty_or_missing_format_returns_empty(self):
        self.assertEqual(vs.to_mono16k(b"", 16000, 1), b"")
        self.assertEqual(vs.to_mono16k(b"\x00\x00", 0, 1), b"")
        self.assertEqual(vs.to_mono16k(b"\x00\x00", 16000, 0), b"")

    def test_duration_seconds(self):
        data = pcm16([0] * 16000)  # ۱۶۰۰۰ نمونه، مونو، ۱۶کیلوهرتز -> ۱ ثانیه
        self.assertAlmostEqual(vs.pcm_duration_seconds(data, 16000, 1), 1.0)
        self.assertEqual(vs.pcm_duration_seconds(b"", 16000, 1), 0.0)

    def test_nothing_touches_disk(self):
        data = pcm16([1, 2, 3, 4] * 10)
        with mock.patch("builtins.open", side_effect=AssertionError("must not touch disk")):
            vs.to_mono16k(data, 8000, 2)
            stt.wav_bytes(data)
            stt.multipart_body([("a", "b")], [("file", "x.wav", "audio/wav", data)])


# --------------------------------------------------------------- append/collect

class AppendBlockTest(unittest.TestCase):

    def test_first_block_sets_format(self):
        session = vs._Session(1, "N", "u")
        vs._append_block(session, make_block(pcm16([1, 2]), sample_rate=16000, channels=1))
        self.assertEqual(session.sample_rate, 16000)
        self.assertEqual(session.channels, 1)
        self.assertEqual(bytes(session.buffer), pcm16([1, 2]))

    def test_later_block_with_other_format_is_converted_not_dropped(self):
        # قبلاً فرمتِ اولین بلوک قفل می‌شد و این بلوک دور ریخته می‌شد.
        session = vs._Session(1, "N", "u")
        vs._append_block(session, make_block(pcm16([1, 2]), sample_rate=16000, channels=1))
        vs._append_block(session, make_block(pcm16([3, 4]), sample_rate=8000, channels=1))
        self.assertGreater(len(session.buffer), len(pcm16([1, 2])))
        self.assertEqual(bytes(session.buffer[:4]), pcm16([1, 2]))

    def test_empty_first_block_does_not_lock_out_real_audio(self):
        # باگِ گزارش‌شده («همیشه خیلی کوتاه»): یه بلوکِ خالی/بی‌نرخِ اول،
        # همه‌ی صدای واقعیِ بعدی رو «فرمتِ ناجور» حساب می‌کرد.
        session = vs._Session(1, "N", "u")
        vs._append_block(session, make_block(b"", sample_rate=0, channels=2))
        voice = pcm16(list(range(480)))
        for _ in range(10):
            vs._append_block(session, make_block(voice, sample_rate=48000, channels=2))
        self.assertEqual(session.sample_rate, 16000)
        self.assertEqual(session.channels, 1)
        self.assertEqual(session.blocks_empty, 1)
        # ۱۰ بلوکِ ۲۴۰ فریمیِ ۴۸کیلوهرتزِ استریو -> ~۵۰ms در ۱۶کیلوهرتزِ مونو
        duration = vs.pcm_duration_seconds(bytes(session.buffer), 16000, 1)
        self.assertAlmostEqual(duration, 0.05, delta=0.005)

    def test_stereo_48k_blocks_are_downmixed_and_resampled(self):
        session = vs._Session(1, "N", "u")
        vs._append_block(session, make_block(pcm16([100, 300] * 480), sample_rate=48000, channels=2))
        samples = vs._samples_from_pcm16(bytes(session.buffer))
        self.assertEqual(len(samples), 160)
        self.assertTrue(all(value == 200 for value in samples))


class CollectStateMachineTest(unittest.TestCase):
    """
    core.voice_search._collect یه تابعِ خالصه (session, cfg) -> نتیجه؛ برای
    تست‌های سریع، رویدادها از قبل توی session.queue گذاشته می‌شن (queue.get
    فوراً برمی‌گردونتشون) و فقط مهلت‌ها خیلی کوچیکن تا خودِ تست‌ها سریع تموم بشن.
    """

    def _cfg(self, **overrides):
        cfg = dict(vs.DEFAULTS)
        cfg.update({"start_timeout_seconds": 0.05, "max_seconds": 0.2, "silence_seconds": 0.05})
        cfg.update(overrides)
        return cfg

    def test_no_speech_times_out(self):
        session = vs._Session(1, "N", "u")
        pcm, sr, ch, outcome = vs._collect(session, self._cfg())
        self.assertEqual(outcome, "no_speech")
        self.assertEqual(pcm, b"")
        self.assertIsNone(sr)
        self.assertIsNone(ch)

    def test_gone_before_any_speech(self):
        session = vs._Session(1, "N", "u")
        session.queue.put(("gone", None))
        pcm, sr, ch, outcome = vs._collect(session, self._cfg())
        self.assertEqual(outcome, "gone")

    def test_end_of_speech_after_silence_grace(self):
        session = vs._Session(1, "N", "u")
        session.queue.put(("talking", True))
        block1 = make_block(pcm16([1, 2, 3]))
        block2 = make_block(pcm16([4, 5, 6]))
        session.queue.put(("audio", block1))
        session.queue.put(("audio", block2))
        session.queue.put(("talking", False))
        pcm, sr, ch, outcome = vs._collect(session, self._cfg())
        self.assertEqual(outcome, "end_of_speech")
        self.assertEqual(pcm, pcm16([1, 2, 3, 4, 5, 6]))
        self.assertEqual(sr, 16000)
        self.assertEqual(ch, 1)

    def test_max_duration_cuts_off_continuous_speech(self):
        session = vs._Session(1, "N", "u")
        session.queue.put(("talking", True))
        session.queue.put(("audio", make_block(pcm16([1, 2]))))
        # هیچ‌وقت "talking"->False نمی‌فرستیم؛ فقط سقفِ max_seconds باید
        # جمع‌کردن رو تموم کنه.
        pcm, sr, ch, outcome = vs._collect(session, self._cfg(max_seconds=0.05))
        self.assertEqual(outcome, "max_duration")
        self.assertEqual(pcm, pcm16([1, 2]))

    def test_resuming_before_silence_grace_expires_keeps_recording(self):
        session = vs._Session(1, "N", "u")
        session.queue.put(("talking", True))
        session.queue.put(("audio", make_block(pcm16([1]))))
        session.queue.put(("talking", False))  # شروعِ مهلتِ سکوت
        session.queue.put(("talking", True))   # قبل از تمومِ مهلت دوباره حرف زد
        session.queue.put(("audio", make_block(pcm16([2]))))
        session.queue.put(("talking", False))  # این‌بار واقعاً تمومِ حرف
        pcm, sr, ch, outcome = vs._collect(session, self._cfg(silence_seconds=0.2, max_seconds=5))
        self.assertEqual(outcome, "end_of_speech")
        self.assertEqual(pcm, pcm16([1, 2]))

    def test_leading_audio_block_counts_as_start_of_speech(self):
        # بعضی وقت‌ها بلوکِ صدا قبل از خودِ USERSTATE_VOICE می‌رسه.
        session = vs._Session(1, "N", "u")
        session.queue.put(("audio", make_block(pcm16([9, 9]))))
        session.queue.put(("talking", False))
        pcm, sr, ch, outcome = vs._collect(session, self._cfg(silence_seconds=0.02))
        self.assertEqual(outcome, "end_of_speech")
        self.assertEqual(pcm, pcm16([9, 9]))

    def test_gone_mid_recording_stops_and_keeps_partial_audio(self):
        session = vs._Session(1, "N", "u")
        session.queue.put(("talking", True))
        session.queue.put(("audio", make_block(pcm16([7]))))
        session.queue.put(("gone", None))
        pcm, sr, ch, outcome = vs._collect(session, self._cfg(max_seconds=5))
        self.assertEqual(outcome, "gone")
        self.assertEqual(pcm, pcm16([7]))


# --------------------------------------------------------------- start()/busy/cleanup

class StartFlowTest(unittest.TestCase):

    def test_busy_when_a_session_is_already_active(self):
        bot = FakeBot()
        bot._voice_search_session = vs._Session(99, "Other", "other")
        vs.start(bot, ctx(bot, uid=2))
        from core import i18n
        # پیامِ واقعی که فرستاده شده دقیقاً پیامِ busy است.
        self.assertEqual(bot.t.sent, [(2, i18n.t("vs_busy"))])
        # چون claim نشده، هیچ عملیاتی روی TeamTalk انجام نشده.
        self.assertEqual(bot.t.calls, [])

    def test_not_in_channel_without_intercept_refuses(self):
        bot = FakeBot(in_channel=False, admin=False)
        vs.start(bot, ctx(bot))
        from core import i18n
        self.assertEqual(bot.t.sent, [(1, i18n.t("vs_not_in_channel"))])
        self.assertIsNone(bot._voice_search_session)

    def test_not_in_channel_with_admin_intercept_is_allowed(self):
        bot = FakeBot(in_channel=False, admin=True)
        with mock.patch.object(vs, "_collect", return_value=(b"", None, None, "no_speech")):
            vs.start(bot, ctx(bot))
        # نه پیامِ رد؛ به‌جاش تا سرِ no_speech رفته.
        from core import i18n
        self.assertEqual(bot.t.sent, [
            (1, i18n.t("vs_listening", seconds=8)),
            (1, i18n.t("vs_no_speech")),
        ])
        listen_calls = [c for c in bot.t.calls if c[0] == "listen_to_voice"]
        self.assertEqual(listen_calls, [("listen_to_voice", 1, True)])

    def test_cleanup_always_runs_even_when_collect_raises(self):
        bot = FakeBot()
        with mock.patch.object(vs, "_collect", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                vs.start(bot, ctx(bot))
        self.assertIn(("release_voice", 1), bot.t.calls)
        self.assertIn(("enable_audio_blocks", 1, False), bot.t.calls)
        self.assertIn(("stop_listening_to_voice", 1, False), bot.t.calls)
        # سشن حتماً آزاد شده، وگرنه دیگه هیچ‌کس نمی‌تونست جستجوی صوتیِ بعدی رو بزنه.
        self.assertIsNone(bot._voice_search_session)

    def test_cleanup_runs_even_when_the_engine_fails(self):
        bot = FakeBot()
        loud = pcm16([100] * 16000)  # ۱ ثانیه، بالای min_seconds
        with mock.patch.object(vs, "_collect", return_value=(loud, 16000, 1, "end_of_speech")):
            with mock.patch.object(stt, "create_engine", side_effect=stt.SpeechToTextError("network down")):
                vs.start(bot, ctx(bot))
        self.assertIn(("release_voice", 1), bot.t.calls)
        self.assertIn(("stop_listening_to_voice", 1, False), bot.t.calls)
        from core import i18n
        self.assertEqual(bot.t.sent[-1], (1, i18n.t("vs_recognize_failed", error="network down")))

    def test_too_short_recording_is_dropped(self):
        bot = FakeBot()
        tiny = pcm16([1] * 100)  # ۱۰۰ نمونه از ۱۶کیلوهرتز یعنی خیلی کمتر از min_seconds
        with mock.patch.object(vs, "_collect", return_value=(tiny, 16000, 1, "end_of_speech")):
            vs.start(bot, ctx(bot))
        from core import i18n
        self.assertEqual(bot.t.sent, [(1, i18n.t("vs_listening", seconds=8)), (1, i18n.t("vs_too_short"))])

    def test_no_recording_channel_explains_the_real_reason(self):
        # گزارشِ واقعی از سرورِ دوم: talking_events=2 ولی blocks=0 -- کانال
        # «No recording» بود؛ قبلاً فقط «خیلی کوتاه بود» می‌گفت.
        from core import i18n
        bot = FakeBot()
        bot.t.no_recording = True
        with mock.patch.object(vs, "_collect") as collect:
            vs.start(bot, ctx(bot))
        collect.assert_not_called()
        self.assertEqual(bot.t.sent, [(1, i18n.t("vs_no_recording"))])
        self.assertNotIn("listen_to_voice", [c[0] for c in bot.t.calls if isinstance(c, tuple)])
        # سشن آزاد شده و هر چیزی که باز شده بود بسته شده.
        self.assertIsNone(bot._voice_search_session)

    def test_recording_check_failure_does_not_block_voice_search(self):
        bot = FakeBot()
        bot.t.recording_blocked = mock.Mock(side_effect=RuntimeError("old sdk"))
        with mock.patch.object(vs, "_collect", return_value=(b"", None, None, "no_speech")) as collect:
            vs.start(bot, ctx(bot))
        collect.assert_called_once()

    def test_too_short_shows_diagnostics_to_admins_only(self):
        # مشکلی که فقط روی یه سرور پیش میاد: ادمین بدونِ سر زدن به لاگِ
        # سرور ببینه بلوک‌های صدا اصلاً رسیدن یا نه.
        from core import i18n, roles
        tiny = pcm16([1] * 100)
        for is_admin, expected_count in ((True, 3), (False, 2)):
            bot = FakeBot()
            with mock.patch.object(vs, "_collect", return_value=(tiny, 16000, 1, "end_of_speech")),                  mock.patch.object(roles, "has_role", return_value=is_admin):
                vs.start(bot, ctx(bot))
            self.assertEqual(len(bot.t.sent), expected_count)
            self.assertEqual(bot.t.sent[1], (1, i18n.t("vs_too_short")))
            if is_admin:
                text = bot.t.sent[2][1]
                self.assertIn("blocks=", text)
                self.assertIn("min_seconds=", text)

    def test_happy_path_runs_p_with_the_recognized_text(self):
        bot = FakeBot()
        loud = pcm16([1000] * 16000)  # ۱ ثانیه، قطعاً بالای min_seconds
        with mock.patch.object(vs, "_collect", return_value=(loud, 16000, 1, "end_of_speech")):
            with mock.patch.object(stt, "create_engine") as create_engine:
                engine = mock.Mock()
                engine.transcribe.return_value = "some song"
                create_engine.return_value = engine
                vs.start(bot, ctx(bot))
        p_handler = bot.commands["p"]["handler"]
        p_handler.assert_called_once()
        called_ctx = p_handler.call_args[0][0]
        self.assertEqual(called_ctx["args"], ["some", "song"])
        self.assertEqual(called_ctx["cmd"], "p")
        from core import i18n
        self.assertIn((1, i18n.t("vs_heard", text="some song")), bot.t.sent)

    def test_empty_transcription_does_not_run_a_search(self):
        bot = FakeBot()
        loud = pcm16([1000] * 16000)
        with mock.patch.object(vs, "_collect", return_value=(loud, 16000, 1, "end_of_speech")):
            with mock.patch.object(stt, "create_engine") as create_engine:
                engine = mock.Mock()
                engine.transcribe.return_value = "   "
                create_engine.return_value = engine
                vs.start(bot, ctx(bot))
        bot.commands["p"]["handler"].assert_not_called()

    def test_configured_service_is_selected_then_restored(self):
        bot = FakeBot(cfg={"voice_search": {"service": "soundcloud"}})
        bot.services = {"youtube": object(), "soundcloud": object()}
        bot.current_service_index = 0
        loud = pcm16([1000] * 16000)

        def fake_p_handler(search_ctx):
            # موقعِ اجرای p، ایندکس باید روی سرویسِ تنظیم‌شده باشه.
            self.assertEqual(bot.current_service_index, 1)
        bot.commands["p"]["handler"] = mock.Mock(side_effect=fake_p_handler)

        with mock.patch.object(vs, "_collect", return_value=(loud, 16000, 1, "end_of_speech")):
            with mock.patch.object(stt, "create_engine") as create_engine:
                engine = mock.Mock()
                engine.transcribe.return_value = "x"
                create_engine.return_value = engine
                vs.start(bot, ctx(bot))
        # بعد از تمومِ جستجو، ایندکسِ اصلی برگشته.
        self.assertEqual(bot.current_service_index, 0)

    def test_cancel_with_no_active_session(self):
        bot = FakeBot()
        vs.cancel(bot, ctx(bot))
        from core import i18n
        self.assertEqual(bot.t.sent, [(1, i18n.t("vs_cancel_nothing"))])

    def test_cancel_by_someone_else_notifies_canceller(self):
        bot = FakeBot()
        session = vs._Session(1, "N", "u")
        bot._voice_search_session = session
        vs.cancel(bot, ctx(bot, uid=2))
        self.assertEqual(session.queue.get_nowait(), ("gone", None))
        from core import i18n
        self.assertEqual(bot.t.sent, [(2, i18n.t("vs_cancelled"))])

    def test_bad_language_argument_shows_usage(self):
        bot = FakeBot()
        vs.start(bot, ctx(bot), language_override="please play some music")
        from core import i18n
        self.assertEqual(bot.t.sent, [(1, i18n.t("usage_generic", usage=vs.USAGE_VS))])
        self.assertIsNone(getattr(bot, "_voice_search_session", None))


class LanguageTest(unittest.TestCase):

    def test_looks_like_language_code(self):
        self.assertTrue(vs.looks_like_language_code("en"))
        self.assertTrue(vs.looks_like_language_code("fa-IR"))
        self.assertTrue(vs.looks_like_language_code("en-US"))
        self.assertFalse(vs.looks_like_language_code("please search this"))
        self.assertFalse(vs.looks_like_language_code(""))

    def test_default_language_follows_bot_language(self):
        from core import i18n
        i18n.load_languages()
        original = i18n.current_language()[0]
        try:
            i18n.set_language("fa")
            self.assertEqual(vs.default_language_for_bot(None), "fa-IR")
            i18n.set_language("en")
            self.assertEqual(vs.default_language_for_bot(None), "en-US")
        finally:
            i18n.set_language(original)

    def test_effective_language_prefers_override_then_config_then_bot_default(self):
        bot = FakeBot(cfg={"voice_search": {"language": "de-DE"}})
        self.assertEqual(vs.effective_language(bot, "fr"), "fr")
        self.assertEqual(vs.effective_language(bot, None), "de-DE")
        bot2 = FakeBot()
        from core import i18n
        original = i18n.current_language()[0]
        try:
            i18n.set_language("en")
            self.assertEqual(vs.effective_language(bot2, None), "en-US")
        finally:
            i18n.set_language(original)


# ---------------------------------------------------------------- تنظیمات

class SettingsValidationTest(unittest.TestCase):

    def test_unknown_key(self):
        self.assertEqual(vs.validate("nope", "x"), (None, "unknown_key"))

    def test_bool_key(self):
        self.assertEqual(vs.validate("announce", "true"), (True, None))
        self.assertEqual(vs.validate("announce", "FALSE"), (False, None))
        self.assertEqual(vs.validate("announce", "yes"), (None, "bool"))

    def test_range_key(self):
        self.assertEqual(vs.validate("max_seconds", "15"), (15.0, None))
        self.assertEqual(vs.validate("max_seconds", "abc"), (None, "number"))
        ok, err = vs.validate("max_seconds", "0")
        self.assertIsNone(ok)
        self.assertTrue(err.startswith("range:"))

    def test_engine_choice(self):
        self.assertEqual(vs.validate("engine", "google"), ("google", None))
        self.assertEqual(vs.validate("engine", "openai"), ("openai", None))
        ok, err = vs.validate("engine", "bogus")
        self.assertIsNone(ok)
        self.assertTrue(err.startswith("choice:"))

    def test_string_key_is_trimmed_and_unrestricted(self):
        self.assertEqual(vs.validate("language", "  fa-IR  "), ("fa-IR", None))
        self.assertEqual(vs.validate("service", ""), ("", None))

    def test_set_setting_persists_on_success(self):
        bot = FakeBot()
        ok, error, value = vs.set_setting(bot, "max_seconds", "12")
        self.assertTrue(ok)
        self.assertIsNone(error)
        self.assertEqual(value, 12.0)
        self.assertEqual(bot.cfg["voice_search"]["max_seconds"], 12.0)
        bot.save_config.assert_called_once()

    def test_set_setting_does_not_save_on_error(self):
        bot = FakeBot()
        ok, error, value = vs.set_setting(bot, "engine", "bogus")
        self.assertFalse(ok)
        self.assertIsNotNone(error)
        self.assertIsNone(value)
        bot.save_config.assert_not_called()
        self.assertNotIn("voice_search", bot.cfg)

    def test_settings_merge_defaults_with_stored_values(self):
        bot = FakeBot(cfg={"voice_search": {"engine": "openai"}})
        current = vs.settings(bot)
        self.assertEqual(current["engine"], "openai")
        self.assertEqual(current["max_seconds"], vs.DEFAULTS["max_seconds"])


class MaskingTest(unittest.TestCase):

    def test_secret_keys_are_masked(self):
        masked = vs.mask_value("google_key", "AIzaSyBOti4mM-6x9WDnZIjIeyEU21OpBXqWBgw")
        self.assertNotEqual(masked, "AIzaSyBOti4mM-6x9WDnZIjIeyEU21OpBXqWBgw")
        self.assertIn("*", masked)
        self.assertTrue(masked.startswith("AIz"))

    def test_short_secret_is_fully_masked(self):
        self.assertEqual(vs.mask_value("openai_api_key", "abcd"), "****")

    def test_empty_secret_stays_empty(self):
        self.assertEqual(vs.mask_value("openai_api_key", ""), "")

    def test_non_secret_keys_are_not_masked(self):
        self.assertEqual(vs.mask_value("language", "fa-IR"), "fa-IR")
        self.assertEqual(vs.mask_value("max_seconds", 10), 10)

    def test_display_settings_masks_only_secrets_and_keeps_order(self):
        bot = FakeBot(cfg={"voice_search": {"openai_api_key": "supersecretvalue"}})
        rows = vs.display_settings(bot)
        keys = [k for k, _ in rows]
        self.assertEqual(keys, list(vs.SETTINGS_ORDER))
        by_key = dict(rows)
        self.assertNotIn("supersecretvalue", str(by_key["openai_api_key"]))


class InstallTest(unittest.TestCase):

    def test_install_subscribes_to_the_expected_events(self):
        bot = FakeBot()
        bot.t = mock.Mock()
        recorded = []
        bot.t.subscribe.side_effect = lambda name: recorded.append(name) or (lambda f: f)
        vs.install(bot)
        self.assertEqual(sorted(recorded), sorted([
            "user_state_changed", "user_audio_block", "user_left",
            "connection_lost", "connection_failed", "kicked",
        ]))


class EventRoutingTest(unittest.TestCase):
    """
    _on_* توابعِ subscriber ان -- همون‌هایی که install() به bot.t وصل
    می‌کنه. تستشون بدونِ نیاز به یه TTBot واقعی، مستقیم صداشون می‌زنه.
    """

    def test_state_change_for_other_user_is_ignored(self):
        bot = FakeBot()
        session = vs._Session(1, "N", "u")
        bot._voice_search_session = session
        vs._on_state_changed(bot, {"params": {"user": {"user_id": 2, "talking": True}}})
        self.assertTrue(session.queue.empty())

    def test_state_change_for_the_session_user_is_queued(self):
        bot = FakeBot()
        session = vs._Session(1, "N", "u")
        bot._voice_search_session = session
        vs._on_state_changed(bot, {"params": {"user": {"user_id": 1, "talking": True}}})
        self.assertEqual(session.queue.get_nowait(), ("talking", True))

    def test_audio_block_for_a_different_stream_type_is_ignored(self):
        bot = FakeBot()
        session = vs._Session(1, "N", "u")
        bot._voice_search_session = session
        vs._on_audio_block(bot, {"params": make_block(b"\x00\x00", stream_type=999, user_id=1)})
        self.assertTrue(session.queue.empty())

    def test_audio_block_for_the_session_user_is_queued(self):
        bot = FakeBot()
        session = vs._Session(1, "N", "u")
        bot._voice_search_session = session
        block = make_block(b"\x00\x00", user_id=1)
        vs._on_audio_block(bot, {"params": block})
        self.assertEqual(session.queue.get_nowait(), ("audio", block))

    def test_no_active_session_means_events_are_dropped_silently(self):
        bot = FakeBot()
        # نباید Exception بده حتی اگه سشنی نباشه.
        vs._on_state_changed(bot, {"params": {"user": {"user_id": 1, "talking": True}}})
        vs._on_audio_block(bot, {"params": make_block(b"\x00\x00")})
        vs._on_user_left(bot, {"params": {"user": {"user_id": 1}}})
        vs._on_disconnect(bot, {"params": {}})

    def test_disconnect_stops_the_session_regardless_of_user(self):
        bot = FakeBot()
        session = vs._Session(1, "N", "u")
        bot._voice_search_session = session
        vs._on_disconnect(bot, {"params": {}})
        self.assertEqual(session.queue.get_nowait(), ("gone", None))

    def test_user_left_only_matches_the_session_user(self):
        bot = FakeBot()
        session = vs._Session(1, "N", "u")
        bot._voice_search_session = session
        vs._on_user_left(bot, {"params": {"user": {"user_id": 2}}})
        self.assertTrue(session.queue.empty())
        vs._on_user_left(bot, {"params": {"user": {"user_id": 1}}})
        self.assertEqual(session.queue.get_nowait(), ("gone", None))


# ----------------------------------------------------------------- commands/

class CommandFilesTest(unittest.TestCase):

    def test_vs_cancel_delegates_to_cancel(self):
        vs_cmd = load_command("vs")
        bot = FakeBot()
        with mock.patch.object(vs, "cancel") as cancel_fn:
            vs_cmd.run(ctx(bot, args=["cancel"]))
        cancel_fn.assert_called_once()

    def test_vs_forwards_language_argument(self):
        vs_cmd = load_command("vs")
        bot = FakeBot()
        with mock.patch.object(vs, "start") as start_fn:
            vs_cmd.run(ctx(bot, args=["fa-IR"]))
        start_fn.assert_called_once()
        self.assertEqual(start_fn.call_args[1].get("language_override"), "fa-IR")

    def test_vs_too_many_args_shows_usage(self):
        vs_cmd = load_command("vs")
        bot = FakeBot()
        bot.commands["vs"] = {"handler": vs_cmd.run, "role": "normal", "usage": vs_cmd.USAGE}
        vs_cmd.run(ctx(bot, args=["fa-IR", "extra"]))
        from core import i18n
        self.assertEqual(bot.t.sent, [(1, i18n.t("usage_generic", usage=vs_cmd.USAGE))])

    def test_vss_shows_settings_with_masking(self):
        vss_cmd = load_command("vss")
        bot = FakeBot(cfg={"voice_search": {"openai_api_key": "supersecretvalue"}})
        bot.send_long_text = lambda send_fn, text: send_fn(text)
        vss_cmd.run(ctx(bot, args=[]))
        self.assertEqual(len(bot.t.sent), 1)
        text = bot.t.sent[0][1]
        self.assertNotIn("supersecretvalue", text)
        self.assertIn("engine", text)

    def test_vss_sets_a_key(self):
        vss_cmd = load_command("vss")
        bot = FakeBot()
        vss_cmd.run(ctx(bot, args=["max_seconds", "20"]))
        self.assertEqual(bot.cfg["voice_search"]["max_seconds"], 20.0)

    def test_vss_invalid_value_does_not_change_config(self):
        vss_cmd = load_command("vss")
        bot = FakeBot()
        vss_cmd.run(ctx(bot, args=["engine", "bogus"]))
        self.assertNotIn("voice_search", bot.cfg)
        self.assertTrue(bot.t.sent)

    def test_vss_missing_value_shows_usage(self):
        vss_cmd = load_command("vss")
        bot = FakeBot()
        bot.commands["vss"] = {"handler": vss_cmd.run, "role": "admin_bot", "usage": vss_cmd.USAGE}
        vss_cmd.run(ctx(bot, args=["engine"]))
        from core import i18n
        self.assertEqual(bot.t.sent, [(1, i18n.t("usage_generic", usage=vss_cmd.USAGE))])


# --------------------------------------------------------- core/stt.py: موتورها

class ErrorMessageSafetyTest(unittest.TestCase):
    """
    هیچ متنِ خامِ exception ای نباید مستقیم (بدون رد شدن از
    core.logging_setup.safe_error_text) به کاربر برسه -- نه STT، نه هیچ
    خطای دیگه‌ای که موقعِ تشخیص گفتار پیش بیاد.
    """

    def test_speech_to_text_error_is_a_value_error(self):
        # قراردادِ safe_error_text: فقط ValueError/LookupError با پیامِ کوتاهِ
        # *خودِ همین پروژه* عیناً نشون داده می‌شه؛ SpeechToTextError باید
        # دقیقاً همین دسته باشه، نه یه Exception خام.
        self.assertTrue(issubclass(stt.SpeechToTextError, ValueError))

    def test_recognize_failed_uses_safe_error_text_not_raw_str(self):
        bot = FakeBot()
        loud = pcm16([100] * 16000)
        with mock.patch.object(vs, "_collect", return_value=(loud, 16000, 1, "end_of_speech")):
            with mock.patch.object(stt, "create_engine") as create_engine:
                engine = mock.Mock()
                engine.transcribe.side_effect = stt.SpeechToTextError("network down")
                create_engine.return_value = engine
                with mock.patch.object(vs.logging_setup, "safe_error_text",
                                        wraps=vs.logging_setup.safe_error_text) as safe_text:
                    vs.start(bot, ctx(bot))
        safe_text.assert_called_once()
        from core import i18n
        self.assertEqual(bot.t.sent[-1], (1, i18n.t("vs_recognize_failed", error="network down")))

    def test_unexpected_engine_exception_never_leaks_raw_text(self):
        bot = FakeBot()
        loud = pcm16([100] * 16000)
        raw_message = "TracebackObject at 0x7f, secret_key=ABCDEF, path=C:\\Users\\x\\file"
        with mock.patch.object(vs, "_collect", return_value=(loud, 16000, 1, "end_of_speech")):
            with mock.patch.object(stt, "create_engine") as create_engine:
                engine = mock.Mock()
                engine.transcribe.side_effect = RuntimeError(raw_message)
                create_engine.return_value = engine
                vs.start(bot, ctx(bot))
        sent_text = bot.t.sent[-1][1]
        self.assertNotIn(raw_message, sent_text)
        self.assertNotIn("secret_key", sent_text)


class SttHelpersTest(unittest.TestCase):

    def test_wav_bytes_header(self):
        data = pcm16([1, 2, 3, 4])
        wav = stt.wav_bytes(data, sample_rate=16000, channels=1)
        self.assertEqual(wav[:4], b"RIFF")
        self.assertEqual(wav[8:12], b"WAVE")
        self.assertEqual(len(wav), 44 + len(data))

    def test_multipart_body_contains_fields_and_file(self):
        body, content_type = stt.multipart_body(
            [("model", "whisper-1")], [("file", "speech.wav", "audio/wav", b"RIFFDATA")])
        self.assertIn("multipart/form-data; boundary=", content_type)
        self.assertIn(b'name="model"', body)
        self.assertIn(b"whisper-1", body)
        self.assertIn(b'filename="speech.wav"', body)
        self.assertIn(b"RIFFDATA", body)

    def test_scrub_removes_known_secrets_and_key_params(self):
        text = stt.scrub("failed for key=ABCDEF123 with secret XYZSECRET", secrets=["XYZSECRET"])
        self.assertNotIn("XYZSECRET", text)
        self.assertNotIn("ABCDEF123", text)

    def test_is_local_url(self):
        self.assertTrue(stt.is_local_url("http://127.0.0.1:8000/v1"))
        self.assertTrue(stt.is_local_url("http://localhost:8000"))
        self.assertFalse(stt.is_local_url("https://api.openai.com/v1"))

    def test_create_engine_unknown_raises(self):
        with self.assertRaises(stt.SpeechToTextError):
            stt.create_engine("does-not-exist", {})

    def test_engine_names_include_google_and_openai(self):
        self.assertIn("google", stt.engine_names())
        self.assertIn("openai", stt.engine_names())


class GoogleEngineTest(unittest.TestCase):

    def test_build_request_uses_language_and_key(self):
        engine = stt.GoogleEngine({"google_key": "mykey"})
        request = engine.build_request(b"\x00\x00", "fa-IR")
        self.assertIn("lang=fa-IR", request.full_url)
        self.assertIn("key=mykey", request.full_url)
        self.assertEqual(request.get_header("Content-type"), f"audio/l16; rate={stt.SAMPLE_RATE}")

    def test_parse_response_picks_best_alternative(self):
        text = (
            '{"result":[]}\n'
            '{"result":[{"alternative":[{"transcript":"low","confidence":0.2},'
            '{"transcript":"high one","confidence":0.9}]}]}\n'
        )
        self.assertEqual(stt.GoogleEngine.parse_response(text), "high one")

    def test_parse_response_empty_result_means_nothing_heard(self):
        self.assertEqual(stt.GoogleEngine.parse_response('{"result":[]}\n'), "")

    def test_parse_response_non_json_is_an_error(self):
        with self.assertRaises(stt.SpeechToTextError):
            stt.GoogleEngine.parse_response("<html>blocked</html>")

    def test_transcribe_end_to_end_with_mocked_urlopen(self):
        engine = stt.GoogleEngine({})
        response_body = b'{"result":[{"alternative":[{"transcript":"hello world"}]}]}\n'
        fake_response = mock.MagicMock()
        fake_response.read.return_value = response_body
        fake_response.__enter__.return_value = fake_response
        with mock.patch("urllib.request.urlopen", return_value=fake_response):
            text = engine.transcribe(b"\x00\x00", "en-US", timeout=5)
        self.assertEqual(text, "hello world")


class OpenAIEngineTest(unittest.TestCase):

    def test_endpoint_appends_v1_when_missing(self):
        engine = stt.OpenAIEngine({"openai_base_url": "http://127.0.0.1:8000"})
        self.assertEqual(engine.endpoint(), "http://127.0.0.1:8000/v1/audio/transcriptions")

    def test_endpoint_left_alone_when_already_full(self):
        engine = stt.OpenAIEngine({"openai_base_url": "https://api.groq.com/openai/v1/audio/transcriptions"})
        self.assertEqual(engine.endpoint(), "https://api.groq.com/openai/v1/audio/transcriptions")

    def test_build_request_sends_language_and_auth_header(self):
        engine = stt.OpenAIEngine({"openai_api_key": "sk-test", "openai_model": "whisper-1"})
        request = engine.build_request(b"\x00\x00", "fa-IR")
        self.assertEqual(request.get_header("Authorization"), "Bearer sk-test")
        self.assertIn(b'name="language"', request.data)
        self.assertIn(b"fa", request.data)

    def test_build_request_omits_language_when_auto(self):
        engine = stt.OpenAIEngine({})
        request = engine.build_request(b"\x00\x00", "")
        self.assertNotIn(b'name="language"', request.data)

    def test_parse_response_requires_text_field(self):
        self.assertEqual(stt.OpenAIEngine.parse_response('{"text": "hi there"}'), "hi there")
        with self.assertRaises(stt.SpeechToTextError):
            stt.OpenAIEngine.parse_response('{"oops": true}')
        with self.assertRaises(stt.SpeechToTextError):
            stt.OpenAIEngine.parse_response("not json")

    def test_transcribe_wraps_http_error_without_leaking_the_key(self):
        engine = stt.OpenAIEngine({"openai_api_key": "sk-secretvalue"})

        def raise_http_error(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO(b"{}"))

        with mock.patch.object(stt, "open_url", side_effect=raise_http_error):
            with self.assertRaises(stt.SpeechToTextError) as caught:
                engine.transcribe(b"\x00\x00", "en", timeout=5)
        self.assertNotIn("sk-secretvalue", str(caught.exception))

    def test_transcribe_times_out_cleanly(self):
        import socket
        engine = stt.OpenAIEngine({})

        def raise_timeout(request, timeout):
            raise socket.timeout()

        with mock.patch.object(stt, "open_url", side_effect=raise_timeout):
            with self.assertRaises(stt.SpeechToTextError) as caught:
                engine.transcribe(b"\x00\x00", "en", timeout=5)
        self.assertIn("5", str(caught.exception))


# ------------------------------------------------------------- کاتالوگ/لایسنس

class CatalogRegistrationTest(unittest.TestCase):

    def test_voice_search_is_a_capability_service(self):
        self.assertIn("voice_search", catalog.CAPABILITY_SERVICES)

    def test_cap_voice_search_maps_to_the_voice_search_service(self):
        self.assertEqual(catalog.CAPABILITY_OF_FEATURE.get("cap_voice_search"), "voice_search")

    def test_cap_voice_search_feature_exists_with_its_commands(self):
        feature = catalog.features()["cap_voice_search"]
        self.assertIn("voice_search", feature["services"])
        self.assertIn("vs", feature["commands"])
        self.assertIn("vss", feature["commands"])

    def test_service_for_command_vs_and_vss(self):
        self.assertEqual(catalog.service_for_command("vs"), "voice_search")
        self.assertEqual(catalog.service_for_command("vss"), "voice_search")

    def test_licence_gate_blocks_voice_search_without_the_feature(self):
        from core import license_gate as gate
        s = gate.LicenseState(data={"key": "TT-TEST-0000-0000", "expires_at": 9999999999,
                                    "features": ["cap_proxy"]})
        self.assertFalse(s.allows_service("voice_search"))

    def test_licence_gate_allows_voice_search_with_the_feature(self):
        from core import license_gate as gate
        s = gate.LicenseState(data={"key": "TT-TEST-0000-0000", "expires_at": 9999999999,
                                    "features": ["cap_voice_search"]})
        self.assertTrue(s.allows_service("voice_search"))


class ConfigDefaultsTest(unittest.TestCase):

    def test_default_shared_config_has_voice_search_defaults(self):
        from core.config_defaults import default_shared_config
        cfg = default_shared_config("host", 1234)
        self.assertIn("voice_search", cfg)
        for key in vs.SETTINGS_ORDER:
            self.assertIn(key, cfg["voice_search"])


if __name__ == "__main__":
    unittest.main()

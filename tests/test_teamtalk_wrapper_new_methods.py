"""
Audit part 1 (docs/TEAMTALK_WRAPPER.md): تست‌های جدول‌محورِ ۲۳ متدِ تازه‌ای
که این audit به core/teamtalk/ttbot.py (کلاسِ TTBot) اضافه کرد. هر مورد چک
می‌کنه که متدِ wrapper دقیقاً همون تابعِ خامِ self.tt.<name> رو با آرگومان‌های
درست‌تبدیل‌شده (str->ttstr، ساختن structِ ctypes با فیلدهای درست، و ...)
صدا می‌زنه.

کاملاً آفلاین: هیچ اتصال/سروری در کار نیست، و مهم‌تر از اون هیچ TeamTalk()
واقعی هم ساخته نمی‌شه -- هرچی تلاش شد نمونه‌ی واقعی TeamTalk() (که DLL رو
مقداردهی اولیه می‌کنه) بسازیم، پروسه‌ی پایتون رو برای مدتِ طولانی/نامعلوم
هنگ کرد؛ دقیقاً همون خطری که دستورالعملِ «هیچ‌وقت اتصالِ واقعیِ تیم‌تاک
استارت نکن» ازش نگران بود. برای همین self.tt با یه FakeSDK ساده (بدونِ
هیچ import از teamtalk.TeamTalk5 حتی) جایگزین می‌شه؛ TTBot با
TTBot.__new__(TTBot) ساخته می‌شه تا __init__ (که TeamTalk() واقعی می‌سازه)
اصلاً اجرا نشه.

وارد کردنِ خودِ ماژولِ teamtalk.ttbot (بدونِ ساختنِ نمونه) بی‌خطره: فقط
DLL رو بارگذاری می‌کنه (ctypes.cdll.LoadLibrary) و امضای توابع رو می‌بنده،
هیچ instance/connection ای نمی‌سازه. این دقیقاً همون کاریه که
core/audio_lines.py هم موقعِ لیست‌کردنِ دستگاه‌های صوتی انجام می‌ده.
"""

import types
import unittest
from unittest import mock

from core.teamtalk import ttbot as ttbot_module
from core.teamtalk.ttbot import TTBot


class FakeSDK:
    """
    جایگزینِ self.tt: هر صدازدنِ متد رو با اسم/آرگومان‌ها ثبت می‌کنه و یه
    مقدارِ ازپیش‌تعیین‌شده (یا پیش‌فرضِ ۱ == truthy) برمی‌گردونه. متدهایی که
    باید یه struct واقعی برگردونن (مثلِ getUserStatistics) رو صریح تعریف
    می‌کنیم، بقیه از __getattr__ داینامیک ساخته می‌شن.
    """

    def __init__(self, returns=None):
        self.calls = []
        self._returns = returns or {}

    def __getattr__(self, name):
        def method(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name in self._returns:
                value = self._returns[name]
                return value(*args, **kwargs) if callable(value) else value
            return 1
        return method

    def last_call(self):
        return self.calls[-1] if self.calls else None


# --- برای media_file_info: TeamTalk5.getMediaFileInfo واقعاً پارامترِ self
# نداره (باگِ باندینگ، مستندشده در docs/TEAMTALK_WRAPPER.md)، پس ttbot.py
# اون رو با type(self.tt).getMediaFileInfo(path) صدا می‌زنه، نه
# self.tt.getMediaFileInfo(path). برای تستِ وفادار به همون رفتار،
# FakeSDK.getMediaFileInfo هم عمداً بدونِ self تعریف می‌شه؛ اگه wrapper
# روزی اشتباهاً از روی نمونه صداش بزنه (self.tt.getMediaFileInfo(path))،
# پایتون خودش self رو جای path پاس می‌ده و همین تست با TypeError شکست
# می‌خوره.
_MEDIA_CALLS = []


def _fake_get_media_file_info(path):
    _MEDIA_CALLS.append(path)
    info = types.SimpleNamespace(
        nStatus=6,
        szFileName="song.mp3",
        audioFmt=types.SimpleNamespace(nSampleRate=44100, nChannels=2),
        videoFmt=types.SimpleNamespace(nWidth=0, nHeight=0),
        uDurationMSec=12345,
        uElapsedMSec=0,
    )
    return info


FakeSDK.getMediaFileInfo = _fake_get_media_file_info


def make_bot(returns=None):
    """TTBot بدونِ اجرای __init__ (که TeamTalk() واقعی می‌سازه و هنگ می‌کنه)."""
    bot = TTBot.__new__(TTBot)
    bot.tt = FakeSDK(returns=returns)
    return bot


class NewWrapperMethodsTest(unittest.TestCase):
    """جدولِ (نامِ متد، نحوه‌ی صدازدن، چک‌کردنِ صدای خام) برای هر ۲۳ متدِ تازه."""

    def test_default_sound_devices(self):
        bot = make_bot(returns={"getDefaultSoundDevices": (5, 7)})
        self.assertEqual(bot.default_sound_devices(), (5, 7))
        self.assertEqual(bot.tt.last_call()[0], "getDefaultSoundDevices")

    def test_set_encryption_context(self):
        bot = make_bot(returns={"setEncryptionContext": True})
        ok = bot.set_encryption_context("cert.pem", "key.pem", ca_file="ca.pem",
                                         ca_dir="/ca", verify_peer=True,
                                         verify_client_once=True, verify_depth=2)
        self.assertTrue(ok)
        name, args, kwargs = bot.tt.last_call()
        self.assertEqual(name, "setEncryptionContext")
        ctx = args[0]
        self.assertEqual(ctx.szCertificateFile, "cert.pem")
        self.assertEqual(ctx.szPrivateKeyFile, "key.pem")
        self.assertEqual(ctx.szCAFile, "ca.pem")
        self.assertEqual(ctx.szCADir, "/ca")
        self.assertEqual(bool(ctx.bVerifyPeer), True)
        self.assertEqual(bool(ctx.bVerifyClientOnce), True)
        self.assertEqual(ctx.nVerifyDepth, 2)

    def test_ping(self):
        bot = make_bot(returns={"doPing": 555})
        self.assertEqual(bot.ping(), 555)
        self.assertEqual(bot.tt.last_call(), ("doPing", (), {}))

    def test_join_channel_struct(self):
        bot = make_bot(returns={"doJoinChannel": 42})
        sentinel = object()
        self.assertEqual(bot.join_channel_struct(sentinel), 42)
        self.assertEqual(bot.tt.last_call(), ("doJoinChannel", (sentinel,), {}))

    def test_ban_full(self):
        bot = make_bot(returns={"doBan": 1})
        ok = bot.ban_full(ip_address="1.2.3.4", channel_path="/Music",
                           nickname="nick", username="user", owner="admin")
        self.assertTrue(ok)
        name, args, kwargs = bot.tt.last_call()
        self.assertEqual(name, "doBan")
        bu = args[0]
        self.assertEqual(bu.szIPAddress, "1.2.3.4")
        self.assertEqual(bu.szChannelPath, "/Music")
        self.assertEqual(bu.szNickname, "nick")
        self.assertEqual(bu.szUsername, "user")
        self.assertEqual(bu.szOwner, "admin")

    def test_ban_full_raises_on_failure(self):
        bot = make_bot(returns={"doBan": 0})
        with self.assertRaises(Exception):
            bot.ban_full(ip_address="1.2.3.4")

    def test_unban_full(self):
        bot = make_bot(returns={"doUnbanUserEx": 1})
        ok = bot.unban_full(ip_address="1.2.3.4", username="user")
        self.assertTrue(ok)
        name, args, kwargs = bot.tt.last_call()
        self.assertEqual(name, "doUnbanUserEx")
        bu = args[0]
        self.assertEqual(bu.szIPAddress, "1.2.3.4")
        self.assertEqual(bu.szUsername, "user")

    def test_notify_quit(self):
        bot = make_bot(returns={"doQuit": 1})
        self.assertTrue(bot.notify_quit())
        self.assertEqual(bot.tt.last_call(), ("doQuit", (), {}))

    def test_my_user_data(self):
        bot = make_bot(returns={"getMyUserData": 42})
        self.assertEqual(bot.my_user_data(), 42)
        self.assertEqual(bot.tt.last_call(), ("getMyUserData", (), {}))

    def test_get_user_statistics(self):
        fake_stats = types.SimpleNamespace(
            nVoicePacketsRecv=1, nVoicePacketsLost=2,
            nVideoCapturePacketsRecv=3, nVideoCaptureFramesRecv=4,
            nVideoCaptureFramesLost=5, nVideoCaptureFramesDropped=6,
            nMediaFileAudioPacketsRecv=7, nMediaFileAudioPacketsLost=8,
            nMediaFileVideoPacketsRecv=9, nMediaFileVideoFramesRecv=10,
            nMediaFileVideoFramesLost=11, nMediaFileVideoFramesDropped=12,
        )
        bot = make_bot(returns={"getUserStatistics": fake_stats})
        result = bot.get_user_statistics(99)
        self.assertEqual(result["voice_packets_recv"], 1)
        self.assertEqual(result["media_file_video_frames_dropped"], 12)
        name, args, kwargs = bot.tt.last_call()
        self.assertEqual((name, args), ("getUserStatistics", (99,)))

    def test_error_message(self):
        bot = make_bot(returns={"getErrorMessage": "Invalid password"})
        self.assertEqual(bot.error_message(2001), "Invalid password")
        name, args, kwargs = bot.tt.last_call()
        self.assertEqual((name, args), ("getErrorMessage", (2001,)))

    def test_set_user_media_storage_dir(self):
        bot = make_bot(returns={"setUserMediaStorageDir": True})
        ok = bot.set_user_media_storage_dir(7, "/rec", "%username%")
        self.assertTrue(ok)
        name, args, kwargs = bot.tt.last_call()
        self.assertEqual(name, "setUserMediaStorageDir")
        self.assertEqual(args[0], 7)
        self.assertEqual(args[1], "/rec")
        self.assertEqual(args[2], "%username%")

    def test_set_user_stopped_playback_delay(self):
        bot = make_bot(returns={"setUserStoppedPlaybackDelay": True})
        ok = bot.set_user_stopped_playback_delay(7, 1, 500)
        self.assertTrue(ok)
        self.assertEqual(bot.tt.last_call(), ("setUserStoppedPlaybackDelay", (7, 1, 500), {}))

    def test_start_streaming_media_file_default_codec(self):
        bot = make_bot(returns={"startStreamingMediaFileToChannel": True})
        ok = bot.start_streaming_media_file("song.mp3")
        self.assertTrue(ok)
        name, args, kwargs = bot.tt.last_call()
        self.assertEqual(name, "startStreamingMediaFileToChannel")
        self.assertEqual(args[0], "song.mp3")
        self.assertEqual(args[1].nCodec, 0)  # Codec.NO_CODEC

    def test_stop_streaming_media_file(self):
        bot = make_bot(returns={"stopStreamingMediaFileToChannel": True})
        self.assertTrue(bot.stop_streaming_media_file())
        self.assertEqual(bot.tt.last_call(), ("stopStreamingMediaFileToChannel", (), {}))

    def test_init_local_playback(self):
        bot = make_bot(returns={"initLocalPlayback": 99})
        session_id = bot.init_local_playback("song.mp3", offset_msec=1000, paused=True)
        self.assertEqual(session_id, 99)
        name, args, kwargs = bot.tt.last_call()
        self.assertEqual(name, "initLocalPlayback")
        self.assertEqual(args[0], "song.mp3")
        self.assertEqual(args[1].uOffsetMSec, 1000)
        self.assertEqual(bool(args[1].bPaused), True)

    def test_init_local_playback_raises_on_failure(self):
        bot = make_bot(returns={"initLocalPlayback": 0})
        with self.assertRaises(Exception):
            bot.init_local_playback("song.mp3")

    def test_update_local_playback(self):
        bot = make_bot(returns={"updateLocalPlayback": True})
        ok = bot.update_local_playback(99, offset_msec=2000, paused=False)
        self.assertTrue(ok)
        name, args, kwargs = bot.tt.last_call()
        self.assertEqual(name, "updateLocalPlayback")
        self.assertEqual(args[0], 99)
        self.assertEqual(args[1].uOffsetMSec, 2000)

    def test_stop_local_playback(self):
        bot = make_bot(returns={"stopLocalPlayback": True})
        self.assertTrue(bot.stop_local_playback(99))
        self.assertEqual(bot.tt.last_call(), ("stopLocalPlayback", (99,), {}))

    def test_enable_audio_block_event_ex(self):
        bot = make_bot(returns={"enableAudioBlockEventEx": True})
        ok = bot.enable_audio_block_event_ex(7, 16000, 1)
        self.assertTrue(ok)
        name, args, kwargs = bot.tt.last_call()
        self.assertEqual(name, "enableAudioBlockEventEx")
        self.assertEqual(args[0], 7)
        fmt = args[2]
        self.assertEqual(fmt.nSampleRate, 16000)
        self.assertEqual(fmt.nChannels, 1)

    def test_insert_audio_block(self):
        bot = make_bot(returns={"insertAudioBlock": True})
        pcm = (b"\x00\x01" * 4) * 2  # 2 channels * 8 bytes samples-worth
        ok = bot.insert_audio_block(3, 16000, 2, pcm)
        self.assertTrue(ok)
        name, args, kwargs = bot.tt.last_call()
        self.assertEqual(name, "insertAudioBlock")
        block = args[0]
        self.assertEqual(block.nStreamID, 3)
        self.assertEqual(block.nSampleRate, 16000)
        self.assertEqual(block.nChannels, 2)
        self.assertEqual(block.nSamples, len(pcm) // (2 * 2))
        self.assertTrue(block.lpRawAudio)

    def test_media_file_info(self):
        _MEDIA_CALLS.clear()
        bot = make_bot()
        result = bot.media_file_info("song.mp3")
        self.assertEqual(_MEDIA_CALLS, ["song.mp3"])
        self.assertEqual(result["status"], 6)
        self.assertEqual(result["filename"], "song.mp3")
        self.assertEqual(result["audio_sample_rate"], 44100)
        self.assertEqual(result["audio_channels"], 2)
        self.assertEqual(result["duration_msec"], 12345)
        # هیچ صدازدنی روی self.tt (نمونه) نباید ثبت شده باشه -- یعنی از
        # مسیرِ باگ‌دارِ self.tt.getMediaFileInfo(...) استفاده نشده.
        self.assertEqual(bot.tt.calls, [])

    def test_sdk_version(self):
        with mock.patch.object(ttbot_module, "getVersion", return_value="5.22.0.5198"):
            bot = make_bot()
            self.assertEqual(bot.sdk_version(), "5.22.0.5198")

    def test_set_license(self):
        with mock.patch.object(ttbot_module, "setLicense", return_value=True) as fake_set:
            bot = make_bot()
            self.assertTrue(bot.set_license("Acme Corp", "SOME-KEY"))
            fake_set.assert_called_once_with("Acme Corp", "SOME-KEY")

    def test_rebuild_message(self):
        # buildTextMessage/rebuildTextMessage واقعی (خالص پایتون/ctypes، بدونِ
        # هیچ صدازدنِ DLL) -- رفت‌وبرگشتِ کامل رو چک می‌کنیم.
        long_text = "x" * 1500
        msgs = ttbot_module.buildTextMessage(long_text, ttbot_module.TextMsgType.MSGTYPE_USER)
        self.assertGreater(len(msgs), 1)  # واقعاً چندتکه شده
        bot = make_bot()
        self.assertEqual(bot.rebuild_message(msgs), long_text)


if __name__ == "__main__":
    unittest.main()

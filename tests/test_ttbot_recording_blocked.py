"""
TTBot.recording_blocked: کانالِ «No recording» (CHANNEL_NO_RECORDING) و ربات نه
ادمینِ سرور نیست => True (اپراتور بودن کافی نیست). آفلاین با یه SDKِ جعلی (مثلِ
tests/test_teamtalk_wrapper_new_methods.py)؛ هیچ TeamTalk() واقعی ساخته نمی‌شه.
"""

import threading
import types
import unittest

from core.teamtalk.ttbot import TTBot, ChannelType, UserRight, UserType


class FakeSDK:
    def __init__(self, channel_type, user_type=0, is_operator=False, channel_id=5, rights=0):
        self._rights = rights
        self._channel_type = channel_type
        self._user_type = user_type
        self._is_operator = is_operator
        self._channel_id = channel_id

    def getMyChannelID(self):
        return self._channel_id

    def getChannel(self, channel_id):
        return types.SimpleNamespace(uChannelType=self._channel_type)

    def getMyUserType(self):
        return self._user_type

    def getMyUserAccount(self):
        return types.SimpleNamespace(uUserRights=self._rights)

    def getMyUserID(self):
        return 7

    def isChannelOperator(self, user_id, channel_id):
        return self._is_operator


def _bot(sdk):
    bot = TTBot.__new__(TTBot)
    bot.tt = sdk
    bot._tt_lock = threading.RLock()
    return bot


class RecordingBlockedTest(unittest.TestCase):
    def test_normal_channel_is_not_blocked(self):
        self.assertFalse(_bot(FakeSDK(ChannelType.CHANNEL_DEFAULT)).recording_blocked())

    def test_no_recording_channel_blocks_a_plain_user(self):
        self.assertTrue(_bot(FakeSDK(ChannelType.CHANNEL_NO_RECORDING)).recording_blocked())

    def test_server_admin_is_exempt(self):
        sdk = FakeSDK(ChannelType.CHANNEL_NO_RECORDING, user_type=UserType.USERTYPE_ADMIN)
        self.assertFalse(_bot(sdk).recording_blocked())

    def test_channel_operator_is_not_enough(self):
        # روی سرورِ واقعی: اپراتور شد، ولی باز هم blocks=0.
        sdk = FakeSDK(ChannelType.CHANNEL_NO_RECORDING, is_operator=True)
        self.assertTrue(_bot(sdk).recording_blocked())

    def test_record_voice_right_is_enough(self):
        # مدیر فقط «Record voice» رو به حسابِ ربات می‌ده -- نه ادمین، نه اپراتور.
        sdk = FakeSDK(ChannelType.CHANNEL_NO_RECORDING, rights=UserRight.USERRIGHT_RECORD_VOICE)
        self.assertFalse(_bot(sdk).recording_blocked())

    def test_not_in_a_channel(self):
        sdk = FakeSDK(ChannelType.CHANNEL_NO_RECORDING, channel_id=0)
        self.assertFalse(_bot(sdk).recording_blocked())


if __name__ == "__main__":
    unittest.main()

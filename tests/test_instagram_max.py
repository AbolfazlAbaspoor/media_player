"""
اینستاگرام: نگاشتِ خطاها، لاگین با sessionid (ذخیره‌ی بدونِ رمز) و دستورهای
مرور/پخش. همه آفلاین: instagrapi با mock جایگزین می‌شه و هیچ درخواستی
به شبکه نمی‌ره.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import i18n, instagram_api, instagram_bot, instagram_user
from tests.helpers import load_command

i18n.load_languages()

SESSIONID = "1234567890%3AabcDEFghiJKLmnoPQRstu%3A28%3AAYdXyZ0123456789"


def _real(name):
    import instagrapi.exceptions as exceptions
    return getattr(exceptions, name)("secret raw text")


class FailureMappingTest(unittest.TestCase):

    def test_real_instagrapi_classes(self):
        cases = {
            "BadPassword": "wrong_password",
            "TwoFactorRequired": "two_factor_required",
            "ChallengeRequired": "challenge_required",
            "CaptchaChallengeRequired": "challenge_required",
            "PleaseWaitFewMinutes": "instagram_rate_limited",
            "ClientThrottledError": "instagram_rate_limited",
            "ReloginAttemptExceeded": "instagram_rate_limited",
            "ClientConnectionError": "network_error",
            "ClientRequestTimeout": "network_error",
            "ProxyAddressIsBlocked": "ip_blocked",
            "SentryBlock": "ip_blocked",
            "ClientForbiddenError": "ip_blocked",
            "ClientJSONDecodeError": "bad_response",
            "FeedbackRequired": "action_blocked",
            "LoginRequired": "session_rejected",
            "ClientLoginRequired": "session_rejected",
            "ClientUnauthorizedError": "session_rejected",
            "UnknownError": "login_failed",
            "ClientBadRequestError": "login_failed",
            "PrivateError": "login_failed",
        }
        for name, expected in cases.items():
            self.assertEqual(instagram_user.login_failure_status(_real(name)), expected, name)

    def test_every_status_has_a_message_key(self):
        statuses = set(instagram_user._FAILURE_BY_CLASS.values()) | {"login_failed"}
        statuses -= {"wrong_password"}  # پیامِ جدا دارد (ig_wrong_password)
        self.assertEqual(sorted(statuses - set(instagram_bot.FAILURE_KEYS)), [])

    def test_unknown_failure_shows_class_name_never_the_message(self):
        text = instagram_bot.exception_text(_real("UnknownError"), "bob")
        self.assertIn("UnknownError", text)
        self.assertNotIn("secret raw text", text)

    def test_class_name_is_sanitised(self):
        weird = type("Bad Name\n<x>", (Exception,), {})("m")
        self.assertEqual(instagram_user.safe_class_name(weird), "BadNamex")


class SessionStorageTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # PBKDF2 کم‌تکرار: تست‌ها مسیرِ کد رو می‌سنجن نه سختیِ کلید.
        patch_iter = mock.patch.object(instagram_user, "_PBKDF2_ITERATIONS", 1000)
        patch_iter.start()
        self.addCleanup(patch_iter.stop)
        instagram_user.set_bot_dir(self.tmp.name)

    def _fake_client(self, username="seab.79"):
        client = mock.Mock()
        client.username = username
        client.get_settings.return_value = {"cookies": {"sessionid": SESSIONID}}
        return client

    def test_sessionid_login_roundtrip_without_password(self):
        client = self._fake_client()
        with mock.patch.object(instagram_api, "new_client", return_value=client):
            result = instagram_user.login_with_sessionid(SESSIONID, who="alice")
        self.assertEqual((result["status"], result["username"]), ("created", "seab.79"))
        client.login_by_sessionid.assert_called_once_with(SESSIONID)
        path = os.path.join(self.tmp.name, "instagram_sessions", "seab.79.json")
        raw = open(path, encoding="utf-8").read()
        self.assertNotIn(SESSIONID, raw)
        self.assertNotIn("password_hash", raw)
        data, cookie_str = instagram_user.load_saved_session("seab.79")
        self.assertEqual(json.loads(cookie_str)["cookies"]["sessionid"], SESSIONID)
        self.assertEqual(data["auth"], "sessionid")

    def test_session_file_alone_cannot_be_decrypted(self):
        with mock.patch.object(instagram_api, "new_client", return_value=self._fake_client()):
            instagram_user.login_with_sessionid(SESSIONID)
        os.remove(os.path.join(self.tmp.name, "instagram_sessions", ".key"))
        self.assertEqual(instagram_user.load_saved_session("seab.79"), (None, None))

    def test_password_login_also_stores_a_usable_session(self):
        client = self._fake_client("pw_user")
        with mock.patch.object(instagram_api, "new_client", return_value=client):
            result = instagram_user.login_or_create("pw_user", "hunter2")
        self.assertEqual(result["status"], "created")
        data, cookie_str = instagram_user.load_saved_session("pw_user")
        self.assertIsNotNone(cookie_str)
        # ورودِ دوباره با همون رمز: سشنِ موجود، بدونِ لاگینِ تازه.
        client.login.reset_mock()
        again = instagram_user.login_or_create("pw_user", "hunter2")
        self.assertEqual(again["status"], "logged_in")
        client.login.assert_not_called()

    def test_password_login_over_a_sessionid_session_does_a_fresh_login(self):
        with mock.patch.object(instagram_api, "new_client", return_value=self._fake_client()):
            instagram_user.login_with_sessionid(SESSIONID)
            result = instagram_user.login_or_create("seab.79", "pw")
        self.assertEqual(result["status"], "created")

    def test_bad_sessionid_is_rejected_before_any_network(self):
        with mock.patch.object(instagram_api, "new_client") as new_client:
            for bad in ("", "short", "abc%3Adef" * 10, "12345 67890"):
                self.assertEqual(instagram_user.login_with_sessionid(bad)["status"], "bad_sessionid", bad)
        new_client.assert_not_called()

    def test_colon_form_from_devtools_is_accepted(self):
        client = self._fake_client()
        with mock.patch.object(instagram_api, "new_client", return_value=client):
            instagram_user.login_with_sessionid(f'"{SESSIONID.replace("%3A", ":")}"')
        client.login_by_sessionid.assert_called_once_with(SESSIONID)

    def test_instagram_failure_is_translated_with_class_name(self):
        client = self._fake_client()
        client.login_by_sessionid.side_effect = _real("LoginRequired")
        with mock.patch.object(instagram_api, "new_client", return_value=client):
            result = instagram_user.login_with_sessionid(SESSIONID)
        self.assertEqual(result, {"status": "session_rejected", "error_class": "LoginRequired"})

    def test_missing_library_is_reported(self):
        with mock.patch.object(instagram_api, "new_client", return_value=None):
            self.assertEqual(instagram_user.login_with_sessionid(SESSIONID)["status"],
                             "instagrapi_unavailable")

    def test_sessionid_attempts_are_rate_limited_per_user(self):
        instagram_user._login_attempts.clear()
        client = self._fake_client()
        client.login_by_sessionid.side_effect = _real("LoginRequired")
        with mock.patch.object(instagram_api, "new_client", return_value=client):
            for _ in range(3):
                instagram_user.login_with_sessionid(SESSIONID, who="carol")
            self.assertEqual(instagram_user.login_with_sessionid(SESSIONID, who="carol")["status"], "rate_limited")
            self.assertEqual(instagram_user.login_with_sessionid(SESSIONID, who="dave")["status"], "session_rejected")
        instagram_user._login_attempts.clear()

    def test_username_cannot_escape_the_sessions_dir(self):
        for bad in ("../x", "a/b", "", "a" * 40, "x y"):
            self.assertFalse(instagram_user.valid_username(bad), bad)
            self.assertEqual(instagram_user.load_saved_session(bad), (None, None))
        self.assertTrue(instagram_user.valid_username("seab.79"))


def _media(pk=1, code="AbC", video="https://cdn/x.mp4", product="clips", user="u1", caption="hello  world",
           media_type=2):
    return SimpleNamespace(pk=pk, code=code, video_url=video, product_type=product, media_type=media_type,
                           user=SimpleNamespace(username=user, pk=99), caption_text=caption,
                           like_count=0, has_liked=False, resources=[])


class PlayItemsTest(unittest.TestCase):

    def test_photos_are_skipped_and_urls_are_public(self):
        photo = _media(code="PHO", video=None, media_type=1, product="feed")
        story = _media(pk=77, code="STO", product="story")
        post = _media(code="POS", product="feed")
        items = instagram_api.to_play_items([_media(), photo, story, post])
        self.assertEqual([i["public_url"] for i in items], [
            "https://www.instagram.com/reel/AbC/",
            "https://www.instagram.com/stories/u1/77/",
            "https://www.instagram.com/p/POS/"])
        self.assertEqual(items[0]["title"], "u1: hello world")
        self.assertTrue(all(i["verified_media"] and i["url"].endswith(".mp4") for i in items))

    def test_album_uses_first_video_resource(self):
        album = _media(video=None, media_type=8, product="feed")
        album.resources = [SimpleNamespace(video_url=None), SimpleNamespace(video_url="https://cdn/a.mp4")]
        self.assertEqual(instagram_api.to_play_items([album])[0]["url"], "https://cdn/a.mp4")


class FakeBot:
    def __init__(self):
        self.sent, self.channel, self.played = [], [], []
        self.t = mock.Mock()
        self.t.user_message.side_effect = lambda uid, text: self.sent.append(text)
        self.cfg = {}
        self.server_dir = None
        self.channel_messages_enabled = True
        self.save_config = mock.Mock()
        self.load_and_play = mock.Mock(side_effect=lambda items, **kw: len(items))
        self.channel_broadcast = self.channel.append
        self.queue = SimpleNamespace(current=lambda: None)


def _ctx(bot, args=()):
    return {"bot": bot, "uid": 1, "username": "alice", "nickname": "Alice", "args": list(args)}


class CommandsTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # PBKDF2 کم‌تکرار: تست‌ها مسیرِ کد رو می‌سنجن نه سختیِ کلید.
        patch_iter = mock.patch.object(instagram_user, "_PBKDF2_ITERATIONS", 1000)
        patch_iter.start()
        self.addCleanup(patch_iter.stop)
        self.bot = FakeBot()
        self.bot.server_dir = self.tmp.name
        self.client = mock.Mock()
        self.client.username = "seab.79"
        self.client.get_settings.return_value = {"a": 1}
        patcher = mock.patch.object(instagram_api, "new_client", return_value=self.client)
        patcher.start()
        self.addCleanup(patcher.stop)
        ig = load_command("ig")
        ig.run(_ctx(self.bot, ["session", SESSIONID]))

    def test_session_login_links_the_teamtalk_user(self):
        self.assertIn("seab.79", self.bot.sent[-1])
        self.assertEqual(instagram_bot.linked_username(self.bot, "alice"), "seab.79")

    def test_ig_session_without_value_shows_how_to_get_it(self):
        self.bot.sent.clear()
        load_command("ig").run(_ctx(self.bot, ["session"]))
        self.assertIn("sessionid", self.bot.sent[-1])
        self.assertIn("F12", self.bot.sent[-1])

    def test_ig_out_removes_session(self):
        load_command("ig").run(_ctx(self.bot, ["out"]))
        self.assertIsNone(instagram_bot.linked_username(self.bot, "alice"))
        self.assertEqual(instagram_user.load_saved_session("seab.79"), (None, None))

    def test_hashtag_reels_are_queued_and_played(self):
        self.client.hashtag_medias_reels_v1.return_value = [_media(), _media(video=None, code="P")]
        with mock.patch("core.command_helpers.broadcast_now_playing") as now_playing:
            load_command("iht").run(_ctx(self.bot, ["#Music"]))
        self.client.hashtag_medias_reels_v1.assert_called_once_with("Music", 10)
        items = self.bot.load_and_play.call_args[0][0]
        self.assertEqual(len(items), 1)
        self.assertEqual(self.bot.load_and_play.call_args[1]["service_name"], "instagram")
        now_playing.assert_called_once()

    def test_user_reels_posts_stories_highlights(self):
        self.client.user_id_from_username.return_value = "42"
        self.client.user_clips.return_value = [_media()]
        self.client.user_medias.return_value = [_media()]
        self.client.user_stories.return_value = [_media(product="story")]
        self.client.user_highlights.return_value = [SimpleNamespace(pk="h1")]
        self.client.highlight_info.return_value = SimpleNamespace(items=[_media(product="story")])
        with mock.patch("core.command_helpers.broadcast_now_playing"):
            load_command("iu").run(_ctx(self.bot, ["@someone"]))
            self.client.user_clips.assert_called_once_with("42", 10)
            load_command("iu").run(_ctx(self.bot, ["someone", "posts"]))
            self.client.user_medias.assert_called_once_with("42", 10)
            load_command("ist").run(_ctx(self.bot, ["someone"]))
            self.client.user_stories.assert_called_once_with("42")
            load_command("ihl").run(_ctx(self.bot, ["someone"]))
            self.client.highlight_info.assert_called_once_with("h1")
        self.assertEqual(self.bot.load_and_play.call_count, 4)

    def test_saved_liked_feed_explore(self):
        self.client.collection_medias.return_value = [_media()]
        self.client.liked_medias.return_value = [_media()]
        self.client.reels_timeline_media.return_value = [_media()]
        self.client.explore_reels.return_value = [_media()]
        with mock.patch("core.command_helpers.broadcast_now_playing"):
            load_command("isv").run(_ctx(self.bot))
            load_command("ilk").run(_ctx(self.bot))
            load_command("rl").run(_ctx(self.bot))
            load_command("rl").run(_ctx(self.bot, ["explore"]))
            load_command("rr").run(_ctx(self.bot))
        self.client.collection_medias.assert_called_once_with("ALL_MEDIA_AUTO_COLLECTION", 10)
        self.assertEqual(self.bot.load_and_play.call_count, 5)
        self.assertEqual(self.bot._ig_reels["alice"][0].code, "AbC")

    def test_instagram_errors_become_real_reasons_not_raw_text(self):
        self.client.hashtag_medias_reels_v1.side_effect = _real("ClientForbiddenError")
        self.bot.sent.clear()
        load_command("iht").run(_ctx(self.bot, ["music"]))
        self.assertEqual(self.bot.sent, [i18n.t("ig_ip_blocked", username="seab.79")])
        self.client.hashtag_medias_reels_v1.side_effect = _real("UnknownError")
        self.bot.sent.clear()
        load_command("iht").run(_ctx(self.bot, ["music"]))
        self.assertIn("UnknownError", self.bot.sent[-1])
        self.assertNotIn("secret raw text", self.bot.sent[-1])

    def test_nothing_playable(self):
        self.client.liked_medias.return_value = [_media(video=None, media_type=1)]
        load_command("ilk").run(_ctx(self.bot))
        self.assertIn("No playable", self.bot.sent[-1])
        self.bot.load_and_play.assert_not_called()

    def test_not_logged_in_and_usage(self):
        stranger = _ctx(self.bot)
        stranger["username"] = "bob"
        load_command("isv").run(stranger)
        self.assertEqual(self.bot.sent[-1], i18n.t("ig_not_logged_in"))
        load_command("iu").run(_ctx(self.bot, ["../etc"]))
        self.assertIn("Usage", self.bot.sent[-1])
        load_command("iht").run(_ctx(self.bot))
        self.assertIn("Usage", self.bot.sent[-1])

    def test_search_users(self):
        self.client.search_users.return_value = [
            SimpleNamespace(username="alpha", full_name="Al Pha", is_private=False),
            SimpleNamespace(username="beta", full_name="", is_private=True)]
        load_command("iss").run(_ctx(self.bot, ["al", "pha"]))
        self.client.search_users.assert_called_once_with("al pha")
        self.assertIn("@alpha (Al Pha) | @beta [private]", self.bot.sent[-1])
        self.client.search_users.return_value = []
        load_command("iss").run(_ctx(self.bot, ["zzz"]))
        self.assertIn("zzz", self.bot.sent[-1])

    def test_current_reel_follows_the_queue(self):
        reels = [_media(code="AAA"), _media(code="BBB")]
        self.bot.queue = SimpleNamespace(current=lambda: SimpleNamespace(
            public_url="https://www.instagram.com/reel/BBB/"))
        self.assertEqual(instagram_bot.current_reel_index(self.bot, "alice", reels), 1)

    def test_like_acts_on_the_reel_the_queue_is_playing(self):
        self.bot._ig_reels = {"alice": [_media(pk=11, code="AAA"), _media(pk=22, code="BBB")]}
        self.bot.queue = SimpleNamespace(current=lambda: SimpleNamespace(
            public_url="https://www.instagram.com/reel/BBB/"))
        load_command("lr").run(_ctx(self.bot))
        self.client.media_like.assert_called_once_with(22)


class ImportCostTest(unittest.TestCase):

    def test_instagrapi_not_imported_at_module_level(self):
        code = ("import sys\n"
                "from core import instagram_api, instagram_user, instagram_bot\n"
                "sys.exit(1 if 'instagrapi' in sys.modules else 0)")
        self.assertEqual(subprocess.run([sys.executable, "-c", code], cwd=ROOT).returncode, 0)


if __name__ == "__main__":
    unittest.main()

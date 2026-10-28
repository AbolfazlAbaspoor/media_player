"""
مدل متادیتای مشترک (core/track_meta.py)، دستورهای i/di روی اون، و ترتیب
نو-به-کهنه‌ی لیست‌ها -- با info‌های ساختگی از اکسترکتورهای مختلف.
"""

import os
import unittest
from unittest import mock

from core import i18n, track_meta, trackqueue
from core.services._ytdlp_service import YtdlpService
from core.services.youtube import Youtube
from tests.helpers import load_command

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


YOUTUBE_INFO = {
    "id": "abc123", "title": "Song", "uploader": "Artist", "channel": "Artist Official",
    "channel_url": "https://www.youtube.com/channel/UC1", "timestamp": 1758297601,
    "view_count": 1234567, "like_count": 4200, "comment_count": 77, "duration": 215.4,
    "description": "Line one\nLine two", "tags": ["a", "b"], "categories": ["Music"],
    "live_status": "not_live", "ext": "webm", "acodec": "opus", "vcodec": "none",
    "abr": 129.5, "asr": 48000, "filesize": 3_500_000, "age_limit": 0,
    "availability": "public", "extractor_key": "Youtube",
}
SOUNDCLOUD_INFO = {
    "id": "999", "title": "Track", "uploader": "Lofi", "upload_date": "20260914",
    "view_count": 1355, "like_count": 51, "repost_count": 4, "license": "all-rights-reserved",
    "ext": "m4a", "acodec": "mp4a.40.2", "vcodec": "none", "abr": 160,
    "duration": 1288, "extractor_key": "Soundcloud",
}


class BuilderTest(unittest.TestCase):

    def test_youtube_style_fields_are_mapped(self):
        meta = track_meta.from_info(YOUTUBE_INFO, "youtube")
        self.assertEqual(meta["uploader"], "Artist")
        self.assertEqual(meta["channel"], "Artist Official")
        self.assertEqual(meta["view_count"], 1234567)
        self.assertEqual(meta["duration"], 215)
        self.assertEqual(meta["categories"], ["Music"])
        self.assertEqual(meta["service"], "youtube")
        self.assertEqual(meta["filesize"], 3_500_000)
        self.assertNotIn("vcodec", meta)  # "none" یعنی فقط صدا
        self.assertNotIn("age_limit", meta)  # 0 یعنی بدون محدودیت

    def test_soundcloud_style_uses_upload_date_and_reposts(self):
        meta = track_meta.from_info(SOUNDCLOUD_INFO, "soundcloud")
        self.assertEqual(meta["timestamp"], track_meta.parse_timestamp("20260914"))
        self.assertEqual(meta["repost_count"], 4)
        self.assertEqual(meta["license"], "all-rights-reserved")

    def test_missing_fields_are_omitted_not_none(self):
        meta = track_meta.from_info({"title": "x", "view_count": None, "tags": []})
        self.assertEqual(meta, {})

    def test_non_dict_gives_empty(self):
        self.assertEqual(track_meta.from_info(None), {})

    def test_live_flag_and_resolution_fallbacks(self):
        meta = track_meta.from_info({"is_live": True, "width": 640, "height": 360})
        self.assertEqual(meta["live_status"], "is_live")
        self.assertEqual(meta["resolution"], "640x360")

    def test_merge_prefers_extra_and_ignores_empty(self):
        merged = track_meta.merge({"view_count": 1, "uploader": "a"},
                                  {"view_count": 5, "uploader": None})
        self.assertEqual(merged, {"view_count": 5, "uploader": "a"})


class TimeTest(unittest.TestCase):

    def test_parse_variants(self):
        base = track_meta.parse_timestamp("2026-09-19T16:00:01+00:00")
        self.assertEqual(track_meta.parse_timestamp("2026-09-19T16:00:01Z"), base)
        self.assertEqual(track_meta.parse_timestamp(base * 1000), base)
        self.assertEqual(track_meta.parse_timestamp("20260919"), base - 16 * 3600 - 1)
        # بدون منطقه‌ی زمانی + آفست تهران
        naive = track_meta.parse_timestamp("2026-09-19 19:30:01", 3.5 * 3600)
        self.assertEqual(naive, base)
        self.assertIsNone(track_meta.parse_timestamp("۱۴۰۵ مهر"))
        self.assertIsNone(track_meta.parse_timestamp(None))

    def test_format_date(self):
        self.assertEqual(track_meta.format_date(1758297601), "2025-09-19 16:00 UTC")
        self.assertIsNone(track_meta.format_date(None))

    def test_persian_digits_only_for_fa(self):
        self.assertEqual(track_meta.localize_digits("1,234", "fa"), "۱،۲۳۴")
        self.assertEqual(track_meta.localize_digits("1,234", "en"), "1,234")

    def test_format_helpers(self):
        self.assertEqual(track_meta.format_count(1234567), "1,234,567")
        self.assertEqual(track_meta.format_size(3_500_000), "3.3 MB")


class OrderingTest(unittest.TestCase):

    def item(self, name, ts=None):
        return {"id": name, "title": name, "timestamp": ts}

    def names(self, items):
        return [i["id"] for i in items]

    def test_mixed_dates_come_out_newest_first(self):
        items = [self.item("week", 700), self.item("day2", 900), self.item("month3", 100)]
        self.assertEqual(self.names(track_meta.sort_newest_first(items)),
                         ["day2", "week", "month3"])

    def test_no_dates_keeps_source_order(self):
        items = [self.item("a"), self.item("b"), self.item("c")]
        self.assertEqual(self.names(track_meta.sort_newest_first(items)), ["a", "b", "c"])

    def test_undated_items_keep_their_slot(self):
        items = [self.item("x", 100), self.item("y", 300), self.item("old1"), self.item("old2")]
        self.assertEqual(self.names(track_meta.sort_newest_first(items)),
                         ["y", "x", "old1", "old2"])

    def test_input_is_not_mutated(self):
        items = [self.item("a", 1), self.item("b", 2)]
        track_meta.sort_newest_first(items)
        self.assertEqual(self.names(items), ["a", "b"])

    def test_date_can_live_in_nested_info(self):
        items = [{"id": "a", "info": {"timestamp": 10}}, {"id": "b", "info": {"timestamp": 20}}]
        self.assertEqual(self.names(track_meta.sort_newest_first(items)), ["b", "a"])

    def test_merged_tabs_are_deduped_and_sorted(self):
        videos = [self.item("v1", 500), self.item("v2", 100)]
        shorts = [self.item("s1", 400), self.item("v1", 500)]
        streams = [self.item("l1", 900)]
        merged = track_meta.merge_newest_first(videos, shorts, streams)
        self.assertEqual(self.names(merged), ["l1", "v1", "s1", "v2"])


class FakeFeedService(YtdlpService):
    SERVICE_NAME = "fake"

    def __init__(self, feed=True):
        super().__init__()
        self.feed = feed

    def _is_feed(self, info):
        return self.feed


class ServiceOrderingTest(unittest.TestCase):

    entries = [{"id": "a", "timestamp": 100}, {"id": "b", "timestamp": 300},
               {"id": "c", "timestamp": 200}]

    def test_feed_is_sorted(self):
        out = FakeFeedService(True)._order_entries(list(self.entries), {})
        self.assertEqual([e["id"] for e in out], ["b", "c", "a"])

    def test_playlist_keeps_owner_order(self):
        out = FakeFeedService(False)._order_entries(list(self.entries), {})
        self.assertEqual([e["id"] for e in out], ["a", "b", "c"])

    def test_youtube_uses_rss_dates_and_keeps_older_undated_after(self):
        yt = Youtube()
        entries = [{"id": "v1"}, {"id": "v2"}, {"id": "v3"}, {"id": "v4"}]
        with mock.patch.object(yt, "_feed_dates", return_value={"v1": 100, "v2": 300}):
            out = yt._order_entries(entries, {"id": "UCxyz", "channel_id": "UCxyz"})
        self.assertEqual([e["id"] for e in out], ["v2", "v1", "v3", "v4"])

    def test_youtube_playlist_is_not_reordered(self):
        yt = Youtube()
        entries = [{"id": "v1", "timestamp": 1}, {"id": "v2", "timestamp": 2}]
        self.assertEqual(yt._order_entries(entries, {"id": "PLabc"}), entries)

    def test_youtube_grow_keeps_failed_entries_aligned(self):
        yt = Youtube()
        page = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        yt._playlist_stub_cache.set("k", page)

        def fake(entry, interactive=False):
            return None if entry["id"] == "b" else {"id": entry["id"], "url": "u"}

        with mock.patch.object(yt, "_resolve_entry", side_effect=fake):
            out = yt.grow_playlist("k", 0, 3)
        self.assertEqual(len(out), 3)
        self.assertEqual(out[1], {"id": "b"})


class TrackInfoPlumbingTest(unittest.TestCase):

    def test_info_survives_from_item_and_as_meta(self):
        track = trackqueue.Track.from_item({"url": "u", "info": {"view_count": 3}}, private=False)
        self.assertEqual(track.as_meta()["info"], {"view_count": 3})

    def test_stub_resolution_merges_info(self):
        resolved = {"url": "u2", "title": "T", "public_url": "p",
                    "info": {"like_count": 9}}
        queue = trackqueue.TrackQueue(play_fn=lambda url: None, resolve_fn=lambda stub: resolved)
        track = trackqueue.Track.from_item({"stub": {"id": 1}, "info": {"view_count": 3}},
                                           private=False)
        queue._resolve_track(track)
        self.assertEqual(track.info, {"view_count": 3, "like_count": 9})


class FakeBot:
    def __init__(self, meta, current="https://x/stream", live=None):
        self.sent = []
        self.track_meta = [meta] if meta is not None else []
        self.queue = mock.Mock(index=0 if meta is not None else None)
        self.player = mock.Mock(current_url=current, position_seconds=65,
                                duration_seconds=None)
        self.player.stream_info.return_value = live or {}
        self.t = mock.Mock()
        self.t.user_message.side_effect = lambda uid, text: self.sent.append(text)
        self.send_long_text = lambda fn, text: fn(text)

    def format_time(self, s):
        return f"{int(s) // 60}:{int(s) % 60:02d}"


def run_command(name, bot):
    load_command(name).run({"bot": bot, "uid": 1, "args": [], "nickname": "n", "username": "u"})
    return "\n".join(bot.sent)


class InfoCommandTest(unittest.TestCase):

    def setUp(self):
        i18n.load_languages()
        i18n.set_language("en")

    def meta(self, info, **extra):
        base = {"title": "Song", "public_url": "https://youtu.be/abc", "private": False,
                "fallback_label": None, "service": "youtube", "info": info}
        base.update(extra)
        return base

    def test_full_item_shows_everything_available(self):
        out = run_command("i", FakeBot(self.meta(track_meta.from_info(YOUTUBE_INFO, "youtube"))))
        for needle in ("Title: Song", "https://youtu.be/abc", "Artist (Artist Official)",
                       "2025-09-19 16:00 UTC", "Position: 1:05", "Duration: 3:35",
                       "Views: 1,234,567", "Likes: 4,200", "Comments: 77", "not live",
                       "Categories: Music", "Tags: a, b", "17 characters", "webm | opus",
                       "130 kbps", "Availability: public", "Source service: youtube"):
            self.assertIn(needle, out)
        self.assertNotIn("Dislikes", out)  # فیلدِ بدون مقدار نمایش داده نمی‌شه

    def test_sparse_item_only_shows_what_exists(self):
        out = run_command("i", FakeBot(self.meta({}, public_url=None, service=None)))
        self.assertIn("Title: Song", out)
        for absent in ("Views", "Likes", "Tags", "Uploader", "Format", "Description"):
            self.assertNotIn(absent, out)

    def test_direct_link_takes_format_from_the_player(self):
        bot = FakeBot(self.meta({}), live={"acodec": "mp3", "abr": 128.0, "ext": "mp3"})
        out = run_command("i", bot)
        self.assertIn("mp3 | mp3 | 128 kbps", out)

    def test_pasted_item_never_prints_its_url(self):
        meta = self.meta(track_meta.from_info(SOUNDCLOUD_INFO, "soundcloud"),
                         public_url="https://example.com/secret.mp3", private=True,
                         fallback_label="https://example.com/secret.mp3", service=None)
        out = run_command("i", FakeBot(meta))
        self.assertNotIn("secret.mp3", out)
        self.assertNotIn("example.com", out)
        self.assertIn("Views: 1,355", out)

    def test_paid_item_never_prints_its_url(self):
        meta = self.meta({}, title="Doc 7", public_url="https://cfdl.ir/vmfiles/7.mkv",
                         private=True, service="documentary")
        self.assertNotIn("cfdl.ir", run_command("i", FakeBot(meta)))

    def test_persian_language_localises_labels_and_digits(self):
        i18n.set_language("fa")
        try:
            out = run_command("i", FakeBot(self.meta(track_meta.from_info(YOUTUBE_INFO, "youtube"))))
        finally:
            i18n.set_language("en")
        self.assertIn("بازدید: ۱،۲۳۴،۵۶۷", out)
        self.assertNotIn("Views", out)

    def test_nothing_playing(self):
        out = run_command("i", FakeBot(None, current=None))
        self.assertIn("No file is currently playing", out)


class DescriptionCommandTest(unittest.TestCase):

    def setUp(self):
        i18n.load_languages()
        i18n.set_language("en")

    def test_non_youtube_item_has_its_description(self):
        meta = {"title": "T", "private": False, "service": "soundcloud",
                "public_url": "https://soundcloud.com/a/b",
                "info": {"description": "Tracklist\n[00:00] intro"}}
        out = run_command("di", FakeBot(meta))
        self.assertIn("Description:", out)
        self.assertIn("[00:00] intro", out)

    def test_pasted_direct_link_with_description(self):
        meta = {"title": "T", "private": True, "service": None,
                "public_url": "https://example.com/a.mp3", "info": {"description": "hello"}}
        out = run_command("di", FakeBot(meta))
        self.assertIn("hello", out)
        self.assertNotIn("example.com", out)

    def test_no_description_says_so(self):
        out = run_command("di", FakeBot({"title": "T", "info": {}}))
        self.assertIn("no description", out)

    def test_long_description_goes_through_send_long_text(self):
        bot = FakeBot({"title": "T", "info": {"description": "x" * 2000}})
        bot.send_long_text = mock.Mock(side_effect=lambda fn, text: fn(text))
        run_command("di", bot)
        bot.send_long_text.assert_called_once()

    def test_nothing_playing(self):
        out = run_command("di", FakeBot(None, current=None))
        self.assertIn("No file is currently playing", out)


if __name__ == "__main__":
    unittest.main()

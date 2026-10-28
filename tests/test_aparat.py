"""
آپارات: پارس شمارشِ فارسی، شناسه‌ی پلی‌لیست از URL، و ساخت استاب از
آیتم‌های JSON:API. بدون شبکه: core.net.fetch_text mock می‌شه.
"""

import json
import unittest
from unittest import mock

from core.services.aparat import Aparat, _parse_persian_count, _exact_count


class ParsePersianCountTest(unittest.TestCase):

    def test_thousand_word(self):
        self.assertEqual(_parse_persian_count("۱۲ هزار"), 12000)

    def test_million_word(self):
        self.assertEqual(_parse_persian_count("۳ میلیون"), 3000000)

    def test_decimal_million(self):
        self.assertEqual(_parse_persian_count("96.2 میلیون"), 96200000)

    def test_plain_comma_number(self):
        self.assertEqual(_parse_persian_count("1,231,831"), 1231831)

    def test_int_passthrough(self):
        self.assertEqual(_parse_persian_count(141), 141)

    def test_none_and_garbage(self):
        self.assertIsNone(_parse_persian_count(None))
        self.assertIsNone(_parse_persian_count("چیز نامفهوم"))


class ExactCountTest(unittest.TestCase):

    def test_prefers_exact_field(self):
        attrs = {"visit_cnt": "۱۲ هزار", "visit_cnt_int": 12345}
        self.assertEqual(_exact_count(attrs, "visit_cnt", "visit_cnt_int"), 12345)

    def test_falls_back_to_text_when_exact_missing(self):
        attrs = {"visit_cnt": "۱۲ هزار", "visit_cnt_int": None}
        self.assertEqual(_exact_count(attrs, "visit_cnt", "visit_cnt_int"), 12000)


class PlaylistIdFromUrlTest(unittest.TestCase):

    def test_path_form(self):
        self.assertEqual(
            Aparat._playlist_id_from_url("https://www.aparat.com/playlist/19639302?tab=videos"),
            "19639302")

    def test_query_param_form(self):
        self.assertEqual(
            Aparat._playlist_id_from_url("https://www.aparat.com/v/xxx?playlist=19639302"),
            "19639302")

    def test_not_a_playlist_url(self):
        self.assertIsNone(Aparat._playlist_id_from_url("https://www.aparat.com/v/xxx"))


SEARCH_PAYLOAD = json.dumps({
    "data": [{"type": "Row"}],
    "included": [
        {"type": "Video", "attributes": {
            "uid": "abc123", "title": "Song", "duration": "120",
            "sender_name": "Someone", "username": "someone",
            "visit_cnt_int": 500, "like_cnt_non_formatted": 10,
        }},
        {"type": "Video", "attributes": {"title": "no uid, skipped"}},
    ],
})

PLAYLIST_PAYLOAD = json.dumps({
    "data": {
        "relationships": {"video": {"data": [{"type": "Video", "id": "2"}, {"type": "Video", "id": "1"}]}},
    },
    "included": [
        {"type": "Video", "id": "1", "attributes": {"uid": "u1", "title": "First"}},
        {"type": "Video", "id": "2", "attributes": {"uid": "u2", "title": "Second"}},
    ],
})


class SearchStubsTest(unittest.TestCase):

    def test_search_stubs_from_included(self):
        with mock.patch("core.services.aparat.net.fetch_text", return_value=("u", SEARCH_PAYLOAD)):
            stubs = Aparat()._search_stubs("song", count=10)
        self.assertEqual(len(stubs), 1)
        self.assertEqual(stubs[0]["id"], "abc123")
        self.assertEqual(stubs[0]["view_count"], 500)
        self.assertEqual(stubs[0]["like_count"], 10)


class PlaylistVideosTest(unittest.TestCase):

    def test_order_follows_relationships_not_included(self):
        with mock.patch("core.services.aparat.net.fetch_text", return_value=("u", PLAYLIST_PAYLOAD)):
            stubs = Aparat().get_playlist_videos("999")
        # relationships گفته 2 قبل از 1 -- خروجی باید همون ترتیب رو داشته باشه،
        # نه ترتیب included.
        self.assertEqual([s["id"] for s in stubs], ["u2", "u1"])


if __name__ == "__main__":
    unittest.main()

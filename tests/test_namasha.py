"""
نماشا: پارس صفحه‌ی جستجوی HTML و ساخت استاب. بدون شبکه: core.net.fetch_text
mock می‌شه.
"""

import unittest
from unittest import mock

from core.services.namasha import Namasha, _parse_duration, parse_search_html

CARD = '''
<div class="d-flex flex-column mb-4 col-6">
    <div class="thumbnail full-width   mx-n2" data-id="{n}" data-has-menu="true">
        <div class="thumbnail-image-wrapper">
            <img alt="x" />
            {time}
        </div>
        <div class="thumbnail-text">
            <a href="https://www.namasha.com/v/{uid}" class="thumbnail-title thumbnail-url" title="{title}">
                <h3>{title}</h3>
            </a>
            <a href="https://www.namasha.com/channel123" class="clamp-text" title="محمد">
                <span class="thumbnail-channel-title">محمد</span>
            </a>
        </div>
    </div>
</div>
'''
PAGE = (
    CARD.format(n=1, uid="Lrs9ENss", title="موسیقی &amp; ترانه",
                time='<span class="time-stamp font-size-xs">۰۱:۰۲:۰۰</span>')
    + CARD.format(n=2, uid="DVgE7374", title="دوم", time="")
    + CARD.format(n=3, uid="Lrs9ENss", title="تکراری", time="")
)


class ParseDurationTest(unittest.TestCase):

    def test_persian_minutes_seconds(self):
        self.assertEqual(_parse_duration("۰۱:۰۰"), 60)

    def test_hours(self):
        self.assertEqual(_parse_duration("۱:۰۲:۰۰"), 3720)

    def test_garbage(self):
        self.assertIsNone(_parse_duration("زنده"))
        self.assertIsNone(_parse_duration(None))


class ParseSearchHtmlTest(unittest.TestCase):

    def test_cards_become_stubs_without_duplicates(self):
        stubs = parse_search_html(PAGE)
        self.assertEqual([s["id"] for s in stubs], ["Lrs9ENss", "DVgE7374"])
        first = stubs[0]
        self.assertEqual(first["url"], "https://www.namasha.com/v/Lrs9ENss")
        self.assertEqual(first["title"], "موسیقی & ترانه")
        self.assertEqual(first["duration"], 3720)
        self.assertEqual(first["uploader"], "محمد")
        self.assertEqual(first["channel_url"], "https://www.namasha.com/channel123")
        self.assertIsNone(stubs[1]["duration"])

    def test_empty_page(self):
        self.assertEqual(parse_search_html(""), [])
        self.assertEqual(parse_search_html(None), [])


class SearchStubsTest(unittest.TestCase):

    def test_count_limit_and_url_encoding(self):
        with mock.patch("core.services.namasha.net.fetch_text",
                        return_value=("u", PAGE)) as fetch:
            stubs = Namasha()._search_stubs("موسیقی", count=1)
        self.assertEqual(len(stubs), 1)
        self.assertIn("search?q=%D9%85", fetch.call_args[0][0])

    def test_network_failure_returns_empty_without_raising(self):
        with mock.patch("core.services.namasha.net.fetch_text", side_effect=OSError("boom")):
            self.assertEqual(Namasha()._search_stubs("x", count=5), [])


class OwnsUrlTest(unittest.TestCase):

    def test_routes_namasha_links_only(self):
        svc = Namasha()
        self.assertTrue(svc.owns_url("https://www.namasha.com/v/Lrs9ENss"))
        self.assertFalse(svc.owns_url("https://www.aparat.com/v/abc"))


if __name__ == "__main__":
    unittest.main()

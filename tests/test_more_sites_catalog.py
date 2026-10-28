"""
سرویس‌های سایت‌های ایرانیِ جدید (رادیو جوان، آپ‌میوزیک، نکس‌وان، رزموزیک،
تماشا): توسط ServiceManager لود می‌شن، برای هرکدوم یه امکانِ فروشی هست، و
فایل‌های کمکیِ `_` به‌عنوان سرویس لود نمی‌شن.
"""

import unittest

from core.manager import ServiceManager
from licensing import catalog

NEW_SERVICES = ("radiojavan", "upmusics", "nex1music", "rozmusic", "tamasha")


class MoreSitesTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.services = ServiceManager().load_services()

    def test_loaded_as_services_with_their_own_markers(self):
        for name in NEW_SERVICES:
            service = self.services.get(name)
            self.assertIsNotNone(service, name)
            self.assertEqual(service.SERVICE_NAME, name)
            self.assertTrue(service.SUPPORTS_SEARCH, name)
            self.assertTrue(service.URL_MARKERS, name)

    def test_helper_modules_are_not_services(self):
        for helper in ("_wp_music", "_farakav", "_ytdlp_service"):
            self.assertNotIn(helper, self.services)
            self.assertNotIn(helper.lstrip("_"), self.services)

    def test_each_service_has_a_priced_feature(self):
        features = catalog.features()
        for name in NEW_SERVICES:
            owners = [code for code, feature in features.items() if name in (feature.get("services") or [])]
            self.assertEqual(owners, [f"svc_{name}"], name)
            entry = features[f"svc_{name}"]
            self.assertEqual(entry["price_usd"], 1.5)
            for key in ("title_fa", "title_en", "note_fa", "note_en"):
                self.assertTrue(entry[key], f"{name}.{key}")
            self.assertEqual(entry["commands"], [])

    def test_links_route_to_the_right_service(self):
        samples = {
            "https://play.radiojavan.com/song/a-b": "radiojavan",
            "https://upmusics.com/some-post/": "upmusics",
            "https://nex1music.com/some-post/": "nex1music",
            "https://rozmusic.com/some-post.html": "rozmusic",
            "https://tamasha.com/v/jN3Ox": "tamasha",
        }
        for url, expected in samples.items():
            owners = [n for n, s in self.services.items() if s.owns_url(url)]
            self.assertEqual(owners, [expected], url)


if __name__ == "__main__":
    unittest.main()

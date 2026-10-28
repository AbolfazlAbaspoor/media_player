"""
Guards around licences that already belong to a customer.

Run everything with:  python -m unittest discover -s tests -t .
"""

import unittest
from unittest import mock

import manage


class ProtectedLicenceTest(unittest.TestCase):

    def _with_protected(self, keys):
        return mock.patch("licensing.config.get",
                          side_effect=lambda k, d=None: keys if k == "protected_licences" else d)

    def test_listed_key_is_protected(self):
        with self._with_protected(["TT-EQ4F-2V6D-AWFF"]):
            self.assertTrue(manage.licence_is_protected("TT-EQ4F-2V6D-AWFF"))

    def test_match_ignores_case_and_whitespace(self):
        with self._with_protected(["TT-EQ4F-2V6D-AWFF"]):
            self.assertTrue(manage.licence_is_protected("  tt-eq4f-2v6d-awff "))

    def test_unlisted_key_is_not_protected(self):
        with self._with_protected(["TT-EQ4F-2V6D-AWFF"]):
            self.assertFalse(manage.licence_is_protected("TT-AAAA-BBBB-CCCC"))

    def test_missing_setting_protects_nothing(self):
        with self._with_protected(None):
            self.assertFalse(manage.licence_is_protected("TT-EQ4F-2V6D-AWFF"))

    def test_reset_refuses_protected_key_before_touching_cloudflare(self):
        with self._with_protected(["TT-EQ4F-2V6D-AWFF"]), \
             mock.patch("licensing.cloudflare.get") as kv_get, \
             mock.patch("licensing.cloudflare.write_licence") as kv_write:
            code = manage.cmd_rental_reset(["TT-EQ4F-2V6D-AWFF", "--force"])
        self.assertEqual(code, 1)
        kv_get.assert_not_called()
        kv_write.assert_not_called()

    def test_reset_refuses_bound_licence_without_force(self):
        record = {"fingerprint": "abc", "features": None, "max_bots": 1, "note": ""}
        with self._with_protected([]), \
             mock.patch("licensing.cloudflare.available", return_value=True), \
             mock.patch("licensing.cloudflare.get", return_value=record), \
             mock.patch("licensing.cloudflare.write_licence") as kv_write:
            code = manage.cmd_rental_reset(["TT-AAAA-BBBB-CCCC"])
        self.assertEqual(code, 1)
        kv_write.assert_not_called()


class RentalExtendTest(unittest.TestCase):
    """
    rental-extend: تمدید/جبران بدونِ دست‌زدن به fingerprint یا تاریخچه --
    برخلافِ rental-reset، حتی روی لایسنسِ فروخته‌شده هم باید کار کنه، چون
    چیزی رو باز/ریست نمی‌کنه.
    """

    def test_extends_a_protected_licence_without_touching_fingerprint(self):
        import time
        now = int(time.time())
        record = {"fingerprint": "customer-device", "expires_at": now + 5 * 86400,
                  "features": None, "max_bots": 1, "revoked": False, "note": "sold"}
        stored = {}

        def fake_put(key, value):
            stored["value"] = dict(value)

        with mock.patch("licensing.config.get",
                        side_effect=lambda k, d=None: ["TT-EQ4F-2V6D-AWFF"] if k == "protected_licences" else d), \
             mock.patch("licensing.cloudflare.available", return_value=True), \
             mock.patch("licensing.cloudflare.get", return_value=dict(record)), \
             mock.patch("licensing.cloudflare.put", side_effect=fake_put):
            code = manage.cmd_rental_extend(["TT-EQ4F-2V6D-AWFF", "2"])

        self.assertEqual(code, 0)
        self.assertEqual(stored["value"]["fingerprint"], "customer-device")
        self.assertEqual(stored["value"]["expires_at"], record["expires_at"] + 2 * 86400)

    def test_unrevoke_flag_clears_revoked(self):
        import time
        now = int(time.time())
        record = {"fingerprint": None, "expires_at": now - 3600,
                  "features": None, "max_bots": 1, "revoked": True, "note": ""}
        stored = {}

        def fake_put(key, value):
            stored["value"] = dict(value)

        with mock.patch("licensing.config.get", return_value=None), \
             mock.patch("licensing.cloudflare.available", return_value=True), \
             mock.patch("licensing.cloudflare.get", return_value=dict(record)), \
             mock.patch("licensing.cloudflare.put", side_effect=fake_put):
            code = manage.cmd_rental_extend(["TT-AAAA-BBBB-CCCC", "2", "--unrevoke"])

        self.assertEqual(code, 0)
        self.assertFalse(stored["value"]["revoked"])
        # منقضی/لغوشده بود؛ مبنا باید همین‌الان باشه، نه تاریخِ منقضیِ قدیم.
        self.assertGreaterEqual(stored["value"]["expires_at"], now + 2 * 86400 - 5)

    def test_missing_licence_on_kv_is_reported(self):
        with mock.patch("licensing.config.get", return_value=None), \
             mock.patch("licensing.cloudflare.available", return_value=True), \
             mock.patch("licensing.cloudflare.get", return_value=None), \
             mock.patch("licensing.cloudflare.put") as kv_put:
            code = manage.cmd_rental_extend(["TT-NOPE-NOPE-NOPE", "2"])
        self.assertEqual(code, 1)
        kv_put.assert_not_called()


if __name__ == "__main__":
    unittest.main()

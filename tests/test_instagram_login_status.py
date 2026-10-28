"""ig <user> <pass>: هر شکستِ لاگین قبلاً «کتابخونه نصب نیست» گزارش می‌شد."""

import unittest

from core import instagram_api, instagram_user


def _exc(name, base=Exception):
    return type(name, (base,), {})("x")


class LoginFailureStatusTest(unittest.TestCase):
    def test_each_failure_gets_its_real_reason(self):
        cases = {
            "BadPassword": "wrong_password",
            "TwoFactorRequired": "two_factor_required",
            "ChallengeRequired": "challenge_required",
            "PleaseWaitFewMinutes": "instagram_rate_limited",
            "ClientConnectionError": "network_error",
            "SomethingElse": "login_failed",
        }
        for name, expected in cases.items():
            self.assertEqual(instagram_user.login_failure_status(_exc(name)), expected, name)

    def test_os_level_network_error(self):
        self.assertEqual(instagram_user.login_failure_status(ConnectionResetError()), "network_error")


class ParseSettingsTest(unittest.TestCase):
    def test_json_and_legacy_repr_both_parse(self):
        self.assertEqual(instagram_api._parse_settings('{"a": 1}'), {"a": 1})
        self.assertEqual(instagram_api._parse_settings("{'a': 1, 'b': True}"), {"a": 1, "b": True})
        self.assertIsNone(instagram_api._parse_settings("garbage"))


if __name__ == "__main__":
    unittest.main()

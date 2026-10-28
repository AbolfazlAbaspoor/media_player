"""
The licence gates services only. Commands always exist; a command that needs a
service the customer did not buy answers with the reason.
"""

import time
import unittest

from core import license_gate as gate
from licensing import catalog

FUTURE = int(time.time()) + 30 * 86400
PAST = int(time.time()) - 86400


def state(**data):
    data.setdefault("key", "TT-TEST-0000-0000")
    data.setdefault("expires_at", FUTURE)
    return gate.LicenseState(data=data)


class CommandsAreNeverGatedTest(unittest.TestCase):

    def test_every_command_is_allowed(self):
        s = state(features=[], services=["youtube"], commands=["p"])
        for name in ("p", "md", "dl", "proxy", "sts", "anything"):
            self.assertTrue(s.allows_command(name), name)

    def test_nothing_is_removed_from_the_command_table(self):
        s = state(features=[])
        table = {"p": {}, "md": {}, "dl": {}}
        self.assertEqual(gate.filter_commands(s, table), table)
        self.assertEqual(gate.removed_commands(s, table), [])


class CapabilitiesAreServicesTest(unittest.TestCase):

    def test_capability_commands_map_to_services(self):
        self.assertEqual(catalog.service_for_command("md"), "documentary")
        self.assertEqual(catalog.service_for_command("dl"), "download")
        self.assertEqual(catalog.service_for_command("proxy"), "proxy")
        self.assertEqual(catalog.service_for_command("sc"), "soundcloud")

    def test_plain_commands_need_no_service(self):
        for name in ("p", "n", "sts", "help"):
            self.assertIsNone(catalog.service_for_command(name), name)

    def test_youtube_is_always_there(self):
        self.assertTrue(state(features=[]).allows_service("youtube"))

    def test_unbought_capability_is_refused(self):
        s = state(features=["cap_proxy"])
        self.assertFalse(s.allows_service("documentary"))
        self.assertFalse(s.allows_service("download"))


class SoldLicenceStillWorksTest(unittest.TestCase):
    """TT-EQ4F was sold with exactly these features."""

    def test_the_goldenfriends_licence(self):
        s = state(features=["cap_documentary", "cap_proxy"])
        for allowed in ("youtube", "documentary", "proxy"):
            self.assertTrue(s.allows_service(allowed), allowed)
        for refused in ("download", "soundcloud", "accounts"):
            self.assertFalse(s.allows_service(refused), refused)


class OldLicenceFilesTest(unittest.TestCase):

    def test_file_written_before_capability_services_existed(self):
        # The platform used to write services=["youtube"] and put md in commands.
        s = state(features=["cap_documentary"], services=["youtube"],
                  commands=catalog.BASE_COMMANDS + ["md", "mostanad"])
        self.assertTrue(s.allows_service("documentary"))

    def test_very_old_file_with_commands_but_no_features(self):
        s = gate.LicenseState(data={"key": "TT-OLD", "expires_at": FUTURE,
                                    "services": ["youtube"],
                                    "commands": ["p", "dl", "dlr", "dlt", "dltc", "dltl", "dlts"]})
        self.assertTrue(s.allows_service("download"))
        self.assertFalse(s.allows_service("documentary"))

    def test_partial_command_list_does_not_unlock_a_capability(self):
        s = gate.LicenseState(data={"key": "TT-OLD", "expires_at": FUTURE,
                                    "services": ["youtube"], "commands": ["dl"]})
        self.assertFalse(s.allows_service("download"))

    def test_unrestricted_licence_allows_everything(self):
        s = gate.LicenseState(data={"key": "TT-ALL", "expires_at": FUTURE})
        self.assertTrue(s.allows_service("documentary"))
        self.assertTrue(s.allows_service("soundcloud"))


class LifecycleTest(unittest.TestCase):

    def test_grace_keeps_only_base_services(self):
        s = state(features=["cap_documentary", "svc_soundcloud"], expires_at=PAST,
                  grace_until=FUTURE)
        self.assertTrue(s.in_grace())
        self.assertTrue(s.allows_service("youtube"))
        self.assertFalse(s.allows_service("soundcloud"))
        self.assertFalse(s.allows_service("documentary"))

    def test_expired_without_grace_allows_nothing(self):
        s = state(features=["cap_documentary"], expires_at=PAST)
        self.assertFalse(s.allows_service("youtube"))
        self.assertTrue(s.blocks_startup())

    def test_paused_suspended_and_revoked_allow_nothing(self):
        for status in ("paused", "suspended", "revoked"):
            s = state(features=["cap_documentary"], status=status)
            self.assertFalse(s.allows_service("youtube"), status)
            self.assertTrue(s.blocks_startup(), status)


if __name__ == "__main__":
    unittest.main()

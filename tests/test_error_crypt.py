"""Customer error logs are sealed with a public key only the owner can open."""

import unittest
from unittest import mock

from core import error_crypt


class ErrorCryptTest(unittest.TestCase):

    def setUp(self):
        self.private, self.public = error_crypt.generate_keypair()
        mock.patch.object(error_crypt, "PUBLIC_KEY_B64", self.public).start()
        mock.patch.object(error_crypt, "_box", None).start()
        mock.patch.object(error_crypt, "_checked", False).start()

    def tearDown(self):
        mock.patch.stopall()

    def _frozen(self, value):
        return mock.patch.object(error_crypt, "is_frozen", return_value=value)

    def test_customer_build_encrypts_and_owner_decrypts(self):
        with self._frozen(True):
            sealed = error_crypt.encrypt_line("crash in core/services/youtube.py\n")
        self.assertTrue(sealed.startswith(error_crypt.PREFIX))
        self.assertNotIn("youtube.py", sealed)
        self.assertEqual(error_crypt.decrypt_line(sealed, self.private),
                         "crash in core/services/youtube.py")

    def test_development_run_stays_readable(self):
        with self._frozen(False):
            self.assertEqual(error_crypt.encrypt_line("debug\n"), "debug\n")

    def test_one_record_per_line(self):
        with self._frozen(True):
            sealed = error_crypt.encrypt_line("a\nb\n")
        self.assertEqual(sealed.count("\n"), 1)

    def test_persian_text_round_trips(self):
        text = "پروکسی جواب نداد"
        with self._frozen(True):
            sealed = error_crypt.encrypt_line(text + "\n")
        self.assertEqual(error_crypt.decrypt_line(sealed, self.private), text)

    def test_wrong_key_is_rejected(self):
        other_private, _ = error_crypt.generate_keypair()
        with self._frozen(True):
            sealed = error_crypt.encrypt_line("secret\n")
        with self.assertRaises(Exception):
            error_crypt.decrypt_line(sealed, other_private)

    def test_plain_lines_pass_through_decrypt(self):
        self.assertEqual(error_crypt.decrypt_line("old raw line\n", self.private), "old raw line")


if __name__ == "__main__":
    unittest.main()

"""
core/license_gate.py -- وقتی license.json خرابه یا خونده نشه، LicenseState.problem
ساخته می‌شه. commands/lic.py این رو مستقیم به *هر* کاربری توی تیم‌تاک نشون
می‌ده (state.status_text()، که problem رو توش می‌ذاره) -- پس نباید متنِ
خامِ OSError باشه (می‌تونه مسیر فایل سیستم رو لو بده). این تست همون
مسیر واقعی رو (بدون mock کردن json/os) با یه فایل واقعاً خراب/غیرقابل‌خوندن
شبیه‌سازی می‌کنه و چک می‌کنه problem از تابعِ ایمن (core.logging_setup.
safe_error_text) رد شده باشه.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import license_gate


class MalformedLicenseFileTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="license_gate_test_")
        self.license_path = os.path.join(self.tmpdir, license_gate.LICENSE_FILE_NAME)

    def test_malformed_json_problem_is_routed_through_safe_error_text(self):
        with open(self.license_path, "w", encoding="utf-8") as f:
            f.write("{ this is not valid json")

        with mock.patch("core.logging_setup.safe_error_text",
                         return_value="SANITIZED") as safe_mock:
            state = license_gate.load(self.tmpdir)

        self.assertTrue(state.unlicensed)
        self.assertEqual(state.problem, "SANITIZED")
        safe_mock.assert_called_once()

    def test_os_error_reading_file_does_not_leak_filesystem_path(self):
        """
        شبیه‌سازیِ یه OSError واقعی (نه ValueError) موقع خوندن فایل --
        open() رو patch می‌کنیم تا PermissionError بده، دقیقاً چیزی که
        پیامش معمولاً مسیر کامل فایل رو توی خودش داره.
        """
        with open(self.license_path, "w", encoding="utf-8") as f:
            f.write("{}")

        real_open = open

        def fake_open(path, *args, **kwargs):
            if str(path) == self.license_path:
                raise PermissionError(13, "Permission denied", self.license_path)
            return real_open(path, *args, **kwargs)

        with mock.patch("builtins.open", side_effect=fake_open):
            state = license_gate.load(self.tmpdir)

        self.assertTrue(state.unlicensed)
        # OSError نیست از جنس ValueError/LookupError، پس safe_error_text
        # باید پیام عمومی برگردونه -- نه مسیرِ فایل رو.
        self.assertNotIn(self.tmpdir, state.problem or "")
        self.assertNotIn(".json", state.problem or "")

    def test_lic_command_surfaces_the_sanitized_problem_not_raw_text(self):
        """
        سناریوی واقعیِ کامل: چیزی که commands/lic.py به کاربر نشون می‌ده
        (status_text()) نباید متنِ خامِ استثنا رو داشته باشه.
        """
        with open(self.license_path, "w", encoding="utf-8") as f:
            f.write("not json at all {{{")

        state = license_gate.load(self.tmpdir)
        text = state.status_text()
        # نکته‌ی اصلی: هیچ traceback/نام فایل داخلی‌ای توی پیام نیست.
        self.assertNotIn(self.tmpdir, text)
        self.assertNotIn(self.license_path, text)


if __name__ == "__main__":
    unittest.main()

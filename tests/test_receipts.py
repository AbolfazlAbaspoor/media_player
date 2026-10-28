"""
licensing/receipts.py -- بررسی خودکار رسید با OCR محلی.

این تست‌ها بیشتر روی چیزی تمرکز دارن که بدون tesseract روی سیستم (که
CI/محیط توسعه معمولاً ندارتش) هم باید درست کار کنه:

  ۱. اگه خودِ کتابخانه‌ی pytesseract نصب نباشه (ImportError).
  ۲. اگه pytesseract نصب باشه ولی باینریِ tesseract روی سیستم نباشه
     (TesseractNotFoundError) -- دقیقاً حالتی که این پروژه توی محیط
     توسعه‌ی فعلی داره: pytesseract پایتونیه، خودِ موتور نه.

هیچ‌کدوم واقعاً tesseract صدا نمی‌زنن -- pytesseract.image_to_string و
get_tesseract_version همه‌جا mock می‌شن.
"""

import hashlib
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from licensing import receipts


def _make_tiny_image(path):
    from PIL import Image
    Image.new("RGB", (20, 20), color="white").save(path)


class TesseractEngineMissingTest(unittest.TestCase):
    """
    شبیه‌سازیِ TesseractNotFoundError -- یعنی pytesseract نصبه (Pillow هم
    همین‌طور) ولی خودِ باینریِ tesseract روی سیستم نیست. طبق مشخصات ماژول:
    این باید خطای روشن برگردونه، نه کرش کنه یا traceback خام نشون بده.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="receipt_test_")
        self.image_path = os.path.join(self.tmpdir, "receipt.png")
        _make_tiny_image(self.image_path)

    def test_ocr_available_is_false_when_engine_missing(self):
        import pytesseract
        with mock.patch.object(pytesseract, "get_tesseract_version",
                                side_effect=pytesseract.TesseractNotFoundError()):
            self.assertFalse(receipts.ocr_available())

    def test_extract_text_returns_clean_error_not_a_crash(self):
        import pytesseract
        with mock.patch.object(pytesseract, "get_tesseract_version",
                                side_effect=pytesseract.TesseractNotFoundError()):
            text, error = receipts.extract_text(self.image_path)
        self.assertEqual(text, "")
        self.assertIsNotNone(error)
        # نباید متنِ خامِ traceback/نوعِ پایتونیِ استثنا رو مستقیم به کاربر
        # بده -- باید از i18n با یه پیام روشن (کلید receipt_engine_missing) رد بشه.
        self.assertNotIn("Traceback", error)

    def test_extract_text_does_not_retry_ocr_twice_when_engine_missing(self):
        # قبل از این fix، وقتی موتور نبود، image_to_string دو بار صدا زده
        # می‌شد (یه بار با lang، یه بار بدون) چون except عمومی retry می‌کرد.
        # حالا باید با یه چکِ زودهنگام (get_tesseract_version) قبل از
        # OCR واقعی برگرده، بدون اینکه اصلاً image_to_string صدا زده بشه.
        import pytesseract
        with mock.patch.object(pytesseract, "get_tesseract_version",
                                side_effect=pytesseract.TesseractNotFoundError()), \
             mock.patch.object(pytesseract, "image_to_string") as image_to_string_mock:
            receipts.extract_text(self.image_path)
        image_to_string_mock.assert_not_called()

    def test_check_degrades_to_unreadable_without_crashing(self):
        """
        سناریوی کامل: check() روی یه سفارش واقعی، ولی بدون موتور OCR.
        نتیجه باید verdict=unreadable باشه و مستقیم برای بررسی دستی ادمین
        بره -- نه اینکه استثنا بالا بره یا فروش رو قفل کنه.
        """
        import pytesseract
        with mock.patch.object(pytesseract, "get_tesseract_version",
                                side_effect=pytesseract.TesseractNotFoundError()):
            result = receipts.check(self.image_path, expected_irr=150000, card_number="6037991234567890")
        self.assertEqual(result.verdict, "unreadable")
        self.assertEqual(result.score, 0.0)
        self.assertTrue(result.notes)

    def test_duplicate_image_still_detected_without_ocr(self):
        """
        نکته‌ی مستندشده‌ی خودِ ماژول: تشخیصِ «همون فایل، بار دوم» نباید به
        OCR وابسته باشه -- سرور بدون tesseract هم باید جلوی رسیدِ تکراری
        رو بگیره.
        """
        digest = hashlib.sha256()
        with open(self.image_path, "rb") as f:
            digest.update(f.read())
        known_hash = digest.hexdigest()

        import pytesseract
        with mock.patch.object(pytesseract, "get_tesseract_version",
                                side_effect=pytesseract.TesseractNotFoundError()):
            result = receipts.check(self.image_path, expected_irr=150000,
                                     known_hashes=(known_hash,))
        self.assertEqual(result.verdict, "mismatch")
        self.assertEqual(result.duplicate_of, "image")


class PytesseractLibraryMissingTest(unittest.TestCase):
    """اگه خودِ pytesseract هم پایتونی نصب نباشه (نه فقط باینریِ tesseract)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="receipt_test_")
        self.image_path = os.path.join(self.tmpdir, "receipt.png")
        _make_tiny_image(self.image_path)

    def test_extract_text_reports_missing_library(self):
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

        def fake_import(name, *args, **kwargs):
            if name == "pytesseract":
                raise ImportError("No module named 'pytesseract'", name="pytesseract")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=fake_import):
            text, error = receipts.extract_text(self.image_path)
        self.assertEqual(text, "")
        self.assertIsNotNone(error)


class ConfigureTesseractCmdTest(unittest.TestCase):
    """
    pytesseract.pytesseract.tesseract_cmd باید از core.platform_paths
    (رجیستریِ E16/install.py) خونده بشه، نه فقط فرض PATH -- وگرنه نصبِ
    سایلنتِ ویندوز که PATH رو ست نمی‌کنه هیچ‌وقت پیدا نمی‌شه.
    """

    def test_sets_tesseract_cmd_when_bundled_binary_found(self):
        import pytesseract
        original_cmd = pytesseract.pytesseract.tesseract_cmd
        try:
            with mock.patch("core.platform_paths.find_native_component",
                             return_value=r"C:\ttbot\tesseract\tesseract.exe"):
                receipts._configure_tesseract_cmd(pytesseract)
            self.assertEqual(pytesseract.pytesseract.tesseract_cmd, r"C:\ttbot\tesseract\tesseract.exe")
        finally:
            pytesseract.pytesseract.tesseract_cmd = original_cmd

    def test_leaves_default_when_nothing_bundled(self):
        import pytesseract
        original_cmd = pytesseract.pytesseract.tesseract_cmd
        try:
            pytesseract.pytesseract.tesseract_cmd = "tesseract"
            with mock.patch("core.platform_paths.find_native_component", return_value=None):
                receipts._configure_tesseract_cmd(pytesseract)
            self.assertEqual(pytesseract.pytesseract.tesseract_cmd, "tesseract")
        finally:
            pytesseract.pytesseract.tesseract_cmd = original_cmd


if __name__ == "__main__":
    unittest.main()

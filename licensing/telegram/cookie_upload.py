"""
دریافتِ فایلِ cookies.txt از تلگرام -- مشترک بینِ ربات فروش
(licensing/telegram/sales/cookies.py) و ربات شخصیِ مشتری
(licensing/telegram/customer_bot.py)، که قبلاً هرکدوم همین چند خط رو جدا
داشتن. حجم قبل از دانلود چک می‌شه تا فایلِ بزرگ اصلاً کشیده نشه؛ اعتبارسنجی
و نوشتن کارِ core/cookie_files.write است.
"""

from telegram.error import TelegramError

from core import cookie_files

TOO_LARGE = "too_large"
DOWNLOAD_FAILED = "download_failed"


async def fetch_cookie_document(document):
    """(bytes, None) در موفقیت، یا (None, TOO_LARGE | DOWNLOAD_FAILED)."""
    if (document.file_size or 0) > cookie_files.MAX_BYTES:
        return None, TOO_LARGE
    try:
        telegram_file = await document.get_file()
        return bytes(await telegram_file.download_as_bytearray()), None
    except TelegramError:
        return None, DOWNLOAD_FAILED

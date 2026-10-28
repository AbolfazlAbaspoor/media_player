"""
کدِ مشترک نماشا و تماشا.

هر دو سرویس ویدیو از یک شرکتِ سازنده‌ان (صفحه‌ی جستجوی HTML، resolve با
اکسترکتورِ عمومیِ yt-dlp)، و مدت‌زمانِ کارت‌هاشون یک قالب داره. این‌جا فقط
چیزیه که بین‌شون واقعاً مشترکه؛ فایلِ با `_` لود نمی‌شه و سرویس نیست.
"""

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def parse_duration(text):
    """"۰۱:۰۰" -> 60، "۱:۰۲:۰۰" -> 3720، "01:41" -> 101، یا None اگه قابل‌فهم نبود."""
    if not text:
        return None
    parts = text.strip().translate(_PERSIAN_DIGITS).split(":")
    if not 2 <= len(parts) <= 3 or not all(p.isdigit() for p in parts):
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds

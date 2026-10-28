"""
سیگنال‌های کوچیکِ «ربات به سرور لایسنس» از طریق یه فایل توی پوشه‌ی خودِ ربات.

ربات و license_server دو پروسه‌ی جدان (supervisor اجراش می‌کنه) ولی روی یه
دیسکن، پس ساده‌ترین و ارزون‌ترین راه برای خبردادن یه فایل JSON کوچیکه:

    <bot_dir>/alerts.json   {"youtube_cookie_needed": <timestamp>}

ربات فقط *می‌نویسه* (اینجا)؛ license_server هر چند دقیقه می‌خونه
(licensing/cookie_alerts.py) و «رسیدگی‌شده» بودنِ هشدار رو توی دیتابیسِ
خودش نگه می‌داره، نه توی این فایل -- تا هر پروسه فقط فایل/جدولِ خودش رو
بنویسه و دو نویسنده روی هم ننویسن.

## قول‌ها

  * هیچ‌وقت exception نمی‌ده: هشدار فرعیه و نباید جلوی یه سرچ یا پخش رو
    بگیره.
  * ارزون: قبل از هر کاری یه مقایسه‌ی زمانِ درون‌حافظه‌ای (debounce)، پس روی
    خطاهای پشت‌سرهم دیسک لمس نمی‌شه.
  * debounce: حداکثر هر ۶ ساعت یک‌بار می‌نویسه (حتی بعد از ری‌استارتِ ربات،
    چون زمانِ قبلی از خودِ فایل خونده می‌شه).

رباتی که روی سیستمِ خودِ مشتری (اجاره‌ای) اجرا می‌شه هم همین فایل رو
می‌نویسه، ولی سرور به دیسکش دسترسی نداره، پس هشداری بهش نمی‌رسه.
"""

import json
import os
import threading
import time

from core import bot_context
from core.paths import write_json_atomic

ALERTS_FILE = "alerts.json"

#: کلیدِ هشدارِ «یوتیوب ازمون کوکی می‌خواد» (err_bot_check).
YOUTUBE_COOKIE_KEY = "youtube_cookie_needed"

DEBOUNCE_SECONDS = 6 * 3600

_lock = threading.Lock()
_last_written = {}  # key -> timestamp آخرین نوشتنِ این پروسه (یا مقدار خوانده‌شده)


def alerts_path(bot_dir):
    return os.path.join(bot_dir, ALERTS_FILE)


def read(bot_dir):
    """محتوای alerts.json؛ خالی اگه نبود یا خراب بود. هیچ‌وقت exception نمی‌ده."""
    try:
        with open(alerts_path(bot_dir), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def note(key, bot_dir=None, now=None, debounce=DEBOUNCE_SECONDS):
    """
    ثبتِ هشدارِ key با زمانِ الان. True فقط وقتی واقعاً نوشته شد؛ False یعنی
    debounce، نبودنِ پوشه‌ی ربات، یا خطا.
    """
    try:
        now = time.time() if now is None else now
        with _lock:
            last = _last_written.get(key)
            if last is not None and now - last < debounce:
                return False
            bot_dir = bot_dir or getattr(bot_context.bot, "bot_dir", None)
            if not bot_dir or not os.path.isdir(bot_dir):
                return False
            data = read(bot_dir)
            try:
                stored = float(data.get(key) or 0)
            except (TypeError, ValueError):
                stored = 0
            if stored and now - stored < debounce:
                # ری‌استارتِ ربات بین دو هشدار: زمانِ قبلی توی فایل مونده.
                _last_written[key] = stored
                return False
            data[key] = int(now)
            write_json_atomic(alerts_path(bot_dir), data, per_process_tmp=True)
            _last_written[key] = now
            return True
    except Exception:
        return False


def note_youtube_cookie_needed(bot_dir=None, now=None):
    return note(YOUTUBE_COOKIE_KEY, bot_dir=bot_dir, now=now)

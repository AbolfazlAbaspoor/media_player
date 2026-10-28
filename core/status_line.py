"""
خطِ استاتوسِ ربات روی سرور تیم‌تاک.

## چرا یه ماژول جدا

قبلاً استاتوس مستقیم از وسط حلقه‌ی اصلی با `t.set_status(4096, text)` ست
می‌شد و آخرین متن توی یه متغیر سراسری نگه داشته می‌شد تا هر تیک دوباره
فرستاده نشه. چهار تا مشکل داشت:

  ۱. **بعد از reconnect استاتوس می‌پرید.** سرور بعد از لاگینِ دوباره هیچ
     استاتوسی از ربات نداره، ولی کشِ «آخرین متن» پاک نمی‌شد؛ پس تا وقتی
     آهنگ عوض نمی‌شد، ربات بدون استاتوس می‌موند -- ربات بیکار تا ابد.
  ۲. **خاموش‌کردنش با h استاتوسِ قبلی رو برنمی‌داشت.** «در حال پخش: ...»
     روی سرور می‌موند.
  ۳. **خطاش گرفته نمی‌شد.** اگه وسط قطع اتصال صدا زده می‌شد، استثنا وسط
     حلقه‌ی اصلی می‌افتاد.
  ۴. **نه سقف طول داشت، نه جنسیت/حالتش قابل تنظیم بود** (۴۰۹۶ ثابت).

## فلگ‌ها

StatusMode تیم‌تاک یه bitmask است: دو بیت پایین حالت (در دسترس/away/سؤال)
و بیت‌های بالا جنسیت. ۰x۱۰۰ زن، ۰x۱۰۰۰ خنثی، بدون هر دو مرد.
"""

import threading

from core import logging_setup

MODE_AVAILABLE = 0x0000
MODE_AWAY = 0x0001

GENDER_FLAGS = {
    "male": 0x0000,
    "female": 0x0100,
    "neutral": 0x1000,
}

#: سقف طول. خود SDK رشته‌ها رو ۵۱۲ کاراکتری نگه می‌داره (TT_STRLEN)؛ سرور
#: هم ممکنه کمتر بپذیره. یه عنوان خیلی بلند نباید بی‌صدا بریده بشه وسط کلمه.
MAX_LENGTH = 250

_lock = threading.Lock()
_last = {"text": None, "mode": None}


def mode_for(cfg, paused=False):
    status_cfg = (cfg or {}).get("status", {}) or {}
    gender = str(status_cfg.get("gender", "neutral")).lower()
    mode = GENDER_FLAGS.get(gender, GENDER_FLAGS["neutral"])
    if paused and status_cfg.get("away_when_paused", False):
        mode |= MODE_AWAY
    return mode


def fit(text):
    text = " ".join(str(text or "").split())
    if len(text) <= MAX_LENGTH:
        return text
    return text[:MAX_LENGTH - 1].rstrip() + "\u2026"


def invalidate():
    """
    دفعه‌ی بعد حتماً دوباره بفرست. بعد از هر لاگین صدا زده می‌شه، چون سرور
    استاتوسِ قبلی رو یادش نیست.
    """
    with _lock:
        _last["text"] = None
        _last["mode"] = None


def apply(t, cfg, text, paused=False, visible=True):
    """
    استاتوس رو ست می‌کنه، فقط اگه واقعاً عوض شده باشه.

    visible=False یعنی استاتوس خاموشه: یه بار متن خالی فرستاده می‌شه تا
    استاتوسِ قبلی از روی سرور برداشته بشه، بعد دیگه هیچی.

    خروجی: True اگه چیزی فرستاده شد.
    """
    text = fit(text) if visible else ""
    mode = mode_for(cfg, paused)
    with _lock:
        if _last["text"] == text and _last["mode"] == mode:
            return False
    try:
        t.set_status(mode, text)
    except Exception:
        # معمولاً یعنی همین الان اتصال قطع شده؛ reconnect دوباره invalidate
        # می‌کنه و تیک بعدی می‌فرستتش.
        logging_setup.log_debug("set_status failed (probably disconnected)")
        return False
    with _lock:
        _last["text"] = text
        _last["mode"] = mode
    return True

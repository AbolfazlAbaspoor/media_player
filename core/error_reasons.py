"""
دلیلِ واقعی و قابل‌نمایشِ یه شکست (بدونِ متنِ خامِ exception).

وقتی یه سرچ/پخش شکست می‌خورد، کاربر فقط «Nothing found.» یا «internal
error» می‌دید -- حتی وقتی دلیلِ واقعی مشخص بود (یوتیوب پرسیده «ربات
نیستی؟»، 403، 404، 429، ویدیوی خصوصی، قطعیِ پروکسی). این ماژول اون دلیل رو
از زنجیره‌ی exception (یا آخرین شکستِ ثبت‌شده‌ی yt-dlp) پیدا می‌کنه و فقط
یه کلیدِ i18n کوتاه برمی‌گردونه؛ متنِ خام هیچ‌وقت به کاربر نمی‌رسه (همچنان
کامل توی لاگ ذخیره می‌شه -- logging_setup.safe_error_text).

ثبتِ آخرین شکست لازمه چون خیلی از مسیرها خطا رو قورت می‌دن و بعداً یه
ValueError("Nothing found.") تازه می‌سازن (مثلاً resolveِ موازیِ آیتم‌ها توی
تردهای استخر). core/proxy_retry.py هر شکستِ استخراج رو اینجا ثبت می‌کنه.
"""

import re
import threading
import time

from core import bot_alerts

# (کلیدِ i18n، الگو) -- ترتیب مهمه: دلیلِ خاص‌تر اول.
_RULES = [
    ("err_bot_check", re.compile(r"sign in to confirm|not a bot")),
    ("err_age_restricted", re.compile(r"age.restricted|confirm your age|inappropriate for some users")),
    ("err_unavailable", re.compile(r"private video|video unavailable|members.only|removed by|"
                                   r"has been terminated|this video is not available|is no longer available")),
    ("err_geo_blocked", re.compile(r"not available in your country|geo.?restrict|not made this video available")),
    ("err_rate_limited", re.compile(r"\b429\b|too many requests|rate.?limit")),
    ("err_forbidden", re.compile(r"\b403\b|forbidden")),
    ("err_not_found", re.compile(r"\b404\b|http error 404|\bnot found\b")),
    ("err_timeout", re.compile(r"timed out|timeout")),
    ("err_network", re.compile(r"connection (refused|reset|aborted)|unable to connect|network is unreachable|"
                               r"name resolution|getaddrinfo|tunnel connection failed|proxy|ssl|"
                               r"remote end closed|winerror 100")),
    ("err_unsupported", re.compile(r"unsupported url")),
]

# «Nothing found.» خودِ پروژه نباید با قانونِ 404 («not found») اشتباه گرفته بشه.
_OWN_MESSAGES = {"nothing found.", "no playable link found."}

_WINDOW_SECONDS = 60
_lock = threading.Lock()
_last = None  # (time, exception)


def _signal_if_bot_check(key):
    """
    بات‌چکِ یوتیوب یعنی این ربات کوکی می‌خواد: یه سیگنالِ کوچیک توی پوشه‌ی
    خودش می‌ذاره تا سرور لایسنس به مالک و ادمین خبر بده (core/bot_alerts.py).
    ارزون و بدونِ exception است.
    """
    if key == "err_bot_check":
        bot_alerts.note_youtube_cookie_needed()


def remember(exc):
    """آخرین شکستِ استخراج رو نگه می‌داره (برای مسیرهایی که خطا رو قورت می‌دن)."""
    global _last
    with _lock:
        _last = (time.time(), exc)
    try:
        _signal_if_bot_check(classify(exc))
    except Exception:
        pass


def _chain(exc, limit=6):
    seen = []
    while exc is not None and len(seen) < limit and exc not in seen:
        seen.append(exc)
        exc = exc.__cause__ or exc.__context__
    return seen


def classify(exc):
    """کلیدِ i18nِ دلیل، یا None اگه دلیلِ شناخته‌شده‌ای پیدا نشد."""
    for item in _chain(exc):
        text = str(item).strip().lower()
        if not text or text in _OWN_MESSAGES:
            continue
        for key, pattern in _RULES:
            if pattern.search(text):
                return key
    return None


def reason_key(exc):
    """
    دلیل از خودِ exception (و زنجیره‌ش)؛ اگه نبود، از آخرین شکستِ ثبت‌شده‌ی
    چند ثانیه‌ی اخیر. بعد از استفاده پاک می‌شه تا دلیلِ یه شکستِ قدیمی به
    خطای بعدی نچسبه.
    """
    global _last
    key = classify(exc)
    with _lock:
        recent = _last if _last and time.time() - _last[0] < _WINDOW_SECONDS else None
        if key is None and recent is not None:
            key = classify(recent[1])
        if key is not None:
            _last = None
    _signal_if_bot_check(key)
    return key


def describe(exc):
    """متنِ ترجمه‌شده‌ی دلیل، یا None."""
    key = reason_key(exc)
    if key is None:
        return None
    from core import i18n
    return i18n.t(key)

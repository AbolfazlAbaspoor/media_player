"""
لاگ خطاهای ربات، در دو سطح و دو فایل جدا (نه کنسول، نه قاطی با data/):

  errors/errors.log  -- خطاهای «واقعی/مهم» (WARNING به بالا) و همه‌ی
                        exceptionها. این همون چیزیه که اول از همه باید
                        نگاهش کنی.
  errors/debug.log   -- «ریزترین» خطاها: هر جایی که کد قبلاً یه خطا رو
                        بی‌صدا می‌خورد (except: pass / return None) حالا
                        با log_debug اینجا ثبتش می‌کنه. برای وقتیه که یه
                        رفتار عجیب رو داری دیباگ می‌کنی و می‌خوای *هیچ*
                        خطایی، حتی بی‌اهمیت، از دستت در نره.

هر دو فایل rotation دارن (سقف اندازه)، پس هیچ‌وقت بی‌نهایت بزرگ نمی‌شن.
یه context ساده («الان داشتیم چیکار می‌کردیم») هم نگه داشته می‌شه تا کنار
هر خطا مشخص باشه دقیقاً حین چه عملیاتی رخ داده.
"""

import logging
import os
import threading
import traceback

from core.paths import get_base_dir

ERRORS_DIR = os.path.join(get_base_dir(), "errors")
ERRORS_FILE = os.path.join(ERRORS_DIR, "errors.log")
DEBUG_FILE = os.path.join(ERRORS_DIR, "debug.log")

_current_operation = "idle"
_op_lock = threading.Lock()

# سقف اندازه‌ی هر فایل لاگ. بدون این، errors.log روی رباتی که ماه‌ها بالاست
# بی‌نهایت بزرگ می‌شه (هم دیسک رو پر می‌کنه، هم باز کردنش برای دیباگ عملاً
# غیرممکن می‌شه). وقتی از سقف رد بشه، فایل فعلی به .1 منتقل می‌شه و از صفر
# شروع می‌کنیم؛ یعنی حداکثر ۲ برابر سقف روی دیسک می‌مونه.
MAX_LOG_BYTES = 1 * 1024 * 1024
_write_lock = threading.Lock()

_crypt_module = None


def _error_crypt():
    """
    import تنبل: error_crypt خودش هیچی از logging_setup نمی‌خواد، ولی
    import سطح-ماژول یه وابستگی حلقوی بالقوه می‌ساخت و logging_setup
    باید پایین‌ترین لایه بمونه.
    """
    global _crypt_module
    if _crypt_module is None:
        from core import error_crypt
        _crypt_module = error_crypt
    return _crypt_module


def _append_line(path, line):
    """
    یه خط به فایل لاگ اضافه می‌کنه و در صورت لزوم چرخش (rotation) انجام
    می‌ده. هیچ‌وقت exception نمی‌ده -- خطای نوشتن لاگ نباید خودش باعث
    خرابی ربات بشه.
    """
    try:
        with _write_lock:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            try:
                if os.path.getsize(path) >= MAX_LOG_BYTES:
                    try:
                        os.replace(path, path + ".1")
                    except OSError:
                        pass
            except OSError:
                pass
            # تنها نقطه‌ای که لاگ روی دیسک می‌ره، پس تنها جایی که
            # رمزنگاری لازمه. روی اجرای عادی (توسعه) دست‌نخورده رد می‌شه.
            with open(path, "a", encoding="utf-8") as f:
                f.write(_error_crypt().encrypt_line(line))
    except Exception:
        pass

def set_operation(description):
    """قبل از هر عملیات مهم (سرچ، اتصال، دانلود لینک و ...) صدا زده می‌شه."""
    global _current_operation
    with _op_lock:
        _current_operation = description

def get_operation():
    with _op_lock:
        return _current_operation

class _ErrorFileHandler(logging.Handler):
    """
    خطاها رو توی فایل ذخیره می‌کنه (نه کنسول)، در دو سطح:
      - WARNING به بالا  -> errors/errors.log  (خطاهای مهم)
      - زیر WARNING       -> errors/debug.log   (ریزترین خطاها/هشدارهای
                             داخلی mpv و yt-dlp، برای وقتی که می‌خوای هیچی
                             از دستت درنره)

    چون سطح لاگ mpv روی "warn" تنظیم شده، عملاً پیام info/debug ازش صادر
    نمی‌شه؛ پس این مسیرِ debug تقریباً فقط برای yt-dlp فعال می‌شه و هزینه‌ی
    CPU محسوسی نداره.
    """

    def emit(self, record):
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        target = ERRORS_FILE if record.levelno >= logging.WARNING else DEBUG_FILE
        _append_line(target, f"[{record.name}] (while: {get_operation()}) {msg}\n")

_MPV_LEVEL_MAP = {
    "fatal": logging.CRITICAL,
    "error": logging.ERROR,
    "warn": logging.WARNING,
    "info": logging.INFO,
    "v": logging.DEBUG,
    "debug": logging.DEBUG,
    "trace": logging.DEBUG,
}

def _make_logger(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    if not logger.handlers:
        handler = _ErrorFileHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(handler)
    return logger

def setup():
    """باید یک‌بار در ابتدای اسکریپت اصلی صدا زده بشه."""
    os.makedirs(ERRORS_DIR, exist_ok=True)
    _make_logger("mpv")
    _make_logger("ytdlp")

def mpv_log_handler(loglevel, component, message):
    """این تابع باید به‌عنوان log_handler به MPV(...) پاس داده بشه."""
    level = _MPV_LEVEL_MAP.get(loglevel, logging.INFO)
    logging.getLogger("mpv").log(level, f"[{component}] {message}")

def get_ytdlp_logger():
    """این logger باید توی ydl_opts سرویس‌ها به‌عنوان 'logger' پاس داده بشه."""
    return logging.getLogger("ytdlp")

_general_logger = None

CONNECTION_LOG_FILE = os.path.join(ERRORS_DIR, "connection.log")


def log_info(message, context=None):
    """
    برای پیام‌های عادی/وضعیتی (مثل وضعیت اتصال/reconnect) که نباید کنسول
    رو شلوغ کنن، ولی خطای واقعی هم نیستن (پس توی errors.log که فقط
    WARNING به بالا ذخیره می‌کنه، ثبت نمی‌شن) -- توی یه فایل جدا و ساده
    (errors/connection.log) ذخیره می‌شن.
    """
    import datetime
    _append_line(CONNECTION_LOG_FILE, f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")


def log_warning(message, context=None):
    """برای مشکلاتی که exception واقعی نیستن ولی باید توی errors/errors.log ثبت بشن."""
    global _general_logger
    if _general_logger is None:
        _general_logger = _make_logger("bot")
    if context:
        set_operation(context)
    _general_logger.warning(message)


def log_debug(message, exc=True):
    """
    برای «ریزترین» خطاها: هر جایی که قبلاً خطا بی‌صدا بلعیده می‌شد
    (except: pass یا return None) این رو صدا بزن تا هیچ خطایی از دست نره.

    توی errors/debug.log ذخیره می‌شه (نه errors.log)، تا لاگ اصلی فقط
    مخصوص خطاهای مهم بمونه و شلوغ نشه.

    exc=True (پیش‌فرض) یعنی اگه داخل یه بلاک except صدا زده شده، traceback
    کاملِ خطای فعلی هم ضمیمه می‌شه -- همون چیزی که برای رفع بعدیِ خطا لازمه.
    """
    import datetime
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} (while: {get_operation()}) {message}\n"
    if exc:
        tb = traceback.format_exc()
        if tb and "NoneType: None" not in tb:
            line += tb
            if not line.endswith("\n"):
                line += "\n"
    _append_line(DEBUG_FILE, line)

def log_exception(context=None, error=None):
    """
    به‌جای traceback.print_exc() (که فقط توی کنسول نشون می‌داد و ذخیره
    نمی‌شد)، این تابع رو صدا بزن؛ خطای فعلی (باید داخل except باشه) رو با
    traceback کامل توی errors/errors.log ذخیره می‌کنه، نه کنسول.

    `error` رو اون‌جایی بده که خطا «فعلیِ» ترد نیست و فقط آبجکتش رو داری --
    مثل error handler تلگرام که بیرون از except صدا زده می‌شه و خطا رو توی
    context.error می‌ذاره. بدون این، logger.exception هیچ traceback ای
    پیدا نمی‌کنه و لاگ می‌شه «NoneType: None»: یعنی دقیقاً همون‌جایی که
    باید بفهمیم چی خراب شده، هیچی نمی‌فهمیم.
    """
    global _general_logger
    if _general_logger is None:
        _general_logger = _make_logger("bot")
    if context:
        set_operation(context)
    if error is not None:
        _general_logger.error(
            "Unhandled exception",
            exc_info=(type(error), error, getattr(error, "__traceback__", None)))
        return
    _general_logger.exception("Unhandled exception")

def safe_error_text(e, context=None):
    """
    برای پیام‌هایی که مستقیم توی چت کاربر (یا لاگ‌های عمومی) نشون داده
    می‌شن: کل traceback و متن کامل exception همیشه با log_exception توی
    errors/errors.log ذخیره می‌شه (برای دیباگ)، ولی چیزی که برمی‌گردونیم
    فقط یه پیام کوتاه و امنه که هیچ‌وقت مسیر فایل، traceback، یا جزئیات
    داخلی کد رو لو نمی‌ده (مثلاً خطاهای خام Playwright/yt-dlp که می‌تونن
    خیلی طولانی و پر از مسیر سیستم باشن).

    استثنا: اگه خودِ کدِ همین پروژه یه ValueError با پیام تمیز و کوتاه
    throw کرده باشه (مثل "Nothing found." یا "No playable link found."،
    نه یه exception خام از یه کتابخونه)، همون پیام امنه و نشونش می‌دیم.
    """
    log_exception(context)
    # دلیلِ واقعی (ربات‌نیستی/403/404/429/خصوصی/پروکسی...) به‌جای «Nothing
    # found» یا «internal error» -- core/error_reasons.py. فقط کلیدِ i18n،
    # نه متنِ خام.
    try:
        from core import error_reasons
        reason = error_reasons.describe(e)
    except Exception:
        reason = None
    if reason:
        return reason
    if isinstance(e, (ValueError, LookupError)):
        text = str(e).strip()
        looks_like_path = "\\" in text or text.startswith("/") or ("://" in text and "http" not in text)
        if text and len(text) < 200 and "\n" not in text and not looks_like_path:
            return text
    return "internal error, please try again in a moment"

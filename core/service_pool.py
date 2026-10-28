"""
بازیافت نمونه‌های YoutubeDL، تا برای هر آیتم یه نمونه‌ی تازه ساخته نشه.

## چرا بازیافت مهمه

ساختن YoutubeDL ارزون نیست: افزونه‌های extractor لود می‌شن، cookiejar باز
می‌شه، و تنظیمات اعتبارسنجی می‌شن. اگه یه پلی‌لیست ۲۰تایی داشته باشیم و
برای هر آیتم یه نمونه‌ی نو بسازیم، همین کار چند ثانیه از زمان کاربر
می‌خوره -- بدون هیچ فایده‌ای.

## سه اشتباهی که نسخه‌ی قبلی داشت

**۱. تنظیمات جدید نادیده گرفته می‌شد.** نمونه با اولین opts ساخته می‌شد و
بعدش هر بار همون برمی‌گشت. یعنی وقتی ادمین با دستور `proxy` پروکسی رو عوض
می‌کرد یا با `ck` کوکی رو خاموش می‌کرد، resolve آیتم‌ها **همچنان با تنظیم
قدیمی** انجام می‌شد. حالا کلید کش شامل اثرانگشت خودِ opts است، پس تنظیم
جدید یعنی نمونه‌ی جدید.

**۲. اشتراک بین تردها.** `_resolve_entries_parallel` چند ترد موازی راه
می‌اندازه و همه یه نمونه‌ی مشترک می‌گرفتن. YoutubeDL حالت داخلی
قابل‌تغییر داره (کش، cookiejar، شمارنده‌ها) و برای استفاده‌ی هم‌زمان ساخته
نشده. حالا نمونه‌ها thread-local ان: هر ترد نمونه‌ی خودش رو داره و هیچ
اشتراکی نیست.

**۳. پروبِ زنده‌بودن گران و بی‌معنی.** هر بار `prepare_filename({"id":
"test"})` صدا زده می‌شد که کل ماشین قالب‌بندی اسم فایل yt-dlp رو اجرا
می‌کنه و درباره‌ی سالم‌بودن نمونه هیچ چیز مفیدی نمی‌گه. حذف شد.

## سقف تعداد

هر ترد حداکثر MAX_PER_THREAD نمونه نگه می‌داره (برای ترکیب‌های مختلف
opts). بیشتر از این، قدیمی‌ترین بسته می‌شه -- وگرنه عوض‌کردن مکرر پروکسی
روی یه ربات که هفته‌ها بالاست، یه نشت حافظه‌ی آروم بود.
"""

import atexit
import json
import threading

from core.ytdlp_lazy import YoutubeDL

# هر ترد چند نمونه (برای ترکیب‌های مختلف تنظیمات) نگه داره.
MAX_PER_THREAD = 3

_local = threading.local()
_options_cache = {}
_options_lock = threading.Lock()

# همه‌ی نمونه‌های ساخته‌شده، فقط برای بستن مرتبشون موقع خروج. ترد سازنده
# دیگه در دسترس نیست، پس نمی‌شه از _local برای پاک‌سازی استفاده کرد.
_all_instances = []
_all_lock = threading.Lock()


def _fingerprint(options):
    """
    یه کلید پایدار از تنظیمات.

    فقط کلیدهایی که واقعاً رفتار شبکه/استخراج رو عوض می‌کنن حساب می‌شن.
    چیزهایی مثل logger شیء زنده‌ان و هر بار آدرس دیگه‌ای دارن؛ اگه توی
    کلید می‌اومدن، هیچ‌وقت هیچ نمونه‌ای reuse نمی‌شد.
    """
    if not options:
        return "{}"
    relevant = {}
    for key, value in options.items():
        if key in ("logger", "progress_hooks", "postprocessor_hooks"):
            continue
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            value = repr(value)
        relevant[key] = value
    return json.dumps(relevant, sort_keys=True, default=repr)


def set_yt_options(service_name, options):
    """تنظیمات پیش‌فرض یه سرویس رو نگه می‌داره، برای وقتی که get بدون opts صدا زده بشه."""
    with _options_lock:
        _options_cache[service_name] = dict(options or {})


def get_yt_instance(service_name, options=None):
    """
    یه YoutubeDL برای همین ترد و همین ترکیب تنظیمات.

    نمونه‌ی برگشتی **مخصوص ترد فعلیه** و نباید به ترد دیگه‌ای پاس داده بشه.
    """
    if options is None:
        with _options_lock:
            options = _options_cache.get(service_name) or {}

    key = (service_name, _fingerprint(options))

    instances = getattr(_local, "instances", None)
    if instances is None:
        instances = _local.instances = {}

    existing = instances.get(key)
    if existing is not None:
        return existing

    if len(instances) >= MAX_PER_THREAD:
        # قدیمی‌ترین (اولین کلید درج‌شده) قربانی می‌شه؛ dict پایتون ترتیب درج
        # رو حفظ می‌کنه، پس همین کافیه و به timestamp نیازی نیست.
        oldest_key = next(iter(instances))
        old = instances.pop(oldest_key, None)
        _close(old)

    instance = YoutubeDL(dict(options))
    instances[key] = instance
    with _all_lock:
        _all_instances.append(instance)
    return instance


def evict(service_name, options=None):
    """
    نمونه‌ی این کلید رو از استخر دور می‌ریزه (و می‌بنده).

    وقتی extract_info یه بار fail می‌شه، caller این رو صدا می‌زنه تا دفعه‌ی
    بعد یه نمونه‌ی *تازه* بسازه، نه همون نمونه‌ای که ممکنه توی وضعیتِ بد
    مونده باشه (مثلاً یه اتصالِ HTTP نصفه‌کاره‌ی مرده توی pool داخلیِ خودِ
    yt-dlp/requests). بدونِ این، یه خطای گذرا (قطعی لحظه‌ای شبکه، پروکسی
    یه لحظه جواب نداد) می‌تونست همون نمونه‌ی خراب رو برای *همه‌ی* درخواست‌های
    بعدیِ همون سرویس روی همین ترد نگه داره تا ربات ری‌استارت بشه.
    """
    if options is None:
        with _options_lock:
            options = _options_cache.get(service_name) or {}
    key = (service_name, _fingerprint(options))
    instances = getattr(_local, "instances", None)
    if not instances:
        return
    instance = instances.pop(key, None)
    _close(instance)


def _close(instance):
    if instance is None:
        return
    try:
        instance.close()
    except Exception:
        pass
    with _all_lock:
        try:
            _all_instances.remove(instance)
        except ValueError:
            pass


def cleanup_yt_instances():
    """همه‌ی نمونه‌ها رو می‌بنده (موقع خروج برنامه)."""
    with _all_lock:
        instances = list(_all_instances)
        _all_instances.clear()
    for instance in instances:
        try:
            instance.close()
        except Exception:
            pass
    if getattr(_local, "instances", None) is not None:
        _local.instances = {}


def stats():
    """برای دیباگ: چند نمونه زنده‌ست و توی این ترد چندتاست."""
    with _all_lock:
        total = len(_all_instances)
    return {"total": total, "this_thread": len(getattr(_local, "instances", {}) or {})}


atexit.register(cleanup_yt_instances)

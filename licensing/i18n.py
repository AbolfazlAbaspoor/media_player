"""
ترجمه‌ی متن‌های پلتفرم لایسنس.

## زبان پیش‌فرض انگلیسیه

هر متنی که کاربر یا ادمین می‌بینه از فایل‌های locale خونده می‌شه و پیش‌فرض
انگلیسیه. فارسی یه ترجمه‌ست مثل بقیه، نه حالت خاص -- پس اضافه‌کردن زبان
سوم فقط یه فایل JSON جدیده، بدون دست‌زدن به کد.

## چرا ContextVar و نه پارامتر zabān

اگه زبان رو به‌عنوان پارامتر به همه‌ی توابع متن پاس می‌دادیم، هر امضا و
هر نقطه‌ی فراخوانی باید عوض می‌شد (چند صد جا). در عوض زبانِ «کاربر فعلی»
اول هر آپدیت یک بار ست می‌شه و توابع متن خودشون ازش می‌خونن.

ContextVar (نه متغیر سراسری) عمدیه: هر آپدیت تلگرام توی یه Task جدای
asyncio پردازش می‌شه و هر Task کپی خودش از context رو داره. با یه متغیر
سراسری، دو کاربر هم‌زمان با دو زبان مختلف، زبان همدیگه رو خراب می‌کردن.

## قاعده‌ی fallback

    زبان کاربر -> انگلیسی -> خودِ کلید

برگردوندن خودِ کلید (به‌جای خطا) عمدیه: یه کلید جاافتاده باید توی خروجی
دیده بشه و درست بشه، نه اینکه ربات رو بخوابونه.
"""

import contextvars
import json
import os
import threading

from core.paths import resource_dir

DEFAULT_LANGUAGE = "en"

LOCALES_DIR = resource_dir("licensing", "locales")

# اسم قابل‌نمایش هر زبان، به خودِ اون زبان.
LANGUAGE_NAMES = {
    "en": "English",
    "fa": "فارسی",
}

_strings = {}
_lock = threading.RLock()
_loaded = False

_current = contextvars.ContextVar("licensing_language", default=DEFAULT_LANGUAGE)


def load(force=False):
    """همه‌ی فایل‌های locale رو می‌خونه. idempotent."""
    global _loaded
    with _lock:
        if _loaded and not force:
            return _strings
        _strings.clear()
        if os.path.isdir(LOCALES_DIR):
            for name in sorted(os.listdir(LOCALES_DIR)):
                if not name.endswith(".json"):
                    continue
                code = name[:-5]
                try:
                    with open(os.path.join(LOCALES_DIR, name), "r", encoding="utf-8") as f:
                        data = json.load(f)
                except (ValueError, OSError) as e:
                    print(f"[i18n] locale '{name}' could not be read: {e}")
                    continue
                _strings[code] = data if isinstance(data, dict) else {}
        _loaded = True
        return _strings


def available():
    """[(code, display_name)] برای زبان‌هایی که فایلشون هست."""
    load()
    return [(code, LANGUAGE_NAMES.get(code, code)) for code in sorted(_strings)]


def is_supported(lang):
    load()
    return lang in _strings


def normalize(lang):
    """
    زبان معتبر برمی‌گردونه. ورودی می‌تونه None، یه کد ناشناس، یا مثلاً
    «fa-IR» باشه.
    """
    if not lang:
        return DEFAULT_LANGUAGE
    code = str(lang).strip().lower().replace("_", "-").split("-")[0]
    return code if is_supported(code) else DEFAULT_LANGUAGE


def set_language(lang):
    """زبان همین آپدیت. برگردوندن token برای reset (معمولاً لازم نیست)."""
    return _current.set(normalize(lang))


def get_language():
    return _current.get()


def t(key, /, **kwargs):
    """
    متن ترجمه‌شده. مقدارهای kwargs با format جایگزین می‌شن.

    `key` عمداً positional-only است (اون `/`): خیلی از متن‌ها خودشون یه
    جای‌گذاریِ `{key}` دارن (کلید لایسنس)، و بدون این، فراخوانی
    `t("...", key=license_key)` با خطای «دو مقدار برای key» می‌شکست.

    اگه format شکست بخوره (کلیدی که توی ترجمه نیست)، متن خام برگردونده
    می‌شه نه استثنا -- یه ترجمه‌ی ناقص نباید ربات رو بخوابونه.
    """
    load()
    lang = _current.get()
    template = _strings.get(lang, {}).get(key)
    if template is None:
        template = _strings.get(DEFAULT_LANGUAGE, {}).get(key)
    if template is None:
        return key
    if isinstance(template, list):
        template = "\n".join(template)
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return template


def has(key):
    load()
    return any(key in table for table in _strings.values())


def missing_keys(reference=DEFAULT_LANGUAGE):
    """
    {lang: [کلیدهای جاافتاده]} -- برای اینکه یه ترجمه‌ی ناقص ساکت نمونه.
    توی تست و دستور /reload استفاده می‌شه.
    """
    load()
    base = set(_strings.get(reference, {}))
    report = {}
    for code, table in _strings.items():
        if code == reference:
            continue
        gap = sorted(base - set(table))
        if gap:
            report[code] = gap
    return report

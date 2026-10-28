"""
سیستم چندزبانه‌ی پیام‌هایی که ربات به کاربرها می‌فرسته (channel_message/user_message).
زبان پیش‌فرض انگلیسیه. فایل‌های زبان به‌صورت JSON توی پوشه‌ی languages/
(کنار اسکریپت اصلی) نگه‌داری می‌شن، هر فایل یه زبان: languages/en.json, languages/fa.json و...

فرمت هر فایل:
{
  "name": "English",
  "strings": { "key": "template with {placeholders}", ... }
}

توجه: این ماژول فقط پیام‌های چت رو پوشش می‌ده. پرامپت‌های کنسول (مثلاً ویزارد
اول اجرا که فقط ادمین محلی می‌بینه، نه یوزرهای تیم‌تاک) بخشی از این سیستم نیستن.
"""

import json
import os

from core.paths import resource_dir

# مسیر مطلق، نه نسبی: ربات ممکنه از هر پوشه‌ای اجرا بشه (مثلاً از طریق
# launcher.py یا یه شورتکات) و اون‌موقع مسیر نسبی "languages" پیدا نمی‌شه
# و همه‌ی پیام‌ها به‌جای متن واقعی، خودِ کلید خام رو نشون می‌دن.
# resource_dir هم حالت بیلدشده رو پوشش می‌ده: فایل‌های زبان داخل باندل
# PyInstaller باز می‌شن، ولی یه پوشه‌ی languages/ کنار فایل اجرایی (مثلاً
# با یه ترجمه‌ی دست‌کاری‌شده) اولویت داره.
LANGUAGES_DIR = resource_dir("languages")
DEFAULT_LANGUAGE = "en"

_strings = {}
_available = []
_current = DEFAULT_LANGUAGE

def load_languages(folder=LANGUAGES_DIR):
    global _strings, _available
    _strings = {}
    _available = []
    if not os.path.isdir(folder):
        return
    for filename in sorted(os.listdir(folder)):
        if not filename.endswith(".json"):
            continue
        code = filename[:-5]
        path = os.path.join(folder, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        _strings[code] = data.get("strings", {})
        _available.append((code, data.get("name", code)))

def available_languages():
    """[(code, name), ...] به همون ترتیب لود شده"""
    return list(_available)

def current_language():
    """(code, name) زبان فعلی"""
    for code, name in _available:
        if code == _current:
            return code, name
    return _current, _current

def set_language(query):
    """
    با کد (en) یا اسم (English) زبان رو عوض می‌کنه (case-insensitive).
    اگه پیدا بشه True، وگرنه False برمی‌گردونه.
    """
    global _current
    query = (query or "").strip().lower()
    for code, name in _available:
        if code.lower() == query or name.lower() == query:
            _current = code
            return True
    return False

def t(key, **kwargs):
    """
    رشته‌ی متناظر با key رو توی زبان فعلی برمی‌گردونه (fallback: انگلیسی،
    بعد خودِ key).

    شکست‌ها **لاگ می‌شن**، چون هر دو حالتِ شکست چیزی رو به کاربر نشون
    می‌دن که هیچ معنایی براش نداره:

      * کلید گم‌شده -> خودِ کلید چاپ می‌شه («now_playing_full_live»)
      * فرمت خراب  -> قالب با آکولادهای خام چاپ می‌شه («{title} توسط {nickname}»)

    قبلاً هر دو بی‌صدا رد می‌شدن، پس یه تایپو توی اسم کلید یا یه آرگومان
    اشتباه (مثل پاس‌دادن کل ctx به‌جای nickname) هیچ ردی توی لاگ
    نمی‌ذاشت و فقط کاربر یه پیام بی‌معنی می‌دید.
    """
    template = _strings.get(_current, {}).get(key)
    if template is None:
        template = _strings.get(DEFAULT_LANGUAGE, {}).get(key)
        if template is None:
            _log_broken(f"missing i18n key '{key}' (languages: {_current}, {DEFAULT_LANGUAGE})")
            return key
    try:
        return template.format(**kwargs)
    except Exception as e:
        _log_broken(f"i18n key '{key}' failed to format ({e}); args={sorted(kwargs)}")
        return template


def _log_broken(message):
    # import تنبل: logging_setup خودش i18n رو لازم داره و import بالای
    # فایل یه حلقه‌ی import می‌ساخت.
    try:
        from core import logging_setup
        logging_setup.log_warning(message, context="i18n")
    except Exception:
        pass

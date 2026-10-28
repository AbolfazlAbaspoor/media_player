"""
مسیرهای برنامه، هم وقتی مستقیم با پایتون اجرا می‌شه و هم بعد از بیلد با
PyInstaller.

دو مفهوم *متفاوت* داریم که نباید قاطی بشن:

    get_base_dir()      -> جایی که داده‌ی همین نصب می‌نشینه (data/, errors/).
                           بعد از بیلد، پوشه‌ی خود فایل اجراییه، نه پوشه‌ی
                           موقتِ PyInstaller -- وگرنه کانفیگ و دیتابیس با
                           هر اجرا پاک می‌شدن.

    resource_dir(name)  -> جایی که فایل‌های *همراه برنامه* هستن
                           (commands/, languages/, core/services/).
                           این‌ها موقع بیلد داخل باندل می‌رن و در زمان اجرا
                           توی sys._MEIPASS باز می‌شن.

## چرا resource_dir اول بیرون رو نگاه می‌کنه

اگه کاربر پوشه‌ی commands/ رو کنار فایل اجرایی بذاره، همون باید برنده بشه.
این‌طوری می‌شه بدون بیلد مجدد، دستور جدید اضافه کرد یا یه دستور موجود رو
عوض کرد -- که کل ایده‌ی پلاگین‌بودن پوشه‌ی commands/ همینه. نسخه‌ی داخل
باندل فقط fallback است.
"""

import json
import os
import sys


def write_json_atomic(path, data, indent=4, makedirs=False, per_process_tmp=False):
    """
    JSON رو اتمی می‌نویسه: اول توی فایل موقت، بعد os.replace. اگه چند
    پروسه هم‌زمان بنویسن یا برق بره، هیچ‌وقت یه JSON نصفه روی دیسک
    نمی‌مونه. per_process_tmp: اسم فایل موقت pid داره (فایل مشترک بین
    ربات‌ها).
    """
    if makedirs:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp" if per_process_tmp else f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
    os.replace(tmp, path)


def force_utf8_console():
    """
    کنسول ویندوز معمولاً cp1256/cp720 است و چاپ فارسی روش UnicodeEncodeError
    می‌ده -- یعنی اسکریپت قبل از اینکه کاری بکنه می‌میره. همه‌ی نقطه‌های
    ورودی (bot/launcher/manage/license_server/install/build) اولِ کارشون
    همین رو صدا می‌زنن.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def get_base_dir():
    """پوشه‌ی داده‌ی این نصب (data/, errors/, کنار برنامه)."""
    if is_frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def bundle_dir():
    """
    پوشه‌ی موقتی که PyInstaller فایل‌های باندل‌شده رو توش باز می‌کنه.
    در حالت اجرای عادی، همون پوشه‌ی پروژه.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return meipass
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_dir(*parts):
    """
    مسیر یه پوشه/فایلِ همراه برنامه.

    اول کنار برنامه (تا کاربر بتونه override کنه)، بعد داخل باندل. اگه
    هیچ‌کدوم نبود، مسیر کنار برنامه برگردونده می‌شه -- چون همون‌جاییه که
    کاربر باید بسازدش، و پیام خطا این‌طور مفیدتره.
    """
    external = os.path.join(get_base_dir(), *parts)
    if os.path.exists(external):
        return external
    bundled = os.path.join(bundle_dir(), *parts)
    if os.path.exists(bundled):
        return bundled
    return external

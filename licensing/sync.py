"""
همگام‌سازی خودکار کاتالوگ فروش با *واقعیتِ* روی دیسک.

## مشکلی که این فایل حل می‌کنه

اضافه‌کردن یه سرویس یا دستور جدید دو تا کار لازم داره، نه یکی:

  ۱. فایلش رو بساز (`core/services/x.py` یا `commands/x.py`)
  ۲. توی `licensing/catalog.py` ثبتش کن

کار دوم **بی‌صدا** فراموش می‌شه. `core/license_gate.py` هرچی توی کاتالوگ
نباشه رو فیلتر می‌کنه، پس نتیجه‌ی فراموش‌کردنش اینه که قابلیت روی دیسک
هست، لود می‌شه، تست هم پاس می‌ده -- ولی روی هر ربات لایسنس‌دار **اصلاً
دیده نمی‌شه**. هیچ خطایی هم نمی‌ده؛ فقط نیست.

(این دقیقاً یه بار اتفاق افتاد: ۱۴ سرویس روی دیسک بود و ربات ۵ تا
می‌دید.)

## راه‌حل

اینجا هر دو طرف رو می‌خونیم و اختلاف رو گزارش/رفع می‌کنیم:

  * `drift()`   -> چی روی دیسک هست ولی توی کاتالوگ نیست (و برعکس)
  * `autoregister()` -> موارد گم‌شده رو به کاتالوگِ در حال اجرا اضافه می‌کنه
  * `report_text()`  -> خلاصه‌ی خوانا برای ادمین

## چرا قیمت خودکار نمی‌ذاریم

قیمت یه تصمیم تجاریه، نه فنی. سرویس جدید با `AUTO_PRICE_USD` ثبت می‌شه و
صریحاً «قیمت‌گذاری‌نشده» علامت می‌خوره تا ادمین ببینه و تصمیم بگیره --
به‌جای این‌که یه عدد ساختگی بی‌سروصدا بره توی فاکتور مشتری.
"""

import os

from core import paths
from core import manager
from core.paths import get_base_dir, resource_dir
from licensing import catalog

#: قیمت پیش‌فرضِ چیزی که خودکار ثبت شده. عمداً غیرصفر تا مجانی فروخته
#: نشه، و عمداً گرد تا توی گزارش تابلو باشه که دستی تنظیم نشده.
AUTO_PRICE_USD = 1.0

#: پیشوند کد امکاناتی که این ماژول ساخته -- برای این‌که توی گزارش از
#: چیزهای دستی جدا بشن.
AUTO_PREFIX = "auto_"


def _commands_dir():
    return resource_dir("commands")


def discover_services():
    """اسم سرویس‌هایی که واقعاً روی دیسکن."""
    folder = manager.DEFAULT_SERVICES_DIR
    if not os.path.isdir(folder):
        return set()
    return {
        name[:-3] for name in os.listdir(folder)
        if name.endswith(".py") and not name.startswith("_")
    }


def discover_commands():
    """
    اسم دستورهایی که واقعاً روی دیسکن، شاملِ نام‌های مستعار.

    فایل import نمی‌شه: خوندن `NAME = ...` با ast هم ارزون‌تره هم امن‌تر
    (import کردنِ ۱۰۰ فایل دستور فقط برای گرفتن اسمشون، هر side-effect ای
    رو هم اجرا می‌کرد).
    """
    import ast

    folder = _commands_dir()
    if not os.path.isdir(folder):
        return set()

    names = set()
    for filename in os.listdir(folder):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue
        path = os.path.join(folder, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), path)
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "NAME" not in targets:
                continue
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                names.add(value.value)
            elif isinstance(value, (ast.Tuple, ast.List)):
                for element in value.elts:
                    if isinstance(element, ast.Constant) and isinstance(element.value, str):
                        names.add(element.value)
    return names


def _catalog_names(base_key, field):
    data = catalog.load()
    known = set(data.get(base_key) or [])
    for feature in data.get("features", {}).values():
        known.update(feature.get(field) or [])
    return known


def catalog_services():
    """سرویس‌هایی که کاتالوگ می‌شناسه (پایه + همه‌ی امکانات)."""
    return _catalog_names("base_services", "services")


def catalog_commands():
    return _catalog_names("base_commands", "commands")


def drift():
    """
    اختلاف دیسک و کاتالوگ.

    خروجی dict با چهار کلید:
      missing_services / missing_commands -- روی دیسک هست، توی کاتالوگ نیست
                                             (= روی ربات لایسنس‌دار نامرئی)
      stale_services   / stale_commands   -- توی کاتالوگ هست، روی دیسک نیست
                                             (= داریم چیزی می‌فروشیم که وجود نداره)
    """
    disk_services, disk_commands = discover_services(), discover_commands()
    known_services, known_commands = catalog_services(), catalog_commands()
    return {
        "missing_services": sorted(disk_services - known_services),
        "missing_commands": sorted(disk_commands - known_commands),
        "stale_services": sorted(known_services - disk_services

                                 - set(catalog.CAPABILITY_SERVICES)),
        "stale_commands": sorted(known_commands - disk_commands),
    }


def autoregister(persist=False):
    """
    هرچی روی دیسک هست ولی توی کاتالوگ نیست رو ثبت می‌کنه تا نامرئی نمونه.

    سرویس‌ها هرکدوم یه امکانِ جدا می‌گیرن (چون جدا فروخته می‌شن). دستورهای
    بی‌صاحب توی یه امکانِ واحد جمع می‌شن -- یه دستور معمولاً بخشی از یه
    قابلیت بزرگ‌تره، نه یه محصول مستقل.

    persist=True نتیجه رو توی data/licensing/catalog.json می‌نویسه تا بعد
    از ری‌استارت هم بمونه و ادمین بتونه قیمت‌ها رو همون‌جا ویرایش کنه.

    خروجی: لیست کدهای امکاناتی که ساخته شد.
    """
    gaps = drift()
    if not gaps["missing_services"]:
        return []

    data = catalog.load()
    features = data.setdefault("features", {})
    created = []

    for service in gaps["missing_services"]:
        code = f"{AUTO_PREFIX}svc_{service}"
        if code in features:
            continue
        features[code] = {
            "title_fa": f"سرویس {service}",
            "title_en": service.capitalize(),
            "price_usd": AUTO_PRICE_USD,
            "services": [service],
            "commands": [],
            "note_fa": "خودکار ثبت شد — قیمت و توضیحش رو تنظیم کن.",
            "note_en": "Registered automatically — set its price and description.",
            "auto": True,
        }
        created.append(code)

    # دستورها دیگه جزو لایسنس نیستن، پس دستورِ بی‌صاحب توی یه امکانِ پولی
    # جمع نمی‌شه -- اون کار یه دستورِ رایگان رو برای فروش می‌ذاشت. دستوری
    # که به یه سرویس نیاز داره باید دستی توی commands همون امکان بیاد.

    if persist and created:
        _persist(features)
    return created


def _persist(features):
    """
    فقط امکاناتِ خودکار رو به فایل override اضافه می‌کنه.

    کل کاتالوگ نوشته نمی‌شه: فایل override عمداً «فقط تفاوت‌ها»ست، و
    ریختن همه‌چیز توش یعنی هر تغییر بعدیِ پیش‌فرض‌ها توی کد، بی‌اثر می‌شد.
    """
    import json

    path = catalog.OVERRIDE_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        if not isinstance(existing, dict):
            existing = {}
    except (FileNotFoundError, ValueError):
        existing = {}

    bucket = existing.setdefault("features", {})
    for code, feature in features.items():
        if feature.get("auto"):
            bucket[code] = feature

    paths.write_json_atomic(path, existing, indent=2)


def report_text(gaps=None):
    """خلاصه‌ی خوانا برای ادمین. رشته‌ی خالی یعنی همه‌چیز همگامه."""
    gaps = gaps if gaps is not None else drift()
    lines = []
    if gaps["missing_services"]:
        lines.append("سرویس روی دیسک ولی خارج از کاتالوگ (روی ربات لایسنس‌دار دیده نمی‌شه): "
                     + ", ".join(gaps["missing_services"]))
    # دستورِ بیرون از کاتالوگ مشکل نیست: لایسنس روی دستورها قفل نمی‌کنه و
    # چنین دستوری برای همه آزاده. فقط دستوری که به یه سرویسِ پولی نیاز
    # داره باید توی commands همون امکان بیاد -- و اون رو sync نمی‌تونه حدس بزنه.
    if gaps["stale_services"]:
        lines.append("سرویس توی کاتالوگ ولی روی دیسک نیست (داریم چیزی می‌فروشیم که وجود نداره): "
                     + ", ".join(gaps["stale_services"]))
    if gaps["stale_commands"]:
        lines.append("دستور توی کاتالوگ ولی روی دیسک نیست: "
                     + ", ".join(gaps["stale_commands"]))
    return "\n".join(lines)

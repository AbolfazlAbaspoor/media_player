"""
ربات فروش و لایسنس (تلگرام) -- نقطه‌ی ورود.

کد اصلی بر اساس حوزه توی پکیج licensing/telegram/sales/ تقسیم شده (توضیح
جریان و چیدمان: sales/__init__.py). این فایل فقط build_application رو
می‌ده و اسم‌های قدیمیِ این ماژول رو هم هنوز جواب می‌ده، تا هر چیزی که
`sales_bot.<اسم>` صدا می‌زد (license_server.py، تست‌ها، اسکریپت‌های
خودت) بدون تغییر کار کنه.
"""

import importlib

from licensing.telegram.sales.app import build_application

# فهرستِ ماژول‌ها فقط یک‌جاست؛ هر اسم هم به‌صورت ویژگیِ همین ماژول
# (sales_bot.common و ...) در دسترسه، مثل importِ صریح.
_MODULE_NAMES = (
    "common",
    "menu",
    "purchase",
    "payment",
    "approval",
    "crypto_payment",
    "wizard",
    "my_licenses",
    "personal_bot",
    "promo_codes",
    "support",
    "admin_panel",
    "admin_grants",
    "admin_commands",
    "text_input",
    "callbacks",
    "background",
    "app",
)
_MODULES = tuple(importlib.import_module(f"licensing.telegram.sales.{name}")
                 for name in _MODULE_NAMES)
globals().update(zip(_MODULE_NAMES, _MODULES))


def __getattr__(name):
    for module in _MODULES:
        if name in vars(module):
            return vars(module)[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

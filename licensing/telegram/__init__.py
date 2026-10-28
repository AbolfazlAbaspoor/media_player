"""
لایه‌ی تلگرام پلتفرم.

    texts.py         متن‌های ربات (از روی locale، پیش‌فرض انگلیسی)
    keyboards.py     کیبوردهای inline
    sales_bot.py     نقطه‌ی ورود ربات اصلی (build_application)
    sales/           ربات اصلی، یه ماژول برای هر حوزه (خرید، رسید، ادمین، ...)
    setup_wizard.py  ویزارد راه‌اندازی ربات، مشترک بین ربات فروش و ربات شخصی
    channel_gate.py  عضویت اجباری کانال رسمی
    customer_bot.py  ربات شخصی هر مشتری (توکن از BotFather)
    runner.py        اجرای هم‌زمان ربات فروش و ربات‌های شخصی

پروکسی هم اینجاست: هر سه‌تا مسیرِ ساختن کلاینت تلگرام باید *یک* جور
پروکسی بگیرن، وگرنه یکی‌شون (مثلاً اعتبارسنجی توکن) از پروکسی رد نمی‌شه
و روی سرور فیلترشده بی‌صدا تایم‌اوت می‌خوره.
"""

from licensing import config


def apply_network(builder):
    """
    پروکسی و تایم‌اوت‌های کانفیگ رو روی ApplicationBuilder می‌ذاره.

    get_updates_* جداست چون PTB برای long-polling یه کلاینت دیگه می‌سازه؛
    بدون این، getUpdates از پروکسی رد نمی‌شد و ربات با اینکه «وصل» بود
    هیچ پیامی نمی‌گرفت.
    """
    proxy = config.proxy_url()
    if proxy:
        builder = builder.proxy(proxy).get_updates_proxy(proxy)
    timeout = config.network_timeout()
    return (builder
            .connect_timeout(timeout)
            .read_timeout(timeout)
            .get_updates_connect_timeout(timeout)
            .get_updates_read_timeout(timeout)
            .get_updates_pool_timeout(timeout))


def request_kwargs():
    """برای جاهایی که به‌جای Application مستقیم telegram.Bot ساخته می‌شه."""
    proxy = config.proxy_url()
    if not proxy:
        return {}
    from telegram.request import HTTPXRequest
    return {"request": HTTPXRequest(proxy=proxy)}

"""
پخش مستند از یه منبع شماره‌گذاری‌شده.

## مدل

فایل‌ها با یه شماره آدرس‌دهی می‌شن و آدرسشون از یه الگو ساخته می‌شه:

    https://cfdl.ir/vmfiles/7.mkv
    https://cfdl.ir/vmfiles/8.mkv
    ...

شماره از یه حد پایین شروع می‌شه (پیش‌فرض ۷) و سقف نداره. هیچ‌جا لیست
مستندها گرفته نمی‌شه، چون منبع لیستی نمی‌ده -- فقط آدرس ساخته می‌شه.

## چرا هیچ درخواست شبکه‌ای نمی‌زنه

آدرس به `.mkv` تموم می‌شه، پس link_resolver اون رو «مدیای مستقیم» تشخیص
می‌ده و yt-dlp اصلاً صدا زده نمی‌شه. یعنی از لحظه‌ی زدن دستور تا شروع پخش،
تنها درخواست شبکه همون درخواستیه که خودِ mpv برای خوندن فایل می‌زنه. این
سریع‌ترین مسیر ممکنه و هیچ ردپایی برای bot-detection نمی‌سازه.

## حالت مستند

بعد از پخش یه مستند، ربات توی «حالت مستند» می‌مونه: فرستادن یه عدد خام
(مثلاً `22`) یعنی «مستند ۲۲ رو پخش کن». این حالت با پخش هر چیز دیگه‌ای
(سرچ، لینک، پلی‌لیست) خودکار بسته می‌شه، تا عدد خام دوباره معنی همیشگی
خودش (پریدن به آیتم پلی‌لیست) رو پیدا کنه.

## تنظیمات

توی shared_config.json بخش documentary:

    "documentary": {
        "url_template": "https://cfdl.ir/vmfiles/{n}.mkv",
        "min_number": 7,
        "max_number": 0,        // ۰ یعنی بی‌نهایت
        "title_template": "مستند {n}"
    }

الگو با {n} جایگزین می‌شه، پس تغییر منبع یا پسوند فایل فقط یه ویرایش
کانفیگه، نه تغییر کد.
"""

from core import config_defaults
from core import i18n
from core import license_gate

SERVICE_NAME = "documentary"

DEFAULTS = config_defaults.DOCUMENTARY_DEFAULTS


class DocumentaryError(Exception):
    """خطای قابل‌نمایش به کاربر (شماره نامعتبر، تنظیمات خراب)."""


def settings(bot):
    """تنظیمات مستند، با پر کردن جاهای خالی از پیش‌فرض."""
    return config_defaults.feature_settings(bot, "documentary", DEFAULTS)


def min_number(bot):
    return config_defaults.positive_int_setting(settings(bot), "min_number", DEFAULTS)


def max_number(bot):
    """سقف شماره، یا None اگه سقفی نباشه."""
    try:
        value = int(settings(bot)["max_number"])
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def is_valid_number(bot, number):
    try:
        number = int(number)
    except (TypeError, ValueError):
        return False
    if number < min_number(bot):
        return False
    ceiling = max_number(bot)
    return not (ceiling is not None and number > ceiling)


def url_for(bot, number):
    template = str(settings(bot)["url_template"])
    if "{n}" not in template:
        raise DocumentaryError(i18n.t("documentary_bad_template"))
    return template.replace("{n}", str(int(number)))


def title_for(bot, number):
    template = str(settings(bot).get("title_template") or DEFAULTS["title_template"])
    return template.replace("{n}", str(int(number)))


def item_for(bot, number):
    """
    همون dict ای که load_and_play می‌خواد. public_url هم خودِ آدرس فایله،
    چون لینکِ قابل‌اشتراکِ دیگه‌ای وجود نداره.
    """
    number = int(number)
    url = url_for(bot, number)
    return {"url": url, "title": title_for(bot, number), "public_url": url}


def range_text(bot):
    """توضیح بازه‌ی مجاز، برای پیام خطا (به زبان فعلیِ ربات)."""
    low = min_number(bot)
    ceiling = max_number(bot)
    if ceiling is None:
        return i18n.t("documentary_range_open", low=low)
    return i18n.t("documentary_range_bounded", low=low, high=ceiling)


def is_active(bot):
    """آیا الان توی حالت مستندیم (یعنی عدد خام معنی مستند داره)؟"""
    return getattr(bot, "documentary_number", None) is not None


def current_number(bot):
    return getattr(bot, "documentary_number", None)


def licensed(bot):
    """
    آیا این ربات اجازه‌ی پخش مستند داره؟

    چک از خود لایسنس انجام می‌شه، نه فقط از وجود دستور md: مسیر «عدد خام»
    یه دستور جدا نیست و بدون این چک، کسی که md نخریده می‌تونست با فرستادن
    یه عدد به مستند برسه.
    """
    return license_gate.bot_allows_service(bot, SERVICE_NAME)


def play(bot, number, requested_by=None):
    """
    مستند شماره‌ی داده‌شده رو پخش می‌کنه و حالت مستند رو فعال نگه می‌داره.

    خروجی: dict آیتم پخش‌شده.
    خطا: DocumentaryError با پیام فارسیِ قابل‌نمایش.
    """
    if not licensed(bot):
        raise DocumentaryError(i18n.t("documentary_not_licensed"))

    if not is_valid_number(bot, number):
        raise DocumentaryError(i18n.t("documentary_invalid_number", range=range_text(bot)))

    number = int(number)
    item = item_for(bot, number)

    # private=True: لینک مستند فایلِ پولیِ خودِ صاحب رباته. نه با k به کسی
    # داده می‌شه، نه توی تاریخچه (که لینک نشون می‌ده) ثبت می‌شه. dl هم از
    # روی سرویس (PAID_PRIVATE_SERVICES) ردش می‌کنه.
    bot.load_and_play(item, private=True, service_name=SERVICE_NAME)
    bot.documentary_number = number
    return item


def step(bot, delta, requested_by=None):
    """
    مستند بعدی (delta=+1) یا قبلی (delta=-1).

    چرا اینجا و نه توی صف: هر مستند تک‌آیتمی پخش می‌شه و صف طولش ۱ می‌مونه،
    پس n/b از مسیر عادیِ صف به «آخر صف» می‌خوردن. مستندها یه دنباله‌ی
    شماره‌ای‌ان، نه یه پلی‌لیست -- حرکت بینشون یعنی عوض‌کردن عدد.

    خروجی: dict آیتم پخش‌شده، یا None اگه به لبه‌ی بازه‌ی مجاز رسیدیم.
    """
    current = current_number(bot)
    if current is None:
        return None
    target = int(current) + int(delta)
    if not is_valid_number(bot, target):
        return None
    return play(bot, target, requested_by=requested_by)


def clear(bot):
    """
    از حالت مستند خارج می‌شه. load_and_play برای هر پخشی که سرویسش مستند
    نیست این رو صدا می‌زنه.
    """
    bot.documentary_number = None


def announce_playing(bot, item, nickname):
    """
    پیامِ «الان این مستند پخش می‌شه» -- یه‌بار اینجا، تا هر مسیری که مستند
    پخش می‌کنه (md، عددِ خام توی bot.py، n/b) از همینِ یکی استفاده کنه.
    عنوان از خودِ item میاد چون display_title (که برای صف/وضعیت استفاده
    می‌شه) هر عنوانی که لینک‌شکل باشه رو برای محتوای پولی حذف می‌کنه --
    اینجا لازم نیست، چون item["title"] همیشه «مستند N» است، نه لینک.
    """
    bot.channel_broadcast(i18n.t("documentary_playing", title=item["title"], nickname=nickname))

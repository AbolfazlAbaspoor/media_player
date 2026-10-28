"""
قفل امکانات بر اساس لایسنس، از سمت خودِ ربات.

## قاعده‌ی اصلی: بدون لایسنس معتبر، ربات اجرا نمی‌شه

هیچ حالت «باز و بدون قفت»ی وجود نداره. اگه license.json نباشه، خراب باشه،
منقضی باشه یا امضاش جور نباشه، ربات با کد خروج ۳ می‌ایسته -- نه اینکه
ناقص یا کامل بالا بیاد.

REQUIRE_LICENSE پایین همین سیاست رو در *یک جا* نگه می‌داره. عمداً از
کانفیگ خونده نمی‌شه: اگه یه کلید کانفیگ می‌تونست خاموشش کنه، خودِ اون کلید
راهِ دور زدن لایسنس بود.

## پس خودِ مالک چطور ربات رو اجرا کنه؟

با یه لایسنس واقعی، نه با استثنا. مالکِ پلتفرم کلید امضا و دیتابیس رو داره،
پس می‌تونه برای خودش لایسنس دائمی صادر کنه:

    python manage.py self-license <telegram_id>

این یه لایسنس همیشگی با همه‌ی امکانات می‌سازه و از همون مسیر عادی عبور
می‌کنه. مزیتش بر یه backdoor: هیچ مسیر دومی توی کد نیست که بشه پیداش کرد
و ازش سوءاستفاده کرد.

## پاک‌کردن فایل لایسنس، راه فرار نیست

قبلاً «فایل نیست» یعنی «قفلی نیست»، پس حذف license.json همه‌چیز رو باز
می‌کرد. حالا برعکسه: نبودن فایل یعنی اجرا نشدن. پرچم MANAGED_FLAG توی
identity.json همچنان نگه داشته می‌شه، ولی فقط برای این‌که پیام خطا دقیق‌تر
باشه -- نه برای تصمیمِ اجرا/عدم‌اجرا.

## چطور قفل می‌کنه

**فقط روی سرویس‌ها، هیچ‌وقت روی دستورها.** همه‌ی دستورها همیشه لود
می‌شن؛ `p music` اجرا می‌شه حتی اگه سرویسی که قراره جوابش رو بده توی
لایسنس نباشه.

  * سرویس‌های پخش که توی لایسنس نیستن از bot.services حذف می‌شن.
  * قابلیت‌ها (مستند، دانلود، پروکسی...) هم سرویس حساب می‌شن. دستوری
    که به یکی‌شون نیاز داره (catalog.service_for_command) می‌مونه و موقع
    اجرا می‌گه «توی لایسنست نیست».

سرویس‌های مجاز از سه جا جمع می‌شن تا لایسنس‌های قدیمی هم درست کار کنن:
`services` خودِ فایل، باز کردنِ `features` با کاتالوگ، و (برای فایل‌های
خیلی قدیمی) دستورهایی که قبلاً مجاز بودن.
"""

import json
import os
import time

from core import logging_setup

# سیاست واحد: برای اجرا لایسنس لازمه. از کانفیگ خونده نمی‌شه -- یه کلید
# کانفیگ که می‌تونست این رو خاموش کنه، خودش راه دور زدن لایسنس بود.
REQUIRE_LICENSE = True

LICENSE_FILE_NAME = "license.json"
IDENTITY_FILE_NAME = "identity.json"

# کلیدی که پلتفرم توی identity.json می‌ذاره تا معلوم باشه این نمونه
# «مدیریت‌شده»ست و بدون لایسنس معتبر نباید اجرا بشه.
MANAGED_FLAG = "platform_managed"

# وضعیت‌هایی که یعنی «الان هیچ امکانی نداری». paused مال عضو نبودن توی
# کانال رسمیه و با برگشتن خودکار برمی‌گرده؛ suspended/revoked دستی‌اند.
BLOCKING_STATUSES = ("suspended", "revoked", "paused")

# وقتی لایسنس منقضیه ولی هنوز توی مهلته: فقط سرویس‌های پایه (یوتیوب). قبلاً
# هیچ سرویسی نمی‌موند و ربات سالم بالا می‌اومد ولی به هر درخواستی می‌گفت
# «سرویسی لود نشده» -- مهلت یعنی وقت تمدید، نه یه ربات مرده.


class LicenseState:
    """
    وضعیت لایسنسِ همین نمونه‌ی ربات.

    unlicensed=True یعنی فایل لایسنس نبود یا قابل‌اعتماد نبود. با
    REQUIRE_LICENSE فعال (پیش‌فرض) این یعنی ربات اجرا نمی‌شه.
    """

    def __init__(self, data=None, path=None, unlicensed=False, managed=False, problem=None):
        self.path = path
        self.unlicensed = unlicensed
        # managed=True یعنی این نمونه رو پلتفرم ساخته. با هم بودن
        # unlicensed=True و managed=True یعنی «لایسنسش گم/خراب شده» که
        # بدترین حالته و جلوی اجرا گرفته می‌شه.
        self.managed = managed
        self.problem = problem
        self.data = data or {}

    # ------------------------------------------------------------ خواندن

    @property
    def key(self):
        return self.data.get("key")

    @property
    def status(self):
        return self.data.get("status", "active")

    @property
    def expires_at(self):
        return int(self.data.get("expires_at") or 0)

    @property
    def grace_until(self):
        value = self.data.get("grace_until")
        return int(value) if value else None

    @property
    def features(self):
        return list(self.data.get("features") or [])

    @property
    def max_users(self):
        return int(self.data.get("max_users") or 0)

    @property
    def seconds_left(self):
        return self.expires_at - int(time.time())

    # ----------------------------------------------------------- وضعیت

    def is_expired(self):
        if self.unlicensed:
            return REQUIRE_LICENSE or self.managed
        if self.status in BLOCKING_STATUSES:
            return True
        return self.seconds_left <= 0

    def in_grace(self):
        """منقضی شده ولی هنوز مهلت داره."""
        if self.unlicensed or self.status in BLOCKING_STATUSES:
            return False
        grace = self.grace_until
        return self.seconds_left <= 0 and grace is not None and grace > time.time()

    def blocks_startup(self):
        """
        آیا ربات اصلاً نباید بالا بیاد؟ سه حالت:
          * نمونه‌ی مدیریت‌شده‌ای که فایل لایسنسش نیست/خرابه
          * لایسنس معلق یا لغوشده
          * لایسنس منقضی که مهلتش هم تموم شده
        """
        if self.unlicensed:
            return REQUIRE_LICENSE or self.managed
        if self.status in BLOCKING_STATUSES:
            return True
        if self.seconds_left > 0:
            return False
        grace = self.grace_until
        return not (grace and grace > time.time())

    def status_text(self):
        if self.unlicensed:
            detail = f" ({self.problem})" if self.problem else ""
            if REQUIRE_LICENSE or self.managed:
                return "لایسنس معتبر پیدا نشد" + detail
            return "بدون لایسنس (حالت کامل)"
        if self.status == "revoked":
            return "لایسنس لغو شده"
        if self.status == "suspended":
            return "لایسنس معلق است"
        if self.status == "paused":
            return "لایسنس متوقف است — عضو کانال رسمی نیستی"
        left = self.seconds_left
        if left <= 0:
            if self.in_grace():
                days = max(1, int((self.grace_until - time.time()) // 86400))
                return f"لایسنس منقضی شده — {days} روز مهلت تمدید"
            return "لایسنس منقضی شده"
        days = left // 86400
        if days > 0:
            return f"لایسنس فعال — {days} روز باقی‌مانده"
        return f"لایسنس فعال — {left // 3600} ساعت باقی‌مانده"

    # -------------------------------------------------------- دسترسی‌ها

    def effective_services(self):
        """
        سرویس‌هایی که این لایسنس واقعاً اجازه داره، یا None یعنی «همه».

        از سه منبع جمع می‌شه تا لایسنس‌های قدیمی هم خراب نشن: خودِ services،
        باز کردن features با کاتالوگ، و دستورهایی که یه فایلِ خیلی قدیمی
        مجاز می‌دونست. اگه کاتالوگ در دسترس نباشه فقط services خودِ فایل
        حساب می‌شه -- یعنی کمتر، نه بیشتر.
        """
        stored = self.data.get("services")
        features = self.data.get("features")
        commands = self.data.get("commands")
        if stored is None and features is None:
            return None
        allowed = set(stored or [])
        try:
            from licensing import catalog
            allowed.update(catalog.BASE_SERVICES)
            if features is not None:
                allowed.update(catalog.allowed_services(features))
            if commands:
                allowed.update(catalog.services_implied_by_commands(commands))
        except Exception:
            logging_setup.log_debug("catalog unavailable; using stored services only")
        return allowed

    def allows_service(self, name):
        if self.unlicensed:
            return not (REQUIRE_LICENSE or self.managed)
        if self.status in BLOCKING_STATUSES:
            return False
        if self.in_grace():
            return name in _base_services()
        if self.is_expired():
            return False
        allowed = self.effective_services()
        return allowed is None or name in allowed

    def allows_command(self, name):
        """
        دستورها قفل نمی‌شن. فقط وقتی کل ربات نباید اجرا بشه False است --
        که اون موقع اصلاً بالا نمی‌آد.
        """
        if self.unlicensed:
            return not (REQUIRE_LICENSE or self.managed)
        return True

def _read_identity(bot_dir):
    if not bot_dir:
        return {}
    try:
        with open(os.path.join(bot_dir, IDENTITY_FILE_NAME), "r", encoding="utf-8") as f:
            identity = json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return {}
    return identity if isinstance(identity, dict) else {}


def is_managed(bot_dir):
    """
    آیا این نمونه رو پلتفرم ساخته؟ از پرچم داخل identity.json خونده می‌شه.

    اگه identity.json خونده نشه، محافظه‌کارانه False برمی‌گردونه: یه ربات
    شخصیِ سالم نباید به‌خاطر یه خطای خواندن فایل بخوابه.
    """
    return bool(_read_identity(bot_dir).get(MANAGED_FLAG))


def load(bot_dir):
    """
    لایسنس این نمونه رو می‌خونه.

    فایل نبودن/خراب‌بودن دو معنی کاملاً متفاوت داره:
      * نمونه‌ی *غیرمدیریت‌شده* -> «بدون لایسنس»، کامل باز.
      * نمونه‌ی *مدیریت‌شده*     -> اجرا بلاک می‌شه.
    """
    if not bot_dir:
        return LicenseState(unlicensed=True)

    managed = is_managed(bot_dir)
    path = os.path.join(bot_dir, LICENSE_FILE_NAME)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        if managed:
            logging_setup.log_warning(
                "این نمونه مدیریت‌شده است ولی license.json ندارد؛ اجرا متوقف می‌شود.",
                context="license gate",
            )
        return LicenseState(unlicensed=True, managed=managed, problem="فایل موجود نیست")
    except (ValueError, OSError) as e:
        logging_setup.log_warning(
            f"license.json خوانده نشد ({e})."
            + (" نمونه مدیریت‌شده است، پس اجرا متوقف می‌شود."
               if managed else " ربات بدون محدودیت اجرا می‌شود."),
            context="license gate",
        )
        # problem از اینجا تا دستورِ lic توی تیم‌تاک به هر کاربری نشون داده
        # می‌شه (commands/lic.py) -- نباید متنِ خامِ OSError/JSONDecodeError
        # باشه (می‌تونه مسیر فایل سیستم رو لو بده)؛ متن کامل قبلاً بالا لاگ شد.
        return LicenseState(unlicensed=True, managed=managed,
                             problem=logging_setup.safe_error_text(e))

    if not isinstance(data, dict) or not data.get("key"):
        return LicenseState(unlicensed=True, managed=managed, problem="محتوای فایل ناقص است")

    return LicenseState(data=data, path=path, managed=managed)


def filter_services(state, services):
    """
    سرویس‌های مجاز رو برمی‌گردونه. ترتیب اصلی حفظ می‌شه تا شماره‌گذاری w
    برای کاربر ثابت بمونه.
    """
    if state.unlicensed and not (REQUIRE_LICENSE or state.managed):
        return services
    return {name: svc for name, svc in services.items() if state.allows_service(name)}


def bot_allows_service(bot, service_name):
    """آیا لایسنسِ این ربات اجازه‌ی سرویس رو می‌ده؟ (بدون لایسنس/state: بله)."""
    state = getattr(bot, "license", None)
    if state is None:
        return True
    return state.allows_service(service_name)


def filter_commands(state, commands):
    """
    commands: {name: {...}} همون شکلی که CommandManager می‌سازه.
    """
    # لایسنس دستورها رو قفل نمی‌کنه؛ همه می‌مونن. (برای سازگاری با
    # صداکننده‌های قدیمی نگه داشته شده.)
    return dict(commands)


def removed_commands(state, commands):
    """هیچ دستوری به‌خاطر لایسنس حذف نمی‌شه."""
    return []


def _base_services():
    try:
        from licensing import catalog
        return list(catalog.BASE_SERVICES)
    except Exception:
        return ["youtube"]


def service_for_command(name):
    """
    سرویسی که یه دستور لازم داره، یا None. اگه کاتالوگ در دسترس نباشه
    None -- ولی اون موقع خودِ سرویس‌ها هم فقط از فایل لایسنس میان.
    """
    try:
        from licensing import catalog
        return catalog.service_for_command(name)
    except Exception:
        return None


def refusal_text(state, service):
    """پیامِ «این سرویس رو نداری»، با دلیلِ واقعی."""
    from core import i18n
    if state is not None and (state.is_expired() or state.status in BLOCKING_STATUSES):
        return i18n.t("license_expired_no_services")
    try:
        from licensing import catalog
        title = catalog.service_title(service)
    except Exception:
        title = service
    return i18n.t("service_not_licensed", service=title)

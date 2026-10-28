"""
تنظیمات پلتفرم: توکن ربات، ادمین‌ها، اطلاعات پرداخت، مسیرها.

## از کجا خونده می‌شه (به ترتیب اولویت)

  ۱. متغیر محیطی (بهترین جا برای توکن‌ها روی سرور)
  ۲. data/licensing/config.json
  ۳. جدول settings دیتابیس (چیزهایی که از داخل خود ربات تلگرام عوض می‌شن،
     مثل شماره کارت یا نرخ دستی دلار)
  ۴. پیش‌فرض

توکن ربات و آیدی ادمین عمداً *فقط* از env و فایل کانفیگ خونده می‌شن، نه از
دیتابیس: اگه از دیتابیس خونده می‌شدن، یه باگ یا دسترسی نوشتن به دیتابیس
می‌تونست ادمین عوض کنه.
"""

import json
import os
import re

from core.paths import get_base_dir

CONFIG_DIR = os.path.join(get_base_dir(), "data", "licensing")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
RECEIPTS_DIR = os.path.join(CONFIG_DIR, "receipts")
KEYS_DIR = os.path.join(CONFIG_DIR, "keys")

_DEFAULTS = {
    # ربات فروش/لایسنس (اجباری)
    "sales_bot_token": "",
    # آیدی عددی تلگرام ادمین‌ها. اولی «ادمین اصلی» حساب می‌شه.
    "admin_ids": [],
    # اطلاعات کارت‌به‌کارت که به کاربر نشون داده می‌شه
    "card_number": "",
    "card_holder": "",
    "card_bank": "",
    # نام کاربری ادمین برای «ارتباط با پشتیبانی»
    "support_username": "",
    # آدرس عمومی سرور لایسنس، برای نسخه‌ی self-host
    "license_api_base": "",
    "license_api_port": 8787,
    "license_api_bind": "127.0.0.1",
    # پروکسی برای وصل‌شدن به api.telegram.org، جایی که تلگرام فیلتره.
    #
    #   "proxy_url": "http://127.0.0.1:8080"
    #   "proxy_url": "socks5://127.0.0.1:1080"   (نیاز: pip install "python-telegram-bot[socks]")
    #
    # خالی یعنی «چیزی دست‌کاری نکن»: در این حالت httpx خودش پروکسیِ
    # محیط رو برمی‌داره (HTTPS_PROXY، و روی ویندوز پروکسی سیستم). روی
    # سرور لینوکسی معمولاً پروکسی سیستمی وجود نداره، پس اونجا این کلید
    # (یا LICENSING_PROXY_URL) تنها راهه.
    "proxy_url": "",
    # هر long-poll چند ثانیه باز بمونه.
    #
    # پشت پروکسی‌هایی که اتصال بی‌کار رو می‌بندن، همین‌جا خودش رو نشون
    # می‌ده: «Error while getting Updates: Server disconnected without
    # sending a response». ربات نمی‌میره (PTB دوباره تلاش می‌کنه) ولی
    # هر بار چند ثانیه از دست می‌ره. عدد کوچیک‌تر = اتصالِ کمتر بی‌کار.
    "telegram_poll_timeout": 10,
    # تایم‌اوت شبکه. پشت پروکسی، باز شدن اتصال کند‌تره و پیش‌فرض‌های
    # PTB (۵ ثانیه) خیلی زود تسلیم می‌شن.
    "telegram_timeout": 30,
    # چند دقیقه بعد از ثبت سفارش، اگه رسید نیاد سفارش منقضی می‌شه
    "order_timeout_minutes": 180,
    # چند روز بعد از انقضا، لاین صدا و دیتا پاک می‌شن (مهلت تمدید)
    "grace_days": 3,
    # ساعت چک شبانه (به وقت سرور)
    "nightly_check_hour": 0,
    "nightly_check_minute": 5,
    # چند روز قبل از انقضا به کاربر یادآوری بشه
    "reminder_days": [7, 3, 1],
    # گزارش روزانه‌ی تلگرام برای ادمین‌ها (وضعیت ربات‌ها، خطاها، انقضاها،
    # سفارش‌ها و پرداخت تتر). ساعتش به وقت محلی سرور، ۰ تا ۲۳.
    "daily_report_enabled": True,
    "daily_report_hour": 9,
    # سقف حجم عکس رسید (بایت)
    "max_receipt_bytes": 8 * 1024 * 1024,
    # حداقل امتیاز بررسی خودکار برای این‌که سفارش به ادمین برسه.
    # پایین‌تر از این «مشکوک» علامت می‌خوره -- ولی در هر صورت تأیید نهایی
    # دست ادمینه.
    "receipt_min_score": 0.5,
    # اجرای ربات‌های مشتری‌ها روی همین سرور
    "hosting_enabled": True,
    # فعال‌بودن نسخه‌ی self-host (توکن امضاشده برای کلاینت).
    #
    # پیش‌فرض خاموش: مدل این پروژه اینه که همه‌ی ربات‌ها روی سرور خودمون
    # اجرا بشن و هیچ فایلی دست مشتری نباشه. با خاموش‌بودنش، API لایسنس
    # اصلاً بالا نمی‌آد -- یعنی یه سطح حمله‌ی کامل حذف می‌شه، نه فقط
    # استفاده‌نشده می‌مونه.
    #
    # کدش سر جاش هست؛ اگه روزی خواستی نسخه‌ی نصبی بفروشی، همین رو true کن.
    "selfhost_enabled": False,
    # مدت اعتبار توکن آفلاین self-host (روز). کوتاه‌تر = امن‌تر، ولی کلاینت
    # باید بیشتر آنلاین بشه.
    "selfhost_token_days": 7,
    # --- لایسنس ابری (Cloudflare KV) ---
    #
    # با این سه‌تا، ربات فروش می‌تونه لایسنس اجاره‌ای رو مستقیم صادر و
    # لغو کنه. بدونشون همه‌چیز کار می‌کنه، فقط صدور دستی می‌مونه
    # (manage.py rental + wrangler kv put).
    #
    # توکن رو با دسترسی «Workers KV Storage: Edit» بساز، نه توکن سراسری:
    # dash.cloudflare.com -> My Profile -> API Tokens -> Create Token
    "cloudflare_account_id": "",
    "cloudflare_kv_namespace": "",
    "cloudflare_api_token": "",
    # --- پرداخت با تتر (USDT) ---
    #
    # ربات فقط *آدرس عمومیِ* کیف‌پولِ تو رو تماشا می‌کنه (فقط‌خواندنی) و
    # هیچ‌وقت کلید خصوصی نداره. هر سفارش یه مبلغِ یکتا می‌گیره (قیمت + چند
    # صدم سنت) و با همون مبلغ تطبیق داده می‌شه. جزئیات: docs/CRYPTO_PAYMENTS.md
    #
    #   enabled            پیش‌فرض خاموش؛ بدون آدرس هم دکمه‌ی پرداخت نمی‌آد
    #   network            "trc20" (USDT روی ترون، پیش‌فرض) یا "bep20" (BSC)
    #   address            آدرس دریافتِ خودت
    #   trongrid_api_key   اختیاری؛ سقفِ درخواستِ TronGrid رو بالا می‌بره
    #   explorer_api_key   فقط bep20؛ کلید Etherscan/BscScan (رایگان)
    #   expiry_minutes     مهلت پرداخت بعد از ساخت فاکتور
    #   min_confirmations  trc20: صفر = همون لحظه، ۱ و بیشتر = فقط تراکنشِ
    #                      قطعی‌شده؛ bep20: تعداد تأییدِ بلاک
    "crypto": {
        "enabled": False,
        "network": "trc20",
        "address": "",
        "trongrid_api_key": "",
        "explorer_api_key": "",
        "expiry_minutes": 30,
        "min_confirmations": 1,
    },
}

_cache = None

# اگه فایل کانفیگ خراب باشه، متن خطای JSON اینجا می‌مونه تا
# missing_required() بتونه *همون* رو گزارش کنه.
_file_error = None


def _read_file():
    """
    کانفیگ از روی دیسک. فایل خراب، کل کانفیگ رو خالی می‌کنه -- ولی ساکت
    نه: بدون ثبت خطا، ادمینی که توکن رو نوشته بود پیغام «توکن تنظیم نشده»
    می‌گرفت و دنبال مشکل توی جای اشتباه می‌گشت.
    """
    global _file_error
    _file_error = None
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            _file_error = "the file must contain a JSON object ({...})"
            return {}
        return data
    except FileNotFoundError:
        return {}
    except ValueError as e:
        _file_error = str(e)
        print(f"[Config] {CONFIG_FILE} is malformed and was ignored: {e}")
        return {}
    except OSError as e:
        _file_error = str(e)
        print(f"[Config] {CONFIG_FILE} could not be read: {e}")
        return {}


_ENV_MAP = {
    "sales_bot_token": "LICENSING_BOT_TOKEN",
    "card_number": "LICENSING_CARD_NUMBER",
    "card_holder": "LICENSING_CARD_HOLDER",
    "card_bank": "LICENSING_CARD_BANK",
    "support_username": "LICENSING_SUPPORT_USERNAME",
    "license_api_base": "LICENSING_API_BASE",
    "proxy_url": "LICENSING_PROXY_URL",
    "cloudflare_account_id": "CF_ACCOUNT_ID",
    "cloudflare_kv_namespace": "CF_KV_NAMESPACE",
    "cloudflare_api_token": "CF_API_TOKEN",
}

# کلیدهای زیرمجموعه‌ی "crypto" که می‌شه با متغیر محیطی هم داد (کلید API
# و آدرس رو بهتره توی فایل کانفیگِ قابل‌اشتراک ننویسی).
_CRYPTO_ENV_MAP = {
    "address": "LICENSING_CRYPTO_ADDRESS",
    "trongrid_api_key": "LICENSING_TRONGRID_API_KEY",
    "explorer_api_key": "LICENSING_EXPLORER_API_KEY",
}


def _coerce_admin_ids(value):
    """
    هرچی ادمین نوشته -> لیست آیدی عددی.

    عمداً سخت‌گیر نیست: @userinfobot آیدی رو به شکل «Id: 123456789» نشون
    می‌ده و همون کپی می‌شه توی کانفیگ. عدد داخلش بی‌ابهامه، پس درش
    می‌آریم به‌جای اینکه ربات با ValueError بخوابه یا بی‌صدا ادمین رو
    بندازه دور.
    """
    ids = []
    for item in (value or []):
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            ids.append(item)
            continue
        found = re.search(r"-?\d+", str(item))
        if found:
            ids.append(int(found.group()))
    return ids


def load(force=False):
    global _cache
    if _cache is not None and not force:
        return _cache

    config = dict(_DEFAULTS)
    config.update(_read_file())

    for key, env_name in _ENV_MAP.items():
        value = os.environ.get(env_name)
        if value:
            config[key] = value

    admin_env = os.environ.get("LICENSING_ADMIN_IDS")
    if admin_env:
        config["admin_ids"] = _coerce_admin_ids(admin_env.split(","))

    config["admin_ids"] = _coerce_admin_ids(config.get("admin_ids"))

    _cache = config
    return config


def reload():
    return load(force=True)


def get(key, default=None):
    """
    مقدار یه کلید. کلیدِ نقطه‌دار (مثل "crypto.enabled") داخل بخشِ تودرتو
    می‌ره؛ برای بقیه همون جستجوی ساده.
    """
    value = load()
    for part in str(key).split("."):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def crypto_settings():
    """
    تنظیمات پرداخت با تتر، نرمال‌شده: همیشه همه‌ی کلیدها هستن و نوعشون
    درسته، حتی اگه کاربر فقط نصفشون رو توی فایل نوشته باشه یا مقدار بد
    (مثلاً "abc" برای expiry_minutes) گذاشته باشه.
    """
    merged = dict(_DEFAULTS["crypto"])
    section = load().get("crypto")
    if isinstance(section, dict):
        merged.update({k: v for k, v in section.items() if k in merged})
    for key, env_name in _CRYPTO_ENV_MAP.items():
        value = os.environ.get(env_name)
        if value and value.strip():
            merged[key] = value.strip()

    enabled = merged["enabled"]
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() in ("1", "true", "yes", "on")
    merged["enabled"] = bool(enabled)
    merged["network"] = str(merged["network"] or "trc20").strip().lower()
    for key in ("address", "trongrid_api_key", "explorer_api_key"):
        merged[key] = str(merged[key] or "").strip()
    for key, floor in (("expiry_minutes", 5), ("min_confirmations", 0)):
        try:
            merged[key] = max(floor, int(merged[key]))
        except (TypeError, ValueError):
            merged[key] = _DEFAULTS["crypto"][key]
    return merged


def proxy_url():
    """
    پروکسیِ تلگرام، یا None.

    None یعنی «تنظیمات پیش‌فرض httpx»، نه «بدون پروکسی» -- httpx در این
    حالت هنوز HTTPS_PROXY و پروکسی سیستم رو می‌بینه. پس این تابع فقط
    وقتی مقدار می‌ده که ادمین صریحاً پروکسی نوشته باشه.
    """
    return (load().get("proxy_url") or "").strip() or None


def poll_timeout():
    try:
        return max(1, int(load().get("telegram_poll_timeout", 10)))
    except (TypeError, ValueError):
        return 10


def network_timeout():
    try:
        return max(5, int(load().get("telegram_timeout", 30)))
    except (TypeError, ValueError):
        return 30


def admin_ids():
    return list(load().get("admin_ids") or [])


def main_admin_id():
    ids = admin_ids()
    return ids[0] if ids else None


def is_admin(telegram_id):
    return int(telegram_id) in admin_ids()


def is_protected_licence(key):
    """
    آیا این کلید دست مشتریه و نباید ریست/rebind بشه؟

    لیست توی کانفیگ محلیه (`protected_licences`)، نه توی کد: کلید لایسنسِ
    یه مشتری نباید توی تاریخچه‌ی git بمونه. هم `manage.py` (CLI) هم پنل
    ادمینِ تلگرام همینو صدا می‌زنن، تا لیستِ محافظت‌شده‌ها یه‌جا بمونه.
    """
    protected = get("protected_licences") or []
    return str(key or "").strip().upper() in {str(k).strip().upper() for k in protected}


def payment_info(db=None):
    """
    اطلاعات کارت. از دیتابیس خونده می‌شه اگه ادمین از داخل ربات عوضش کرده
    باشه، وگرنه از فایل کانفیگ.
    """
    config = load()
    info = {
        "card_number": config.get("card_number", ""),
        "card_holder": config.get("card_holder", ""),
        "card_bank": config.get("card_bank", ""),
    }
    if db is not None:
        for key in info:
            override = db.get_setting(f"payment_{key}")
            if override:
                info[key] = override
    return info


def write_template():
    """
    اگه فایل کانفیگ نیست، یه نمونه‌ی خالی می‌سازه تا ادمین فقط پرش کنه.
    مقدارهای حساس خالی گذاشته می‌شن، نه پیش‌فرضِ الکی.
    """
    if os.path.isfile(CONFIG_FILE):
        return False
    os.makedirs(CONFIG_DIR, exist_ok=True)
    template = dict(_DEFAULTS)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(template, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass
    return True


# ------------------------------------------------------------ نوشتن کانفیگ
#
# ویزارد (configure.py) و `manage.py cf-token` هر دو از همین‌جا می‌نویسن، تا
# «فایل کانفیگ چطور نوشته می‌شه» یه جا بمونه: اتمیک، chmod 600، و -- مهم‌تر از
# همه -- فایلِ خراب هیچ‌وقت بی‌صدا بازنویسی نمی‌شه.

class ConfigWriteError(Exception):
    """فایل کانفیگ رو نمی‌شه با خیال راحت نوشت (مثلاً JSON خراب داره)."""


#: کلیدهایی که راز حساب می‌شن و هیچ‌وقت کامل چاپ نمی‌شن. کلیدهای جدید
#: (مثل crypto.*) با اسمشون تشخیص داده می‌شن -- ببین is_secret_key.
SECRET_KEYS = frozenset({"sales_bot_token", "cloudflare_api_token"})
_SECRET_HINTS = ("token", "secret", "password", "passphrase", "private", "seed",
                 "mnemonic", "api_key", "apikey")

_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def known_keys(prefix=""):
    """
    همه‌ی کلیدهایی که این ماژول می‌شناسه، تخت‌شده (``a.b`` برای کلیدِ
    تودرتو). با prefix فقط همون گروه: known_keys("crypto.").
    """
    names = []
    for key, value in _DEFAULTS.items():
        if isinstance(value, dict) and value:
            names.extend(f"{key}.{sub}" for sub in value)
        else:
            names.append(key)
    return sorted(name for name in names if name.startswith(prefix))


def knows(key):
    return key in known_keys()


def default_for(key):
    """مقدار پیش‌فرضِ یه کلید (پشتیبانی از ``a.b``)؛ None اگه ناشناسه."""
    if key in _DEFAULTS:
        return _DEFAULTS[key]
    node = _DEFAULTS
    for part in str(key).split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def is_secret_key(key):
    if key in SECRET_KEYS:
        return True
    last = str(key).rsplit(".", 1)[-1].lower()
    return any(hint in last for hint in _SECRET_HINTS)


def mask_secret(value):
    """
    نسخه‌ی قابل‌نمایشِ یه راز: دو سه حرف اولِ مقدار، بعد ستاره، بعد دو حرفِ
    آخر -- و برای مقدار کوتاه فقط ستاره. طولِ ستاره‌ها ثابته، پس طولِ
    واقعیِ راز هم لو نمی‌ره.
    """
    text = str(value or "")
    if not text:
        return ""
    if len(text) < 16:
        return "*" * 8
    return f"{text[:4]}{'*' * 8}{text[-2:]}"


def mask_value(key, value):
    """مقدار برای نمایش: راز -> ماسک، پروکسی -> بدون user:pass، بقیه خودشون."""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    if key == "proxy_url":
        from core import proxy_state
        return proxy_state.mask(value) or ""
    if is_secret_key(key):
        return mask_secret(value)
    return "" if value is None else str(value)


def parse_admin_ids(text):
    """
    «Id: 123456789, 987654321» -> [123456789, 987654321]. همون نگاهِ سهل‌گیرِ
    _coerce_admin_ids، ولی روی یه متنِ آزاد: هر عددی که توش باشه یه آیدیه.
    """
    return _coerce_admin_ids(re.findall(r"-?\d+", str(text or "").translate(_DIGIT_MAP)))


def normalize_card_number(text):
    """
    شماره کارت را به ``6037 9975 1234 5678`` (چهارتا‌چهارتا) تبدیل می‌کنه.
    ارقام فارسی/عربی هم قبوله. None یعنی «به شماره کارت نمی‌خوره»
    (۱۲ تا ۱۹ رقم).
    """
    digits = re.sub(r"[\s\-_.]", "", str(text or "").translate(_DIGIT_MAP))
    if not digits.isdigit() or not 12 <= len(digits) <= 19:
        return None
    return " ".join(digits[i:i + 4] for i in range(0, len(digits), 4))


def file_values():
    """
    چیزی که *توی فایل* نوشته شده (بدون env و پیش‌فرض). ویزارد ازش می‌فهمه
    چی رو قبلاً ادمین گذاشته، بدون این‌که مقدارِ env رو بریزه توی فایل.
    """
    return dict(_read_file())


def file_error():
    """متنِ خطای آخرین خوندنِ فایل (JSON خراب)، یا None."""
    return _file_error


def env_name(key):
    """اسم متغیر محیطی که این کلید رو override می‌کنه، یا None."""
    if key == "admin_ids":
        return "LICENSING_ADMIN_IDS"
    if str(key).startswith("crypto."):
        return _CRYPTO_ENV_MAP.get(str(key)[len("crypto."):])
    return _ENV_MAP.get(key)


def env_overrides():
    """{کلید: اسم متغیر محیطی} برای کلیدهایی که الان env جای فایل رو گرفته."""
    found = {k: name for k, name in _ENV_MAP.items() if os.environ.get(name)}
    if os.environ.get("LICENSING_ADMIN_IDS"):
        found["admin_ids"] = "LICENSING_ADMIN_IDS"
    for sub, name in _CRYPTO_ENV_MAP.items():
        if (os.environ.get(name) or "").strip():
            found["crypto." + sub] = name
    return found


def _set_path(data, key, value):
    # کلیدی که *عیناً* با نقطه توی پیش‌فرض‌ها هست (مثل "crypto.enabled")
    # تخت نوشته می‌شه، چون load() هم تخت می‌خونه؛ بقیه تودرتو.
    if key in _DEFAULTS or "." not in str(key):
        data[key] = value
        return
    parts = str(key).split(".")
    node = data
    for part in parts[:-1]:
        if not isinstance(node.get(part), dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = value


def get_path(data, key, default=None):
    if isinstance(data, dict) and key in data:
        return data[key]
    node = data
    for part in str(key).split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def save_values(updates):
    """
    ``updates`` (کلید -> مقدار، کلیدِ تودرتو با ``a.b``) رو توی فایل
    کانفیگ ادغام می‌کنه و حافظه رو تازه می‌کنه. بقیه‌ی کلیدهای فایل
    دست‌نخورده می‌مونن. اگه فایل خراب باشه ConfigWriteError می‌ده و
    چیزی نمی‌نویسه -- بازنویسیِ فایلِ خراب، هرچی ادمین توش داشته رو
    برای همیشه می‌بُرد.
    """
    data = _read_file()
    if _file_error:
        raise ConfigWriteError(
            f"{CONFIG_FILE} is not valid JSON ({_file_error}); fix or delete it first")
    for key, value in updates.items():
        _set_path(data, key, value)

    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_FILE)
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass
    reload()
    return CONFIG_FILE


def missing_required_keys():
    """
    کلیدهای اجباریِ پرنشده، هم‌ترازِ missing_required() (همون شرط‌ها، فقط
    به‌جای متنِ خطا اسمِ کلید) تا ویزارد بدونِ کپیِ لیست بدونه چی رو بپرسه.
    """
    if _file_error:
        return []
    config = load()
    keys = [key for key in ("sales_bot_token", "admin_ids") if not config.get(key)]
    # شماره کارت فقط وقتی اجباریه که پرداخت با تتر هم آماده نباشه
    # (همون شرطِ missing_required).
    if not config.get("card_number") and not _crypto_ready():
        keys.append("card_number")
    return keys


def missing_required():
    """چیزهایی که بدونشون ربات فروش نمی‌تونه کار کنه."""
    config = load()
    problems = []

    # فایل خراب = *یه* مشکل، نه سه تا. اگه اینجا لیست «توکن نیست، ادمین
    # نیست، کارت نیست» هم چاپ می‌شد، ادمین می‌رفت سراغ مقدارهایی که
    # درست نوشته بودشون، درحالی‌که فقط یه ویرگول یا کوتیشن کم بود.
    if _file_error:
        return [
            f"{CONFIG_FILE} is not valid JSON, so every setting in it was ignored: "
            f"{_file_error}. Fix that line (a missing comma or quote is the usual "
            "cause -- ids must look like \"admin_ids\": [123456789]), or delete the "
            "file and run: python license_server.py --init"
        ]

    if not config.get("sales_bot_token"):
        problems.append(
            "The sales bot token is not set. Either set LICENSING_BOT_TOKEN, or "
            f"write sales_bot_token in {CONFIG_FILE}."
        )
    if not config.get("admin_ids"):
        problems.append(
            "No admin is configured. Put your numeric Telegram id in admin_ids "
            "(@userinfobot will tell you what it is)."
        )
    if not config.get("card_number") and not _crypto_ready():
        problems.append("No card number is configured; without one an invoice cannot be paid "
                        "(or enable crypto payments, see docs/CRYPTO_PAYMENTS.md).")
    return problems


def _crypto_ready():
    """آیا پرداخت با تتر روشنه و آدرسش معتبره؟ (فروشنده‌ی فقط‌کریپتو کارت لازم نداره)"""
    from licensing import crypto_pay
    return crypto_pay.available()

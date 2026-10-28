"""
پخش زنده‌ی کانال‌های تلویزیون/رادیوی اینترنتی (IPTV) از پلی‌لیست M3U/M3U8.

## مدل

کانال‌ها از چند «منبع» (لینک‌های M3U/M3U8 عمومی یا اختصاصی) خونده و پارس
می‌شن؛ هر خط از پلی‌لیست به یه dict به شکل زیر تبدیل می‌شه:

    {"name": "BBC Persian", "url": "https://.../stream.m3u8",
     "group": "News", "user_agent": None, "referrer": None, "source": "..."}

نتیجه‌ی همه‌ی منبع‌ها با هم جمع و **در حافظه** کش می‌شه (با TTL از
تنظیمات) -- هیچ‌وقت روی دیسک نوشته نمی‌شه، چون این آدرس‌ها خودشون معمولاً
مثل خود لینکِ استریم حساسن.

## حالت تلویزیون (TV mode)

دقیقاً هم‌خانواده‌ی حالت مستند (core/documentary.py)، با یه فرق: مستند
فرمول داره (شماره -> آدرس)، ولی IPTV «لیستِ آخر»ی داره که با `tv <متن>`
یا `tv list` نشون داده می‌شه. بعد از یه لیست *یا* یه پخش:

  * یه عدد خام (یا `tv <عدد>`) یعنی «همون شماره از همون لیست رو پخش کن».
  * `n`/`b` یعنی کانال بعدی/قبلی *توی همون لیست*، فقط وقتی همین الان یه
    کانال از IPTV در حال پخشه.

پخش هر چیز دیگه‌ای (سرچ یوتیوب، لینک مستقیم، مستند) این حالت رو کامل
می‌بنده -- هم لیست پاک می‌شه هم هدرهای HTTP اختصاصیِ کانال قبلی، وگرنه
مثلاً user-agent مخصوص یه IPTV به پخش بعدی (که ربطی به IPTV نداره) سرایت
می‌کرد.

## لایسنس

سرویس `iptv` مثل `documentary` یه «قابلیت» است (licensing/catalog.py:
CAPABILITY_SERVICES). دیسپچرِ اصلی (bot.py) قبل از اجرای دستورهای `tv`/
`tvs` این رو چک می‌کنه، ولی مسیر «عدد خام» دستور جدا نیست و از همون چک رد
نمی‌شه -- برای همین `play()` خودش هم `licensed()` رو چک می‌کنه (دقیقاً
همون دلیلی که core/documentary.py توضیح داده).

## حریم خصوصی

آدرس واقعیِ استریم/پلی‌لیست هیچ‌وقت توی هیچ پیامی (چت، وضعیت، خطا) چاپ
نمی‌شه، چون این آدرس‌ها معمولاً یوزر/پسورد اشتراک IPTV رو توی خودشون
دارن. جایی که باید منبع نشون داده بشه (دستور tvs) فقط اسم و میزبانِ
نیمه‌پنهان‌شده (mask_host) دیده می‌شه.

## تنظیمات (shared_config.json -> "iptv")

    "iptv": {
        "sources": [{"name": "...", "url": "https://.../list.m3u8"}],
        "cache_minutes": 60,
        "max_channels": 5000,
        "page_size": 15,
    }

پیش‌فرض یه منبع عمومی (لیست ایرانِ iptv-org) داره تا بدون هیچ تنظیمی هم
کار کنه؛ مقدارهای پیش‌فرض توی core/config_defaults.py هم تکرار شدن تا
کانفیگ‌های قدیمی موقع بالا اومدن خودکار این کلید رو بگیرن.
"""

import re
import threading
import time
import urllib.parse

from core import command_helpers
from core import config_defaults
from core import i18n
from core import license_gate
from core import logging_setup
from core import net

SERVICE_NAME = "iptv"

#: منبع پیش‌فرض: لیست عمومیِ ایرانِ iptv-org، تا بدون هیچ تنظیمی هم چیزی
#: برای پخش وجود داشته باشه (خودِ مقدارها توی core/config_defaults.py است).
DEFAULTS = config_defaults.IPTV_DEFAULTS
DEFAULT_SOURCES = DEFAULTS["sources"]

# مهلت هر تلاش شبکه (پروکسی یا مستقیم) برای گرفتن یه پلی‌لیست.
_FETCH_TIMEOUT = 12
_FETCH_UA = "Mozilla/5.0 (compatible; iptv-fetcher)"

# key="value"  -- برای پارس attribute های #EXTINF (tvg-id، group-title، ...).
_ATTR_RE = re.compile(r'([A-Za-z0-9_-]+)\s*=\s*"([^"]*)"')

_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


class IPTVError(Exception):
    """خطای قابل‌نمایش به کاربر (شماره نامعتبر، لیست خالی، منبع در دسترس نیست)."""


# ---------------------------------------------------------------- تنظیمات

def settings(bot):
    """تنظیمات IPTV، با پر کردن جاهای خالی از پیش‌فرض (شبیه documentary.settings)."""
    return config_defaults.feature_settings(bot, "iptv", DEFAULTS)


def sources(bot):
    """لیستِ منبع‌ها، هر کدوم یه dict مستقل (تغییرش روی کانفیگ اصلی اثر نداره)."""
    raw = settings(bot).get("sources")
    if not isinstance(raw, list):
        return []
    return [dict(s) for s in raw if isinstance(s, dict) and s.get("url")]


def cache_minutes(bot):
    return config_defaults.positive_int_setting(settings(bot), "cache_minutes", DEFAULTS)


def max_channels(bot):
    return config_defaults.positive_int_setting(settings(bot), "max_channels", DEFAULTS)


def page_size(bot):
    return config_defaults.positive_int_setting(settings(bot), "page_size", DEFAULTS)


def licensed(bot):
    """
    آیا این ربات اجازه‌ی پخش IPTV داره؟ توضیح کامل بالای فایل (چرا اینجا
    هم چک می‌شه، نه فقط سطح دستور).
    """
    return license_gate.bot_allows_service(bot, SERVICE_NAME)


def looks_like_source_url(url):
    return command_helpers.is_link(url)


# ------------------------------------------------------------- حریم خصوصی

def mask_host(url):
    """
    فقط میزبانِ لینک رو *نیمه‌پنهان* برمی‌گردونه (نه مسیر، نه کوئری، نه
    یوزر/پسورد) -- مثلاً iptv-org.github.io -> ip*************io. برای
    نشون‌دادنِ «کدوم منبع» به ادمین بدون لو رفتن آدرس کامل.
    """
    host = ""
    try:
        candidate = url if "://" in (url or "") else "//" + (url or "")
        host = urllib.parse.urlparse(candidate).hostname or ""
    except Exception:
        host = ""
    if not host:
        return "***"
    if len(host) <= 4:
        return host[0] + "*" * (len(host) - 1)
    return host[:2] + "*" * (len(host) - 4) + host[-2:]


# --------------------------------------------------------------- دریافت

def _fetch_text(url, timeout=_FETCH_TIMEOUT):
    """
    متنِ یه پلی‌لیست، از مسیر مشترکِ core/net.py (اول پروکسیِ ربات، بعد
    مستقیم؛ socks5 هم کار می‌کنه). خطای خام دوباره raise می‌شه و فراخوان --
    fetch_channels -- فقط لاگش می‌کنه، هیچ‌وقت به کاربر نشونش نمی‌ده.
    """
    _, text = net.fetch_text(url, headers={"User-Agent": _FETCH_UA}, timeout=timeout,
                             label="iptv", encoding="utf-8-sig")
    return text


# ------------------------------------------------------------- پارس M3U

def _parse_extinf(content):
    """
    content: چیزی که بعد از '#EXTINF:' میاد، مثلاً:
        '-1 tvg-id="x" group-title="News, Local",Channel One, Extra'

    برمی‌گردونه (attrs, title). اول همه‌ی attribute های key="value" با
    regex در میان (مقدارشون حتی اگه کاما داشته باشه مشکلی نیست، چون کل
    match از خط حذف می‌شه)، بعد اولین کاماي باقی‌مونده مرزِ مدت‌زمان/عنوانه
    -- تا اسمِ کانالی که خودش کاما داره خراب نشه.
    """
    attrs = {m.group(1).lower(): m.group(2) for m in _ATTR_RE.finditer(content)}
    stripped = _ATTR_RE.sub("", content)
    comma_idx = stripped.find(",")
    if comma_idx == -1:
        return attrs, ""
    return attrs, stripped[comma_idx + 1:].strip()


def _name_from_url(url):
    try:
        path = urllib.parse.urlparse(url).path
        base = path.rsplit("/", 1)[-1]
        return urllib.parse.unquote(base) or url
    except Exception:
        return url


def parse_m3u(text, source_name=None):
    """
    متنِ یه پلی‌لیست M3U/M3U8 رو به لیستی از کانال‌ها (dict) تبدیل می‌کنه.

    پشتیبانی‌شده: #EXTM3U، #EXTINF (با attribute های tvg-id/tvg-name/
    group-title و عنوانِ بعد از کاما)، #EXTGRP، #EXTVLCOPT:http-user-agent=
    و http-referrer=، خط خالی، و آیتم‌های بدون EXTINF (اسم از خودِ آدرس
    ساخته می‌شه). BOM/CRLF قبل از این تابع هندل می‌شن (_fetch_text با
    utf-8-sig می‌خونه؛ splitlines() خودش \\r\\n را هم می‌فهمد).

    خطای فرمت کلِ عملیات رو خراب نمی‌کنه -- بدترین حالت یه لیستِ ناقص‌تره.
    """
    channels = []
    pending_name = None
    pending_group = None
    pending_user_agent = None
    pending_referrer = None

    for raw_line in (text or "").splitlines():
        line = raw_line.strip().lstrip("\ufeff")
        if not line:
            continue
        upper = line.upper()

        if upper.startswith("#EXTM3U"):
            continue

        if upper.startswith("#EXTINF"):
            content = line.split(":", 1)[1] if ":" in line else ""
            attrs, title = _parse_extinf(content)
            pending_name = title or attrs.get("tvg-name")
            pending_group = attrs.get("group-title") or pending_group
            continue

        if upper.startswith("#EXTGRP"):
            if ":" in line:
                pending_group = line.split(":", 1)[1].strip() or pending_group
            continue

        if upper.startswith("#EXTVLCOPT"):
            opt = line.split(":", 1)[1] if ":" in line else ""
            key, _, value = opt.partition("=")
            key = key.strip().lower()
            value = value.strip()
            if value:
                if key == "http-user-agent":
                    pending_user_agent = value
                elif key in ("http-referrer", "http-referer"):
                    pending_referrer = value
            continue

        if line.startswith("#"):
            # تگ ناشناخته (مثلاً #PLAYLIST یا اضافه‌های آینده) -- نادیده.
            continue

        # این خط دیگه خودِ URL کانال است.
        name = (pending_name or "").strip() or _name_from_url(line)
        channels.append({
            "name": name,
            "url": line,
            "group": pending_group,
            "user_agent": pending_user_agent,
            "referrer": pending_referrer,
            "source": source_name,
        })
        pending_name = None
        pending_group = None
        pending_user_agent = None
        pending_referrer = None

    return channels


# ----------------------------------------------------------------- کش

_CACHE = {}
_CACHE_LOCK = threading.Lock()


def _cache_key(bot):
    return (id(bot), tuple((s.get("name"), s.get("url")) for s in sources(bot)))


def invalidate_cache(bot=None):
    """کش رو خالی می‌کنه -- بعد از تغییر منبع‌ها (tvs add/del) لازمه."""
    with _CACHE_LOCK:
        if bot is None:
            _CACHE.clear()
            return
        for key in [k for k in _CACHE if k[0] == id(bot)]:
            del _CACHE[key]


def fetch_channels(bot, force=False):
    """
    کانال‌های همه‌ی منبع‌ها رو با هم برمی‌گردونه (کش‌شده با TTL از
    cache_minutes). خطای یه منبع بقیه رو خراب نمی‌کنه؛ فقط اگه *همه‌ی*
    منبع‌ها fail کردن (یا اصلاً منبعی نیست) IPTVError می‌ده.
    """
    key = _cache_key(bot)
    ttl = cache_minutes(bot) * 60
    now = time.time()
    if not force:
        with _CACHE_LOCK:
            cached = _CACHE.get(key)
            if cached is not None and (now - cached["fetched_at"]) < ttl:
                return list(cached["channels"])

    srcs = sources(bot)
    if not srcs:
        raise IPTVError(i18n.t("iptv_unavailable"))

    limit = max_channels(bot)
    channels = []
    failed = []
    for src in srcs:
        if len(channels) >= limit:
            break
        try:
            text = _fetch_text(src["url"])
            channels.extend(parse_m3u(text, source_name=src.get("name")))
        except Exception as e:
            failed.append(src.get("name") or mask_host(src.get("url", "")))
            logging_setup.log_debug(f"[iptv] source '{src.get('name')}' failed: {e}")

    if not channels and failed:
        raise IPTVError(i18n.t("iptv_unavailable"))

    channels = channels[:limit]
    with _CACHE_LOCK:
        _CACHE[key] = {"channels": channels, "fetched_at": now}
    return list(channels)


# --------------------------------------------------------------- جستجو

def _normalize(text):
    """
    یکسان‌سازی برای مقایسه: بزرگی/کوچکی حروف، رقم فارسی/عربی -> لاتین،
    ی/ي و ک/ك -> یه شکل، فاصله‌های تکراری/نیم‌فاصله -> یه اسپیس.
    """
    text = (text or "").strip().lower()
    text = text.translate(_DIGIT_MAP)
    text = text.replace("ي", "ی").replace("ك", "ک")
    text = text.replace("‌", " ")  # نیم‌فاصله
    return re.sub(r"\s+", " ", text).strip()


def search(bot, query, channels=None):
    """
    جستجوی نام کانال: بدون‌حساسیت به بزرگی/کوچکی، فرقِ ی/ي و ک/ك، رقم
    فارسی/عربی، و تطبیقِ جزئی (کافیه هر کلمه‌ی سرچ یه‌جای اسم باشه، به هر
    ترتیب). channels=None یعنی از fetch_channels (ممکنه IPTVError بده).
    """
    channels = fetch_channels(bot) if channels is None else channels
    norm_query = _normalize(query)
    if not norm_query:
        return list(channels)
    words = norm_query.split(" ")
    return [ch for ch in channels if all(w in _normalize(ch.get("name")) for w in words)]


def paginate(items, page, size):
    """(آیتم‌های صفحه، شماره‌ی صفحه‌ی واقعی، تعداد صفحه‌ها، تعداد کل)."""
    size = max(1, int(size or 1))
    total = len(items)
    pages = max(1, (total + size - 1) // size)
    try:
        page = int(page or 1)
    except (TypeError, ValueError):
        page = 1
    page = min(max(1, page), pages)
    start = (page - 1) * size
    return list(items[start:start + size]), page, pages, total


# ------------------------------------------------------------ حالت تلویزیون

def set_list(bot, channels):
    """آخرین لیستِ شماره‌گذاری‌شده رو ثبت می‌کنه (نتیجه‌ی سرچ یا یه صفحه از list)."""
    bot.iptv_channels = list(channels)
    bot.iptv_playing_index = None


def has_list(bot):
    """آیا الان یه لیستِ شماره‌گذاری‌شده هست که یه عدد خام بهش معنی بده؟"""
    return bool(getattr(bot, "iptv_channels", None))


def current_list(bot):
    return list(getattr(bot, "iptv_channels", None) or [])


def is_active(bot):
    """آیا الان یه کانال IPTV در حال پخشه (برای n/b -- نه فقط «لیستی هست»)."""
    return getattr(bot, "iptv_playing_index", None) is not None


_HEADER_PROPERTIES = ("user_agent", "referrer")


def _player_raw(bot):
    player = getattr(bot, "player", None)
    return getattr(player, "raw", None) if player is not None else None


def apply_stream_headers(bot, channel):
    """
    هدرهای EXTVLCOPT کانال (user-agent/referrer) رو روی mpv می‌ذاره.
    `channel` هر دیکشنری‌ای با این دو کلید می‌تونه باشه: bot.load_and_play همین
    رو برای لینک‌هایی که لوله‌ی عمومی (core/link_resolver.py) گفته Referer/UA
    می‌خوان صدا می‌زنه.

    mpv این‌ها رو فقط به‌صورت پراپرتیِ سراسری داره، پس مقدارِ پیش‌فرضِ
    پخش‌کننده بار اول نگه داشته می‌شه: کانالی که هدر نداره همون پیش‌فرض رو
    می‌گیره -- نه رشته‌ی خالی، چون خیلی از سرورها درخواستِ بی‌User-Agent رو
    رد می‌کنن -- و clear() بعد از IPTV همون رو برمی‌گردونه.
    """
    raw = _player_raw(bot)
    if raw is None:
        return
    defaults = getattr(bot, "iptv_player_defaults", None)
    if defaults is None:
        defaults = {}
        for name in _HEADER_PROPERTIES:
            try:
                value = getattr(raw, name)
            except Exception:
                value = None
            defaults[name] = value if isinstance(value, str) else None
        bot.iptv_player_defaults = defaults
    for name in _HEADER_PROPERTIES:
        value = channel.get(name) or defaults.get(name)
        if value is None:
            continue
        try:
            setattr(raw, name, value)
        except Exception:
            logging_setup.log_debug(f"iptv: could not set player {name}")


def _restore_player_headers(bot):
    """
    هدرهای پیش‌فرضِ mpv رو برمی‌گردونه -- فقط اگه IPTV قبلاً عوضشون کرده.

    load_and_play این مسیر رو برای *هر* پخشی صدا می‌زنه؛ اگه به پخش‌کننده‌ای
    که IPTV هیچ‌وقت بهش دست نزده دست می‌زد، User-Agent همه‌ی استریم‌های
    یوتیوب و بقیه عوض می‌شد.
    """
    defaults = getattr(bot, "iptv_player_defaults", None)
    if defaults is None:
        return
    bot.iptv_player_defaults = None
    raw = _player_raw(bot)
    if raw is None:
        return
    for name, value in defaults.items():
        if value is None:
            continue
        try:
            setattr(raw, name, value)
        except Exception:
            logging_setup.log_debug(f"iptv: could not restore player {name}")


def _play_channel(bot, index, channel, requested_by=None):
    if not licensed(bot):
        raise IPTVError(i18n.t("iptv_not_licensed"))
    apply_stream_headers(bot, channel)
    item = {"url": channel.get("url"), "title": channel.get("name"), "public_url": None}
    # private=True: آدرس استریم/پلی‌لیست حساسه (معمولاً یوزر/پسورد داره)
    # -- نه با k به کسی داده می‌شه، نه توی تاریخچه ثبت می‌شه، نه با dl توی
    # کانال آپلود می‌شه (PAID_PRIVATE_SERVICES توی core/command_helpers.py).
    bot.load_and_play(item, private=True, service_name=SERVICE_NAME)
    bot.iptv_playing_index = index
    return channel


def play(bot, number, requested_by=None):
    """
    کانال شماره‌ی number از آخرین لیست رو پخش می‌کنه (شماره ۱-پایه، همونی
    که کاربر روی صفحه دیده). هم‌نقشِ documentary.play، با این فرق که
    «شماره» اینجا ایندکسِ توی لیست آخره، نه ورودیِ یه فرمول.

    خروجی: dict کانالِ پخش‌شده.
    خطا: IPTVError با کلیدِ i18n قابل‌نمایش.
    """
    channels = current_list(bot)
    if not channels:
        raise IPTVError(i18n.t("iptv_no_list"))
    try:
        index = int(str(number).translate(_DIGIT_MAP)) - 1
    except (TypeError, ValueError):
        index = -1
    if not (0 <= index < len(channels)):
        raise IPTVError(i18n.t("iptv_invalid_number", count=len(channels)))
    return _play_channel(bot, index, channels[index], requested_by=requested_by)


def step(bot, delta, requested_by=None):
    """
    کانال بعدی (delta=+1) یا قبلی (delta=-1) *توی همون لیستِ آخر*.
    خروجی: dict کانالِ پخش‌شده، یا None اگه به لبه‌ی لیست رسیدیم یا اصلاً
    چیزی در حال پخش نیست.
    """
    if not is_active(bot):
        return None
    channels = current_list(bot)
    target = bot.iptv_playing_index + int(delta)
    if not (0 <= target < len(channels)):
        return None
    return _play_channel(bot, target, channels[target], requested_by=requested_by)


def clear(bot):
    """
    از حالت تلویزیون خارج می‌شه: لیستِ شماره‌گذاری‌شده پاک می‌شه و هدرهای
    پیش‌فرضِ پخش‌کننده (اگه IPTV عوضشون کرده بود) برمی‌گردن. load_and_play
    این رو برای هر پخشی که سرویسش iptv نیست صدا می‌زنه (مثل documentary.clear).
    """
    bot.iptv_channels = []
    bot.iptv_playing_index = None
    _restore_player_headers(bot)


def announce_playing(bot, channel, nickname):
    """
    پیامِ «الان این کانال پخش می‌شه» -- یه‌بار اینجا، تا هر مسیری که یه
    کانال IPTV پخش می‌کنه (tv <عدد>، عددِ خام توی bot.py، n/b) از همینِ
    یکی استفاده کنه. فقط اسمِ کانال، هیچ‌وقت آدرس استریم.
    """
    bot.channel_broadcast(i18n.t("iptv_playing", title=channel.get("name") or "-",
                                 nickname=nickname))


def step_command(bot, ctx, delta):
    """
    n/b وقتی یه کانال IPTV در حال پخشه: کانال بعدی/قبلی و اعلامش توی کانال.

    True یعنی رسیدگی شد و دستور نباید سراغ صف بره. یه نسخه برای هر دو دستور،
    تا خطا و پیام‌ها یه جا درست بشن.
    """
    if not is_active(bot):
        return False
    try:
        channel = step(bot, delta, requested_by=ctx.get("username"))
    except IPTVError as e:
        bot.t.user_message(ctx["uid"], str(e))
        return True
    except Exception as e:
        # متنِ خامِ خطای پخش‌کننده می‌تونه آدرسِ استریم رو داشته باشه.
        bot.t.user_message(ctx["uid"], i18n.t("command_error", error=logging_setup.safe_error_text(e)))
        return True
    if channel is None:
        command_helpers.notify(bot, ctx, "iptv_last" if delta > 0 else "iptv_first")
        return True
    announce_playing(bot, channel, ctx["nickname"])
    return True

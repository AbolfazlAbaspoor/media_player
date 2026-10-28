"""
مدل یکتای متادیتای ترک (برای دستورهای i و di) و ترتیب زمانی لیست‌ها.

## چرا این فایل هست

قبلاً `i` فقط عنوان/لینک/موقعیت/طول رو نشون می‌داد و `di` فقط برای یوتیوب
کار می‌کرد (از کش توضیحات خود سرویس یوتیوب می‌خوند). هر سرویس هم متادیتای
خودش رو یه‌جوری برمی‌گردوند. حالا:

  * `from_info(info)` از یه dict به سبک yt-dlp (اسم فیلدها بین همه‌ی
    اکسترکتورها مشترکه) یک dict نرمال می‌سازه -- تنها جایی که «چی از یه
    آیتم می‌دونیم» تعریف می‌شه. سرویس‌هایی که yt-dlp نیستن (آپارات، ...)
    هم همون اسم‌ها رو پر می‌کنن و از همین تابع رد می‌شن.
  * نتیجه موقع resolve به آیتم چسبونده می‌شه (کلید "info")، از صف به
    `bot.track_meta` می‌رسه و `i`/`di` فقط از همون‌جا می‌خونن -- بدون هیچ
    درخواست اضافه‌ای.
  * فقط فیلدهایی که واقعاً مقدار دارن توی dict می‌مونن؛ نمایش هم فقط
    همون‌ها رو نشون می‌ده.

## ترتیب زمانی

`sort_newest_first` تنها مرحله‌ی مرتب‌سازیِ همه‌ی مسیرهای لیست‌گیری
(کانال، تب، پروفایل ...) است: نو به کهنه، و وقتی تاریخ نیست ترتیب منبع
دست‌نخورده می‌مونه. فقط «فید»ها مرتب می‌شن (YtdlpService._is_feed)؛
پلی‌لیست/آلبوم ترتیب خودِ صاحبش رو نگه می‌داره.

### کدوم منبع تاریخ می‌ده (تجربه‌ی زنده)

  * یوتیوب (تب videos/shorts/streams): entryهای flat هیچ timestamp
    ندارن. ترتیب خودِ تب نو به کهنه‌ست، ولی برای تاریخ، فید RSS کانال
    (یک درخواست سبک، ۱۵ آپلود اخیرِ همه‌ی تب‌ها) استفاده می‌شه؛ قدیمی‌ترها
    بی‌تاریخ می‌مونن و همون‌جا (بعد از تاریخ‌دارها) می‌شینن.
  * ساندکلاد (صفحه‌ی هنرمند): flat هیچ تاریخی نداره و ترتیب API آلبوم/
    ری‌پست وسطش قاطی می‌کنه (مثلاً ۲۶ اوت بین ۲۴ اوت‌ها). تاریخ چندتای اول
    با استخراج کامل (موازی) گرفته می‌شه (DATE_PROBE_LIMIT).
  * آپارات (لیست کانال): API خودش sdate_rss (وقت تهران) می‌ده -- بدون
    درخواست اضافه.
  * اینستاگرام: همه‌ی آیتم‌ها کامل resolve می‌شن و timestamp دارن؛ خودِ
    لیست بدون لاگین از این ماشین خالی برگشت (best-effort).
  * سرچ متنی (p/ytsearch/scsearch) عمداً مرتب نمی‌شه: ترتیبش «ارتباط» است.
"""

import calendar
import datetime

#: فیلدهای عددی که مستقیم از info برداشته می‌شن.
_COUNT_FIELDS = ("view_count", "like_count", "dislike_count", "comment_count",
                 "repost_count")

#: فیلدهای رشته‌ایِ ساده (کلیدِ خروجی، کلیدهای ممکن در info به ترتیب اولویت).
_TEXT_FIELDS = (
    ("uploader", ("uploader", "creator", "artist", "uploader_id")),
    ("channel", ("channel", "uploader")),
    ("channel_url", ("channel_url", "uploader_url")),
    ("description", ("description",)),
    ("live_status", ("live_status",)),
    ("ext", ("ext",)),
    ("acodec", ("acodec",)),
    ("vcodec", ("vcodec",)),
    ("format", ("format", "format_note")),
    ("resolution", ("resolution",)),
    ("playlist_title", ("playlist_title", "playlist")),
    ("license", ("license",)),
    ("availability", ("availability",)),
    ("id", ("id",)),
)

_TEHRAN_OFFSET = 3.5 * 3600  # آپارات زمان‌ها رو به وقت تهران می‌ده (بدون DST از ۱۴۰۱).


# ------------------------------------------------------------- زمان


def parse_timestamp(value, utc_offset=0):
    """
    هر شکلی از تاریخ رو به epoch (UTC، ثانیه) تبدیل می‌کنه، یا None.

    قبول می‌کنه: عدد (ثانیه یا میلی‌ثانیه)، "YYYYMMDD" (شکل yt-dlp)،
    ISO-8601 (با یا بدون Z/offset) و "YYYY-MM-DD HH:MM:SS". رشته‌ی بدون
    منطقه‌ی زمانی با `utc_offset` (ثانیه‌ی اختلاف از UTC) تعبیر می‌شه.
    """
    if value in (None, "", 0):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 1e11:  # میلی‌ثانیه
            seconds /= 1000.0
        return int(seconds) if seconds > 0 else None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        if len(text) == 8:
            try:
                dt = datetime.datetime.strptime(text, "%Y%m%d")
            except ValueError:
                return None
            return calendar.timegm(dt.timetuple()) - int(utc_offset)
        return parse_timestamp(int(text))
    iso = text.replace("Z", "+00:00").replace("z", "+00:00")
    if " " in iso and "T" not in iso:
        iso = iso.replace(" ", "T", 1)
    try:
        dt = datetime.datetime.fromisoformat(iso)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        return int(dt.timestamp())
    return calendar.timegm(dt.timetuple()) - int(utc_offset)


def timestamp_of(item):
    """
    زمان انتشارِ یه آیتم/stub/متا (epoch) یا None. هم شکل نرمال
    ("timestamp") هم فیلدهای خامِ yt-dlp/آپارات رو می‌فهمه، و توی "info"
    تو در تو هم می‌گرده.
    """
    if not isinstance(item, dict):
        return None
    for key in ("timestamp", "release_timestamp"):
        ts = parse_timestamp(item.get(key))
        if ts:
            return ts
    ts = parse_timestamp(item.get("upload_date"), _TEHRAN_OFFSET
                         if _looks_like_tehran(item) else 0)
    if ts:
        return ts
    info = item.get("info")
    if isinstance(info, dict):
        return timestamp_of(info)
    return None


def _looks_like_tehran(item):
    """آپارات تاریخِ بدون منطقه‌ی زمانی به وقت تهران می‌ده؛ بقیه UTC."""
    text = " ".join(str(item.get(k) or "") for k in ("webpage_url", "url", "public_url"))
    return "aparat.com" in text


def format_date(ts):
    """epoch -> "2026-09-19 16:00 UTC" (یا None)."""
    if not ts:
        return None
    try:
        dt = datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def sort_newest_first(items):
    """
    ترتیب یکتای همه‌ی لیست‌ها: جدیدترین اول.

    قاعده (تا ترتیبِ منبع، که معمولاً خودش نو-به-کهنه‌ست، خراب نشه):
      * هیچ آیتمی تاریخ نداره -> لیست دست‌نخورده.
      * همه تاریخ دارن -> مرتب‌سازیِ پایدار نزولی.
      * بعضی تاریخ دارن -> آیتم‌های بی‌تاریخ سر جای خودشون می‌مونن و
        آیتم‌های تاریخ‌دار به ترتیب نزولی توی بقیه‌ی خانه‌ها می‌نشینن.
    ورودی تغییر نمی‌کنه؛ لیست تازه برمی‌گرده.
    """
    items = list(items)
    stamps = [timestamp_of(item) for item in items]
    dated = [i for i, ts in enumerate(stamps) if ts]
    if not dated:
        return items
    ordered = sorted((items[i] for i in dated), key=timestamp_of, reverse=True)
    out = list(items)
    for slot, item in zip(dated, ordered):
        out[slot] = item
    return out


def merge_newest_first(*lists):
    """چند لیست (مثلاً تب‌های یه کانال) رو ادغام و با sort_newest_first مرتب می‌کنه."""
    merged = []
    seen = set()
    for lst in lists:
        for item in lst or []:
            key = item.get("id") if isinstance(item, dict) else None
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            merged.append(item)
    return sort_newest_first(merged)


# --------------------------------------------------------- ساخت متا


def _count(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _pick_text(info, keys):
    for key in keys:
        value = info.get(key)
        if isinstance(value, str) and value.strip() and value.strip().lower() != "none":
            return value.strip()
    return None


def from_info(info, service=None):
    """
    dict نرمالِ متادیتا از یه info به سبک yt-dlp. فقط فیلدهای دارای مقدار.

    کلیدها: uploader, channel, channel_url, timestamp (UTC epoch),
    view_count, like_count, dislike_count, comment_count, repost_count,
    duration, description, tags, categories, live_status, ext, acodec,
    vcodec, abr, tbr, resolution, format, filesize, asr, fps, playlist_title,
    age_limit, license, availability, id, service, extractor.
    """
    out = {}
    if not isinstance(info, dict):
        return out

    for key, sources in _TEXT_FIELDS:
        text = _pick_text(info, sources)
        if text and key in ("acodec", "vcodec") and text == "none":
            text = None
        if text:
            out[key] = text

    ts = timestamp_of(info)
    if ts:
        out["timestamp"] = ts

    for key in _COUNT_FIELDS:
        number = _count(info.get(key))
        if number is not None:
            out[key] = number

    duration = info.get("duration")
    if isinstance(duration, (int, float)) and duration > 0:
        out["duration"] = int(duration)

    for key in ("tags", "categories"):
        values = [str(v).strip() for v in (info.get(key) or []) if str(v).strip()]
        if values:
            out[key] = values

    if "live_status" not in out and info.get("is_live"):
        out["live_status"] = "is_live"

    for key in ("abr", "tbr", "fps", "asr"):
        value = info.get(key)
        if isinstance(value, (int, float)) and value > 0:
            out[key] = value

    size = info.get("filesize") or info.get("filesize_approx")
    if isinstance(size, (int, float)) and size > 0:
        out["filesize"] = int(size)

    if "resolution" not in out and info.get("width") and info.get("height"):
        out["resolution"] = f"{info['width']}x{info['height']}"

    age = info.get("age_limit")
    if isinstance(age, int) and age > 0:
        out["age_limit"] = age

    extractor = info.get("extractor_key") or info.get("extractor")
    if extractor:
        out["extractor"] = str(extractor)
    if service:
        out["service"] = service
    return out


def merge(base, extra):
    """extra روی base می‌شینه (extra برنده‌ست)؛ هیچ‌کدوم تغییر نمی‌کنن."""
    merged = dict(base or {})
    merged.update({k: v for k, v in (extra or {}).items() if v not in (None, "", [])})
    return merged


# ------------------------------------------------------------ نمایش


def format_count(number):
    """12345 -> '12,345'."""
    return f"{int(number):,}"


def format_size(size):
    """بایت -> متن خوانا (MB/GB)."""
    size = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


_PERSIAN_TABLE = str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹،")


def localize_digits(text, language):
    """برای زبان فارسی رقم‌ها و ویرگول رو فارسی می‌کنه؛ برای بقیه دست‌نخورده."""
    return str(text).translate(_PERSIAN_TABLE) if language == "fa" else str(text)

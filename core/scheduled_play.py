"""
پخشِ زمان‌بندی‌شده (دستور sch، فقط ادمین: admin_bot یا بالاتر).

    sch add HH:MM [روزها] <جستجو | لینک | sf N>
    sch list
    sch del <n>

روزها (اختیاری، قبل از هدف): `mon,wed,fri` (۳حرفیِ انگلیسی، با کاما)،
`weekdays`، `weekends` یا `daily`. بدونِ روز یعنی هر روز.
هدف: یه عبارتِ جستجو (مثل دستور p)، یه لینک (مثل پیستِ لینک)، یا `sf N`
(آیتمِ N از فروریتِ لاگین‌شده‌ی خودِ ادمین؛ همون لحظه‌ی افزودن به لینکِ
صفحه‌ش تبدیل و ذخیره می‌شه، پس بعدها به لاگین بودنِ ادمین وابسته نیست).

## ساعت

**ساعتِ محلیِ سیستمی که ربات روش اجرا می‌شه** (datetime.now() بدونِ tzinfo).
ربات فعلاً کانفیگِ منطقه‌ی زمانی نداره؛ اگه روزی اضافه بشه فقط now() عوض
می‌شه. (همین متن توی خروجیِ `sch list` هم به کاربر گفته می‌شه.)

## ذخیره

توی cfg["schedule"] -- یه لیستِ dict که جزو کلیدهای *مخصوصِ همین ربات*
(identity.json، نه shared_config) است؛ چون برنامه‌ی پخشِ یه ربات نباید روی
ربات‌های دیگه‌ی همون سرور اثر بذاره. با ری‌استارت می‌مونه.

## اجرا

از core/scheduler.py (همون زمان‌بندِ تک‌تردی‌ای که تایمرهای dl/st استفاده
می‌کنن) استفاده می‌شه، نه یه ترد/حلقه‌ی جدید: یه کارِ دورنی که فقط وقتی
این ربات حداقل یه برنامه داره وجود داره، برای نزدیک‌ترین موعد (یا حداکثر
MAX_SLEEP_SECONDS بعد، تا تغییرِ ساعتِ سیستم/DST هم دیده بشه) تنظیم می‌شه
و بعد از هر اجرا خودش دوباره تنظیم می‌شه. موعد با ساعتِ دیواری سنجیده
می‌شه، نه با شمارشِ دورنی، پس سنکرون‌بودنش به ساعتِ واقعی تضمین‌شده‌ست.

در موعد، پخش *عیناً مثلِ این‌که همون ادمین فرستاده باشه* انجام می‌شه: یه
ctx با یوزرنیم/نیک‌نیمِ ادمین (و شناسه‌ی زنده‌اش اگه آنلاینه) ساخته می‌شه و
handlerِ ثبت‌شده‌ی `p` (برای جستجو) یا command_helpers.run_link_command
(برای لینک -- همون مسیرِ پیستِ لینک) صدا زده می‌شه. موعدی که ربات موقعِ
خاموش/قطع بودن ازش رد شده (بیش از LATE_GRACE_SECONDS) اجرا *نمی‌شه*:
یه آهنگ ساعتِ ۸ صبح ساعتِ ۱۰ شب پخش نشه.
"""

import datetime
import threading

from core import command_helpers
from core import i18n
from core import license_gate
from core import logging_setup
from core import scheduler

SERVICE_NAME = "schedule"

MAX_ENTRIES = 30
MAX_TARGET_CHARS = 200

# ربات اگه موعد رو با این‌قدر تأخیر دید هنوز اجراش می‌کنه؛ بیشتر = از دست رفته.
LATE_GRACE_SECONDS = 120
# بیشترین فاصله‌ی دو بیدارشدن (برای دیدنِ تغییرِ ساعت/DST).
MAX_SLEEP_SECONDS = 300

_DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_DAY_GROUPS = {
    "daily": (),
    "weekdays": (0, 1, 2, 3, 4),
    "weekends": (5, 6),
}

_lock = threading.RLock()


class ScheduleError(Exception):
    """خطای قابل‌نمایش: key کلیدِ i18n و kwargs پارامترهاشه (هیچ متنِ خامی نیست)."""

    def __init__(self, key, **kwargs):
        super().__init__(key)
        self.key = key
        self.kwargs = kwargs


# --------------------------------------------------------------- parse

def parse_time(text):
    """'8:05' / '08:05' -> (8, 5)؛ ساعتِ ۲۴ساعته. خطا -> ScheduleError."""
    parts = (text or "").strip().split(":")
    if (len(parts) != 2 or not parts[0].isdigit() or len(parts[0]) > 2
            or not parts[1].isdigit() or len(parts[1]) != 2):
        raise ScheduleError("sch_bad_time")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ScheduleError("sch_bad_time")
    return hour, minute


def parse_days(token):
    """
    'mon,wed' / 'weekdays' / 'daily' -> tuple ِ مرتبِ روزها (دوشنبه=۰)، با ()
    برای «هر روز». اگه token اصلاً شکلِ «روزها» نداره None (یعنی این جزوِ
    هدفه، نه روزها -- تا «friday» به‌عنوانِ عبارتِ جستجو قاپیده نشه).
    """
    token = (token or "").strip().lower()
    if token in _DAY_GROUPS:
        return _DAY_GROUPS[token]
    names = token.split(",")
    if not names or not all(name in _DAY_NAMES for name in names):
        return None
    return tuple(sorted({_DAY_NAMES.index(name) for name in names}))


def parse_add(args):
    """
    آرگومان‌های بعد از `sch add` -> (hour, minute, days, target_text).
    target_text هنوز خام است؛ build_target اون رو به {kind, query} تبدیل می‌کنه.
    """
    args = list(args or [])
    if not args:
        raise ScheduleError("sch_usage")
    hour, minute = parse_time(args[0])
    rest = args[1:]
    days = ()
    if rest:
        parsed = parse_days(rest[0])
        if parsed is not None:
            days, rest = parsed, rest[1:]
    target = " ".join(rest).strip()
    if not target:
        raise ScheduleError("sch_missing_target")
    if len(target) > MAX_TARGET_CHARS:
        raise ScheduleError("sch_target_too_long", max=MAX_TARGET_CHARS)
    return hour, minute, days, target


def build_target(bot, ctx, target):
    """
    هدفِ خام -> {"kind": "link"|"play", "query": ...}.

    `sf N` اینجا (موقعِ افزودن) به لینکِ صفحه‌ی آیتمِ N از فروریتِ
    لاگین‌شده‌ی ادمین تبدیل می‌شه؛ اگه لاگین نیست یا N نامعتبره،
    ScheduleError (پیامِ مناسب به خودِ ادمین می‌ره).
    """
    words = target.split()
    if words[0].lower() == "sf" and len(words) == 2 and words[1].isdigit():
        return _favorite_target(bot, ctx, int(words[1]))
    if command_helpers.looks_like_bare_link(target) or command_helpers.is_link(target):
        return {"kind": "link", "query": command_helpers.normalize_pasted_link(target)}
    return {"kind": "play", "query": target}


def _favorite_target(bot, ctx, number):
    from core import accounts
    account_username, _path, data, _is_public = accounts.get_session_account(bot, ctx["username"])
    if data is None:
        raise ScheduleError("sf_not_logged_in")
    favorites = data.get("favorites", [])
    if not (1 <= number <= len(favorites)):
        raise ScheduleError("invalid_playlist_number")
    entry = favorites[number - 1]
    return {"kind": "link", "query": entry.get("public_url") or entry["url"],
            "title": entry.get("title") or None}


# --------------------------------------------------------------- ذخیره

def _entries(bot):
    """لیستِ زنده‌ی cfg["schedule"] (اگه نبود یا خراب بود، یه لیستِ تازه جاش می‌شینه)."""
    current = bot.cfg.get("schedule")
    if not isinstance(current, list):
        current = bot.cfg["schedule"] = []
    return current


def _sort_key(entry):
    return (entry.get("time", ""), entry.get("id", 0))


def add(bot, ctx, hour, minute, days, target):
    """برنامه رو ذخیره می‌کنه؛ (شماره‌ی ۱-مبنا توی `sch list`، خودِ برنامه)."""
    resolved = build_target(bot, ctx, target)
    with _lock:
        entries = _entries(bot)
        if len(entries) >= MAX_ENTRIES:
            raise ScheduleError("sch_full", max=MAX_ENTRIES)
        next_id = max([e.get("id", 0) for e in entries] + [0]) + 1
        entry = {
            "id": next_id,
            "time": f"{hour:02d}:{minute:02d}",
            "days": list(days),
            "kind": resolved["kind"],
            "query": resolved["query"],
            "by": ctx["username"],
            "nickname": ctx.get("nickname") or ctx["username"],
            "last_run": "",
        }
        if resolved.get("title"):
            entry["title"] = resolved["title"]
        entries.append(entry)
        entries.sort(key=_sort_key)
        number = entries.index(entry) + 1
    bot.save_config()
    arm(bot)
    return number, entry


def delete(bot, number):
    """برنامه‌ی شماره‌ی number (۱-مبنا) رو حذف می‌کنه؛ True اگه بود."""
    with _lock:
        entries = _entries(bot)
        if not (1 <= number <= len(entries)):
            return False
        entries.pop(number - 1)
    bot.save_config()
    arm(bot)
    return True


def describe_when(entry):
    """'08:30 every day' / '08:30 mon,wed' برای لیست و اعلام."""
    days = entry.get("days") or []
    if not days or len(days) == 7:
        when = i18n.t("sch_when_daily")
    else:
        when = ",".join(_DAY_NAMES[d] for d in days if 0 <= d < 7)
    return f"{entry.get('time', '')} {when}"


def describe_target(entry):
    """متنِ قابل‌نمایش: عبارتِ جستجو، یا عنوانِ فروریت، یا «یه لینک» (لینک هیچ‌وقت نمایش داده نمی‌شه)."""
    if entry.get("kind") == "link":
        return entry.get("title") or i18n.t("sch_target_link")
    return entry.get("query", "")


def list_lines(bot):
    """خطوطِ خروجیِ `sch list` (بدون هدر)؛ لیستِ خالی اگه برنامه‌ای نیست."""
    with _lock:
        snapshot = list(_entries(bot))
    return [f"{number}. {describe_when(entry)} - {_list_target(entry)}"
            for number, entry in enumerate(snapshot, start=1)]


def _list_target(entry):
    # `sch list` فقط برای خودِ ادمینه (خصوصی)، پس اینجا لینک هم دیده می‌شه تا
    # بشه فرقِ دو برنامه‌ی لینکی رو فهمید.
    if entry.get("kind") == "link":
        return entry.get("title") or entry.get("query", "")
    return entry.get("query", "")


# --------------------------------------------------------------- زمان

def scheduled_moment(entry, day):
    """datetime ِ موعدِ entry توی روزِ day (date)، یا None اگه امروز روزش نیست/خراب است."""
    try:
        hour, minute = (int(part) for part in entry["time"].split(":"))
        days = entry.get("days") or []
        if days and day.weekday() not in days:
            return None
        return datetime.datetime.combine(day, datetime.time(hour, minute))
    except (KeyError, ValueError, AttributeError, TypeError):
        return None


def due_entries(entries, now):
    """
    برنامه‌هایی که الان باید اجرا بشن: موعدِ امروزشون رسیده، از
    LATE_GRACE_SECONDS بیشتر نگذشته، و امروز قبلاً اجرا نشدن (last_run).
    """
    today = now.date()
    due = []
    for entry in entries:
        moment = scheduled_moment(entry, today)
        if moment is None or entry.get("last_run") == today.isoformat():
            continue
        late = (now - moment).total_seconds()
        if 0 <= late <= LATE_GRACE_SECONDS:
            due.append(entry)
    return due


def seconds_until_next(entries, now):
    """ثانیه تا نزدیک‌ترین موعدِ آینده (None اگه برنامه‌ای نیست)."""
    best = None
    for entry in entries:
        for offset in range(0, 8):
            day = now.date() + datetime.timedelta(days=offset)
            moment = scheduled_moment(entry, day)
            if moment is None:
                continue
            if offset == 0 and (moment <= now or entry.get("last_run") == day.isoformat()):
                continue
            delta = (moment - now).total_seconds()
            if best is None or delta < best:
                best = delta
            break
    return best


def _now():
    return datetime.datetime.now()


# ------------------------------------------------------------ زمان‌بندی

def arm(bot, now_fn=None):
    """
    کارِ بعدی رو روی core.scheduler تنظیم می‌کنه (کارِ قبلیِ همین ربات رو
    لغو می‌کنه). بدونِ برنامه هیچ کاری باقی نمی‌مونه.
    """
    now = (now_fn or _now)()
    with _lock:
        previous = getattr(bot, "_schedule_task_id", None)
        if previous is not None:
            scheduler.cancel(previous)
            bot._schedule_task_id = None
        entries = _entries(bot)
        # موعدی که هنوز توی مهلتِ دیرکرد هست (مثلاً ربات همون دقیقه بالا اومد)
        # همین الان اجرا می‌شه.
        wait = 0.0 if due_entries(entries, now) else seconds_until_next(entries, now)
        if wait is None:
            return None
        delay = min(max(wait, 0.0), MAX_SLEEP_SECONDS)
        # چند ثانیه‌ی اضافه: موقعِ بیدار شدن مطمئن باشیم ساعتِ دیواری رد شده.
        bot._schedule_task_id = scheduler.schedule(delay + 0.5, fire_due, bot)
        return bot._schedule_task_id


def fire_due(bot, now_fn=None):
    """موعدرسیده‌ها رو اجرا می‌کنه و کارِ بعدی رو تنظیم می‌کنه (توی ترد core.scheduler)."""
    now = (now_fn or _now)()
    try:
        with _lock:
            due = due_entries(_entries(bot), now)
            for entry in due:
                entry["last_run"] = now.date().isoformat()
        if due:
            bot.save_config()
        for entry in due:
            _start(bot, dict(entry))
    finally:
        arm(bot, now_fn)


def _admin_ctx(bot, entry):
    """
    ctx ای که انگار خودِ ادمین فرستاده. اگه ادمین آنلاینه شناسه‌ی زنده و
    نیک‌نیمِ فعلیش، وگرنه شناسه‌ی ۰ (پیام‌های خصوصی بی‌اثر می‌مونن) و
    نیک‌نیمِ ذخیره‌شده.
    """
    username = entry.get("by") or ""
    uid, nickname = 0, entry.get("nickname") or username
    try:
        online = bot.t.get_user_by_username(username) if username else None
    except Exception:
        online = None
    if online:
        uid = online.get("user_id", 0)
        nickname = online.get("nickname") or nickname
    return {"uid": uid, "nickname": nickname, "username": username,
            "raw": "", "args": [], "cmd": "sch", "bot": bot, "scheduled": True}


def _start(bot, entry):
    """اعلام توی کانال، بعد پخشِ عیناً مثلِ دستورِ خودِ ادمین (توی ترد جدا: جستجو/resolve کنده)."""
    if not license_gate.bot_allows_service(bot, SERVICE_NAME):
        logging_setup.log_info("scheduled playback skipped: not in this bot's licence")
        return
    ctx = _admin_ctx(bot, entry)
    bot.channel_broadcast(i18n.t("sch_fired", time=entry.get("time", ""),
                                 nickname=ctx["nickname"], target=describe_target(entry)))
    threading.Thread(target=_play, args=(bot, ctx, entry), daemon=True).start()


def _play(bot, ctx, entry):
    try:
        if entry.get("kind") == "link":
            command_helpers.run_link_command(bot, ctx, entry["query"])
        else:
            ctx = dict(ctx, args=entry["query"].split(), raw="p " + entry["query"], cmd="p")
            bot.commands["p"]["handler"](ctx)
    except Exception:
        logging_setup.log_exception("scheduled playback")


def install(bot):
    """یه‌بار موقعِ بالا اومدنِ ربات: برنامه‌های ذخیره‌شده رو دوباره تنظیم می‌کنه."""
    arm(bot)

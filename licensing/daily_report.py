"""
داده‌ی گزارش روزانه‌ی ادمین‌ها (متن و ارسالش توی ربات فروشه؛ این‌جا فقط جمع‌آوری).

یه dict ساده برمی‌گردونه تا هم ارسالِ صبحگاهی و هم دکمه‌ی «📊 گزارش همین
الان» از یه منبع بخونن:

    bots       {"running": n, "crashed": n, "blocked": n}
    errors     {"count": n, "top": [(زمینه, تعداد), ...]}
    expiring   {"count": n, "items": [{"key", "user", "expires_at"}, ...]}
    orders_pending   سفارش‌های منتظرِ تأییدِ ادمین
    crypto     None (تتر خاموشه) یا {"pending", "received", "received_micro"}

## خطاها

errors.log همه‌ی پروسه‌های این نصب (ربات‌ها و license_server) رو توی یه
فایل می‌نویسه. از هر خطش فقط «زمینه‌ی» ثبت‌شده (while: ...) و زمانش خونده
می‌شه، هیچ‌وقت متنِ exception یا traceback. زمینه‌ها هم قبل از شمارش
تمیز می‌شن: متنِ توی کوتیشن (جستجو/لینکِ کاربر) و اسمِ درخواست‌دهنده
حذف می‌شه تا هم چیزی از کاربرها توی گزارش نیاد، هم «searching 'a'» و
«searching 'b'» یه گروه حساب بشن.

خطوطِ رمزشده (بیلد، #e1:) بدونِ کلیدِ خصوصی خونده نمی‌شن و شمرده نمی‌شن.
"""

import re
import time
from collections import Counter

from core import logging_setup
from licensing import config

WINDOW_SECONDS = 24 * 3600
EXPIRY_DAYS = 3
TOP_ERRORS = 3
MAX_EXPIRING_LISTED = 5
DEFAULT_HOUR = 9

# [logger] (while: زمینه) 2026-09-30 10:11:12,345 [ERROR] ...
_ENTRY = re.compile(
    r"^\[[^\]]*\] \(while: (?P<ctx>.*?)\) (?P<ts>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_REQUESTER = re.compile(r"\s*\(requested by [^)]*\)")
_NUMBER = re.compile(r"\d+")
_CONTEXT_MAX = 60


def report_hour():
    """ساعتِ ارسال (۰ تا ۲۳)؛ مقدارِ خراب یعنی پیش‌فرض."""
    try:
        hour = int(config.get("daily_report_hour", DEFAULT_HOUR))
    except (TypeError, ValueError):
        return DEFAULT_HOUR
    return hour if 0 <= hour <= 23 else DEFAULT_HOUR


def enabled():
    value = config.get("daily_report_enabled", True)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def clean_context(text):
    """زمینه‌ی لاگ بدونِ داده‌ی کاربر و عددِ متغیر، کوتاه‌شده."""
    text = _REQUESTER.sub("", text or "")
    text = _QUOTED.sub("'…'", text)
    text = _NUMBER.sub("N", text)
    text = " ".join(text.split())
    if len(text) > _CONTEXT_MAX:
        text = text[:_CONTEXT_MAX - 1] + "…"
    return text or "?"


def errors_summary(paths=None, now=None, top=TOP_ERRORS):
    """(تعداد خطاهای ۲۴ ساعت اخیر، [(زمینه، تعداد)] بیشترین‌ها)."""
    now = time.time() if now is None else now
    if paths is None:
        paths = (logging_setup.ERRORS_FILE + ".1", logging_setup.ERRORS_FILE)
    cutoff = now - WINDOW_SECONDS
    total = 0
    contexts = Counter()
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    found = _ENTRY.match(line)
                    if found is None:
                        continue
                    try:
                        stamp = time.mktime(time.strptime(found.group("ts"), "%Y-%m-%d %H:%M:%S"))
                    except (ValueError, OverflowError):
                        continue
                    if stamp < cutoff:
                        continue
                    total += 1
                    contexts[clean_context(found.group("ctx"))] += 1
        except OSError:
            continue
    return total, contexts.most_common(top)


def bot_health(db, supervisor=None):
    """
    {"running", "crashed", "blocked"}. وضعیتِ زنده‌ی supervisor مقدم است؛
    دیتابیس برای نمونه‌هایی که supervisor (هنوز) نمی‌شناسه -- مثلاً بعد از
    ری‌استارتِ سرور -- یا وقتی supervisor اصلاً نیست.
    """
    live = {item["slug"]: item for item in (supervisor.status() if supervisor else [])}
    counts = {"running": 0, "crashed": 0, "blocked": 0}
    for row in db.query("SELECT slug, status FROM instances WHERE status != 'removed'"):
        item = live.get(row["slug"])
        if item is not None:
            if item["alive"]:
                state = "running"
            elif item["blocked"]:
                state = "blocked"
            elif item["failures"] or row["status"] == "crashed":
                state = "crashed"
            else:
                state = None
        elif row["status"] == "running" and supervisor is None:
            state = "running"
        else:
            state = row["status"] if row["status"] in ("crashed", "blocked") else None
        if state:
            counts[state] += 1
    return counts


def _user_label(db, user_id):
    user = db.get_user(int(user_id))
    if user is None:
        return str(user_id)
    return f"@{user['username']}" if user["username"] else str(user["first_name"] or user_id)


def expiring_licenses(db, now):
    rows = db.licenses_expiring_before(now + EXPIRY_DAYS * 86400)
    items = [{"key": row["key"], "user": _user_label(db, row["user_id"]),
              "expires_at": int(row["expires_at"])}
             for row in rows[:MAX_EXPIRING_LISTED]]
    return {"count": len(rows), "items": items}


def collect(db, supervisor=None, now=None, errors_paths=None):
    """همه‌ی بخش‌های گزارش. همگام و I/O دارد -- از ترد صدا بزن."""
    now = int(time.time() if now is None else now)
    error_count, top = errors_summary(errors_paths, now)
    crypto = None
    if config.crypto_settings()["enabled"]:
        received = db.crypto_received_since(now - WINDOW_SECONDS)
        crypto = {"pending": len(db.pending_crypto_payments()),
                  "received": received[0], "received_micro": received[1]}
    return {
        "now": now,
        "bots": bot_health(db, supervisor),
        "errors": {"count": error_count, "top": top},
        "expiring": expiring_licenses(db, now),
        "orders_pending": len(db.pending_admin_orders(limit=500)),
        "crypto": crypto,
    }

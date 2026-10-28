"""
چک انقضای لایسنس‌ها.

## دو لایه، عمداً

  **لحظه‌ای**: هر جا لایسنس خونده می‌شه (استارت ربات، منوی تلگرام، درخواست
  API) تاریخ انقضا همون لحظه با ثانیه دقت چک می‌شه. یعنی یه لایسنسی که
  ساعت ۳ بعدازظهر تموم می‌شه، ساعت ۳ و یک دقیقه دیگه کار نمی‌کنه -- نه
  اینکه تا نیمه‌شب باز بمونه.

  **شبانه (ساعت ۱۲ شب)**: یه جاروی کامل که کارهای «سنگین» رو انجام می‌ده:
  علامت‌زدن منقضی‌ها، بستن لاین صدا، پاک‌کردن دیتای کسانی که مهلتشون تموم
  شده، و فرستادن یادآوری تمدید.

دلیل این تقسیم: بستن لاین صدا و پاک‌کردن دیتا کارهای برگشت‌ناپذیر و
پرهزینه‌ان؛ نباید وسط یه درخواست کاربر انجام بشن. ولی *دسترسی* باید فوری
قطع بشه.

## ترتیب کارها در جاروی شبانه

    ۱. یادآوری تمدید (هنوز فعال، ولی نزدیک انقضا)
    ۲. تازه-منقضی‌شده‌ها -> status=expired + شروع مهلت + خاموش‌کردن ربات‌ها
    ۳. مهلت‌تموم‌شده‌ها -> حذف لاین صدا + پاک‌کردن دیتا

قدم ۲ و ۳ جدان: کاربر اول فقط سرویسش قطع می‌شه (قابل برگشت با تمدید)، و
فقط اگه چند روز هیچ کاری نکرد، داده‌هاش پاک می‌شه.
"""

import time

from core import logging_setup
from licensing import config
from licensing import i18n
from licensing import licenses
from licensing import provisioning


class SweepResult:
    def __init__(self):
        self.reminded = []        # [(license_row, days_left)]
        self.expired = []         # [license_row]
        self.purged = []          # [license_row]
        self.errors = []

    def is_empty(self):
        return not (self.reminded or self.expired or self.purged or self.errors)

    def summary_fa(self):
        parts = []
        if self.reminded:
            parts.append(i18n.t("sweep_summary_reminded", count=len(self.reminded)))
        if self.expired:
            parts.append(i18n.t("sweep_summary_expired", count=len(self.expired)))
        if self.purged:
            parts.append(i18n.t("sweep_summary_purged", count=len(self.purged)))
        if self.errors:
            parts.append(i18n.t("sweep_summary_errors", count=len(self.errors)))
        separator = "، " if i18n.get_language() == "fa" else ", "
        return separator.join(parts) if parts else i18n.t("sweep_summary_nothing")


def seconds_until_next_run(hour=None, minute=None, now=None):
    """
    چند ثانیه تا اجرای بعدیِ جاروی شبانه. از زمان *محلی* سرور استفاده
    می‌شه، چون «ساعت ۱۲ شب» برای ادمین یعنی نیمه‌شبِ خودش.
    """
    hour = config.get("nightly_check_hour", 0) if hour is None else hour
    minute = config.get("nightly_check_minute", 5) if minute is None else minute
    now = now if now is not None else time.time()

    parts = list(time.localtime(now))
    parts[3] = int(hour)
    parts[4] = int(minute)
    parts[5] = 0
    target = time.mktime(tuple(parts))
    if target <= now:
        target += 86400
    return max(1, int(target - now))


def _use_recipient_language(db, user_id):
    """
    زبان گیرنده رو برای ساختن پیام ست می‌کنه.

    جاروی شبانه توی یه تسک پس‌زمینه اجرا می‌شه و هیچ آپدیت تلگرامی پشتش
    نیست، پس ContextVar زبان هنوز روی پیش‌فرضه. بدون این، همه‌ی یادآوری‌ها
    و اعلان‌های انقضا به زبان پیش‌فرض می‌رفت، نه زبان خود کاربر.
    """
    try:
        row = db.get_user(int(user_id))
    except Exception:
        row = None
    i18n.set_language(row["lang"] if row else None)


def days_left(license_row, now=None):
    now = now if now is not None else time.time()
    return int((int(license_row["expires_at"]) - now) // 86400)


def run_sweep(db, supervisor=None, notify=None, now=None):
    """
    جاروی کامل. notify یه callable(user_id, text) است (معمولاً ارسال پیام
    تلگرام) -- اگه None باشه، فقط دیتابیس به‌روز می‌شه.
    """
    now = int(now if now is not None else time.time())
    result = SweepResult()
    reminder_days = sorted(set(int(d) for d in (config.get("reminder_days") or [])), reverse=True)

    # --- ۱) یادآوری تمدید ---
    for license_row in db.active_licenses():
        try:
            left = days_left(license_row, now)
            if left < 0:
                continue
            stage = next((d for d in reminder_days if left <= d), None)
            if stage is None:
                continue
            # هر مرحله فقط یک بار: بدون این، هر شب تا انقضا پیام می‌رفت.
            if license_row["warned_stage"] == str(stage):
                continue
            db.update_license(int(license_row["id"]), warned_stage=str(stage))
            result.reminded.append((license_row, left))
            if notify:
                _use_recipient_language(db, license_row["user_id"])
                notify(int(license_row["user_id"]), _reminder_text(license_row, left))
        except Exception as e:
            result.errors.append(f"reminder for licence {license_row['id']}: {e}")
            logging_setup.log_exception(f"reminder for license {license_row['id']}")

    # --- ۲) تازه منقضی‌شده‌ها ---
    for license_row in db.licenses_expiring_before(now, status=licenses.STATUS_ACTIVE):
        try:
            updated = licenses.mark_expired(db, license_row)
            provisioning.deactivate_license(
                db, int(license_row["id"]), purge_data=False,
                supervisor=supervisor, reason="expired")
            result.expired.append(updated)
            if notify:
                _use_recipient_language(db, license_row["user_id"])
                notify(int(license_row["user_id"]), _expired_text(updated))
        except Exception as e:
            result.errors.append(f"expiring licence {license_row['id']}: {e}")
            logging_setup.log_exception(f"expiring license {license_row['id']}")

    # --- ۳) مهلت‌تموم‌شده‌ها: حالا دیگه دیتا پاک می‌شه ---
    for license_row in db.query(
        "SELECT * FROM licenses WHERE status = ? AND grace_until IS NOT NULL AND grace_until <= ?",
        (licenses.STATUS_EXPIRED, now),
    ):
        try:
            provisioning.deactivate_license(
                db, int(license_row["id"]), purge_data=True,
                supervisor=supervisor, reason="grace_over")
            db.update_license(int(license_row["id"]), grace_until=None)
            result.purged.append(license_row)
            if notify:
                _use_recipient_language(db, license_row["user_id"])
                notify(int(license_row["user_id"]), _purged_text(license_row))
        except Exception as e:
            result.errors.append(f"purging licence {license_row['id']}: {e}")
            logging_setup.log_exception(f"purging license {license_row['id']}")

    db.set_setting("last_sweep_at", str(now))
    db.log_event("sweep", detail={
        "reminded": len(result.reminded),
        "expired": len(result.expired),
        "purged": len(result.purged),
        "errors": result.errors,
    })
    return result


def check_one(db, license_id, supervisor=None, notify=None):
    """
    چک لحظه‌ای یه لایسنس. جایی صدا زده می‌شه که کاربر کاری با لایسنسش
    می‌کنه، تا لازم نباشه تا نیمه‌شب صبر کنیم.
    """
    license_row = db.get_license(license_id)
    if license_row is None:
        return None
    if license_row["status"] != licenses.STATUS_ACTIVE:
        return license_row
    if licenses.seconds_left(license_row) > 0:
        return license_row

    updated = licenses.mark_expired(db, license_row)
    provisioning.deactivate_license(db, license_id, purge_data=False,
                                    supervisor=supervisor, reason="expired (on-demand check)")
    if notify:
        _use_recipient_language(db, license_row["user_id"])
        notify(int(license_row["user_id"]), _expired_text(updated))
    return updated


# ---------------------------------------------------------------------------
# متن پیام‌ها
# ---------------------------------------------------------------------------

def _fmt_date(timestamp):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(timestamp)))


def _reminder_text(license_row, left):
    if left <= 0:
        when = i18n.t("reminder_when_today")
    elif left == 1:
        when = i18n.t("reminder_when_tomorrow")
    else:
        when = i18n.t("reminder_when_days", days=left)
    return i18n.t("reminder_title") + i18n.t(
        "reminder_body", key=license_row["key"], when=when,
        date=_fmt_date(license_row["expires_at"]))


def _expired_text(license_row):
    grace = license_row["grace_until"]
    grace_note = ""
    if grace:
        days = max(1, int((int(grace) - time.time()) // 86400))
        grace_note = i18n.t("expired_grace", days=days)
    return i18n.t("expired_notice", key=license_row["key"], grace=grace_note)


def _purged_text(license_row):
    return i18n.t("purged_notice", key=license_row["key"])

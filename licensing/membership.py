"""
عضویت اجباری در کانال رسمی تلگرام.

## قاعده

  * کاربری که از کانال رسمی بیرون بره، همون لحظه پیام می‌گیره.
  * اگه تا `channel_grace_hours` (پیش‌فرض ۲۴ ساعت) برنگرده، **همه‌ی**
    لایسنس‌های فعالش `paused` می‌شن: ربات‌های تیم‌تاکش خاموش می‌شن و ربات
    شخصیِ تلگرامش هم به هیچ درخواستی جواب نمی‌ده.
  * به‌محض برگشتن به کانال، همه‌چیز خودکار برمی‌گرده.

## چرا وضعیت جدید (paused) و نه suspended

suspended را ادمین دستی می‌ذاره، به دلیل‌های دیگه (پرداخت مشکوک، سوءاستفاده).
اگه برگشتن به کانال suspended رو هم برمی‌داشت، کافی بود مشتریِ معلق‌شده یه
بار leave و join کنه تا تعلیقش خودبه‌خود برداشته بشه. paused فقط از همین
ماژول ست می‌شه و فقط همین ماژول برش می‌داره.

## چرا ربات‌های روشن ثبت می‌شن

سوپروایزر فقط نمونه‌های لایسنس‌های `active` رو اجرا نگه می‌داره و موقع
خاموش‌کردن وضعیت نمونه رو `stopped` می‌کنه. پس برگشتنِ لایسنس به active
به‌تنها ربات رو روشن نمی‌کنه -- و نباید هم همه‌ی stopped ها رو روشن کرد،
چون رباتی که مشتری خودش عمداً خاموش کرده هم stopped است. لیستِ ربات‌هایی
که *موقع توقف* روشن بودن نگه داشته می‌شه و فقط همون‌ها برمی‌گردن.
"""

import json
import time

from core import logging_setup
from licensing import config
from licensing import licenses

#: وضعیت‌هایی از getChatMember که یعنی «عضوه».
MEMBER_STATUSES = frozenset({"creator", "owner", "administrator", "member"})

#: وضعیت نمونه‌هایی که سوپروایزر اجراشون می‌کنه (db.runnable_instances).
_RUNNABLE_INSTANCE_STATUSES = ("created", "running", "crashed")


def required_channel(db=None):
    """
    @username یا شناسه‌ی عددی کانال. خالی یعنی این قابلیت خاموشه.

    اول از تنظیمات دیتابیس (که ادمین از داخل تلگرام عوضش می‌کنه)، بعد از
    کانفیگ.
    """
    value = None
    if db is not None:
        try:
            value = db.get_setting("required_channel")
        except Exception:
            value = None
    if value is None:
        value = config.get("required_channel")
    return str(value or "").strip()


def enabled(db=None):
    return bool(required_channel(db))


def grace_seconds():
    try:
        hours = float(config.get("channel_grace_hours", 24))
    except (TypeError, ValueError):
        hours = 24.0
    return int(max(hours, 0.0) * 3600)


def join_url(channel):
    """لینکی که دکمه‌ی «عضو شو» بهش می‌ره، یا None برای کانال خصوصی."""
    channel = str(channel or "").strip()
    if channel.startswith("@"):
        return "https://t.me/" + channel[1:]
    if channel.startswith("https://") or channel.startswith("http://"):
        return channel
    return None


def is_member_status(status, is_member=None):
    """
    restricted فقط وقتی عضو حسابه که is_member درست باشه؛ left و kicked هیچ‌وقت.
    """
    status = str(status or "").lower()
    if status in MEMBER_STATUSES:
        return True
    if status == "restricted":
        return bool(is_member)
    return False


# -------------------------------------------------------------- وضعیت کاربر

def is_out(db, user_id):
    """کاربر الان بیرون از کاناله (از دید آخرین چیزی که دیدیم)؟"""
    if not enabled(db):
        return False
    row = db.get_user(int(user_id))
    return bool(row is not None and row["channel_left_at"])


def mark_left(db, user_id, now=None):
    """
    ثبت می‌کنه که کاربر بیرونه. True فقط وقتی *تازه* بیرون رفته -- یعنی باید
    خبرش داده بشه. دفعه‌های بعد False، تا هر ساعت پیام تکراری نره.
    """
    now = int(now if now is not None else time.time())
    row = db.get_user(int(user_id))
    if row is None or row["channel_left_at"]:
        return False
    db._execute("UPDATE users SET channel_left_at = ?, channel_warned_at = ? "
                "WHERE telegram_id = ?", (now, now, int(user_id)))
    db.log_event("channel_left", user_id=int(user_id))
    return True


def mark_joined(db, user_id):
    """ثبت می‌کنه که کاربر برگشته. True یعنی واقعاً بیرون بوده."""
    row = db.get_user(int(user_id))
    if row is None or not row["channel_left_at"]:
        return False
    db._execute("UPDATE users SET channel_left_at = NULL, channel_warned_at = NULL "
                "WHERE telegram_id = ?", (int(user_id),))
    db.log_event("channel_joined", user_id=int(user_id))
    return True


def users_to_pause(db, now=None):
    """کاربرهایی که مهلت برگشتنشون تموم شده و هنوز لایسنس فعال دارن."""
    now = int(now if now is not None else time.time())
    cutoff = now - grace_seconds()
    rows = db.query(
        "SELECT DISTINCT u.telegram_id FROM users u "
        "JOIN licenses l ON l.user_id = u.telegram_id "
        "WHERE u.channel_left_at IS NOT NULL AND u.channel_left_at <= ? "
        "AND l.status = ?",
        (cutoff, licenses.STATUS_ACTIVE),
    )
    return [int(row[0]) for row in rows]


def users_to_check(db):
    """
    کاربرهایی که عضویتشون باید هر از گاهی واقعاً از تلگرام پرسیده بشه: هر
    کسی لایسنس فعال یا متوقف داره. رویدادِ leave/join ممکنه از دست بره
    (ربات خاموش بوده، یا کاربر قبل از روشن‌شدن این قابلیت رفته).
    """
    rows = db.query(
        "SELECT DISTINCT user_id FROM licenses WHERE status IN (?, ?)",
        (licenses.STATUS_ACTIVE, licenses.STATUS_PAUSED),
    )
    return [int(row[0]) for row in rows]


# --------------------------------------------------------- توقف و برگشت

def _paused_instances_key(license_id):
    return f"channel_paused_instances:{int(license_id)}"


def pause_user(db, user_id, supervisor=None):
    """
    همه‌ی لایسنس‌های فعالِ کاربر رو paused می‌کنه و ربات‌هاشون رو خاموش.

    خروجی: لیست ردیف‌های لایسنسی که متوقف شدن.
    """
    paused = []
    for license_row in db.licenses_by_user(int(user_id)):
        if license_row["status"] != licenses.STATUS_ACTIVE:
            continue
        license_id = int(license_row["id"])

        running = [inst for inst in db.instances_by_license(license_id)
                   if inst["status"] in _RUNNABLE_INSTANCE_STATUSES]
        # قبل از هر خاموش‌کردنی ثبت می‌شه؛ اگه وسط کار قطع بشه، برگشت هنوز
        # می‌دونه کدوم‌ها رو روشن کنه.
        db.set_setting(_paused_instances_key(license_id),
                       json.dumps([int(inst["id"]) for inst in running]))

        updated = licenses.pause(db, license_id)
        _refresh_files(db, updated)
        for inst in running:
            if supervisor is not None:
                try:
                    supervisor.stop(inst["slug"])
                except Exception:
                    logging_setup.log_exception(f"stopping {inst['slug']} for channel pause")
        paused.append(updated)
    return paused


def resume_user(db, user_id, supervisor=None):
    """
    لایسنس‌های paused کاربر رو برمی‌گردونه و فقط ربات‌هایی رو روشن می‌کنه که
    موقع توقف روشن بودن. لایسنسی که وسط توقف منقضی شده مسیر عادی انقضا رو
    می‌ره، نه active.

    خروجی: لیست ردیف‌های لایسنسی که عوض شدن.
    """
    changed = []
    for license_row in db.licenses_by_user(int(user_id)):
        if license_row["status"] != licenses.STATUS_PAUSED:
            continue
        license_id = int(license_row["id"])
        updated = licenses.unpause(db, license_id)
        _refresh_files(db, updated)

        key = _paused_instances_key(license_id)
        try:
            instance_ids = set(json.loads(db.get_setting(key) or "[]"))
        except ValueError:
            instance_ids = set()
        db.set_setting(key, None)

        if updated["status"] == licenses.STATUS_ACTIVE:
            for inst in db.instances_by_license(license_id):
                if int(inst["id"]) not in instance_ids:
                    continue
                db.update_instance(int(inst["id"]), status="created")
                if supervisor is not None:
                    try:
                        supervisor.start_instance(db.get_instance(int(inst["id"])))
                    except Exception:
                        logging_setup.log_exception(f"starting {inst['slug']} after channel rejoin")
        changed.append(updated)
    return changed


def _refresh_files(db, license_row):
    """license.json ها وضعیت جدید رو بگیرن، تا ربات روشن‌شده هم بلاک بشه."""
    try:
        from licensing import provisioning
        provisioning.refresh_license_files(db, license_row)
    except Exception:
        logging_setup.log_exception(f"refreshing licence files for {license_row['id']}")

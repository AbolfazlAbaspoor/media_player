"""
منطق لایسنس: ساخت، تمدید، انقضا، فعال/غیرفعال‌سازی، و امکانات.

## زمان انقضا دقیقاً از لحظه‌ی خرید حساب می‌شه

انقضا یه **timestamp دقیق** است (لحظه‌ی تأیید پرداخت + تعداد ماه)، نه
«آخر روز». چک شبانه فقط یه جاروی پشتیبانه، نه منبع حقیقت -- یعنی:

  * هر بار که ربات بالا میاد یا لایسنس خونده می‌شه، انقضا لحظه‌ای چک می‌شه.
  * چک شبانه (ساعت ۱۲ شب) اون‌هایی رو که در طول روز منقضی شدن جمع می‌کنه و
    لاین صداشون رو می‌بنده.

این ترکیب همون چیزیه که خواسته شده: «هر شب ساعت ۱۲ بررسی می‌کنیم» + «ساعت
بررسی از وقتی ربات خریداری می‌شه».

## مهلت (grace)

بعد از انقضا لایسنس فوراً `expired` می‌شه و ربات‌ها بالا نمی‌آن، ولی
لاین صدا و دیتا تا `grace_days` روز نگه داشته می‌شن. اگه کاربر توی این
مدت تمدید کنه، همه‌چیز سر جای خودش برمی‌گرده؛ وگرنه پاک می‌شه. حذف
داده‌ی مشتری یه کار برگشت‌ناپذیره و نباید همون ثانیه‌ی اول انجام بشه.
"""

import os
import secrets
import time

from licensing import catalog
from licensing import i18n
from licensing.db import json_list
from core import paths

# ماه تجاری = ۳۰ روز. عمداً ثابت و ساده، تا فاکتور و انقضا قابل پیش‌بینی
# باشن (ماه شمسی/میلادی طول متغیر داره و باعث سوال «چرا ۲ روز کمتر شد؟»
# می‌شه).
MONTH_SECONDS = 30 * 24 * 3600

STATUS_ACTIVE = "active"
STATUS_EXPIRED = "expired"
STATUS_SUSPENDED = "suspended"
STATUS_REVOKED = "revoked"
#: عضو کانال رسمی نیست. فقط licensing/membership.py ست و برش می‌داره --
#: برخلاف suspended که ادمین دستی می‌ذاره و نباید با join برداشته بشه.
STATUS_PAUSED = "paused"

_KEY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # بدون I/O/0/1 که با هم قاطی می‌شن


def generate_key():
    """کلید لایسنس خوانا: TT-XXXX-XXXX-XXXX."""
    groups = ["".join(secrets.choice(_KEY_ALPHABET) for _ in range(4)) for _ in range(3)]
    return "TT-" + "-".join(groups)


def unique_key(db):
    for _attempt in range(50):
        key = generate_key()
        if db.get_license_by_key(key) is None:
            return key
    raise RuntimeError("could not generate a unique licence key")


# ---------------------------------------------------------------------------
# ساخت و تمدید
# ---------------------------------------------------------------------------

def create_from_order(db, order, starts_at=None):
    """
    یه لایسنس تازه از روی یه سفارش تأییدشده می‌سازه.

    اگه سفارش «تمدید» باشه (kind='renew' با license_id)، به‌جای ساخت
    لایسنس جدید، همون لایسنس تمدید می‌شه -- وگرنه مشتری با هر تمدید یه
    کلید جدید می‌گرفت و باید همه‌ی ربات‌هاش رو دوباره می‌ساخت.
    """
    now = int(starts_at or time.time())
    features = catalog.expand_features(json_list(order["features"]))
    months = int(order["months"])

    if order["kind"] == "renew" and order["license_id"]:
        return renew(db, int(order["license_id"]), months,
                     order_id=int(order["id"]), extra_features=features,
                     max_bots=int(order["bots"]), max_users=int(order["users"]))

    if order["kind"] == "addon" and order["license_id"]:
        return add_features(db, int(order["license_id"]), features,
                            order_id=int(order["id"]),
                            max_bots=int(order["bots"]), max_users=int(order["users"]))

    license_row = db.create_license(
        key=unique_key(db),
        user_id=int(order["user_id"]),
        order_id=int(order["id"]),
        max_bots=int(order["bots"]),
        max_users=int(order["users"]),
        features=features,
        starts_at=now,
        expires_at=now + months * MONTH_SECONDS,
        status=STATUS_ACTIVE,
    )
    db.log_event("license_created", user_id=int(order["user_id"]),
                 license_id=int(license_row["id"]), order_id=int(order["id"]),
                 detail={"months": months, "features": features,
                         "bots": int(order["bots"]), "users": int(order["users"])})
    return license_row


def renew(db, license_id, months, order_id=None, extra_features=None,
          max_bots=None, max_users=None):
    """
    تمدید. اگه لایسنس هنوز منقضی نشده، از تاریخ انقضای فعلی اضافه می‌شه
    (روزهای باقی‌مانده سوخت نمی‌شن)؛ اگه منقضی شده، از همین لحظه.
    """
    license_row = db.get_license(license_id)
    if license_row is None:
        raise ValueError(f"licence {license_id} not found")

    now = int(time.time())
    base = max(now, int(license_row["expires_at"]))
    new_expiry = base + int(months) * MONTH_SECONDS

    fields = {
        "expires_at": new_expiry,
        "status": STATUS_ACTIVE,
        "grace_until": None,
        "warned_stage": None,
        "deactivated_at": None,
    }
    if order_id:
        fields["order_id"] = order_id
    if max_bots:
        fields["max_bots"] = max(int(license_row["max_bots"]), int(max_bots))
    if max_users:
        fields["max_users"] = max(int(license_row["max_users"]), int(max_users))
    if extra_features:
        merged = list(json_list(license_row["features"]))
        for code in catalog.expand_features(extra_features):
            if code not in merged:
                merged.append(code)
        fields["features"] = merged

    updated = db.update_license(license_id, **fields)
    db.log_event("license_renewed", user_id=int(license_row["user_id"]),
                 license_id=license_id, order_id=order_id,
                 detail={"months": months, "expires_at": new_expiry})
    return updated


def add_features(db, license_id, feature_codes, order_id=None, max_bots=None, max_users=None):
    """اضافه کردن امکانات به یه لایسنس موجود، بدون تغییر تاریخ انقضا."""
    license_row = db.get_license(license_id)
    if license_row is None:
        raise ValueError(f"licence {license_id} not found")

    merged = list(json_list(license_row["features"]))
    added = []
    for code in catalog.expand_features(feature_codes):
        if code not in merged:
            merged.append(code)
            added.append(code)

    fields = {"features": merged}
    if max_bots:
        fields["max_bots"] = max(int(license_row["max_bots"]), int(max_bots))
    if max_users:
        fields["max_users"] = max(int(license_row["max_users"]), int(max_users))
    if order_id:
        fields["order_id"] = order_id

    updated = db.update_license(license_id, **fields)
    db.log_event("license_features_added", user_id=int(license_row["user_id"]),
                 license_id=license_id, order_id=order_id, detail={"added": added})
    return updated


# ---------------------------------------------------------------------------
# وضعیت
# ---------------------------------------------------------------------------

def seconds_left(license_row):
    return int(license_row["expires_at"]) - int(time.time())


def is_valid(license_row):
    """
    همین الان معتبره؟ فقط به ستون status اعتماد نمی‌کنیم و تاریخ رو هم چک
    می‌کنیم -- چون بین دو چک شبانه ممکنه لایسنس منقضی شده باشه ولی status
    هنوز عوض نشده باشه.
    """
    if license_row is None:
        return False
    if license_row["status"] in (STATUS_SUSPENDED, STATUS_REVOKED):
        return False
    return seconds_left(license_row) > 0


def describe_status(license_row):
    """(کد وضعیت، متن فارسی) برای نشون دادن به کاربر."""
    if license_row is None:
        return "none", i18n.t("status_none")
    status = license_row["status"]
    left = seconds_left(license_row)

    if status == STATUS_REVOKED:
        return STATUS_REVOKED, i18n.t("status_revoked")
    if status == STATUS_SUSPENDED:
        return STATUS_SUSPENDED, i18n.t("status_suspended")
    if left <= 0:
        grace = license_row["grace_until"]
        if grace and int(grace) > time.time():
            days = max(1, int((int(grace) - time.time()) // 86400))
            return STATUS_EXPIRED, i18n.t("status_expired_grace", days=days)
        return STATUS_EXPIRED, i18n.t("status_expired")

    days = left // 86400
    hours = (left % 86400) // 3600
    if days > 0:
        return STATUS_ACTIVE, i18n.t("status_active_days", days=days, hours=hours)
    return STATUS_ACTIVE, i18n.t("status_active_hours", hours=hours)


def mark_expired(db, license_row, grace_days=None):
    """
    لایسنس رو منقضی علامت می‌زنه و مهلت پاک‌سازی رو ست می‌کنه. ربات‌ها
    بعد از این بالا نمی‌آن، ولی داده و لاین صدا تا پایان مهلت می‌مونن.
    """
    from licensing import config

    days = grace_days if grace_days is not None else int(config.get("grace_days", 3))
    grace_until = int(time.time()) + days * 86400
    updated = db.update_license(int(license_row["id"]), status=STATUS_EXPIRED,
                                grace_until=grace_until, deactivated_at=int(time.time()))
    db.log_event("license_expired", user_id=int(license_row["user_id"]),
                 license_id=int(license_row["id"]), detail={"grace_until": grace_until})
    return updated


def _deactivate(db, license_id, status, event, reason):
    """suspend/revoke: فقط وضعیت و اسمِ رویدادِ لاگ فرق دارن."""
    license_row = db.update_license(license_id, status=status,
                                    deactivated_at=int(time.time()), notes=reason or None)
    db.log_event(event, user_id=int(license_row["user_id"]),
                 license_id=license_id, detail={"reason": reason})
    return license_row


def suspend(db, license_id, reason=""):
    return _deactivate(db, license_id, STATUS_SUSPENDED, "license_suspended", reason)


def resume(db, license_id):
    license_row = db.get_license(license_id)
    if license_row is None:
        raise ValueError(f"licence {license_id} not found")
    if seconds_left(license_row) <= 0:
        raise ValueError("this licence has expired; renew it instead of lifting the suspension")
    updated = db.update_license(license_id, status=STATUS_ACTIVE, deactivated_at=None)
    db.log_event("license_resumed", user_id=int(license_row["user_id"]), license_id=license_id)
    return updated


def pause(db, license_id, reason="channel"):
    license_row = db.update_license(license_id, status=STATUS_PAUSED,
                                    deactivated_at=int(time.time()))
    db.log_event("license_paused", user_id=int(license_row["user_id"]),
                 license_id=license_id, detail={"reason": reason})
    return license_row


def unpause(db, license_id):
    """
    فقط از paused برمی‌گردونه؛ هر وضعیت دیگه‌ای دست‌نخورده می‌مونه. اگه وسط
    توقف منقضی شده باشه مسیر عادی انقضا (با مهلت) رو می‌ره، نه active.
    """
    license_row = db.get_license(license_id)
    if license_row is None:
        raise ValueError(f"licence {license_id} not found")
    if license_row["status"] != STATUS_PAUSED:
        return license_row
    if seconds_left(license_row) <= 0:
        return mark_expired(db, license_row)
    updated = db.update_license(license_id, status=STATUS_ACTIVE, deactivated_at=None)
    db.log_event("license_unpaused", user_id=int(license_row["user_id"]),
                 license_id=license_id)
    return updated


def revoke(db, license_id, reason=""):
    return _deactivate(db, license_id, STATUS_REVOKED, "license_revoked", reason)


# ---------------------------------------------------------------------------
# فایل لایسنس کنار هر ربات
# ---------------------------------------------------------------------------
# ربات تیم‌تاک هیچ‌وقت به این دیتابیس دست نمی‌زنه. در عوض موقع ساخت/تمدید
# هر نمونه، یه فایل license.json کنار identity.json نوشته می‌شه و
# core/license_gate.py توی خود ربات همون رو می‌خونه. مزیتش: ربات‌ها و
# پلتفرم کاملاً جدا می‌مونن و ربات بدون پلتفرم هم می‌تونه اجرا بشه.

LICENSE_FILE_NAME = "license.json"


def is_unlimited(license_row):
    """
    لایسنسِ خودِ مالک/ادمین («owner self-licence» و «admin unlimited») --
    نه فروخته‌شده. همه‌ی امکانات، حتی امکاناتی که بعداً به کاتالوگ اضافه
    می‌شن، باید خودکار براش باز باشن (sync_unlimited_features).
    """
    notes = str(license_row["notes"] or "").strip().lower()
    return notes.startswith("owner") or "admin unlimited" in notes


def sync_unlimited_features(db):
    """
    امکاناتِ لایسنس‌های نامحدودِ فعال رو با کلِ کاتالوگِ *فعلی* هم‌تراز
    می‌کنه. قبلاً امکانات فقط لحظه‌ی صدور کپی می‌شد، پس هر سرویس/قابلیتِ
    تازه (نماشا، cld، ...) روی لایسنسِ خودِ مالک بسته می‌موند.
    خروجی: ردیف‌های به‌روزشده (فراخوان فایلِ لایسنسِ ربات‌هاشون رو تازه می‌کنه).
    """
    wanted = sorted(catalog.features())
    updated = []
    for row in db.active_licenses():
        if not is_unlimited(row) or sorted(json_list(row["features"])) == wanted:
            continue
        updated.append(db.update_license(int(row["id"]), features=wanted))
    return updated


def license_payload(license_row, instance_row=None):
    features = catalog.expand_features(json_list(license_row["features"]))
    payload = {
        "key": license_row["key"],
        "status": license_row["status"],
        "starts_at": int(license_row["starts_at"]),
        "expires_at": int(license_row["expires_at"]),
        "grace_until": int(license_row["grace_until"]) if license_row["grace_until"] else None,
        "max_bots": int(license_row["max_bots"]),
        "max_users": int(license_row["max_users"]),
        "features": features,
        "services": catalog.allowed_services(features),
        "commands": catalog.allowed_commands(features),
        "issued_at": int(time.time()),
    }
    if instance_row is not None:
        payload["instance"] = {
            "slug": instance_row["slug"],
            "audio_line": instance_row["audio_line"],
        }
    return payload


def write_license_file(bot_dir, license_row, instance_row=None):
    """
    license.json رو اتمی می‌نویسه. نوشتن اتمی مهمه: ربات ممکنه همون لحظه
    فایل رو بخونه و یه فایل نیمه‌نوشته باعث می‌شد همه‌ی امکانات قفل بشن.
    """
    os.makedirs(bot_dir, exist_ok=True)
    path = os.path.join(bot_dir, LICENSE_FILE_NAME)
    paths.write_json_atomic(path, license_payload(license_row, instance_row), indent=2)
    return path


def remove_license_file(bot_dir):
    path = os.path.join(bot_dir, LICENSE_FILE_NAME)
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return False

"""
کدهای هدیه و تخفیف.

## چهار نوع کد

    free_trial   ربات رایگان برای N ساعت (یه لایسنس آزمایشی کامل می‌سازه)
    bonus_time   N ساعت به لایسنس فعالِ موجود اضافه می‌کنه
    percent_off  N درصد تخفیف روی یه سفارش
    amount_off   N دلار تخفیف روی یه سفارش

مثالی که خواسته شده — کد «norooz» که به هر کسی یک ساعت ربات کامل رایگان
می‌ده و ۱۳ روز از لحظه‌ی ساخت معتبره و هر نفر فقط یک بار می‌تونه:

    kind=free_trial, value=1 (ساعت), valid_until=+13 روز,
    per_user_limit=1, per_user_period=ever, features=[] (یعنی همه)

و اگه بخوای هر نفر بتونه *هر روز* یک بار استفاده کنه، فقط
per_user_period=day می‌شه. بقیه‌ی ترکیب‌ها هم همین‌طور از همین چند فیلد
درمی‌آن، بدون نیاز به کد جدید.

## چرا سقف‌ها سه‌تان

سه محدودیت مستقل وجود داره و هر کدوم یه سوءاستفاده‌ی متفاوت رو می‌بنده:

    valid_until      کد بعد از این تاریخ مرده -- برای کمپین‌های فصلی
    per_user_limit   یه نفر چند بار (در هر بازه) -- جلوی تکرار همون آدم
    total_limit      کل دفعات از همه -- سقف هزینه‌ی کمپین

بدون total_limit یه کد لو رفته می‌تونست تا آخر مهلتش سرور رو پر کنه.

## نکته‌ی مهم درباره‌ی redeem

بررسی و ثبت مصرف باید *اتمی* باشن، وگرنه دو پیام هم‌زمان از یه کاربر
می‌تونن هر دو از چک رد بشن و دو بار جایزه بگیرن. برای همین redeem یه قفل
سراسری داره؛ حجم کار این‌قدر کمه که هزینه‌ی قفل اصلاً محسوس نیست.
"""

import threading
import time

from licensing import catalog
from licensing import i18n
from licensing import licenses
from licensing.db import json_list

KIND_FREE_TRIAL = "free_trial"
KIND_BONUS_TIME = "bonus_time"
KIND_PERCENT_OFF = "percent_off"
KIND_AMOUNT_OFF = "amount_off"

KINDS = (KIND_FREE_TRIAL, KIND_BONUS_TIME, KIND_PERCENT_OFF, KIND_AMOUNT_OFF)

PERIODS = {
    "ever": None,
    "day": 86400,
    "week": 7 * 86400,
    "month": 30 * 86400,
}

# سقف منطقی برای کد آزمایشی، تا یه اشتباه تایپی (۱۰۰۰ به‌جای ۱۰) یه ماه
# سرویس رایگان نده.
MAX_TRIAL_HOURS = 24 * 30

_redeem_lock = threading.Lock()


def _fmt_time(timestamp):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(timestamp)))


class PromoError(Exception):
    """خطای قابل‌نمایش به کاربر."""


# ---------------------------------------------------------------------------
# ساخت
# ---------------------------------------------------------------------------

def create(db, code, kind, value, valid_days, features=None, max_bots=1, max_users=1,
           per_user_limit=1, per_user_period="ever", total_limit=0, note=None,
           created_by=None):
    """
    یه کد جدید می‌سازه. اگه کد از قبل باشه PromoError می‌ده -- عمداً
    بازنویسی نمی‌شه، چون یه کد فعالِ پخش‌شده نباید بی‌سروصدا معنیش عوض بشه.
    """
    code = str(code or "").strip().upper()
    if not code or not code.isalnum():
        raise PromoError(i18n.t("promo_err_code_chars"))
    if len(code) > 32:
        raise PromoError(i18n.t("promo_err_code_long"))
    if kind not in KINDS:
        raise PromoError(i18n.t("promo_err_kind", kinds=", ".join(KINDS)))
    if per_user_period not in PERIODS:
        raise PromoError(i18n.t("promo_err_period", periods=", ".join(PERIODS)))

    try:
        value = float(value)
    except (TypeError, ValueError):
        raise PromoError(i18n.t("promo_err_value_number"))
    if value <= 0:
        raise PromoError(i18n.t("promo_err_value_positive"))
    if kind in (KIND_FREE_TRIAL, KIND_BONUS_TIME) and value > MAX_TRIAL_HOURS:
        raise PromoError(i18n.t("promo_err_hours_max", max=MAX_TRIAL_HOURS))
    if kind == KIND_PERCENT_OFF and value > 100:
        raise PromoError(i18n.t("promo_err_percent_max"))

    try:
        valid_days = float(valid_days)
    except (TypeError, ValueError):
        raise PromoError(i18n.t("promo_err_days_number"))
    if valid_days <= 0:
        raise PromoError(i18n.t("promo_err_days_positive"))

    if db.get_promo(code) is not None:
        raise PromoError(i18n.t("promo_err_exists", code=code))

    now = int(time.time())
    return db.create_promo(
        code=code, kind=kind, value=value,
        features=catalog.expand_features(features or []),
        valid_from=now, valid_until=now + int(valid_days * 86400),
        max_bots=max(1, int(max_bots)), max_users=max(1, int(max_users)),
        per_user_limit=max(1, int(per_user_limit)), per_user_period=per_user_period,
        total_limit=max(0, int(total_limit)), note=note, created_by=created_by,
    )


def deactivate(db, code):
    promo = db.get_promo(code)
    if promo is None:
        raise PromoError(i18n.t("promo_err_unknown"))
    db.update_promo(code, active=0)
    return db.get_promo(code)


# ---------------------------------------------------------------------------
# بررسی
# ---------------------------------------------------------------------------

def validate(db, code, user_id):
    """
    (promo_row, error_text). یکی از دوتا None است. error_text متن فارسیِ
    آماده برای نشون دادن به کاربره.
    """
    code = str(code or "").strip().upper()
    if not code:
        return None, i18n.t("promo_err_empty")

    promo = db.get_promo(code)
    if promo is None:
        return None, i18n.t("promo_err_invalid")
    if not promo["active"]:
        return None, i18n.t("promo_err_disabled")

    now = int(time.time())
    if now < int(promo["valid_from"]):
        return None, i18n.t("promo_err_not_started")
    if now > int(promo["valid_until"]):
        return None, i18n.t("promo_err_expired")

    total_limit = int(promo["total_limit"] or 0)
    if total_limit and int(promo["used_count"] or 0) >= total_limit:
        return None, i18n.t("promo_err_full")

    period_seconds = PERIODS.get(promo["per_user_period"])
    since = (now - period_seconds) if period_seconds else None
    used = len(db.redemptions_by_user(code, user_id, since=since))
    limit = int(promo["per_user_limit"] or 1)
    if used >= limit:
        if period_seconds is None:
            return None, i18n.t("promo_err_used_ever")
        return None, i18n.t("promo_err_used_period",
                            period=i18n.t(f"promo_period_{promo['per_user_period']}"))

    return promo, None


def describe(promo):
    """یه خط توضیح فارسی از کاری که کد می‌کنه."""
    kind, value = promo["kind"], float(promo["value"])
    features = json_list(promo["features"])
    if features:
        separator = "، " if i18n.get_language() == "fa" else ", "
        scope = separator.join(catalog.feature_title(c) for c in features)
    else:
        scope = i18n.t("promo_scope_all")

    if kind == KIND_FREE_TRIAL:
        return i18n.t("promo_desc_trial", duration=_hours_text(value), scope=scope)
    if kind == KIND_BONUS_TIME:
        return i18n.t("promo_desc_bonus", duration=_hours_text(value))
    if kind == KIND_PERCENT_OFF:
        return i18n.t("promo_desc_percent", percent=int(value))
    if kind == KIND_AMOUNT_OFF:
        return i18n.t("promo_desc_amount", amount=value)
    return kind


def _hours_text(hours):
    hours = float(hours)
    if hours >= 24 and hours % 24 == 0:
        return i18n.t("promo_hours_days", days=int(hours // 24))
    if hours == int(hours):
        return i18n.t("promo_hours_hours", hours=int(hours))
    return i18n.t("promo_hours_hours", hours=hours)


def summary_line(promo):
    """یه خط برای لیست ادمین."""
    now = int(time.time())
    remaining_days = max(0, (int(promo["valid_until"]) - now) // 86400)
    period = promo["per_user_period"]
    per_user = i18n.t("promo_summary_per_user", count=promo["per_user_limit"])
    if period != "ever":
        per_user += i18n.t("promo_summary_per_period",
                             period=i18n.t(f"promo_period_{period}"))
    total = i18n.t("promo_summary_total", count=promo["total_limit"]) if promo["total_limit"] else ""
    status = i18n.t("promo_summary_active" if promo["active"] and now <= int(promo["valid_until"])
                    else "promo_summary_finished")
    return i18n.t("promo_summary_line", code=promo["code"], description=describe(promo),
                  status=status, days=remaining_days, used=promo["used_count"],
                  per_user=per_user, total=total)


# ---------------------------------------------------------------------------
# استفاده
# ---------------------------------------------------------------------------

def redeem(db, code, user_id, supervisor=None):
    """
    کد رو برای این کاربر اعمال می‌کنه.

    خروجی dict:
        {"kind", "message", "license": row|None, "discount": {...}|None}

    برای کدهای تخفیف، لایسنسی ساخته نمی‌شه -- فقط اطلاعات تخفیف برمی‌گرده
    تا موقع ساخت سفارش اعمال بشه.
    """
    with _redeem_lock:
        promo, error = validate(db, code, user_id)
        if error:
            raise PromoError(error)

        kind = promo["kind"]
        features = json_list(promo["features"]) or list(catalog.features())
        hours = float(promo["value"])

        if kind == KIND_FREE_TRIAL:
            license_row = _grant_trial(db, promo, user_id, features, hours)
            db.record_redemption(code, user_id, license_id=int(license_row["id"]),
                                 detail={"kind": kind, "hours": hours})
            db.log_event("promo_redeemed", user_id=user_id,
                         license_id=int(license_row["id"]),
                         detail={"code": promo["code"], "kind": kind, "hours": hours})
            return {
                "kind": kind,
                "license": license_row,
                "discount": None,
                "message": i18n.t(
                    "promo_trial_granted", code=promo["code"],
                    duration=_hours_text(hours), key=license_row["key"],
                    expires=_fmt_time(license_row["expires_at"])),
            }

        if kind == KIND_BONUS_TIME:
            active = [row for row in db.licenses_by_user(user_id) if licenses.is_valid(row)]
            if not active:
                raise PromoError(i18n.t("promo_err_needs_license"))
            target = active[0]
            updated = _add_hours(db, int(target["id"]), hours)
            db.record_redemption(code, user_id, license_id=int(updated["id"]),
                                 detail={"kind": kind, "hours": hours})
            db.log_event("promo_redeemed", user_id=user_id, license_id=int(updated["id"]),
                         detail={"code": promo["code"], "kind": kind, "hours": hours})
            return {
                "kind": kind,
                "license": updated,
                "discount": None,
                "message": i18n.t(
                    "promo_bonus_granted", code=promo["code"],
                    duration=_hours_text(hours), key=updated["key"],
                    expires=_fmt_time(updated["expires_at"])),
            }

        # کدهای تخفیف: اینجا فقط تأیید می‌شن؛ ثبت مصرف موقع تأیید سفارش
        # انجام می‌شه (تابع consume_for_order) تا یه کد با سفارشی که هیچ‌وقت
        # پرداخت نشد سوخت نشه.
        return {
            "kind": kind,
            "license": None,
            "discount": {"code": promo["code"], "kind": kind, "value": float(promo["value"])},
            "message": i18n.t("promo_applied", code=promo["code"], description=describe(promo)),
        }


def consume_for_order(db, code, user_id, order_id):
    """
    مصرف یه کد تخفیف، بعد از این‌که سفارشش واقعاً تأیید شد.

    عمداً اینجا ثبت می‌شه نه موقع وارد کردن کد: وگرنه کسی که کد رو وارد
    می‌کرد ولی پرداخت نمی‌کرد، سهمیه‌ش رو می‌سوزوند.
    """
    promo = db.get_promo(code)
    if promo is None:
        return False
    db.record_redemption(code, user_id, order_id=order_id,
                         detail={"kind": promo["kind"], "value": promo["value"]})
    db.log_event("promo_consumed", user_id=user_id, order_id=order_id,
                 detail={"code": promo["code"]})
    return True


def apply_discount(quote, discount):
    """
    تخفیف رو روی یه فاکتور اعمال می‌کنه و *کپی* برمی‌گردونه.

    مبلغ هیچ‌وقت زیر صفر نمی‌ره، و مبلغ تومانی دوباره از مبلغ دلاریِ جدید
    حساب می‌شه (نه از روی عدد قبلی) تا دو مبلغ همیشه با هم بخونن.
    """
    if not discount:
        return quote

    from licensing import pricing

    result = dict(quote)
    total = float(result.get("total_usd") or 0)
    if discount["kind"] == KIND_PERCENT_OFF:
        off = total * float(discount["value"]) / 100.0
    else:
        off = float(discount["value"])
    off = min(off, total)

    result["discount_code"] = discount["code"]
    result["discount_usd"] = round(off, 2)
    result["total_before_discount_usd"] = round(total, 2)
    result["total_usd"] = round(max(0.0, total - off), 2)
    if result.get("usd_rate"):
        result["total_irr"] = pricing.round_irr(result["total_usd"] * result["usd_rate"])
    result["lines"] = list(result.get("lines") or []) + [
        {"title": i18n.t("invoice_discount_line", code=discount["code"]), "usd": -round(off, 2)}
    ]
    return result


# ---------------------------------------------------------------------------
# جایزه‌ی دستی (بدون کد)
# ---------------------------------------------------------------------------

def grant_hours(db, user_id, hours, features=None, max_bots=1, max_users=1,
                reason="admin gift"):
    """
    مستقیم به یه کاربر ساعت جایزه می‌ده، بدون کد.

    اگه لایسنس فعال داشته باشه ساعت بهش اضافه می‌شه؛ وگرنه یه لایسنس
    آزمایشی تازه ساخته می‌شه. این همون چیزیه که «به هر یوزر تلگرام
    N ساعت جایزه بده» لازم داره.
    """
    hours = float(hours)
    if hours <= 0:
        raise PromoError(i18n.t("promo_err_hours_positive"))

    db.upsert_user(user_id)
    active = [row for row in db.licenses_by_user(user_id) if licenses.is_valid(row)]
    if active:
        updated = _add_hours(db, int(active[0]["id"]), hours)
        db.log_event("bonus_hours", user_id=user_id, license_id=int(updated["id"]),
                     detail={"hours": hours, "reason": reason, "mode": "extended"})
        return updated, "extended"

    fake_promo = {
        "features": features or [],
        "max_bots": max_bots,
        "max_users": max_users,
        "code": reason,
    }
    license_row = _grant_trial(
        db, fake_promo, user_id,
        catalog.expand_features(features or []) or list(catalog.features()),
        hours,
    )
    db.log_event("bonus_hours", user_id=user_id, license_id=int(license_row["id"]),
                 detail={"hours": hours, "reason": reason, "mode": "new"})
    return license_row, "new"


# ---------------------------------------------------------------------------
# داخلی
# ---------------------------------------------------------------------------

def _grant_trial(db, promo, user_id, features, hours):
    """
    یه لایسنس آزمایشیِ ساعتی می‌سازه.

    از همون مسیر همیشگی (سفارش -> لایسنس) عبور می‌کنه تا هیچ مسیر دومی
    توی سیستم لایسنس وجود نداشته باشه؛ فقط تاریخ انقضاش بعدش دقیق ست
    می‌شه، چون create_from_order برحسب ماه کار می‌کنه.
    """
    db.upsert_user(user_id)
    order = db.create_order(
        user_id=user_id, months=1,
        users=max(1, int(promo["max_users"])), bots=max(1, int(promo["max_bots"])),
        features=features, amount_usd=0.0, status="approved", kind="new",
    )
    db.update_order(int(order["id"]), admin_note=f"promo {promo['code']}")
    license_row = licenses.create_from_order(db, db.get_order(int(order["id"])))

    now = int(time.time())
    updated = db.update_license(
        int(license_row["id"]),
        starts_at=now,
        expires_at=now + int(hours * 3600),
        notes=f"trial: {promo['code']}",
    )
    return updated


def _add_hours(db, license_id, hours):
    """
    ساعت به یه لایسنس اضافه می‌کنه.

    از تاریخ انقضای *فعلی* اضافه می‌شه اگه هنوز نگذشته، وگرنه از همین
    لحظه -- همون قاعده‌ای که تمدید ماهانه داره، تا روزهای باقی‌مانده سوخت
    نشن.
    """
    row = db.get_license(license_id)
    if row is None:
        raise PromoError(i18n.t("license_not_found"))
    now = int(time.time())
    base = max(now, int(row["expires_at"]))
    return db.update_license(
        license_id,
        expires_at=base + int(float(hours) * 3600),
        status=licenses.STATUS_ACTIVE,
        grace_until=None,
        warned_stage=None,
        deactivated_at=None,
    )

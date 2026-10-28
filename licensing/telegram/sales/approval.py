"""
تصمیم ادمین روی یه سفارش: تأیید (صدور لایسنس) یا رد.
"""

import time

from core import logging_setup
from licensing import crypto_pay
from licensing import i18n
from licensing import licenses
from licensing import promos
from licensing import provisioning
from licensing.telegram import keyboards as kb
from licensing.telegram import texts as T
from licensing.telegram.sales.common import _db, _notify, _send, _set_user_language


async def issue_order_license(application, order_id, decided_by):
    """
    هسته‌ی تأییدِ سفارش: صدور/تمدید لایسنس، مصرف کد تخفیف، ری‌استارت ربات‌ها و
    خبر دادن به مشتری. هم دکمه‌ی «تأیید» ادمین و هم پرداخت خودکارِ تتر
    (crypto_payment.py) همین یه مسیر رو می‌رن -- تا تأییدِ خودکار و دستی
    هیچ‌وقت از هم جدا نشن.

    decided_by آیدی ادمینه، یا None وقتی سیستم خودش تأیید کرده.
    خروجی: (دلیل، ردیف لایسنس)؛ دلیل یکی از "ok"، "not_found"، "already".
    """
    db = application.bot_data["db"]
    order = db.get_order(order_id)
    if order is None:
        return "not_found", None
    if order["status"] == "approved":
        return "already", None

    license_row = licenses.create_from_order(db, order)
    db.update_order(order_id, status="approved", decided_by=decided_by,
                    decided_at=int(time.time()))
    # اگه این سفارش یه فاکتور تتریِ باز داشت (تأییدِ دستی)، بسته می‌شه.
    crypto_pay.close_for_order(db, order_id)

    note = order["admin_note"] or ""
    if note.startswith("discount:"):
        try:
            promos.consume_for_order(db, note.split(":", 1)[1], int(order["user_id"]), order_id)
        except Exception:
            logging_setup.log_exception("consuming discount code")
    db.log_event("order_approved", user_id=int(order["user_id"]), order_id=order_id,
                 license_id=int(license_row["id"]))

    # اگه تمدید/افزودن امکانات بود، نمونه‌های موجود بلافاصله لایسنس جدید رو
    # می‌بینن -- بدون این، مشتری تمدید می‌کرد ولی ربات همچنان می‌گفت منقضی.
    if order["kind"] in ("renew", "addon"):
        updated = provisioning.refresh_license_files(db, license_row)
        supervisor = application.bot_data.get("supervisor")
        if supervisor is not None:
            for slug in updated:
                try:
                    supervisor.restart(slug)
                except Exception:
                    logging_setup.log_exception(f"restarting {slug} after renewal")

    instances = db.instances_by_license(int(license_row["id"]))
    needs_setup = len(instances) < int(license_row["max_bots"])

    # پیام مشتری با زبان خودش ساخته می‌شه؛ بعدش زبانِ فراخوان برمی‌گرده تا
    # پیام ادمین (یا اعلانِ ادمین‌ها) با زبان ادمین بمونه.
    caller_language = i18n.get_language()
    _set_user_language(db, int(order["user_id"]))
    markup = kb.license_actions(license_row, can_add_bot=True) if needs_setup else None
    text = T.order_approved(license_row, needs_setup)
    i18n.set_language(caller_language)

    await _notify(application, int(order["user_id"]), text, markup)
    return "ok", license_row


async def approve_order(update, context, order_id):
    reason, license_row = await issue_order_license(
        context.application, order_id, update.effective_user.id)
    if reason == "not_found":
        await _send(update, i18n.t("admin_order_not_found"))
    elif reason == "already":
        await _send(update, i18n.t("admin_order_already_approved"))
    else:
        await _send(update, i18n.t("admin_order_approved", order_id=order_id,
                                   key=license_row["key"]))


async def reject_order(update, context, order_id, reason=""):
    db = _db(context)
    order = db.get_order(order_id)
    if order is None:
        await _send(update, i18n.t("admin_order_not_found"))
        return
    db.update_order(order_id, status="rejected", admin_note=reason or None,
                    decided_by=update.effective_user.id, decided_at=int(time.time()))
    db.log_event("order_rejected", user_id=int(order["user_id"]), order_id=order_id,
                 detail={"reason": reason})
    await _notify(context.application, int(order["user_id"]), T.order_rejected(reason))
    await _send(update, i18n.t("admin_order_rejected", order_id=order_id))

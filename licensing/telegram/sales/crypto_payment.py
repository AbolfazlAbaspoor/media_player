"""
پرداخت با تتر: فاکتور، «پرداخت کردم / الان چک کن»، بررسی پس‌زمینه و نمای ادمین.

منطق شبکه و تطبیق توی licensing/crypto_pay.py است (بدون تلگرام)؛ اینجا
فقط چسباندنش به ربات. تأییدِ سفارش هم از همون مسیرِ ادمین می‌ره
(approval.issue_order_license)، نه یه کپیِ جدا.
"""

import asyncio
import time

from core import logging_setup
from licensing import config
from licensing import crypto_pay
from licensing import i18n
from licensing.telegram import keyboards as kb
from licensing.telegram import texts as T
from licensing.telegram.sales.approval import issue_order_license
from licensing.telegram.sales.common import (
    _db,
    _is_admin,
    _notify,
    _notify_admins,
    _send,
    _set_user_language,
    _user_row,
)
from licensing.telegram.sales.purchase import create_cart_order

# فاصله‌ی دو «الان چک کن» از طرف یه کاربر (ثانیه)، تا دکمه API عمومی رو
# زیر بار نبره.
CHECK_COOLDOWN_SECONDS = 10


async def crypto_invoice_start(update, context, order_id=None):
    """
    فاکتور تتری. order_id=None یعنی از فاکتورِ سبد اومده و هنوز سفارشی
    نیست؛ با عدد یعنی کاربر روی سفارشِ کارتِ همین الانش روش رو عوض کرده.
    """
    db = _db(context)
    user_row = _user_row(update, context)

    if not crypto_pay.available():
        await _send(update, i18n.t("crypto_unavailable"), kb.back_to_menu())
        return

    created_here = order_id is None
    if created_here:
        result = await create_cart_order(update, context, "draft", needs_card=False)
        if result is None:
            return
        order = result[0]
    else:
        order = db.get_order(order_id)
        if (order is None or int(order["user_id"]) != int(user_row["telegram_id"])
                or order["status"] not in ("awaiting_receipt", "awaiting_crypto")):
            await _send(update, i18n.t("crypto_order_closed"), kb.back_to_menu())
            return

    try:
        payment = crypto_pay.create_payment(db, order)
    except crypto_pay.CryptoError as e:
        if created_here:
            db.update_order(int(order["id"]), status="cancelled")
        key = "crypto_busy" if isinstance(e, crypto_pay.CryptoBusy) else "crypto_unavailable"
        await _send(update, i18n.t(key), kb.back_to_menu())
        return

    # رسیدِ کارت دیگه معنی نداره: عکسِ بعدی «منتظر رسید نیستیم» می‌گیره.
    context.user_data.pop("awaiting", None)
    context.user_data["pending_order_id"] = int(order["id"])
    await _send(update, T.crypto_invoice(payment), kb.crypto_actions(int(order["id"])))


async def crypto_check_now(update, context, order_id):
    """دکمه‌ی «فرستادم / الان چک کن»: همون بررسیِ پس‌زمینه، همین لحظه."""
    db = _db(context)
    user_row = _user_row(update, context)
    order = db.get_order(order_id)
    payment = db.crypto_payment_for_order(order_id) if order is not None else None
    if (order is None or payment is None
            or int(order["user_id"]) != int(user_row["telegram_id"])
            or order["status"] != "awaiting_crypto" or payment["status"] != "pending"):
        await _send(update, i18n.t("crypto_order_closed"), kb.back_to_menu())
        return

    now = time.time()
    last = float(context.user_data.get("crypto_checked_at", 0))
    if now - last < CHECK_COOLDOWN_SECONDS:
        await _send(update, T.crypto_invoice(payment, i18n.t("crypto_check_cooldown")),
                    kb.crypto_actions(order_id))
        return
    context.user_data["crypto_checked_at"] = now

    result = await crypto_check_pending(context.application)
    payment = db.get_crypto_payment(int(payment["id"]))
    if payment["status"] == "pending":
        note = i18n.t("crypto_check_failed" if result.failed else "crypto_last_checked",
                      time=time.strftime("%H:%M:%S"))
        await _send(update, T.crypto_invoice(payment, note), kb.crypto_actions(order_id))
    elif payment["status"] in ("paid", "approval_failed"):
        await _send(update, i18n.t("crypto_check_paid"), kb.back_to_menu())
    else:
        await _send(update, i18n.t("crypto_order_closed"), kb.back_to_menu())


async def crypto_check_pending(application):
    """
    یه دور بررسی: تطبیق، تأیید سفارش‌ها، اعلان و منقضی‌کردن. هم حلقه‌ی
    پس‌زمینه و هم دکمه‌ی «الان چک کن» همین رو صدا می‌زنن؛ قفل باعث می‌شه دو
    بررسیِ هم‌زمان نوبتی بشن (ادعای تراکنش توی دیتابیس هم اتمیکه، این
    فقط از درخواست‌های اضافه به API جلوگیری می‌کنه).
    """
    db = application.bot_data["db"]
    lock = application.bot_data.setdefault("crypto_lock", asyncio.Lock())
    async with lock:
        result = await asyncio.to_thread(crypto_pay.check_pending, db)
        for payment, transfer in result.matched:
            await _crypto_settle(application, payment, transfer)
        for payment in result.expired:
            await _crypto_notify_expired(application, payment)
    return result


async def _crypto_settle(application, payment, transfer):
    """پرداخت تطبیق خورد: به مشتری خبر بده، سفارش رو تأیید کن، به ادمین‌ها خبر بده."""
    db = application.bot_data["db"]
    order_id, user_id = int(payment["order_id"]), int(payment["user_id"])
    label = crypto_pay.NETWORKS[payment["network"]].label
    amount = crypto_pay.format_amount(payment["amount_micro"])
    tx_hash = payment["tx_hash"]

    _set_user_language(db, user_id)
    await _notify(application, user_id, i18n.t(
        "crypto_paid_user", amount=amount, tx=T.esc(tx_hash[:10] + "…")))
    i18n.set_language(None)

    try:
        reason, license_row = await issue_order_license(application, order_id, None)
    except Exception:
        logging_setup.log_exception(f"approving crypto order {order_id}")
        reason, license_row = "error", None
    if reason == "error":
        db.set_crypto_payment_status(int(payment["id"]), "approval_failed", only_from="paid")

    if reason == "ok":
        result = i18n.t("crypto_result_ok", key=T.esc(license_row["key"]))
    elif reason == "already":
        result = i18n.t("crypto_result_already")
    else:
        result = i18n.t("crypto_result_failed")
    db.log_event("crypto_paid", user_id=user_id, order_id=order_id,
                 detail={"tx": tx_hash, "amount_micro": int(payment["amount_micro"]),
                         "network": payment["network"], "result": reason})
    await _notify_admins(application, i18n.t(
        "crypto_paid_admin", order_id=order_id, amount=amount, network=label,
        tx=_tx_link(payment), result=result))


async def _crypto_notify_expired(application, payment):
    db = application.bot_data["db"]
    _set_user_language(db, int(payment["user_id"]))
    try:
        await _notify(application, int(payment["user_id"]), i18n.t(
            "crypto_expired_user", order_id=int(payment["order_id"])))
    finally:
        i18n.set_language(None)


def _tx_link(payment):
    """هشِ کوتاه‌شده‌ی تراکنش، لینک به اکسپلورر (برای ادمین)."""
    tx_hash = payment["tx_hash"] or ""
    url = crypto_pay.NETWORKS[payment["network"]].tx_url(tx_hash)
    short = T.esc(tx_hash[:10] + "…")
    return f'<a href="{T.esc(url)}">{short}</a>' if url else short


async def admin_crypto_view(update, context, check=False):
    """پنل ادمین: وضعیتِ پیکربندی، پرداخت‌های در انتظار و آخرین دریافتی‌ها."""
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    db = _db(context)

    lines = [i18n.t("admin_crypto_title"), ""]
    reason = crypto_pay.unavailable_reason()
    if reason is None:
        settings = config.crypto_settings()
        lines.append(i18n.t("admin_crypto_on",
                            network=crypto_pay.NETWORKS[settings["network"]].label,
                            address=T.esc(settings["address"])))
    else:
        lines.append(i18n.t("admin_crypto_off", reason=i18n.t(f"admin_crypto_reason_{reason}")))

    if check:
        result = await crypto_check_pending(context.application)
        lines += ["", i18n.t("admin_crypto_checked", matched=len(result.matched),
                             expired=len(result.expired),
                             failed=i18n.t("admin_crypto_check_failed") if result.failed else "")]

    now = int(time.time())
    pending = db.pending_crypto_payments()
    lines += ["", i18n.t("admin_crypto_pending_title", count=len(pending))]
    pending = pending[:15]
    for payment in pending:
        lines.append(i18n.t(
            "admin_crypto_pending_line", order_id=int(payment["order_id"]),
            amount=crypto_pay.format_amount(payment["amount_micro"]),
            minutes=max(0, (int(payment["expires_at"]) - now) // 60),
            user_id=int(payment["user_id"])))

    received = db.recent_crypto_payments(("paid", "approval_failed"), limit=8)
    lines += ["", i18n.t("admin_crypto_received_title")]
    if not received:
        lines.append(i18n.t("admin_crypto_none"))
    for payment in received:
        lines.append(i18n.t(
            "admin_crypto_received_line",
            icon="⚠️" if payment["status"] == "approval_failed" else "✅",
            order_id=int(payment["order_id"]),
            amount=crypto_pay.format_amount(payment["amount_micro"]),
            date=T.fmt_date(payment["paid_at"]), tx=_tx_link(payment)))

    await _send(update, "\n".join(lines),
                kb.admin_crypto([int(p["order_id"]) for p in pending]))

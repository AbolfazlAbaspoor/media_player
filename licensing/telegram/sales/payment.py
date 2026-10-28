"""
رسید پرداخت: گرفتن عکس، بررسی خودکار و فرستادن برای تأیید ادمین.
"""

import asyncio
import time

from telegram.error import TelegramError

from core import logging_setup
from licensing import config
from licensing import i18n
from licensing import pricing
from licensing import receipts
from licensing.telegram import keyboards as kb
from licensing.telegram import texts as T
from licensing.telegram.sales.broadcast import broadcast_capture
from licensing.telegram.sales.common import HTML, _db, _is_admin, _notify, _user_row


async def on_photo(update, context):
    """
    عکس رسید. اگه منتظر رسید نبودیم، یه پیام راهنما می‌دیم -- نه سکوت، چون
    کاربر ممکنه فکر کنه کار کرد.

    یه استثنا: ادمینی که منتظرِ محتوای پیام همگانیه (C1) و عکس فرستاده --
    اون عکس رسید نیست، محتوای پخشه.
    """
    if _is_admin(update) and context.user_data.get("awaiting") == "broadcast_content":
        await broadcast_capture(update, context)
        return

    db = _db(context)
    user_row = _user_row(update, context)
    order_id = context.user_data.get("pending_order_id")

    if context.user_data.get("awaiting") != "receipt" or not order_id:
        # آخرین سفارش منتظر رسید همین کاربر رو پیدا کن؛ ممکنه ربات ری‌استارت
        # شده باشه و user_data پاک شده باشه.
        pending = [row for row in db.orders_by_user(user_row["telegram_id"], limit=5)
                   if row["status"] == "awaiting_receipt"]
        if not pending:
            await update.effective_message.reply_text(
                i18n.t("receipt_not_waiting"), parse_mode=HTML)
            return
        order_id = int(pending[0]["id"])
        context.user_data["pending_order_id"] = order_id

    order = db.get_order(order_id)
    if order is None or order["status"] != "awaiting_receipt":
        await update.effective_message.reply_text(
            i18n.t("receipt_order_closed"), parse_mode=HTML)
        return

    photo = update.effective_message.photo[-1]
    if photo.file_size and photo.file_size > int(config.get("max_receipt_bytes", 8 * 1024 * 1024)):
        await update.effective_message.reply_text(i18n.t("receipt_too_big"))
        return

    await update.effective_message.reply_text(T.RECEIPT_RECEIVED, parse_mode=HTML)

    path = receipts.receipt_path(order_id, ".jpg")
    try:
        telegram_file = await photo.get_file()
        await telegram_file.download_to_drive(path)
    except TelegramError:
        logging_setup.log_exception("downloading receipt")
        await update.effective_message.reply_text(i18n.t("receipt_download_failed"))
        return

    db.update_order(order_id, status="checking", receipt_file_id=photo.file_id,
                    receipt_path=path, receipt_at=int(time.time()))

    # بررسی OCR توی یه ترد جدا: tesseract سنگین و همگامه و نباید حلقه‌ی
    # asyncio (و بقیه‌ی کاربرها) رو قفل کنه.
    known_hashes, known_references, known_phashes = _known_receipt_markers(
        db, exclude_order_id=order_id)
    payment = config.payment_info(db)
    check = await asyncio.to_thread(
        receipts.check,
        path,
        order["amount_irr"],
        order["amount_usd"],
        payment.get("card_number", ""),
        int(order["created_at"]),
        known_hashes,
        known_references,
        known_phashes,
    )

    check_dict = check.as_dict()
    min_score = float(config.get("receipt_min_score", 0.5))
    status = "admin_review" if check.score >= min_score else "check_failed"

    db.update_order(order_id, status=status, check_verdict=check.verdict,
                    check_score=check.score, check_summary=check.summary())
    db.log_event("receipt_checked", user_id=int(order["user_id"]), order_id=order_id,
                 detail=check_dict)

    context.user_data.pop("awaiting", None)

    if check.duplicate_of:
        await update.effective_message.reply_text(T.receipt_duplicate_user(), parse_mode=HTML)
    elif status == "check_failed":
        await update.effective_message.reply_text(
            T.receipt_check_failed_user(check), parse_mode=HTML)

    order = db.get_order(order_id)
    user = db.get_user(int(order["user_id"]))
    # نرخ امروز هم پاس داده می‌شه تا اگه بین ثبت سفارش و واریز تکون خورده
    # باشه، ادمین بفهمه چرا عدد رسید با انتظارش فرق داره.
    admin_text = T.admin_order_review(
        order, user, check_dict, current_rate=pricing.current_rate(db).get("rate"))
    for admin_id in config.admin_ids():
        try:
            await context.application.bot.send_photo(
                admin_id, photo.file_id, caption=admin_text, parse_mode=HTML,
                reply_markup=kb.admin_order_decision(order_id))
        except TelegramError:
            await _notify(context.application, admin_id, admin_text,
                          kb.admin_order_decision(order_id))


def _known_receipt_markers(db, exclude_order_id=None):
    """
    هش تصویر و شماره پیگیریِ رسیدهای قبلی، برای تشخیص ارسال دوباره.
    فقط سفارش‌هایی که واقعاً رسید داشتن حساب می‌شن.
    """
    hashes, references, phashes = [], [], []
    rows = db.query(
        "SELECT id, check_verdict, check_summary, receipt_path FROM orders "
        "WHERE receipt_path IS NOT NULL AND status IN ('approved', 'admin_review', 'check_failed')"
    )
    for row in rows:
        if exclude_order_id and int(row["id"]) == int(exclude_order_id):
            continue
        for event in db.query(
            "SELECT detail FROM events WHERE kind = 'receipt_checked' AND order_id = ?",
            (int(row["id"]),),
        ):
            import json
            try:
                detail = json.loads(event["detail"] or "{}")
            except ValueError:
                continue
            if detail.get("image_hash"):
                hashes.append(detail["image_hash"])
            if detail.get("reference"):
                references.append(str(detail["reference"]))
            if detail.get("perceptual_hash"):
                # شماره پیگیری همراهش می‌ره: تطبیق تصویری به‌تنهایی کافی
                # نیست و باید با شماره پیگیری تأیید بشه (توضیح توی receipts.py).
                phashes.append({"phash": detail["perceptual_hash"],
                                "reference": detail.get("reference")})
    return hashes, references, phashes

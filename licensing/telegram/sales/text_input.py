"""
ورودی متنی آزاد: بسته به اینکه گفت‌وگو منتظر چیه، به بخش درست فرستاده می‌شه.
"""

from licensing import i18n
from licensing.telegram import keyboards as kb
from licensing.telegram import texts as T
from licensing.telegram.sales.admin_catalog import (
    admin_quote_bots,
    admin_quote_features,
    admin_quote_months,
)
from licensing.telegram.sales.admin_grants import (
    admin_freebot_owner,
    admin_grant_user_id,
    admin_rental_reset_key_text,
)
from licensing.telegram.sales.admin_licenses import admin_license_find_text
from licensing.telegram.sales.admin_pricing_panels import (
    panels_admin_title_en_text,
    panels_admin_title_fa_text,
)
from licensing.telegram.sales.admin_panel import admin_line_add_text
from licensing.telegram.sales.approval import reject_order
from licensing.telegram.sales.broadcast import broadcast_capture
from licensing.telegram.sales.common import _db, _is_admin, _notify, _send, _user_row
from licensing.telegram.sales.cookies import COOKIES_AWAITING, cookies_on_text
from licensing.telegram.sales.personal_bot import personal_bot_set_token
from licensing.telegram.sales.promo_codes import redeem_apply
from licensing.telegram.sales.support import support_submit
from licensing.telegram.sales.wizard import setup_handle_text


async def on_text(update, context):
    db = _db(context)
    user_row = _user_row(update, context)
    if user_row["blocked"]:
        await _send(update, T.BLOCKED)
        return

    text = (update.effective_message.text or "").strip()
    awaiting = context.user_data.get("awaiting")

    if awaiting == "broadcast_content":
        # این یکی جداست: فقط ادمین می‌تونه توش باشه (broadcast_start این
        # حالت رو فقط برای ادمین ست می‌کنه)، و باید محتوا رو دست‌نخورده
        # نگه داره -- پس از این تابع صدا زده می‌شه، نه این‌که متن استخراج بشه.
        if not _is_admin(update):
            context.user_data.pop("awaiting", None)
        else:
            await broadcast_capture(update, context)
            return
    if awaiting in COOKIES_AWAITING:
        # متن را strip نمی‌کنیم: کوکی‌ها با tab جدا شدن و خطِ اول ممکنه tab داشته باشه.
        await cookies_on_text(update, context, update.effective_message.text or "")
        return
    if awaiting == "promo_code":
        await redeem_apply(update, context, text)
        return
    if awaiting == "support":
        await support_submit(update, context, text)
        return
    if awaiting == "pbot_token":
        await personal_bot_set_token(update, context, text)
        return
    if awaiting == "setup":
        await setup_handle_text(update, context, text)
        return
    if awaiting == "freebot_owner":
        await admin_freebot_owner(update, context, text)
        return
    if awaiting == "rental_reset_key":
        await admin_rental_reset_key_text(update, context, text)
        return
    if awaiting == "grant_user_id":
        await admin_grant_user_id(update, context, text)
        return
    if awaiting == "panel_title_fa":
        await panels_admin_title_fa_text(update, context, text)
        return
    if awaiting == "panel_title_en":
        await panels_admin_title_en_text(update, context, text)
        return
    if awaiting == "quote_months":
        await admin_quote_months(update, context, text)
        return
    if awaiting == "quote_bots":
        await admin_quote_bots(update, context, text)
        return
    if awaiting == "quote_features":
        await admin_quote_features(update, context, text)
        return
    if awaiting == "line_add":
        await admin_line_add_text(update, context, text)
        return
    if awaiting == "license_find":
        await admin_license_find_text(update, context, text)
        return
    if awaiting == "reject_reason":
        order_id = context.user_data.pop("reject_order_id", None)
        context.user_data.pop("awaiting", None)
        if order_id:
            await reject_order(update, context, int(order_id), text)
        return
    if awaiting == "ticket_reply":
        ticket_id = context.user_data.pop("reply_ticket_id", None)
        context.user_data.pop("awaiting", None)
        if ticket_id:
            ticket = db.get_ticket(int(ticket_id))
            if ticket:
                db.close_ticket(int(ticket_id), text)
                await _notify(context.application, int(ticket["user_id"]), T.support_reply(text))
                await _send(update, i18n.t("admin_ticket_replied", ticket_id=ticket_id))
        return
    if awaiting == "receipt":
        await _send(update, T.RECEIPT_NOT_A_PHOTO)
        return

    await _send(update, T.UNKNOWN, kb.main_menu(
        bool(db.licenses_by_user(user_row["telegram_id"])), _is_admin(update)))

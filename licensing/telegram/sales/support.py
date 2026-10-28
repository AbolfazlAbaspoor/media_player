"""
پشتیبانی: ساخت تیکت و فرستادنش برای ادمین.
"""

from licensing import i18n
from licensing.telegram import keyboards as kb
from licensing.telegram import texts as T
from licensing.telegram.sales.common import _db, _notify_admins, _send, _user_row


async def support_start(update, context):
    context.user_data["awaiting"] = "support"
    await _send(update, T.SUPPORT_INTRO)


async def support_submit(update, context, text):
    db = _db(context)
    user_row = _user_row(update, context)
    context.user_data.pop("awaiting", None)

    last_order = None
    orders = db.orders_by_user(user_row["telegram_id"], limit=1)
    if orders:
        last_order = int(orders[0]["id"])

    ticket = db.create_ticket(user_row["telegram_id"], text, last_order)
    db.log_event("ticket_created", user_id=user_row["telegram_id"], order_id=last_order,
                 detail={"ticket": int(ticket["id"])})

    await _send(update, T.SUPPORT_SENT, kb.back_to_menu())

    username = f"@{user_row['username']}" if user_row["username"] else "—"
    await _notify_admins(
        context.application,
        i18n.t("support_ticket_admin", ticket_id=ticket["id"],
               username=T.esc(username), user_id=user_row["telegram_id"],
               order_line=(i18n.t("support_ticket_order_line", order_id=last_order)
                           if last_order else ""),
               text=T.esc(text)))

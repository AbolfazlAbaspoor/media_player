"""
خرید: پنل‌های آماده، سفارشی‌ساز، فاکتور و ساخت سفارش.
"""

from licensing import config
from licensing import crypto_pay
from licensing import i18n
from licensing import pricing
from licensing import promos
from licensing.telegram import keyboards as kb
from licensing.telegram import texts as T
from licensing.telegram.sales.common import (
    _cfg_state,
    _db,
    _notify,
    _notify_admins,
    _send,
    _user_row,
)


async def show_panels(update, context):
    db = _db(context)
    await _send(update, T.panels_intro(), kb.panels(db))


async def show_configurator(update, context):
    db = _db(context)
    state = _cfg_state(context)
    quote = pricing.quote(state["months"], state["bots"],
                          state["features"], db=db)
    await _send(update,
                T.configurator(state["months"], state["bots"],
                               state["features"], quote),
                kb.configurator(state["months"], state["bots"]))


async def show_invoice(update, context):
    db = _db(context)
    state = _cfg_state(context)
    quote = pricing.quote(state["months"], state["bots"],
                          state["features"], db=db)
    # کد تخفیفی که کاربر قبلاً وارد کرده هنوز معتبره؟ هر بار دوباره چک
    # می‌شه، چون ممکنه بین دیدن فاکتور و پرداخت منقضی یا پر شده باشه.
    discount = context.user_data.get("discount")
    if discount:
        _promo, error = promos.validate(db, discount["code"], update.effective_user.id)
        if error:
            context.user_data.pop("discount", None)
            discount = None
            await _notify(context.application, update.effective_user.id,
                          i18n.t("promo_removed_invalid", reason=T.esc(error)))
    if discount:
        quote = promos.apply_discount(quote, discount)

    context.user_data["quote"] = quote
    # کارت تنظیم نشده ولی تتر آماده‌ست: دکمه‌ی کارت جایی نمی‌بره، پس نمی‌آد.
    has_card = bool(config.payment_info(db).get("card_number"))
    await _send(update, T.invoice(quote),
                kb.invoice_actions(from_config=True,
                                   card=has_card or not crypto_pay.available()))


async def create_cart_order(update, context, status, needs_card):
    """
    سفارش رو از روی سبد (ماه/ربات/امکانات + کد تخفیف) می‌سازه. مشترک بین
    پرداخت کارتی و تتری.

    خروجی (سفارش، فاکتور)، یا None اگه نشد (پیام به کاربر فرستاده شده).
    needs_card=True یعنی بدون شماره کارت سفارش ساخته نمی‌شه.
    """
    db = _db(context)
    state = _cfg_state(context)
    user_row = _user_row(update, context)

    quote = pricing.quote(state["months"], state["bots"],
                          state["features"], db=db)
    discount = context.user_data.get("discount")
    if discount:
        _promo, error = promos.validate(db, discount["code"], user_row["telegram_id"])
        if error:
            context.user_data.pop("discount", None)
            discount = None
            await _send(update, i18n.t("promo_no_longer_valid", reason=T.esc(error)))
        else:
            quote = promos.apply_discount(quote, discount)
    if needs_card and not config.payment_info(db).get("card_number"):
        await _send(update,
                    i18n.t("payment_no_card"),
                    kb.back_to_menu())
        await _notify_admins(context.application,
                             i18n.t("payment_admin_no_card"))
        return None

    order = db.create_order(
        user_id=user_row["telegram_id"],
        # users=1: ستونِ قدیمیه، دیگه قیمت/سهمیه‌ای نداره و جایی خونده
        # نمی‌شه؛ فقط برای سازگاری با ردیف‌های قدیمی نگه داشته شده.
        months=quote["months"], users=1, bots=quote["bots"],
        features=quote["features"],
        amount_usd=quote["total_usd"], amount_irr=quote["total_irr"],
        usd_rate=quote["usd_rate"], panel_code=state.get("panel_code"),
        kind=state.get("kind", "new"), license_id=state.get("license_id"),
        status=status,
    )
    if discount:
        # کد روی خود سفارش ثبت می‌شه ولی هنوز «مصرف» نشده -- مصرفش موقع
        # تأیید ادمین انجام می‌شه، وگرنه سفارشی که هیچ‌وقت پرداخت نشد،
        # سهمیه‌ی کاربر رو می‌سوزوند.
        db.update_order(int(order["id"]), admin_note=f"discount:{discount['code']}")
    db.log_event("order_created", user_id=user_row["telegram_id"], order_id=int(order["id"]),
                 detail={"usd": quote["total_usd"], "irr": quote["total_irr"],
                         "kind": state.get("kind", "new"),
                         "discount": discount["code"] if discount else None})
    return order, quote


async def create_order_and_ask_payment(update, context):
    db = _db(context)
    result = await create_cart_order(update, context, "awaiting_receipt", needs_card=True)
    if result is None:
        return
    order, quote = result

    context.user_data["awaiting"] = "receipt"
    context.user_data["pending_order_id"] = int(order["id"])

    await _send(update, T.payment_instructions(order, config.payment_info(db), quote),
                kb.payment_actions(int(order["id"])))


async def cancel_order(update, context, order_id):
    db = _db(context)
    order = db.get_order(order_id)
    if order and order["status"] in ("awaiting_receipt", "awaiting_crypto", "draft"):
        db.update_order(order_id, status="cancelled")
        crypto_pay.cancel_for_order(db, order_id)
        db.log_event("order_cancelled", user_id=int(order["user_id"]), order_id=order_id)
    context.user_data.pop("awaiting", None)
    context.user_data.pop("pending_order_id", None)
    await _send(update, i18n.t("order_cancelled"), kb.back_to_menu())

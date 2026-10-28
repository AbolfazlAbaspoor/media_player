"""
کد تخفیف و هدیه: وارد کردن کد توسط کاربر، و ساخت/خاموش‌کردن کد توسط ادمین.
"""

from licensing import i18n
from licensing import promos
from licensing.telegram import keyboards as kb
from licensing.telegram import texts as T
from licensing.telegram.sales.common import (
    _db,
    _is_admin,
    _notify,
    _notify_admins,
    _send,
    _user_row,
)


async def redeem_start(update, context):
    context.user_data["awaiting"] = "promo_code"
    await _send(update, T.PROMO_ASK)


async def redeem_apply(update, context, code):
    db = _db(context)
    user_row = _user_row(update, context)
    context.user_data.pop("awaiting", None)

    try:
        result = promos.redeem(db, code, user_row["telegram_id"])
    except promos.PromoError as e:
        await _send(update, "❌ " + T.esc(str(e)), kb.back_to_menu())
        return

    if result["discount"]:
        # تخفیف فقط نگه داشته می‌شه؛ موقع ساخت سفارش اعمال و بعد از تأیید
        # ادمین مصرف می‌شه.
        context.user_data["discount"] = result["discount"]
        await _send(update, result["message"] + "\n\n" + T.PROMO_PICK_PANEL, kb.panels(db))
        return

    license_row = result["license"]
    markup = kb.license_actions(license_row, can_add_bot=True) if license_row else kb.back_to_menu()
    await _send(update, result["message"], markup)
    await _notify_admins(
        context.application,
        i18n.t("promo_used_by", code=T.esc(str(code).upper()),
               user_id=user_row["telegram_id"]))


async def cmd_promo(update, context):
    """لیست کدها (ادمین)."""
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    rows = _db(context).list_promos()
    if not rows:
        await _send(update, T.PROMO_NONE)
        return
    text = [i18n.t("promo_list_title"), ""]
    for row in rows[:25]:
        text.append("<code>" + T.esc(promos.summary_line(row)) + "</code>")
    await _send(update, "\n".join(text))


def _parse_options(args):
    """گزینه‌های key=value انتهای دستور."""
    options = {}
    for item in args:
        if "=" in item:
            key, value = item.split("=", 1)
            options[key.strip()] = value.strip()
    return options


async def cmd_promoadd(update, context):
    """/promoadd <code> <kind> <value> <days> [key=value ...]"""
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    args = context.args or []
    if len(args) < 4:
        await _send(update, T.PROMO_ADD_HELP)
        return

    options = _parse_options(args[4:])
    features = [f.strip() for f in options.get("features", "").split(",") if f.strip()]

    try:
        promo = promos.create(
            _db(context), args[0], args[1], args[2], args[3],
            features=features,
            # options.get("users", ...) عمداً خونده نمی‌شه: کاربر مدیر
            # دیگه سهمیه نداره، پس یه users= قدیمی فقط بی‌صدا نادیده
            # گرفته می‌شه (max_users پیش‌فرضِ promos.create رو می‌گیره).
            max_bots=int(options.get("bots", 1)),
            per_user_limit=int(options.get("per_user", 1)),
            per_user_period=options.get("period", "ever"),
            total_limit=int(options.get("total", 0)),
            note=options.get("note"),
            created_by=update.effective_user.id,
        )
    except promos.PromoError as e:
        await _send(update, "❌ " + T.esc(str(e)))
        return
    except ValueError:
        await _send(update, "❌ " + i18n.t("promo_err_value_number"))
        return

    await _send(update, i18n.t("promo_created", summary=T.esc(promos.summary_line(promo))))


async def cmd_promooff(update, context):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    args = context.args or []
    if not args:
        await _send(update, i18n.t("promo_usage_off"))
        return
    try:
        promo = promos.deactivate(_db(context), args[0])
    except promos.PromoError as e:
        await _send(update, "❌ " + T.esc(str(e)))
        return
    await _send(update, i18n.t("promo_deactivated", code=T.esc(promo["code"])))


async def cmd_gift(update, context):
    """/gift <user_id> <hours> [features=a,b]"""
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    args = context.args or []
    if len(args) < 2:
        await _send(update, T.GIFT_HELP)
        return

    options = _parse_options(args[2:])
    features = [f.strip() for f in options.get("features", "").split(",") if f.strip()]

    try:
        user_id = int(args[0])
        row, mode = promos.grant_hours(_db(context), user_id, float(args[1]), features=features)
    except (promos.PromoError, ValueError) as e:
        await _send(update, "❌ " + T.esc(str(e)))
        return

    await _send(update, i18n.t(
        "gift_done_extended" if mode == "extended" else "gift_done_new",
        key=T.esc(row["key"]), expires=T.fmt_date(row["expires_at"])))
    await _notify(context.application, user_id, T.gift_received(args[1], row))

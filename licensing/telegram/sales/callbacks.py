"""
مسیریابی دکمه‌های inline به بخش‌های ربات، و گزارش خطای هندلرها.
"""

from telegram.error import TelegramError

from core import logging_setup
from licensing import catalog
from licensing import i18n
from licensing.telegram import keyboards as kb
from licensing.telegram import texts as T
from licensing.telegram.sales.admin_catalog import admin_quote_start, cmd_catalog, cmd_quote
from licensing.telegram.sales.admin_commands import cmd_admin_commands, cmd_card
from licensing.telegram.sales.admin_errors import admin_errors_start
from licensing.telegram.sales.admin_gc import (
    gc_apply,
    gc_attention,
    gc_category,
    gc_confirm,
    gc_start,
)
from licensing.telegram.sales.admin_grants import (
    admin_freebot_self,
    admin_freebot_start,
    admin_grant_start,
    admin_rental_machines,
    admin_rental_reset_days_button,
    admin_rental_reset_force_button,
    admin_rental_reset_start,
    admin_rental_revoke,
    admin_rental_start,
)
from licensing.telegram.sales.admin_licenses import (
    admin_extend_license,
    admin_license_find_start,
    admin_licenses_list,
    admin_resume_button,
    admin_revoke_button,
    admin_revoke_confirm,
    admin_suspend_button,
)
from licensing.telegram.sales.admin_panel import (
    admin_bots,
    admin_line_add_start,
    admin_line_del,
    admin_line_del_confirm,
    admin_line_ensure,
    admin_lines,
    admin_panel,
    admin_pending,
    admin_rate_view,
    admin_send_receipt,
    admin_show_order,
    admin_show_ticket,
    admin_sweep,
    admin_tickets,
)
from licensing.telegram.sales.approval import approve_order, reject_order
from licensing.telegram.sales.broadcast import (
    broadcast_cancel,
    broadcast_pick_audience,
    broadcast_send,
    broadcast_start,
)
from licensing.telegram.sales.cookies import cookies_on_callback
from licensing.telegram.sales.crypto_payment import (
    admin_crypto_view,
    crypto_check_now,
    crypto_invoice_start,
)
from licensing.telegram.sales.common import _cfg_state, _db, _is_admin, _send, _user_row
from licensing.telegram.sales.menu import cmd_help, cmd_start, language_menu, language_set
from licensing.telegram.sales.my_licenses import (
    admin_delete_license,
    instance_action,
    renew_with_months,
    show_instance,
    show_instances,
    show_license,
    show_licenses,
    start_addon,
    start_renew,
)
from licensing.telegram.sales.personal_bot import (
    personal_bot_ask_token,
    personal_bot_delete,
    personal_bot_info,
)
from licensing.telegram.sales.promo_codes import redeem_start
from licensing.telegram.sales.purchase import (
    cancel_order,
    create_order_and_ask_payment,
    show_configurator,
    show_invoice,
    show_panels,
)
from licensing.telegram.sales.reports import admin_report_now
from licensing.telegram.sales.support import support_start
from licensing.telegram.sales.wizard import (
    setup_apply,
    setup_edit_start,
    setup_start,
    setup_use_default,
)


async def on_callback(update, context):
    query = update.callback_query
    try:
        await query.answer()
    except TelegramError:
        pass

    data = query.data or ""
    parts = data.split(":")
    domain = parts[0] if parts else ""
    action = parts[1] if len(parts) > 1 else ""
    arg = parts[2] if len(parts) > 2 else None
    arg2 = parts[3] if len(parts) > 3 else None

    db = _db(context)
    user_row = _user_row(update, context)
    if user_row["blocked"]:
        await _send(update, T.BLOCKED)
        return

    try:
        if domain == "nav":
            if action == "menu":
                await cmd_start(update, context)
            elif action == "help":
                await cmd_help(update, context)

        elif domain == "buy":
            if action == "panels":
                await show_panels(update, context)
            elif action == "custom":
                await show_configurator(update, context)
            elif action == "panel":
                panel = next((p for p in catalog.panels() if p["code"] == arg), None)
                if panel is None:
                    await show_panels(update, context)
                    return
                state = _cfg_state(context)
                state.update({
                    "months": panel["months"], "bots": panel["bots"],
                    "features": catalog.expand_features(panel.get("features", [])),
                    "panel_code": panel["code"], "kind": "new", "license_id": None,
                })
                await show_invoice(update, context)
            elif action == "confirm":
                await create_order_and_ask_payment(update, context)
            elif action == "cancel" and arg:
                await cancel_order(update, context, int(arg))
            elif action == "crypto":
                await crypto_invoice_start(update, context, int(arg) if arg else None)
            elif action == "cchk" and arg:
                await crypto_check_now(update, context, int(arg))

        elif domain == "cfg":
            state = _cfg_state(context)
            limits = catalog.pricing()
            if action == "months" and arg:
                allowed = sorted(int(m) for m in limits.get("duration_multipliers", {})) or [1]
                current = state["months"]
                if arg.startswith("+"):
                    nxt = next((m for m in allowed if m > current), allowed[-1])
                else:
                    nxt = next((m for m in reversed(allowed) if m < current), allowed[0])
                state["months"] = nxt
                await show_configurator(update, context)
            elif action == "bots" and arg:
                delta = 1 if arg.startswith("+") else -1
                state["bots"] = max(1, min(int(limits.get("max_bots", 10)), state["bots"] + delta))
                await show_configurator(update, context)
            elif action == "features":
                await _send(update,
                            i18n.t("features_title") + "\n\n" + i18n.t("features_hint"),
                            kb.feature_picker(state["features"]))
            elif action == "tf" and arg:
                if arg in state["features"]:
                    state["features"].remove(arg)
                else:
                    state["features"].append(arg)
                await _send(update, i18n.t("features_title") + "\n\n" + i18n.t("features_saved"),
                            kb.feature_picker(state["features"]))
            elif action == "tb" and arg:
                members = catalog.expand_features([arg])
                if all(code in state["features"] for code in members):
                    state["features"] = [c for c in state["features"] if c not in members]
                else:
                    for code in members:
                        if code not in state["features"]:
                            state["features"].append(code)
                await _send(update, i18n.t("features_title") + "\n\n" + i18n.t("features_saved"),
                            kb.feature_picker(state["features"]))
            elif action == "tclear":
                state["features"] = []
                await _send(update, i18n.t("features_title") + "\n\n" + i18n.t("features_cleared"),
                            kb.feature_picker(state["features"]))
            elif action in ("done", "review"):
                if state.get("kind") in ("renew", "addon"):
                    await show_invoice(update, context)
                elif action == "done":
                    await show_configurator(update, context)
                else:
                    await show_invoice(update, context)
            elif action == "noop":
                pass

        elif domain == "lic":
            if action == "list":
                await show_licenses(update, context)
            elif action == "show" and arg:
                await show_license(update, context, int(arg))
            elif action == "renew" and arg:
                await start_renew(update, context, int(arg))
            elif action == "renewm" and arg and arg2:
                await renew_with_months(update, context, int(arg), int(arg2))
            elif action == "addon" and arg:
                await start_addon(update, context, int(arg))
            elif action == "del" and arg:
                await admin_delete_license(update, context, int(arg))
            elif action == "delok" and arg:
                await admin_delete_license(update, context, int(arg), confirmed=True)

        elif domain == "inst":
            if action == "list":
                await show_instances(update, context)
            elif action == "of" and arg:
                await show_instances(update, context, int(arg))
            elif action == "show" and arg:
                await show_instance(update, context, int(arg))
            elif action == "edit" and arg:
                await setup_edit_start(update, context, int(arg))
            elif arg:
                await instance_action(update, context, action, int(arg))

        elif domain == "ck":
            if arg:
                await cookies_on_callback(update, context, action, int(arg), arg2)

        elif domain == "setup":
            if action == "start" and arg:
                await setup_start(update, context, int(arg))
            elif action == "apply" and arg:
                await setup_apply(update, context, int(arg))
            elif action == "def" and arg:
                await setup_use_default(update, context, int(arg))

        elif domain == "pbot":
            if action == "info":
                await personal_bot_info(update, context)
            elif action == "set":
                await personal_bot_ask_token(update, context)
            elif action == "del":
                await personal_bot_delete(update, context)

        elif domain == "lang":
            if action == "pick":
                await language_menu(update, context)
            elif action == "set" and arg:
                await language_set(update, context, arg)

        elif domain == "promo":
            if action == "new":
                await redeem_start(update, context)

        elif domain == "sup":
            if action == "new":
                await support_start(update, context)

        elif domain == "agr":
            # ویزاردِ دکمه‌ایِ لایسنسِ هدیه/اجاره‌ای (admin_gift.py).
            if not _is_admin(update):
                await _send(update, T.ADMIN_ONLY)
                return
            from licensing.telegram.sales import admin_gift
            await admin_gift.gift_on_callback(update, context, action, arg)

        elif domain == "pnl":
            # مدیریتِ پنل‌های آماده‌ی فروش (admin_pricing_panels.py).
            if not _is_admin(update):
                await _send(update, T.ADMIN_ONLY)
                return
            from licensing.telegram.sales import admin_pricing_panels
            await admin_pricing_panels.panels_admin_on_callback(update, context, action, arg)

        elif domain == "adm":
            if not _is_admin(update):
                await _send(update, T.ADMIN_ONLY)
                return
            if action == "panel":
                await admin_panel(update, context)
            elif action == "pending":
                await admin_pending(update, context)
            elif action == "show" and arg:
                await admin_show_order(update, context, int(arg))
            elif action == "ok" and arg:
                await approve_order(update, context, int(arg))
            elif action == "no" and arg:
                await reject_order(update, context, int(arg))
            elif action == "noreason" and arg:
                context.user_data["awaiting"] = "reject_reason"
                context.user_data["reject_order_id"] = int(arg)
                await _send(update, i18n.t("admin_ask_reject_reason"))
            elif action == "receipt" and arg:
                await admin_send_receipt(update, context, int(arg))
            elif action == "crypto":
                await admin_crypto_view(update, context)
            elif action == "cryptock":
                await admin_crypto_view(update, context, check=True)
            elif action == "rate":
                await admin_rate_view(update, context, refresh=False)
            elif action == "raterefresh":
                await admin_rate_view(update, context, refresh=True)
            elif action == "card":
                await cmd_card(update, context)
            elif action == "bots":
                await admin_bots(update, context)
            elif action == "freebot":
                await admin_freebot_start(update, context)
            elif action == "freeself":
                await admin_freebot_self(update, context)
            elif action == "rental":
                await admin_rental_start(update, context)
            elif action == "rrev" and arg:
                await admin_rental_revoke(update, context, arg)
            elif action == "rmach" and arg:
                await admin_rental_machines(update, context, arg)
            elif action == "rrstart":
                await admin_rental_reset_start(update, context)
            elif action == "rreset" and arg and arg2:
                await admin_rental_reset_days_button(update, context, arg, arg2)
            elif action == "rresetok" and arg and arg2:
                await admin_rental_reset_force_button(update, context, arg, arg2)
            elif action == "grant":
                await admin_grant_start(update, context)
            elif action == "lics" and arg:
                await admin_licenses_list(update, context, arg, int(arg2 or 0))
            elif action == "licfind":
                await admin_license_find_start(update, context)
            elif action == "ext" and arg and arg2:
                await admin_extend_license(update, context, int(arg), int(arg2))
            elif action == "suspend" and arg:
                await admin_suspend_button(update, context, int(arg))
            elif action == "resume" and arg:
                await admin_resume_button(update, context, int(arg))
            elif action == "revoke" and arg:
                await admin_revoke_confirm(update, context, int(arg))
            elif action == "revokeok" and arg:
                await admin_revoke_button(update, context, int(arg))
            elif action == "catalog":
                await cmd_catalog(update, context)
            elif action == "quote":
                await admin_quote_start(update, context)
            elif action == "errors":
                await admin_errors_start(update, context)
            elif action == "lineadd":
                await admin_line_add_start(update, context)
            elif action == "linedel" and arg:
                await admin_line_del_confirm(update, context, arg)
            elif action == "linedelok" and arg:
                await admin_line_del(update, context, arg)
            elif action == "lineensure":
                await admin_line_ensure(update, context)
            elif action == "lines":
                await admin_lines(update, context)
            elif action == "sweep":
                await admin_sweep(update, context)
            elif action == "report":
                await admin_report_now(update, context)
            elif action == "gc":
                await gc_start(update, context)
            elif action == "gcc" and arg:
                await gc_category(update, context, arg, int(arg2 or 0))
            elif action == "gcd" and arg:
                await gc_confirm(update, context, arg)
            elif action == "gcok" and arg:
                await gc_apply(update, context, arg)
            elif action == "gca":
                await gc_attention(update, context)
            elif action == "tickets":
                await admin_tickets(update, context)
            elif action == "ticket" and arg:
                await admin_show_ticket(update, context, int(arg))
            elif action == "treply" and arg:
                context.user_data["awaiting"] = "ticket_reply"
                context.user_data["reply_ticket_id"] = int(arg)
                await _send(update, i18n.t("admin_ask_reply"))
            elif action == "tclose" and arg:
                db.close_ticket(int(arg))
                await _send(update, i18n.t("admin_ticket_closed", ticket_id=arg))
            elif action == "commands":
                await cmd_admin_commands(update, context)
            elif action == "broadcast":
                await broadcast_start(update, context)
            elif action == "bcast" and arg:
                await broadcast_pick_audience(update, context, arg)
            elif action == "bcastok" and arg:
                await broadcast_send(update, context, arg)
            elif action == "bcastcancel":
                await broadcast_cancel(update, context)

    except Exception:
        logging_setup.log_exception(f"callback {data}")
        await _send(update, i18n.t("unexpected_error"), kb.back_to_menu())


async def on_error(update, context):
    # خطا رو صریح پاس می‌دیم: این هندلر بیرون از except اجرا می‌شه، پس
    # بدون context.error فقط «NoneType: None» توی لاگ می‌نشست.
    logging_setup.log_exception("telegram handler", error=getattr(context, "error", None))

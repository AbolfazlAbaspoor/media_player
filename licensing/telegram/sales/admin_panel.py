"""
پنل ادمین: آمار، صف تأیید، ربات‌ها، لاین‌ها، جارو، نرخ و تیکت‌ها.
"""

import asyncio

from telegram.error import TelegramError

from core import audio_lines
from core import logging_setup
from licensing import i18n
from licensing import pricing
from licensing import provisioning
from licensing.telegram import keyboards as kb
from licensing.telegram import texts as T
from licensing.telegram.sales.background import _run_sweep
from licensing.telegram.sales.common import HTML, _admin_ask, _db, _is_admin, _send, _supervisor


async def admin_panel(update, context):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    db = _db(context)
    stats = db.stats()
    rate_state = pricing.current_rate(db)
    capacity = await asyncio.to_thread(provisioning.capacity_report, db)
    await _send(update, T.admin_panel(stats, rate_state, capacity),
                kb.admin_panel(stats["orders_pending"], stats["tickets_open"]))


async def admin_pending(update, context):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    db = _db(context)
    orders = db.pending_admin_orders()
    if not orders:
        await _send(update, i18n.t("admin_no_pending"),
                    kb.admin_panel(0, db.stats()["tickets_open"]))
        return
    await _send(update, i18n.t("admin_pending_title", count=len(orders)), kb.admin_pending_list(orders))


async def admin_show_order(update, context, order_id):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    db = _db(context)
    order = db.get_order(order_id)
    if order is None:
        await _send(update, i18n.t("admin_order_not_found"))
        return
    user = db.get_user(int(order["user_id"]))
    import json
    check_dict = {"verdict": order["check_verdict"] or "unreadable",
                  "score": order["check_score"] or 0,
                  "notes": [order["check_summary"]] if order["check_summary"] else []}
    for event in db.query(
        "SELECT detail FROM events WHERE kind='receipt_checked' AND order_id=? ORDER BY id DESC LIMIT 1",
        (order_id,),
    ):
        try:
            check_dict = json.loads(event["detail"] or "{}") or check_dict
        except ValueError:
            pass

    text = T.admin_order_review(
        order, user, check_dict, current_rate=pricing.current_rate(db).get("rate"))
    if order["receipt_file_id"]:
        try:
            await context.application.bot.send_photo(
                update.effective_chat.id, order["receipt_file_id"], caption=text,
                parse_mode=HTML, reply_markup=kb.admin_order_decision(order_id))
            return
        except TelegramError:
            pass
    await _send(update, text, kb.admin_order_decision(order_id))


async def admin_send_receipt(update, context, order_id):
    if not _is_admin(update):
        return
    db = _db(context)
    order = db.get_order(order_id)
    if order is None or not order["receipt_file_id"]:
        await _send(update, i18n.t("admin_no_receipt"))
        return
    try:
        await context.application.bot.send_photo(
            update.effective_chat.id, order["receipt_file_id"],
            caption=i18n.t("admin_receipt_caption", order_id=order_id))
    except TelegramError:
        logging_setup.log_exception("sending receipt photo to admin")
        await _send(update, T.UNEXPECTED_ERROR)


async def admin_bots(update, context):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    supervisor = _supervisor(context)
    if supervisor is None:
        await _send(update, i18n.t("no_supervisor"), kb.admin_panel(0, 0))
        return
    status = supervisor.status()
    if not status:
        await _send(update, i18n.t("admin_bots_none"), kb.admin_panel(0, 0))
        return
    lines = [i18n.t("admin_bots_title"), ""]
    for item in status:
        icon = "🟢" if item["alive"] else ("🔴" if item["blocked"] else "⚪️")
        detail = ""
        if item["alive"]:
            detail += i18n.t("admin_bot_running", pid=item["pid"],
                             uptime=T.fmt_duration(item["uptime_seconds"]))
        if item["failures"]:
            detail += i18n.t("admin_bot_failures", count=item["failures"])
        if not item["alive"] and item["last_exit_code"] is not None:
            detail += i18n.t("admin_bot_exit", code=item["last_exit_code"])
        lines.append(i18n.t("admin_bot_line", icon=icon,
                            slug=T.esc(item["slug"]), detail=detail))
    await _send(update, "\n".join(lines), kb.admin_panel(0, 0))


async def admin_lines(update, context):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    lines = await asyncio.to_thread(audio_lines.list_lines)
    text = [i18n.t("admin_lines_title"), ""]
    if not lines:
        text.append(i18n.t("admin_lines_none"))
    for line in lines:
        text.append(
            i18n.t("admin_line_entry",
                   icon="🟢" if line.get("alive") else "🔴",
                   slug=T.esc(line["slug"]),
                   output=T.esc(line.get("output_device")),
                   input=T.esc(line.get("input_device")))
            + (i18n.t("admin_line_owner", owner=T.esc(line.get("owner")))
               if line.get("owner") else "")
        )
    # افزودن/حذف/بازسازیِ لاین (B8) هم همین‌جا -- هر ردیف یه دکمه‌ی حذف
    # داره، بدون این‌که لازم باشه اسمش رو تایپ کنی.
    await _send(update, "\n".join(text), kb.admin_lines_actions(lines))


async def admin_line_add_start(update, context):
    await _admin_ask(update, context, _is_admin(update), _send, "line_add", "admin_line_add_ask")


async def admin_line_add_text(update, context, text):
    if not _is_admin(update):
        return
    context.user_data.pop("awaiting", None)
    parts = (text or "").strip().split(None, 1)
    if not parts:
        await _send(update, i18n.t("admin_line_add_ask"))
        return
    slug, description = parts[0], (parts[1] if len(parts) > 1 else None)
    try:
        line = await asyncio.to_thread(
            audio_lines.create_line, slug, description=description,
            owner=f"telegram admin {update.effective_user.id}")
    except audio_lines.AudioLineError as e:
        # AudioLineError پیامِ خودمونه (کوتاه و امن)، نه یه exception خام.
        await _send(update, i18n.t("admin_line_add_failed", error=T.esc(str(e))), kb.admin_back())
        return
    _db(context).log_event("line_added", user_id=update.effective_user.id,
                           detail={"slug": line["slug"]})
    await _send(update, i18n.t("admin_line_add_done", slug=T.esc(line["slug"]),
                               output=T.esc(line["output_device"]),
                               input=T.esc(line["input_device"])),
                kb.admin_back())


async def admin_line_del_confirm(update, context, slug):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    await _send(update, i18n.t("admin_line_del_confirm", slug=T.esc(slug)),
                kb.confirm(f"adm:linedelok:{slug}", "adm:lines", i18n.t("btn_delete_yes")))


async def admin_line_del(update, context, slug):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    removed = await asyncio.to_thread(audio_lines.destroy_line, slug)
    _db(context).log_event("line_deleted", user_id=update.effective_user.id,
                           detail={"slug": slug, "removed": removed})
    await admin_lines(update, context)


async def admin_line_ensure(update, context):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    restored = await asyncio.to_thread(audio_lines.ensure_all_lines)
    await _send(update, i18n.t("admin_line_ensure_done", count=restored), kb.admin_back())


async def admin_sweep(update, context):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    await _send(update, i18n.t("admin_sweep_running"))
    result = await _run_sweep(context.application)
    await _send(update, T.sweep_report(result), kb.admin_panel(0, 0))


async def admin_rate_view(update, context, refresh=False):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    db = _db(context)
    if refresh:
        state = await asyncio.to_thread(pricing.refresh_rate, db)
    else:
        state = pricing.current_rate(db)
    await _send(update, T.admin_rate_report(state), kb.admin_rate())


async def admin_tickets(update, context):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    db = _db(context)
    tickets = db.open_tickets()
    if not tickets:
        await _send(update, i18n.t("admin_tickets_none"), kb.admin_panel(0, 0))
        return
    await _send(update, i18n.t("admin_tickets_title", count=len(tickets)), kb.admin_tickets(tickets))


async def admin_show_ticket(update, context, ticket_id):
    if not _is_admin(update):
        return
    db = _db(context)
    ticket = db.get_ticket(ticket_id)
    if ticket is None:
        await _send(update, i18n.t("admin_ticket_not_found"))
        return
    user = db.get_user(int(ticket["user_id"]))
    username = f"@{user['username']}" if user and user["username"] else "—"
    await _send(update,
                "\n".join([
                    i18n.t("admin_ticket_title", ticket_id=ticket["id"]), "",
                    i18n.t("admin_ticket_from", username=T.esc(username),
                           user_id=ticket["user_id"]),
                    i18n.t("admin_ticket_when", date=T.fmt_date(ticket["created_at"])),
                    "", T.esc(ticket["message"]),
                ]),
                kb.admin_ticket_actions(int(ticket["id"]), int(ticket["user_id"])))

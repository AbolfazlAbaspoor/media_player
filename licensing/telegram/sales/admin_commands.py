"""
دستورهای اسلشیِ ادمین (/rate، /grant، /extend، /suspend، ...).
"""

import asyncio
import time

from licensing import catalog
from licensing import config
from licensing import i18n
from licensing import keys
from licensing import licenses
from licensing import pricing
from licensing import provisioning
from licensing.telegram import keyboards as kb
from licensing.telegram import texts as T
from licensing.telegram.sales.common import (
    _db,
    _is_admin,
    _notify,
    _send,
    _supervisor,
    _use_user_language,
)


# «/rate auto» یعنی نرخ دستی رو بردار و برگرد به نرخ خودکار. متن راهنما
# «auto» رو پیشنهاد می‌ده، ولی معادل فارسی هم قبول می‌شه چون ادمین ممکنه
# به زبان خودش تایپ کنه.
_RATE_AUTO_WORDS = {"auto", "automatic", "خودکار", "اتوماتیک"}


async def cmd_rate(update, context):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    db = _db(context)
    args = context.args or []
    if not args:
        state = await asyncio.to_thread(pricing.refresh_rate, db)
        await _send(update, T.admin_rate_report(state), kb.admin_rate())
        return
    if args[0].lower() in _RATE_AUTO_WORDS:
        db.set_setting("usd_rate_manual", None)
        state = await asyncio.to_thread(pricing.refresh_rate, db)
        await _send(update, i18n.t("rate_manual_cleared") + "\n\n" + T.admin_rate_report(state))
        return
    try:
        value = int(float(args[0].replace(",", "").replace("\u066c", "")))
    except ValueError:
        await _send(update, i18n.t("rate_bad_number"))
        return
    if not pricing.RATE_SANITY_MIN <= value <= pricing.RATE_SANITY_MAX:
        await _send(update, i18n.t("rate_out_of_range",
                                   min=f"{pricing.RATE_SANITY_MIN:,}",
                                   max=f"{pricing.RATE_SANITY_MAX:,}"))
        return
    db.set_setting("usd_rate_manual", str(value))
    db.log_event("rate_set_manual", user_id=update.effective_user.id, detail={"rate": value})
    await _send(update, T.admin_rate_report(pricing.current_rate(db)), kb.admin_rate())


async def cmd_card(update, context):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    db = _db(context)
    raw = " ".join(context.args or [])
    if not raw:
        info = config.payment_info(db)
        dash = i18n.t("dash")
        await _send(update, i18n.t(
            "card_current",
            number=T.esc(info["card_number"] or dash),
            holder=T.esc(info["card_holder"] or dash),
            bank=T.esc(info["card_bank"] or dash)))
        return
    parts = [p.strip() for p in raw.split("|")]
    db.set_setting("payment_card_number", parts[0])
    if len(parts) > 1:
        db.set_setting("payment_card_holder", parts[1])
    if len(parts) > 2:
        db.set_setting("payment_card_bank", parts[2])
    db.log_event("card_updated", user_id=update.effective_user.id)
    await _send(update, i18n.t("card_updated"))


async def do_grant(context, admin_id, user_id, months, bots, features, days=None):
    """
    صدورِ دستیِ یه لایسنسِ رایگان (بدون سفارش/فاکتور واقعی). هم /grant هم
    ویزاردِ دکمه‌ایِ «🎁 صدورِ لایسنس» (admin_gift.py) همینو صدا می‌زنن.

    days (اختیاری): مدتِ دقیق به روز. سفارش‌ها ماه‌محورن، پس months برای
    سابقه‌ی سفارش می‌مونه ولی انقضای لایسنس همون روزِ دقیق می‌شه -- تا
    ادمین بتونه مثلاً ۳ روز یا ۴۵ روز هدیه بده، نه فقط مضربِ ۳۰.

    خروجی: license_row. مشتری خودکار خبردار می‌شه.
    """
    db = _db(context)
    db.upsert_user(int(user_id))
    order = db.create_order(user_id=int(user_id), months=int(months), users=1, bots=int(bots),
                            features=features or [], amount_usd=0.0, status="approved",
                            kind="new")
    db.update_order(int(order["id"]), decided_by=admin_id,
                    decided_at=int(time.time()), admin_note="granted manually")
    license_row = licenses.create_from_order(db, db.get_order(int(order["id"])))
    if days:
        license_row = db.update_license(
            int(license_row["id"]),
            expires_at=int(license_row["starts_at"]) + int(days) * 86400)
    _use_user_language(context, int(user_id))
    await _notify(context.application, int(user_id), T.order_approved(license_row, True),
                  kb.license_actions(license_row, can_add_bot=True))
    return license_row


async def cmd_grant(update, context):
    """/grant <user_id> <months> [bots] [feature_codes...]"""
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    args = context.args or []
    if len(args) < 2:
        await _send(update, i18n.t("admin_usage_grant",
                                   features=", ".join(catalog.features())))
        return
    try:
        user_id = int(args[0])
        months = int(args[1])
        bots = int(args[2]) if len(args) > 2 else 1
    except ValueError:
        await _send(update, i18n.t("admin_bad_number"))
        return

    # سازگاری با فرم قدیمی: /grant <user_id> <months> <bots> <users> [features...]
    # اگه آرگومان بعدی هم عددی باشه، «تعداد کاربر» قدیمیه -- نادیده گرفته
    # می‌شه (کاربر مدیر دیگه سهمیه/قیمت نداره).
    feature_args = args[3:]
    legacy_users = bool(feature_args) and feature_args[0].lstrip("-").isdigit()
    if legacy_users:
        feature_args = feature_args[1:]
    features = catalog.expand_features(feature_args) if feature_args else []

    license_row = await do_grant(context, update.effective_user.id, user_id, months, bots, features)

    text = i18n.t("admin_license_granted", key=license_row["key"],
                  user_id=user_id, months=months)
    if legacy_users:
        text += "\n" + i18n.t("admin_grant_users_ignored")
    await _send(update, text)


async def do_extend(context, license_row, months):
    """
    تمدید + رفرش فایل لایسنسِ همه‌ی ربات‌هاش + ری‌استارت + خبردادن به
    مشتری. هم /extend هم دکمه‌های +۱/+۳/+۱۲ روی کارتِ لایسنس (B8) همینو
    صدا می‌زنن، تا دو نسخه از یه منطق نباشه.
    """
    db = _db(context)
    updated = licenses.renew(db, int(license_row["id"]), int(months))
    slugs = await asyncio.to_thread(provisioning.refresh_license_files, db, updated)
    supervisor = _supervisor(context)
    if supervisor is not None:
        for slug in slugs:
            await asyncio.to_thread(supervisor.restart, slug)
    _use_user_language(context, int(updated["user_id"]))
    await _notify(context.application, int(updated["user_id"]),
                  i18n.t("license_renewed_notice", key=updated["key"],
                         date=T.fmt_date(updated["expires_at"])))
    return updated


async def _license_by_key_arg(update, db, key):
    """ردیفِ لایسنس از روی کلیدِ تایپ‌شده؛ اگه نبود همین‌جا جواب می‌ده و None."""
    license_row = db.get_license_by_key(key.strip().upper())
    if license_row is None:
        await _send(update, i18n.t("license_not_found"))
    return license_row


async def cmd_extend(update, context):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    args = context.args or []
    if len(args) < 2:
        await _send(update, i18n.t("admin_usage_extend"))
        return
    db = _db(context)
    license_row = await _license_by_key_arg(update, db, args[0])
    if license_row is None:
        return
    try:
        months = int(args[1])
    except ValueError:
        await _send(update, i18n.t("admin_bad_months"))
        return

    updated = await do_extend(context, license_row, months)
    await _send(update, i18n.t("admin_license_extended", key=updated["key"],
                               date=T.fmt_date(updated["expires_at"])))


async def do_license_status_action(context, license_row, action, reason=""):
    """
    suspend/resume/revoke -- منطقِ واقعی، جدا از این‌که دستورِ متنی صداش
    زده یا دکمه‌ی کارتِ لایسنس (B8). resume روی لایسنسِ منقضی ValueError
    می‌ده (licenses.resume) که صداکننده باید بگیردش.
    """
    db = _db(context)
    license_id = int(license_row["id"])
    supervisor = _supervisor(context)

    if action == "suspend":
        licenses.suspend(db, license_id, reason)
        await asyncio.to_thread(provisioning.deactivate_license, db, license_id,
                                False, supervisor, f"suspended: {reason}")
        _use_user_language(context, int(license_row["user_id"]))
        await _notify(context.application, int(license_row["user_id"]),
                      i18n.t("license_suspended_notice",
                             reason=(i18n.t("notice_reason", reason=T.esc(reason))
                                     if reason else "")))
    elif action == "resume":
        licenses.resume(db, license_id)   # ValueError اگه منقضی شده باشه
        updated = db.get_license(license_id)
        await asyncio.to_thread(provisioning.refresh_license_files, db, updated)
        for instance in db.instances_by_license(license_id):
            if supervisor is not None:
                await asyncio.to_thread(supervisor.start_instance, instance)
        _use_user_language(context, int(license_row["user_id"]))
        await _notify(context.application, int(license_row["user_id"]),
                      i18n.t("license_resumed_notice"))
    elif action == "revoke":
        licenses.revoke(db, license_id, reason)
        await asyncio.to_thread(provisioning.deactivate_license, db, license_id,
                                True, supervisor, f"revoked: {reason}")
        _use_user_language(context, int(license_row["user_id"]))
        await _notify(context.application, int(license_row["user_id"]),
                      i18n.t("license_revoked_notice",
                             reason=(i18n.t("notice_reason", reason=T.esc(reason))
                                     if reason else "")))
    return db.get_license(license_id)


async def _admin_license_action(update, context, action):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    args = context.args or []
    if not args:
        await _send(update, i18n.t("admin_usage_license_action", action=action))
        return
    db = _db(context)
    license_row = await _license_by_key_arg(update, db, args[0])
    if license_row is None:
        return
    reason = " ".join(args[1:])

    if action == "resume":
        try:
            await do_license_status_action(context, license_row, action, reason)
        except ValueError:
            # پیامِ داخلیِ resume() انگلیسیِ خامه؛ به‌جاش کلیدِ ترجمه‌شده.
            await _send(update, i18n.t("admin_resume_expired", key=license_row["key"]))
            return
    else:
        await do_license_status_action(context, license_row, action, reason)

    key_map = {"suspend": "admin_license_suspended", "resume": "admin_license_resumed",
              "revoke": "admin_license_revoked"}
    await _send(update, i18n.t(key_map[action], key=license_row["key"]))


async def cmd_suspend(update, context):
    await _admin_license_action(update, context, "suspend")


async def cmd_resume(update, context):
    await _admin_license_action(update, context, "resume")


async def cmd_revoke(update, context):
    await _admin_license_action(update, context, "revoke")


async def cmd_license_info(update, context):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    args = context.args or []
    if not args:
        await _send(update, i18n.t("admin_usage_license"))
        return
    db = _db(context)
    license_row = await _license_by_key_arg(update, db, args[0])
    if license_row is None:
        return
    instances = db.instances_by_license(int(license_row["id"]), include_removed=True)
    _status, status_text = licenses.describe_status(license_row)
    user = db.get_user(int(license_row["user_id"]))
    owner = f"@{user['username']}" if user and user["username"] else str(license_row["user_id"])
    await _send(update,
                i18n.t("admin_license_owner", owner=T.esc(owner),
                       user_id=license_row["user_id"]) + "\n\n"
                + T.license_card(license_row, status_text, instances))


async def cmd_reply(update, context):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    args = context.args or []
    if len(args) < 2:
        await _send(update, i18n.t("admin_usage_reply"))
        return
    db = _db(context)
    try:
        ticket_id = int(args[0])
    except ValueError:
        await _send(update, i18n.t("admin_bad_ticket_id"))
        return
    ticket = db.get_ticket(ticket_id)
    if ticket is None:
        await _send(update, i18n.t("admin_ticket_not_found"))
        return
    reply = " ".join(args[1:])
    db.close_ticket(ticket_id, reply)
    sent = await _notify(context.application, int(ticket["user_id"]), T.support_reply(reply))
    await _send(update,
                i18n.t("admin_ticket_closed", ticket_id=ticket_id)
                + ("" if sent else i18n.t("admin_ticket_reply_failed")))


async def cmd_say(update, context):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    args = context.args or []
    if len(args) < 2:
        await _send(update, i18n.t("admin_usage_say"))
        return
    try:
        user_id = int(args[0])
    except ValueError:
        await _send(update, i18n.t("admin_bad_id"))
        return
    text = " ".join(args[1:])
    sent = await _notify(context.application, user_id, T.support_reply(text))
    await _send(update, i18n.t("admin_message_sent") if sent else i18n.t("admin_message_failed"))


async def cmd_reload(update, context):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    catalog.reload()
    config.reload()
    i18n.load(force=True)
    await _send(update, i18n.t("admin_reloaded"))


async def cmd_pubkey(update, context):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    try:
        public = await asyncio.to_thread(keys.public_key_b64)
    except keys.SigningUnavailable as e:
        await _send(update, str(e))
        return
    await _send(update, i18n.t("admin_pubkey", key=T.esc(public)))


async def cmd_admin_commands(update, context):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    await _send(update, T.ADMIN_COMMANDS, kb.admin_panel(0, 0))

"""
ربات شخصی مشتری: گرفتن، ذخیره و حذف توکن.
"""

from telegram.error import TelegramError

from core import logging_setup
from licensing import i18n
from licensing import licenses
from licensing.telegram import keyboards as kb
from licensing.telegram import texts as T
from licensing.telegram.sales.common import _db, _runner, _send, _user_row


async def personal_bot_info(update, context):
    db = _db(context)
    user_row = _user_row(update, context)
    active = [row for row in db.licenses_by_user(user_row["telegram_id"])
              if licenses.is_valid(row)]
    if not active:
        await _send(update, T.PERSONAL_BOT_NEEDS_LICENSE, kb.back_to_menu())
        return

    has_bot = bool(user_row["personal_bot_token"])
    status_line = ""
    if has_bot:
        status_line = i18n.t(
            "personal_bot_current",
            username=T.esc(user_row["personal_bot_username"] or "?"),
            status=T.esc(user_row["personal_bot_status"]))
    await _send(update, T.PERSONAL_BOT_INTRO + status_line, kb.personal_bot(has_bot))


async def personal_bot_ask_token(update, context):
    context.user_data["awaiting"] = "pbot_token"
    await _send(update, i18n.t("personal_bot_ask_token"))


async def personal_bot_set_token(update, context, token):
    db = _db(context)
    user_row = _user_row(update, context)
    context.user_data.pop("awaiting", None)

    try:
        await update.effective_message.delete()
    except TelegramError:
        pass

    runner = _runner(context)
    if runner is None:
        await _send(update, i18n.t("personal_bot_disabled"), kb.back_to_menu())
        return

    ok, detail = await runner.validate_token(token)
    if not ok:
        # detail می‌تونه پیامِ خامِ کتابخونه‌ی تلگرام باشه (getMe شکست
        # خورده) -- هیچ‌وقت مستقیم به کاربر نشون داده نمی‌شه، فقط لاگ.
        logging_setup.log_debug(f"personal bot token validation failed: {detail}")
        await _send(update, T.PERSONAL_BOT_BAD_TOKEN,
                    kb.personal_bot(bool(user_row["personal_bot_token"])))
        return

    # هر توکنِ تازه‌ای که مشتری بفرسته، نشونِ "dead" رو هم پاک می‌کنه --
    # همین‌جا، با ست‌کردنِ صریحِ وضعیت (starting/running/failed/dead)،
    # چون set_personal_bot کل ردیف رو بازمی‌نویسه.
    db.set_personal_bot(user_row["telegram_id"], token, detail, status="starting")
    db.log_event("personal_bot_set", user_id=user_row["telegram_id"], detail={"username": detail})

    started, error, dead = await runner.start_customer_bot(user_row["telegram_id"], token)
    if not started:
        # dead=True یعنی همین توکنِ تازه هم از قبل باطل/لغوشده بود (نادر،
        # ولی ممکنه بینِ اعتبارسنجی و استارت اتفاق افتاده باشه). پیامِ
        # جداگانه‌ی "توکنت مرد" لازم نیست چون همین الان و همینجا داریم
        # بهش می‌گیم -- فقط وضعیت درست ثبت می‌شه تا start_all بعداً
        # دوباره امتحانش نکنه.
        db.set_personal_bot(user_row["telegram_id"], token, detail,
                            status="dead" if dead else "failed")
        logging_setup.log_debug(f"personal bot start failed for {user_row['telegram_id']}: {error}")
        await _send(update, i18n.t("personal_bot_start_failed"), kb.back_to_menu())
        return

    db.set_personal_bot(user_row["telegram_id"], token, detail, status="running")
    await _send(update, T.personal_bot_ready(detail), kb.back_to_menu())


async def personal_bot_delete(update, context):
    db = _db(context)
    user_row = _user_row(update, context)
    runner = _runner(context)
    if runner is not None:
        await runner.stop_customer_bot(user_row["telegram_id"])
    db.set_personal_bot(user_row["telegram_id"], None, None, status="none")
    db.log_event("personal_bot_removed", user_id=user_row["telegram_id"])
    await _send(update, T.PERSONAL_BOT_REMOVED, kb.back_to_menu())

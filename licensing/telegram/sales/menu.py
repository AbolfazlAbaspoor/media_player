"""
منوی اصلی، راهنما، انتخاب زبان و لغو گفت‌وگو.
"""

from licensing import i18n
from licensing.telegram import keyboards as kb
from licensing.telegram import texts as T
from licensing.telegram.sales.common import _db, _is_admin, _send, _user_row


async def cmd_start(update, context):
    user_row = _user_row(update, context)
    if user_row["blocked"]:
        await _send(update, T.BLOCKED)
        return
    context.user_data.pop("awaiting", None)
    db = _db(context)
    has_license = bool(db.licenses_by_user(user_row["telegram_id"]))
    await _send(update, T.welcome(user_row["first_name"], has_license),
                kb.main_menu(has_license, _is_admin(update)))


async def cmd_help(update, context):
    _user_row(update, context)
    await _send(update, T.HELP, kb.back_to_menu())


async def language_menu(update, context):
    user_row = _user_row(update, context)
    await _send(update, i18n.t("language_title"), kb.language_picker(user_row["lang"]))


async def language_set(update, context, code):
    """
    زبان کاربر رو عوض می‌کنه و *بلافاصله* با زبان جدید جواب می‌ده.

    set_language قبل از ساختن پیام صدا زده می‌شه، وگرنه تأییدیه به زبان
    قبلی نوشته می‌شد -- که دقیقاً برای کسی که داره زبان رو عوض می‌کنه
    گیج‌کننده‌ست.
    """
    db = _db(context)
    user = update.effective_user
    if not i18n.is_supported(code):
        await language_menu(update, context)
        return

    db.set_user_lang(user.id, code)
    i18n.set_language(code)
    await _send(update,
                i18n.t("language_set", name=i18n.LANGUAGE_NAMES.get(code, code)),
                kb.main_menu(bool(db.licenses_by_user(user.id)), _is_admin(update)))


async def cmd_cancel(update, context):
    context.user_data.pop("awaiting", None)
    context.user_data.pop("setup", None)
    await _send(update, T.CANCELLED)
    await cmd_start(update, context)

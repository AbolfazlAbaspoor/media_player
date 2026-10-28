"""
دسترسی به سرویس‌ها و ارسال پیام: چیزهایی که همه‌ی بخش‌های ربات فروش لازم دارن.
"""

from telegram.constants import ParseMode
from telegram.error import TelegramError

from core import logging_setup
from licensing import config
from licensing import i18n
from licensing.telegram import texts as T


HTML = ParseMode.HTML


def _db(context):
    return context.application.bot_data["db"]


def _supervisor(context):
    return context.application.bot_data.get("supervisor")


def _runner(context):
    return context.application.bot_data.get("runner")


async def _send(update, text, reply_markup=None):
    """
    پاسخ، فارغ از این‌که از دکمه اومده یا از پیام. پیام‌های دکمه‌ای ویرایش
    می‌شن (نه اینکه پیام جدید بفرستن) تا چت شلوغ نشه؛ ولی اگه ویرایش نشد
    (مثلاً متن عوض نشده)، می‌افتیم روی ارسال جدید.
    """
    if update.callback_query is not None:
        try:
            await update.callback_query.edit_message_text(
                text, parse_mode=HTML, reply_markup=reply_markup,
                disable_web_page_preview=True)
            return
        except TelegramError:
            pass
        await update.callback_query.message.reply_text(
            text, parse_mode=HTML, reply_markup=reply_markup, disable_web_page_preview=True)
        return
    await update.effective_message.reply_text(
        text, parse_mode=HTML, reply_markup=reply_markup, disable_web_page_preview=True)


async def _admin_ask(update, context, is_admin, send, awaiting, prompt_key, clear=()):
    """
    شروعِ یه ویزاردِ متنیِ ادمین: اگه ادمین نبود ADMIN_ONLY، وگرنه حالتِ
    awaiting رو ست می‌کنه و سؤالِ اول رو می‌پرسه. is_admin و send رو فراخوان
    می‌ده (هر ماژول _is_admin/_send خودش رو داره که تست‌ها جدا mock می‌کنن).
    """
    if not is_admin:
        await send(update, T.ADMIN_ONLY)
        return
    for key in clear:
        context.user_data.pop(key, None)
    context.user_data["awaiting"] = awaiting
    await send(update, i18n.t(prompt_key))


async def _notify(application, user_id, text, reply_markup=None):
    """
    پیام به یه کاربر دلخواه. خطا (بلاک کردن ربات، اکانت پاک‌شده) نباید کل
    عملیات رو بخوابونه، فقط لاگ می‌شه.
    """
    try:
        await application.bot.send_message(
            user_id, text, parse_mode=HTML, reply_markup=reply_markup,
            disable_web_page_preview=True)
        return True
    except TelegramError as e:
        logging_setup.log_debug(f"telegram notify to {user_id} failed: {e}")
        return False


async def _notify_admins(application, text, reply_markup=None):
    sent = 0
    for admin_id in config.admin_ids():
        if await _notify(application, admin_id, text, reply_markup):
            sent += 1
    return sent


async def _notify_admins_localized(application, build):
    """
    مثل _notify_admins، ولی برای هر ادمین به زبانِ خودش. build() بعد از ست
    شدنِ زبانِ اون ادمین صدا زده می‌شه و (متن، کیبورد یا None) برمی‌گردونه.
    تعداد پیام‌های رسیده رو برمی‌گردونه.
    """
    db = application.bot_data.get("db")
    sent = 0
    for admin_id in config.admin_ids():
        _set_user_language(db, admin_id)
        text, reply_markup = build()
        if await _notify(application, admin_id, text, reply_markup):
            sent += 1
    return sent


def _user_row(update, context):
    """
    کاربر رو از دیتابیس می‌گیره (و اگه تازه‌ست می‌سازه) و **زبان همین آپدیت
    رو ست می‌کنه**.

    چون همه‌ی هندلرها اول این رو صدا می‌زنن، یه جا ست کردن زبان کافیه و
    لازم نیست به هر تابع متن پاس داده بشه (توضیح توی licensing/i18n.py).

    اگه کاربر تازه‌ست و هنوز زبانی انتخاب نکرده، زبان تلگرام خودش امتحان
    می‌شه -- یه حدس بهتر از پیش‌فرض خشک، و کاربر بعداً می‌تونه عوضش کنه.
    """
    user = update.effective_user
    row = _db(context).upsert_user(user.id, user.username, user.first_name)

    lang = row["lang"]
    if not row["last_seen_at"] or row["created_at"] == row["last_seen_at"]:
        guess = i18n.normalize(getattr(user, "language_code", None))
        if guess != lang and i18n.is_supported(guess):
            _db(context).set_user_lang(user.id, guess)
            lang = guess

    i18n.set_language(lang)
    return row


def _set_user_language(db, user_id):
    """
    زبان رو به زبانِ کاربرِ user_id ست می‌کنه (کاربرِ ناشناس = پیش‌فرض).
    جدا از _use_user_language چون تسک‌های پس‌زمینه context ندارن.
    """
    try:
        row = db.get_user(int(user_id))
    except Exception:
        row = None
    i18n.set_language(row["lang"] if row else None)


def _use_user_language(context, user_id):
    """
    زبان رو به زبانِ *گیرنده* عوض می‌کنه، نه فرستنده.

    کارهای ادمین (تمدید، تعلیق، لغو) دو تا پیام دارن: یکی به خود ادمین و
    یکی به مشتری. بدون این، پیامِ مشتری با زبانِ ادمین ساخته می‌شد -- یه
    ادمین فارسی‌زبان برای مشتریِ انگلیسی‌زبان فارسی می‌فرستاد.

    ترتیبش مهمه: اول پیام ادمین رو بفرست، بعد این رو صدا بزن.
    """
    try:
        db = _db(context)
    except Exception:
        db = None
    _set_user_language(db, user_id)


def _is_admin(update):
    return config.is_admin(update.effective_user.id)


def _cfg_state(context):
    """وضعیت سفارشی‌سازی فعلی کاربر."""
    state = context.user_data.get("cfg")
    if not state:
        state = {"months": 1, "bots": 1, "features": [],
                 "panel_code": None, "kind": "new", "license_id": None}
        context.user_data["cfg"] = state
    return state

"""
عضویت اجباری کانال رسمی، سمت تلگرام.

منطقِ «کی متوقف بشه، کی برگرده» توی licensing/membership.py است و تست داره؛
این ماژول فقط به تلگرام وصلش می‌کنه:

  * gate            هر پیامِ خصوصیِ غیرادمین قبل از بقیه‌ی هندلرها از اینجا رد
                    می‌شه. عضو نیست -> دکمه‌ی «عضو شو» و پایانِ پردازش.
  * on_chat_member  رویداد join/leave کانال، لحظه‌ای.
  * membership_loop هر ساعت عضویت همه‌ی صاحبان لایسنس رو واقعاً از تلگرام
                    می‌پرسه (رویدادها ممکنه از دست برن) و مهلت‌تموم‌شده‌ها رو
                    متوقف می‌کنه.
  * /channel        ادمین کانال رو تنظیم/خاموش می‌کنه.

## ربات باید ادمینِ کانال باشه

وگرنه تلگرام نه رویداد عضویت می‌فرسته نه اجازه‌ی getChatMember می‌ده.
/channel موقع تنظیم همین رو چک می‌کنه.

## در شک، مجازات نکن

اگه عضویت قابل بررسی نباشه (ربات ادمین نیست، شبکه قطعه، کانال عوض شده)،
هیچ‌کس متوقف یا بلاک نمی‌شه و فقط به ادمین خبر داده می‌شه. توقفِ مشتری‌های
پول‌داده به‌خاطر اشتباهِ تنظیمات خودمون، بدتر از چند ساعت بی‌اثر بودنِ این
قابلیته.
"""

import asyncio
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    ApplicationHandlerStop,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    TypeHandler,
)

from core import logging_setup
from licensing import config
from licensing import i18n
from licensing import membership

CHECK_EVERY_SECONDS = 3600
#: جواب getChatMember این‌قدر کش می‌شه تا هر کلیک یه درخواست API نباشه.
CACHE_SECONDS = 300
#: هشدارِ «بررسی کار نمی‌کنه» به ادمین حداکثر هر این‌قدر یه بار.
ADMIN_ALERT_EVERY_SECONDS = 6 * 3600
CALLBACK_CHECK = "chan:check"

HTML = ParseMode.HTML


def _db(application):
    return application.bot_data["db"]


def _hours():
    return max(1, round(membership.grace_seconds() / 3600))


def join_keyboard(channel):
    rows = []
    url = membership.join_url(channel)
    if url:
        rows.append([InlineKeyboardButton(i18n.t("channel_join_button"), url=url)])
    rows.append([InlineKeyboardButton(i18n.t("channel_check_button"), callback_data=CALLBACK_CHECK)])
    return InlineKeyboardMarkup(rows)


def _same_chat(chat, channel):
    channel = str(channel or "").strip()
    if channel.startswith("@"):
        return (chat.username or "").lower() == channel[1:].lower()
    return str(chat.id) == channel


async def _send_user(application, user_id, text, reply_markup=None):
    try:
        await application.bot.send_message(int(user_id), text, parse_mode=HTML,
                                           reply_markup=reply_markup,
                                           disable_web_page_preview=True)
        return True
    except TelegramError as e:
        logging_setup.log_debug(f"channel notice to {user_id} failed: {e}")
        return False


def _use_user_language(application, user_id):
    """زبان پیام بعدی. خوندنش هیچ‌وقت نباید جلوی خودِ پیام رو بگیره."""
    try:
        row = _db(application).get_user(int(user_id))
        lang = row["lang"] if row else None
    except Exception:
        lang = None
    i18n.set_language(lang if isinstance(lang, str) else None)


# ----------------------------------------------------------- بررسی عضویت

async def fetch_is_member(application, channel, user_id):
    """True/False، یا None یعنی «معلوم نشد» -- که هیچ‌وقت به‌معنی «عضو نیست» نیست."""
    try:
        member = await application.bot.get_chat_member(channel, int(user_id))
    except TelegramError as e:
        await _alert_admins_check_broken(application, str(e))
        return None
    return membership.is_member_status(member.status, getattr(member, "is_member", None))


async def _cached_is_member(application, channel, user_id):
    cache = application.bot_data.setdefault("channel_member_cache", {})
    hit = cache.get(int(user_id))
    if hit and hit[0] == channel and time.time() - hit[1] < CACHE_SECONDS:
        return hit[2]
    result = await fetch_is_member(application, channel, user_id)
    if result is not None:
        cache[int(user_id)] = (channel, time.time(), result)
    return result


def _remember(application, channel, user_id, is_member):
    cache = application.bot_data.setdefault("channel_member_cache", {})
    cache[int(user_id)] = (channel, time.time(), bool(is_member))


async def _alert_admins_check_broken(application, error):
    last = application.bot_data.get("channel_alert_at", 0)
    if time.time() - last < ADMIN_ALERT_EVERY_SECONDS:
        return
    application.bot_data["channel_alert_at"] = time.time()
    for admin_id in config.admin_ids():
        _use_user_language(application, admin_id)
        await _send_user(application, admin_id,
                         i18n.t("admin_channel_check_failed", error=error))


# ------------------------------------------------------- پیامد join/leave

async def handle_joined(application, user_id, notify=True):
    db = _db(application)
    supervisor = application.bot_data.get("supervisor")
    was_out = await asyncio.to_thread(membership.mark_joined, db, user_id)
    changed = await asyncio.to_thread(membership.resume_user, db, user_id, supervisor)
    if notify and changed:
        _use_user_language(application, user_id)
        await _send_user(application, user_id, i18n.t("channel_resumed_notice"))
    return was_out, changed


async def handle_left(application, user_id, channel):
    db = _db(application)
    newly = await asyncio.to_thread(membership.mark_left, db, user_id)
    if newly:
        _use_user_language(application, user_id)
        await _send_user(application, user_id,
                         i18n.t("channel_left_warning", channel=channel, hours=_hours()),
                         join_keyboard(channel))
    return newly


# ------------------------------------------------------------- هندلرها

async def gate(update, context):
    """group=-1: قبل از همه‌ی هندلرهای دیگه."""
    application = context.application
    db = _db(application)
    channel = membership.required_channel(db)
    if not channel or update.chat_member is not None:
        return

    user = update.effective_user
    chat = update.effective_chat
    if user is None or (chat is not None and chat.type != "private"):
        return
    if config.is_admin(user.id):
        return
    query = update.callback_query
    if query is not None and query.data == CALLBACK_CHECK:
        return

    is_member = await _cached_is_member(application, channel, user.id)
    if is_member is None:
        return
    if is_member:
        if membership.is_out(db, user.id):
            await handle_joined(application, user.id)
        return

    # فقط ساعت ۲۴ ساعته شروع می‌شه؛ پیامِ «بیرون رفتی» اینجا نمی‌ره چون همین
    # الان جوابِ «باید عضو باشی» رو می‌گیره -- و کسی که هیچ‌وقت عضو نبوده
    # «بیرون نرفته».
    await asyncio.to_thread(membership.mark_left, db, user.id)
    i18n.set_language(getattr(user, "language_code", None))
    _use_user_language(application, user.id)
    text = i18n.t("channel_required", channel=channel, hours=_hours())
    try:
        if query is not None:
            try:
                await query.answer()
            except TelegramError:
                pass
            await query.message.reply_text(text, parse_mode=HTML,
                                           reply_markup=join_keyboard(channel),
                                           disable_web_page_preview=True)
        elif update.effective_message is not None:
            await update.effective_message.reply_text(text, parse_mode=HTML,
                                                      reply_markup=join_keyboard(channel),
                                                      disable_web_page_preview=True)
    except TelegramError as e:
        logging_setup.log_debug(f"channel gate reply failed: {e}")
    raise ApplicationHandlerStop


async def on_check(update, context):
    """دکمه‌ی «عضو شدم»: بدون کش دوباره می‌پرسه."""
    application = context.application
    query = update.callback_query
    user = update.effective_user
    channel = membership.required_channel(_db(application))
    _use_user_language(application, user.id)

    if not channel:
        await query.answer()
        return
    is_member = await fetch_is_member(application, channel, user.id)
    if is_member:
        _remember(application, channel, user.id, True)
        await handle_joined(application, user.id, notify=False)
        await query.answer()
        try:
            await query.edit_message_text(i18n.t("channel_thanks"), parse_mode=HTML)
        except TelegramError:
            pass
        return
    await query.answer(i18n.t("channel_still_not_member"), show_alert=True)


async def on_chat_member(update, context):
    application = context.application
    channel = membership.required_channel(_db(application))
    change = update.chat_member
    if not channel or change is None or not _same_chat(change.chat, channel):
        return
    new = change.new_chat_member
    user_id = new.user.id
    is_member = membership.is_member_status(new.status, getattr(new, "is_member", None))
    _remember(application, channel, user_id, is_member)
    if is_member:
        await handle_joined(application, user_id)
    else:
        await handle_left(application, user_id, channel)


async def cmd_channel(update, context):
    """/channel ، /channel @name ، /channel off -- فقط ادمین."""
    user = update.effective_user
    if user is None or not config.is_admin(user.id):
        return
    application = context.application
    db = _db(application)
    _use_user_language(application, user.id)
    args = context.args or []

    if not args:
        channel = membership.required_channel(db)
        text = (i18n.t("admin_channel_status", channel=channel, hours=_hours())
                if channel else i18n.t("admin_channel_off"))
        await update.effective_message.reply_text(text + "\n\n" + i18n.t("admin_channel_usage"),
                                                  parse_mode=HTML)
        return

    value = args[0].strip()
    if value.lower() in ("off", "none", "-"):
        await asyncio.to_thread(db.set_setting, "required_channel", "")
        await update.effective_message.reply_text(i18n.t("admin_channel_off"), parse_mode=HTML)
        return

    # قبل از روشن‌کردن، مطمئن شو ربات واقعاً می‌تونه عضویت رو ببینه؛ وگرنه
    # قابلیت روشن به‌نظر می‌رسه ولی هیچ کاری نمی‌کنه.
    try:
        me = await application.bot.get_chat_member(value, application.bot.id)
        is_admin = str(me.status).lower() in ("administrator", "creator", "owner")
    except TelegramError:
        is_admin = False
    if not is_admin:
        await update.effective_message.reply_text(
            i18n.t("admin_channel_not_admin", channel=value), parse_mode=HTML)
        return

    await asyncio.to_thread(db.set_setting, "required_channel", value)
    application.bot_data.pop("channel_member_cache", None)
    await update.effective_message.reply_text(
        i18n.t("admin_channel_set", channel=value), parse_mode=HTML)


# --------------------------------------------------------- حلقه‌ی ساعتی

async def check_all(application):
    """یه دور: عضویت همه، بعد متوقف‌کردنِ مهلت‌تموم‌شده‌ها. خروجی: تعداد متوقف‌شده."""
    db = _db(application)
    channel = membership.required_channel(db)
    if not channel:
        return 0

    for user_id in await asyncio.to_thread(membership.users_to_check, db):
        if config.is_admin(user_id):
            continue
        is_member = await fetch_is_member(application, channel, user_id)
        if is_member is None:
            # بررسی کار نمی‌کنه؛ بقیه‌ی دور هم همین‌طوره. هیچ‌کس متوقف نمی‌شه.
            return 0
        _remember(application, channel, user_id, is_member)
        if is_member:
            await handle_joined(application, user_id)
        else:
            await handle_left(application, user_id, channel)
        await asyncio.sleep(0.05)   # زیر سقف نرخ API تلگرام

    supervisor = application.bot_data.get("supervisor")
    paused_total = 0
    for user_id in await asyncio.to_thread(membership.users_to_pause, db):
        if config.is_admin(user_id):
            continue
        paused = await asyncio.to_thread(membership.pause_user, db, user_id, supervisor)
        if paused:
            paused_total += len(paused)
            _use_user_language(application, user_id)
            await _send_user(application, user_id,
                             i18n.t("channel_paused_notice", channel=channel),
                             join_keyboard(channel))
    return paused_total


async def membership_loop(application):
    await asyncio.sleep(30)   # بعد از بالا آمدن کامل ربات
    while True:
        try:
            await check_all(application)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging_setup.log_exception("channel membership loop")
        await asyncio.sleep(CHECK_EVERY_SECONDS)


def register(application):
    """
    باید *قبل از* هندلرهای عمومیِ ربات فروش صدا زده بشه: CallbackQueryHandler
    عمومی همه‌ی دکمه‌ها رو می‌گیره و chan:check هیچ‌وقت به on_check نمی‌رسید.
    """
    application.add_handler(TypeHandler(Update, gate), group=-1)
    application.add_handler(ChatMemberHandler(on_chat_member, ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(CallbackQueryHandler(on_check, pattern=f"^{CALLBACK_CHECK}$"))
    application.add_handler(CommandHandler("channel", cmd_channel))

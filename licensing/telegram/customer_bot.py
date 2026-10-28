"""
ربات شخصی مشتری: هر مشتری می‌تونه از @BotFather یه ربات بسازه و توکنش رو
بده، تا همون ربات فقط *مال خودش* اجرا بشه.

## چرا جدا از ربات فروش

  * حریم خصوصی: مشتری داخل ربات خودش فقط ربات‌های خودش رو می‌بینه، و هیچ
    داده‌ای از بقیه به چشمش نمی‌خوره.
  * برندینگ: اسم و عکس ربات مال خودشه.
  * ایزوله‌بودن خطا: اگه توکن یکی باطل بشه یا محدود بشه، ربات فروش و
    بقیه‌ی مشتری‌ها اثری نمی‌بینن.

## دسترسی

ربات شخصی *فقط* به صاحب توکن جواب می‌ده (owner_id). هر کس دیگه‌ای که پیداش
کنه و /start بزنه، یه پیام کوتاه می‌گیره و تمام. این مهمه: توکن ربات
تلگرام عمومیه (هر کسی می‌تونه یوزرنیمش رو پیدا کنه)، پس نمی‌شه فرض کرد
فقط مالک بهش پیام می‌ده.

## چه کارهایی می‌شه کرد

دیدن لایسنس‌ها، دیدن و کنترل ربات‌ها (اجرا/توقف/ری‌استارت)، دیدن لاین صدا،
و تغییر چند تنظیم ساده‌ی ربات. خرید و پرداخت عمداً اینجا نیست و توی ربات
فروش می‌مونه، چون پرداخت به اطلاعات کارت و صف تأیید ادمین وصله.
"""

import asyncio
import json
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import Forbidden, InvalidToken, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from core import audio_lines
from core import logging_setup
from licensing import catalog
from licensing import i18n
from licensing import licenses
from licensing import provisioning
from licensing.db import json_list
from licensing import telegram as telegram_layer
from licensing.telegram import cookie_upload
from licensing.telegram import setup_wizard
from licensing.telegram import texts as T
from licensing.telegram.sales.common import _db, _send, _supervisor

HTML = ParseMode.HTML

def _not_owner():
    return i18n.t("customer_not_owner")


def _owner_id(context):
    return int(context.application.bot_data["owner_id"])


def _is_owner(update, context):
    """
    فقط صاحب توکن جواب می‌گیره -- و همین‌جا زبان همون آپدیت هم ست می‌شه.

    یوزرنیم ربات تلگرام عمومیه، پس نمی‌شه فرض کرد فقط مالک بهش پیام می‌ده؛
    برای همین هر هندلر اول این رو صدا می‌زنه.
    """
    user = update.effective_user
    if user is None or user.id != _owner_id(context):
        # زبان غریبه رو از خود تلگرامش حدس می‌زنیم تا پیام «این مال تو
        # نیست» رو دست‌کم به زبان خودش ببینه.
        i18n.set_language(getattr(user, "language_code", None) if user else None)
        return False
    try:
        row = _db(context).get_user(user.id)
    except Exception:
        row = None
    i18n.set_language(row["lang"] if row else None)
    return True


def _menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(i18n.t("menu_bots"), callback_data="my:bots")],
        [InlineKeyboardButton(i18n.t("menu_licenses"), callback_data="my:lic")],
        [InlineKeyboardButton(i18n.t("customer_menu_lines"), callback_data="my:lines")],
        [InlineKeyboardButton(i18n.t("customer_menu_status"), callback_data="my:status")],
    ])


async def cmd_start(update, context):
    if not _is_owner(update, context):
        await _send(update, _not_owner())
        return
    db = _db(context)
    owner = _owner_id(context)
    active = [row for row in db.licenses_by_user(owner) if licenses.is_valid(row)]
    instances = db.instances_by_user(owner)
    await _send(update,
                i18n.t("customer_panel", licenses=len(active), bots=len(instances)),
                _menu())


async def show_licenses(update, context):
    if not _is_owner(update, context):
        await _send(update, _not_owner())
        return
    db = _db(context)
    rows = db.licenses_by_user(_owner_id(context))
    if not rows:
        await _send(update, i18n.t("no_license"), _menu())
        return
    blocks = []
    for row in rows:
        _status, status_text = licenses.describe_status(row)
        features = catalog.expand_features(json_list(row["features"]))
        blocks.append(i18n.t(
            "customer_license_entry", key=T.esc(row["key"]),
            status=T.esc(status_text), expires=T.fmt_date(row["expires_at"]),
            bots=row["max_bots"],
            features=T.esc(T.feature_list(features)),
        ))
    # برای هر لایسنسِ فعالی که هنوز جای ربات داره، دکمه‌ی ساخت ربات -- قبلاً
    # این فقط از ربات فروش ممکن بود.
    buttons = []
    for row in rows:
        if licenses.is_valid(row) and len(db.instances_by_license(int(row["id"]))) < int(row["max_bots"]):
            buttons.append([InlineKeyboardButton(i18n.t("btn_new_bot_for", key=row["key"]),
                                                 callback_data=f"my:sustart:{row['id']}")])
    buttons.append([InlineKeyboardButton(i18n.t("btn_menu"), callback_data="my:menu")])
    await _send(update, i18n.t("licenses_title") + "\n\n" + "\n\n".join(blocks),
                InlineKeyboardMarkup(buttons))


async def _owned_instance_or_reply(update, context, instance_id):
    """(ربات، لایسنسش) یا None بعد از جواب دادنِ «پیدا نشد/مالِ تو نیست»."""
    db = _db(context)
    instance = db.get_instance(instance_id)
    if instance is None:
        await _send(update, i18n.t("bot_not_found"), _menu())
        return None
    license_row = db.get_license(int(instance["license_id"]))
    if license_row is None or int(license_row["user_id"]) != _owner_id(context):
        await _send(update, i18n.t("bot_not_yours"), _menu())
        return None
    return instance, license_row


async def show_bots(update, context):
    if not _is_owner(update, context):
        await _send(update, _not_owner())
        return
    db = _db(context)
    rows = db.instances_by_user(_owner_id(context))
    if not rows:
        await _send(update, i18n.t("customer_no_bots"), _menu())
        return
    buttons = []
    for row in rows:
        marker = {"running": "🟢", "stopped": "⚪️", "crashed": "🟡",
                  "blocked": "🔴", "missing": "⚠️"}.get(row["status"], "⚪️")
        buttons.append([InlineKeyboardButton(
            f"{marker} {row['slug']} — {row['tt_host']}",
            callback_data=f"my:bot:{row['id']}")])
    buttons.append([InlineKeyboardButton(i18n.t("btn_menu"), callback_data="my:menu")])
    await _send(update, i18n.t("bots_title"), InlineKeyboardMarkup(buttons))


async def show_bot(update, context, instance_id):
    if not _is_owner(update, context):
        await _send(update, _not_owner())
        return
    owned = await _owned_instance_or_reply(update, context, instance_id)
    if owned is None:
        return
    instance, license_row = owned

    supervisor = _supervisor(context)
    live = None
    if supervisor is not None:
        live = next((item for item in supervisor.status() if item["slug"] == instance["slug"]), None)

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(i18n.t("btn_restart"), callback_data=f"my:restart:{instance_id}"),
            InlineKeyboardButton(i18n.t("btn_stop"), callback_data=f"my:stop:{instance_id}"),
        ],
        [InlineKeyboardButton(i18n.t("btn_start"), callback_data=f"my:run:{instance_id}")],
        [InlineKeyboardButton(i18n.t("btn_cookies"), callback_data=f"my:cookies:{instance_id}")],
        [InlineKeyboardButton(i18n.t("btn_edit_bot"), callback_data=f"my:suedit:{instance_id}")],
        [InlineKeyboardButton(i18n.t("btn_bots"), callback_data="my:bots")],
    ])
    await _send(update, T.instance_card(instance, live), buttons)


# ---------------------------------------------------------------- ویزارد
#
# همون ویزارد ربات فروش (setup_wizard.py)، با دکمه‌های این ربات. مالکیت
# لایسنس/نمونه همیشه دوباره چک می‌شه، چون شناسه‌ها از callback data میان
# و قابل جعلن.

_WIZARD_PREFIX = "my:su"


def _owned_license(context, license_id):
    row = _db(context).get_license(int(license_id))
    if row is None or int(row["user_id"]) != _owner_id(context):
        return None
    return row


async def wizard_start(update, context, license_id):
    license_row = _owned_license(context, license_id)
    if license_row is None:
        await _send(update, i18n.t("license_not_yours"), _menu())
        return
    try:
        setup_wizard.check_can_add(_db(context), license_row)
    except setup_wizard.WizardError as e:
        await _send(update, T.LICENSE_BOT_QUOTA_FULL if str(e) == "quota" else str(e), _menu())
        return
    state = setup_wizard.new_state(license_id)
    context.user_data["setup"] = state
    context.user_data["awaiting"] = "setup"
    await _send(update, T.SETUP_INTRO)
    await update.effective_chat.send_message(
        setup_wizard.prompt(0), parse_mode=ParseMode.HTML,
        reply_markup=setup_wizard.step_keyboard(0, state, _WIZARD_PREFIX))


async def wizard_edit(update, context, instance_id):
    instance = _owned_instance(context, instance_id)
    if instance is None:
        await _send(update, i18n.t("bot_not_yours"), _menu())
        return
    state = setup_wizard.state_from_instance(instance)
    context.user_data["setup"] = state
    context.user_data["awaiting"] = "setup"
    await _send(update, i18n.t("setup_edit_intro", slug=T.esc(instance["slug"])))
    await update.effective_chat.send_message(
        setup_wizard.prompt(0), parse_mode=ParseMode.HTML,
        reply_markup=setup_wizard.step_keyboard(0, state, _WIZARD_PREFIX))


async def wizard_text(update, context, text):
    state = context.user_data.get("setup")
    if not state or _owned_license(context, state["license_id"]) is None:
        context.user_data.pop("awaiting", None)
        context.user_data.pop("setup", None)
        await cmd_start(update, context)
        return
    if await setup_wizard.answer_step(update, state, text, _WIZARD_PREFIX, "my:menu"):
        context.user_data.pop("awaiting", None)


async def wizard_default(update, context, index):
    state = context.user_data.get("setup")
    if not state or int(state.get("step", -1)) != int(index):
        await _send(update, i18n.t("setup_missing_state"), _menu())
        return
    value = setup_wizard.default_for(int(index), state)
    if value is None:
        return
    context.user_data["awaiting"] = "setup"
    await wizard_text(update, context, str(value))


async def wizard_apply(update, context, license_id):
    state = context.user_data.get("setup")
    license_row = _owned_license(context, license_id)
    if not state or license_row is None or int(state.get("license_id", 0)) != int(license_id):
        await _send(update, i18n.t("setup_missing_state"), _menu())
        return
    db = _db(context)
    await _send(update, i18n.t("setup_working"))
    try:
        if state.get("instance_id"):
            if _owned_instance(context, state["instance_id"]) is None:
                raise setup_wizard.WizardError(i18n.t("bot_not_yours"))
            instance = await asyncio.to_thread(setup_wizard.update, db, license_row, state,
                                               _supervisor(context))
            text = i18n.t("setup_edit_done", slug=T.esc(instance["slug"]),
                          host=T.esc(instance["tt_host"]), port=instance["tt_port"])
        else:
            instance = await asyncio.to_thread(setup_wizard.create, db, license_row, state,
                                               _supervisor(context))
            line_output, line_input = audio_lines.line_names(instance["audio_line"])
            text = T.setup_done(instance, line_output, line_input)
    except setup_wizard.WizardError as e:
        await _send(update, T.LICENSE_BOT_QUOTA_FULL if str(e) == "quota" else str(e), _menu())
        return
    except Exception:
        logging_setup.log_exception("customer bot setup")
        await _send(update, T.setup_failed(), _menu())
        return
    context.user_data.pop("setup", None)
    await _send(update, text, _menu())


# ------------------------------------------------------------------ کوکی
#
# مشتری cookies.txt رو برای *ربات خودش* می‌فرسته. فایل توی پوشه‌ی همون ربات
# ذخیره می‌شه (core/cookie_files.py)، هیچ‌وقت به کاربر برگردونده یا لاگ نمی‌شه،
# و بعدش ربات ری‌استارت می‌شه چون سرویس‌ها کوکی رو موقع ساخت می‌خونن.

COOKIE_SERVICES = ("youtube", "youtubemusic", "instagram", "soundcloud")


def _owned_instance(context, instance_id):
    db = _db(context)
    instance = db.get_instance(int(instance_id))
    if instance is None:
        return None
    license_row = db.get_license(int(instance["license_id"]))
    if license_row is None or int(license_row["user_id"]) != _owner_id(context):
        return None
    return instance


async def show_cookies(update, context, instance_id, service=None):
    from core import cookie_files
    from licensing import provisioning

    instance = _owned_instance(context, instance_id)
    if instance is None:
        await _send(update, i18n.t("bot_not_yours"), _menu())
        return
    if service in COOKIE_SERVICES:
        context.user_data["cookie_target"] = (int(instance_id), service)
    target = context.user_data.get("cookie_target")
    selected = target[1] if target and target[0] == int(instance_id) else None

    _group_dir, bot_dir = provisioning.instance_dirs(instance)
    have = set(cookie_files.present(bot_dir))
    lines = [i18n.t("cookies_title")]
    for name in COOKIE_SERVICES:
        mark = "\u2705" if name in have else "\u2796"
        lines.append(f"{mark} {name}")
    lines.append("")
    lines.append(i18n.t("cookies_send_hint", service=selected) if selected
                 else i18n.t("cookies_pick_hint"))

    rows = [[InlineKeyboardButton(name, callback_data=f"my:ckset:{instance_id}:{name}")]
            for name in COOKIE_SERVICES]
    for name in COOKIE_SERVICES:
        if name in have:
            rows.append([InlineKeyboardButton(i18n.t("btn_cookie_delete", service=name),
                                              callback_data=f"my:ckdel:{instance_id}:{name}")])
    rows.append([InlineKeyboardButton(i18n.t("btn_back"), callback_data=f"my:bot:{instance_id}")])
    await _send(update, "\n".join(lines), InlineKeyboardMarkup(rows))


async def _restart_if_running(context, instance):
    supervisor = _supervisor(context)
    if supervisor is None:
        return
    running = any(item["slug"] == instance["slug"] and item.get("alive")
                  for item in supervisor.status())
    if running:
        await asyncio.to_thread(supervisor.restart, instance["slug"])


async def delete_cookie(update, context, instance_id, service):
    from core import cookie_files
    from licensing import provisioning

    instance = _owned_instance(context, instance_id)
    if instance is None or service not in COOKIE_SERVICES:
        await _send(update, i18n.t("bot_not_yours"), _menu())
        return
    _group_dir, bot_dir = provisioning.instance_dirs(instance)
    if await asyncio.to_thread(cookie_files.remove, bot_dir, service):
        await _restart_if_running(context, instance)
    await show_cookies(update, context, instance_id)


async def on_document(update, context):
    from core import cookie_files
    from licensing import provisioning

    if not _is_owner(update, context):
        await _send(update, _not_owner())
        return
    target = context.user_data.get("cookie_target")
    document = update.effective_message.document
    if not target or document is None:
        await _send(update, i18n.t("cookies_pick_first"), _menu())
        return
    instance_id, service = target
    instance = _owned_instance(context, instance_id)
    if instance is None:
        await _send(update, i18n.t("bot_not_yours"), _menu())
        return
    data, problem = await cookie_upload.fetch_cookie_document(document)
    if problem is not None:
        await _send(update, i18n.t("cookies_rejected",
                                   reason="too large" if problem == cookie_upload.TOO_LARGE
                                   else "download failed"))
        return
    _group_dir, bot_dir = provisioning.instance_dirs(instance)
    try:
        await asyncio.to_thread(cookie_files.write, bot_dir, service, data)
    except cookie_files.CookieError as e:
        await _send(update, i18n.t("cookies_rejected", reason=str(e)))
        return
    finally:
        data = None
    context.user_data.pop("cookie_target", None)
    await _restart_if_running(context, instance)
    await _send(update, i18n.t("cookies_saved", service=service))
    await show_cookies(update, context, instance_id)


async def bot_action(update, context, action, instance_id):
    if not _is_owner(update, context):
        await _send(update, _not_owner())
        return
    owned = await _owned_instance_or_reply(update, context, instance_id)
    if owned is None:
        return
    instance, license_row = owned

    supervisor = _supervisor(context)
    if supervisor is None:
        await _send(update, i18n.t("no_supervisor"), _menu())
        return

    if action in ("restart", "run") and not licenses.is_valid(license_row):
        await _send(update, i18n.t("customer_license_inactive"), _menu())
        return

    if action == "restart":
        await asyncio.to_thread(supervisor.restart, instance["slug"])
    elif action == "stop":
        await asyncio.to_thread(supervisor.stop, instance["slug"])
    elif action == "run":
        await asyncio.to_thread(supervisor.start_instance, instance)

    await show_bot(update, context, instance_id)


async def show_lines(update, context):
    if not _is_owner(update, context):
        await _send(update, _not_owner())
        return
    db = _db(context)
    rows = db.instances_by_user(_owner_id(context))
    if not rows:
        await _send(update, i18n.t("customer_no_lines"), _menu())
        return
    blocks = []
    for row in rows:
        output, inp = audio_lines.line_names(row["audio_line"] or row["slug"])
        blocks.append(i18n.t("customer_line_entry", line=T.esc(row["audio_line"]),
                             output=T.esc(output), input=T.esc(inp)))
    await _send(update, i18n.t("customer_lines_title") + "\n\n" + "\n\n".join(blocks), _menu())


async def show_status(update, context):
    if not _is_owner(update, context):
        await _send(update, _not_owner())
        return
    db = _db(context)
    supervisor = _supervisor(context)
    rows = db.instances_by_user(_owner_id(context))
    mine = {row["slug"] for row in rows}
    if not mine:
        await _send(update, i18n.t("customer_no_bots_at_all"), _menu())
        return
    status = [item for item in (supervisor.status() if supervisor else []) if item["slug"] in mine]
    if not status:
        await _send(update, i18n.t("customer_bots_unmanaged"), _menu())
        return
    lines = [i18n.t("customer_status_title"), ""]
    for item in status:
        icon = "🟢" if item["alive"] else ("🔴" if item["blocked"] else "⚪️")
        lines.append(i18n.t(
            "customer_status_up" if item["alive"] else "customer_status_down",
            icon=icon, slug=T.esc(item["slug"]),
            uptime=T.fmt_duration(item["uptime_seconds"]) if item["alive"] else ""))
    await _send(update, "\n".join(lines), _menu())


async def on_callback(update, context):
    query = update.callback_query
    try:
        await query.answer()
    except TelegramError:
        pass
    if not _is_owner(update, context):
        await _send(update, _not_owner())
        return

    parts = (query.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""
    arg = parts[2] if len(parts) > 2 else None

    try:
        if action == "menu":
            await cmd_start(update, context)
        elif action == "lic":
            await show_licenses(update, context)
        elif action == "bots":
            await show_bots(update, context)
        elif action == "lines":
            await show_lines(update, context)
        elif action == "status":
            await show_status(update, context)
        elif action == "bot" and arg:
            await show_bot(update, context, int(arg))
        elif action in ("restart", "stop", "run") and arg:
            await bot_action(update, context, action, int(arg))
        elif action == "sustart" and arg:
            await wizard_start(update, context, int(arg))
        elif action == "suedit" and arg:
            await wizard_edit(update, context, int(arg))
        elif action == "sudef" and arg:
            await wizard_default(update, context, int(arg))
        elif action == "suapply" and arg:
            await wizard_apply(update, context, int(arg))
        elif action == "cookies" and arg:
            await show_cookies(update, context, int(arg))
        elif action == "ckset" and arg and len(parts) > 3:
            await show_cookies(update, context, int(arg), parts[3])
        elif action == "ckdel" and arg and len(parts) > 3:
            await delete_cookie(update, context, int(arg), parts[3])
    except Exception:
        logging_setup.log_exception(f"customer bot callback {query.data}")
        await _send(update, i18n.t("unexpected_error"), _menu())


async def on_text(update, context):
    if not _is_owner(update, context):
        await _send(update, _not_owner())
        return
    if context.user_data.get("awaiting") == "setup":
        await wizard_text(update, context, update.effective_message.text or "")
        return
    await cmd_start(update, context)


async def on_error(update, context):
    error = getattr(context, "error", None)
    logging_setup.log_exception("customer bot handler", error=error)

    # توکن حین polling باطل/لغو شده (نه یه مشکلِ موقتِ شبکه): E11 می‌خواد
    # این حالت "dead" علامت بخوره و دیگه هیچ‌وقت (حتی بعد از ری‌استارتِ
    # پلتفرم) دوباره امتحان نشه، و مالکش فقط یک‌بار خبردار بشه.
    #
    # با asyncio.create_task صدا می‌زنیم، نه await مستقیم: mark_dead این
    # اپلیکیشن رو stop می‌کنه، و stop-کردنِ یه Application از *داخلِ*
    # هندلر خطای همون اپ می‌تونه قفل کنه (تسکِ پردازشِ آپدیت منتظرِ
    # توقفِ خودش می‌مونه). یه تسکِ جدا این مشکل رو کنار می‌ذاره.
    if isinstance(error, (InvalidToken, Forbidden)):
        runner = context.application.bot_data.get("runner")
        owner_id = context.application.bot_data.get("owner_id")
        if runner is not None and owner_id is not None:
            asyncio.create_task(runner.mark_dead(owner_id, reason=str(error)))


async def _channel_gate(update, context):
    """
    صاحبی که از کانال رسمی بیرونه، از ربات شخصیش هم هیچی نمی‌گیره.

    این ربات ادمینِ کانال نیست و نمی‌تونه عضویت رو بپرسه؛ آخرین وضعیتی که
    ربات فروش دیده (رویداد لحظه‌ای + بررسی ساعتی) از دیتابیس خونده می‌شه.
    """
    from telegram.ext import ApplicationHandlerStop
    from licensing import membership

    db = _db(context)
    owner = _owner_id(context)
    if not await asyncio.to_thread(membership.is_out, db, owner):
        return
    _is_owner(update, context)   # زبان پیام
    channel = membership.required_channel(db)
    text = i18n.t("channel_required", channel=channel,
                  hours=max(1, round(membership.grace_seconds() / 3600)))
    url = membership.join_url(channel)
    markup = None
    if url:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        markup = InlineKeyboardMarkup([[InlineKeyboardButton(i18n.t("channel_join_button"), url=url)]])
    try:
        if update.callback_query is not None:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(text, parse_mode="HTML", reply_markup=markup)
        elif update.effective_message is not None:
            await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception:
        pass
    raise ApplicationHandlerStop


def build_application(token, owner_id, db, supervisor=None, runner=None):
    application = telegram_layer.apply_network(Application.builder().token(token)).build()
    application.bot_data["db"] = db
    application.bot_data["supervisor"] = supervisor
    application.bot_data["owner_id"] = int(owner_id)
    # برای E11: on_error موقع باطل‌شدنِ توکن (حین polling) از همینجا
    # runner.mark_dead رو صدا می‌زنه.
    application.bot_data["runner"] = runner

    from telegram import Update as _Update
    from telegram.ext import TypeHandler
    application.add_handler(TypeHandler(_Update, _channel_gate), group=-1)

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("bots", show_bots))
    application.add_handler(CommandHandler("licenses", show_licenses))
    application.add_handler(CommandHandler("lines", show_lines))
    application.add_handler(CommandHandler("status", show_status))
    application.add_handler(CallbackQueryHandler(on_callback))
    application.add_handler(MessageHandler(filters.Document.ALL, on_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    application.add_error_handler(on_error)
    return application

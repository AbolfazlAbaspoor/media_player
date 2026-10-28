"""
راه‌اندازی و ویرایش ربات تیم‌تاک مشتری.

منطقِ ویزارد مشترکه و توی licensing/telegram/setup_wizard.py است -- ربات
شخصیِ مشتری هم ازش استفاده می‌کنه. اینجا فقط پیام‌ها، دکمه‌ها و
اطلاع‌رسانی‌های ربات فروش.
"""

import asyncio

from core import audio_lines
from core import logging_setup
from licensing import i18n
from licensing import licenses
from licensing.telegram import keyboards as kb
from licensing.telegram import setup_wizard
from licensing.telegram import texts as T
from licensing.telegram.sales.common import (
    HTML,
    _db,
    _is_admin,
    _notify,
    _notify_admins,
    _send,
    _supervisor,
    _use_user_language,
)


_NO_PASSWORD_MARKERS = setup_wizard.NO_PASSWORD_MARKERS
_SETUP_STEPS = setup_wizard.STEPS
_SETUP_PREFIX = "setup:"


def _setup_prompt(index):
    return setup_wizard.prompt(index)


def _setup_keyboard(index, state=None):
    return setup_wizard.step_keyboard(index, state, _SETUP_PREFIX)


def _may_setup(update, license_row):
    """
    کی حق داره برای این لایسنس ربات بسازه؟

    صاحب لایسنس، یا ادمین. اجازه‌ی ادمین لازمه چون «ساخت ربات نامحدود»
    توی پنل مدیریت، ربات رو *به‌جای* مشتری تنظیم می‌کنه.
    """
    if license_row is None:
        return False
    return int(license_row["user_id"]) == update.effective_user.id or _is_admin(update)


async def setup_start(update, context, license_id):
    db = _db(context)
    license_row = db.get_license(license_id)
    if not _may_setup(update, license_row):
        await _send(update, i18n.t("license_not_yours"))
        return
    if not licenses.is_valid(license_row):
        await _send(update, i18n.t("license_inactive"),
                    kb.license_actions(license_row, can_add_bot=False))
        return
    if len(db.instances_by_license(license_id)) >= int(license_row["max_bots"]):
        await _send(update, T.LICENSE_BOT_QUOTA_FULL,
                    kb.license_actions(license_row, can_add_bot=False))
        return

    state = setup_wizard.new_state(license_id)
    context.user_data["setup"] = state
    context.user_data["awaiting"] = "setup"
    await _send(update, T.SETUP_INTRO)
    await update.effective_chat.send_message(_setup_prompt(0), parse_mode=HTML,
                                             reply_markup=_setup_keyboard(0, state))


async def setup_handle_text(update, context, text):
    state = context.user_data.get("setup")
    if not state:
        context.user_data.pop("awaiting", None)
        await _send(update, T.UNKNOWN)
        return

    if await setup_wizard.answer_step(update, state, text, _SETUP_PREFIX, "nav:menu"):
        context.user_data.pop("awaiting", None)


async def setup_use_default(update, context, index):
    """
    دکمه‌ی پیش‌فرض: همون جواب رو از مسیر همیشگیِ متن رد می‌کنه، تا
    اعتبارسنجی‌ها فقط یه جا باشن.
    """
    state = context.user_data.get("setup")
    if not state or int(state.get("step", -1)) != int(index) or not (0 <= index < len(_SETUP_STEPS)):
        await _send(update, i18n.t("setup_missing_state"))
        return
    value = setup_wizard.default_for(index, state)
    if value is None:
        return
    context.user_data["awaiting"] = "setup"
    await setup_handle_text(update, context, str(value))


async def setup_apply(update, context, license_id):
    db = _db(context)
    state = context.user_data.get("setup")
    if not state or int(state.get("license_id", 0)) != int(license_id):
        await _send(update, i18n.t("setup_missing_state"))
        return

    license_row = db.get_license(license_id)
    if not _may_setup(update, license_row):
        await _send(update, i18n.t("license_not_yours"))
        return

    # ویرایش یه ربات موجود، نه ساخت ربات جدید: نه سهمیه مصرف می‌کنه، نه
    # slug/لاین صدای جدید می‌خواد.
    if state.get("instance_id"):
        await setup_apply_edit(update, context, license_row, state)
        return

    try:
        setup_wizard.check_can_add(db, license_row)
    except setup_wizard.WizardError as e:
        await _send(update, T.LICENSE_BOT_QUOTA_FULL if str(e) == "quota" else str(e))
        return

    await _send(update, i18n.t("setup_working"))
    try:
        instance = await asyncio.to_thread(
            setup_wizard.create, db, license_row, state, _supervisor(context))
    except setup_wizard.WizardError as e:
        await _send(update, T.LICENSE_BOT_QUOTA_FULL if str(e) == "quota" else str(e),
                    kb.back_to_menu())
        return
    except Exception:
        logging_setup.log_exception("creating instance")
        await _send(update, T.setup_failed(), kb.back_to_menu())
        return

    line_output, line_input = audio_lines.line_names(instance["audio_line"])
    context.user_data.pop("setup", None)
    await _send(update, T.setup_done(instance, line_output, line_input), kb.back_to_menu())
    await _notify_admins(
        context.application,
        i18n.t("admin_new_instance", slug=instance["slug"], host=instance["tt_host"],
               port=instance["tt_port"], key=license_row["key"]))

    # اگه ادمین این ربات رو برای یکی دیگه ساخته، خودِ مشتری باید خبردار
    # بشه -- وگرنه یه ربات آماده داره و ازش بی‌خبره.
    owner_id = int(license_row["user_id"])
    if owner_id != update.effective_user.id:
        _use_user_language(context, owner_id)
        await _notify(context.application, owner_id,
                      i18n.t("admin_gift_bot_ready", key=license_row["key"],
                             slug=instance["slug"], host=instance["tt_host"],
                             port=instance["tt_port"]),
                      kb.license_actions(license_row, can_add_bot=True))


async def setup_edit_start(update, context, instance_id):
    """
    ویرایش مشخصات یه ربات موجود: *همون* ویزارد، ولی از مقدارهای فعلی پر
    شده. هر مرحله یه دکمه‌ی «همین بمونه» داره.
    """
    db = _db(context)
    instance = db.get_instance(instance_id)
    if instance is None:
        await _send(update, i18n.t("bot_not_found"), kb.back_to_menu())
        return
    license_row = db.get_license(int(instance["license_id"]))
    if not _may_setup(update, license_row):
        await _send(update, i18n.t("bot_not_yours"), kb.back_to_menu())
        return

    state = setup_wizard.state_from_instance(instance)
    context.user_data["setup"] = state
    context.user_data["awaiting"] = "setup"
    await _send(update, i18n.t("setup_edit_intro", slug=T.esc(instance["slug"])))
    await update.effective_chat.send_message(_setup_prompt(0), parse_mode=HTML,
                                             reply_markup=_setup_keyboard(0, state))


async def setup_apply_edit(update, context, license_row, state):
    """
    مقدارهای جدید رو می‌نویسه، کانفیگ روی دیسک رو دوباره می‌سازه و ربات رو
    ری‌استارت می‌کنه. لاین صدا و slug دست‌نخورده می‌مونن.
    """
    db = _db(context)
    await _send(update, i18n.t("setup_working"))
    try:
        instance = await asyncio.to_thread(
            setup_wizard.update, db, license_row, state, _supervisor(context))
    except setup_wizard.WizardError as e:
        await _send(update, str(e), kb.back_to_menu())
        return
    except Exception:
        logging_setup.log_exception("updating instance")
        await _send(update, T.setup_failed(), kb.back_to_menu())
        return

    context.user_data.pop("setup", None)
    await _send(update, i18n.t("setup_edit_done", slug=T.esc(instance["slug"]),
                               host=T.esc(instance["tt_host"]), port=instance["tt_port"]),
                kb.instance_actions(instance, is_admin=_is_admin(update)))

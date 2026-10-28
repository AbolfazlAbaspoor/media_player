"""
لایسنس‌ها و ربات‌های خودِ کاربر: کارت لایسنس، تمدید، افزودن امکانات، کنترل ربات‌ها.
"""

import asyncio

from core import logging_setup
from licensing import catalog
from licensing import expiry
from licensing import i18n
from licensing import licenses
from licensing import provisioning
from licensing.db import json_list
from licensing.telegram import keyboards as kb
from licensing.telegram import texts as T
from licensing.telegram.sales.common import (
    _cfg_state,
    _db,
    _is_admin,
    _notify,
    _send,
    _supervisor,
    _use_user_language,
    _user_row,
)
from licensing.telegram.sales.purchase import show_invoice


async def show_licenses(update, context):
    db = _db(context)
    user_row = _user_row(update, context)
    rows = db.licenses_by_user(user_row["telegram_id"])
    if not rows:
        await _send(update, T.NO_LICENSE, kb.back_to_menu())
        return
    await _send(update, i18n.t("licenses_title"), kb.license_list(rows))


async def show_license(update, context, license_id):
    db = _db(context)
    license_row = expiry.check_one(db, license_id, supervisor=_supervisor(context))
    if license_row is None or (
        int(license_row["user_id"]) != update.effective_user.id and not _is_admin(update)
    ):
        await _send(update, i18n.t("license_not_found"))
        return
    instances = db.instances_by_license(license_id)
    _status, status_text = licenses.describe_status(license_row)
    can_add = licenses.is_valid(license_row) and len(instances) < int(license_row["max_bots"])
    await _send(update, T.license_card(license_row, status_text, instances),
                kb.license_actions(license_row, can_add, is_admin=_is_admin(update)))


async def admin_delete_license(update, context, license_id, confirmed=False):
    """
    پاک‌کردن کاملِ یه لایسنس از سمت ادمین.

    ترتیب مهمه و همونیه که توی licensing/provisioning.py توضیح داده شده:
    اول ربات‌ها خاموش و لاین صداشون آزاد و دیتاشون پاک، *بعد* ردیف‌های
    دیتابیس. برعکسش یعنی ربات‌های یتیم که هیچ‌جا ثبت نیستن ولی روی سرور
    در حال اجران.

    این با /revoke فرق داره: revoke لایسنس رو «لغوشده» نگه می‌داره (برای
    تاریخچه و امکان بازگردوندن)، این یکی واقعاً پاکش می‌کنه.
    """
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    db = _db(context)
    license_row = db.get_license(license_id)
    if license_row is None:
        await _send(update, i18n.t("license_not_found"), kb.admin_back())
        return

    instances = db.instances_by_license(license_id)
    if not confirmed:
        await _send(update,
                    i18n.t("admin_license_delete_confirm", key=T.esc(license_row["key"]),
                           user_id=license_row["user_id"], bots=len(instances)),
                    kb.confirm(f"lic:delok:{license_id}", f"lic:show:{license_id}",
                               i18n.t("btn_delete_yes")))
        return

    await _send(update, i18n.t("setup_working"))
    supervisor = _supervisor(context)
    try:
        _row, results, errors = await asyncio.to_thread(
            provisioning.delete_license_completely, db, license_id, supervisor,
            "deleted by admin", update.effective_user.id)
    except Exception:
        logging_setup.log_exception("deleting licence")
        await _send(update, T.UNEXPECTED_ERROR, kb.admin_back())
        return

    owner_id = int(license_row["user_id"])

    text = i18n.t("admin_license_deleted", key=T.esc(license_row["key"]), bots=len(results))
    if errors:
        text += i18n.t("bot_deleted_errors", errors="\n".join(f"  • {e}" for e in errors))
    await _send(update, text, kb.admin_back())

    if owner_id != update.effective_user.id:
        _use_user_language(context, owner_id)
        await _notify(context.application, owner_id,
                      i18n.t("license_deleted_notice", key=license_row["key"]))


async def start_renew(update, context, license_id):
    db = _db(context)
    license_row = db.get_license(license_id)
    if license_row is None or int(license_row["user_id"]) != update.effective_user.id:
        await _send(update, i18n.t("license_not_yours"))
        return
    await _send(update,
                i18n.t("renew_title", key=license_row["key"]) + "\n\n"
                + i18n.t("renew_hint"),
                kb.renew_durations(license_id))


async def renew_with_months(update, context, license_id, months):
    db = _db(context)
    license_row = db.get_license(license_id)
    if license_row is None or int(license_row["user_id"]) != update.effective_user.id:
        await _send(update, i18n.t("license_not_yours"))
        return
    state = _cfg_state(context)
    state.update({
        "months": int(months),
        "bots": int(license_row["max_bots"]),
        "features": catalog.expand_features(json_list(license_row["features"])),
        "kind": "renew",
        "license_id": int(license_id),
        "panel_code": None,
    })
    await show_invoice(update, context)


async def start_addon(update, context, license_id):
    db = _db(context)
    license_row = db.get_license(license_id)
    if license_row is None or int(license_row["user_id"]) != update.effective_user.id:
        await _send(update, i18n.t("license_not_yours"))
        return

    remaining_days = max(1, licenses.seconds_left(license_row) // 86400)
    months = max(1, int(round(remaining_days / 30)))
    state = _cfg_state(context)
    state.update({
        "months": months,
        "bots": int(license_row["max_bots"]),
        "features": catalog.expand_features(json_list(license_row["features"])),
        "kind": "addon",
        "license_id": int(license_id),
        "panel_code": None,
    })
    await _send(update,
                i18n.t("addon_title", key=license_row["key"]) + "\n\n"
                + i18n.t("addon_hint", days=remaining_days, months=months),
                kb.feature_picker(state["features"], target="cfg"))


async def _owned_instance(update, context, instance_id):
    """
    (ربات، لایسنسش) برای رباتِ مالِ خودِ کاربر (یا هر رباتی برای ادمین). اگه
    نبود یا مالِ کس دیگه‌ای بود خودش جواب می‌ده و None برمی‌گردونه.
    """
    db = _db(context)
    instance = db.get_instance(instance_id)
    if instance is None:
        await _send(update, i18n.t("bot_not_found"))
        return None
    license_row = db.get_license(int(instance["license_id"]))
    if license_row is None or (
        int(license_row["user_id"]) != update.effective_user.id and not _is_admin(update)
    ):
        await _send(update, i18n.t("bot_not_yours"))
        return None
    return instance, license_row


async def show_instances(update, context, license_id=None):
    db = _db(context)
    if license_id:
        license_row = db.get_license(license_id)
        if license_row is None or (
            int(license_row["user_id"]) != update.effective_user.id and not _is_admin(update)
        ):
            await _send(update, i18n.t("license_not_found"))
            return
        rows = db.instances_by_license(license_id)
        back = f"lic:show:{license_id}"
    else:
        rows = db.instances_by_user(update.effective_user.id)
        back = "nav:menu"

    if not rows:
        await _send(update, i18n.t("no_bots"), kb.back_to_menu())
        return
    await _send(update, i18n.t("bots_title"), kb.instance_list(rows, back))


async def show_instance(update, context, instance_id):
    owned = await _owned_instance(update, context, instance_id)
    if owned is None:
        return
    instance, _license_row = owned

    supervisor = _supervisor(context)
    live = None
    if supervisor is not None:
        live = next((item for item in supervisor.status() if item["slug"] == instance["slug"]), None)
    await _send(update, T.instance_card(instance, live),
                kb.instance_actions(instance, _is_admin(update)))


async def instance_action(update, context, action, instance_id):
    owned = await _owned_instance(update, context, instance_id)
    if owned is None:
        return
    instance, license_row = owned
    db = _db(context)

    supervisor = _supervisor(context)
    if supervisor is None:
        await _send(update, i18n.t("no_supervisor"))
        return

    if action == "restart":
        if not licenses.is_valid(license_row):
            await _send(update, i18n.t("bot_license_inactive"))
            return
        await asyncio.to_thread(supervisor.restart, instance["slug"])
        await _send(update, i18n.t("bot_restarted"))
    elif action == "stop":
        await asyncio.to_thread(supervisor.stop, instance["slug"])
        await _send(update, i18n.t("bot_stopped"))
    elif action == "start":
        if not licenses.is_valid(license_row):
            await _send(update, i18n.t("bot_license_inactive"))
            return
        await asyncio.to_thread(supervisor.start_instance, instance)
        await _send(update, i18n.t("bot_started"))
    elif action == "del":
        await _send(update,
                    i18n.t("bot_delete_confirm", slug=instance["slug"]),
                    kb.confirm(f"inst:delok:{instance_id}", f"inst:show:{instance_id}",
                               i18n.t("btn_delete_yes")))
        return
    elif action == "delok":
        result = await asyncio.to_thread(
            provisioning.deprovision_instance, db, instance, True, supervisor)
        errors = "\n".join(f"  • {e}" for e in result["errors"])
        await _send(update,
                    i18n.t("bot_deleted")
                    + (i18n.t("bot_deleted_errors", errors=errors) if errors else ""),
                    kb.back_to_menu())
        return

    await show_instance(update, context, instance_id)

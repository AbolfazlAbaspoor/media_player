"""
پیام همگانی از پنل ادمین (C1): /broadcast یا دکمه‌ی «📣 پیام همگانی».

جریان: ادمین محتوا رو می‌فرسته (هر نوعی) -> مخاطب رو انتخاب می‌کنه (همه /
لایسنسِ فعال دارن / ندارن) -> تعداد گیرنده و پیش‌نمایش رو می‌بینه و تأیید
می‌کنه -> ارسال به‌عنوان یه تسکِ پس‌زمینه شروع می‌شه (قابل لغو) -> در آخر
گزارش می‌رسه.
"""

import asyncio

from licensing import broadcast as broadcast_module
from licensing import i18n
from licensing.telegram import keyboards as kb
from licensing.telegram import texts as T
from licensing.telegram.sales.common import _db, _is_admin, _send

_JOB_KEY = "broadcast"


def _current_job(context):
    return context.application.bot_data.get(_JOB_KEY)


def _audience_title_key(audience):
    return {
        broadcast_module.AUDIENCE_ALL: "broadcast_audience_all",
        broadcast_module.AUDIENCE_ACTIVE: "broadcast_audience_active",
        broadcast_module.AUDIENCE_INACTIVE: "broadcast_audience_inactive",
    }[audience]


def _preview_text(message):
    text = message.text or message.caption
    if text:
        return text if len(text) <= 300 else text[:300] + "…"
    if message.photo:
        return i18n.t("broadcast_kind_photo")
    if message.video:
        return i18n.t("broadcast_kind_video")
    if message.voice or message.audio:
        return i18n.t("broadcast_kind_voice")
    if message.document:
        return i18n.t("broadcast_kind_document")
    return i18n.t("broadcast_kind_other")


async def broadcast_start(update, context):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    job = _current_job(context)
    if job is not None and not job.done:
        await _send(update, i18n.t("broadcast_already_running"), kb.admin_back())
        return
    context.user_data.pop("broadcast_draft", None)
    context.user_data["awaiting"] = "broadcast_content"
    await _send(update, i18n.t("broadcast_ask_content"))


async def broadcast_capture(update, context):
    """
    پیامِ مبدأِ پخش رو ذخیره می‌کنه -- فقط chat_id/message_id، نه خودِ
    محتوا، چون فرستادن با copy_message انجام می‌شه (بدونِ نیاز به فهمیدنِ
    نوعش). فقط ادمین و فقط وقتی منتظرِ محتوا هستیم صدا زده می‌شه.
    """
    message = update.effective_message
    context.user_data.pop("awaiting", None)
    context.user_data["broadcast_draft"] = {
        "chat_id": message.chat_id,
        "message_id": message.message_id,
        "preview": _preview_text(message),
    }

    db = _db(context)
    counts = {audience: len(broadcast_module.recipients(db, audience))
              for audience in broadcast_module.AUDIENCES}
    await _send(update, i18n.t("broadcast_pick_audience"), kb.broadcast_audiences(counts))


async def broadcast_pick_audience(update, context, audience):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    draft = context.user_data.get("broadcast_draft")
    if draft is None or audience not in broadcast_module.AUDIENCES:
        await _send(update, i18n.t("broadcast_content_lost"), kb.admin_back())
        return

    db = _db(context)
    count = len(broadcast_module.recipients(db, audience))
    draft["audience"] = audience
    text = "\n".join([
        i18n.t("broadcast_confirm_title"),
        i18n.t("broadcast_confirm_audience", audience=i18n.t(_audience_title_key(audience))),
        i18n.t("broadcast_confirm_count", count=count),
        "",
        i18n.t("broadcast_confirm_preview", preview=T.esc(draft["preview"])),
    ])
    if count == 0:
        await _send(update, text + "\n\n" + i18n.t("broadcast_no_recipients"), kb.admin_back())
        return
    await _send(update, text,
                kb.confirm(f"adm:bcastok:{audience}", "adm:panel", i18n.t("btn_broadcast_send")))


async def broadcast_send(update, context, audience):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    job = _current_job(context)
    if job is not None and not job.done:
        await _send(update, i18n.t("broadcast_already_running"), kb.admin_back())
        return

    draft = context.user_data.get("broadcast_draft")
    if draft is None or draft.get("audience") != audience:
        await _send(update, i18n.t("broadcast_content_lost"), kb.admin_back())
        return

    db = _db(context)
    ids = broadcast_module.recipients(db, audience)
    if not ids:
        await _send(update, i18n.t("broadcast_no_recipients"), kb.admin_back())
        return

    job = broadcast_module.BroadcastJob(
        admin_id=update.effective_user.id, audience=audience,
        from_chat_id=draft["chat_id"], message_id=draft["message_id"], total=len(ids))
    context.application.bot_data[_JOB_KEY] = job
    context.user_data.pop("broadcast_draft", None)

    application = context.application
    job.task = asyncio.create_task(broadcast_module.run(application.bot, db, job, ids))
    job.task.add_done_callback(lambda _t: asyncio.create_task(_report(application, job)))

    await _send(update, i18n.t("broadcast_started", count=len(ids)), kb.broadcast_running())


async def broadcast_cancel(update, context):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    job = _current_job(context)
    if job is None or job.done:
        await _send(update, i18n.t("broadcast_none_running"), kb.admin_back())
        return
    job.cancel()
    await _send(update, i18n.t("broadcast_cancel_requested"), kb.broadcast_running())


async def _report(application, job):
    """گزارشِ نهایی به همون ادمینی که پیام همگانی رو شروع کرده."""
    from licensing.telegram.sales.common import _notify

    text = i18n.t(
        "broadcast_report", sent=job.sent, blocked=job.blocked,
        failed=job.failed, total=job.total,
        cancelled_note=(i18n.t("broadcast_report_cancelled") if job.cancelled else ""))
    await _notify(application, job.admin_id, text, kb.admin_back())

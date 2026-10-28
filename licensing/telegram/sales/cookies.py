"""
مدیریتِ کوکی‌های (cookies.txt) هر رباتِ تیم‌تاک از تلگرام: مشتریِ صاحبِ لایسنس
و ادمین. بعد از اینکه یوتیوب شروع کرد «Sign in to confirm you're not a bot»
بدهد، ربات بدون کوکی روی بعضی سرورها کار نمی‌کنه.

جریان:
  ربات -> 🍪 کوکی‌ها (ck:menu) -> انتخابِ سرویس (ck:add) -> فایلِ .txt یا
  متنِ پیست‌شده -> اعتبارسنجی و ذخیره -> دکمه‌ی ری‌استارتِ ربات.
  حذف: ck:del -> تأیید -> ck:delok.

امنیت:
  * فقط مالکِ لایسنس یا ادمین (همون _owned_instance که بقیه‌ی دکمه‌های ربات
    استفاده می‌کنن) -- توی هر مرحله دوباره چک می‌شه، نه فقط موقع شروع.
  * محتوای کوکی هیچ‌وقت به چت برنمی‌گرده، حتی توی پیام خطا.
  * پیامِ پیست‌شده (بهترین تلاش) از چت پاک می‌شه.
  * اسم سرویس با cookie_files.check_service_name چک می‌شه (بدون path traversal).

state (context.user_data["cookies"]): {"iid": شناسه‌ی ربات, "service": اسم یا None}
و context.user_data["awaiting"] یکی از "cookie_upload" / "cookie_service".
"""

from telegram.error import TelegramError

from core import cookie_files
from core import logging_setup
from licensing import i18n
from licensing import provisioning
from licensing.telegram import cookie_upload
from licensing.telegram import keyboards as kb
from licensing.telegram import texts as T
from licensing.telegram.sales.common import _send
from licensing.telegram.sales.my_licenses import _owned_instance

# سرویس‌هایی که دکمه‌ی آماده دارن؛ بقیه با «سرویس دیگر».
COOKIES_COMMON_SERVICES = ("youtube", "instagram")
COOKIES_AWAITING = ("cookie_upload", "cookie_service")


def _cookies_bot_dir(instance):
    return provisioning.instance_dirs(instance)[1]


def _cookies_clear(context):
    context.user_data.pop("cookies", None)
    if context.user_data.get("awaiting") in COOKIES_AWAITING:
        context.user_data.pop("awaiting", None)


async def cookies_show(update, context, instance_id):
    """صفحه‌ی اصلی: کدوم سرویس‌ها کوکی دارن (فقط اسم، نه محتوا)."""
    _cookies_clear(context)
    owned = await _owned_instance(update, context, instance_id)
    if owned is None:
        return
    instance, _license_row = owned
    present = cookie_files.present(_cookies_bot_dir(instance))
    services = list(COOKIES_COMMON_SERVICES) + [n for n in present if n not in COOKIES_COMMON_SERVICES]
    stored = ", ".join(present) if present else i18n.t("cookies_none")
    await _send(update,
                i18n.t("cookies_menu_title", slug=T.esc(instance["slug"]), stored=T.esc(stored)),
                kb.cookies_menu(instance_id, services, set(present)))


def _cookies_arm(context, instance_id, service):
    context.user_data["cookies"] = {"iid": int(instance_id), "service": service}
    context.user_data["awaiting"] = "cookie_upload" if service else "cookie_service"


async def cookies_on_callback(update, context, action, instance_id, service=None):
    """دکمه‌های ck:*."""
    if action == "menu":
        await cookies_show(update, context, instance_id)
        return
    owned = await _owned_instance(update, context, instance_id)
    if owned is None:
        return
    instance, _license_row = owned

    if action == "other":
        _cookies_arm(context, instance_id, None)
        await _send(update, i18n.t("cookies_ask_name"), kb.cookies_cancel(instance_id))
        return

    try:
        service = cookie_files.check_service_name(service)
    except cookie_files.CookieError:
        await _send(update, i18n.t("cookies_bad_name"), kb.cookies_cancel(instance_id))
        return

    if action == "add":
        _cookies_arm(context, instance_id, service)
        await _send(update, i18n.t("cookies_ask", service=T.esc(service)),
                    kb.cookies_cancel(instance_id))
    elif action == "del":
        await _send(update,
                    i18n.t("cookies_delete_confirm", service=T.esc(service),
                           slug=T.esc(instance["slug"])),
                    kb.confirm(f"ck:delok:{instance_id}:{service}", f"ck:menu:{instance_id}",
                               i18n.t("btn_delete_yes")))
    elif action == "delok":
        removed = cookie_files.remove(_cookies_bot_dir(instance), service)
        key = "cookies_deleted" if removed else "cookies_delete_missing"
        await _send(update, i18n.t(key, service=T.esc(service)),
                    kb.cookies_saved_actions(instance_id) if removed
                    else kb.cookies_cancel(instance_id))


async def _cookies_save(update, context, data):
    """
    مشترکِ فایل و متن: دسترسی رو دوباره چک می‌کنه، اعتبارسنجی و ذخیره. هیچ
    متنی از محتوا یا از پیامِ استثنا به کاربر نمی‌ره.
    """
    state = context.user_data.get("cookies")
    if not state or not state.get("service"):
        await _send(update, i18n.t("cookies_expired"))
        return
    owned = await _owned_instance(update, context, state["iid"])
    if owned is None:
        _cookies_clear(context)
        return
    instance, _license_row = owned
    instance_id = int(state["iid"])
    try:
        cookie_files.write(_cookies_bot_dir(instance), state["service"], data)
    except cookie_files.CookieError as exc:
        reason = str(exc)
        key = {"too large": "cookies_too_large",
               "not a text file": "cookies_not_text"}.get(reason, "cookies_invalid")
        await _send(update, i18n.t(key), kb.cookies_cancel(instance_id))
        return
    except OSError:
        logging_setup.log_exception("saving cookies")
        await _send(update, T.UNEXPECTED_ERROR, kb.cookies_cancel(instance_id))
        return
    service = state["service"]
    _cookies_clear(context)
    await _send(update, i18n.t("cookies_saved_restart", service=T.esc(service)),
                kb.cookies_saved_actions(instance_id))


async def cookies_on_text(update, context, text):
    """متنِ پیست‌شده (یا اسمِ سرویسِ «سرویس دیگر»)."""
    state = context.user_data.get("cookies")
    if not state:
        context.user_data.pop("awaiting", None)
        await _send(update, i18n.t("cookies_expired"))
        return

    if context.user_data.get("awaiting") == "cookie_service":
        try:
            service = cookie_files.check_service_name(text)
        except cookie_files.CookieError:
            await _send(update, i18n.t("cookies_bad_name"), kb.cookies_cancel(state["iid"]))
            return
        _cookies_arm(context, state["iid"], service)
        await _send(update, i18n.t("cookies_ask", service=T.esc(service)),
                    kb.cookies_cancel(state["iid"]))
        return

    # پیامِ حاوی کوکی رو همین اول پاک می‌کنیم (بهترین تلاش)، چه معتبر باشه چه نه.
    try:
        await update.effective_message.delete()
    except TelegramError:
        pass
    await _cookies_save(update, context, text)


async def cookies_on_document(update, context):
    """فایلِ .txt. حجم قبل از دانلود چک می‌شه تا فایلِ بزرگ اصلاً کشیده نشه."""
    document = update.effective_message.document
    state = context.user_data.get("cookies")
    if not state or not state.get("service"):
        context.user_data.pop("awaiting", None)
        await _send(update, i18n.t("cookies_expired"))
        return
    data, problem = await cookie_upload.fetch_cookie_document(document)
    if problem is not None:
        key = "cookies_too_large" if problem == cookie_upload.TOO_LARGE else "cookies_download_failed"
        await _send(update, i18n.t(key), kb.cookies_cancel(state["iid"]))
        return
    try:
        await update.effective_message.delete()
    except TelegramError:
        pass
    await _cookies_save(update, context, data)

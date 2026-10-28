"""
پیام‌های غیرمتنی/غیرعکسی که ربات فروش قبلاً هیچ هندلری براشون نداشت: سند
(فایل)، ویدیو، صدا. دو استفاده‌ی امروزشون: محتوای پیام همگانی (C1، هر
نوعی) و لاگ خطای رمزشده‌ی مشتری (B8، فقط سند).

عمداً جدا از on_photo/on_text: قبلاً فرستادنِ ویدیو/صدا/فایل به این ربات
هیچ پاسخی نداشت (نه هندلری ثبت شده بود)، پس این فایل یه قابلیتِ تازه‌ست،
نه جایگزینِ چیزی.
"""

from licensing.telegram import keyboards as kb
from licensing.telegram import texts as T
from licensing.telegram.sales.admin_errors import ERRORS_LOG_TRIGGERS, handle_errors_document
from licensing.telegram.sales.broadcast import broadcast_capture
from licensing.telegram.sales.common import _db, _is_admin, _send, _user_row
from licensing.telegram.sales.cookies import COOKIES_AWAITING, cookies_on_document


async def _fallback(update, context, user_row):
    await _send(update, T.UNKNOWN, kb.main_menu(
        bool(_db(context).licenses_by_user(user_row["telegram_id"])), _is_admin(update)))


async def on_document(update, context):
    if context.user_data.get("awaiting") in COOKIES_AWAITING:
        # آپلودِ کوکی: هم مشتری هم ادمین (دسترسی به ربات توی خودِ هندلر چک می‌شه).
        user_row = _user_row(update, context)
        if user_row["blocked"]:
            await _send(update, T.BLOCKED)
            return
        await cookies_on_document(update, context)
        return
    if _is_admin(update):
        awaiting = context.user_data.get("awaiting")
        caption = (update.effective_message.caption or "").strip().lower()
        if awaiting == "errors_log" or caption.startswith(ERRORS_LOG_TRIGGERS):
            await handle_errors_document(update, context)
            return
        if awaiting == "broadcast_content":
            await broadcast_capture(update, context)
            return

    user_row = _user_row(update, context)
    if user_row["blocked"]:
        await _send(update, T.BLOCKED)
        return
    await _fallback(update, context, user_row)


async def on_other_media(update, context):
    """ویدیو/صدا -- امروز فقط برای محتوای پیام همگانی معنی داره."""
    if _is_admin(update) and context.user_data.get("awaiting") == "broadcast_content":
        await broadcast_capture(update, context)
        return

    user_row = _user_row(update, context)
    if user_row["blocked"]:
        await _send(update, T.BLOCKED)
        return
    await _fallback(update, context, user_row)

"""
باز کردنِ لاگ خطای رمزشده‌ی مشتری از داخل تلگرام (بخشی از B8؛ معادلِ
`manage.py read-errors`).

ادمین فایلِ errors.log رو به‌عنوانِ سند می‌فرسته -- یا بعدِ زدنِ دکمه، یا
مستقیم با کپشنِ /readerrors -- و یه فایلِ .txتِ رمزگشایی‌شده پس می‌گیره.
هیچ‌وقت برای غیرِ ادمین (چک اصلی توی media_input.py، قبل از صدازدنِ این
ماژول، انجام می‌شه).
"""

import io
import os

from telegram.error import TelegramError

from core import error_crypt
from core import logging_setup
from core.paths import get_base_dir
from licensing import i18n
from licensing.telegram import keyboards as kb
from licensing.telegram import texts as T
from licensing.telegram.sales.common import _admin_ask, _db, _is_admin, _send

#: کپشن‌هایی که یعنی «این فایل رو رمزگشایی کن» -- برای فرستادنِ فایل و
#: دستور توی یه پیام (به‌جای دکمه‌ی جدا).
ERRORS_LOG_TRIGGERS = ("/readerrors", "/errors")

#: لاگ‌های مشتری معمولاً چند ده کیلوبایت تا چند مگابایتن؛ سقف سخاوتمندانه
#: ولی محدود، تا یه فایلِ عجیب حافظه‌ی پروسه رو پر نکنه.
MAX_ERRORS_LOG_BYTES = 15 * 1024 * 1024

_PRIVATE_KEY_PATH = os.path.join(get_base_dir(), "data", "licensing", "keys", "errors_private.key")


def _load_private_key():
    try:
        with open(_PRIVATE_KEY_PATH, "r", encoding="ascii") as f:
            return f.read().strip()
    except OSError:
        return None


async def admin_errors_start(update, context):
    """دکمه‌ی «🔓 بازکردنِ لاگِ خطا» توی /admin."""
    await _admin_ask(update, context, _is_admin(update), _send, "errors_log", "admin_errors_ask_file")


async def handle_errors_document(update, context):
    """فایلِ errors.log رسیده -- رمزگشایی کن و یه .txt پس بفرست."""
    if not _is_admin(update):
        return
    context.user_data.pop("awaiting", None)

    document = update.effective_message.document
    if document is None:
        await _send(update, i18n.t("admin_errors_ask_file"))
        return
    if document.file_size and document.file_size > MAX_ERRORS_LOG_BYTES:
        await _send(update, i18n.t("admin_errors_too_big"), kb.admin_back())
        return

    private_b64 = _load_private_key()
    if not private_b64:
        await _send(update, i18n.t("admin_errors_no_key", path=T.esc(_PRIVATE_KEY_PATH)),
                    kb.admin_back())
        return

    try:
        telegram_file = await document.get_file()
        raw = bytes(await telegram_file.download_as_bytearray())
    except TelegramError:
        logging_setup.log_exception("downloading errors.log for decryption")
        await _send(update, i18n.t("admin_errors_download_failed"), kb.admin_back())
        return

    raw_text = raw.decode("utf-8", "replace")
    output_text, decrypted, plain, failed = error_crypt.decrypt_log_text(raw_text, private_b64)

    summary = i18n.t("admin_errors_summary", decrypted=decrypted, plain=plain, failed=failed)
    buffer = io.BytesIO((output_text or i18n.t("admin_errors_empty")).encode("utf-8"))
    buffer.name = "errors_decrypted.txt"
    await update.effective_message.reply_document(buffer, caption=summary)

    _db(context).log_event(
        "errors_log_decrypted", user_id=update.effective_user.id,
        detail={"decrypted": decrypted, "plain": plain, "failed": failed})

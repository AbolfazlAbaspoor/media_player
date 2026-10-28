"""
ساختن Application ربات فروش: ثبت هندلرها و تسک‌های پس‌زمینه.
"""

import asyncio

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
from licensing import config
from licensing import i18n
from licensing import telegram as telegram_layer
from licensing.telegram import channel_gate
from licensing.telegram.sales.admin_catalog import cmd_catalog, cmd_quote
from licensing.telegram.sales.admin_commands import (
    cmd_admin_commands,
    cmd_card,
    cmd_extend,
    cmd_grant,
    cmd_license_info,
    cmd_pubkey,
    cmd_rate,
    cmd_reload,
    cmd_reply,
    cmd_resume,
    cmd_revoke,
    cmd_say,
    cmd_suspend,
)
from licensing.telegram.sales.admin_errors import admin_errors_start
from licensing.telegram.sales.admin_grants import admin_rental_reset_start
from licensing.telegram.sales.admin_licenses import admin_licenses_list
from licensing.telegram.sales.admin_gc import gc_start
from licensing.telegram.sales.admin_panel import (
    admin_bots,
    admin_lines,
    admin_panel,
    admin_pending,
    admin_sweep,
    admin_tickets,
)
from licensing.telegram.sales.background import (
    _cookie_alert_loop,
    _crypto_poll_loop,
    _daily_report_loop,
    _nightly_loop,
    _order_timeout_loop,
    _rate_refresh_loop,
)
from licensing.telegram.sales.broadcast import broadcast_start
from licensing.telegram.sales.callbacks import on_callback, on_error
from licensing.telegram.sales.common import _notify_admins
from licensing.telegram.sales.media_input import on_document, on_other_media
from licensing.telegram.sales.menu import cmd_cancel, cmd_help, cmd_start, language_menu
from licensing.telegram.sales.my_licenses import show_instances, show_licenses
from licensing.telegram.sales.payment import on_photo
from licensing.telegram.sales.promo_codes import (
    cmd_gift,
    cmd_promo,
    cmd_promoadd,
    cmd_promooff,
    redeem_start,
)
from licensing.telegram.sales.purchase import show_panels
from licensing.telegram.sales.support import support_start
from licensing.telegram.sales.text_input import on_text


def build_application(db, supervisor=None, runner=None):
    token = config.get("sales_bot_token")
    if not token:
        raise RuntimeError("the sales bot token is not configured")

    # کاتالوگ رو با سرویس‌ها/دستورهای واقعیِ روی دیسک همگام کن.
    #
    # بدون این، اضافه‌کردن یه سرویس جدید بی‌صدا شکست می‌خورد: فایل روی
    # دیسک بود و لود هم می‌شد، ولی چون توی کاتالوگ ثبت نشده بود،
    # license_gate روی هر ربات لایسنس‌دار حذفش می‌کرد -- بدون هیچ خطایی.
    # اینجا حداقل «قابل‌فروش و قابل‌دیدن» می‌شه؛ قیمتش رو ادمین تنظیم می‌کنه.
    try:
        from licensing import sync as sync_module
        created = sync_module.autoregister(persist=True)
        if created:
            print(f"[Catalog] {len(created)} امکان تازه خودکار ثبت شد: {', '.join(created)}")
            print(f"[Catalog] قیمت‌هاشون رو توی {catalog.OVERRIDE_FILE} تنظیم کن.")
    except Exception:
        logging_setup.log_exception("auto-syncing the catalog")

    application = telegram_layer.apply_network(Application.builder().token(token)).build()
    application.bot_data["db"] = db
    application.bot_data["supervisor"] = supervisor
    application.bot_data["runner"] = runner

    # عضویت اجباری کانال: قبل از بقیه، وگرنه دکمه‌ی «عضو شدم» رو
    # CallbackQueryHandler عمومی می‌گرفت.
    channel_gate.register(application)

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("cancel", cmd_cancel))
    application.add_handler(CommandHandler("buy", show_panels))
    application.add_handler(CommandHandler("licenses", show_licenses))
    application.add_handler(CommandHandler("mybots", show_instances))
    application.add_handler(CommandHandler("support", support_start))
    application.add_handler(CommandHandler("language", language_menu))
    application.add_handler(CommandHandler("lang", language_menu))
    application.add_handler(CommandHandler("redeem", redeem_start))
    application.add_handler(CommandHandler("promo", cmd_promo))
    application.add_handler(CommandHandler("promoadd", cmd_promoadd))
    application.add_handler(CommandHandler("promooff", cmd_promooff))
    application.add_handler(CommandHandler("gift", cmd_gift))
    application.add_handler(CommandHandler("renew", show_licenses))

    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("pending", admin_pending))
    application.add_handler(CommandHandler("rate", cmd_rate))
    application.add_handler(CommandHandler("card", cmd_card))
    application.add_handler(CommandHandler("grant", cmd_grant))
    application.add_handler(CommandHandler("extend", cmd_extend))
    application.add_handler(CommandHandler("suspend", cmd_suspend))
    application.add_handler(CommandHandler("resume", cmd_resume))
    application.add_handler(CommandHandler("revoke", cmd_revoke))
    application.add_handler(CommandHandler("license", cmd_license_info))
    application.add_handler(CommandHandler("bots", admin_bots))
    application.add_handler(CommandHandler("lines", admin_lines))
    application.add_handler(CommandHandler("sweep", admin_sweep))
    application.add_handler(CommandHandler("gc", gc_start))
    application.add_handler(CommandHandler("tickets", admin_tickets))
    application.add_handler(CommandHandler("reply", cmd_reply))
    application.add_handler(CommandHandler("say", cmd_say))
    application.add_handler(CommandHandler("reload", cmd_reload))
    application.add_handler(CommandHandler("pubkey", cmd_pubkey))
    application.add_handler(CommandHandler("commands", cmd_admin_commands))
    application.add_handler(CommandHandler("broadcast", broadcast_start))
    application.add_handler(CommandHandler("readerrors", admin_errors_start))
    application.add_handler(CommandHandler("catalog", cmd_catalog))
    application.add_handler(CommandHandler("quote", cmd_quote))
    application.add_handler(CommandHandler("rentalreset", admin_rental_reset_start))
    # /licenses (بالاتر) لایسنس‌های خودِ کاربره؛ این یکی لیستِ همه‌ی
    # لایسنس‌های سرور برای ادمینه (B8).
    application.add_handler(CommandHandler("alllicenses", admin_licenses_list))

    application.add_handler(CallbackQueryHandler(on_callback))
    application.add_handler(MessageHandler(filters.PHOTO, on_photo))
    application.add_handler(MessageHandler(filters.Document.ALL, on_document))
    application.add_handler(MessageHandler(filters.VIDEO | filters.VOICE | filters.AUDIO, on_other_media))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    application.add_error_handler(on_error)

    async def _post_init(app):
        app.bot_data["tasks"] = [
            asyncio.create_task(_nightly_loop(app)),
            asyncio.create_task(_order_timeout_loop(app)),
            asyncio.create_task(_rate_refresh_loop(app)),
            asyncio.create_task(_crypto_poll_loop(app)),
            asyncio.create_task(_daily_report_loop(app)),
            asyncio.create_task(_cookie_alert_loop(app)),
            asyncio.create_task(channel_gate.membership_loop(app)),
        ]
        # لاین‌های صدا بعد از ریبوت سرور از بین رفتن؛ قبل از هر چیزی
        # بازسازی می‌شن تا ربات‌هایی که سوپروایزر بالا می‌آره صدا داشته باشن.
        restored = await asyncio.to_thread(audio_lines.ensure_all_lines)
        if restored:
            await _notify_admins(app, i18n.t("lines_restored", count=restored))
        if supervisor is not None:
            supervisor.start()
        if runner is not None:
            # ربات فروش رو به runner می‌دیم تا اگه توکنِ یه ربات شخصی
            # باطل شد (E11)، بتونه از همینجا (نه از ربات مرده‌ی خودش) به
            # مالکش خبر بده.
            runner.set_sales_bot(app.bot)
            await runner.start_all()

    async def _post_shutdown(app):
        for task in app.bot_data.get("tasks", []):
            task.cancel()

    application.post_init = _post_init
    application.post_shutdown = _post_shutdown
    return application

"""
نقطه‌ی شروع پلتفرم لایسنس. روی سرور همین یه فایل اجرا می‌شه:

    python license_server.py

سه چیز رو هم‌زمان بالا می‌آره:

    ۱. ربات فروش/لایسنس تلگرام
    ۲. سوپروایزر ربات‌های مشتری‌ها (پروسه‌های bot.py)
    ۳. ربات‌های شخصی مشتری‌ها (هر کدوم با توکن خودش)

نسخه‌ی self-host (API لایسنس + توکن امضاشده‌ی client) بازنشسته شده؛ همه‌ی
ربات‌ها یا میزبانی می‌شن (license.json مستقیم توسط پلتفرم نوشته می‌شه) یا
اجاره‌ای‌اند (core/license_remote.py، مقابل Cloudflare KV). کلید امضای
Ed25519 همچنان اینجا ساخته می‌شه، ولی فقط برای Cloudflare Worker
(`manage.py worker-key`/`deploy-worker`) -- نه برای یه API لایسنس محلی.

گزینه‌ها:
    --no-hosting     ربات‌های تیم‌تاک رو اجرا نکن (فقط فروش)
    --no-personal    ربات‌های شخصی مشتری‌ها رو اجرا نکن
    --check          فقط بررسی کن همه‌چیز آماده‌ست و خارج شو
    --init           فایل‌های کانفیگ نمونه رو بساز و خارج شو
"""

import os
import sys


from core import logging_setup
from core import paths
from core import audio_lines
from core import platform_paths

paths.force_utf8_console()
from licensing import config
from licensing import catalog
from licensing import db as db_module
from licensing import keys
from licensing import supervisor as supervisor_module


def init_files():
    """
    فایل‌های کانفیگ/کلید/دیتابیسِ پلتفرم رو (اگه نیستن) می‌سازه و لیستِ
    چیزهایی که *همین الان* ساخته شد رو برمی‌گردونه. idempotent. هم
    `--init` هم ویزارد configure.py ازش استفاده می‌کنن.
    """
    created = []
    if config.write_template():
        created.append(config.CONFIG_FILE)
    if catalog.write_override_template():
        created.append(catalog.OVERRIDE_FILE)
    try:
        # همون کلید امضای Ed25519 که بعداً `manage.py deploy-worker`/`worker-key`
        # می‌ذارتش روی Cloudflare Worker (لایسنس اجاره‌ای).
        private_path, public_path = keys.ensure_keypair()
        created.append(private_path)
    except keys.SigningUnavailable as e:
        print(f"[Init] کلید امضا ساخته نشد: {e}")

    db_module.get_db()
    created.append(db_module.DB_PATH)
    return created


def cmd_init():
    created = init_files()

    if created:
        print("ساخته/آماده شد:")
        for path in created:
            print(f"  - {path}")
    else:
        print("همه‌ی فایل‌های کانفیگ از قبل وجود دارن؛ چیزی عوض نشد.")

    print()
    print("قدم بعدی: توکن ربات و آیدی تلگرامت رو توی این فایل بنویس:")
    print(f"  {config.CONFIG_FILE}")
    print()
    print("یا با متغیر محیطی:")
    print("  export LICENSING_BOT_TOKEN=123456:AA...")
    print("  export LICENSING_ADMIN_IDS=123456789")
    return 0


def _telegram_reachable(timeout=20):
    """
    (ok, detail) -- واقعاً یه getMe می‌زنه.

    چک‌کردن «توکن نوشته شده یا نه» کافی نیست: شایع‌ترین خرابیِ این پلتفرم
    روی سرور ایران، رسیدننکردن به api.telegram.org است، و بدون این چک
    --check می‌گفت «همه‌چیز آماده‌ست» درحالی‌که ربات هیچ‌وقت بالا نمی‌آمد.
    """
    import asyncio

    from telegram import Bot
    from licensing.telegram import request_kwargs

    async def probe():
        bot = Bot(config.get("sales_bot_token"), **request_kwargs())
        async with bot:
            me = await bot.get_me()
            return me.username or str(me.id)

    try:
        return True, asyncio.run(asyncio.wait_for(probe(), timeout))
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:160]}"


def cmd_check():
    print(f"محیط اجرا: {platform_paths.describe_runtime()}")
    print(f"لاین صدا: backend={audio_lines.backend()}, "
          f"قابل ساخت={audio_lines.backend_is_manageable()}")

    problems = []

    for problem in platform_paths.missing_runtime_requirements():
        problems.append(("ربات", problem))

    if audio_lines.backend() == "none":
        problems.append(("لاین صدا",
                         "هیچ backend ای برای لاین صدا نیست. روی لینوکس: "
                         "sudo apt install pulseaudio-utils"))
    elif audio_lines.backend() == "pulse" and not audio_lines.pulse_available():
        problems.append(("لاین صدا",
                         "pactl هست ولی به سرور صدا وصل نشد. اگه با systemd اجرا می‌کنی، "
                         "سرویس کاربری بساز و linger رو فعال کن: "
                         "sudo loginctl enable-linger $USER"))

    for problem in config.missing_required():
        problems.append(("پلتفرم", problem))

    try:
        keys.public_key_b64()
        print("کلید امضا (برای Cloudflare Worker): آماده")
    except keys.SigningUnavailable as e:
        problems.append(("کلید امضا", str(e)))

    try:
        database = db_module.get_db()
        stats = database.stats()
        print(f"دیتابیس: {db_module.DB_PATH}")
        print(f"  کاربر: {stats['users']}، لایسنس فعال: {stats['licenses_active']}، "
              f"ربات: {stats['instances_total']}")
    except Exception as e:
        problems.append(("دیتابیس", str(e)))

    try:
        from licensing import receipts
        print(f"بررسی رسید (OCR): {'آماده' if receipts.ocr_available() else 'نصب نیست'}")
        if not receipts.ocr_available():
            print("  برای فعال‌کردن: pip install pytesseract Pillow && "
                  "sudo apt install tesseract-ocr tesseract-ocr-fas")
            print("  (بدون این هم کار می‌کنه؛ رسیدها مستقیم می‌رن برای بررسی دستی)")
    except Exception as e:
        print(f"بررسی رسید: خطا — {e}")

    try:
        import telegram
        print(f"python-telegram-bot: {telegram.__version__}")
    except ImportError:
        problems.append(("تلگرام", "python-telegram-bot نصب نیست: "
                                   "pip install 'python-telegram-bot>=20.7'"))
    else:
        proxy = config.proxy_url()
        print(f"پروکسی تلگرام: {proxy or 'تنظیم نشده (پروکسی سیستم/محیط، اگه باشه)'}")
        if config.get("sales_bot_token"):
            ok, detail = _telegram_reachable()
            if ok:
                print(f"اتصال به تلگرام: وصل شد (@{detail})")
            else:
                problems.append(("تلگرام", f"به api.telegram.org وصل نشد: {detail}\n"
                                           "    اگه تلگرام فیلتره، پروکسی رو اینجا بنویس: "
                                           f'"proxy_url" توی {config.CONFIG_FILE}\n'
                                           "    (یا متغیر محیطی LICENSING_PROXY_URL)"))

    # پرداخت با تتر: خاموش بودنش خطا نیست، ولی «روشن ولی ناقص» (آدرس
    # نوشته نشده یا غلطه) باید همین‌جا معلوم بشه، نه وقتی که دکمه نمی‌آد.
    from licensing import crypto_pay
    crypto = config.crypto_settings()
    reason = crypto_pay.unavailable_reason(crypto)
    if reason is None:
        print(f"پرداخت با تتر: فعال ({crypto_pay.NETWORKS[crypto['network']].label})")
    elif reason == "disabled":
        print("پرداخت با تتر: خاموش (docs/CRYPTO_PAYMENTS.md)")
    else:
        problems.append(("پرداخت با تتر",
                         f"crypto.enabled روشنه ولی تنظیماتش کامل نیست ({reason}): "
                         f'بخش "crypto" توی {config.CONFIG_FILE} رو ببین.'))

    # لایسنس ابری: تنظیم نبودنش خطا نیست (صدور دستی همچنان کار می‌کنه)،
    # ولی «تنظیم شده ولی کار نمی‌کنه» باید همین‌جا معلوم بشه، نه وسط
    # صدور لایسنس برای یه مشتری.
    from licensing import cloudflare
    if cloudflare.available():
        ok, detail = cloudflare.check_connection()
        if ok:
            print(f"لایسنس ابری (Cloudflare KV): {detail}")
        else:
            problems.append(("Cloudflare", f"تنظیم شده ولی جواب نداد: {detail}"))
    else:
        print("لایسنس ابری: تنظیم نشده "
              f"({', '.join(cloudflare.missing_settings())}) — صدور از تلگرام خاموشه")

    # کاتالوگ با دیسک همگامه؟ ناهمگامی خطا نیست ولی بی‌صدا هم نباید بمونه:
    # هر سرویس/دستوری که توی کاتالوگ نباشه، روی ربات‌های لایسنس‌دار اصلاً
    # دیده نمی‌شه و هیچ ارور هم نمی‌ده.
    from licensing import sync as sync_module
    drift_text = sync_module.report_text()
    if drift_text:
        print("\n⚠️  کاتالوگ با دیسک همگام نیست:")
        for line in drift_text.splitlines():
            print(f"  - {line}")
        print("  رفعش: python license_server.py --sync")
    else:
        print("کاتالوگ: با سرویس‌ها و دستورهای روی دیسک همگامه")

    print()
    if problems:
        print(f"❌ {len(problems)} مشکل:")
        for area, problem in problems:
            print(f"  [{area}] {problem}")
        return 1

    print("✅ همه‌چیز آماده‌ست.")
    return 0


def cmd_sync():
    """
    کاتالوگ فروش رو با سرویس‌ها و دستورهای *واقعیِ* روی دیسک همگام می‌کنه.

    هرچی روی دیسک هست ولی توی کاتالوگ نیست، ثبت می‌شه تا روی ربات‌های
    لایسنس‌دار نامرئی نمونه. قیمتش پیش‌فرض می‌خوره و باید دستی تنظیم بشه --
    قیمت‌گذاری تصمیم تجاریه، نه فنی.
    """
    from licensing import sync as sync_module

    gaps = sync_module.drift()
    report = sync_module.report_text(gaps)
    if not report:
        print("✅ کاتالوگ از قبل همگام بود؛ چیزی عوض نشد.")
        return 0

    print("وضعیت فعلی:")
    for line in report.splitlines():
        print(f"  - {line}")

    created = sync_module.autoregister(persist=True)
    if created:
        print(f"\n✅ {len(created)} امکان خودکار ثبت شد: {', '.join(created)}")
        print(f"   قیمت پیش‌فرض ${sync_module.AUTO_PRICE_USD} خورده -- "
              f"توی {catalog.OVERRIDE_FILE} تنظیمش کن.")
    else:
        print("\nچیزی برای ثبت نبود.")

    if gaps["stale_services"] or gaps["stale_commands"]:
        print("\n⚠️  این‌ها توی کاتالوگن ولی روی دیسک نیستن و باید دستی "
              "از کاتالوگ حذف بشن (خودکار پاکشون نمی‌کنیم تا لایسنس‌های "
              "فروخته‌شده بی‌سروصدا نشکنن):")
        for name in gaps["stale_services"] + gaps["stale_commands"]:
            print(f"  - {name}")
    return 0


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])

    if "--init" in argv:
        return cmd_init()
    if "--check" in argv:
        return cmd_check()
    if "--sync" in argv:
        return cmd_sync()

    hosting = "--no-hosting" not in argv and bool(config.get("hosting_enabled", True))
    with_personal = "--no-personal" not in argv

    problems = config.missing_required()
    if problems:
        print("❌ پلتفرم راه نمی‌افته چون:")
        for problem in problems:
            print(f"  - {problem}")
        print("\nبرای ساخت فایل کانفیگ نمونه: python license_server.py --init")
        return 1

    try:
        from licensing.telegram import runner as runner_module
        from telegram import Update
        from licensing.telegram import sales_bot
    except ImportError as e:
        print(f"❌ python-telegram-bot نصب نیست ({e}).")
        print("   pip install 'python-telegram-bot>=20.7'")
        return 1

    database = db_module.get_db()

    # لایسنسِ خودِ مالک/ادمین همیشه همه‌ی امکاناتِ فعلیِ کاتالوگ رو داره.
    from licensing import provisioning
    try:
        synced = provisioning.sync_unlimited(database)
        if synced:
            print(f"لایسنس‌های نامحدود با کاتالوگ هم‌تراز شدن: {len(synced)}")
    except Exception:
        logging_setup.log_exception("syncing unlimited licences")

    print(f"محیط اجرا: {platform_paths.describe_runtime()}")
    for problem in platform_paths.missing_runtime_requirements():
        print(f"[هشدار] {problem}")

    bot_supervisor = None
    if hosting:
        bot_supervisor = supervisor_module.Supervisor(database)
        print("سوپروایزر ربات‌ها: فعال")
    else:
        print("سوپروایزر ربات‌ها: خاموش (--no-hosting)")

    bot_runner = None
    if with_personal:
        bot_runner = runner_module.BotRunner(database, bot_supervisor)
        print("ربات‌های شخصی مشتری‌ها: فعال")

    application = sales_bot.build_application(database, bot_supervisor, bot_runner)

    print("ربات فروش در حال اجراست. برای خروج Ctrl+C.")
    try:
        # بدون allowed_updates، تلگرام رویداد عضویت کانال (chat_member) رو
        # نمی‌فرسته و عضویت اجباری فقط از حلقه‌ی ساعتی باخبر می‌شد.
        application.run_polling(drop_pending_updates=True, close_loop=False,
                                timeout=config.poll_timeout(),
                                allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        print("\nدر حال بستن...")
    finally:
        if bot_supervisor is not None:
            bot_supervisor.shutdown()
        print("بسته شد.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

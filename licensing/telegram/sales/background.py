"""
تسک‌های پس‌زمینه: جاروی شبانه‌ی انقضا، منقضی‌کردن سفارش‌ها، به‌روزرسانی نرخ.
"""

import asyncio
import time

from core import logging_setup
from licensing import provisioning
from licensing import config
from licensing import cookie_alerts
from licensing import crypto_pay
from licensing import daily_report
from licensing import expiry
from licensing import i18n
from licensing import pricing
from licensing.telegram import texts as T
from licensing.telegram.sales.alerts import notify_cookie_alerts
from licensing.telegram.sales.common import _notify, _notify_admins
from licensing.telegram.sales.crypto_payment import crypto_check_pending
from licensing.telegram.sales.reports import send_daily_report


async def _run_sweep(application):
    """
    جاروی انقضا. پیام‌ها باید از حلقه‌ی asyncio فرستاده بشن، ولی خود جارو
    همگام و I/O سنگینه -- پس جارو توی ترد اجرا می‌شه و پیام‌ها بعدش صف
    می‌شن.
    """
    db = application.bot_data["db"]
    supervisor = application.bot_data.get("supervisor")
    pending_messages = []
    # امکاناتِ تازه‌ی کاتالوگ (بدونِ ری‌استارتِ سرور) هم شبانه به لایسنسِ
    # نامحدودِ مالک/ادمین برسن.
    try:
        await asyncio.to_thread(provisioning.sync_unlimited, db)
    except Exception:
        logging_setup.log_exception("nightly unlimited-licence sync")

    def collect(user_id, text):
        pending_messages.append((user_id, text))

    result = await asyncio.to_thread(expiry.run_sweep, db, supervisor, collect)

    for user_id, text in pending_messages:
        await _notify(application, user_id, text)

    if not result.is_empty():
        await _notify_admins(application, T.sweep_report(result))
    return result


async def _nightly_loop(application):
    """
    هر شب ساعت مقرر جارو می‌زنه. محاسبه‌ی «چند ثانیه تا دفعه‌ی بعد» هر دور
    دوباره انجام می‌شه، پس تغییر ساعت تابستانی یا ری‌استارت وسط شب مشکلی
    نمی‌سازه.
    """
    while True:
        delay = expiry.seconds_until_next_run()
        logging_setup.log_debug(f"nightly license sweep in {delay}s")
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        try:
            await _run_sweep(application)
        except Exception:
            logging_setup.log_exception("nightly sweep")


async def _daily_report_loop(application):
    """
    هر روز ساعتِ تنظیم‌شده (daily_report_hour، پیش‌فرض ۹ صبح به وقت محلی
    سرور) گزارش رو برای ادمین‌ها می‌فرسته. زمان‌بندی همون محاسبه‌ی جاروی
    شبانه‌ست (expiry.seconds_until_next_run) با ساعتِ خودش؛ هر دور دوباره
    حساب می‌شه و ساعتِ کانفیگ هم با reload عوض می‌شه.
    """
    while True:
        delay = expiry.seconds_until_next_run(hour=daily_report.report_hour(), minute=0)
        logging_setup.log_debug(f"daily report in {delay}s")
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        try:
            if daily_report.enabled():
                await send_daily_report(application)
        except Exception:
            logging_setup.log_exception("daily report")
        # اگه ساعتِ سیستم چند میلی‌ثانیه عقب بوده باشه، delay بعدی ۱ ثانیه
        # درمیاد و گزارش دوباره می‌رفت؛ یه دقیقه مکث این رو خنثی می‌کنه.
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            return


async def _cookie_alert_loop(application):
    """
    هر چند دقیقه یه‌بار می‌بینه رباتی به بات‌چکِ یوتیوب خورده یا نه و به
    مالک و ادمین‌ها خبر می‌ده. اگه supervisor ربات نداره، هیچ فایلی
    خونده نمی‌شه (cookie_alerts.pending).
    """
    while True:
        try:
            await asyncio.sleep(cookie_alerts.SCAN_SECONDS)
        except asyncio.CancelledError:
            return
        try:
            await notify_cookie_alerts(application)
        except Exception:
            logging_setup.log_exception("cookie alert loop")


async def _order_timeout_loop(application):
    """
    سفارش‌هایی که رسیدشون نیومده رو منقضی می‌کنه. بدون این، لیست «در
    انتظار» ادمین پر می‌شه از سفارش‌های رهاشده.
    """
    db = application.bot_data["db"]
    while True:
        try:
            await asyncio.sleep(600)
        except asyncio.CancelledError:
            return
        try:
            timeout = int(config.get("order_timeout_minutes", 180)) * 60
            cutoff = int(time.time()) - timeout
            for order in db.orders_by_status("awaiting_receipt", limit=200):
                if int(order["created_at"]) > cutoff:
                    continue
                db.update_order(int(order["id"]), status="expired")
                db.log_event("order_expired", user_id=int(order["user_id"]),
                             order_id=int(order["id"]))
                await _notify(application, int(order["user_id"]), T.ORDER_EXPIRED)
        except Exception:
            logging_setup.log_exception("order timeout loop")


async def _crypto_poll_loop(application):
    """
    پرداخت‌های تتریِ در انتظار رو هر چند ثانیه با بلاک‌چین تطبیق می‌ده.
    وقتی هیچ پرداختی در انتظار نیست اصلاً به شبکه وصل نمی‌شه (فقط یه
    SELECT ارزون)، پس مصرفی نداره مگه وقتی واقعاً کسی داره پرداخت می‌کنه.
    """
    db = application.bot_data["db"]
    while True:
        try:
            await asyncio.sleep(crypto_pay.POLL_SECONDS)
        except asyncio.CancelledError:
            return
        try:
            if db.pending_crypto_payments():
                await crypto_check_pending(application)
        except Exception:
            logging_setup.log_exception("crypto poll loop")


async def _rate_refresh_loop(application):
    """
    نرخ دلار رو هر چند ساعت به‌روز می‌کنه. اگه نشد، نرخ کش‌شده‌ی قبلی سر
    جاش می‌مونه (fallback توی pricing.current_rate).
    """
    db = application.bot_data["db"]
    while True:
        try:
            state = await asyncio.to_thread(pricing.refresh_rate, db)
            if state.get("error") and not state.get("rate"):
                await _notify_admins(
                    application,
                    i18n.t("rate_fetch_failed_admin", error=T.esc(state["error"])))
        except Exception:
            logging_setup.log_exception("rate refresh loop")
        try:
            await asyncio.sleep(4 * 3600)
        except asyncio.CancelledError:
            return

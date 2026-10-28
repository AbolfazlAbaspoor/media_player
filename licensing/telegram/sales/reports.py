"""
گزارش روزانه‌ی ادمین‌ها: ارسالِ صبحگاهی به همه‌ی ادمین‌ها و دکمه‌ی «📊 گزارش
همین الان» توی پنل ادمین. هر دو از یه منبع (licensing/daily_report.py) و یه
قالبِ متن (texts.daily_report) می‌خونن.
"""

import asyncio

from licensing import daily_report
from licensing.telegram import keyboards as kb
from licensing.telegram import texts as T
from licensing.telegram.sales.common import (
    _db,
    _is_admin,
    _notify_admins_localized,
    _send,
    _supervisor,
)


async def _collect_report(db, supervisor):
    # جمع‌آوری همگام و I/O دارد (دیتابیس + خوندنِ errors.log)، پس توی ترد.
    return await asyncio.to_thread(daily_report.collect, db, supervisor)


async def send_daily_report(application):
    """گزارش رو برای هر ادمین به زبانِ خودش می‌فرسته؛ تعداد پیام‌های رسیده."""
    data = await _collect_report(application.bot_data["db"],
                                 application.bot_data.get("supervisor"))
    return await _notify_admins_localized(
        application, lambda: (T.daily_report(data), None))


async def admin_report_now(update, context):
    """دکمه‌ی «📊 گزارش همین الان» (adm:report): همون گزارش، فقط برای همین ادمین."""
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    data = await _collect_report(_db(context), _supervisor(context))
    await _send(update, T.daily_report(data), kb.admin_back())

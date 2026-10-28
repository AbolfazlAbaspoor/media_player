"""
هشدارِ «ربات کوکیِ یوتیوب می‌خواد»: پیام به مالکِ لایسنس (با دکمه‌ی مستقیم به
🍪 کوکی‌های همون ربات) و به همه‌ی ادمین‌ها. کشفِ هشدار و «رسیدگی‌شده» بودنش
توی licensing/cookie_alerts.py است؛ این‌جا فقط پیام فرستاده می‌شه.

مالکی که خودش ادمینه فقط پیامِ ادمین رو می‌گیره (دو پیامِ تکراری نمی‌گیره)؛
پیامِ ادمین هم همون دکمه رو داره و ادمین از ck:menu به هر رباتی دسترسی داره.
"""

import asyncio
import time

from licensing import config
from licensing import cookie_alerts
from licensing import i18n
from licensing.telegram import keyboards as kb
from licensing.telegram import texts as T
from licensing.telegram.sales.common import (
    _notify,
    _notify_admins_localized,
    _set_user_language,
)


async def notify_cookie_alerts(application):
    """اسکنِ یک‌باره؛ تعداد هشدارهای تازه‌ای که پیام‌شون تلاش شد."""
    db = application.bot_data["db"]
    supervisor = application.bot_data.get("supervisor")
    alerts = await asyncio.to_thread(cookie_alerts.pending, db, supervisor, time.time())
    for alert in alerts:
        slug = T.esc(alert.instance["slug"])
        instance_id = int(alert.instance["id"])
        owner_id = int(alert.license["user_id"])
        delivered = 0

        if owner_id not in config.admin_ids():
            _set_user_language(db, owner_id)
            delivered += await _notify(
                application, owner_id, i18n.t("cookie_alert_owner", slug=slug),
                kb.cookie_alert_actions(instance_id))

        delivered += await _notify_admins_localized(
            application,
            lambda: (i18n.t("cookie_alert_admin", slug=slug, key=T.esc(alert.license["key"]),
                            owner=owner_id),
                     kb.cookie_alert_actions(instance_id)))
        await asyncio.to_thread(cookie_alerts.settle, db, alert, delivered > 0, time.time())
    return len(alerts)

"""
هشدارِ «این ربات کوکیِ یوتیوب می‌خواد» از سمتِ license_server.

رباتی که به بات‌چکِ یوتیوب می‌خوره یه سیگنال توی پوشه‌ی خودش می‌نویسه
(core/bot_alerts.py). این‌جا هر چند دقیقه پوشه‌ی ربات‌های تحتِ نظارتِ
supervisor رو نگاه می‌کنیم؛ ارسالِ پیام کارِ ربات فروشه
(licensing/telegram/sales/alerts.py).

## «رسیدگی‌شده» کجا نگه داشته می‌شه

توی جدول settings، نه توی alerts.json: فایل رو ربات می‌نویسه و اگه سرور هم
توش می‌نوشت، دو پروسه روی هم می‌نوشتن و یه هشدارِ تازه گم می‌شد. به ازای هر
نمونه یه ردیف:  {"seen": زمانِ آخرین هشدارِ دیده‌شده, "notified": زمانِ آخرین پیام}.

## محدودیت: ربات‌های اجاره‌ای

رباتی که روی ماشینِ خودِ مشتری اجرا می‌شه (لایسنس اجاره‌ای) همین فایل رو
روی دیسکِ خودش می‌نویسه و سرور هیچ راهی به اون دیسک نداره؛ اون‌ها
نمونه‌ی supervisor نیستن و هشدار نمی‌گیرن. عمداً تلاشی برای رسیدن بهشون
نمی‌کنیم.
"""

import json
import os
from collections import namedtuple

from core import bot_alerts
from licensing import provisioning

SCAN_SECONDS = 600
#: به یه ربات بیشتر از هر ۲۴ ساعت یک‌بار پیام نمی‌دیم، حتی اگه مشکل
#: ادامه داشته باشه و ربات هر ۶ ساعت هشدار بنویسه.
RENOTIFY_SECONDS = 24 * 3600
#: اگه هیچ پیامی نرسید (مثلاً قطعیِ پروکسی)، اسکنِ بعدی دوباره تلاش می‌کنه؛
#: ولی نه برای همیشه.
RETRY_SECONDS = 24 * 3600

Alert = namedtuple("Alert", "instance license ts")


def _state_key(instance_id):
    return f"ytcookie_alert_{int(instance_id)}"


def _state(db, instance_id):
    try:
        state = json.loads(db.get_setting(_state_key(instance_id)) or "{}")
    except ValueError:
        state = {}
    return state if isinstance(state, dict) else {}


def _save_state(db, instance_id, **fields):
    state = _state(db, instance_id)
    state.update(fields)
    db.set_setting(_state_key(instance_id), json.dumps(state))


def pending(db, supervisor, now):
    """
    هشدارهای تازه‌ای که باید اطلاع داده بشن. اگه supervisor چیزی اجرا
    نمی‌کنه هیچ فایلی خونده نمی‌شه. هشداری که توی بازه‌ی RENOTIFY بعد از
    پیامِ قبلیه بی‌صدا «دیده‌شده» حساب می‌شه.
    """
    if supervisor is None or not supervisor.status():
        return []
    found = []
    for instance in db.runnable_instances():
        bot_dir = provisioning.instance_dirs(instance)[1]
        if not os.path.isfile(bot_alerts.alerts_path(bot_dir)):
            continue
        try:
            ts = int(float(bot_alerts.read(bot_dir).get(bot_alerts.YOUTUBE_COOKIE_KEY) or 0))
        except (TypeError, ValueError):
            continue
        state = _state(db, instance["id"])
        if ts <= int(state.get("seen") or 0):
            continue
        if now - int(state.get("notified") or 0) < RENOTIFY_SECONDS:
            _save_state(db, instance["id"], seen=ts)
            continue
        license_row = db.get_license(int(instance["license_id"]))
        if license_row is not None:
            found.append(Alert(instance, license_row, ts))
    return found


def settle(db, alert, delivered, now):
    """
    بعد از تلاشِ ارسال: اگه حداقل یه پیام رسید (یا هشدار دیگه خیلی کهنه‌ست)
    «رسیدگی‌شده» ثبت می‌شه و تکرار نمی‌شه؛ وگرنه اسکنِ بعدی دوباره تلاش می‌کنه.
    """
    if delivered:
        _save_state(db, alert.instance["id"], seen=alert.ts, notified=int(now))
    elif now - alert.ts >= RETRY_SECONDS:
        _save_state(db, alert.instance["id"], seen=alert.ts)

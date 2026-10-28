"""
پخش مستند با شماره.

    md          -> اولین مستند (پیش‌فرض ۷)
    md 11       -> مستند ۱۱

بعد از پخش، ربات توی «حالت مستند» می‌مونه: فرستادن یه عدد خام (مثلاً 22)
یعنی همون مستند پخش بشه. این حالت با پخش هر چیز دیگه‌ای خودکار بسته می‌شه.

منطق اصلی توی core/documentary.py است، چون مسیر «عدد خام» توی bot.py هم
از همون استفاده می‌کنه و نباید دو نسخه از این قاعده وجود داشته باشه.
"""

from core import documentary
from core import i18n
from core import logging_setup

NAME = ("md", "mostanad")
USAGE = "md [number]  (play documentary; no number = first documentary)"


def run(ctx):
    bot, uid = ctx["bot"], ctx["uid"]
    args = ctx.get("args") or []

    if args:
        raw = args[0].strip()
        # اعداد فارسی/عربی هم قبول می‌شن، چون کاربر ممکنه با کیبورد فارسی بنویسه.
        normalized = raw.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
        if not normalized.isdigit():
            bot.t.user_message(
                uid, i18n.t("documentary_number_required", example=documentary.min_number(bot)))
            return
        number = int(normalized)
    else:
        number = documentary.min_number(bot)

    logging_setup.set_operation(f"playing documentary {number} (requested by {ctx['username']})")
    try:
        item = documentary.play(bot, number, requested_by=ctx.get("username"))
    except documentary.DocumentaryError as e:
        bot.t.user_message(uid, str(e))
        return
    except Exception as e:
        bot.t.user_message(uid, i18n.t(
            "documentary_play_failed", number=number, error=logging_setup.safe_error_text(e)))
        return
    finally:
        logging_setup.set_operation("idle")

    # پیامِ زبانِ ربات، بدون هیچ راهنماییِ اضافه («از این به بعد فقط عدد
    # بفرست») -- رفتارِ عدد خام سرجاشه، فقط دیگه هر بار یادآوری نمی‌شه.
    documentary.announce_playing(bot, item, ctx["nickname"])

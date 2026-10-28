"""
تست سلامت ربات، از داخل خود تیم‌تاک.

    dg        -> فقط مشکل‌ها (گزارش کوتاه)
    dg all    -> همه‌ی نتایج
    dg boot   -> گزارش لحظه‌ی راه‌اندازی (بدون تست دوباره)

چرا لازمه: وقتی کاربر می‌گه «صدا نمیاد»، جواب‌دادن نیاز به دیدن وضعیت
*همین لحظه*ی دستگاه‌ها داره، نه حدس‌زدن. این دستور همون تستی رو اجرا
می‌کنه که موقع استارت اجرا شده، روی همون پلیر و اتصال زنده.

نقش admin_bot می‌خواد چون اسم دستگاه‌ها و مسیرهای سرور رو نشون می‌ده.
"""

from core import i18n, selftest

NAME = ("dg", "diag")
REQUIRED_ROLE = "admin_bot"
USAGE = "dg [all|boot]  (تست سلامت: صدا، دستگاه‌ها، لاین، سرویس‌ها، لایسنس)"


def run(ctx):
    bot, uid = ctx["bot"], ctx["uid"]
    args = [a.lower() for a in (ctx.get("args") or [])]
    mode = args[0] if args else ""

    send = lambda text: bot.send_long_text(lambda chunk: bot.t.user_message(uid, chunk), text)

    if mode == "boot":
        report = getattr(bot, "selftest_report", None)
        if report is None:
            bot.t.user_message(uid, i18n.t("dg_no_boot_report"))
            return
        send(i18n.t("dg_boot_title", report=report.text(), summary=report.summary()))
        return

    show_all = mode in ("all", "همه", "full")

    # تُن تست عمداً پخش نمی‌شه: ربات ممکنه همین الان وسط پخش باشه و یه
    # قطع ۰.۳ ثانیه‌ای برای شنونده‌ها آزاردهنده‌ست. باز شدن دستگاه موقع
    # استارت یک بار تست شده.
    report = selftest.run(bot=bot, player=bot.player, tt=bot.t, play_tone=False)

    text = report.text(only_problems=not show_all)
    if not text:
        text = i18n.t("dg_no_problems")
    send(i18n.t("dg_title", report=text, summary=report.summary())
         + ("" if show_all else "\n" + i18n.t("dg_see_all_hint")))

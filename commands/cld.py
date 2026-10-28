"""
پخشِ زنده‌ی کانالِ فعلی با قابلیتِ برگشت به عقب (DVR).

    cld            پخش از لبه‌ی لایو، با بافرِ عقبِ پیش‌فرض (live_dvr.default_back_minutes)
    cld 30         پخش از لبه‌ی لایو، با امکانِ سیک تا ۳۰ دقیقه عقب

مثلِ cl، اگه کانالِ چیزی که الان پخش می‌شه *همین لحظه* لایو داره پخشش
می‌کنه -- ولی به‌جای دادنِ مستقیمِ لینکِ HLS به mpv (که فقط چند ثانیه‌ی
آخر رو seekable می‌کنه)، یه دانلودِ پس‌زمینه از ابتدای پخش شروع می‌کنه
(core/live_dvr.py؛ v2: فقط `minutes` دقیقه‌ی آخر رو اول می‌گیره، نه از اولِ برودکست) تا بشه با دستورهای معمولیِ +/- به عقب سیک کرد.

قابلیتِ لایسنسِ جداست (cap_live_dvr، نه cap_channel_live) چون تا وقتی
فعاله یه دانلودِ پیوسته روی سرورِ ربات باز نگه می‌داره -- مصرفِ منابعش
از cl معمولی بیشتره، برای همین جدا و گران‌تر قیمت‌گذاری شده.
"""

from core import command_helpers
from core import i18n
from core import live_dvr
from core import logging_setup

NAME = "cld"
ADMIN_ONLY = False
USAGE = "cld [minutes]  (play the current channel's live stream from the live edge, able to seek back up to [minutes] with -; if it is live now)"


def run(ctx):
    bot = ctx["bot"]
    name, service = bot.require_channel_service(ctx)
    if not service:
        return
    if not hasattr(service, "get_channel_live"):
        bot.t.user_message(ctx["uid"], i18n.t("channel_not_supported", service=name))
        return
    if not live_dvr.licensed(bot):
        bot.t.user_message(ctx["uid"], i18n.t("live_dvr_not_licensed"))
        return

    args = ctx.get("args") or []
    back_minutes = None
    if args:
        limit = live_dvr.max_back_minutes(bot)
        try:
            back_minutes = int(str(args[0]).strip())
        except ValueError:
            back_minutes = 0
        if back_minutes < 1 or back_minutes > limit:
            bot.t.user_message(ctx["uid"], i18n.t("live_dvr_bad_minutes", max=limit))
            return

    bot.channel_broadcast(i18n.t("channel_live_checking", nickname=ctx["nickname"]))
    try:
        result = live_dvr.start(bot, service, bot.last_channel_url, requested_by=ctx["username"],
                              back_minutes=back_minutes)
    except live_dvr.LiveDVRError as e:
        bot.t.user_message(ctx["uid"], str(e))
        return
    except Exception as e:
        bot.t.user_message(ctx["uid"], i18n.t("command_error", error=logging_setup.safe_error_text(e)))
        return

    if result is None:
        # «زنده نیست» یه خطا نیست، یه جوابه -- همون پیامِ cl.
        command_helpers.notify(bot, ctx, "channel_not_live")
        return

    bot.channel_broadcast(i18n.t("live_dvr_playing_back", title=result["title"], nickname=ctx["nickname"],
                                          minutes=result.get("back_minutes", 0)))

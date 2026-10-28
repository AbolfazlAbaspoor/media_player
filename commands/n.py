"""
آیتم بعدی.

## چرا این فایل حالا این‌قدر کوتاهه

نسخه‌ی قبلی ۱۳۰ خط بود و بیشترش حدس‌زدن: «آیا به آخر صف نزدیکیم؟»، «آیا
رشدی در جریانه؟»، و یه حلقه‌ی sleep تا ۴ ثانیه‌ای به امید این‌که پس‌زمینه
آیتم اضافه کنه. دلیلش این بود که صف، پلی‌لیست داخلی mpv بود و این فایل
هیچ راهی نداشت بفهمه واقعاً چند آیتم مونده.

حالا صف مال خودمونه (core/trackqueue.py):

  * `advance()` فوری و قطعیه و هیچ‌وقت بلاک نمی‌کنه.
  * آیتم بعدی از قبل resolve شده (prefetch)، پس پخش بی‌تأخیر شروع می‌شه.
  * رشد صف خودکار و بر اساس شمارش واقعیه، نه حدس -- و خودِ صف انجامش می‌ده.

پس این فایل فقط یه کار داره: کرسر رو جلو ببر و نتیجه رو بگو.
"""

from core import i18n, logging_setup, command_helpers

NAME = 'n'
ADMIN_ONLY = False
USAGE = 'n'


def run(ctx):
    bot, username, uid = ctx["bot"], ctx["username"], ctx["uid"]

    # حالت مستند: n/b یعنی مستند بعدی/قبلی، نه حرکت توی صف (هر مستند
    # تک‌آیتمی پخش می‌شه، پس مسیر صف همیشه به «آخر صف» می‌خورد).
    from core import documentary
    if documentary.is_active(bot):
        try:
            item = documentary.step(bot, +1)
        except documentary.DocumentaryError as e:
            bot.t.user_message(uid, str(e))
            return
        except Exception as e:
            bot.t.user_message(uid, i18n.t(
                "command_error", error=logging_setup.safe_error_text(e, context="n: documentary step")))
            return
        if item is None:
            command_helpers.notify(bot, ctx, "documentary_last")
            return
        documentary.announce_playing(bot, item, ctx["nickname"])
        return

    # حالت تلویزیون (IPTV): n یعنی کانال بعدی توی همون لیستِ آخر -- core/iptv.py.
    from core import iptv
    if iptv.step_command(bot, ctx, +1):
        return

    if bot.queue.length < 1:
        bot.t.user_message(uid, i18n.t("queue_empty"))
        return

    try:
        # force=True: n یعنی «کاربر صریحاً بعدی رو خواست»، حتی توی حالتِ
        # تکرارِ آهنگ (m 3) -- اون مُد فقط رفتارِ خودکارِ پایانِ طبیعیِ
        # آهنگ رو تعیین می‌کنه، نه معنیِ n رو.
        advanced, _track = bot.queue.advance(force=True)
    except Exception as e:
        bot.t.user_message(uid, i18n.t(
            "command_error", error=logging_setup.safe_error_text(e, context="n: advance")))
        return

    if advanced:
        bot.track_meta = bot.queue.meta()
        command_helpers.broadcast_now_playing(bot)
        return

    # به آخر رسیدیم. advance خودش رشد رو راه انداخته، پس به‌جای بلاک کردن
    # چند ثانیه‌ای (کاری که نسخه‌ی قبلی می‌کرد) فقط می‌گیم در حال گرفتنه و
    # کاربر می‌تونه یه لحظه بعد دوباره n بزنه.
    if bot.queue.is_growing():
        bot.t.user_message(uid, i18n.t("queue_loading_more"))
        return

    with bot.search_lock:
        has_query = bool(bot.search_session.get("query"))
    if has_query:
        command_helpers.notify(bot, ctx, "search_ended", nickname=ctx["nickname"])
    else:
        command_helpers.notify(bot, ctx, "queue_end")

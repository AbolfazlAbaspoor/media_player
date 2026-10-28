"""
آیتم قبلی.

مثل n، فقط کرسر صف رو عقب می‌بره (core/trackqueue.py). آیتم‌های قبلی از
قبل resolve شدن، پس برگشت عقب همیشه فوریه.
"""

from core import i18n, logging_setup, command_helpers

NAME = 'b'
ADMIN_ONLY = False
USAGE = 'b'


def run(ctx):
    bot, uid = ctx["bot"], ctx["uid"]

    if bot.queue.length < 1:
        bot.t.user_message(uid, i18n.t("queue_empty"))
        return

    # حالت مستند: n/b یعنی مستند بعدی/قبلی، نه حرکت توی صف (هر مستند
    # تک‌آیتمی پخش می‌شه، پس مسیر صف همیشه به «آخر صف» می‌خورد).
    from core import documentary
    if documentary.is_active(bot):
        try:
            item = documentary.step(bot, -1)
        except documentary.DocumentaryError as e:
            bot.t.user_message(uid, str(e))
            return
        except Exception as e:
            bot.t.user_message(uid, i18n.t(
                "command_error", error=logging_setup.safe_error_text(e, context="b: documentary step")))
            return
        if item is None:
            command_helpers.notify(bot, ctx, "documentary_first")
            return
        documentary.announce_playing(bot, item, ctx["nickname"])
        return

    # حالت تلویزیون (IPTV): b یعنی کانال قبلی توی همون لیستِ آخر -- core/iptv.py.
    from core import iptv
    if iptv.step_command(bot, ctx, -1):
        return

    try:
        moved, _track = bot.queue.retreat()
    except Exception as e:
        bot.t.user_message(uid, i18n.t(
            "command_error", error=logging_setup.safe_error_text(e, context="b: retreat")))
        return

    if moved:
        bot.track_meta = bot.queue.meta()
        command_helpers.broadcast_now_playing(bot)
    else:
        # برخلافِ «آخرِ صف»ِ n (که به بقیه‌ی کانال هم مربوطه: یعنی وقتِ
        # سرچِ تازه‌ست)، «اولِ صف»ِ b یه مرزِ کاملاً شخصیه -- فقط خودِ
        # درخواست‌کننده لازمه بدونه، پس خصوصی می‌ره نه به کل کانال.
        bot.t.user_message(uid, i18n.t("queue_start"))

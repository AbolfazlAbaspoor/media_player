"""
تایمر خواب: بعد از N دقیقه پخش رو خودکار متوقف می‌کنه.
    st <minutes>   -> تنظیم/جایگزینی تایمر
    st 0           -> لغو تایمر فعال
    st             -> نمایش زمان باقی‌مونده
"""

import time

from core import i18n
from core import scheduler

NAME = 'st'
ADMIN_ONLY = False
USAGE = 'st [minutes]  (0 = cancel, no arg = show remaining)'


def _cancel_existing(bot):
    if bot._sleep_timer_task_id is not None:
        scheduler.cancel(bot._sleep_timer_task_id)
        bot._sleep_timer_task_id = None
        bot._sleep_timer_deadline = None


def _fire(bot):
    bot._sleep_timer_task_id = None
    bot._sleep_timer_deadline = None
    if bot.player.current_url is not None:
        bot.stop_player()
        bot.channel_broadcast(i18n.t('sleep_timer_fired'))


def run(ctx):
    bot = ctx["bot"]
    args = ctx['args']

    if not args:
        deadline = bot._sleep_timer_deadline
        if not deadline:
            bot.t.user_message(ctx['uid'], i18n.t('sleep_timer_status_off'))
            return
        remaining = max(0, int(deadline - time.time()))
        bot.t.user_message(ctx['uid'], i18n.t('sleep_timer_status_on', time=bot.format_time(remaining)))
        return

    if not args[0].isdigit():
        bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands['st']['usage']))
        return

    minutes = int(args[0])
    _cancel_existing(bot)

    if minutes <= 0:
        bot.channel_broadcast(i18n.t('sleep_timer_cancelled', nickname=ctx['nickname']))
        return

    bot._sleep_timer_task_id = scheduler.schedule(minutes * 60, _fire, bot)
    bot._sleep_timer_deadline = time.time() + minutes * 60
    bot.channel_broadcast(i18n.t('sleep_timer_set', nickname=ctx['nickname'], minutes=minutes))

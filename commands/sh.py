"""
به‌هم‌ریختن صف.

آیتم در حال پخش سر جاش می‌مونه و فقط بقیه به‌هم می‌ریزن -- وگرنه shuffle
وسط یه آهنگ، آهنگ رو عوض می‌کرد که رفتار غافلگیرکننده‌ایه.
"""

from core import i18n

NAME = 'sh'
ADMIN_ONLY = False
USAGE = 'sh  (shuffle the current playlist)'


def run(ctx):
    bot, uid = ctx["bot"], ctx["uid"]

    if bot.queue.length < 2:
        bot.t.user_message(uid, i18n.t('nothing_to_shuffle'))
        return

    if not bot.queue.shuffle():
        bot.t.user_message(uid, i18n.t('nothing_to_shuffle'))
        return

    bot.track_meta = bot.queue.meta()
    bot.channel_broadcast(i18n.t('playlist_shuffled', nickname=ctx['nickname']))

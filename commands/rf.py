"""
حذف از فروریت شخصی.
    rf            -> حذف آهنگِ در حال پخش (اگه توی فروریت باشه)
    rf <number>   -> حذف آیتم شماره‌ی N (شماره‌ها همون ترتیب sfl هستن)
"""

from core import command_helpers, i18n
from core import accounts

NAME = 'rf'
ADMIN_ONLY = False
USAGE = 'rf [number]  (remove from your favorites; no number = current track)'


def run(ctx):
    bot = ctx["bot"]
    args = ctx['args']

    if args:
        if not args[0].isdigit():
            bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands['rf']['usage']))
            return
        status = accounts.remove_favorite_by_index(bot, ctx['username'], int(args[0]) - 1)
    else:
        meta = command_helpers.current_track_meta(bot, ctx)
        if meta is None:
            return
        public_url = meta.get('public_url')
        if not public_url:
            bot.t.user_message(ctx['uid'], i18n.t('link_private'))
            return
        status = accounts.remove_favorite_by_url(bot, ctx['username'], public_url)

    if status == "not_logged_in":
        bot.t.user_message(ctx['uid'], i18n.t('sf_not_logged_in'))
    elif status == "invalid_index":
        bot.t.user_message(ctx['uid'], i18n.t('invalid_playlist_number'))
    elif status == "not_found":
        bot.t.user_message(ctx['uid'], i18n.t('sf_not_in_favorites'))
    else:
        bot.t.user_message(ctx['uid'], i18n.t('sf_removed'))

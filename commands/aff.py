"""مثل af، ولی همیشه از زمان صفر ذخیره می‌شه (نقطه‌ی resume قبلی، اگه بود، پاک می‌شه)."""

from core import command_helpers, i18n
from core import accounts

NAME = 'aff'
ADMIN_ONLY = False
USAGE = 'aff  (add/reset current track in your favorites, starting from 0)'


def run(ctx):
    bot = ctx["bot"]
    meta = command_helpers.current_shareable_meta(bot, ctx)
    if meta is None:
        return

    status = accounts.upsert_favorite(bot, ctx['username'], meta['public_url'], meta.get('title'), 0)

    if status == "not_logged_in":
        bot.t.user_message(ctx['uid'], i18n.t('sf_not_logged_in'))
    elif status == "added":
        bot.t.user_message(ctx['uid'], i18n.t('sf_added'))
    else:
        bot.t.user_message(ctx['uid'], i18n.t('sf_reset_to_zero'))

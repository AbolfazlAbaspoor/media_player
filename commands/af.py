"""
اضافه‌کردن آهنگ در حال پخش به فروریت شخصی؛ اگه از قبل توش بود، فقط
موقعیت فعلی پخش به‌عنوان نقطه‌ی ادامه (resume) ذخیره می‌شه. برای همیشه از
صفر شروع‌کردن، به‌جاش از aff استفاده کن.
"""

from core import command_helpers, i18n
from core import accounts

NAME = 'af'
ADMIN_ONLY = False
USAGE = 'af  (add current track to your favorites, or save resume position)'


def run(ctx):
    bot = ctx["bot"]
    meta = command_helpers.current_shareable_meta(bot, ctx)
    if meta is None:
        return

    position = int(bot.player.position_seconds or 0)
    status = accounts.upsert_favorite(bot, ctx['username'], meta['public_url'], meta.get('title'), position)

    if status == "not_logged_in":
        bot.t.user_message(ctx['uid'], i18n.t('sf_not_logged_in'))
    elif status == "added":
        bot.t.user_message(ctx['uid'], i18n.t('sf_added'))
    else:
        bot.t.user_message(ctx['uid'], i18n.t('sf_time_updated', time=bot.format_time(position)))

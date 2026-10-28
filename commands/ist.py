"""استوری‌های فعالِ یه پروفایل (فقط ویدیوها، فقط صدا). خصوصی‌ها فقط اگه
اکانتِ وصل‌شده‌ت فالوشون کرده باشه."""
from core import i18n, instagram_api, instagram_bot

NAME = 'ist'
ADMIN_ONLY = False
USAGE = 'ist <username>  (active stories of a profile, audio only)'


def run(ctx):
    name = instagram_bot.username_arg(ctx, USAGE)
    if not name:
        return
    instagram_bot.run_browse(ctx, lambda client: instagram_api.fetch_user_stories(client, name),
                             i18n.t('ig_what_stories', username=name))

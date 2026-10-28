"""پست‌هایی که اکانتِ وصل‌شده لایک کرده (فقط ویدیوها، فقط صدا)."""
from core import i18n, instagram_api, instagram_bot

NAME = 'ilk'
ADMIN_ONLY = False
USAGE = 'ilk  (videos you liked on Instagram, audio only)'


def run(ctx):
    instagram_bot.run_browse(ctx, instagram_api.fetch_liked, i18n.t('ig_what_liked'))

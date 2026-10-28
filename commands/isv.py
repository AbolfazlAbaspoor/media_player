"""پست‌های ذخیره‌شده‌ی (Saved) اکانتِ وصل‌شده (فقط ویدیوها، فقط صدا)."""
from core import i18n, instagram_api, instagram_bot

NAME = 'isv'
ADMIN_ONLY = False
USAGE = 'isv  (your saved Instagram videos, audio only)'


def run(ctx):
    instagram_bot.run_browse(ctx, instagram_api.fetch_saved, i18n.t('ig_what_saved'))

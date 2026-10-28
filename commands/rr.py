"""ریلزِ فید رو دوباره از اینستاگرام می‌گیره (تازه‌سازیِ rl)."""
from core import i18n, instagram_api, instagram_bot

NAME = 'rr'
ADMIN_ONLY = False
USAGE = 'rr'


def run(ctx):
    instagram_bot.run_browse(ctx, instagram_api.fetch_feed_reels, i18n.t('ig_what_feed'))

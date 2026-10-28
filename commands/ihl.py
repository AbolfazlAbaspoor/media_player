"""ویدیوهای چند هایلایتِ اولِ یه پروفایل (فقط صدا)."""
from core import i18n, instagram_api, instagram_bot

NAME = 'ihl'
ADMIN_ONLY = False
USAGE = 'ihl <username>  (highlight videos of a profile, audio only)'


def run(ctx):
    name = instagram_bot.username_arg(ctx, USAGE)
    if not name:
        return
    instagram_bot.run_browse(ctx, lambda client: instagram_api.fetch_user_highlights(client, name),
                             i18n.t('ig_what_highlights', username=name))
